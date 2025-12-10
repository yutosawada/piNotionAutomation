import sys
import unittest
from automation import execution_logger


class TestExecutionLogger(unittest.TestCase):
    def test_log_capture_restores_stdout(self):
        original_stdout = sys.stdout
        capture = execution_logger.LogCapture()
        capture.start()
        print("hello")  # captured
        capture.stop()
        self.assertIs(sys.stdout, original_stdout)
        self.assertIn("hello", capture.get_log())

    def test_load_retention_days_reads_config(self):
        value = execution_logger._load_retention_days()
        self.assertIsInstance(value, int)
        self.assertGreater(value, 0)


if __name__ == "__main__":
    unittest.main()
