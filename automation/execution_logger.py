#!/usr/bin/env python3
"""
Shared utilities for capturing stdout logs and publishing execution logs to Notion.

This module is compatible with notion-client 2.7.0 which does not have
DatabasesEndpoint.query method. It uses direct HTTP requests instead.

Reference: https://pypi.org/project/notion-client/
"""

import sys
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta
import requests


class LogCapture:
    """Capture stdout while still printing to the console."""
    def __init__(self):
        self.log = StringIO()
        self.original_stdout = sys.stdout

    def start(self):
        """Begin capturing stdout."""
        sys.stdout = self

    def stop(self):
        """Stop capturing stdout."""
        sys.stdout = self.original_stdout

    def write(self, text):
        """Write text to both the buffer and real stdout."""
        self.log.write(text)
        self.original_stdout.write(text)

    def flush(self):
        """Flush buffers."""
        self.log.flush()
        self.original_stdout.flush()

    def get_log(self):
        """Return the captured log as a string."""
        return self.log.getvalue()


def _load_retention_days(default_days=30):
    """
    Try to read log_retention_days from schedule_config.yml (top-level key).
    Falls back to default_days on any error.
    """
    config_path = Path(__file__).resolve().parent.parent / "schedule_config.yml"
    if not config_path.exists():
        return default_days

    try:
        with config_path.open("r", encoding="utf-8") as f:
            for line in f:
                # Remove comments and trim
                stripped = line.split("#", 1)[0].strip()
                if stripped.startswith("log_retention_days:"):
                    _, value = stripped.split(":", 1)
                    value = value.strip()
                    if value.isdigit():
                        return int(value)
    except Exception:
        return default_days

    return default_days


def _notion_database_query(api_token: str, database_id: str, filter_obj=None, start_cursor=None):
    """
    Perform a database query via HTTPS.
    This is required because DatabasesEndpoint.query is not available in notion-client 2.7.0.

    Args:
        api_token: Notion API token.
        database_id: Target database ID.
        filter_obj: Optional filter object for the query.
        start_cursor: Optional cursor for pagination.

    Returns:
        JSON response from Notion API.
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    body = {
        "page_size": 100,
    }
    if filter_obj:
        body["filter"] = filter_obj
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


def cleanup_old_logs(notion, api_token: str, exe_log_db_id: str, retention_days=None):
    """
    Archive execution log entries older than the retention window.

    Args:
        notion: Notion client instance.
        api_token: Notion API token (required for HTTP queries).
        exe_log_db_id: Target execution log database ID.
        retention_days: Number of days to retain logs. Defaults to config or 30.
    """
    if retention_days is None:
        retention_days = _load_retention_days()

    cutoff_date = datetime.now() - timedelta(days=retention_days)
    cutoff_iso = cutoff_date.isoformat()
    archived_count = 0
    start_cursor = None

    filter_obj = {
        "property": "日付",
        "date": {
            "before": cutoff_iso
        }
    }

    while True:
        response = _notion_database_query(
            api_token,
            exe_log_db_id,
            filter_obj=filter_obj,
            start_cursor=start_cursor
        )

        results = response.get('results', [])
        for page in results:
            try:
                notion.pages.update(page_id=page['id'], archived=True)
                archived_count += 1
            except Exception as exc:  # noqa: BLE001
                print(f"✗ Failed to archive old log ({page['id']}): {exc}")

        if not response.get('has_more'):
            break

        start_cursor = response.get('next_cursor')

    if archived_count:
        print(f"✓ Archived {archived_count} execution logs older than {retention_days} days")


def save_execution_log(notion, exe_log_db_id: str, status: str, log_content: str,
                       script_name: str = "script", api_token: str = None):
    """
    Persist an execution log to a Notion database.

    Args:
        notion: Notion client instance.
        exe_log_db_id: Target execution log database ID.
        status: "正常完了" or "異常終了".
        log_content: Collected stdout text.
        script_name: Base name used for the Notion page title.
        api_token: Notion API token (required for cleanup).
    """
    try:
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        name = f"{script_name}_{timestamp}" if script_name else timestamp
        date_time = now.isoformat()

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
                                "content": (log_content or "")[:2000]
                            }
                        }
                    ]
                }
            }
        )
        print("✓ Execution log saved to database")

        # Cleanup old logs if api_token is provided
        if api_token:
            cleanup_old_logs(notion, api_token, exe_log_db_id)
    except Exception as exc:  # noqa: BLE001 - surface Notion errors
        print(f"✗ Failed to save execution log: {exc}")

