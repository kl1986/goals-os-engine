import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import execute  # noqa: E402
import migrate_triage_row_metadata as mig  # noqa: E402


def plan(*row_lines):
    body = ""
    for i, line in enumerate(row_lines, 1):
        body += f"{line}\n    preview {i}\n    [[inbox/raw/text/c{i}.md]]\n\n"
    return "---\ntype: triage-plan\nstatus: pending\n---\n\n# Plan\n\n## g\n\n" + body


class TestConvertText(unittest.TestCase):
    def test_wraps_the_metadata_and_leaves_everything_else_alone(self):
        text = plan("- [ ] **1** → `areas/home/_inbox.md` · Pass A · High · a1b2c3d4")
        new, count, problem = mig.convert_text(text)
        self.assertIsNone(problem)
        self.assertEqual(count, 1)
        self.assertIn("- [ ] **1** → `areas/home/_inbox.md` %%· Pass A · High · a1b2c3d4%%", new)
        # Continuation lines and structure untouched.
        self.assertIn("    preview 1", new)
        self.assertIn("    [[inbox/raw/text/c1.md]]", new)
        self.assertIn("## g", new)

    def test_preserves_tick_and_executed_marker(self):
        text = plan(
            "- [x] **1** → `discard` · Pass B · — · — (done)",
            "- [x] **2** → `agent: librarian` · Pass B · — · — (dispatched)",
        )
        new, count, _ = mig.convert_text(text)
        self.assertEqual(count, 2)
        self.assertIn("- [x] **1** → `discard` %%· Pass B · — · —%% (done)", new)
        self.assertIn("- [x] **2** → `agent: librarian` %%· Pass B · — · —%% (dispatched)", new)
        rows = {r["n"]: r for r in execute.parse_plan_rows(new)}
        self.assertEqual(rows["1"]["approve"], "[x] (done)")
        self.assertEqual(rows["2"]["approve"], "[x] (dispatched)")

    def test_multi_destination_rows_survive(self):
        text = plan("- [ ] **1** → `areas/home/_inbox.md`, `projects/p/n.md` · Pass B · — · —")
        new, count, _ = mig.convert_text(text)
        self.assertEqual(count, 1)
        rows = execute.parse_plan_rows(new)
        self.assertEqual(rows[0]["destinations"], ["areas/home/_inbox.md", "projects/p/n.md"])

    def test_is_idempotent(self):
        text = plan("- [ ] **1** → `areas/home/_inbox.md` · Pass A · High · a1b2c3d4")
        once, count, _ = mig.convert_text(text)
        twice, second_count, _ = mig.convert_text(once)
        self.assertEqual(second_count, 0)
        self.assertEqual(once, twice)

    def test_every_field_survives_the_round_trip(self):
        before = plan("- [ ] **7** → `areas/home/_inbox.md` · Pass A · Medium · deadbeef")
        after, _, _ = mig.convert_text(before)
        b = execute.parse_plan_rows(before)[0]
        a = execute.parse_plan_rows(after)[0]
        self.assertEqual(a, b)

    def test_an_unreadable_row_line_refuses_the_whole_text(self):
        text = plan(
            "- [ ] **1** → `areas/home/_inbox.md` · Pass A · High · a1b2c3d4",
            "- [ ] **2** → nobackticks · Pass B · — · —",
        )
        new, count, problem = mig.convert_text(text)
        self.assertIsNotNone(problem)
        self.assertIn("nobackticks", problem)
        # Nothing converted — the good row above it is not written either.
        self.assertEqual(count, 0)
        self.assertEqual(new, text)


class TestMigrate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        self.triage = self.brain / "inbox" / "triage"
        self.triage.mkdir(parents=True)
        (self.brain / "archive" / "triage").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_dry_run_writes_nothing(self):
        p = self.triage / "2026-07-24-email.md"
        original = plan("- [ ] **1** → `discard` · Pass B · — · —")
        p.write_text(original)
        result = mig.migrate(self.brain, dry_run=True)
        self.assertEqual(result["converted"], {"2026-07-24-email.md": 1})
        self.assertEqual(p.read_text(), original)

    def test_archived_plans_are_never_touched(self):
        archived = self.brain / "archive" / "triage" / "2026-07-23-email.md"
        original = plan("- [x] **1** → `discard` · Pass B · — · — (done)")
        archived.write_text(original)
        mig.migrate(self.brain)
        self.assertEqual(archived.read_text(), original)

    def test_a_refused_plan_is_left_untouched_and_others_still_convert(self):
        good = self.triage / "good.md"
        bad = self.triage / "bad.md"
        good.write_text(plan("- [ ] **1** → `discard` · Pass B · — · —"))
        bad_text = plan("- [ ] **1** → nobackticks · Pass B · — · —")
        bad.write_text(bad_text)
        result = mig.migrate(self.brain)
        self.assertIn("good.md", result["converted"])
        self.assertIn("bad.md", result["refused"])
        self.assertEqual(bad.read_text(), bad_text)


if __name__ == "__main__":
    unittest.main()
