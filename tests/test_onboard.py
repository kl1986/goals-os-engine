import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import onboard  # noqa: E402


class TestFreshOnboardIncludesDailyNoteRows(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_routine_state_includes_daily_note_routines(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Daily note | never |", text)
        self.assertIn("| Close daily note | never |", text)

    def test_fresh_action_types_includes_file_capture_today(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "config" / "action-types.md").read_text()
        self.assertIn("file-capture-today", text)


class TestUpgradeExistingBrain(unittest.TestCase):
    """A Brain onboarded before these rows existed shouldn't be stuck
    without them — `track()`'s existing-file migration path (already
    established for `agent-dispatched`) covers the daily-note additions
    the same way."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        config_dir = self.brain_path / "config"
        config_dir.mkdir()
        (config_dir / "routine-state.md").write_text(
            "---\ntype: config\nconfig: routine-state\n---\n\n"
            "| Routine | Last run |\n|---|---|\n"
            "| Capture sweep | never |\n| Dashboard | never |\n"
        )
        (config_dir / "action-types.md").write_text(
            "---\ntype: config\nconfig: action-types\n---\n\n"
            "| Action type | Risk tier | Autonomy level | Notes |\n|---|---|---|---|\n"
            "| file-capture | internal & reversible | confirm-first | Appends a Raw Capture reference. |\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_upgrade_adds_missing_daily_note_routine_rows(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Daily note | never |", text)
        self.assertIn("| Close daily note | never |", text)
        # Pre-existing rows/timestamps untouched.
        self.assertIn("| Capture sweep | never |", text)

    def test_upgrade_adds_missing_file_capture_today_action_type(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "config" / "action-types.md").read_text()
        self.assertIn("file-capture-today", text)
        self.assertIn("file-capture |", text)  # original row preserved

    def test_rerunning_onboard_does_not_duplicate_migrated_rows(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        routine_text = (self.brain_path / "config" / "routine-state.md").read_text()
        action_text = (self.brain_path / "config" / "action-types.md").read_text()
        self.assertEqual(routine_text.count("| Daily note |"), 1)
        self.assertEqual(routine_text.count("| Close daily note |"), 1)
        self.assertEqual(action_text.count("file-capture-today"), 1)


if __name__ == "__main__":
    unittest.main()
