import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import ticket_normalization  # noqa: E402


TODAY = dt.datetime(2026, 7, 22, 9, 0)

ALL_KEYS_BLANK = (
    "---\n"
    "status: prioritised\n"
    "type: task\n"
    "priority: \n"
    "component: \n"
    "parent: \n"
    "assignee: \n"
    "github: \n"
    "goal: \n"
    "created: 2026-07-01\n"
    "resolved: \n"
    "---\n\n"
    "# Fully conforming ticket\n"
)


class TestTicketNormalization(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        self.tasks_dir = self.brain_path / "tasks"
        self.tasks_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel_path: str, content: str) -> Path:
        path = self.brain_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    # -- missing-key backfill -------------------------------------------------

    def test_backfills_missing_keys_blank_and_type_defaults_to_task(self):
        self._write(
            "tasks/projects/clear-the-garage/bye.md",
            "---\nstatus: backlog\nkanban_order: V0\n---\n\n# Order shelves\n",
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)

        candidates = list((self.brain_path / "tasks" / "projects" / "clear-the-garage").glob("*.md"))
        self.assertEqual(len(candidates), 1)
        text = candidates[0].read_text()

        self.assertIn("status: backlog", text)  # existing value preserved
        self.assertIn("kanban_order: V0", text)  # untouched, not part of the check
        self.assertIn("type: task", text)  # defaulted, since missing
        for key in ("priority", "component", "parent", "assignee", "github", "goal", "created", "resolved"):
            self.assertRegex(text, rf"(?m)^{key}:\s*$")

    def test_logs_one_action_log_entry_per_file_modified(self):
        self._write(
            "tasks/projects/clear-the-garage/bye.md",
            "---\nstatus: backlog\nkanban_order: V0\n---\n\n# Order shelves\n",
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)
        log_text = (self.brain_path / "log" / "2026-07-22.md").read_text()
        self.assertEqual(log_text.count("### "), 1)
        self.assertIn("ticket-normalize", log_text)
        self.assertIn("actor:** EA", log_text)
        self.assertIn("Ticket normalization (Routine)", log_text)

    # -- slug + number inference / renaming -----------------------------------

    def test_infers_slug_and_number_and_renames_file(self):
        self._write(
            "tasks/projects/clear-the-garage/clear-the-garage-1.md",
            ALL_KEYS_BLANK,  # already conforming — occupies number 1
        )
        self._write(
            "tasks/projects/clear-the-garage/weird-name.md",
            "---\nstatus: backlog\nkanban_order: V0\n---\n\n# Order shelves for the shed\n",
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)

        garage_dir = self.brain_path / "tasks" / "projects" / "clear-the-garage"
        self.assertTrue((garage_dir / "clear-the-garage-1.md").exists())  # untouched
        self.assertTrue((garage_dir / "clear-the-garage-2-order-shelves-for-the-shed.md").exists())
        self.assertFalse((garage_dir / "weird-name.md").exists())

    def test_area_slug_inferred_same_as_project_slug(self):
        self._write(
            "tasks/areas/health/random.md",
            "---\nstatus: backlog\nkanban_order: V0\n---\n\n# Book a dentist appointment\n",
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)
        health_dir = self.brain_path / "tasks" / "areas" / "health"
        self.assertTrue((health_dir / "health-1-book-a-dentist-appointment.md").exists())

    def test_no_h1_gets_generic_title_and_untitled_short_desc(self):
        self._write(
            "tasks/projects/return-on-constraints/bye.md",
            "---\nstatus: backlog\nkanban_order: V0\n---\n",
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)
        target_dir = self.brain_path / "tasks" / "projects" / "return-on-constraints"
        matches = list(target_dir.glob("return-on-constraints-1-untitled.md"))
        self.assertEqual(len(matches), 1)
        self.assertIn("# Untitled ticket", matches[0].read_text())

    # -- no inferable slug -> tasks/_unfiled/ ---------------------------------

    def test_no_inferable_slug_moves_to_unfiled_keeping_filename(self):
        self._write(
            "tasks/loose-card.md",
            "---\nstatus: backlog\nkanban_order: V0\n---\n\n# Some loose card\n",
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)
        self.assertFalse((self.brain_path / "tasks" / "loose-card.md").exists())
        unfiled_path = self.brain_path / "tasks" / "_unfiled" / "loose-card.md"
        self.assertTrue(unfiled_path.exists())
        text = unfiled_path.read_text()
        self.assertIn("# Some loose card", text)  # contents preserved
        self.assertIn("type: task", text)  # frontmatter still backfilled

    def test_directly_under_project_folder_no_slug_subfolder_goes_unfiled(self):
        # tasks/projects/loose.md — under "projects" itself, not a <slug>/
        # subfolder — has no inferable slug either.
        self._write(
            "tasks/projects/loose.md",
            "---\nstatus: backlog\n---\n\n# Loose\n",
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)
        self.assertTrue((self.brain_path / "tasks" / "_unfiled" / "loose.md").exists())

    # -- idempotency -----------------------------------------------------------

    def test_fully_conforming_ticket_left_untouched(self):
        path = self._write(
            "tasks/projects/clear-the-garage/clear-the-garage-1-order-shelves.md",
            ALL_KEYS_BLANK,
        )
        original_text = path.read_text()
        changes = ticket_normalization.normalize(self.brain_path, now=TODAY)
        self.assertEqual(changes, [])
        self.assertEqual(path.read_text(), original_text)
        self.assertTrue(path.exists())

    def test_running_twice_produces_no_further_changes(self):
        self._write(
            "tasks/projects/clear-the-garage/bye.md",
            "---\nstatus: backlog\nkanban_order: V0\n---\n\n# Order shelves\n",
        )
        first_changes = ticket_normalization.normalize(self.brain_path, now=TODAY)
        self.assertEqual(len(first_changes), 1)

        # Snapshot every file's content after the first pass.
        garage_dir = self.brain_path / "tasks" / "projects" / "clear-the-garage"
        before = {p.name: p.read_text() for p in garage_dir.glob("*.md")}

        second_changes = ticket_normalization.normalize(self.brain_path, now=TODAY)
        self.assertEqual(second_changes, [])

        after = {p.name: p.read_text() for p in garage_dir.glob("*.md")}
        self.assertEqual(before, after)

    # -- heartbeat ---------------------------------------------------------

    def test_bumps_ticket_normalization_heartbeat_row(self):
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Ticket normalization | never |\n"
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)
        state_text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Ticket normalization | 2026-07-22 09:00 |", state_text)

    def test_bumps_heartbeat_even_when_nothing_to_normalize(self):
        self._write(
            "tasks/projects/clear-the-garage/clear-the-garage-1.md",
            ALL_KEYS_BLANK,
        )
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Ticket normalization | never |\n"
        )
        ticket_normalization.normalize(self.brain_path, now=TODAY)
        state_text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Ticket normalization | 2026-07-22 09:00 |", state_text)


if __name__ == "__main__":
    unittest.main()
