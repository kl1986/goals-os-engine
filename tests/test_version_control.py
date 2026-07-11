import datetime as dt
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import version_control as vc  # noqa: E402


def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True)


class TestVersionControl(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.origin = root / "origin.git"
        self.brain_path = root / "brain"

        _git(root, "init", "--bare", "-b", "main", str(self.origin))
        _git(root, "clone", str(self.origin), str(self.brain_path))
        _git(self.brain_path, "config", "user.email", "test@example.com")
        _git(self.brain_path, "config", "user.name", "Test")

        (self.brain_path / "config").mkdir()
        self.routine_state_path = self.brain_path / "config" / "routine-state.md"
        self.routine_state_path.write_text(
            "| Routine | Last run |\n|---|---|\n| Triage | never |\n| Version control | never |\n"
        )
        (self.brain_path / "README.md").write_text("# Brain\n")
        _git(self.brain_path, "add", "-A")
        _git(self.brain_path, "commit", "-m", "Initial commit")
        _git(self.brain_path, "push", "-u", "origin", "main")

        self.now = dt.datetime(2026, 7, 11, 22, 15)

    def tearDown(self):
        self._tmp.cleanup()

    def test_noop_on_clean_tree(self):
        result = vc.run(self.brain_path, now=self.now)
        self.assertFalse(result["committed"])
        self.assertIsNone(result["tag"])

    def test_commits_pushes_and_tags_dirty_tree(self):
        (self.brain_path / "log").mkdir()
        (self.brain_path / "log" / "2026-07-11.md").write_text("# Action Log\n")

        result = vc.run(self.brain_path, now=self.now)

        self.assertTrue(result["committed"])
        self.assertEqual(result["tag"], "brain-2026-07-11-2215")
        self.assertTrue(result["pushed"])

        log = _git(self.brain_path, "log", "-1", "--pretty=%s").stdout.strip()
        self.assertIn("Brain checkpoint 2026-07-11", log)

        tags_on_origin = _git(self.origin, "tag").stdout.split()
        self.assertIn("brain-2026-07-11-2215", tags_on_origin)

    def test_bumps_version_control_last_run_and_includes_it_in_the_commit(self):
        (self.brain_path / "log").mkdir()
        (self.brain_path / "log" / "2026-07-11.md").write_text("# Action Log\n")

        vc.run(self.brain_path, now=self.now)

        text = self.routine_state_path.read_text()
        self.assertIn("| Version control | 2026-07-11 22:15 |", text)

        show = _git(self.brain_path, "show", "--stat", "HEAD").stdout
        self.assertIn("routine-state.md", show)

    def test_second_run_after_commit_is_a_noop(self):
        (self.brain_path / "log").mkdir()
        (self.brain_path / "log" / "2026-07-11.md").write_text("# Action Log\n")
        vc.run(self.brain_path, now=self.now)

        result = vc.run(self.brain_path, now=self.now + dt.timedelta(minutes=5))
        self.assertFalse(result["committed"])


if __name__ == "__main__":
    unittest.main()
