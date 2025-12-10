#!/usr/bin/env python3
"""
Notion Database Sync Script

Compares FIL_SU_LONG_LIST (Active Flag = Active) with FIL_STATUS_REPORT
and adds missing companies to FIL_STATUS_REPORT.
Uses the HTTP request interface because DatabasesEndpoint.query is not available in notion-client 2.7.0.
"""

import os
import sys
import importlib.metadata
import requests
from dotenv import load_dotenv
from notion_client import Client
from automation.execution_logger import LogCapture, save_execution_log


try:
    NOTION_CLIENT_VERSION = importlib.metadata.version("notion-client")
except importlib.metadata.PackageNotFoundError:
    NOTION_CLIENT_VERSION = "unknown"


def notion_database_query(api_token: str, database_id: str, start_cursor=None):
    """
    Perform a database query via HTTPS because DatabasesEndpoint.query is not available in 2.7.0.
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


def fetch_all_pages(api_token: str, notion, database_id):
    """Fetch all pages from a database with pagination."""
    all_results = []
    has_more = True
    start_cursor = None
    page_counter = 0

    while has_more:
        response = notion_database_query(api_token, database_id, start_cursor=start_cursor)
        page_counter += 1
        all_results.extend(response.get("results", []))
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    print(f"  Queried {page_counter} page(s) from database {database_id}")
    return all_results


def get_company_name(page):
    """
    Extract company name from a page.
    For SU Long List: '企業名' (title)
    For Status Report: 'Name' (rollup -> title)
    """
    properties = page["properties"]

    # Try '企業名' field (title type) - for SU Long List
    if "企業名" in properties and properties["企業名"]["type"] == "title":
        title_data = properties["企業名"]["title"]
        if title_data:
            return "".join([t["plain_text"] for t in title_data])

    # Try 'Name' field (rollup type) - for Status Report
    if "Name" in properties and properties["Name"]["type"] == "rollup":
        rollup_data = properties["Name"]["rollup"].get("array", [])
        if rollup_data:
            for item in rollup_data:
                if item["type"] == "title" and item["title"]:
                    return "".join([t["plain_text"] for t in item["title"]])

    # Try 'No' field (title type) - for Status Report
    if "No" in properties and properties["No"]["type"] == "title":
        title_data = properties["No"]["title"]
        if title_data:
            text = "".join([t["plain_text"] for t in title_data])
            # If it's a number, skip it
            if not text.isdigit():
                return text

    return None


def is_active_flag(properties):
    """Return True if Active Flag property exists and is 'Active'."""
    active_flag = properties.get("Active Flag", {})
    flag_type = active_flag.get("type")

    if flag_type == "select" and active_flag.get("select"):
        return active_flag["select"].get("name") == "Active"

    if flag_type == "status" and active_flag.get("status"):
        return active_flag["status"].get("name") == "Active"

    return False


def get_active_companies(api_token, notion, su_long_list_db_id):
    """Get all active companies from SU Long List."""
    print("Fetching active companies from SU Long List...")
    all_pages = fetch_all_pages(api_token, notion, su_long_list_db_id)

    active_companies = {}
    for page in all_pages:
        properties = page["properties"]
        if is_active_flag(properties):
            company_name = get_company_name(page)
            if company_name:
                active_companies[company_name] = page["id"]

    print(f"  Scanned {len(all_pages)} pages, Found {len(active_companies)} active companies")
    return active_companies


def get_status_report_companies(api_token, notion, status_report_db_id):
    """Get all companies from Status Report."""
    print("Fetching companies from Status Report...")
    all_pages = fetch_all_pages(api_token, notion, status_report_db_id)

    status_companies = {}
    for page in all_pages:
        company_name = get_company_name(page)
        if company_name:
            status_companies[company_name] = page["id"]

    print(f"  Found {len(status_companies)} companies in Status Report")
    return status_companies


def add_company_to_status_report(notion, status_report_db_id, company_name, su_long_list_page_id):
    """Add a new company to Status Report database."""
    try:
        notion.pages.create(
            parent={"database_id": status_report_db_id},
            properties={
                "Company Name": {
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
    load_dotenv()

    notion_api_key = os.getenv("NOTION_API_KEY")
    su_long_list_db_id = os.getenv("FIL_SU_LONG_LIST_DB_ID")
    status_report_db_id = os.getenv("FIL_STATUS_REPORT_DB_ID")
    exe_log_db_id = os.getenv("EXE_LOG_DB_ID")

    if not notion_api_key:
        print("Error: NOTION_API_KEY not found in .env file")
        return

    if not su_long_list_db_id:
        print("Error: FIL_SU_LONG_LIST_DB_ID not found in .env file")
        return

    if not status_report_db_id:
        print("Error: FIL_STATUS_REPORT_DB_ID not found in .env file")
        return

    notion = Client(auth=notion_api_key)
    log_capture = LogCapture()
    log_capture.start()
    status = "正常完了"
    exit_code = 0

    print("=" * 80)
    print(f"Notion Database Sync (client={NOTION_CLIENT_VERSION}): SU Long List -> Status Report")
    print("=" * 80)
    print()

    try:
        active_companies = get_active_companies(notion_api_key, notion, su_long_list_db_id)
        status_companies = get_status_report_companies(notion_api_key, notion, status_report_db_id)

        print()
        print("-" * 80)
        print("Comparison Results:")
        print("-" * 80)

        missing_companies = [
            (name, pid) for name, pid in active_companies.items() if name not in status_companies
        ]

        if not missing_companies:
            print("✓ All active companies are already in Status Report!")
            print()
        else:
            print(f"Found {len(missing_companies)} companies to add:")
            for company_name, _ in missing_companies:
                print(f"  - {company_name}")

            print()
            print("-" * 80)
            print("Adding missing companies to Status Report:")
            print("-" * 80)

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

            if failed_count > 0:
                status = "異常終了"
                exit_code = 1

    except Exception as exc:
        status = "異常終了"
        exit_code = 1
        print(f"✗ Error: {exc}")
    finally:
        log_capture.stop()
        log_content = log_capture.get_log()
        if exe_log_db_id:
            try:
                save_execution_log(
                    notion,
                    exe_log_db_id,
                    status,
                    log_content,
                    script_name="sync_databases",
                    api_token=notion_api_key
                )
            except Exception as log_exc:
                print(f"✗ Failed to save execution log: {log_exc}")
        if exit_code != 0:
            sys.exit(exit_code)


if __name__ == "__main__":
    main()

