import datetime as dt
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import dashboard  # noqa: E402


class TestRenderDashboard(unittest.TestCase):
    def test_renders_overdue_pending_and_log_sections(self):
        data = {
            "generated": "2026-07-11 21:50",
            "date_str": "2026-07-11",
            "overdue": [{"routine": "Triage", "last_run": "never", "cadence_days": 1}],
            "pending_plans": [{"path": Path("inbox/triage/2026-07-11-voice.md"), "total": 2, "ticked": 1, "pending": 1}],
            "pending_rule_diffs": [{"path": Path("inbox/rule-diffs/2026-07-11-routing-rules.md"), "total": 2, "decided": 1, "pending": 1}],
            "awaiting_review_tickets": [{"title": "Surface awaiting-review on the Dashboard", "path": Path("tasks/projects/goals-os/surface-awaiting-review-on-the-dashboard.md")}],
            "waiting_for": [{"person": "Jane Doe", "path": Path("people/Jane Doe.md"), "text": "Jane to send over the draft budget"}],
            "action_log": {"exists": True, "entry_count": 2, "unreviewed": 2, "date_str": "2026-07-11"},
            "dropzone": [
                {"name": "Expenses", "count": 3},
                {"name": "Homework", "count": 1},
                {"name": "Recipes", "count": 2},
            ],
        }
        text = dashboard.render_dashboard(data)
        self.assertIn("Triage (last run: never)", text)
        self.assertIn("[[inbox/triage/2026-07-11-voice.md]]", text)
        self.assertIn("1 ticked, 1 awaiting approval", text)
        self.assertIn("## Pending review", text)
        self.assertIn("[[inbox/rule-diffs/2026-07-11-routing-rules.md]]", text)
        self.assertIn("2 diff(s), 1 decided, 1 awaiting review", text)
        self.assertIn("## Tickets awaiting review", text)
        self.assertIn("- **Surface awaiting-review on the Dashboard** ([[tasks/projects/goals-os/surface-awaiting-review-on-the-dashboard.md]])", text)
        self.assertIn("**Jane Doe** — Jane to send over the draft budget ([[people/Jane Doe.md]])", text)
        self.assertIn("2 entries logged today", text)
        self.assertIn("2 awaiting your feedback", text)
        self.assertIn("## 📁 Dropzone awaiting processing", text)
        self.assertIn("- Expenses: 3 waiting", text)
        self.assertIn("- Homework: 1 waiting", text)
        self.assertIn("- Recipes: 2 waiting", text)

    def test_renders_empty_states(self):
        data = {
            "generated": "2026-07-11 21:50", "date_str": "2026-07-11",
            "overdue": [], "pending_plans": [], "pending_rule_diffs": [], "awaiting_review_tickets": [], "waiting_for": [],
            "action_log": {"exists": False, "entry_count": 0, "unreviewed": 0, "date_str": "2026-07-11"},
            "dropzone": [
                {"name": "Expenses", "count": 0},
                {"name": "Homework", "count": 0},
                {"name": "Recipes", "count": 0},
            ],
        }
        text = dashboard.render_dashboard(data)
        self.assertIn("Nothing overdue.", text)
        self.assertIn("No pending Triage Plans.", text)
        self.assertIn("No pending rule-diff reviews.", text)
        self.assertIn("No tickets awaiting review.", text)
        self.assertIn("Nothing open.", text)
        self.assertIn("No Action Log entries yet today.", text)
        self.assertIn("- Expenses: 0 waiting", text)
        self.assertIn("- Homework: 0 waiting", text)
        self.assertIn("- Recipes: 0 waiting", text)


