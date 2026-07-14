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


class TestFreshOnboardIncludesWikiRows(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_routine_state_includes_compile(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Compile | never |", text)

    def test_fresh_action_types_includes_all_five_wiki_rows(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "config" / "action-types.md").read_text()
        for action_type in (
            "wiki-compile", "wiki-audit-fix-dead-link", "wiki-audit-relist-orphan",
            "wiki-audit-delete-stale", "wiki-audit-merge-duplicate",
        ):
            self.assertIn(action_type, text)

    def test_fresh_area_note_has_log_section(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "areas" / "work" / "Work.md").read_text()
        self.assertIn("## Log", text)
        # Parallel to Projects' Notes & progress / People's Log — comes before Related.
        self.assertLess(text.index("## Log"), text.index("## Related"))


class TestUpgradeExistingBrainWikiRows(unittest.TestCase):
    """Mirrors TestUpgradeExistingBrain's daily-note precedent — an
    already-onboarded Brain (like Kelvin's live Vault) shouldn't be
    permanently missing the Compile routine-state row or the 5 wiki-*
    action types just because it was onboarded before this ticket."""

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

    def test_upgrade_adds_missing_compile_routine_row(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Compile | never |", text)
        self.assertIn("| Capture sweep | never |", text)  # untouched

    def test_upgrade_adds_all_five_missing_wiki_action_types(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        text = (self.brain_path / "config" / "action-types.md").read_text()
        for action_type in (
            "wiki-compile", "wiki-audit-fix-dead-link", "wiki-audit-relist-orphan",
            "wiki-audit-delete-stale", "wiki-audit-merge-duplicate",
        ):
            self.assertIn(action_type, text)
        self.assertIn("file-capture |", text)  # original row preserved

    def test_rerunning_onboard_does_not_duplicate_wiki_rows(self):
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        routine_text = (self.brain_path / "config" / "routine-state.md").read_text()
        action_text = (self.brain_path / "config" / "action-types.md").read_text()
        self.assertEqual(routine_text.count("| Compile |"), 1)
        self.assertEqual(action_text.count("wiki-compile"), 1)

    def test_upgrade_is_noop_when_wiki_rows_already_present(self):
        # Simulates Kelvin's real Vault: action-types.md already has all 5
        # wiki-* rows and model-routing.md already has wiki-compile (shipped
        # by the design-spec ticket), only routine-state.md's Compile row
        # is actually missing.
        (self.brain_path / "config" / "action-types.md").write_text(
            "---\ntype: config\nconfig: action-types\n---\n\n"
            "| Action type | Risk tier | Autonomy level | Notes |\n|---|---|---|---|\n"
            "| wiki-compile | internal & reversible | confirm-first | x |\n"
            "| wiki-audit-fix-dead-link | internal & reversible | confirm-first | x |\n"
            "| wiki-audit-relist-orphan | internal & reversible | confirm-first | x |\n"
            "| wiki-audit-delete-stale | internal & reversible | confirm-first | x |\n"
            "| wiki-audit-merge-duplicate | outward-facing / hard-to-reverse | confirm-first | x |\n"
        )
        onboard.onboard(self.brain_path, "Work", "Will", "work", 3, 5)
        action_text = (self.brain_path / "config" / "action-types.md").read_text()
        self.assertEqual(action_text.count("wiki-compile"), 1)
        routine_text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Compile | never |", routine_text)


if __name__ == "__main__":
    unittest.main()
