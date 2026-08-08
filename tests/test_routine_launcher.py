import os
import subprocess
import unittest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import routine_launcher

class TestRoutineLauncher(unittest.TestCase):
    def setUp(self):
        self.patcher = patch("subprocess.run")
        self.mock_subprocess = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_unknown_identifier_refused(self):
        with self.assertRaises(SystemExit) as exc:
            routine_launcher.main(["unknown-identifier"])
        self.assertNotEqual(exc.exception.code, 0)
        calls = self.mock_subprocess.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertIn("osascript", calls[0].args[0])

    @patch.dict(os.environ, {})
    def test_missing_brain_refused(self):
        os.environ.pop("GOALS_OS_BRAIN_PATH", None)
        with self.assertRaises(SystemExit) as exc:
            routine_launcher.main(["generate-daily-note"])
        self.assertNotEqual(exc.exception.code, 0)
        calls = self.mock_subprocess.call_args_list
        self.assertEqual(len(calls), 1)
        self.assertIn("osascript", calls[0].args[0])

    @patch.dict(os.environ, {"GOALS_OS_BRAIN_PATH": "/mock/brain"})
    def test_generate_daily_note_mapping(self):
        routine_launcher.main(["generate-daily-note"])

        calls = self.mock_subprocess.call_args_list
        self.assertEqual(len(calls), 2)

        script_call = calls[0]
        args = script_call.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertTrue(args[1].endswith("scripts/daily_note.py"))
        self.assertEqual(args[2], "--brain")
        self.assertEqual(args[3], "/mock/brain")
        self.assertEqual(args[4], "generate")

        notification_call = calls[1]
        self.assertIn("osascript", notification_call.args[0])
        self.assertEqual(notification_call.args[0][-2], "Generate Daily Note completed successfully.")

    @patch.dict(os.environ, {"GOALS_OS_BRAIN_PATH": "/mock/brain"})
    def test_close_daily_note_mapping(self):
        routine_launcher.main(["close-daily-note"])

        calls = self.mock_subprocess.call_args_list
        self.assertEqual(len(calls), 2)

        script_call = calls[0]
        args = script_call.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertTrue(args[1].endswith("scripts/daily_note.py"))
        self.assertEqual(args[2], "--brain")
        self.assertEqual(args[3], "/mock/brain")
        self.assertEqual(args[4], "close")

    @patch.dict(os.environ, {"GOALS_OS_BRAIN_PATH": "/mock/brain"})
    def test_triage_mapping(self):
        routine_launcher.main(["triage"])
        calls = self.mock_subprocess.call_args_list
        self.assertEqual(len(calls), 2)

        script_call = calls[0]
        args = script_call.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertTrue(args[1].endswith("scripts/triage.py"))
        self.assertEqual(args[2], "--brain")
        self.assertEqual(args[3], "/mock/brain")
        self.assertEqual(args[4], "--source")
        self.assertEqual(args[5], "email")

    @patch.dict(os.environ, {"GOALS_OS_BRAIN_PATH": "/mock/brain"})
    def test_refresh_dashboard_mapping(self):
        routine_launcher.main(["refresh-dashboard"])
        calls = self.mock_subprocess.call_args_list
        self.assertEqual(len(calls), 2)

        script_call = calls[0]
        args = script_call.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertTrue(args[1].endswith("scripts/dashboard.py"))
        self.assertEqual(args[2], "--brain")
        self.assertEqual(args[3], "/mock/brain")

    @patch.dict(os.environ, {"GOALS_OS_BRAIN_PATH": "/mock/brain"})
    def test_rule_learning_mapping(self):
        routine_launcher.main(["rule-learning"])
        calls = self.mock_subprocess.call_args_list
        self.assertEqual(len(calls), 2)

        script_call = calls[0]
        args = script_call.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertTrue(args[1].endswith("scripts/rule_learning.py"))
        self.assertEqual(args[2], "--brain")
        self.assertEqual(args[3], "/mock/brain")
        self.assertEqual(args[4], "scan")

    @patch.dict(os.environ, {"GOALS_OS_BRAIN_PATH": "/mock/brain"})
    def test_failure_notification_on_error(self):
        self.mock_subprocess.side_effect = [subprocess.CalledProcessError(1, "cmd"), MagicMock()]

        with self.assertRaises(SystemExit):
            routine_launcher.main(["triage"])

        calls = self.mock_subprocess.call_args_list
        self.assertEqual(len(calls), 2)
        notification_call = calls[1]
        self.assertIn("osascript", notification_call.args[0])
        self.assertEqual(notification_call.args[0][-2], "Triage (Email) failed.")

if __name__ == "__main__":
    unittest.main()