class TestPendingRuleDiffs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "inbox" / "rule-diffs").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_batch(self, filename, body):
        (self.brain_path / "inbox" / "rule-diffs" / filename).write_text(body)

    def test_finds_pending_batch_with_decided_and_undecided_counts(self):
        self._write_batch(
            "2026-07-15-routing-rules.md",
            "---\ntype: rule-diff-batch\nruleset: routing-rules\ndate: 2026-07-15\nstatus: pending\n---\n\n"
            "# Rule diffs — routing-rules — 2026-07-15\n\n"
            "### Diff 1 — sonia-email-to-work\n\n```\nif: source == \"email\"\nthen: route -> areas/work/_inbox.md\n```\n\n"
            "**Why:** rationale\n\n**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]\n\n"
            "- [x] (applied) Approve\n- [ ] Reject\n\n"
            "### Diff 2 — junk-newsletter-discard\n\n```\nif: source == \"email\"\nthen: route -> discard\n```\n\n"
            "**Why:** rationale\n\n**Evidence:** [[log/2026-07-09#08:00 — file-email]], [[log/2026-07-10#08:05 — file-email]]\n\n"
            "- [ ] Approve\n- [ ] Reject\n",
        )
        batches = dashboard._pending_rule_diffs(self.brain_path)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["total"], 2)
        self.assertEqual(batches[0]["decided"], 1)
        self.assertEqual(batches[0]["pending"], 1)

    def test_ignores_resolved_batches_and_missing_dir(self):
        self._write_batch(
            "2026-07-14-routing-rules.md",
            "---\ntype: rule-diff-batch\nruleset: routing-rules\ndate: 2026-07-14\nstatus: resolved\n---\n\nnothing pending\n",
        )
        self.assertEqual(dashboard._pending_rule_diffs(self.brain_path), [])

        empty_brain = Path(tempfile.mkdtemp())
        self.assertEqual(dashboard._pending_rule_diffs(empty_brain), [])


class TestOpenWaitingFor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "people").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_hub(self, filename, body):
        (self.brain_path / "people" / filename).write_text(body)

    def test_finds_open_items_with_canonical_schema_heading(self):
        # protocols/people-tracking.md's schema heading, exactly as authored.
        self._write_hub(
            "Jane Doe.md",
            "---\nname: Jane Doe\n---\n\n"
            "# Jane Doe\n> Some Role\n\n"
            "## ⏳ Waiting For\n"
            "- [ ] #waiting-for Jane to send over the draft budget\n"
            "- [x] #waiting-for Jane to share the meeting agenda\n"
            "- [ ] ~~#waiting-for Already closed via strikethrough~~ done 19/06\n"
            "\n## 🧠 Context\n- some context\n",
        )
        items = dashboard._open_waiting_for(self.brain_path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["person"], "Jane Doe")
        self.assertIn("send over the draft budget", items[0]["text"])

    def test_tolerates_a_heading_without_the_emoji(self):
        # Real v1 hub data was inconsistent here before migration (some hubs
        # used "## Waiting For" with no emoji) — the regex is deliberately
        # tolerant of this, so this fixture exercises that tolerance
        # specifically, separate from the canonical-heading case above.
        self._write_hub(
            "John Smith.md",
            "---\nname: John Smith\n---\n\n"
            "## Waiting For\n"
            "- [ ] #waiting-for John to send over the draft budget\n"
            "\n## Context\n- some context\n",
        )
        items = dashboard._open_waiting_for(self.brain_path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["person"], "John Smith")

    def test_ignores_alias_file_and_missing_people_dir(self):
        self._write_hub("_aliases.md", "## Waiting For\n- [ ] #waiting-for should not count\n")
        self.assertEqual(dashboard._open_waiting_for(self.brain_path), [])

        empty_brain = Path(tempfile.mkdtemp())
        self.assertEqual(dashboard._open_waiting_for(empty_brain), [])


