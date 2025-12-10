import importlib.util
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

_dotenv_available = importlib.util.find_spec("dotenv") is not None
if _dotenv_available:
    from automation import update_business_state as ub
else:
    ub = None


class TestUpdateBusinessState(unittest.TestCase):
    @unittest.skipUnless(_dotenv_available, "python-dotenv not installed")
    def test_load_reset_days_reads_config(self):
        value = ub._load_reset_days()
        self.assertIsInstance(value, int)
        self.assertGreater(value, 0)

    @unittest.skipUnless(_dotenv_available, "python-dotenv not installed")
    def test_reset_old_business_state_styles_resets_only_old_entries(self):
        today = datetime.now().date()
        old_date = (today - timedelta(days=30)).isoformat()
        recent_date = today.isoformat()

        companies = [
            {
                "company_name": "OldCo",
                "page_id": "old-id",
                "properties": {
                    "business_status_update_day": old_date,
                    "Business State": "X",
                    "_business_state_styled": True,  # Style is applied, needs reset
                },
            },
            {
                "company_name": "NewCo",
                "page_id": "new-id",
                "properties": {
                    "business_status_update_day": recent_date,
                    "Business State": "Y",
                    "_business_state_styled": True,
                },
            },
        ]

        notion = MagicMock()
        with patch.object(ub, "reset_business_state_style", return_value=True) as mock_reset:
            ub.reset_old_business_state_styles(notion, companies)

        mock_reset.assert_called_once_with(notion, "old-id", "X")


if __name__ == "__main__":
    unittest.main()
