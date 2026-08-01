import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import execute
import migrate_triage_rows_one_line as migrate


OLD_PLAN_TEXT = """---
type: triage-plan
source: email
date: 2026-08-01
status: pending
---

# Triage Plan — email — 2026-08-01

## unmatched

- [ ] **1** → `unmatched` %%· Pass B · — · —%%
    ICAS / CA Weekly — Ten factors shaping the UK economy
    [[inbox/raw/email/2026-07-29-010012-ten-factors-shaping-the-uk-economy.md]]

## discard

- [ ] **2** → `discard` %%· Pass A · High · bc2e56b6%%
    Big Game Hunters — Payday Sale Reminder: 15% Off
    [[inbox/raw/email/2026-07-29-010013-payday-sale.md]]
"""


class TestMigrateTriageRowsOneLine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.brain = Path(self.tmpdir.name)
        self.triage_dir = self.brain / "inbox" / "triage"
        self.triage_dir.mkdir(parents=True, exist_ok=True)
        self.plan_path = self.triage_dir / "2026-08-01-email.md"
        self.plan_path.write_text(OLD_PLAN_TEXT, encoding="utf-8")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_converts_old_3_line_format_to_one_line_with_keeper_options(self):
        res = migrate.migrate_brain(self.brain, dry_run=False)
        self.assertEqual(res["converted"], {"2026-08-01-email.md": 2})
        self.assertEqual(res["refused"], {})

        new_text = self.plan_path.read_text(encoding="utf-8")

        # Verify frontmatter rules
        self.assertIn("rules:", new_text)
        self.assertIn("2026-07-29-010013-payday-sale.md:", new_text)
        self.assertIn("rule: bc2e56b6", new_text)

        # Verify check_row_blocks returns empty
        errors = execute.check_row_blocks(new_text)
        self.assertEqual(errors, [])

        # Verify parsed rows
        rows = execute.parse_plan_rows(new_text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["preview"], "ICAS / CA Weekly — Ten factors shaping the UK economy")
        self.assertEqual(rows[0]["destinations"], ["unmatched"])
        self.assertEqual(len(rows[0]["options"]), 4)

        self.assertEqual(rows[1]["preview"], "Big Game Hunters — Payday Sale Reminder: 15% Off")
        self.assertEqual(rows[1]["destinations"], ["discard"])
        self.assertEqual(rows[1]["route"], "Pass A")
        self.assertEqual(rows[1]["rule"], "bc2e56b6")
        self.assertEqual(len(rows[1]["options"]), 0)

    def test_idempotent_second_run_is_no_op(self):
        migrate.migrate_brain(self.brain, dry_run=False)
        res2 = migrate.migrate_brain(self.brain, dry_run=False)
        self.assertEqual(res2["converted"], {})
        self.assertEqual(res2["refused"], {})

    def test_dry_run_does_not_modify_file(self):
        res = migrate.migrate_brain(self.brain, dry_run=True)
        self.assertEqual(res["converted"], {"2026-08-01-email.md": 2})
        self.assertEqual(self.plan_path.read_text(encoding="utf-8"), OLD_PLAN_TEXT)

    def test_regrouped_order_and_ticked_rows_conversion(self):
        regroup_plan_text = """---
type: triage-plan
source: email
date: 2026-08-01
status: pending
---

# Triage Plan — email — 2026-08-01

## discard

- [x] **1** → `discard` %%· Pass A · High · rule1%%
    Item Discard
    [[inbox/raw/email/2026-07-29-000001-discard.md]]

## unmatched

- [x] **2** → `unmatched` %%· Pass B · — · —%%
    Item Unmatched
    [[inbox/raw/email/2026-07-29-000002-unmatched.md]]
"""
        plan2 = self.triage_dir / "2026-08-01-regroup.md"
        plan2.write_text(regroup_plan_text, encoding="utf-8")

        res = migrate.migrate_brain(self.brain, dry_run=False)
        self.assertIn("2026-08-01-regroup.md", res["converted"])
        self.assertEqual(res["refused"], {})

        new_text = plan2.read_text(encoding="utf-8")
        rows = execute.parse_plan_rows(new_text)
        self.assertEqual(len(rows), 2)

        row_map = {r["capture"]: r for r in rows}
        self.assertEqual(row_map["inbox/raw/email/2026-07-29-000001-discard.md"]["approve"], "[x]")
        self.assertEqual(row_map["inbox/raw/email/2026-07-29-000002-unmatched.md"]["approve"], "[x]")

    def test_migrates_legacy_markdown_table_plan_and_preserves_dry_run(self):
        legacy_table_plan = (
            "---\ntype: triage-plan\nsource: email\ndate: 2026-08-01\nstatus: pending\n---\n\n"
            "# Triage Plan — email — 2026-08-01\n\n"
            "| # | capture | preview | route | destination | confidence | rule | approve |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| 1 | [[inbox/raw/email/cap-1.md]] | Item 1 | Pass B | unmatched | High | — | [ ] |\n"
            "| 2 | [[inbox/raw/email/cap-2.md]] | Item 2 | Pass A | discard | High | r1 | [x] |\n"
        )
        plan_path = self.triage_dir / "2026-08-01-table.md"
        plan_path.write_text(legacy_table_plan, encoding="utf-8")

        # Test dry-run: reports conversion, file content unchanged
        res_dry = migrate.migrate_brain(self.brain, dry_run=True)
        self.assertIn("2026-08-01-table.md", res_dry["converted"])
        self.assertEqual(plan_path.read_text(encoding="utf-8"), legacy_table_plan)

        # Real run: converts to 1-line shape
        res = migrate.migrate_brain(self.brain, dry_run=False)
        self.assertIn("2026-08-01-table.md", res["converted"])
        new_text = plan_path.read_text(encoding="utf-8")
        self.assertFalse(execute.requires_migration(new_text))
        rows = execute.parse_plan_rows(new_text)
        self.assertEqual(len(rows), 2)

    def test_legacy_table_with_dash_destination_refuses(self):
        legacy_table_plan_dash = (
            "---\ntype: triage-plan\nsource: email\ndate: 2026-08-01\nstatus: pending\n---\n\n"
            "# Triage Plan — email — 2026-08-01\n\n"
            "| # | capture | preview | route | destination | confidence | rule | approve |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| 1 | [[inbox/raw/email/cap-1.md]] | Item 1 | Pass B | — | High | — | [ ] |\n"
        )
        plan_path = self.triage_dir / "2026-08-01-table-dash.md"
        plan_path.write_text(legacy_table_plan_dash, encoding="utf-8")

        res = migrate.migrate_brain(self.brain, dry_run=False)
        self.assertIn("2026-08-01-table-dash.md", res["refused"])
        self.assertNotIn("2026-08-01-table-dash.md", res["converted"])
        self.assertEqual(plan_path.read_text(encoding="utf-8"), legacy_table_plan_dash)

    def test_unparseable_legacy_table_refuses(self):
        legacy_table_plan_unparseable = (
            "---\ntype: triage-plan\nsource: email\ndate: 2026-08-01\nstatus: pending\n---\n\n"
            "# Triage Plan — email — 2026-08-01\n\n"
            "| # | capture | preview | route | destination | confidence | rule | approve |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| 1 | [[inbox/raw/email/cap-1.md]] | Item 1 | Pass B | discard | High | — | [X] |\n"
        )
        plan_path = self.triage_dir / "2026-08-01-table-unparseable.md"
        plan_path.write_text(legacy_table_plan_unparseable, encoding="utf-8")

        res = migrate.migrate_brain(self.brain, dry_run=False)
        self.assertIn("2026-08-01-table-unparseable.md", res["refused"])
        self.assertNotIn("2026-08-01-table-unparseable.md", res["converted"])
        self.assertEqual(plan_path.read_text(encoding="utf-8"), legacy_table_plan_unparseable)


if __name__ == "__main__":
    unittest.main()
