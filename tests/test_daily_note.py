import datetime as dt
import sys
import tempfile
import unittest
import unittest.mock
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

    def test_sections_in_order_with_embeds_and_empty_state_rendering(self):
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        expected_headings = (
            "## Critical",
            "## Available time",
            "## Now",
            "## Call Companion",
            "## Drafts to review and send",
            "## Later today",
            "## Tomorrow candidates",
            "## Today's tasks",
            "## Daily priorities",
            "## Project next actions",
            "## Waiting for",
            "## Proposed from meetings",
            "## Notes",
        )
        for heading in expected_headings:
            self.assertIn(heading, text)
        # Order
        positions = [text.index(h) for h in expected_headings]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count("![[tasks/all-tickets.base#Critical work]]"), 1)
        self.assertEqual(text.count("![[tasks/all-tickets.base#Today]]"), 1)
        self.assertEqual(text.count("![[tasks/all-tickets.base#Call Companion]]"), 1)
        self.assertEqual(text.count("![[tasks/all-tickets.base#Tomorrow candidates]]"), 1)
        self.assertEqual(text.count("![[tasks/all-tickets.base#Daily priorities]]"), 1)
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

    def test_carry_forward_now_and_later_today_to_todays_tasks(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            "## Critical\n![[tasks/all-tickets.base#Critical work]]\n- [ ] Critical item\n\n"
            "## Available time\n- [ ] Available item\n\n"
            "## Now\n![[tasks/all-tickets.base#Today]]\n- [ ] Unchecked from Now\n\n"
            "## Call Companion\n![[tasks/all-tickets.base#Call Companion]]\n- [ ] Call item\n\n"
            "## Drafts to review and send\n- [ ] [draft] Draft item — [[Sam Patel]]\n    - [ ] Send\n    - [ ] Discard\n    - [ ] Carry forward\n\n"
            "## Later today\n- [ ] Unchecked from Later today\n\n"
            "## Tomorrow candidates\n![[tasks/all-tickets.base#Tomorrow candidates]]\n- [ ] Tomorrow item\n\n"
            "## Today's tasks\n- [ ] Unchecked from Today's tasks\n\n"
            "## Daily priorities\n![[tasks/all-tickets.base#Daily priorities]]\n\n"
            "## Project next actions\n\n"
            "## Waiting for\n\n"
            "## Proposed from meetings\n\n"
            "## Notes\n"
        )
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        section = text.split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
        self.assertEqual(
            lines,
            [
                "- [ ] Unchecked from Today's tasks",
                "- [ ] Unchecked from Now",
                "- [ ] Unchecked from Later today",
            ]
        )
        self.assertNotIn("Critical item", text)
        self.assertNotIn("Available item", text)
        self.assertNotIn("Call item", text)
        self.assertIn("Draft item", text)
        self.assertNotIn("Tomorrow item", text)

    def test_carry_forward_deduplicates_across_sections(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            "## Today's tasks\n- [ ] shared task\n\n"
            "## Now\n- [ ] shared task\n\n"
            "## Later today\n"
        )
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        section = text.split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, ["- [ ] shared task"])

    def test_carry_forward_preserves_duplicates_within_single_section(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            "## Today's tasks\n- [ ] duplicate task\n- [ ] duplicate task\n\n"
            "## Now\n\n"
            "## Later today\n"
        )
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        section = text.split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, ["- [ ] duplicate task", "- [ ] duplicate task"])



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

    def test_embed_idempotence_on_repeat_generation(self):
        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = (self.brain_path / "2026-07-13.md").read_text()
        self.assertEqual(text.count("![[tasks/all-tickets.base#Critical work]]"), 1)
        self.assertEqual(text.count("![[tasks/all-tickets.base#Today]]"), 1)
        self.assertEqual(text.count("![[tasks/all-tickets.base#Call Companion]]"), 1)
        self.assertEqual(text.count("![[tasks/all-tickets.base#Tomorrow candidates]]"), 1)
        self.assertEqual(text.count("![[tasks/all-tickets.base#Daily priorities]]"), 1)

    def test_upgrade_path_old_schema_note_gains_all_headings_and_embeds_verbatim(self):
        note_path = self.brain_path / "2026-07-13.md"
        note_path.write_text(
            "---\ntype: daily-note\ndate: 2026-07-13\n---\n\n"
            "# Monday, 13 July 2026\n\n"
            "## Today's tasks\n- [ ] Keep this\n\n"
            "## Project next actions\n\n"
            "## Waiting for\n\n"
            "## Notes\nKeep this too.\n"
        )

        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        first_text = note_path.read_text()
        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        second_text = note_path.read_text()

        expected_headings = (
            "## Critical",
            "## Available time",
            "## Now",
            "## Call Companion",
            "## Drafts to review and send",
            "## Later today",
            "## Tomorrow candidates",
            "## Today's tasks",
            "## Daily priorities",
            "## Project next actions",
            "## Waiting for",
            "## Proposed from meetings",
            "## Notes",
        )
        for heading in expected_headings:
            self.assertIn(heading, first_text)
        positions = [first_text.index(h) for h in expected_headings]
        self.assertEqual(positions, sorted(positions))

        self.assertEqual(first_text.count("![[tasks/all-tickets.base#Critical work]]"), 1)
        self.assertEqual(first_text.count("![[tasks/all-tickets.base#Today]]"), 1)
        self.assertEqual(first_text.count("![[tasks/all-tickets.base#Call Companion]]"), 1)
        self.assertEqual(first_text.count("![[tasks/all-tickets.base#Tomorrow candidates]]"), 1)
        self.assertEqual(first_text.count("![[tasks/all-tickets.base#Daily priorities]]"), 1)
        self.assertIn("- [ ] Keep this", first_text)
        self.assertIn("Keep this too.", first_text)
        self.assertEqual(first_text, second_text)

    def test_refresh_preserves_manual_planning_content(self):
        path = daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        text = path.read_text()
        text = text.replace(
            "## Available time\n",
            "## Available time\n| 09:00 - 10:00 | Deep work |\n"
        )
        text = text.replace(
            "## Now\n![[tasks/all-tickets.base#Today]]\n",
            "## Now\n![[tasks/all-tickets.base#Today]]\n- [ ] Hand typed item under Now\n- [x] Ticked item under Now\n"
        )
        path.write_text(text)

        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        refreshed_text = path.read_text()
        self.assertIn("| 09:00 - 10:00 | Deep work |", refreshed_text)
        self.assertIn("- [ ] Hand typed item under Now", refreshed_text)
        self.assertIn("- [x] Ticked item under Now", refreshed_text)

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

    def test_clears_planning_metadata_and_criticality_on_completion(self):
        ticket_path = _write_ticket(
            self.brain_path, "projects", "clear-the-garage", "planning-ticket",
            "Planning ticket", "prioritised",
            planned_for="2026-07-13", planning_lane="now", estimate_minutes="15",
            call_suitable="true", critical="true",
        )
        note = self.brain_path / "2026-07-13.md"
        text = note.read_text().replace(
            "## Project next actions\n",
            "## Project next actions\n- [x] Planning ticket — [[planning-ticket]]\n"
        )
        note.write_text(text)
        daily_note.close_daily_note(self.brain_path, now=MONDAY)
        ticket_text = (self.brain_path / ticket_path).read_text()
        self.assertIn("status: done", ticket_text)
        self.assertIn("resolved: 2026-07-13", ticket_text)
        self.assertNotIn("planned_for:", ticket_text)
        self.assertNotIn("planning_lane:", ticket_text)
        self.assertNotIn("estimate_minutes:", ticket_text)
        self.assertNotIn("call_suitable:", ticket_text)
        self.assertNotIn("critical:", ticket_text)

    def test_clears_multiline_planning_metadata_on_completion(self):
        ticket = self.brain_path / "tasks" / "projects" / "clear-the-garage" / "multiline-ticket.md"
        ticket.write_text(
            "---\nstatus: prioritised\nplanned_for: |\n  2026-07-13\n  continuation line\nplanning_lane: |\n  now\ncritical: |\n  true\n---\n\n# Multiline ticket\n"
        )
        note = self.brain_path / "2026-07-13.md"
        text = note.read_text().replace(
            "## Project next actions\n",
            "## Project next actions\n- [x] Multiline ticket — [[multiline-ticket]]\n"
        )
        note.write_text(text)
        daily_note.close_daily_note(self.brain_path, now=MONDAY)
        ticket_text = ticket.read_text()
        self.assertIn("status: done", ticket_text)
        self.assertIn("resolved: 2026-07-13", ticket_text)
        self.assertNotIn("planned_for:", ticket_text)
        self.assertNotIn("planning_lane:", ticket_text)
        self.assertNotIn("critical:", ticket_text)
        self.assertNotIn("continuation line", ticket_text)

    def test_action_log_entry_on_completion_mentions_clearing_planning_metadata(self):
        daily_note.close_daily_note(self.brain_path, now=MONDAY)
        log_text = (self.brain_path / "log" / "2026-07-13.md").read_text()
        self.assertIn(
            "Written back — status set to done in ticket frontmatter, temporary planning metadata and criticality cleared",
            log_text
        )


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

    def test_close_moves_archive_with_all_sections_intact_and_ticked_now_is_noop(self):
        daily_note.generate_daily_note(self.brain_path, now=MONDAY)
        note = self.brain_path / "2026-07-13.md"
        text = note.read_text().replace(
            "## Now\n![[tasks/all-tickets.base#Today]]\n",
            "## Now\n![[tasks/all-tickets.base#Today]]\n- [x] Ticked item under Now\n"
        )
        note.write_text(text)
        summary = daily_note.close_daily_note(self.brain_path, now=MONDAY)
        archived = self.brain_path / "archive" / "daily-notes" / "2026-07-13.md"
        self.assertTrue(archived.exists())
        archived_text = archived.read_text()
        self.assertIn("## Critical", archived_text)
        self.assertIn("- [x] Ticked item under Now", archived_text)

    def test_tomorrow_candidate_ticket_byte_identical_after_close_and_generate(self):
        ticket_path = _write_ticket(
            self.brain_path, "projects", "clear-the-garage", "tomorrow-ticket",
            "Tomorrow candidate ticket", "prioritised",
            planned_for="2026-07-14", planning_lane="tomorrow-candidate"
        )
        ticket_file = self.brain_path / ticket_path
        original_ticket_content = ticket_file.read_text()

        daily_note.close_daily_note(self.brain_path, now=MONDAY)
        daily_note.generate_daily_note(self.brain_path, now=MONDAY)

        self.assertEqual(ticket_file.read_text(), original_ticket_content)


