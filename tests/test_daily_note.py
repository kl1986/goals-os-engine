import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import daily_note  # noqa: E402


MONDAY = dt.datetime(2026, 7, 13, 8, 0)  # "today" in most fixtures
SUNDAY = dt.datetime(2026, 7, 12, 21, 0)  # "yesterday" — the archived note's date


def _write_project(brain_path, slug, name, status, next_action_lines, notes_body=""):
    projects_dir = brain_path / "projects" / slug
    projects_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(next_action_lines)
    (projects_dir / f"{name}.md").write_text(
        f"---\nstatus: {status}\n---\n\n"
        f"# {name}\n\n"
        "## Why this matters\nSome reason.\n\n"
        f"## Next action\n{body}\n\n"
        "## Backlog\n- Something else\n\n"
        f"## Notes & progress\n{notes_body}\n\n"
        "## Related\n"
    )
    return f"projects/{slug}/{name}.md"


def _write_person(brain_path, filename, name, waiting_lines):
    people_dir = brain_path / "people"
    people_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(waiting_lines)
    (people_dir / filename).write_text(
        f"---\nname: {name}\n---\n\n"
        f"# {name}\n> Some role\n\n"
        f"## ⏳ Waiting For\n{body}\n\n"
        "## \U0001f9e0 Context\n- some context\n"
    )


class TestGenerateFreshCreation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_note_at_brain_root_with_correct_path(self):
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        self.assertEqual(path, self.brain_path / "2026-07-13.md")
        self.assertTrue(path.exists())

    def test_schema_frontmatter_has_no_generated_field(self):
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn(
            "---\ntype: daily-note\ndate: 2026-07-13\ntags:\n  - daily-note\n---\n",
            text,
        )
        self.assertNotIn("generated:", text)

    def test_heading_format(self):
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("# Monday, 13 July 2026\n", text)

    def test_four_sections_in_order_with_empty_state_rendering(self):
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        for heading in ("## Today's tasks", "## Project next actions", "## Waiting for", "## Notes"):
            self.assertIn(heading, text)
        # Order
        positions = [text.index(h) for h in ("## Today's tasks", "## Project next actions", "## Waiting for", "## Notes")]
        self.assertEqual(positions, sorted(positions))
        # Empty-state: bare placeholder checkbox, no source projects/people yet
        self.assertIn("## Today's tasks\n- [ ]\n", text)

    def test_bumps_daily_note_heartbeat(self):
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Daily note | never |\n"
        )
        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        state_text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Daily note | 2026-07-13 08:00 |", state_text)


class TestCarryForward(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        self.archive_dir = self.brain_path / "archive" / "daily-notes"
        self.archive_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_archived_note(self, today_tasks_body):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            f"## Today's tasks\n{today_tasks_body}\n\n"
            "## Project next actions\n\n"
            "## Waiting for\n\n"
            "## Notes\n"
        )

    def test_carries_forward_unchecked_lines_verbatim_and_skips_ticked(self):
        self._write_archived_note(
            "- [ ] Buy milk\n- [x] Already done thing\n- [ ] Call plumber"
        )
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("- [ ] Buy milk", text)
        self.assertIn("- [ ] Call plumber", text)
        self.assertNotIn("Already done thing", text)

    def test_does_not_add_bare_placeholder_when_something_carried(self):
        self._write_archived_note("- [ ] Buy milk")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        section = path.read_text().split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, ["- [ ] Buy milk"])

    def test_ignores_bare_placeholder_line_itself(self):
        self._write_archived_note("- [ ]\n- [ ] Real task")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("- [ ] Real task", text)
        section = text.split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, ["- [ ] Real task"])

    def test_falls_back_to_placeholder_when_archive_has_nothing_unchecked(self):
        self._write_archived_note("- [x] Everything already done")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        section = path.read_text().split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, ["- [ ]"])

    def test_falls_back_to_placeholder_when_no_archive_dir_at_all(self):
        empty_brain = Path(tempfile.mkdtemp())
        path = daily_note.generate_daily_note(empty_brain, now=MONDAY)
        section = path.read_text().split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, ["- [ ]"])

    def test_picks_lexicographically_latest_archived_file(self):
        self._write_archived_note("- [ ] From the 12th")
        (self.archive_dir / "2026-07-01.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-01\ntags:\n  - daily-note\n---\n\n"
            "# Wednesday, 1 July 2026\n\n"
            "## Today's tasks\n- [ ] From the 1st\n\n"
            "## Project next actions\n\n## Waiting for\n\n## Notes\n"
        )
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("From the 12th", text)
        self.assertNotIn("From the 1st", text)


