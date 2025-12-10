import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

_dotenv_available = importlib.util.find_spec("dotenv") is not None
if _dotenv_available:
    from automation import sync_oi_issue_list as so
else:
    so = None


class TestSyncOiIssueList(unittest.TestCase):
    @unittest.skipUnless(_dotenv_available, "python-dotenv not installed")
    def test_rollup_item_to_text_handles_select_and_number(self):
        self.assertEqual(so._rollup_item_to_text({"type": "select", "select": {"name": "X"}}), "X")
        self.assertEqual(so._rollup_item_to_text({"type": "number", "number": 3}), "3")

    @unittest.skipUnless(_dotenv_available, "python-dotenv not installed")
    @patch.dict(
        "os.environ",
        {
            "NOTION_API_KEY": "x",
            "OI_ISSUE_LIST_ID": "a",
            "OI_LIST_SHARE_RS_ID": "b",
            "EXE_LOG_DB_ID": "",  # skip execution log during tests
        },
    )
    @patch("automation.sync_oi_issue_list.Client")
    @patch("automation.sync_oi_issue_list.save_execution_log")
    @patch("automation.sync_oi_issue_list.copy_reference_properties")
    def test_sync_oi_issue_list_exit_code_on_failure(self, mock_copy, mock_save_log, mock_client):
        with patch.object(so, "get_title_property_name", return_value="Title"), patch.object(
            so, "get_active_issues", return_value={"A": "page-a"}
        ), patch.object(so, "get_share_entries", return_value=({}, set())), patch.object(
            so, "create_share_entry", return_value=(False, "err")
        ):
            with self.assertRaises(SystemExit) as ctx:
                so.main()
            self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
