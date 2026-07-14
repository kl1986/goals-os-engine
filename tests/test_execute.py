import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import execute  # noqa: E402

PLAN_TEXT = """---
type: triage-plan
source: voice
date: 2026-07-11
status: pending
---

# Triage Plan — voice — 2026-07-11

| # | capture | preview | route | destination | confidence | approve |
|---|---|---|---|---|---|---|
| 1 | [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] | Remember to buy milk | Pass A | areas/home/_inbox.md | High | [x] |
| 2 | [[inbox/raw/voice/2026-07-11-140500-junk.md]] | not worth keeping | Pass B | discard | Medium | [x] |
| 3 | [[inbox/raw/voice/2026-07-11-140600-later.md]] | deal with this later | Pass B | areas/home/_inbox.md | Medium | [ ] |
"""


class TestActionTypeFor(unittest.TestCase):
    def test_discard_destination_is_discard_capture(self):
        self.assertEqual(execute.action_type_for("discard"), "discard-capture")
        self.assertEqual(execute.action_type_for("Discard"), "discard-capture")

    def test_path_destination_is_file_capture(self):
        self.assertEqual(execute.action_type_for("areas/home/_inbox.md"), "file-capture")

    def test_agent_destination_is_agent_dispatched(self):
        self.assertEqual(execute.action_type_for("agent: Researcher"), "agent-dispatched")
        self.assertEqual(execute.action_type_for("Agent: Writer "), "agent-dispatched")

    def test_today_destination_is_file_capture_today(self):
        self.assertEqual(execute.action_type_for("today"), "file-capture-today")
        self.assertEqual(execute.action_type_for("Today"), "file-capture-today")
        self.assertEqual(execute.action_type_for("  TODAY  "), "file-capture-today")


class TestParsePlanRows(unittest.TestCase):
    def test_parses_all_three_rows(self):
        rows = execute.parse_plan_rows(PLAN_TEXT)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["approve"], "[x]")
        self.assertEqual(rows[2]["approve"], "[ ]")

    def test_parses_dispatched_and_done_rows(self):
        text = "| 1 | [[inbox/raw/x.md]] | p | Pass A | d | High | [x] (dispatched) |\n"
        text += "| 2 | [[inbox/raw/y.md]] | p | Pass A | d | High | [x] (done) |\n"
        rows = execute.parse_plan_rows(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["approve"], "[x] (dispatched)")
        self.assertEqual(rows[1]["approve"], "[x] (done)")


