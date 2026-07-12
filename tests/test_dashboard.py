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
            "waiting_for": [{"person": "Jane Doe", "path": Path("people/Jane Doe.md"), "text": "Jane to send over the draft budget"}],
            "action_log": {"exists": True, "entry_count": 2, "unreviewed": 2, "date_str": "2026-07-11"},
        }
        text = dashboard.render_dashboard(data)
        self.assertIn("Triage (last run: never)", text)
        self.assertIn("[[inbox/triage/2026-07-11-voice.md]]", text)
        self.assertIn("1 ticked, 1 awaiting approval", text)
        self.assertIn("**Jane Doe** — Jane to send over the draft budget ([[people/Jane Doe.md]])", text)
        self.assertIn("2 entries logged today", text)
        self.assertIn("2 awaiting your feedback", text)

    def test_renders_empty_states(self):
        data = {
            "generated": "2026-07-11 21:50", "date_str": "2026-07-11",
            "overdue": [], "pending_plans": [], "waiting_for": [],
            "action_log": {"exists": False, "entry_count": 0, "unreviewed": 0, "date_str": "2026-07-11"},
        }
        text = dashboard.render_dashboard(data)
        self.assertIn("Nothing overdue.", text)
        self.assertIn("No pending Triage Plans.", text)
        self.assertIn("Nothing open.", text)
        self.assertIn("No Action Log entries yet today.", text)


class TestOpenWaitingFor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "people").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_hub(self, filename, body):
        (self.brain_path / "people" / filename).write_text(body)

    def test_finds_open_items_and_skips_closed_ones(self):
        self._write_hub(
            "Jane Doe.md",
            "---\nname: Jane Doe\n---\n\n"
            "## Waiting For\n"
            "- [ ] #waiting-for Jane to send over the draft budget\n"
            "- [x] #waiting-for Jane to share the meeting agenda\n"
            "- [ ] ~~#waiting-for Already closed via strikethrough~~ done 19/06\n"
            "\n## Context\n- some context\n",
        )
        items = dashboard._open_waiting_for(self.brain_path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["person"], "Jane Doe")
        self.assertIn("send over the draft budget", items[0]["text"])

    def test_ignores_alias_file_and_missing_people_dir(self):
        self._write_hub("_aliases.md", "## Waiting For\n- [ ] #waiting-for should not count\n")
        self.assertEqual(dashboard._open_waiting_for(self.brain_path), [])

        empty_brain = Path(tempfile.mkdtemp())
        self.assertEqual(dashboard._open_waiting_for(empty_brain), [])


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
        self.assertIn("2 entries logged today", text)
        self.assertIn("2 awaiting your feedback", text)

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

        # Triage Plan gets executed/archived; a new log entry lands.
        (self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md").unlink()
        with (self.brain_path / "log" / "2026-07-11.md").open("a") as f:
            f.write("\n### 11:00 — file-capture\n\n- **actor:** EA\n- **feedback:** ✓\n")

        path = dashboard.write_dashboard(self.brain_path, now=self.now)
        text = path.read_text()
        self.assertNotIn("2026-07-11-voice.md", text)
        self.assertIn("No pending Triage Plans.", text)
        self.assertIn("3 entries logged today", text)
        self.assertIn("2 awaiting your feedback", text)


if __name__ == "__main__":
    unittest.main()
