import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import commission  # noqa: E402


class TestRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "log").mkdir()
        self.now = dt.datetime(2026, 7, 12, 9, 30)

    def tearDown(self):
        self._tmp.cleanup()

    def test_appends_action_log_entry_with_correct_actor_format(self):
        log_path = commission.run(
            self.brain_path,
            commissioning_agent="Will",
            capability_role="Researcher",
            task_summary="Find recent papers on LLM agents.",
            outcome="Found 3 papers.",
            now=self.now,
        )

        log_text = log_path.read_text()
        self.assertIn("commission-capability", log_text)
        self.assertIn("**actor:** Researcher (via Will)", log_text)
        self.assertIn("**trigger:** Commissioned Capability Agent", log_text)
        self.assertIn("Commissioned Researcher: Find recent papers on LLM agents.", log_text)
        self.assertIn("Found 3 papers.", log_text)

    def test_confidence_threads_through(self):
        log_path = commission.run(
            self.brain_path,
            commissioning_agent="EA",
            capability_role="Writer",
            task_summary="Draft email.",
            outcome="Drafted.",
            confidence="Medium",
            now=self.now,
        )

        log_text = log_path.read_text()
        self.assertIn("**confidence:** Medium", log_text)


if __name__ == "__main__":
    unittest.main()