class TestExecutePlan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "areas" / "home").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "voice").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        for name in ("2026-07-11-140203-buy-milk.md", "2026-07-11-140500-junk.md", "2026-07-11-140600-later.md"):
            (self.brain_path / "inbox" / "raw" / "voice" / name).write_text("---\nraw: true\n---\nbody\n")
        self.plan_path = self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md"
        self.plan_path.write_text(PLAN_TEXT)
        self.now = dt.datetime(2026, 7, 11, 15, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_files_and_discards_ticked_rows_leaves_unticked_alone(self):
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertEqual(len(result["filed"]), 1)
        self.assertEqual(len(result["discarded"]), 1)
        self.assertEqual(result["errors"], [])

        inbox_note = (self.brain_path / "areas" / "home" / "_inbox.md").read_text()
        self.assertIn("buy-milk", inbox_note)
        self.assertIn("Remember to buy milk", inbox_note)

    def test_moves_processed_raw_files_to_archive_leaves_unticked_raw_in_place(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertFalse((self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140203-buy-milk.md").exists())
        self.assertFalse((self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140500-junk.md").exists())
        self.assertTrue((self.brain_path / "archive" / "inbox" / "voice" / "2026-07-11-140203-buy-milk.md").exists())
        self.assertTrue((self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140600-later.md").exists())

    def test_appends_action_log_entries(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        log_text = (self.brain_path / "log" / "2026-07-11.md").read_text()
        self.assertEqual(log_text.count("### "), 2)
        self.assertIn("file-capture", log_text)
        self.assertIn("discard-capture", log_text)

    def test_plan_not_archived_while_a_row_remains_unticked(self):
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertFalse(result["plan_executed"])
        self.assertTrue(self.plan_path.exists())
        text = self.plan_path.read_text()
        self.assertIn("status: pending", text)
        self.assertIn("[x] (done)", text)
        self.assertIn("| [ ] |", text)  # row 3 still untouched

    def test_second_run_after_ticking_last_row_archives_plan(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        text = self.plan_path.read_text()
        text = text.replace(
            "| 3 | [[inbox/raw/voice/2026-07-11-140600-later.md]] | deal with this later | Pass B | areas/home/_inbox.md | Medium | [ ] |",
            "| 3 | [[inbox/raw/voice/2026-07-11-140600-later.md]] | deal with this later | Pass B | areas/home/_inbox.md | Medium | [x] |",
        )
        self.plan_path.write_text(text)

        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertTrue(result["plan_executed"])
        self.assertFalse(self.plan_path.exists())
        archived_text = result["archived_to"].read_text()
        self.assertIn("status: executed", archived_text)

    def test_missing_raw_capture_reports_error_not_crash(self):
        (self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140203-buy-milk.md").unlink()
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("not found", result["errors"][0])

    def test_unmatched_destination_on_ticked_row_reports_error(self):
        text = PLAN_TEXT.replace(
            "| 1 | [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] | Remember to buy milk | Pass A | areas/home/_inbox.md | High | [x] |",
            "| 1 | [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] | Remember to buy milk | Pass B | unmatched | — | [x] |",
        )
        self.plan_path.write_text(text)
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("unmatched", result["errors"][0])

    def test_bumps_execute_last_run_when_routine_state_exists(self):
        (self.brain_path / "config").mkdir()
        routine_state = self.brain_path / "config" / "routine-state.md"
        routine_state.write_text("| Routine | Last run |\n|---|---|\n| Execute | never |\n")

        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertIn("| Execute | 2026-07-11 15:00 |", routine_state.read_text())

    def test_agent_dispatched_leaves_raw_capture_and_returns_log_id(self):
        text = PLAN_TEXT.replace(
            "| 1 | [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] | Remember to buy milk | Pass A | areas/home/_inbox.md | High | [x] |",
            "| 1 | [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] | Remember to buy milk | Pass A | agent: Reviewer | High | [x] |",
        )
        self.plan_path.write_text(text)
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        
        self.assertEqual(len(result["agent_dispatched"]), 1)
        dispatched_row = result["agent_dispatched"][0]
        self.assertIn("log_id", dispatched_row)
        
        # Raw capture should NOT be moved to archive
        self.assertTrue((self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140203-buy-milk.md").exists())
        self.assertFalse((self.brain_path / "archive" / "inbox" / "voice" / "2026-07-11-140203-buy-milk.md").exists())
        
        # Plan should be updated to [x] (dispatched)
        plan_text = self.plan_path.read_text()
        self.assertIn("[x] (dispatched)", plan_text)


TODAY_PLAN_TEXT = """---
type: triage-plan
source: voice
date: 2026-07-13
status: pending
---

# Triage Plan — voice — 2026-07-13

| # | capture | preview | route | destination | confidence | approve |
|---|---|---|---|---|---|---|
| 1 | [[inbox/raw/voice/2026-07-13-090000-call-plumber.md]] | Call the plumber | Pass A | today | High | [x] |
| 2 | [[inbox/raw/voice/2026-07-13-091000-later.md]] | deal with this later | Pass B | areas/home/_inbox.md | Medium | [ ] |
"""


class TestFileCaptureToday(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "inbox" / "raw" / "voice").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        for name in ("2026-07-13-090000-call-plumber.md", "2026-07-13-091000-later.md"):
            (self.brain_path / "inbox" / "raw" / "voice" / name).write_text("---\nraw: true\n---\nbody\n")
        self.plan_path = self.brain_path / "inbox" / "triage" / "2026-07-13-voice.md"
        self.plan_path.write_text(TODAY_PLAN_TEXT)
        self.now = dt.datetime(2026, 7, 13, 15, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_daily_note(self, today_tasks_body="- [ ]"):
        (self.brain_path / "2026-07-13.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-13\ntags:\n  - daily-note\n---\n\n"
            "# Monday, 13 July 2026\n\n"
            f"## Today's tasks\n{today_tasks_body}\n\n"
            "## Project next actions\n\n"
            "## Waiting for\n\n"
            "## Notes\n"
        )

    def test_happy_path_inserts_as_last_line_of_todays_tasks_before_next_heading(self):
        self._write_daily_note("- [ ] Existing manual task")
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["filed"]), 1)

        note_text = (self.brain_path / "2026-07-13.md").read_text()
        section = note_text.split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, [
            "- [ ] Existing manual task",
            "- [ ] Call the plumber — [[inbox/raw/voice/2026-07-13-090000-call-plumber.md]]",
        ])
        # It landed before the next heading, not appended blindly at EOF.
        self.assertTrue(note_text.rstrip().endswith("## Notes"))

    def test_happy_path_archives_capture_and_marks_row_done(self):
        self._write_daily_note()
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertFalse(
            (self.brain_path / "inbox" / "raw" / "voice" / "2026-07-13-090000-call-plumber.md").exists()
        )
        self.assertTrue(
            (self.brain_path / "archive" / "inbox" / "voice" / "2026-07-13-090000-call-plumber.md").exists()
        )
        plan_text = self.plan_path.read_text()
        self.assertIn("[x] (done)", plan_text)

        log_text = (self.brain_path / "log" / "2026-07-13.md").read_text()
        self.assertIn("file-capture-today", log_text)
        self.assertIn("Filed to today's daily note", log_text)

    def test_missing_todays_note_reports_error_leaves_row_and_capture_untouched(self):
        # No daily note written for today at all.
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("does not exist", result["errors"][0])
        self.assertEqual(result["filed"], [])

        # Row left untouched (still [x], not [x] (done)) and capture not moved.
        plan_text = self.plan_path.read_text()
        self.assertIn("| Call the plumber | Pass A | today | High | [x] |", plan_text)
        self.assertTrue(
            (self.brain_path / "inbox" / "raw" / "voice" / "2026-07-13-090000-call-plumber.md").exists()
        )
        self.assertFalse(
            (self.brain_path / "archive" / "inbox" / "voice" / "2026-07-13-090000-call-plumber.md").exists()
        )

    def test_missing_todays_note_does_not_block_other_rows(self):
        # Tick the second row too, and give it a real destination — it
        # should still get filed even though row 1 errors out.
        text = self.plan_path.read_text().replace(
            "| 2 | [[inbox/raw/voice/2026-07-13-091000-later.md]] | deal with this later | Pass B | areas/home/_inbox.md | Medium | [ ] |",
            "| 2 | [[inbox/raw/voice/2026-07-13-091000-later.md]] | deal with this later | Pass B | areas/home/_inbox.md | Medium | [x] |",
        )
        self.plan_path.write_text(text)
        (self.brain_path / "areas" / "home").mkdir(parents=True)

        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(result["filed"]), 1)
        self.assertIn(
            "[[inbox/raw/voice/2026-07-13-091000-later.md]]",
            (self.brain_path / "areas" / "home" / "_inbox.md").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