class TestProjectNextActions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_filters_to_status_active_only(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active",
                        ["- [ ] Order shelves for the shed"])
        _write_project(self.brain_path, "simmer-project", "Simmer project", "Simmering",
                        ["- [ ] Should not appear"])
        _write_project(self.brain_path, "done-project", "Done project", "Complete",
                        ["- [ ] Should not appear either"])
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("Order shelves for the shed", text)
        self.assertNotIn("Should not appear", text)
        self.assertNotIn("Should not appear either", text)

    def test_takes_first_unchecked_line_in_file_order_only(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active",
                        ["- [ ] Order shelves for the shed", "- [ ] Buy paint"])
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("Order shelves for the shed", text)
        self.assertNotIn("Buy paint", text)

    def test_skips_empty_or_fully_ticked_next_action_silently(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active", [])
        _write_project(self.brain_path, "fix-the-fence", "Fix the fence", "Active",
                        ["- [x] Already done"])
        # Should not raise, and Project next actions section stays empty.
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        section = text.split("## Project next actions\n", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(section.strip(), "")

    def test_render_format_includes_project_wikilink_and_src_comment(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active",
                        ["- [ ] Order shelves for the shed"])
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn(
            "- [ ] Order shelves for the shed — [[Clear the garage]] "
            "<!-- daily-note-src: projects/clear-the-garage/Clear the garage.md "
            "| Order shelves for the shed -->",
            text,
        )


class TestWaitingFor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_renders_plain_bullets_not_checkboxes_ordered_by_filename(self):
        # dashboard._open_waiting_for's own item['text'] retains the
        # "#waiting-for" tag verbatim (it only strips the leading "- [ ] ");
        # daily_note.py renders that text as-is, same as dashboard.py's own
        # render_dashboard does — so it appears in the daily note too.
        _write_person(self.brain_path, "John Smith.md", "John Smith",
                      ["- [ ] #waiting-for John to send the report"])
        _write_person(self.brain_path, "Jane Doe.md", "Jane Doe",
                      ["- [ ] #waiting-for Jane to send the budget"])
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        section = text.split("## Waiting for\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, [
            "- #waiting-for Jane to send the budget — [[Jane Doe]]",
            "- #waiting-for John to send the report — [[John Smith]]",
        ])
        for ln in lines:
            self.assertFalse(ln.startswith("- [ ]"))
            self.assertFalse(ln.startswith("- [x]"))


class TestAdditiveSameDayRefresh(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active",
                        ["- [ ] Order shelves for the shed"])
        _write_person(self.brain_path, "Jane Doe.md", "Jane Doe",
                      ["- [ ] #waiting-for Jane to send the budget"])

    def tearDown(self):
        self._tmp.cleanup()

    def test_rerun_same_day_preserves_manual_edits_and_adds_new_rows_only(self):
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)

        # Simulate the user's own edits during the day.
        text = path.read_text()
        text = text.replace("## Today's tasks\n- [ ]\n", "## Today's tasks\n- [x] Manually ticked task\n")
        text = text.replace("## Notes\n", "## Notes\nSome private notes I wrote.\n")
        path.write_text(text)

        # A new Active project shows up mid-day.
        _write_project(self.brain_path, "fix-the-fence", "Fix the fence", "Active",
                        ["- [ ] Buy new hinges"])

        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        second_text = path.read_text()

        # Manual edits untouched.
        self.assertIn("- [x] Manually ticked task", second_text)
        self.assertIn("Some private notes I wrote.", second_text)
        # No duplicate of the original project row (it appears twice per line
        # by design — once in the visible text, once in the trailing
        # daily-note-src comment — so count whole rendered lines, not the
        # substring).
        self.assertEqual(
            second_text.count("- [ ] Order shelves for the shed — [[Clear the garage]]"), 1
        )
        # New project row added.
        self.assertIn("Buy new hinges", second_text)
        # No duplicate Waiting For row.
        self.assertEqual(second_text.count("Jane to send the budget"), 1)

    def test_rerun_same_day_does_not_duplicate_when_nothing_changed(self):
        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        first_text = (self.brain_path / "2026-07-13.md").read_text()
        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        second_text = (self.brain_path / "2026-07-13.md").read_text()
        self.assertEqual(first_text, second_text)

    def test_rerun_same_day_replaces_changed_waiting_for_text_instead_of_duplicating(self):
        # Waiting For is a pure read-only mirror (decision 7) — no checkbox,
        # no daily-note-src comment, nothing for a user to hand-edit in the
        # daily note itself. If the source hub's text changes mid-day, a
        # same-day refresh should show the new text, not both old and new.
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        self.assertIn("Jane to send the budget", path.read_text())

        _write_person(self.brain_path, "Jane Doe.md", "Jane Doe",
                      ["- [ ] #waiting-for Jane to send the REVISED budget"])

        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        second_text = path.read_text()
        self.assertNotIn("Jane to send the budget\n", second_text)
        self.assertIn("Jane to send the REVISED budget", second_text)
        self.assertEqual(second_text.count("— [[Jane Doe]]"), 1)