if __name__ == "__main__":
    unittest.main()


class TestProposedFromMeetings(unittest.TestCase):
    """protocols/daily-note.md v3 — meetings/*.md `## Proposed` items mirrored
    into the daily note, additive-only and read-only."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "meetings").mkdir()
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n"
        )
        self.now = dt.datetime(2026, 7, 25, 9, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_note(self, filename, body):
        (self.brain_path / "meetings" / filename).write_text(body)

    def _generate(self):
        return daily_note.generate_daily_note(self.brain_path, now=self.now)

    def test_new_note_carries_proposed_items_as_plain_bullets(self):
        self._write_note(
            "2026-07-25 Planning call.md",
            "# Planning call\n\n## Proposed\n"
            "- [ ] Create a Person Hub for Dani\n- [ ] Close the pricing ticket?\n",
        )
        text = self._generate().read_text()
        self.assertIn("## Proposed from meetings", text)
        self.assertIn("- Create a Person Hub for Dani — [[2026-07-25 Planning call]]", text)
        self.assertIn("- Close the pricing ticket? — [[2026-07-25 Planning call]]", text)
        # Plain bullets, never checkboxes — a tick here would be a false
        # affordance, exactly as for Waiting for.
        self.assertNotIn("- [ ] Create a Person Hub for Dani", text)

    def test_section_sits_between_waiting_for_and_notes(self):
        text = self._generate().read_text()
        self.assertLess(text.index("## Waiting for"), text.index("## Proposed from meetings"))
        self.assertLess(text.index("## Proposed from meetings"), text.index("## Notes"))

    def test_same_day_rerun_is_additive_and_does_not_duplicate(self):
        self._write_note("2026-07-25 A.md", "# A\n\n## Proposed\n- [ ] first item\n")
        self._generate()

        self._write_note("2026-07-25 B.md", "# B\n\n## Proposed\n- [ ] second item\n")
        text = self._generate().read_text()

        self.assertEqual(text.count("- first item — [[2026-07-25 A]]"), 1)
        self.assertEqual(text.count("- second item — [[2026-07-25 B]]"), 1)

    def test_multiple_items_from_one_note_all_survive(self):
        """Dedupe is on the exact line, not the wikilink — deduping on the link
        would collapse these two into one."""
        self._write_note("2026-07-25 A.md", "# A\n\n## Proposed\n- [ ] one\n- [ ] two\n")
        self._generate()
        text = self._generate().read_text()
        self.assertIn("- one — [[2026-07-25 A]]", text)
        self.assertIn("- two — [[2026-07-25 A]]", text)

    def test_existing_lines_are_never_touched_or_reordered(self):
        self._write_note("2026-07-25 A.md", "# A\n\n## Proposed\n- [ ] first item\n")
        note_path = self._generate()

        edited = note_path.read_text().replace(
            "- first item — [[2026-07-25 A]]",
            "- first item — [[2026-07-25 A]] (mine, hand-annotated)",
        )
        note_path.write_text(edited)

        self._write_note("2026-07-25 B.md", "# B\n\n## Proposed\n- [ ] second item\n")
        text = self._generate().read_text()

        self.assertIn("(mine, hand-annotated)", text)
        self.assertIn("- second item — [[2026-07-25 B]]", text)

    def test_missing_heading_is_inserted_on_an_older_note(self):
        """A note generated before v3 has no such heading; appending into a
        missing heading is a silent no-op, so generation inserts it."""
        note_path = self.brain_path / "2026-07-25.md"
        note_path.write_text(
            "---\ntype: daily-note\ndate: 2026-07-25\n---\n\n"
            "# Saturday, 25 July 2026\n\n"
            "## Today's tasks\n- [ ] something\n\n"
            "## Project next actions\n\n"
            "## Waiting for\n\n"
            "## Notes\n- a note of mine\n"
        )
        self._write_note("2026-07-25 A.md", "# A\n\n## Proposed\n- [ ] first item\n")

        text = self._generate().read_text()
        self.assertIn("## Proposed from meetings", text)
        self.assertIn("- first item — [[2026-07-25 A]]", text)
        self.assertLess(text.index("## Proposed from meetings"), text.index("## Notes"))
        self.assertIn("- a note of mine", text)
        self.assertIn("- [ ] something", text)

    def test_generation_never_writes_back_to_a_meeting_note(self):
        body = "# A\n\n## Proposed\n- [ ] first item\n"
        self._write_note("2026-07-25 A.md", body)
        self._generate()
        self._generate()
        self.assertEqual((self.brain_path / "meetings" / "2026-07-25 A.md").read_text(), body)

    def test_no_meetings_folder_is_not_an_error(self):
        empty = Path(tempfile.mkdtemp())
        (empty / "config").mkdir()
        (empty / "config" / "routine-state.md").write_text("| Routine | Last run |\n|---|---|\n")
        text = daily_note.generate_daily_note(empty, now=self.now).read_text()
        self.assertIn("## Proposed from meetings", text)


class TestEmptySectionDoesNotSwallowFollowingSections(unittest.TestCase):
    """Regression for a pre-existing data-loss bug found while adding the
    Proposed-from-meetings section.

    `_replace_section`/`_append_new_lines_to_section` matched the heading with
    `\\s*\\n`. `\\s` matches newlines, so on an EMPTY section it consumed the
    blank line and the captured "body" became every section that followed —
    which `_replace_section` then overwrote. A daily note with no open Waiting
    For items therefore lost `## Notes` (where the user writes) and everything
    after it on the next same-day regeneration."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n"
        )
        self.now = dt.datetime(2026, 7, 25, 9, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_replace_section_on_an_empty_section_keeps_what_follows(self):
        text = ("# Sat\n\n## Today's tasks\n- [ ] something\n\n"
                "## Waiting for\n\n"
                "## Notes\n- a note of mine\n")
        out = daily_note._replace_section(text, "Waiting for", [])
        self.assertIn("## Notes", out)
        self.assertIn("- a note of mine", out)

    def test_replace_section_still_replaces_a_populated_section(self):
        text = ("## Waiting for\n- stale item — [[Old]]\n\n"
                "## Notes\n- a note of mine\n")
        out = daily_note._replace_section(text, "Waiting for", ["- fresh item — [[New]]"])
        self.assertIn("- fresh item — [[New]]", out)
        self.assertNotIn("- stale item", out)
        self.assertIn("- a note of mine", out)

    def test_append_into_an_empty_section_lands_under_its_own_heading(self):
        text = ("## Project next actions\n\n"
                "## Notes\n- a note of mine\n")
        out = daily_note._append_new_lines_to_section(
            text, "Project next actions", lambda c, e: False, ["- [ ] new — [[T]]"])
        self.assertLess(out.index("- [ ] new — [[T]]"), out.index("## Notes"))
        self.assertIn("- a note of mine", out)

    def test_end_to_end_regeneration_preserves_user_notes(self):
        note_path = self.brain_path / "2026-07-25.md"
        daily_note.generate_daily_note(self.brain_path, now=self.now)

        text = note_path.read_text().replace("## Notes\n", "## Notes\n- my hand-written note\n")
        note_path.write_text(text)

        daily_note.generate_daily_note(self.brain_path, now=self.now)
        self.assertIn("- my hand-written note", note_path.read_text())


class TestFrontmatterBlockScalarAndDuplicateCleanup(unittest.TestCase):
    def test_completion_clears_multiline_block_scalars_with_internal_and_leading_blank_lines(self):
        text = (
            "---\n"
            "status: in-progress\n"
            "planned_for: |\n"
            "\n"
            "  2026-08-04\n"
            "planning_lane: |\n"
            "  now\n"
            "\n"
            "  later\n"
            "---\n\n"
            "# Ticket\n"
        )
        updated = daily_note._update_frontmatter(text, {"status": "done"})
        self.assertIn("status: done", updated)
        self.assertNotIn("planned_for", updated)
        self.assertNotIn("planning_lane", updated)
        self.assertNotIn("2026-08-04", updated)
        self.assertNotIn("later", updated)

    def test_completion_clears_duplicate_planning_keys(self):
        text = (
            "---\n"
            "status: in-progress\n"
            "planned_for: 2026-08-04\n"
            "planned_for: 2026-08-10\n"
            "---\n\n"
            "# Ticket\n"
        )
        updated = daily_note._update_frontmatter(text, {"status": "done"})
        self.assertIn("status: done", updated)
        self.assertNotIn("planned_for", updated)


class TestDraftLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.brain_path = Path(self.temp_dir.name)
        self.archive_dir = self.brain_path / "archive" / "daily-notes"
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_draft_parsing_and_states(self):
        text = (
            "## Drafts to review and send\n"
            "- [ ] [draft] Follow up with Sam — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Send quote — [[Ticket 12]]\n"
            "    - [x] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Trash this — [[Ticket 13]]\n"
            "    - [ ] Send\n"
            "    - [x] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Push to tomorrow — [[Ticket 14]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [x] Carry forward\n"
        )
        drafts = daily_note.parse_drafts(text)
        self.assertEqual(len(drafts), 4)
        self.assertEqual(drafts[0].state, "draft")
        self.assertEqual(drafts[1].state, "sent")
        self.assertEqual(drafts[2].state, "discarded")
        self.assertEqual(drafts[3].state, "carried-forward")

    def test_close_rewrites_unresolved_drafts_to_carried_forward(self):
        note_date = dt.datetime(2026, 7, 12, 10, 0)
        note_path = self.brain_path / "2026-07-12.md"
        note_path.write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] Unresolved draft — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Sent draft — [[Ticket 1]]\n"
            "    - [x] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n\n"
            "## Project next actions\n\n"
        )
        daily_note.close_daily_note(self.brain_path, now=note_date)
        archived_path = self.archive_dir / "2026-07-12.md"
        self.assertTrue(archived_path.exists())
        archived_text = archived_path.read_text()
        self.assertIn("- [ ] [carried-forward] Unresolved draft — [[Sam Patel]]", archived_text)
        self.assertIn("    - [x] Carry forward", archived_text)
        self.assertIn("- [x] [sent] Sent draft — [[Ticket 1]]", archived_text)

    def test_generate_carries_forward_only_unresolved_drafts(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            "## Drafts to review and send\n"
            "- [ ] [carried-forward] Unresolved draft — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [x] Carry forward\n"
            "- [ ] [draft] Sent draft — [[Ticket 1]]\n"
            "    - [x] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Discarded draft — [[Ticket 2]]\n"
            "    - [ ] Send\n"
            "    - [x] Discard\n"
            "    - [ ] Carry forward\n\n"
        )
        monday = dt.datetime(2026, 7, 13, 10, 0)
        path = daily_note.generate_daily_note(self.brain_path, now=monday)
        text = path.read_text()
        section = text.split("## Drafts to review and send\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("- [ ] [carried-forward] Unresolved draft — [[Sam Patel]]", section)

        self.assertNotIn("Sent draft", section)
        self.assertNotIn("Discarded draft", section)

    def test_refresh_deduplicates_drafts(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [carried-forward] Draft 1 — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [x] Carry forward\n"
        )
        monday = dt.datetime(2026, 7, 13, 10, 0)
        path = daily_note.generate_daily_note(self.brain_path, now=monday)
        # Refresh again
        path = daily_note.generate_daily_note(self.brain_path, now=monday)
        text = path.read_text()
        self.assertEqual(text.count("Draft 1"), 1)

    def test_prove_no_external_send(self):
        import sys
        import subprocess
        import socket

        # (a) No networking module in sys.modules after a clean import of daily_note
        cmd = [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; sys.path.insert(0, str(Path('scripts').resolve())); "
            "import daily_note; "
            "banned = ['socket', 'requests', 'httpx', 'urllib.request', 'smtplib']; "
            "loaded = [m for m in banned if m in sys.modules]; "
            "assert not loaded, f'Networking modules loaded: {loaded}'"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))
        self.assertEqual(res.returncode, 0, f"Clean import check failed: {res.stderr}")

        # (b) Monkeypatch subprocess.run and socket.socket to raise, then drive draft transitions
        def block_socket(*args, **kwargs):
            raise RuntimeError("Network call attempted via socket")

        def block_subprocess(*args, **kwargs):
            raise RuntimeError("Subprocess call attempted")

        original_socket = socket.socket
        original_run = subprocess.run
        try:
            socket.socket = block_socket
            subprocess.run = block_subprocess

            # Drive draft through generate -> user transition (draft -> sent) -> close
            note_date = dt.datetime(2026, 7, 12, 10, 0)
            (self.archive_dir / "2026-07-11.md").write_text(
                "---\ntype: daily-note\ndate: 2026-07-11\ntags:\n  - daily-note\n---\n\n"
                "## Drafts to review and send\n"
                "- [ ] [draft] Follow up with Sam — [[Sam Patel]]\n"
                "    - [ ] Send\n"
                "    - [ ] Discard\n"
                "    - [ ] Carry forward\n"
            )
            note_path = daily_note.generate_daily_note(self.brain_path, now=note_date)
            text = note_path.read_text()
            self.assertIn("Follow up with Sam", text)

            # User marks Send in markdown
            updated_text = text.replace(
                "    - [ ] Send",
                "    - [x] Send"
            )
            note_path.write_text(updated_text)

            # Close daily note
            summary = daily_note.close_daily_note(self.brain_path, now=note_date)
            self.assertTrue(summary["archived_to"].exists())
        finally:
            socket.socket = original_socket
            subprocess.run = original_run

    def test_finding_1_parse_drafts_absent_section(self):
        text = (
            "# Sunday, 12 July 2026\n\n"
            "## Project next actions\n"
            "- [ ] [draft] Ship the pricing model — [[goals-os-14]]\n"
            "- [x] Done action — [[goals-os-15]]\n"
        )
        drafts = daily_note.parse_drafts(text)
        self.assertEqual(drafts, [])

    def test_finding_2_close_preserves_ticked_header(self):
        note_date = dt.datetime(2026, 7, 12, 10, 0)
        note_path = self.brain_path / "2026-07-12.md"
        note_path.write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            "## Drafts to review and send\n"
            "- [x] [draft] Follow up with Sam — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n\n"
        )
        daily_note.close_daily_note(self.brain_path, now=note_date)
        archived_path = self.archive_dir / "2026-07-12.md"
        self.assertTrue(archived_path.exists())
        archived_text = archived_path.read_text()
        self.assertIn("- [x] [sent] Follow up with Sam — [[Sam Patel]]", archived_text)
        self.assertIn("    - [x] Send", archived_text)

        monday = dt.datetime(2026, 7, 13, 10, 0)
        mon_path = daily_note.generate_daily_note(self.brain_path, now=monday)
        self.assertNotIn("Follow up with Sam", mon_path.read_text())

    def test_finding_3_unified_parser(self):
        # Verify parse_drafts and _rewrite_closed_drafts produce consistent draft parsing
        text = (
            "## Drafts to review and send\n"
            "- [x] [draft] Follow up — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        drafts = daily_note.parse_drafts(text)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].state, "sent")
        rewritten = daily_note._rewrite_closed_drafts(text)
        self.assertIn("- [x] [sent] Follow up — [[Sam Patel]]", rewritten)

    def test_finding_4_refresh_dedupes_edited_drafts_by_wikilink(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [carried-forward] Follow up with Sam — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [x] Carry forward\n"
        )
        monday = dt.datetime(2026, 7, 13, 10, 0)
        path = daily_note.generate_daily_note(self.brain_path, now=monday)
        # User edits the description of the draft in Monday's note
        edited_text = path.read_text().replace(
            "Follow up with Sam",
            "Follow up with Sam on pricing"
        )
        path.write_text(edited_text)

        # Refresh daily note on same day
        path = daily_note.generate_daily_note(self.brain_path, now=monday)
        text = path.read_text()
        self.assertEqual(text.count("[[Sam Patel]]"), 1)
        self.assertIn("Follow up with Sam on pricing", text)

    def test_finding_5_carried_forward_state_preserved_on_carry(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [carried-forward] Follow up — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [x] Carry forward\n"
        )
        monday = dt.datetime(2026, 7, 13, 10, 0)
        path = daily_note.generate_daily_note(self.brain_path, now=monday)
        text = path.read_text()
        self.assertIn("- [ ] [carried-forward] Follow up — [[Sam Patel]]", text)

    def test_finding_6_sent_and_discarded_written_to_archive_tag(self):
        text = (
            "## Drafts to review and send\n"
            "- [ ] [draft] Send item — [[Ticket 1]]\n"
            "    - [x] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Discard item — [[Ticket 2]]\n"
            "    - [ ] Send\n"
            "    - [x] Discard\n"
            "    - [ ] Carry forward\n"
        )
        rewritten = daily_note._rewrite_closed_drafts(text)
        self.assertIn("- [x] [sent] Send item — [[Ticket 1]]", rewritten)
        self.assertIn("- [x] [discarded] Discard item — [[Ticket 2]]", rewritten)

    def test_finding_7_interleaved_lines_no_duplicate_subcheckboxes(self):
        text = (
            "## Drafts to review and send\n"
            "- [ ] [draft] Item with note — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    Note: check details first\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        rewritten = daily_note._rewrite_closed_drafts(text)
        self.assertEqual(rewritten.count("Discard"), 1)
        self.assertEqual(rewritten.count("Carry forward"), 1)

    def test_finding_8_multiple_options_ticked_diagnostic(self):
        import io
        import sys
        text = (
            "## Drafts to review and send\n"
            "- [ ] [draft] Conflicting draft — [[Sam Patel]]\n"
            "    - [x] Send\n"
            "    - [x] Discard\n"
            "    - [ ] Carry forward\n"
        )
        stderr_trap = io.StringIO()
        orig_stderr = sys.stderr
        try:
            sys.stderr = stderr_trap
            drafts = daily_note.parse_drafts(text)
        finally:
            sys.stderr = orig_stderr
        self.assertEqual(drafts[0].state, "sent")
        self.assertIn("Multiple draft options checked", stderr_trap.getvalue())

    def test_finding_9_adr0041_matches_canonical_template(self):
        adr_path = Path(__file__).parent.parent / "docs" / "adr" / "0041-draft-lifecycle-and-carry-forward-in-the-daily-note.md"
        self.assertTrue(adr_path.exists())
        adr_text = adr_path.read_text()
        self.assertNotIn("Deciders:", adr_text)
        self.assertIn("Decided ", adr_text)
        self.assertTrue(adr_text.startswith("# Draft lifecycle and carry-forward in the daily note\n"))

    def test_refresh_carries_draft_into_preexisting_note(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [carried-forward] Carried draft from yesterday — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [x] Carry forward\n"
        )
        monday = dt.datetime(2026, 7, 13, 10, 0)
        # Pre-create Monday's note without any drafts section or drafts
        mon_path = self.brain_path / "2026-07-13.md"
        mon_path.write_text(
            "---\ntype: daily-note\ndate: 2026-07-13\ntags:\n  - daily-note\n---\n\n"
            "# Monday, 13 July 2026\n\n"
            "## Today's tasks\n"
            "- [ ] Existing task\n"
        )

        # Refresh daily note on Monday
        daily_note.generate_daily_note(self.brain_path, now=monday)
        text = mon_path.read_text()
        self.assertIn("## Drafts to review and send", text)
        self.assertIn("- [ ] [carried-forward] Carried draft from yesterday — [[Sam Patel]]", text)

    def test_ticked_carried_forward_header_archives_as_sent(self):
        note_date = dt.datetime(2026, 7, 12, 10, 0)
        note_path = self.brain_path / "2026-07-12.md"
        note_path.write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            "## Drafts to review and send\n"
            "- [x] [carried-forward] Follow up with Sam — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n\n"
        )
        daily_note.close_daily_note(self.brain_path, now=note_date)
        archived_path = self.archive_dir / "2026-07-12.md"
        self.assertTrue(archived_path.exists())
        archived_text = archived_path.read_text()
        self.assertIn("- [x] [sent] Follow up with Sam — [[Sam Patel]]", archived_text)
        self.assertIn("    - [x] Send", archived_text)

        monday = dt.datetime(2026, 7, 13, 10, 0)
        mon_path = daily_note.generate_daily_note(self.brain_path, now=monday)
        self.assertNotIn("Follow up with Sam", mon_path.read_text())

    def test_close_preserves_unrecognized_indented_lines(self):
        note_date = dt.datetime(2026, 7, 12, 10, 0)
        note_path = self.brain_path / "2026-07-12.md"
        note_path.write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "# Sunday, 12 July 2026\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] Item — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    Note: called Sam, he wants revised numbers first\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n\n"
        )
        daily_note.close_daily_note(self.brain_path, now=note_date)
        archived_path = self.archive_dir / "2026-07-12.md"
        self.assertTrue(archived_path.exists())
        archived_text = archived_path.read_text()
        self.assertIn("Note: called Sam, he wants revised numbers first", archived_text)

    def test_finding_4_docs_specify_header_tick_to_sent(self):
        protocol_path = Path(__file__).parent.parent / "protocols" / "daily-note.md"
        adr_path = Path(__file__).parent.parent / "docs" / "adr" / "0041-draft-lifecycle-and-carry-forward-in-the-daily-note.md"
        proto_text = protocol_path.read_text()
        adr_text = adr_path.read_text()
        self.assertIn("ticking the top-level draft checkbox", proto_text)
        self.assertIn("ticked top-level task checkbox", adr_text)

    def test_finding_5_tag_parsing(self):
        # Ensure all four valid tags parse cleanly
        for tag in ("draft", "sent", "discarded", "carried-forward"):
            text = (
                "## Drafts to review and send\n"
                f"- [ ] [{tag}] Test draft — [[Sam Patel]]\n"
                "    - [ ] Send\n"
                "    - [ ] Discard\n"
                "    - [ ] Carry forward\n"
            )
            drafts = daily_note.parse_drafts(text)
            self.assertEqual(len(drafts), 1)
            self.assertEqual(drafts[0].tag, tag)

    def test_two_distinct_drafts_same_wikilink_carry_and_survive_refresh(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] First draft for Sam — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Second draft for Sam — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        monday = dt.datetime(2026, 7, 13, 10, 0)
        path = daily_note.generate_daily_note(self.brain_path, now=monday)
        text = path.read_text()
        self.assertIn("First draft for Sam", text)
        self.assertIn("Second draft for Sam", text)

        # Refresh daily note on Monday
        path_refreshed = daily_note.generate_daily_note(self.brain_path, now=monday)
        text_refreshed = path_refreshed.read_text()
        self.assertIn("First draft for Sam", text_refreshed)
        self.assertIn("Second draft for Sam", text_refreshed)
        self.assertEqual(text_refreshed.count("First draft for Sam"), 1)
        self.assertEqual(text_refreshed.count("Second draft for Sam"), 1)

    def test_draft_carried_across_three_days_preserves_original_marker(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] Persistent draft — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        day2 = dt.datetime(2026, 7, 13, 10, 0)
        d2_path = daily_note.generate_daily_note(self.brain_path, now=day2)
        d2_text = d2_path.read_text()
        self.assertIn("^d20260712-1", d2_text)
        daily_note.close_daily_note(self.brain_path, now=day2)

        day3 = dt.datetime(2026, 7, 14, 10, 0)
        d3_path = daily_note.generate_daily_note(self.brain_path, now=day3)
        d3_text = d3_path.read_text()
        self.assertIn("^d20260712-1", d3_text)
        self.assertNotIn("^d20260713", d3_text)

    def test_editing_carried_draft_text_then_refreshing_does_not_duplicate(self):
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] Initial draft text — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        monday = dt.datetime(2026, 7, 13, 10, 0)
        mon_path = daily_note.generate_daily_note(self.brain_path, now=monday)
        text = mon_path.read_text()

        edited_text = text.replace("Initial draft text", "Edited draft text by user")
        mon_path.write_text(edited_text)

        daily_note.generate_daily_note(self.brain_path, now=monday)
        refreshed_text = mon_path.read_text()
        self.assertIn("Edited draft text by user", refreshed_text)
        self.assertNotIn("Initial draft text", refreshed_text)
        self.assertEqual(refreshed_text.count("Edited draft text by user"), 1)

    def test_legacy_draft_line_with_no_marker_parses_carries_and_gains_marker(self):
        legacy_text = (
            "## Drafts to review and send\n"
            "- [ ] [draft] Legacy draft without marker — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        drafts = daily_note.parse_drafts(legacy_text)
        self.assertEqual(len(drafts), 1)
        self.assertIsNone(drafts[0].origin_marker)

        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            + legacy_text
        )
        monday = dt.datetime(2026, 7, 13, 10, 0)
        mon_path = daily_note.generate_daily_note(self.brain_path, now=monday)
        gen_text = mon_path.read_text()
        self.assertIn("Legacy draft without marker", gen_text)
        self.assertIn("^d20260712-1", gen_text)

    def test_round_trip_parse_and_render_marked_draft_line(self):
        marked_text = (
            "## Drafts to review and send\n"
            "- [ ] [carried-forward] Draft TWO about the contract — [[Sam Patel]] ^d20260712-2\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        drafts = daily_note.parse_drafts(marked_text)
        self.assertEqual(len(drafts), 1)
        rendered_lines = drafts[0].render()
        expected_lines = [
            "- [ ] [carried-forward] Draft TWO about the contract — [[Sam Patel]] ^d20260712-2",
            "    - [ ] Send",
            "    - [ ] Discard",
            "    - [ ] Carry forward",
        ]
        self.assertEqual(rendered_lines, expected_lines)

    def test_marker_collision_drops_live_draft_after_same_day_close_then_regenerate(self):
        # 1. close_daily_note(2026-07-13) archives a note holding one unmarked draft Alpha
        d1 = dt.datetime(2026, 7, 13, 9, 0)
        note_13 = self.brain_path / "2026-07-13.md"
        note_13.write_text(
            "---\ntype: daily-note\ndate: 2026-07-13\ntags:\n  - daily-note\n---\n\n"
            "# Monday, 13 July 2026\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] Alpha — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n\n"
        )
        daily_note.close_daily_note(self.brain_path, now=d1)

        # 2. generate_daily_note(2026-07-13) same evening -> Alpha carried in as ^d20260713-1
        daily_note.generate_daily_note(self.brain_path, now=d1)
        gen13_text = note_13.read_text()
        self.assertIn("Alpha — [[Sam Patel]] ^d20260713-1", gen13_text)

        # 3. User hand-writes a new draft BRAND NEW above Alpha; close again -> archive holds
        # [BRAND NEW (unmarked, idx 1), Alpha ^d20260713-1 (idx 2)]
        note_13.write_text(
            "---\ntype: daily-note\ndate: 2026-07-13\ntags:\n  - daily-note\n---\n\n"
            "# Monday, 13 July 2026\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] BRAND NEW — [[Ticket 1]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [carried-forward] Alpha — [[Sam Patel]] ^d20260713-1\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n\n"
        )
        daily_note.close_daily_note(self.brain_path, now=d1)

        # 4. generate_daily_note(2026-07-14) -> assert both drafts are present and distinctly marked
        d2 = dt.datetime(2026, 7, 14, 9, 0)
        note_14 = daily_note.generate_daily_note(self.brain_path, now=d2)
        gen14_text = note_14.read_text()

        self.assertIn("BRAND NEW — [[Ticket 1]] ^d20260713-2", gen14_text)
        self.assertIn("Alpha — [[Sam Patel]] ^d20260713-1", gen14_text)

    def test_stray_archive_filename_filtered_out_by_shared_helper(self):
        (self.archive_dir / "2026-07-11.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-11\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] Beta — [[Ticket 2]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n\n"
            "## Today's tasks\n"
            "- [ ] Valid task from 11th\n"
        )
        # Create a sync conflict copy in archive
        (self.archive_dir / "2026-07-12 (conflict).md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] Alpha — [[Sam Patel]]\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n\n"
            "## Today's tasks\n"
            "- [ ] Conflict task from 12th\n"
        )

        d_now = dt.datetime(2026, 7, 13, 9, 0)
        note_13 = daily_note.generate_daily_note(self.brain_path, now=d_now)
        text_13 = note_13.read_text()

        self.assertNotIn("(conflict)", text_13)
        self.assertIn("Beta — [[Ticket 2]] ^d20260711-1", text_13)
        self.assertIn("Valid task from 11th", text_13)

    def test_source_archive_edit_warns_on_collision_or_gap(self):
        import io
        (self.archive_dir / "2026-07-11.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-11\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] First — [[Ticket 1]] ^d20260711-1\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Second — [[Ticket 2]] ^d20260711-1\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        d_now = dt.datetime(2026, 7, 12, 9, 0)
        stderr_trap = io.StringIO()
        with unittest.mock.patch("sys.stderr", stderr_trap):
            daily_note.generate_daily_note(self.brain_path, now=d_now)
        self.assertIn("Warning: Duplicate draft origin marker 'd20260711-1' detected in archive.", stderr_trap.getvalue())

        (self.brain_path / "2026-07-12.md").unlink(missing_ok=True)
        (self.archive_dir / "2026-07-12.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-12\ntags:\n  - daily-note\n---\n\n"
            "## Drafts to review and send\n"
            "- [ ] [draft] One — [[Ticket 1]] ^d20260712-1\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
            "- [ ] [draft] Three — [[Ticket 3]] ^d20260712-3\n"
            "    - [ ] Send\n"
            "    - [ ] Discard\n"
            "    - [ ] Carry forward\n"
        )
        d_now2 = dt.datetime(2026, 7, 13, 9, 0)
        stderr_trap2 = io.StringIO()
        with unittest.mock.patch("sys.stderr", stderr_trap2):
            daily_note.generate_daily_note(self.brain_path, now=d_now2)
        self.assertIn("Warning: Gap detected in draft origin markers for '20260712': missing [2].", stderr_trap2.getvalue())

    def test_adr_0041_reflects_carried_forward_only_and_lowest_free_ordinal_rule(self):
        adr_path = Path(__file__).parent.parent / "docs" / "adr" / "0041-draft-lifecycle-and-carry-forward-in-the-daily-note.md"
        adr_text = adr_path.read_text()
        self.assertNotIn("or [draft]", adr_text)
        self.assertIn("lowest positive integer ordinal", adr_text)

    def test_skill_descriptions_mention_origin_markers(self):
        gen_skill = Path(__file__).parent.parent / "adapters" / "claude-code" / "skills" / "daily-note-generate" / "SKILL.md"
        close_skill = Path(__file__).parent.parent / "adapters" / "claude-code" / "skills" / "daily-note-close" / "SKILL.md"
        self.assertIn("origin marker", gen_skill.read_text())
        self.assertIn("origin marker", close_skill.read_text())

    def test_daily_note_imports_unittest_mock(self):
        test_file = Path(__file__)
        content = test_file.read_text()
        top_imports = "\n".join(content.splitlines()[:20])
        self.assertTrue(
            "import unittest.mock" in top_imports or "from unittest import mock" in top_imports,
            "tests/test_daily_note.py must explicitly import unittest.mock at top",
        )

    def test_protocol_draft_identity_wording(self):
        protocol_path = Path(__file__).parent.parent / "protocols" / "daily-note.md"
        protocol_text = protocol_path.read_text()
        self.assertNotIn("1-based ordinal position in that day's Drafts section", protocol_text)
        self.assertIn("lowest positive integer ordinal", protocol_text)
















