#!/usr/bin/env python3
"""
Notion Database Sync Script
Compares FIL_SU_LONG_LIST (Active Flag = Active) with FIL_STATUS_REPORT
and adds missing companies to FIL_STATUS_REPORT.
"""

import os
from dotenv import load_dotenv
from notion_client import Client


def get_company_name(page):
    """
    Extract company name from a page.
    For SU Long List: '名前' (title)
    For Status Report: 'Name' (rollup -> title)
    """
    properties = page['properties']

    # Try '名前' field (title type) - for SU Long List
    if '名前' in properties and properties['名前']['type'] == 'title':
        title_data = properties['名前']['title']
        if title_data:
            return ''.join([t['plain_text'] for t in title_data])

    # Try 'Name' field (rollup type) - for Status Report
    if 'Name' in properties and properties['Name']['type'] == 'rollup':
        rollup_data = properties['Name']['rollup'].get('array', [])
        if rollup_data:
            for item in rollup_data:
                if item['type'] == 'title' and item['title']:
                    return ''.join([t['plain_text'] for t in item['title']])

    # Try 'No' field (title type) - for Status Report
    if 'No' in properties and properties['No']['type'] == 'title':
        title_data = properties['No']['title']
        if title_data:
            text = ''.join([t['plain_text'] for t in title_data])
            # If it's a number, skip it
            if not text.isdigit():
                return text

    return None


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


def get_active_companies(notion, su_long_list_db_id):
    """Get all active companies from SU Long List."""
    print("Fetching active companies from SU Long List...")
    all_pages = fetch_all_pages(notion, su_long_list_db_id)

    active_companies = {}
    for page in all_pages:
        active_flag = page['properties'].get('Active Flag', {})
        if active_flag.get('type') == 'select' and active_flag.get('select'):
            if active_flag['select'].get('name') == 'Active':
                company_name = get_company_name(page)
                if company_name:
                    active_companies[company_name] = page['id']

    print(f"  Found {len(active_companies)} active companies")
    return active_companies


def get_status_report_companies(notion, status_report_db_id):
    """Get all companies from Status Report."""
    print("Fetching companies from Status Report...")
    all_pages = fetch_all_pages(notion, status_report_db_id)

    status_companies = {}
    for page in all_pages:
        company_name = get_company_name(page)
        if company_name:
            status_companies[company_name] = page['id']

    print(f"  Found {len(status_companies)} companies in Status Report")
    return status_companies


def add_company_to_status_report(notion, status_report_db_id, company_name, su_long_list_page_id):
    """Add a new company to Status Report database."""
    try:
        new_page = notion.pages.create(
            parent={"database_id": status_report_db_id},
            properties={
                "No": {
                    "title": [
                        {
                            "text": {
                                "content": company_name
                            }
                        }
                    ]
                },
                "reference": {
                    "relation": [
                        {
                            "id": su_long_list_page_id
                        }
                    ]
                }
            }
        )
        print(f"  ✓ Added: {company_name}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to add {company_name}: {str(e)}")
        return False


def main():
    # Load environment variables
    load_dotenv()

    # Get credentials from environment
    notion_api_key = os.getenv('NOTION_API_KEY')
    su_long_list_db_id = os.getenv('FIL_SU_LONG_LIST_DB_ID')
    status_report_db_id = os.getenv('FIL_STATUS_REPORT_DB_ID')

    if not notion_api_key:
        print("Error: NOTION_API_KEY not found in .env file")
        return

    if not su_long_list_db_id:
        print("Error: FIL_SU_LONG_LIST_DB_ID not found in .env file")
        return

    if not status_report_db_id:
        print("Error: FIL_STATUS_REPORT_DB_ID not found in .env file")
        return

    # Initialize Notion client
    notion = Client(auth=notion_api_key)

    print("=" * 80)
    print("Notion Database Sync: SU Long List -> Status Report")
    print("=" * 80)
    print()

    # Get active companies from SU Long List
    active_companies = get_active_companies(notion, su_long_list_db_id)

    # Get existing companies from Status Report
    status_companies = get_status_report_companies(notion, status_report_db_id)

    print()
    print("-" * 80)
    print("Comparison Results:")
    print("-" * 80)

    # Find missing companies
    missing_companies = []
    for company_name, page_id in active_companies.items():
        if company_name not in status_companies:
            missing_companies.append((company_name, page_id))

    if not missing_companies:
        print("✓ All active companies are already in Status Report!")
        print()
        return

    print(f"Found {len(missing_companies)} companies to add:")
    for company_name, _ in missing_companies:
        print(f"  - {company_name}")

    print()
    print("-" * 80)
    print("Adding missing companies to Status Report:")
    print("-" * 80)

    # Add missing companies
    success_count = 0
    failed_count = 0

    for company_name, page_id in missing_companies:
        if add_company_to_status_report(notion, status_report_db_id, company_name, page_id):
            success_count += 1
        else:
            failed_count += 1

    print()
    print("=" * 80)
    print("Sync Summary:")
    print("=" * 80)
    print(f"Total active companies in SU Long List: {len(active_companies)}")
    print(f"Companies already in Status Report: {len(status_companies)}")
    print(f"Companies to add: {len(missing_companies)}")
    print(f"Successfully added: {success_count}")
    print(f"Failed to add: {failed_count}")
    print("=" * 80)
    print()


if __name__ == "__main__":
    main()