class TestDropzoneCounts(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Files/dropzone/ lives as a sibling of the Brain root, not inside it
        # (Documents/Vault vs Documents/Files/dropzone) — see
        # tickets/capture-source-plugins/execution/shared-context.md.
        self.documents_root = Path(self._tmp.name)
        self.brain_path = self.documents_root / "Vault"
        self.brain_path.mkdir()
        self.dropzone = self.documents_root / "Files" / "dropzone"

    def tearDown(self):
        self._tmp.cleanup()

    def _touch(self, *parts):
        p = self.dropzone.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")

    def test_counts_files_per_subfolder_in_spec_order(self):
        self._touch("Expenses", "a.pdf")
        self._touch("Expenses", "b.pdf")
        self._touch("Expenses", "c.pdf")
        self._touch("Homework", "spelling.jpg")
        self._touch("Recipes", "curry.jpg")
        self._touch("Recipes", "soup.jpg")

        counts = dashboard._dropzone_counts(self.brain_path)
        self.assertEqual(
            counts,
            [
                {"name": "Expenses", "count": 3},
                {"name": "Homework", "count": 1},
                {"name": "Recipes", "count": 2},
            ],
        )

    def test_missing_dropzone_returns_zero_counts(self):
        # No Files/dropzone/ at all — still returns the three named
        # subfolders, all zero, rather than an empty list.
        counts = dashboard._dropzone_counts(self.brain_path)
        self.assertEqual(
            counts,
            [
                {"name": "Expenses", "count": 0},
                {"name": "Homework", "count": 0},
                {"name": "Recipes", "count": 0},
            ],
        )

    def test_non_recursive_ignores_nested_files(self):
        # Homework/ has real-world sub-subfolders (Student One/Student Two/Both) — the
        # spec is explicit this section is top-level-only, so files nested
        # a level deeper don't count.
        self._touch("Homework", "Student One", "spelling.jpg")
        self._touch("Homework", "top-level.jpg")

        counts = dashboard._dropzone_counts(self.brain_path)
        homework = next(c for c in counts if c["name"] == "Homework")
        self.assertEqual(homework["count"], 1)

    def test_ignores_hidden_files(self):
        self._touch("Recipes", ".DS_Store")
        self._touch("Recipes", "curry.jpg")

        counts = dashboard._dropzone_counts(self.brain_path)
        recipes = next(c for c in counts if c["name"] == "Recipes")
        self.assertEqual(recipes["count"], 1)


class TestAwaitingReviewTickets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_ticket(self, rel_path, body):
        p = self.brain_path / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)

    def test_finds_awaiting_review_tickets(self):
        self._write_ticket(
            "tasks/projects/goals-os/my-feature.md",
            "---\nstatus: awaiting-review\ntype: task\n---\n\n# Build My Feature\n\nSome body\n"
        )
        self._write_ticket(
            "tasks/areas/work/review-budget.md",
            "---\nstatus: awaiting-review\ntype: task\n---\n\n# Review Annual Budget\n\nSome body\n"
        )
        self._write_ticket(
            "tasks/projects/goals-os/other-task.md",
            "---\nstatus: in-progress\ntype: task\n---\n\n# In Progress Task\n"
        )
        tickets = dashboard._awaiting_review_tickets(self.brain_path)
        self.assertEqual(len(tickets), 2)
        self.assertEqual(tickets[0]["title"], "Review Annual Budget")
        self.assertEqual(tickets[0]["path"], self.brain_path / "tasks/areas/work/review-budget.md")
        self.assertEqual(tickets[1]["title"], "Build My Feature")

    def test_returns_empty_if_no_tasks_dir_or_no_matching_status(self):
        self.assertEqual(dashboard._awaiting_review_tickets(self.brain_path), [])
        (self.brain_path / "tasks" / "projects" / "goals-os").mkdir(parents=True)
        self._write_ticket(
            "tasks/projects/goals-os/done-task.md",
            "---\nstatus: done\n---\n# Done Task\n"
        )
        self.assertEqual(dashboard._awaiting_review_tickets(self.brain_path), [])


