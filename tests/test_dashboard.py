import datetime as dt
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
            "overdue": [], "pending_plans": [], "pending_rule_diffs": [], "waiting_for": [],
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
        # Homework/ has real-world sub-subfolders (Kara/Khloe/Both) — the
        # spec is explicit this section is top-level-only, so files nested
        # a level deeper don't count.
        self._touch("Homework", "Kara", "spelling.jpg")
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
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md").write_text(
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-07-11\nstatus: pending\n---\n\n"
            "| # | capture | preview | route | destination | confidence | approve |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 1 | [[inbox/raw/voice/x.md]] | preview | Pass A | areas/home/_inbox.md | High | [ ] |\n"
        )
        (self.brain_path / "inbox" / "rule-diffs").mkdir(parents=True)
        (self.brain_path / "inbox" / "rule-diffs" / "2026-07-11-routing-rules.md").write_text(
            "---\ntype: rule-diff-batch\nruleset: routing-rules\ndate: 2026-07-11\nstatus: pending\n---\n\n"
            "# Rule diffs — routing-rules — 2026-07-11\n\n"
            "### Diff 1 — sonia-email-to-work\n\n```\nif: source == \"email\"\nthen: route -> areas/work/_inbox.md\n```\n\n"
            "**Why:** rationale\n\n**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-09#09:00 — file-email]]\n\n"
            "- [ ] Approve\n- [ ] Reject\n"
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
        # and archived; a new log entry lands.
        (self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md").unlink()
        (self.brain_path / "inbox" / "rule-diffs" / "2026-07-11-routing-rules.md").unlink()
        with (self.brain_path / "log" / "2026-07-11.md").open("a") as f:
            f.write("\n### 11:00 — file-capture\n\n- **actor:** EA\n- **feedback:** ✓\n")

        path = dashboard.write_dashboard(self.brain_path, now=self.now)
        text = path.read_text()
        self.assertNotIn("2026-07-11-voice.md", text)
        self.assertIn("No pending Triage Plans.", text)
        self.assertNotIn("2026-07-11-routing-rules.md", text)
        self.assertIn("No pending rule-diff reviews.", text)
        self.assertIn("3 entries logged today", text)
        self.assertIn("2 awaiting your feedback", text)


if __name__ == "__main__":
    unittest.main()
