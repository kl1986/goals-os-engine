"""Tests for scripts/migrate_triage_plan_rows.py (ADR-0031's conversion step).

Every test builds its Brain under a temp dir — nothing here touches a real Vault.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import execute  # noqa: E402
import migrate_triage_plan_rows as migrate  # noqa: E402
import triage  # noqa: E402

OLD_PLAN = """---
type: triage-plan
source: email
date: 2026-07-27
status: pending
---

# Triage Plan — email — 2026-07-27

| # | capture | preview | route | destination | confidence | rule | approve |
|---|---|---|---|---|---|---|---|
| 1 | [[inbox/raw/email/a.md]] | LinkedIn Job Alerts · "Credit Manager" | Pass B | discard | — | — | [ ] |
| 2 | [[inbox/raw/email/b.md]] | An invoice from the accountant | Pass A | areas/finances/_inbox.md | High | a1b2c3d4 | [x] (done) |
| 3 | [[inbox/raw/email/c.md]] | more junk | Pass B | discard | Medium | — | [x] |
| 4 | [[inbox/raw/email/d.md]] | dispatched to an agent | Pass B | agent: Researcher | Low | — | [x] (dispatched) |
"""

# Pre-`rule`-column Plan (7 columns). A Brain can still hold one; converting it
# with `—` is exactly what a Row that predates rule tracking means.
OLD_PLAN_NO_RULE_COLUMN = """---
type: triage-plan
source: voice
date: 2026-07-11
status: pending
---

# Triage Plan — voice — 2026-07-11

| # | capture | preview | route | destination | confidence | approve |
|---|---|---|---|---|---|---|
| 1 | [[inbox/raw/voice/x.md]] | preview | Pass A | areas/household/_inbox.md | High | [ ] |
"""

# Row 2's approve cell is `[X]` — iOS autocapitalise. It is a real approval the
# user made, and it is not recoverable from `inbox/raw/`, so it must stop the
# conversion rather than be dropped.
PLAN_WITH_AN_UNPARSEABLE_ROW = """---
type: triage-plan
source: email
date: 2026-07-27
status: pending
---

# Triage Plan — email — 2026-07-27

