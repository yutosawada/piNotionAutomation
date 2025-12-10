#!/usr/bin/env python3
"""
OI Issue List -> OI List Share Sync Script

1. Fetches all entries from OI_ISSUE_LIST_ID where Active Flag == Active.
2. Creates a relation entry in OI_LIST_SHARE_RS_ID (reference property) for
   each active issue that is not yet present.
3. Writes the relation name into the title property of the destination database.
4. After syncing, copies *_ref rollup values into the corresponding user-facing
   columns (オープンイノベーションとの親和性／探索難易度).
"""

import os
import sys
from typing import Dict, Optional, Tuple
from dotenv import load_dotenv
from notion_client import Client
from automation.execution_logger import LogCapture, save_execution_log


def fetch_all_pages(notion: Client, database_id: str):
    """Fetch all pages from a database (handles pagination)."""
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


def get_title_property_name(notion: Client, database_id: str) -> str:
    """Retrieve the title property name for the specified database."""
    db_info = notion.databases.retrieve(database_id=database_id)
    for prop_name, prop_meta in db_info.get('properties', {}).items():
        if prop_meta.get('type') == 'title':
            return prop_name
    raise RuntimeError(f"No title property found for database {database_id}")


def extract_title(page: dict, title_property: str) -> str:
    """Return the plain text title for the given page using the provided property name."""
    properties = page.get('properties', {})
    title_data = properties.get(title_property, {})
    if title_data.get('type') == 'title':
        text_fragments = title_data.get('title', [])
        return ''.join(fragment.get('plain_text', '') for fragment in text_fragments).strip()
    return ''


def get_active_issues(notion: Client, database_id: str, title_property: str) -> Dict[str, str]:
    """Collect Active issues keyed by title -> page_id."""
    print("Fetching Active issues...")
    all_pages = fetch_all_pages(notion, database_id)

    active_pages: Dict[str, str] = {}
    for page in all_pages:
        properties = page.get('properties', {})
        active_flag = properties.get('Active Flag', {})

        is_active = (
            active_flag.get('type') == 'select'
            and active_flag.get('select')
            and active_flag['select'].get('name') == 'Active'
        )

        if not is_active:
            continue

        title = extract_title(page, title_property)
        if title:
            active_pages[title] = page['id']

    print(f"  Found {len(active_pages)} active issues.")
    return active_pages


def _extract_text_from_rich_text(items):
    return ''.join(fragment.get('plain_text', '') for fragment in items).strip()


def _rollup_item_to_text(item: dict) -> str:
    item_type = item.get('type')
    if item_type in ('title', 'rich_text'):
        return _extract_text_from_rich_text(item.get(item_type, []))
    if item_type == 'select':
        select = item.get('select')
        return select.get('name', '') if select else ''
    if item_type == 'status':
        status = item.get('status')
        return status.get('name', '') if status else ''
    if item_type == 'people':
        return ', '.join(
            person.get('name', '')
            for person in item.get('people', [])
            if person.get('name')
        )
    if item_type == 'number':
        number = item.get('number')
        return '' if number is None else str(number)
    if item_type == 'date':
        date = item.get('date', {})
        return date.get('start', '') or ''
    return ''


def extract_plain_text_from_property(prop_data: dict) -> str:
    """Convert various Notion property payloads into a comparable string."""
    if not prop_data:
        return ''

    prop_type = prop_data.get('type')

    if prop_type in ('title', 'rich_text'):
        return _extract_text_from_rich_text(prop_data.get(prop_type, []))

    if prop_type == 'select':
        select = prop_data.get('select')
        return select.get('name', '') if select else ''

    if prop_type == 'status':
        status = prop_data.get('status')
        return status.get('name', '') if status else ''

    if prop_type == 'number':
        number = prop_data.get('number')
        return '' if number is None else str(number)

    if prop_type == 'multi_select':
        options = [opt.get('name', '') for opt in prop_data.get('multi_select', []) if opt.get('name')]
        return ', '.join(options)

    if prop_type == 'rollup':
        rollup = prop_data.get('rollup', {})
        rollup_type = rollup.get('type')
        if rollup_type == 'array':
            values = []
            for item in rollup.get('array', []):
                text = _rollup_item_to_text(item)
                if text:
                    values.append(text)
            return ', '.join(values)
        if rollup_type == 'number':
            number = rollup.get('number')
            return '' if number is None else str(number)
        if rollup_type == 'date':
            date = rollup.get('date', {})
            return date.get('start', '') or ''
        return ''

    return ''


def build_property_update(prop_data: dict, new_value: str) -> Optional[dict]:
    """Build an update payload for the target property using the provided value."""
    if not new_value:
        return None

    prop_type = prop_data.get('type')

    if prop_type == 'rich_text':
        return {
            "rich_text": [
                {
                    "text": {
                        "content": new_value
                    }
                }
            ]
        }

    if prop_type == 'title':
        return {
            "title": [
                {
                    "text": {
                        "content": new_value
                    }
                }
            ]
        }

    if prop_type == 'select':
        return {
            "select": {
                "name": new_value
            }
        }

    if prop_type == 'status':
        return {
            "status": {
                "name": new_value
            }
        }

    if prop_type == 'number':
        try:
            numeric_value = float(new_value)
        except ValueError:
            return None
        return {
            "number": numeric_value
        }

    if prop_type == 'multi_select':
        options = [
            {"name": option.strip()}
            for option in new_value.split(',')
            if option.strip()
        ]
        if not options:
            return None
        return {
            "multi_select": options
        }

    return None


