#!/usr/bin/env python3
"""
Business State Update Script

Monitors and updates Business State for active companies in FIL_SU_LONG_LIST database.

Features:
- Fetches all companies where Active Flag is 'Active'
- Syncs Business State with status_buffer when they differ
- Updates business_state_log with change history
- Applies orange+bold styling to recently updated Business States
- Resets styling for Business States older than 2 weeks
- Records update timestamps in business_status_update_day

Uses the HTTP request interface because DatabasesEndpoint.query is not available in notion-client 2.7.0.
"""

import os
import json
from pathlib import Path
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
from notion_client import Client
from automation.execution_logger import LogCapture, save_execution_log


def notion_database_query(api_token: str, database_id: str, start_cursor=None):
    """
    Perform a database query via HTTPS.
    Required because DatabasesEndpoint.query is not available in notion-client 2.7.0.
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    body = {
        "page_size": 100,
    }
    if start_cursor:
        body["start_cursor"] = start_cursor

    resp = requests.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_all_pages(api_token: str, database_id: str):
    """Fetch all pages from a database with pagination."""
    all_results = []
    has_more = True
    start_cursor = None

    while has_more:
        response = notion_database_query(api_token, database_id, start_cursor=start_cursor)
        all_results.extend(response['results'])
        has_more = response.get('has_more', False)
        start_cursor = response.get('next_cursor')

    return all_results


def get_company_name(page):
    """
    Extract company name from a page.
    For SU Long List: '名前' (title)
    """
    properties = page['properties']

    # Find the title property
    for prop_name, prop_value in properties.items():
        if prop_value.get('type') == 'title':
            title_data = prop_value.get('title', [])
            if title_data:
                return ''.join([t['plain_text'] for t in title_data])

    return None


def get_active_companies(api_token: str, database_id: str):
    """
    Get all companies where Active Flag is 'Active'.
    Returns a list of dictionaries with company information.
    """
    print("Fetching active companies...")
    all_pages = fetch_all_pages(api_token, database_id)

    active_companies = []

    for page in all_pages:
        properties = page['properties']

        # Check Active Flag
        active_flag = properties.get('Active Flag', {})
        if active_flag.get('type') == 'select' and active_flag.get('select'):
            if active_flag['select'].get('name') == 'Active':
                company_name = get_company_name(page)

                if company_name:
                    # Extract additional information
                    company_info = {
                        'page_id': page['id'],
                        'company_name': company_name,
                        'created_time': page['created_time'],
                        'last_edited_time': page['last_edited_time'],
                        'properties': {}
                    }

                    # Extract other relevant properties
                    for prop_name, prop_value in properties.items():
                        prop_type = prop_value['type']

                        if prop_type == 'title':
                            text = ''.join([t['plain_text'] for t in prop_value['title']])
                            company_info['properties'][prop_name] = text

                        elif prop_type == 'rich_text':
                            text = ''.join([t['plain_text'] for t in prop_value['rich_text']])
                            company_info['properties'][prop_name] = text
                            # Store style info for Business State to check if reset is needed
                            if prop_name == 'Business State' and prop_value['rich_text']:
                                annotations = prop_value['rich_text'][0].get('annotations', {})
                                company_info['properties']['_business_state_styled'] = (
                                    annotations.get('bold', False) and
                                    annotations.get('color', 'default') == 'orange'
                                )

                        elif prop_type == 'number':
                            company_info['properties'][prop_name] = prop_value['number']

                        elif prop_type == 'select':
                            if prop_value['select']:
                                company_info['properties'][prop_name] = prop_value['select']['name']
                            else:
                                company_info['properties'][prop_name] = None

                        elif prop_type == 'multi_select':
                            options = [opt['name'] for opt in prop_value['multi_select']]
                            company_info['properties'][prop_name] = options

                        elif prop_type == 'date':
                            if prop_value['date']:
                                company_info['properties'][prop_name] = {
                                    'start': prop_value['date']['start'],
                                    'end': prop_value['date'].get('end')
                                }
                            else:
                                company_info['properties'][prop_name] = None

                        elif prop_type == 'checkbox':
                            company_info['properties'][prop_name] = prop_value['checkbox']

                        elif prop_type == 'url':
                            company_info['properties'][prop_name] = prop_value['url']

                        elif prop_type == 'email':
                            company_info['properties'][prop_name] = prop_value['email']

                        elif prop_type == 'phone_number':
                            company_info['properties'][prop_name] = prop_value['phone_number']

                        elif prop_type == 'status':
                            if prop_value['status']:
                                company_info['properties'][prop_name] = prop_value['status']['name']
                            else:
                                company_info['properties'][prop_name] = None

                        elif prop_type == 'relation':
                            relations = [r['id'] for r in prop_value['relation']]
                            company_info['properties'][prop_name] = {
                                'count': len(relations),
                                'ids': relations
                            }

                    active_companies.append(company_info)

    return active_companies


def display_active_companies(companies):
    """Display active companies in a formatted way."""
    print(f"Found {len(companies)} active companies")


def save_to_json(companies, filename='active_companies.json'):
    """Save active companies data to a JSON file."""
    output_data = {
        'timestamp': datetime.now().isoformat(),
        'total_count': len(companies),
        'companies': companies
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def _load_reset_days(default_days=14):
    """Load Business State style reset threshold from schedule_config.yml."""
    config_path = Path(__file__).resolve().parent.parent / "schedule_config.yml"
    if not config_path.exists():
        return default_days

    try:
        with config_path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.split("#", 1)[0].strip()
                if stripped.startswith("business_state_reset_days:"):
                    _, value = stripped.split(":", 1)
                    value = value.strip()
                    if value.isdigit():
                        return int(value)
    except Exception:
        return default_days

    return default_days


def sync_business_state(notion, page_id, business_state, status_buffer, last_state, business_state_log, apply_style=True):
    """
    Synchronize Business State and status_buffer fields, and update business_state_log.

    Args:
        notion: Notion client instance
        page_id: Page ID to update
        business_state: Current Business State value
        status_buffer: Current status_buffer value
        last_state: Current Last State value
        business_state_log: Current business_state_log value
        apply_style: Whether to apply orange+bold style to Business State

    Returns:
        Tuple of (success: bool, updated_log: str)
    """
    try:
        # Get current date
        now = datetime.now()
        current_date = now.date().isoformat()
        date_string = now.strftime("%m/%d")  # MM/DD format

        # Build new log entry
        # Format: → {Business State}({MM/DD})
        new_log_entry = f"→{business_state}({date_string})"

        # Append to existing log
        if business_state_log:
            # Add newline before the new entry if log already exists
            updated_log = f"{business_state_log}\n{new_log_entry}"
        else:
            # No existing log, just add the new entry
            updated_log = new_log_entry

        # Build Business State rich text with styling
        if apply_style:
            # Apply orange color and bold
            business_state_rich_text = {
                "rich_text": [
                    {
                        "text": {
                            "content": business_state if business_state else ""
                        },
                        "annotations": {
                            "bold": True,
                            "color": "orange"
                        }
                    }
                ]
            }
        else:
            # Default style (no color, no bold)
            business_state_rich_text = {
                "rich_text": [
                    {
                        "text": {
                            "content": business_state if business_state else ""
                        }
                    }
                ]
            }

        # Build update properties
        update_properties = {
            "Business State": business_state_rich_text,
            "Last State": {
                "rich_text": [
                    {
                        "text": {
                            "content": status_buffer if status_buffer else ""
                        }
                    }
                ]
            },
            "status_buffer": {
                "rich_text": [
                    {
                        "text": {
                            "content": business_state if business_state else ""
                        }
                    }
                ]
            },
            "business_status_update_day": {
                "date": {
                    "start": current_date
                }
            },
            "business_state_log": {
                "rich_text": [
                    {
                        "text": {
                            "content": updated_log
                        }
                    }
                ]
            }
        }

        # Update the page
        notion.pages.update(
            page_id=page_id,
            properties=update_properties
        )

        return True, updated_log
    except Exception as e:
        print(f"    ✗ Error updating page: {str(e)}")
        return False, None


def reset_business_state_style(notion, page_id, business_state):
    """
    Reset Business State style to default (remove color and bold).

    Args:
        notion: Notion client instance
        page_id: Page ID to update
        business_state: Current Business State value

    Returns:
        bool: True if update was successful, False otherwise
    """
    try:
        # Build Business State with default style
        update_properties = {
            "Business State": {
                "rich_text": [
                    {
                        "text": {
                            "content": business_state if business_state else ""
                        }
                    }
                ]
            }
        }

        # Update the page
        notion.pages.update(
            page_id=page_id,
            properties=update_properties
        )

        return True
    except Exception as e:
        print(f"    ✗ Error resetting style: {str(e)}")
        return False


def process_active_companies(notion, companies):
    """
    Process active companies and sync Business State with status_buffer.
    If Business State and status_buffer differ:
    1. Copy status_buffer to Last State
    2. Copy Business State to status_buffer
    3. Update business_status_update_day to current date
    4. Append to business_state_log: →{Business State}({MM/DD})

    Returns:
        set: Set of page IDs that were updated (to skip in style reset)
    """
    updated_page_ids = set()

    if not companies:
        return updated_page_ids

    print("\nSyncing Business States...")
    updated_count = 0
    error_count = 0

    for company in companies:
        company_name = company['company_name']
        page_id = company['page_id']
        properties = company['properties']

        # Get current values
        business_state = properties.get('Business State', '')
        status_buffer = properties.get('status_buffer', '')
        last_state = properties.get('Last State', '')
        business_state_log = properties.get('business_state_log', '')

        # Check if Business State and status_buffer are different
        if business_state != status_buffer:
            success, updated_log = sync_business_state(
                notion, page_id, business_state, status_buffer, last_state, business_state_log
            )

            if success:
                print(f"  ✓ {company_name}: Synced")
                updated_count += 1
                updated_page_ids.add(page_id)
            else:
                print(f"  ✗ {company_name}: Failed")
                error_count += 1

    if updated_count > 0 or error_count > 0:
        print(f"  Updated: {updated_count}, Errors: {error_count}")

    return updated_page_ids


def reset_old_business_state_styles(notion, companies, skip_page_ids=None):
    """
    Reset Business State styles for companies where business_status_update_day
    is older than the configured threshold (default 14 days).

    Args:
        notion: Notion client instance
        companies: List of company data dictionaries
        skip_page_ids: Set of page IDs to skip (recently updated pages)

    Returns:
        int: Number of companies whose styles were reset
    """
    if not companies:
        return 0

    if skip_page_ids is None:
        skip_page_ids = set()

    print("\nResetting old styles (> threshold)...")
    reset_days = _load_reset_days()
    today = datetime.now().date()
    cutoff_date = today - timedelta(days=reset_days)
    reset_count = 0
    error_count = 0

    skipped_count = 0

    for company in companies:
        company_name = company['company_name']
        page_id = company['page_id']
        properties = company['properties']

        # Skip pages that were just updated in this run
        if page_id in skip_page_ids:
            continue

        # Skip if style is already reset (not bold+orange)
        is_styled = properties.get('_business_state_styled', False)
        if not is_styled:
            skipped_count += 1
            continue

        # Get business_status_update_day
        business_status_update_day = properties.get('business_status_update_day')
        business_state = properties.get('Business State', '')

        # Skip if no update day is set
        if not business_status_update_day:
            continue

        # Parse the date
        try:
            if isinstance(business_status_update_day, dict):
                update_date_str = business_status_update_day.get('start')
            else:
                update_date_str = business_status_update_day

            if not update_date_str:
                continue

            update_date = datetime.fromisoformat(update_date_str).date()

            # Check if older than the threshold
            if update_date <= cutoff_date:
                if reset_business_state_style(notion, page_id, business_state):
                    print(f"  ✓ {company_name}: Style reset")
                    reset_count += 1
                else:
                    print(f"  ✗ {company_name}: Failed")
                    error_count += 1

        except (ValueError, TypeError):
            error_count += 1

    if reset_count > 0 or error_count > 0 or skipped_count > 0:
        print(f"  Reset: {reset_count}, Skipped (already reset): {skipped_count}, Errors: {error_count}")

    return reset_count


def main():
    # Load environment variables
    load_dotenv()

    # Get credentials from environment
    notion_api_key = os.getenv('NOTION_API_KEY')
    su_long_list_db_id = os.getenv('FIL_SU_LONG_LIST_DB_ID')
    exe_log_db_id = os.getenv('EXE_LOG_DB_ID')

    if not notion_api_key:
        print("Error: NOTION_API_KEY not found in .env file")
        return

    if not su_long_list_db_id:
        print("Error: FIL_SU_LONG_LIST_DB_ID not found in .env file")
        return

    # Initialize Notion client
    notion = Client(auth=notion_api_key)

    # Start log capture
    log_capture = LogCapture()
    log_capture.start()

    status = "正常完了"

    try:
        # Get active companies
        active_companies = get_active_companies(notion_api_key, su_long_list_db_id)

        # Display results
        display_active_companies(active_companies)

        # Save to JSON file
        save_to_json(active_companies)

        # Process companies and sync Business State
        updated_page_ids = process_active_companies(notion, active_companies)

        # Reset styles for Business States older than 2 weeks
        # Skip pages that were just updated in this run
        reset_old_business_state_styles(notion, active_companies, skip_page_ids=updated_page_ids)

        print("\n✓ Completed")

    except Exception as e:
        status = "異常終了"
        print(f"\n✗ Error: {str(e)}")

    finally:
        # Stop log capture
        log_capture.stop()
        log_content = log_capture.get_log()

        # Save execution log to Notion if EXE_LOG_DB_ID is configured
        if exe_log_db_id:
            save_execution_log(
                notion,
                exe_log_db_id,
                status,
                log_content,
                script_name="update_business_state",
                api_token=notion_api_key
            )


if __name__ == "__main__":
    main()

