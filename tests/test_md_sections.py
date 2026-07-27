"""Regression cover for the section regex that swallowed following sections.

Every section scanner in `scripts/` matched its heading with `\\s*\\n`. `\\s`
matches newlines, so on an *empty* section `\\s*` consumed the blank line and
then backtracked — making the captured "body" of that section every section
that followed it, to EOF. Two call sites were fixed in 645d864; these tests
cover the remaining ones, each asserting the empty-section case specifically.
"""

import datetime as dt
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import md_sections  # noqa: E402
import daily_note  # noqa: E402
import dashboard  # noqa: E402
import execute  # noqa: E402
import migrate_next_actions  # noqa: E402


class TestSectionBodyPattern(unittest.TestCase):
    def test_empty_section_body_is_empty_not_the_rest_of_the_file(self):
        text = "## Waiting for\n\n## Notes\n- a note of mine\n"
        match = re.search(
            md_sections.SECTION_BODY.format(re.escape("Waiting for")),
            text,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "")

    def test_populated_section_body_still_captures_its_own_lines_only(self):
        text = "## Waiting for\n- one\n- two\n\n## Notes\n- a note\n"
        match = re.search(
            md_sections.SECTION_BODY.format(re.escape("Waiting for")),
            text,
            re.MULTILINE | re.DOTALL,
        )
        self.assertEqual(match.group(1), "- one\n- two\n")

    def test_daily_note_reexports_the_shared_pattern(self):
        """`daily_note._SECTION_BODY` was the original home; it must not
        diverge into a second pattern."""
        self.assertEqual(daily_note._SECTION_BODY, md_sections.SECTION_BODY)


class TestExecuteInsertBeforeNextHeading(unittest.TestCase):
    """The data-corruption case, and the reason this ticket is priority: high.
    A `file-capture` into an empty target section appended into the *next*
    section, silently corrupting a curated note."""

    def test_insert_into_empty_section_lands_under_its_own_heading(self):
        text = "# Home\n\n## Inbox\n\n## Notes\n- an existing note\n"
        result = execute._insert_before_next_heading(text, "Inbox", "- new capture")

        self.assertEqual(
            result,
            "# Home\n\n## Inbox\n- new capture\n## Notes\n- an existing note\n",
        )
        self.assertIn("- an existing note", result)

    def test_file_capture_into_empty_section_does_not_touch_the_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp)
            (brain / "areas" / "household").mkdir(parents=True)
            dest = brain / "areas" / "household" / "_inbox.md"
            dest.write_text("# Home inbox\n\n## Inbox\n\n## Notes\n- keep me\n")

            execute._file_capture(brain, "areas/household/_inbox.md#Inbox", "- buy milk")

            after = dest.read_text()
            self.assertIn("- keep me", after)
            self.assertIn("## Notes", after)
            inbox_body = after.split("## Inbox\n", 1)[1].split("## Notes", 1)[0]
            self.assertIn("- buy milk", inbox_body)

    def test_insert_into_populated_section_still_appends_at_its_end(self):
        text = "## Inbox\n- first\n\n## Notes\n- a note\n"
        result = execute._insert_before_next_heading(text, "Inbox", "- second")
        self.assertEqual(result, "## Inbox\n- first\n- second\n## Notes\n- a note\n")


class TestDashboardOpenWaitingFor(unittest.TestCase):
    def test_empty_waiting_for_does_not_scan_into_following_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp)
            (brain / "people").mkdir(parents=True)
            (brain / "people" / "Jane Doe.md").write_text(
                "---\nname: Jane Doe\n---\n\n"
                "## Waiting For\n\n"
                "## To Discuss\n- [ ] Ask Jane about the budget #waiting-for\n"
            )

            items = dashboard._open_waiting_for(brain)
            self.assertEqual(items, [])

    def test_populated_waiting_for_still_surfaces_its_own_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp)
            (brain / "people").mkdir(parents=True)
            (brain / "people" / "Jane Doe.md").write_text(
                "---\nname: Jane Doe\n---\n\n"
                "## Waiting For\n- [ ] Jane to send the draft budget #waiting-for\n\n"
                "## To Discuss\n- [ ] Something else\n"
            )

            items = dashboard._open_waiting_for(brain)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["person"], "Jane Doe")
            self.assertIn("draft budget", items[0]["text"])


class TestDailyNoteCarryForwardTasks(unittest.TestCase):
    def test_empty_todays_tasks_carries_nothing_from_following_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp)
            archive = brain / "archive" / "daily-notes"
            archive.mkdir(parents=True)
            (archive / "2026-07-25.md").write_text(
                "# 2026-07-25\n\n"
                "## Today's tasks\n\n"
                "## Project next actions\n- [ ] Ship the section regex fix\n"
            )

            carried = daily_note._carry_forward_tasks(brain)
            self.assertEqual(carried, [])

    def test_populated_todays_tasks_still_carries_its_own_open_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp)
            archive = brain / "archive" / "daily-notes"
            archive.mkdir(parents=True)
            (archive / "2026-07-25.md").write_text(
                "# 2026-07-25\n\n"
                "## Today's tasks\n- [ ] Still open\n- [x] Already done\n\n"
                "## Project next actions\n- [ ] Not mine to carry\n"
            )

            carried = daily_note._carry_forward_tasks(brain)
            self.assertEqual(carried, ["- [ ] Still open"])


class TestDailyNoteCloseDailyNote(unittest.TestCase):
    def test_empty_project_next_actions_reconciles_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp)
            ticket_dir = brain / "tasks" / "projects" / "goals-os"
            ticket_dir.mkdir(parents=True)
            ticket = ticket_dir / "some-ticket.md"
            ticket.write_text("---\nstatus: in-progress\nresolved:\n---\n# Some ticket\n")
            (brain / "2026-07-26.md").write_text(
                "# 2026-07-26\n\n"
                "## Project next actions\n\n"
                "## Today's tasks\n- [x] Unrelated [[some-ticket]]\n"
            )

            summary = daily_note.close_daily_note(brain, dt.datetime(2026, 7, 26, 18, 0))

            self.assertEqual(summary["reconciled"], 0)
            self.assertIn("status: in-progress", ticket.read_text())


class TestMigrateNextActionsSection(unittest.TestCase):
    def test_empty_next_action_section_does_not_capture_following_sections(self):
        text = "# Project\n\n## Next action\n\n## Backlog\n- [ ] Something to keep\n"
        match = migrate_next_actions.NEXT_ACTION_SECTION_RE.search(text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "")

    def test_empty_next_action_deletion_does_not_delete_following_sections(self):
        text = "# Project\n\n## Next action\n\n## Backlog\n- [ ] Something to keep\n"
        result = migrate_next_actions.NEXT_ACTION_FULL_RE.sub("", text)
        self.assertIn("## Backlog", result)
        self.assertIn("- [ ] Something to keep", result)

    def test_populated_next_action_still_captures_its_own_lines(self):
        text = "## Next action\n- [ ] Do the thing\n\n## Backlog\n- [ ] Later\n"
        match = migrate_next_actions.NEXT_ACTION_SECTION_RE.search("\n" + text)
        self.assertEqual(match.group(1), "- [ ] Do the thing\n")


if __name__ == "__main__":
    unittest.main()
