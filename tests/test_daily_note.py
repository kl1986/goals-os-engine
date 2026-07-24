import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import daily_note  # noqa: E402


MONDAY = dt.datetime(2026, 7, 13, 8, 0)  # "today" in most fixtures
SUNDAY = dt.datetime(2026, 7, 12, 21, 0)  # "yesterday" — the archived note's date


def _write_project(brain_path, slug, name, status):
    """Create a Project note (`projects/<slug>/<name>.md`) — since ADR-0017
    the note carries no Next-action/task content itself; it only exists so
    `_project_next_actions()` can gate a `tasks/projects/<slug>/` ticket on
    this note's `status:`. Includes `type: project` per
    `project-tracking.md`'s schema — this is the key `_project_statuses()`
    uses to identify the real Project note among any other loose `.md`
    files that might share its folder."""
    projects_dir = brain_path / "projects" / slug
    projects_dir.mkdir(parents=True, exist_ok=True)
    (projects_dir / f"{name}.md").write_text(
        f"---\ntype: project\nstatus: {status}\n---\n\n"
        f"# {name}\n\n"
        "## Why this matters\nSome reason.\n\n"
        "## Backlog\n- Something else\n\n"
        "## Notes & progress\n\n"
        "## Related\n"
    )
    return f"projects/{slug}/{name}.md"


def _write_loose_project_file(brain_path, slug, filename, content="Some unrelated notes.\n"):
    """Create a non-Project-note `.md` file directly under `projects/<slug>/`
    — mimicking the real `projects/goals-os/` folder, which holds ~17 loose
    files (CONTEXT.md, CLAUDE.md, PRD - Goals OS.md, shared-context files,
    etc.) alongside the one real Project note. These files have no
    `type: project` frontmatter (often no frontmatter at all) and must never
    be mistaken for the Project note itself, however they sort
    alphabetically against it."""
    projects_dir = brain_path / "projects" / slug
    projects_dir.mkdir(parents=True, exist_ok=True)
    (projects_dir / filename).write_text(content)
    return f"projects/{slug}/{filename}"


