import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import planning_session  # noqa: E402

MEMORY_STUB = """# Will — memory

Continuity notes Will reads before each session. Empty until the
first planning session.

## Session log
"""


class TestAppendMemoryEntry(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.memory_path = Path(self._tmp.name) / "_memory.md"
        self.now = dt.datetime(2026, 7, 12, 9, 30)

    def tearDown(self):
        self._tmp.cleanup()

    def test_appends_dated_entry_under_existing_session_log_heading(self):
        self.memory_path.write_text(MEMORY_STUB)

        planning_session.append_memory_entry(self.memory_path, "Discussed Q3 goals.", now=self.now)

        text = self.memory_path.read_text()
        self.assertIn("## Session log", text)
        self.assertIn("### 2026-07-12", text)
        self.assertIn("Discussed Q3 goals.", text)

    def test_second_call_appends_without_clobbering_first_entry(self):
        self.memory_path.write_text(MEMORY_STUB)

        planning_session.append_memory_entry(self.memory_path, "First session.", now=self.now)
        planning_session.append_memory_entry(
            self.memory_path, "Second session.", now=self.now + dt.timedelta(days=7)
        )

        text = self.memory_path.read_text()
        self.assertIn("First session.", text)
        self.assertIn("Second session.", text)
        self.assertLess(text.index("First session."), text.index("Second session."))

    def test_creates_session_log_heading_if_missing(self):
        self.memory_path.write_text("# Will — memory\n\nEmpty.\n")

        planning_session.append_memory_entry(self.memory_path, "First session.", now=self.now)

        text = self.memory_path.read_text()
        self.assertIn("## Session log", text)
        self.assertIn("First session.", text)


class TestRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

        (self.brain_path / "areas" / "work").mkdir(parents=True)
        (self.brain_path / "areas" / "work" / "Work.md").write_text(
            "---\ntype: area\nagent: Will\ntags: [area]\n---\n\n# Work\n\n"
            "## Standard\n-\n\n## Current goals\n-\n"
        )
        (self.brain_path / "areas" / "work" / "_memory.md").write_text(MEMORY_STUB)

        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Planning session | never |\n"
        )

        self.now = dt.datetime(2026, 7, 12, 9, 30)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, notes="Decomposed goals into next actions.", outcome="Updated Current goals."):
        return planning_session.run(
            self.brain_path,
            area_note="areas/work/Work.md",
            area_agent="Will",
            notes=notes,
            outcome=outcome,
            now=self.now,
        )

    def test_bumps_planning_session_last_run(self):
        self._run()
        text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Planning session | 2026-07-12 09:30 |", text)

    def test_writes_memory_entry(self):
        self._run(notes="Decomposed Q3 goals with Will.")
        text = (self.brain_path / "areas" / "work" / "_memory.md").read_text()
        self.assertIn("Decomposed Q3 goals with Will.", text)

    def test_appends_action_log_entry_with_area_agent_as_actor(self):
        result = self._run(notes="Discussed Standard.", outcome="Standard revised.")
        log_text = result["log_path"].read_text()
        self.assertIn("planning-session", log_text)
        self.assertIn("**actor:** Will", log_text)
        self.assertIn("**trigger:** Planning session (Routine)", log_text)
        self.assertIn("Discussed Standard.", log_text)
        self.assertIn("Standard revised.", log_text)
        self.assertIn("areas/work/Work.md", log_text)

    def test_confidence_is_not_hardcoded_and_threads_through_to_the_log_entry(self):
        result = planning_session.run(
            self.brain_path, area_note="areas/work/Work.md", area_agent="Will",
            notes="Tentative first pass at goals.", outcome="Current goals drafted, not yet confirmed.",
            confidence="Low", now=self.now,
        )
        log_text = result["log_path"].read_text()
        self.assertIn("**confidence:** Low", log_text)

    def test_second_run_does_not_duplicate_or_clobber_prior_entries(self):
        self._run(notes="First session.")
        self._run(notes="Second session.")

        memory_text = (self.brain_path / "areas" / "work" / "_memory.md").read_text()
        self.assertIn("First session.", memory_text)
        self.assertIn("Second session.", memory_text)

        log_path = self.brain_path / "log" / "2026-07-12.md"
        log_text = log_path.read_text()
        self.assertEqual(log_text.count("**trigger:** Planning session (Routine)"), 2)


if __name__ == "__main__":
    unittest.main()
