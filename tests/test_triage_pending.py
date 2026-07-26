"""Tests for scripts/triage_pending.py.

Every test builds its Brain under tmp_path — nothing here reads the real Vault.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import triage_pending as tp  # noqa: E402

HEADER = (
    "| # | capture | preview | route | destination | confidence | rule | approve |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def row(n, dest="unmatched", approve="[ ]", route="Pass B"):
    return (f"| {n} | [[inbox/raw/email/cap-{n}.md]] | preview… | {route} | "
            f"{dest} | — | — | {approve} |\n")


def plan(rows, status="pending", source="email", date="2026-07-23"):
    return (f"---\ntype: triage-plan\nsource: {source}\ndate: {date}\n"
            f"status: {status}\n---\n\n# Triage Plan — {source} — {date}\n\n"
            + HEADER + "".join(rows))


class TriageDirFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        self.triage = self.brain / "inbox" / "triage"
        self.triage.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, content):
        (self.triage / name).write_text(content, encoding="utf-8")

    def scan(self):
        return tp.scan_plans(self.triage)


class TestCounting(TriageDirFixture):
    def test_unmatched_rows_count_as_awaiting_pass_b(self):
        self.write("2026-07-23-email.md", plan([row(1), row(2), row(3)]))
        c = self.scan()
        self.assertEqual(c["awaiting_pass_b"], 3)
        self.assertEqual(c["awaiting_execute"], 0)

    def test_routed_but_unticked_rows_await_execute(self):
        """The other half of the queue: Pass A resolved it, a human hasn't ticked it."""
        self.write("2026-07-23-email.md",
                   plan([row(1, dest="projects/goals-os/Goals OS.md", route="Pass A"),
                         row(2)]))
        c = self.scan()
        self.assertEqual(c["awaiting_pass_b"], 1)
        self.assertEqual(c["awaiting_execute"], 1)

    def test_ticked_rows_are_not_pending(self):
        self.write("2026-07-23-email.md", plan([
            row(1, approve="[x]"),
            row(2, approve="[x] (done)"),
            row(3, approve="[x] (dispatched)"),
            row(4),
        ]))
        c = self.scan()
        self.assertEqual(c["awaiting_pass_b"], 1)
        self.assertEqual(c["awaiting_execute"], 0)

    def test_executed_plans_are_skipped(self):
        self.write("2026-07-23-email.md", plan([row(1)], status="executed"))
        self.assertEqual(self.scan()["plans"], 0)

    def test_plans_with_no_pending_rows_are_not_counted_as_open(self):
        self.write("2026-07-23-email.md", plan([row(1, approve="[x]")]))
        self.assertEqual(self.scan()["plans"], 0)

    def test_counts_split_by_source_across_plans(self):
        self.write("2026-07-23-email.md", plan([row(1), row(2)], source="email"))
        self.write("2026-07-23-youtube.md", plan([row(1)], source="youtube",
                                                 date="2026-07-23"))
        self.write("2026-07-24-email.md", plan([row(1)], source="email",
                                               date="2026-07-24"))
        c = self.scan()
        self.assertEqual(c["by_source"]["email"], (3, 0))
        self.assertEqual(c["by_source"]["youtube"], (1, 0))
        self.assertEqual(c["plans"], 3)

    def test_missing_triage_dir_is_zero_not_a_crash(self):
        """A Brain that has never triaged must not break a session-start hook."""
        c = tp.scan_plans(self.brain / "nope")
        self.assertEqual(c["awaiting_pass_b"], 0)
        self.assertEqual(c["plans"], 0)

    def test_a_plan_with_no_status_key_counts_as_open(self):
        text = ("---\ntype: triage-plan\nsource: email\n---\n\n# Triage Plan\n\n"
                + HEADER + row(1))
        self.write("2026-07-23-email.md", text)
        self.assertEqual(self.scan()["awaiting_pass_b"], 1)


class TestOutput(TriageDirFixture):
    def test_line_names_both_queues(self):
        self.write("2026-07-23-email.md",
                   plan([row(1), row(2, dest="today", route="Pass A")]))
        line = tp.format_line(self.scan())
        self.assertIn("2 row(s) pending", line)
        self.assertIn("1 awaiting Pass B", line)
        self.assertIn("1 awaiting Execute", line)

    def test_empty_queue_says_so(self):
        self.assertEqual(tp.format_line(self.scan()), "Triage: nothing pending.")

    def test_quiet_if_zero_prints_nothing(self):
        """The session-start hook must stay silent on a clean queue."""
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = tp.main(["--brain", str(self.brain), "--quiet-if-zero"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_report_format_breaks_down_by_source(self):
        self.write("2026-07-23-email.md", plan([row(1), row(2)]))
        out = tp.format_report(self.scan())
        self.assertIn("email", out)
        self.assertIn("awaiting Pass B", out)

    def test_main_exits_zero_with_a_backlog(self):
        """Never a non-zero exit — this runs in a session-start hook, and a
        non-zero would surface as a hook failure rather than a nudge."""
        self.write("2026-07-23-email.md", plan([row(1)]))
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tp.main(["--brain", str(self.brain)]), 0)


class TestSharedParser(TriageDirFixture):
    def test_it_uses_executes_own_row_parser(self):
        """Reusing execute.ROW_RE is what stops the nudge and the executor
        disagreeing about what a row is — a row execute.py cannot parse must
        not be silently counted as pending here."""
        self.write("2026-07-23-email.md", plan([row(1)]) +
                   "| 2 | not-a-wikilink | x | Pass B | unmatched | — | — | [ ] |\n")
        self.assertEqual(self.scan()["awaiting_pass_b"], 1)


if __name__ == "__main__":
    unittest.main()