class TestWriteDashboard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n"
            + "\n".join(f"| {r} | never |" for r in [
                "Capture sweep", "Triage", "Execute", "Dashboard", "Planning session",
                "Weekly Review", "Coaching session", "Goal review", "Upgrade review",
                "Architecture review", "Version control", "Metrics pulse",
            ])
        )
        # Cadence comes from the Brain since ADR-0030 — a Brain with no
        # config/schedules.md has nothing to due-check, so the fixture ships
        # the same starter table a fresh Brain clones.
        shutil.copyfile(
            Path(__file__).parent.parent / "protocols" / "examples" / "schedules.md",
            self.brain_path / "config" / "schedules.md",
        )
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md").write_text(
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-07-11\nstatus: pending\n---\n\n"
            "# Triage Plan — voice — 2026-07-11\n\n"
            "## areas/household/_inbox.md\n\n"
            "- [ ] **1** → `areas/household/_inbox.md` · Pass A · High · a1b2c3d4\n"
            "    preview\n"
            "    [[inbox/raw/voice/x.md]]\n"
        )
        (self.brain_path / "inbox" / "rule-diffs").mkdir(parents=True)
        (self.brain_path / "inbox" / "rule-diffs" / "2026-07-11-routing-rules.md").write_text(
            "---\ntype: rule-diff-batch\nruleset: routing-rules\ndate: 2026-07-11\nstatus: pending\n---\n\n"
            "# Rule diffs — routing-rules — 2026-07-11\n\n"
            "### Diff 1 — sonia-email-to-work\n\n```\nif: source == \"email\"\nthen: route -> areas/work/_inbox.md\n```\n\n"
            "**Why:** rationale\n\n**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-09#09:00 — file-email]]\n\n"
            "- [ ] Approve\n- [ ] Reject\n"
        )
        (self.brain_path / "tasks" / "projects" / "goals-os").mkdir(parents=True)
        (self.brain_path / "tasks" / "projects" / "goals-os" / "build-feature.md").write_text(
            "---\nstatus: awaiting-review\ntype: task\n---\n\n# Build Feature\n"
        )
        (self.brain_path / "log").mkdir()
        (self.brain_path / "log" / "2026-07-11.md").write_text(
            "# Action Log — 2026-07-11\n\n"
            "### 09:00 — file-capture\n\n- **actor:** EA\n- **feedback:** —\n\n"
            "### 10:00 — discard-capture\n\n- **actor:** EA\n- **feedback:** —\n"
        )
        self.now = dt.datetime(2026, 7, 11, 21, 50)

    def tearDown(self):
        self._tmp.cleanup()

    def test_surfaces_overdue_pending_plan_and_log_entries(self):
        path = dashboard.write_dashboard(self.brain_path, now=self.now)
        text = path.read_text()
        self.assertIn("Triage (last run: never)", text)
        self.assertIn("Dashboard (last run: never)", text)
        self.assertIn("Version control (last run: never)", text)
        self.assertIn("2026-07-11-voice.md", text)
        self.assertIn("## Pending review", text)
        self.assertIn("2026-07-11-routing-rules.md", text)
        self.assertIn("1 diff(s), 0 decided, 1 awaiting review", text)
        self.assertIn("## Tickets awaiting review", text)
        self.assertIn("- **Build Feature** ([[tasks/projects/goals-os/build-feature.md]])", text)
        self.assertIn("2 entries logged today", text)
        self.assertIn("2 awaiting your feedback", text)
        # No Files/dropzone/ sibling exists next to this temp Brain root —
        # the section still renders, with all-zero counts, rather than
        # erroring or being omitted.
        self.assertIn("## 📁 Dropzone awaiting processing", text)
        self.assertIn("- Expenses: 0 waiting", text)
        self.assertIn("- Homework: 0 waiting", text)
        self.assertIn("- Recipes: 0 waiting", text)

    def test_bumps_dashboards_own_last_run_but_reflects_pre_run_overdue_state(self):
        path = dashboard.write_dashboard(self.brain_path, now=self.now)
        # This run's own rendered output still shows it as overdue coming in...
        self.assertIn("Dashboard (last run: never)", path.read_text())
        # ...but routine-state.md is bumped for the *next* run to see.
        state_text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Dashboard | 2026-07-11 21:50 |", state_text)

        second_path = dashboard.write_dashboard(self.brain_path, now=self.now)
        self.assertNotIn("Dashboard (last run:", second_path.read_text())

    def test_second_run_has_no_stale_content_after_state_changes(self):
        dashboard.write_dashboard(self.brain_path, now=self.now)

        # Triage Plan gets executed/archived; a rule-diff batch gets resolved
        # and archived; an awaiting-review ticket is resolved; a new log entry lands.
        (self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md").unlink()
        (self.brain_path / "inbox" / "rule-diffs" / "2026-07-11-routing-rules.md").unlink()
        (self.brain_path / "tasks" / "projects" / "goals-os" / "build-feature.md").unlink()
        with (self.brain_path / "log" / "2026-07-11.md").open("a") as f:
            f.write("\n### 11:00 — file-capture\n\n- **actor:** EA\n- **feedback:** ✓\n")

        path = dashboard.write_dashboard(self.brain_path, now=self.now)
        text = path.read_text()
        self.assertNotIn("2026-07-11-voice.md", text)
        self.assertIn("No pending Triage Plans.", text)
        self.assertNotIn("2026-07-11-routing-rules.md", text)
        self.assertIn("No pending rule-diff reviews.", text)
        self.assertNotIn("build-feature.md", text)
        self.assertIn("No tickets awaiting review.", text)
        self.assertIn("3 entries logged today", text)
        self.assertIn("2 awaiting your feedback", text)


if __name__ == "__main__":
    unittest.main()


class TestOpenProposedItems(unittest.TestCase):
    """protocols/dashboard.md v0.5 — meetings/*.md as a source, added the same
    way people/*.md was."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "meetings").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_note(self, filename, body):
        (self.brain_path / "meetings" / filename).write_text(body)

    def test_finds_open_proposed_items(self):
        self._write_note(
            "2026-07-25 Planning call.md",
            "---\ntype: meeting\ndate: 2026-07-25\n---\n\n"
            "# Planning call\n\n"
            "## Summary\n\nWe talked.\n\n"
            "## Proposed\n"
            "- [ ] Create a Person Hub for Dani\n"
            "- [x] Already actioned this one\n"
            "- [ ] ~~Withdrawn~~\n"
            "- [ ] Close the stale 'pricing review' ticket?\n",
        )
        items = dashboard._open_proposed_items(self.brain_path)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["meeting"], "Planning call")
        self.assertIn("Person Hub for Dani", items[0]["text"])
        self.assertIn("pricing review", items[1]["text"])

    def test_ticked_and_struck_through_items_do_not_count(self):
        self._write_note(
            "2026-07-25 Done.md",
            "# Done\n\n## Proposed\n- [x] actioned\n- [ ] ~~withdrawn~~\n",
        )
        self.assertEqual(dashboard._open_proposed_items(self.brain_path), [])

    def test_note_without_a_proposed_section_is_skipped(self):
        self._write_note(
            "2026-07-25 No proposals.md",
            "# No proposals\n\n## Summary\n\n- [ ] this is not under Proposed\n",
        )
        self.assertEqual(dashboard._open_proposed_items(self.brain_path), [])

    def test_stops_at_the_next_heading(self):
        self._write_note(
            "2026-07-25 Bounded.md",
            "# Bounded\n\n## Proposed\n- [ ] in scope\n\n## Notes\n- [ ] out of scope\n",
        )
        items = dashboard._open_proposed_items(self.brain_path)
        self.assertEqual([i["text"] for i in items], ["in scope"])

    def test_ignores_readme_underscore_files_and_missing_dir(self):
        self._write_note("README.md", "# meetings\n\n## Proposed\n- [ ] should not count\n")
        self._write_note("_scratch.md", "# scratch\n\n## Proposed\n- [ ] should not count\n")
        self.assertEqual(dashboard._open_proposed_items(self.brain_path), [])

        empty_brain = Path(tempfile.mkdtemp())
        self.assertEqual(dashboard._open_proposed_items(empty_brain), [])

    def test_scan_is_non_destructive(self):
        body = (
            "# Planning call\n\n## Proposed\n- [ ] Create a Person Hub for Dani\n"
        )
        self._write_note("2026-07-25 Planning call.md", body)
        dashboard._open_proposed_items(self.brain_path)
        self.assertEqual(
            (self.brain_path / "meetings" / "2026-07-25 Planning call.md").read_text(), body
        )

    def test_grouped_by_note_for_the_dashboard(self):
        self._write_note(
            "2026-07-24 First.md", "# First\n\n## Proposed\n- [ ] a\n- [ ] b\n")
        self._write_note(
            "2026-07-25 Second.md", "# Second\n\n## Proposed\n- [ ] c\n")
        rows = dashboard._proposed_by_note(dashboard._open_proposed_items(self.brain_path))
        self.assertEqual([(r["meeting"], r["count"]) for r in rows],
                         [("First", 2), ("Second", 1)])

    def test_renders_a_read_only_link_per_note(self):
        self._write_note(
            "2026-07-25 Planning call.md",
            "# Planning call\n\n## Proposed\n- [ ] a\n- [ ] b\n")
        data = dashboard.compute_dashboard_data(self.brain_path)
        out = dashboard.render_dashboard(data)
        self.assertIn("## Proposed from meetings", out)
        self.assertIn("**Planning call** — 2 proposed items", out)
        self.assertIn("[[meetings/2026-07-25 Planning call.md]]", out)

    def test_singular_count_and_empty_state(self):
        data = dashboard.compute_dashboard_data(self.brain_path)
        self.assertIn("Nothing proposed.", dashboard.render_dashboard(data))

        self._write_note("2026-07-25 One.md", "# One\n\n## Proposed\n- [ ] a\n")
        data = dashboard.compute_dashboard_data(self.brain_path)
        self.assertIn("1 proposed item (", dashboard.render_dashboard(data))


class TestPendingPlanSummary(unittest.TestCase):
    """The ticked/pending split the Dashboard shows, read straight off a
    Plan in the ADR-0031 task-list shape via `execute.parse_plan_rows`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.plan = Path(self._tmp.name) / "2026-07-27-email.md"

    def tearDown(self):
        self._tmp.cleanup()

    def _row(self, n, dest, approve):
        tick, marker = approve[:3], approve[4:]
        suffix = f" {marker}" if marker else ""
        return f"- {tick} preview → `{dest}` [[inbox/raw/email/cap-{n}.md]]{suffix}\n\n"

    def test_counts_ticked_and_pending_rows(self):
        self.plan.write_text(
            "---\ntype: triage-plan\nsource: email\ndate: 2026-07-27\n"
            "status: pending\n---\n\n# Triage Plan — email — 2026-07-27\n\n"
            "## discard\n\n"
            + self._row(1, "discard", "[ ]")
            + self._row(2, "discard", "[x]")
            + self._row(3, "discard", "[x] (done)")
        )
        summary = dashboard._pending_plan_summary(self.plan)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["ticked"], 2)
        self.assertEqual(summary["pending"], 1)

    def test_legacy_plan_summary_and_rendering(self):
        legacy_table = (
            "---\ntype: triage-plan\nsource: email\ndate: 2026-07-27\nstatus: pending\n---\n\n"
            "# Triage Plan — email — 2026-07-27\n\n"
            "| # | capture | preview | route | destination | confidence | rule | approve |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| 1 | [[inbox/raw/email/cap-1.md]] | item 1 | Pass B | unmatched | High | — | [ ] |\n"
        )
        self.plan.write_text(legacy_table, encoding="utf-8")
        summary = dashboard._pending_plan_summary(self.plan)
        self.assertTrue(summary["migration_required"])
        self.assertEqual(summary["total"], 0)

        data = {
            "generated": "2026-08-02 10:00",
            "date_str": "2026-08-02",
            "overdue": [],
            "pending_plans": [summary],
            "pending_rule_diffs": [],
            "awaiting_review_tickets": [],
            "waiting_for": [],
            "action_log": {"exists": False, "entry_count": 0, "unreviewed": 0, "date_str": "2026-08-02"},
            "dropzone": [],
        }
        text = dashboard.render_dashboard(data)
        self.assertIn("migration required", text)
        self.assertNotIn("No pending Triage Plans.", text)
        self.assertNotIn("0 row(s)", text)
