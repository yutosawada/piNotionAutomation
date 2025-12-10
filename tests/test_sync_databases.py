import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

_dotenv_available = importlib.util.find_spec("dotenv") is not None
if _dotenv_available:
    from automation import sync_databases as sd
else:
    sd = None


class TestSyncDatabases(unittest.TestCase):
    @unittest.skipUnless(_dotenv_available, "python-dotenv not installed")
    @patch.dict(
        "os.environ",
        {
            "NOTION_API_KEY": "x",
            "FIL_SU_LONG_LIST_DB_ID": "a",
            "FIL_STATUS_REPORT_DB_ID": "b",
            "EXE_LOG_DB_ID": "",  # skip execution log during tests
        },
    )
    @patch("automation.sync_databases.Client")
    @patch("automation.sync_databases.save_execution_log")
    def test_sync_databases_exits_nonzero_on_failures(self, mock_save_log, mock_client):
        with patch.object(sd, "get_active_companies", return_value={"A": "page-a"}), patch.object(
            sd, "get_status_report_companies", return_value={}
        ), patch.object(sd, "add_company_to_status_report", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                sd.main()
            self.assertEqual(ctx.exception.code, 1)

    @unittest.skipUnless(_dotenv_available, "python-dotenv not installed")
    def test_get_company_name_skips_numeric_no_field(self):
        page = {"properties": {"No": {"type": "title", "title": [{"plain_text": "123"}]}}}
        self.assertIsNone(sd.get_company_name(page))


if __name__ == "__main__":
    unittest.main()
