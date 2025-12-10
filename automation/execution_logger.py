#!/usr/bin/env python3
"""
Shared utilities for capturing stdout logs and publishing execution logs to Notion.
"""

import sys
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta


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


def cleanup_old_logs(notion, exe_log_db_id, retention_days=None):
    """Archive execution log entries older than the retention window."""
    if retention_days is None:
        retention_days = _load_retention_days()

    cutoff_date = datetime.now() - timedelta(days=retention_days)
    cutoff_iso = cutoff_date.isoformat()
    archived_count = 0
    start_cursor = None

    while True:
        response = notion.databases.query(
            database_id=exe_log_db_id,
            start_cursor=start_cursor,
            filter={
                "property": "日付",
                "date": {
                    "before": cutoff_iso
                }
            }
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


def save_execution_log(notion, exe_log_db_id, status, log_content, script_name="script"):
    """
    Persist an execution log to a Notion database.

    Args:
        notion: Notion client instance.
        exe_log_db_id: Target execution log database ID.
        status: "正常完了" or "異常終了".
        log_content: Collected stdout text.
        script_name: Base name used for the Notion page title.
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
        cleanup_old_logs(notion, exe_log_db_id)
    except Exception as exc:  # noqa: BLE001 - surface Notion errors
        print(f"✗ Failed to save execution log: {exc}")
