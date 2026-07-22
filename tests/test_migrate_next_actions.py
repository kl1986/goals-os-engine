import datetime as dt
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import migrate_next_actions  # noqa: E402


TODAY = dt.datetime(2026, 7, 22, 9, 0)


def _write_project(brain_path, slug, name, next_action_lines=None):
    projects_dir = brain_path / "projects" / slug
    projects_dir.mkdir(parents=True, exist_ok=True)
    next_action_block = ""
    if next_action_lines is not None:
        body = "\n".join(next_action_lines)
        next_action_block = f"## Next action\n<!-- Open items only. -->\n{body}\n\n"
    (projects_dir / f"{name}.md").write_text(
        f"---\nstatus: Active\n---\n\n"
        f"# {name}\n\n"
        "## Why this matters\nSome reason.\n\n"
        f"{next_action_block}"
        "## Backlog\n<!-- Future phases, not yet scheduled. -->\n\n"
        "## Notes & progress\n\n"
        "## Related\n"
    )
    return projects_dir / f"{name}.md"


class TestMigrateNextActions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_multiple_lines_become_multiple_tickets_in_order(self):
        note_path = _write_project(
            self.brain_path, "clear-the-garage", "Clear the garage",
            next_action_lines=[
                "- [ ] Order shelves for the shed",
                "- [ ] Buy paint",
                "- [ ] Sweep the floor",
            ],
        )
        migrate_next_actions.migrate(self.brain_path, now=TODAY)

        tasks_dir = self.brain_path / "tasks" / "projects" / "clear-the-garage"
        ticket_1 = (tasks_dir / "clear-the-garage-1.md").read_text()
        ticket_2 = (tasks_dir / "clear-the-garage-2.md").read_text()
        ticket_3 = (tasks_dir / "clear-the-garage-3.md").read_text()

        self.assertIn("# Order shelves for the shed", ticket_1)
        self.assertIn("# Buy paint", ticket_2)
        self.assertIn("# Sweep the floor", ticket_3)

        for ticket_text in (ticket_1, ticket_2, ticket_3):
            self.assertIn("status: prioritised", ticket_text)
            self.assertIn("type: task", ticket_text)
            self.assertIn("created: 2026-07-22", ticket_text)

        # Note untouched otherwise, still has a title.
        self.assertNotIn("Order shelves for the shed", note_path.read_text())

    def test_section_deleted_after_migration(self):
        note_path = _write_project(
            self.brain_path, "clear-the-garage", "Clear the garage",
            next_action_lines=["- [ ] Order shelves for the shed"],
        )
        migrate_next_actions.migrate(self.brain_path, now=TODAY)
        text = note_path.read_text()
        self.assertNotIn("## Next action", text)
        # Rest of the schema stays intact.
        self.assertIn("## Why this matters", text)
        self.assertIn("## Backlog", text)
        self.assertIn("## Notes & progress", text)
        self.assertIn("## Related", text)

    def test_empty_next_action_section_is_noop_but_still_deleted(self):
        note_path = _write_project(
            self.brain_path, "clear-the-garage", "Clear the garage",
            next_action_lines=[],
        )
        summary = migrate_next_actions.migrate(self.brain_path, now=TODAY)
        text = note_path.read_text()
        self.assertNotIn("## Next action", text)
        self.assertEqual(summary, {})
        tasks_dir = self.brain_path / "tasks" / "projects" / "clear-the-garage"
        self.assertFalse(tasks_dir.exists())

    def test_absent_next_action_section_is_noop(self):
        note_path = _write_project(
            self.brain_path, "clear-the-garage", "Clear the garage",
            next_action_lines=None,
        )
        original_text = note_path.read_text()
        summary = migrate_next_actions.migrate(self.brain_path, now=TODAY)
        self.assertEqual(summary, {})
        self.assertEqual(note_path.read_text(), original_text)

    def test_numbering_continues_from_existing_tickets(self):
        existing_dir = self.brain_path / "tasks" / "projects" / "clear-the-garage"
        existing_dir.mkdir(parents=True)
        (existing_dir / "clear-the-garage-1.md").write_text(
            "---\nstatus: done\ntype: task\ncreated: 2026-07-01\n---\n\n# Old ticket\n"
        )
        (existing_dir / "clear-the-garage-3.md").write_text(
            "---\nstatus: in-progress\ntype: task\ncreated: 2026-07-10\n---\n\n# Another old ticket\n"
        )
        _write_project(
            self.brain_path, "clear-the-garage", "Clear the garage",
            next_action_lines=["- [ ] Order shelves for the shed", "- [ ] Buy paint"],
        )
        migrate_next_actions.migrate(self.brain_path, now=TODAY)

        self.assertTrue((existing_dir / "clear-the-garage-4.md").exists())
        self.assertTrue((existing_dir / "clear-the-garage-5.md").exists())
        self.assertIn("Order shelves for the shed", (existing_dir / "clear-the-garage-4.md").read_text())
        self.assertIn("Buy paint", (existing_dir / "clear-the-garage-5.md").read_text())

    def test_summary_counts_tickets_created_per_project(self):
        _write_project(
            self.brain_path, "clear-the-garage", "Clear the garage",
            next_action_lines=["- [ ] Order shelves for the shed", "- [ ] Buy paint"],
        )
        _write_project(
            self.brain_path, "fix-the-fence", "Fix the fence",
            next_action_lines=["- [ ] Buy new hinges"],
        )
        summary = migrate_next_actions.migrate(self.brain_path, now=TODAY)
        self.assertEqual(summary, {"clear-the-garage": 2, "fix-the-fence": 1})

    def test_blank_fields_present_in_created_ticket(self):
        _write_project(
            self.brain_path, "clear-the-garage", "Clear the garage",
            next_action_lines=["- [ ] Order shelves for the shed"],
        )
        migrate_next_actions.migrate(self.brain_path, now=TODAY)
        ticket_text = (self.brain_path / "tasks" / "projects" / "clear-the-garage" / "clear-the-garage-1.md").read_text()
        for key in ("priority", "component", "parent", "assignee", "github", "goal", "resolved"):
            self.assertTrue(
                re.search(rf"^{key}:\s*$", ticket_text, re.MULTILINE),
                msg=f"missing blank {key}",
            )


if __name__ == "__main__":
    unittest.main()
