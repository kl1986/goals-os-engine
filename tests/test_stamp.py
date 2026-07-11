import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import stamp  # noqa: E402


class TestStamp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_valid_frontmatter(self):
        now = dt.datetime(2026, 7, 11, 14, 2, 3)
        path = stamp.stamp(self.brain_path, "voice", "Buy milk", "Remember to buy milk", now=now)
        text = path.read_text()
        self.assertIn("type: raw", text)
        self.assertIn("date: 2026-07-11", text)
        self.assertIn("source: voice", text)
        self.assertIn("id: 2026-07-11-140203-buy-milk", text)
        self.assertIn("raw: true", text)
        self.assertIn("Remember to buy milk", text)

    def test_writes_to_per_source_subfolder(self):
        path = stamp.stamp(self.brain_path, "email", "Newsletter", "body")
        self.assertEqual(path.parent, self.brain_path / "inbox" / "raw" / "email")

    def test_collision_safe_naming(self):
        now = dt.datetime(2026, 7, 11, 14, 2, 3)
        path1 = stamp.stamp(self.brain_path, "voice", "Same title", "first", now=now)
        path2 = stamp.stamp(self.brain_path, "voice", "Same title", "second", now=now)
        self.assertNotEqual(path1, path2)
        self.assertTrue(path1.exists())
        self.assertTrue(path2.exists())
        self.assertIn("first", path1.read_text())
        self.assertIn("second", path2.read_text())

    def test_slugify_handles_punctuation(self):
        self.assertEqual(stamp.slugify("Buy milk & eggs!"), "buy-milk-eggs")
        self.assertEqual(stamp.slugify(""), "capture")


if __name__ == "__main__":
    unittest.main()
