import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import migrate_routine_state as mrs  # noqa: E402

OLD_SHAPE = (
    "---\ntype: config\nconfig: routine-state\n---\n\n"
    "# Routine state\n\n"
    "| Routine | Cadence | Last run |\n"
    "|---|---|---|\n"
    "| Capture sweep | continuous/hourly | never |\n"
    "| Triage | on new raw / daily | 2026-07-10 08:00 |\n"
)

NEW_SHAPE = (
    "---\ntype: config\nconfig: routine-state\n---\n\n"
    "# Routine state\n\n"
    "| Routine | Last run |\n"
    "|---|---|\n"
    "| Capture sweep | never |\n"
    "| Triage | never |\n"
)


class TestMigrate(unittest.TestCase):
    def test_migrates_old_shape_and_preserves_non_never_last_run(self):
        new_text, changed = mrs.migrate(OLD_SHAPE)
        self.assertTrue(changed)
        self.assertIn("| Routine | Last run |", new_text)
        self.assertNotIn("Cadence", new_text)
        self.assertIn("| Triage | 2026-07-10 08:00 |", new_text)
        self.assertIn("| Capture sweep | never |", new_text)

    def test_noop_on_already_new_shape(self):
        new_text, changed = mrs.migrate(NEW_SHAPE)
        self.assertFalse(changed)
        self.assertEqual(new_text, NEW_SHAPE)

    def test_noop_on_empty_text(self):
        new_text, changed = mrs.migrate("")
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