def property_matches(prop_data: dict, new_value: str) -> bool:
    """Check if the existing property value already matches the provided text."""
    return extract_plain_text_from_property(prop_data) == new_value


def get_share_entries(
    notion: Client,
    database_id: str,
    title_property: str
) -> Tuple[Dict[str, str], set]:
    """Collect existing entries keyed by title and track referenced issue IDs."""
    print("Fetching existing entries from OI List Share...")
    all_pages = fetch_all_pages(notion, database_id)

    entries: Dict[str, str] = {}
    linked_issue_ids: set = set()
    for page in all_pages:
        properties = page.get('properties', {})

        title = extract_title(page, title_property)
        if title:
            entries[title] = page['id']

        reference_prop = properties.get('reference', {})
        if reference_prop.get('type') == 'relation':
            for relation in reference_prop.get('relation', []):
                relation_id = relation.get('id')
                if relation_id:
                    linked_issue_ids.add(relation_id)

    print(f"  Found {len(entries)} existing share entries.")
    return entries, linked_issue_ids


def copy_reference_properties(notion: Client, database_id: str):
    """Copy *_ref rollup fields into the corresponding visible properties."""
    reference_pairs = [
        ("オープンイノベーションとの親和性_ref", "オープンイノベーションとの親和性"),
        ("探索難易度_ref", "探索難易度"),
    ]

    print("\nSyncing reference fields to display columns...")
    all_pages = fetch_all_pages(notion, database_id)
    updated_pages = 0

    for page in all_pages:
        properties = page.get('properties', {})
        update_payload = {}

        for source_field, target_field in reference_pairs:
            source_data = properties.get(source_field)
            target_data = properties.get(target_field)

            if not source_data or not target_data:
                continue

            new_value = extract_plain_text_from_property(source_data)
            if not new_value or property_matches(target_data, new_value):
                continue

            update_value = build_property_update(target_data, new_value)
            if update_value:
                update_payload[target_field] = update_value

        if update_payload:
            notion.pages.update(page_id=page['id'], properties=update_payload)
            updated_pages += 1

    print(f"  Updated {updated_pages} entries.")


def create_share_entry(
    notion: Client,
    database_id: str,
    title_property: str,
    issue_title: str,
    issue_page_id: str
) -> Tuple[bool, str]:
    """Create a new entry in the share database with a relation to the issue page."""
    try:
        notion.pages.create(
            parent={"database_id": database_id},
            properties={
                title_property: {
                    "title": [
                        {
                            "text": {
                                "content": issue_title
                            }
                        }
                    ]
                },
                "reference": {
                    "relation": [
                        {
                            "id": issue_page_id
                        }
                    ]
                }
            }
        )
        return True, ""
    except Exception as err:  # noqa: BLE001 - surface Notion errors
        return False, str(err)


def main():
    load_dotenv()

    notion_api_key = os.getenv('NOTION_API_KEY')
    issue_db_id = os.getenv('OI_ISSUE_LIST_ID')
    share_db_id = os.getenv('OI_LIST_SHARE_RS_ID')
    exe_log_db_id = os.getenv('EXE_LOG_DB_ID')

    if not notion_api_key:
        print("Error: NOTION_API_KEY is not set.")
        return

    if not issue_db_id:
        print("Error: OI_ISSUE_LIST_ID is not set.")
        return

    if not share_db_id:
        print("Error: OI_LIST_SHARE_RS_ID is not set.")
        return

    notion = Client(auth=notion_api_key)
    log_capture = LogCapture()
    log_capture.start()
    status = "正常完了"
    exit_code = 0

    issue_title_property = get_title_property_name(notion, issue_db_id)
    share_title_property = get_title_property_name(notion, share_db_id)

    try:
        active_issues = get_active_issues(notion, issue_db_id, issue_title_property)
        share_entries, linked_issue_ids = get_share_entries(notion, share_db_id, share_title_property)

        missing_titles = [
            (title, page_id)
            for title, page_id in active_issues.items()
            if title not in share_entries and page_id not in linked_issue_ids
        ]

        if not missing_titles:
            print("✓ All active issues already exist in OI List Share.")
            created = 0
            failed = 0
        else:
            print(f"Creating {len(missing_titles)} new entries in OI List Share...")
            created = 0
            failed = 0

            for issue_title, issue_page_id in missing_titles:
                success, error_message = create_share_entry(
                    notion,
                    share_db_id,
                    share_title_property,
                    issue_title,
                    issue_page_id
                )

                if success:
                    print(f"  ✓ Added {issue_title}")
                    created += 1
                else:
                    print(f"  ✗ Failed {issue_title}: {error_message}")
                    failed += 1

        print()
        print("=" * 60)
        print("Sync Summary")
        print("=" * 60)
        print(f"Active issues: {len(active_issues)}")
        print(f"Existing share entries: {len(share_entries)}")
        print(f"Created: {created}")
        print(f"Failed: {failed}")

        if failed > 0:
            status = "異常終了"
            exit_code = 1

        copy_reference_properties(notion, share_db_id)

    except Exception as exc:
        status = "異常終了"
        exit_code = 1
        print(f"✗ Error: {exc}")
    finally:
        log_capture.stop()
        log_content = log_capture.get_log()
        if exe_log_db_id:
            save_execution_log(
                notion,
                exe_log_db_id,
                status,
                log_content,
                script_name="sync_oi_issue_list"
            )
        if exit_code != 0:
            sys.exit(exit_code)


if __name__ == "__main__":
    main()
