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
"""

import os
import json
import sys
from io import StringIO
from datetime import datetime, timedelta
from dotenv import load_dotenv
from notion_client import Client


class LogCapture:
    """Capture stdout to string for logging."""
    def __init__(self):
        self.log = StringIO()
        self.original_stdout = sys.stdout

    def start(self):
        """Start capturing output."""
        sys.stdout = self

    def stop(self):
        """Stop capturing and restore original stdout."""
        sys.stdout = self.original_stdout

    def write(self, text):
        """Write to both log and original stdout."""
        self.log.write(text)
        self.original_stdout.write(text)

    def flush(self):
        """Flush both streams."""
        self.log.flush()
        self.original_stdout.flush()

    def get_log(self):
        """Get captured log content."""
        return self.log.getvalue()


def fetch_all_pages(notion, database_id):
    """Fetch all pages from a database with pagination."""
    all_results = []
    has_more = True
    start_cursor = None

    while has_more:
        response = notion.databases.query(
            database_id=database_id,
            start_cursor=start_cursor
        )
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


def get_active_companies(notion, database_id):
    """
    Get all companies where Active Flag is 'Active'.
    Returns a list of dictionaries with company information.
    """
    print("Fetching active companies...")
    all_pages = fetch_all_pages(notion, database_id)

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
    """
    if not companies:
        return

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
            else:
                print(f"  ✗ {company_name}: Failed")
                error_count += 1

    if updated_count > 0 or error_count > 0:
        print(f"  Updated: {updated_count}, Errors: {error_count}")


def reset_old_business_state_styles(notion, companies):
    """
    Reset Business State styles for companies where business_status_update_day
    is more than 2 weeks old.

    Args:
        notion: Notion client instance
        companies: List of company data dictionaries

    Returns:
        int: Number of companies whose styles were reset
    """
    if not companies:
        return 0

    print("\nResetting old styles (>2 weeks)...")
    today = datetime.now().date()
    two_weeks_ago = today - timedelta(days=14)
    reset_count = 0
    error_count = 0

    for company in companies:
        company_name = company['company_name']
        page_id = company['page_id']
        properties = company['properties']

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

            # Check if older than 2 weeks
            if update_date <= two_weeks_ago:
                if reset_business_state_style(notion, page_id, business_state):
                    print(f"  ✓ {company_name}: Style reset")
                    reset_count += 1
                else:
                    print(f"  ✗ {company_name}: Failed")
                    error_count += 1

        except (ValueError, TypeError):
            error_count += 1

    if reset_count > 0 or error_count > 0:
        print(f"  Reset: {reset_count}, Errors: {error_count}")

    return reset_count


def save_execution_log(notion, exe_log_db_id, status, log_content):
    """
    Save execution log to EXE_LOG_DB_ID database.

    Args:
        notion: Notion client instance
        exe_log_db_id: Execution log database ID
        status: "正常完了" or "異常終了"
        log_content: Log text content
    """
    try:
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        name = f"update_business_state_{timestamp}"
        date_time = now.isoformat()

        # Create new page in execution log database
        notion.pages.create(
            parent={"database_id": exe_log_db_id},
            properties={
                "名前": {
                    "title": [
                        {
                            "text": {
                                "content": name
                            }
                        }
                    ]
                },
                "日付": {
                    "date": {
                        "start": date_time
                    }
                },
                "実行結果": {
                    "select": {
                        "name": status
                    }
                },
                "ログ本文": {
                    "rich_text": [
                        {
                            "text": {
                                "content": log_content[:2000]  # Notion has 2000 char limit for rich_text
                            }
                        }
                    ]
                }
            }
        )
        print(f"✓ Execution log saved to database")
    except Exception as e:
        print(f"✗ Failed to save execution log: {str(e)}")


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
        active_companies = get_active_companies(notion, su_long_list_db_id)

        # Display results
        display_active_companies(active_companies)

        # Save to JSON file
        save_to_json(active_companies)

        # Process companies and sync Business State
        process_active_companies(notion, active_companies)

        # Reset styles for Business States older than 2 weeks
        reset_old_business_state_styles(notion, active_companies)

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
            save_execution_log(notion, exe_log_db_id, status, log_content)


if __name__ == "__main__":
    main()