| # | capture | preview | route | destination | confidence | rule | approve |
|---|---|---|---|---|---|---|---|
| 1 | [[inbox/raw/email/a.md]] | good | Pass A | discard | High | e1 | [ ] |
| 2 | [[inbox/raw/email/b.md]] | approved but hand-typed | Pass A | discard | High | e1 | [X] |
"""


class TestConvertPlanText(unittest.TestCase):
    def setUp(self):
        self.converted = migrate.convert_plan_text(OLD_PLAN)
        self.rows = {r["preview"]: r for r in execute.parse_plan_rows(self.converted)}

    def test_every_row_survives(self):
        self.assertEqual(len(self.rows), 4)

    def test_an_unparseable_table_row_is_refused_not_dropped(self):
        """The conversion rewrites the file from the rows it parsed, so a row
        it cannot parse would be deleted — taking the user's approval state
        and any Pass-B work with it. It must refuse the file instead."""
        with self.assertRaises(migrate.UnconvertiblePlanError) as ctx:
            migrate.convert_plan_text(PLAN_WITH_AN_UNPARSEABLE_ROW)
        message = str(ctx.exception)
        self.assertIn("line 13", message)  # 1-based, as an editor shows it
        self.assertIn("[X]", message)

    def test_unparseable_lines_names_only_the_offenders(self):
        offenders = migrate.unparseable_table_lines(PLAN_WITH_AN_UNPARSEABLE_ROW)
        self.assertEqual(len(offenders), 1)
        self.assertIn("hand-typed", offenders[0][1])

    def test_header_and_separator_are_not_offenders(self):
        self.assertEqual(migrate.unparseable_table_lines(OLD_PLAN), [])
        self.assertEqual(migrate.unparseable_table_lines(OLD_PLAN_NO_RULE_COLUMN), [])

    def test_a_row_missing_a_trailing_cell_is_refused(self):
        text = (OLD_PLAN
                + "| 5 | [[inbox/raw/email/e.md]] | truncated | Pass A | discard | High |\n")
        with self.assertRaises(migrate.UnconvertiblePlanError):
            migrate.convert_plan_text(text)

    def test_a_row_with_an_extra_cell_is_refused_not_garbled(self):
        """An extra cell used to match with the fields shifted along —
        `confidence='High | e1'`, `rule='extra'`. Nothing was lost, but the
        converted Row was wrong, so it belongs with the other malformed shapes:
        the cells are bounded to `[^|]`, and the line refuses the file."""
        row = ("| 5 | [[inbox/raw/email/e.md]] | good | Pass A | discard "
               "| High | e1 | extra | [ ] |")
        self.assertIsNone(migrate.OLD_ROW_RE.match(row))
        offenders = migrate.unparseable_table_lines(OLD_PLAN + row + "\n")
        self.assertEqual(len(offenders), 1)
        self.assertIn("extra", offenders[0][1])
        with self.assertRaises(migrate.UnconvertiblePlanError):
            migrate.convert_plan_text(OLD_PLAN + row + "\n")

    def test_bounding_the_cells_did_not_break_the_normal_shapes(self):
        # Guards the tightening: both live column counts must still parse.
        self.assertEqual(len(migrate.parse_old_rows(OLD_PLAN)), 4)
        self.assertEqual(len(migrate.parse_old_rows(OLD_PLAN_NO_RULE_COLUMN)), 1)

    def test_no_table_syntax_is_left_behind(self):
        self.assertNotIn("|---|", self.converted)
        self.assertNotIn("| # |", self.converted)

    def test_frontmatter_and_title_are_preserved(self):
        self.assertTrue(self.converted.startswith("---\ntype: triage-plan\n"))
        self.assertIn("status: pending", self.converted)
        self.assertIn("# Triage Plan — email — 2026-07-27", self.converted)

    def test_every_field_is_preserved(self):
        row = self.rows["An invoice from the accountant"]
        self.assertEqual(row["destination"], "areas/finances/_inbox.md")
        self.assertEqual(row["route"], "Pass A")
        self.assertEqual(row["confidence"], "High")
        self.assertEqual(row["rule"], "a1b2c3d4")
        self.assertEqual(row["preview"], "An invoice from the accountant")
        self.assertEqual(row["capture"], "inbox/raw/email/b.md")

    def test_approval_and_executed_state_are_preserved(self):
        self.assertEqual(self.rows['LinkedIn Job Alerts · "Credit Manager"']["approve"], "[ ]")
        self.assertEqual(self.rows["An invoice from the accountant"]["approve"], "[x] (done)")
        self.assertEqual(self.rows["more junk"]["approve"], "[x]")
        self.assertEqual(self.rows["dispatched to an agent"]["approve"], "[x] (dispatched)")

    def test_rows_are_grouped_under_destination_headings(self):
        self.assertIn("## discard\n", self.converted)
        self.assertIn("## areas/finances/_inbox.md\n", self.converted)
        self.assertIn("## agent: Researcher\n", self.converted)
        # One heading per destination, however many Rows share it.
        self.assertEqual(self.converted.count("## discard"), 1)

    def test_converted_plan_is_already_regrouped(self):
        """Every Row lands under a heading matching its own destination, so
        the re-grouper is a no-op on a freshly converted Plan."""
        self.assertEqual(execute.regroup_plan(self.converted), self.converted)

    def test_conversion_is_idempotent(self):
        self.assertEqual(migrate.convert_plan_text(self.converted), self.converted)

    def test_numbering_continues_from_the_highest_converted_number(self):
        self.assertEqual(triage.next_row_number(self.converted), 5)

    def test_a_preview_containing_the_field_separator_still_round_trips(self):
        self.assertIn('LinkedIn Job Alerts · "Credit Manager"', self.rows)

    def test_a_plan_with_no_rule_column_converts_with_a_dash(self):
        converted = migrate.convert_plan_text(OLD_PLAN_NO_RULE_COLUMN)
        row = execute.parse_plan_rows(converted)[0]
        self.assertEqual(row["rule"], "—")
        self.assertEqual(row["destination"], "areas/household/_inbox.md")

    def test_a_plan_with_nothing_to_convert_is_returned_unchanged(self):
        text = "---\ntype: triage-plan\nstatus: pending\n---\n\n# Empty\n"
        self.assertEqual(migrate.convert_plan_text(text), text)


class TestMigrate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        self.triage_dir = self.brain / "inbox" / "triage"
        self.triage_dir.mkdir(parents=True)
        self.archive_dir = self.brain / "archive" / "triage"
        self.archive_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_converts_every_open_plan(self):
        (self.triage_dir / "2026-07-27-email.md").write_text(OLD_PLAN)
        (self.triage_dir / "2026-07-11-voice.md").write_text(OLD_PLAN_NO_RULE_COLUMN)

        result = migrate.migrate(self.brain)

        self.assertEqual(result["converted"],
                         {"2026-07-11-voice.md": 1, "2026-07-27-email.md": 4})
        self.assertEqual(result["refused"], {})
        for name in result["converted"]:
            self.assertNotIn("|---|", (self.triage_dir / name).read_text())

    def test_a_refused_plan_is_left_untouched_and_does_not_block_the_others(self):
        good = self.triage_dir / "2026-07-27-email.md"
        good.write_text(OLD_PLAN)
        bad = self.triage_dir / "2026-07-28-email.md"
        bad.write_text(PLAN_WITH_AN_UNPARSEABLE_ROW)

        result = migrate.migrate(self.brain)

        self.assertEqual(result["converted"], {"2026-07-27-email.md": 4})
        self.assertIn("2026-07-28-email.md", result["refused"])
        self.assertEqual(bad.read_text(), PLAN_WITH_AN_UNPARSEABLE_ROW)
        self.assertNotIn("|---|", good.read_text())

    def test_dry_run_refuses_too(self):
        """A refusal that only fired on the real run would let --dry-run report
        a clean bill of health for a file that cannot safely be converted."""
        bad = self.triage_dir / "2026-07-28-email.md"
        bad.write_text(PLAN_WITH_AN_UNPARSEABLE_ROW)

        result = migrate.migrate(self.brain, dry_run=True)

        self.assertIn("2026-07-28-email.md", result["refused"])
        self.assertEqual(result["converted"], {})

    def test_cli_exits_non_zero_on_a_refusal(self):
        (self.triage_dir / "2026-07-28-email.md").write_text(PLAN_WITH_AN_UNPARSEABLE_ROW)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as ctx:
                migrate.main(["--brain", str(self.brain)])
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("REFUSED", err.getvalue())

    def test_archived_plans_are_never_touched(self):
        archived = self.archive_dir / "2026-07-01-email.md"
        archived.write_text(OLD_PLAN)
        (self.triage_dir / "2026-07-27-email.md").write_text(OLD_PLAN)

        migrate.migrate(self.brain)

        self.assertEqual(archived.read_text(), OLD_PLAN)

    def test_dry_run_reports_without_writing(self):
        plan = self.triage_dir / "2026-07-27-email.md"
        plan.write_text(OLD_PLAN)

        result = migrate.migrate(self.brain, dry_run=True)

        self.assertEqual(result["converted"], {"2026-07-27-email.md": 4})
        self.assertEqual(plan.read_text(), OLD_PLAN)

    def test_second_run_is_a_no_op(self):
        plan = self.triage_dir / "2026-07-27-email.md"
        plan.write_text(OLD_PLAN)
        migrate.migrate(self.brain)
        after_first = plan.read_text()

        self.assertEqual(migrate.migrate(self.brain),
                         {"converted": {}, "refused": {}})
        self.assertEqual(plan.read_text(), after_first)

    def test_missing_triage_dir_is_not_a_crash(self):
        self.assertEqual(migrate.migrate(Path(self._tmp.name) / "nope"),
                         {"converted": {}, "refused": {}})


class TestConvertedPlanStillWorks(unittest.TestCase):
    """The converted Plan must be a live Plan, not just well-formed text:
    Execute acts on its ticked Rows, and Triage adds to it without
    duplicating a capture or reusing a row number."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        (self.brain / "inbox" / "triage").mkdir(parents=True)
        (self.brain / "inbox" / "raw" / "email").mkdir(parents=True)
        (self.brain / "areas" / "finances").mkdir(parents=True)
        for name in ("a.md", "b.md", "c.md", "d.md"):
            (self.brain / "inbox" / "raw" / "email" / name).write_text(
                "---\nid: cap\n---\n\n# Cap\n\nbody\n"
            )
        self.plan = self.brain / "inbox" / "triage" / "2026-07-27-email.md"
        self.plan.write_text(OLD_PLAN)
        migrate.migrate(self.brain)

    def tearDown(self):
        self._tmp.cleanup()

    def test_execute_acts_on_exactly_the_ticked_rows(self):
        import datetime as dt
        result = execute.execute_plan(
            self.brain, self.plan, now=dt.datetime(2026, 7, 27, 9, 0)
        )
        self.assertEqual(result["errors"], [])
        # Row 3 is `[x]` discard; row 4 is `[x] (dispatched)` and already done;
        # rows 1 (untidied `[ ]`) and 2 (`[x] (done)`) must not move.
        self.assertEqual(result["discarded"], ["inbox/raw/email/c.md"])
        self.assertEqual(result["filed"], [])
        self.assertTrue((self.brain / "inbox" / "raw" / "email" / "a.md").exists())

    def test_triage_adds_only_new_captures_and_keeps_numbering(self):
        match_result = {
            "routed": [],
            "unmatched": [
                # Already in the Plan, by wikilink — must not gain a second Row.
                {"id": "a", "source": "email", "title": "A", "body": "body",
                 "path": "inbox/raw/email/a.md"},
                {"id": "e", "source": "email", "title": "E", "body": "new one",
                 "path": "inbox/raw/email/e.md"},
            ],
        }
        triage.write_triage_plan(self.brain, "email", match_result, date_str="2026-07-27")
        rows = execute.parse_plan_rows(self.plan.read_text())
        captures = [r["capture"] for r in rows]
        self.assertEqual(captures.count("inbox/raw/email/a.md"), 1)
        self.assertIn("inbox/raw/email/e.md", captures)
        self.assertEqual(sorted(r["n"] for r in rows), ["1", "2", "3", "4", "5"])


if __name__ == "__main__":
    unittest.main()