class TestCloseDailyNote(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

        self.garage_path = _write_project(
            self.brain_path, "clear-the-garage", "Clear the garage", "Active",
            ["- [ ] Order shelves for the shed"],
            notes_body="12/07/2026 — Some earlier entry.",
        )
        # Fence project's Next action has already been edited/removed at the
        # source since this morning's generation — the daily-note line will
        # be a "miss" when Close daily note tries to reconcile it.
        self.fence_path = _write_project(
            self.brain_path, "fix-the-fence", "Fix the fence", "Active",
            ["- [ ] A completely different task now"],
        )

        (self.brain_path / "2026-07-13.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-13\ntags:\n  - daily-note\n---\n\n"
            "# Monday, 13 July 2026\n\n"
            "## Today's tasks\n- [ ] Some manual task\n\n"
            "## Project next actions\n"
            "- [x] Order shelves for the shed — [[Clear the garage]] "
            "<!-- daily-note-src: projects/clear-the-garage/Clear the garage.md "
            "| Order shelves for the shed -->\n"
            "- [x] Buy new hinges — [[Fix the fence]] "
            "<!-- daily-note-src: projects/fix-the-fence/Fix the fence.md "
            "| Buy new hinges -->\n\n"
            "## Waiting for\n- Jane to send the budget — [[Jane Doe]]\n\n"
            "## Notes\nSome notes.\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_happy_path_removes_from_next_action_and_appends_done_entry(self):
        daily_note.close_daily_note(self.brain_path, now=MONDAY)
        garage_text = (self.brain_path / self.garage_path).read_text()
        self.assertNotIn("- [ ] Order shelves for the shed", garage_text)
        self.assertIn("13/07/2026 — Order shelves for the shed (done, via daily note)", garage_text)
        self.assertIn("12/07/2026 — Some earlier entry.", garage_text)  # prior entries preserved

    def test_miss_path_does_not_crash_and_does_not_touch_source_or_ticked_state(self):
        summary = daily_note.close_daily_note(self.brain_path, now=MONDAY)
        fence_text = (self.brain_path / self.fence_path).read_text()
        self.assertIn("- [ ] A completely different task now", fence_text)
        self.assertEqual(summary["reconciled"], 1)
        self.assertEqual(len(summary["misses"]), 1)
        self.assertEqual(summary["misses"][0]["project_path"], self.fence_path)

        log_text = (self.brain_path / "log" / "2026-07-13.md").read_text()
        self.assertIn("Row not found at source, no write-back performed", log_text)
        self.assertEqual(log_text.count("### "), 2)  # one per line, no extra summary entry

        # The daily note itself (now archived) still shows both rows ticked —
        # a miss never un-ticks or otherwise rewrites the daily note's own state.
        archived_text = (self.brain_path / "archive" / "daily-notes" / "2026-07-13.md").read_text()
        self.assertIn("- [x] Buy new hinges", archived_text)
        self.assertIn("- [x] Order shelves for the shed", archived_text)

    def test_archives_note_to_archive_daily_notes(self):
        summary = daily_note.close_daily_note(self.brain_path, now=MONDAY)
        self.assertFalse((self.brain_path / "2026-07-13.md").exists())
        archived = self.brain_path / "archive" / "daily-notes" / "2026-07-13.md"
        self.assertTrue(archived.exists())
        self.assertEqual(summary["archived_to"], archived)

    def test_bumps_close_daily_note_heartbeat(self):
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Close daily note | never |\n"
        )
        daily_note.close_daily_note(self.brain_path, now=MONDAY)
        state_text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Close daily note | 2026-07-13 08:00 |", state_text)


if __name__ == "__main__":
    unittest.main()