def _write_ticket(brain_path, kind, slug, ticket_stem, title, status, **extra_frontmatter):
    """Create a ticket file under `tasks/projects/<slug>/` or
    `tasks/areas/<slug>/` (`kind` is "projects" or "areas"), per ADR-0015's
    schema. Returns its path relative to `brain_path`."""
    tasks_dir = brain_path / "tasks" / kind / slug
    tasks_dir.mkdir(parents=True, exist_ok=True)
    frontmatter_lines = [f"status: {status}", "type: task"]
    for key, value in extra_frontmatter.items():
        frontmatter_lines.append(f"{key}: {value}")
    frontmatter = "\n".join(frontmatter_lines)
    title_line = f"# {title}\n\n" if title is not None else ""
    (tasks_dir / f"{ticket_stem}.md").write_text(
        f"---\n{frontmatter}\n---\n\n"
        f"{title_line}"
        "## Execution Plan & Details\n"
    )
    return f"tasks/{kind}/{slug}/{ticket_stem}.md"


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
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-1",
                      "Order shelves for the shed", "prioritised")
        _write_project(self.brain_path, "simmer-project", "Simmer project", "Simmering")
        _write_ticket(self.brain_path, "projects", "simmer-project", "simmer-project-1",
                      "Should not appear", "prioritised")
        _write_project(self.brain_path, "done-project", "Done project", "Complete")
        _write_ticket(self.brain_path, "projects", "done-project", "done-project-1",
                      "Should not appear either", "prioritised")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("Order shelves for the shed", text)
        self.assertNotIn("Should not appear", text)
        self.assertNotIn("Should not appear either", text)

    def test_one_row_per_matching_ticket_no_cap(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-1",
                      "Order shelves for the shed", "prioritised")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-2",
                      "Buy paint", "in-progress")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-3",
                      "Not yet started, backlog", "backlog")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        # Both prioritised and in-progress surface, one row each — no cap.
        self.assertIn("- [ ] Order shelves for the shed — [[clear-the-garage-1]]", text)
        self.assertIn("- [ ] Buy paint — [[clear-the-garage-2]]", text)
        # A backlog-status ticket is silently skipped.
        self.assertNotIn("Not yet started, backlog", text)

    def test_surfaces_awaiting_review_tickets_with_distinct_prefix(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-1",
                      "Review pull request for shed shelving", "awaiting-review")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("- [ ] [Awaiting review] Review pull request for shed shelving — [[clear-the-garage-1]]", text)

    def test_awaiting_review_survives_the_old_allowlist(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-1",
                      "Future status item added after allowlist was written", "awaiting-review")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("- [ ] [Awaiting review] Future status item added after allowlist was written — [[clear-the-garage-1]]", text)


    def test_area_ticket_surfaces_unconditionally_no_project_gate(self):
        _write_ticket(self.brain_path, "areas", "health", "health-1",
                      "Book a dentist appointment", "prioritised")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("- [ ] Book a dentist appointment — [[health-1]]", text)

    def test_project_ticket_skipped_silently_when_parent_project_not_active(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Simmering")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-1",
                      "Order shelves for the shed", "prioritised")
        # Should not raise, and Project next actions section stays empty.
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        section = text.split("## Project next actions\n", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(section.strip(), "")

    def test_render_format_uses_ticket_title_and_direct_wikilink_no_src_comment(self):
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-1",
                      "Order shelves for the shed", "prioritised")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn(
            "- [ ] Order shelves for the shed — [[clear-the-garage-1]]",
            text,
        )
        self.assertNotIn("daily-note-src", text)
        self.assertNotIn("Clear the garage.md", text)

    def test_project_status_resolved_correctly_when_folder_has_loose_non_project_files(self):
        # Regression: projects/goals-os/ in the real Vault has ~17 loose
        # .md files (CONTEXT.md, CLAUDE.md, PRD - Goals OS.md, shared-context
        # files, etc.) alongside the one real Project note. "Agents to
        # build.md" sorts alphabetically before "Goals OS.md" and has no
        # frontmatter at all — a status resolver that just takes the first
        # file found in the folder (rather than identifying the real
        # Project note by its `type: project` key) silently resolves this
        # project's status to None, and every ticket under it vanishes from
        # every future daily note.
        _write_loose_project_file(self.brain_path, "goals-os", "Agents to build.md")
        _write_loose_project_file(self.brain_path, "goals-os", "CLAUDE.md")
        _write_loose_project_file(self.brain_path, "goals-os", "CONTEXT.md")
        _write_project(self.brain_path, "goals-os", "Goals OS", "Active")
        _write_ticket(self.brain_path, "projects", "goals-os", "goals-os-28",
                      "Some real ticket", "prioritised")
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        self.assertIn("- [ ] Some real ticket — [[goals-os-28]]", text)


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
        _write_project(self.brain_path, "clear-the-garage", "Clear the garage", "Active")
        _write_ticket(self.brain_path, "projects", "clear-the-garage", "clear-the-garage-1",
                      "Order shelves for the shed", "prioritised")
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

        # A new prioritised ticket shows up mid-day under a new Active project.
        _write_project(self.brain_path, "fix-the-fence", "Fix the fence", "Active")
        _write_ticket(self.brain_path, "projects", "fix-the-fence", "fix-the-fence-1",
                      "Buy new hinges", "prioritised")

        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        second_text = path.read_text()

        # Manual edits untouched.
        self.assertIn("- [x] Manually ticked task", second_text)
        self.assertIn("Some private notes I wrote.", second_text)
        # No duplicate of the original ticket row.
        self.assertEqual(
            second_text.count("- [ ] Order shelves for the shed — [[clear-the-garage-1]]"), 1
        )
        # New ticket row added.
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

        self.garage_ticket_path = _write_ticket(
            self.brain_path, "projects", "clear-the-garage", "clear-the-garage-1",
            "Order shelves for the shed", "prioritised",
        )
        # No "fix-the-fence-1" ticket exists at all — simulates a ticket
        # that's been renamed/moved/deleted since this morning's generation.
        # The daily-note line pointing at it will be a "miss" when Close
        # daily note tries to reconcile it.

        (self.brain_path / "2026-07-13.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-13\ntags:\n  - daily-note\n---\n\n"
            "# Monday, 13 July 2026\n\n"
            "## Today's tasks\n- [ ] Some manual task\n\n"
            "## Project next actions\n"
            "- [x] Order shelves for the shed — [[clear-the-garage-1]]\n"
            "- [x] Buy new hinges — [[fix-the-fence-1]]\n\n"
            "## Waiting for\n- Jane to send the budget — [[Jane Doe]]\n\n"
            "## Notes\nSome notes.\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_happy_path_writes_status_done_and_resolved_to_ticket_frontmatter(self):
        daily_note.close_daily_note(self.brain_path, now=MONDAY)
        ticket_text = (self.brain_path / self.garage_ticket_path).read_text()
        self.assertIn("status: done", ticket_text)
        self.assertIn("resolved: 2026-07-13", ticket_text)
        self.assertNotIn("status: prioritised", ticket_text)

    def test_miss_path_does_not_crash_and_does_not_touch_ticked_state(self):
        summary = daily_note.close_daily_note(self.brain_path, now=MONDAY)
        self.assertEqual(summary["reconciled"], 1)
        self.assertEqual(len(summary["misses"]), 1)
        self.assertEqual(summary["misses"][0]["ticket_file"], "fix-the-fence-1")

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
