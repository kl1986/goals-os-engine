import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import rule_diff_review  # noqa: E402

BATCH_TEXT = """---
type: rule-diff-batch
ruleset: routing-rules
date: 2026-07-15
status: pending
---

# Rule diffs — routing-rules — 2026-07-15

### Diff 1 — sonia-email-to-work

```
if: source == "email" and contains("sonia")
then: route -> areas/work/_inbox.md
confidence: High
```

**Why:** Two corrections in the last week moved SONIA curve emails from Home to Work.

**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]

- [ ] Approve
- [ ] Reject

### Diff 2 — junk-newsletter-discard

```
if: source == "email" and contains("unsubscribe")
then: route -> discard
confidence: Medium
```

**Why:** Repeated newsletter noise corrected to discard twice this week.

**Evidence:** [[log/2026-07-09#08:00 — file-email]], [[log/2026-07-10#08:05 — file-email]]

- [ ] Approve
- [ ] Reject
"""


class TestDiffKey(unittest.TestCase):
    def test_deterministic_and_ruleset_scoped(self):
        k1 = rule_diff_review.diff_key("routing-rules", "if: x\nthen: y\n")
        k2 = rule_diff_review.diff_key("routing-rules", "if: x\nthen: y\n")
        k3 = rule_diff_review.diff_key("other-rules", "if: x\nthen: y\n")
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)

    def test_whitespace_insensitive_at_the_edges(self):
        k1 = rule_diff_review.diff_key("routing-rules", "if: x\nthen: y")
        k2 = rule_diff_review.diff_key("routing-rules", "  if: x\nthen: y  \n")
        self.assertEqual(k1, k2)


class TestParseBatch(unittest.TestCase):
    def test_parses_both_diffs_undecided(self):
        diffs = rule_diff_review.parse_batch(BATCH_TEXT)
        self.assertEqual(len(diffs), 2)
        self.assertEqual(diffs[0]["n"], "1")
        self.assertEqual(diffs[0]["slug"], "sonia-email-to-work")
        self.assertIn('if: source == "email" and contains("sonia")', diffs[0]["rule_block"])
        self.assertIn("Two corrections", diffs[0]["why"])
        self.assertEqual(len(diffs[0]["evidence"]), 2)
        self.assertEqual(diffs[0]["evidence"][0], "log/2026-07-08#14:32 — file-email")
        self.assertFalse(diffs[0]["approve_ticked"])
        self.assertFalse(diffs[0]["reject_ticked"])
        self.assertIsNone(diffs[0]["approve_state"])

    def test_parses_ticked_and_processed_states(self):
        text = BATCH_TEXT.replace(
            "### Diff 1 — sonia-email-to-work\n\n```\nif: source == \"email\" and contains(\"sonia\")\nthen: route -> areas/work/_inbox.md\nconfidence: High\n```\n\n**Why:** Two corrections in the last week moved SONIA curve emails from Home to Work.\n\n**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]\n\n- [ ] Approve\n- [ ] Reject",
            "### Diff 1 — sonia-email-to-work\n\n```\nif: source == \"email\" and contains(\"sonia\")\nthen: route -> areas/work/_inbox.md\nconfidence: High\n```\n\n**Why:** Two corrections in the last week moved SONIA curve emails from Home to Work.\n\n**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]\n\n- [x] (applied) Approve\n- [ ] Reject",
        )
        diffs = rule_diff_review.parse_batch(text)
        self.assertTrue(diffs[0]["approve_ticked"])
        self.assertEqual(diffs[0]["approve_state"], "applied")

    def test_no_diffs_in_empty_batch(self):
        self.assertEqual(rule_diff_review.parse_batch("---\nstatus: pending\n---\n\nnothing here\n"), [])


class TestApplyBatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routing-rules.md").write_text(
            "---\ntype: config\nconfig: routing-rules\n---\n\n"
            "# Routing rules\n\n"
            "```\n# if: source == \"text\" and contains(\"milk\")\n"
            "# then: route -> areas/home/_inbox.md\n# confidence: High\n```\n"
        )
        (self.brain_path / "inbox" / "rule-diffs").mkdir(parents=True)
        self.batch_path = self.brain_path / "inbox" / "rule-diffs" / "2026-07-15-routing-rules.md"
        self.now = dt.datetime(2026, 7, 15, 21, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_batch(self, text):
        self.batch_path.write_text(text)

    @staticmethod
    def _approve_diff1_reject_diff2(text):
        text = text.replace("- [ ] Approve\n- [ ] Reject", "- [x] Approve\n- [ ] Reject", 1)
        idx = text.find("- [ ] Approve\n- [ ] Reject")
        return text[:idx] + "- [ ] Approve\n- [x] Reject" + text[idx + len("- [ ] Approve\n- [ ] Reject"):]

    def test_undecided_batch_stays_pending_and_in_place(self):
        self._write_batch(BATCH_TEXT)
        result = rule_diff_review.apply_batch(self.brain_path, self.batch_path, now=self.now)
        self.assertEqual(result["applied"], [])
        self.assertEqual(result["rejected"], [])
        self.assertFalse(result["batch_resolved"])
        self.assertTrue(self.batch_path.exists())
        self.assertIn("status: pending", self.batch_path.read_text())

    def test_one_approved_one_rejected_resolves_and_archives(self):
        text = self._approve_diff1_reject_diff2(BATCH_TEXT)
        self._write_batch(text)

        result = rule_diff_review.apply_batch(self.brain_path, self.batch_path, now=self.now)

        self.assertEqual(result["applied"], ["1"])
        self.assertEqual(result["rejected"], ["2"])
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["batch_resolved"])

        # Ruleset file gained the approved block only, additive-only —
        # existing (commented) example rule untouched.
        ruleset_text = (self.brain_path / "config" / "routing-rules.md").read_text()
        self.assertIn('if: source == "email" and contains("sonia")', ruleset_text)
        self.assertIn('# if: source == "text" and contains("milk")', ruleset_text)
        self.assertNotIn("unsubscribe", ruleset_text)  # rejected diff never written

        # Log entries correctly shaped.
        log_text = (self.brain_path / "log" / "2026-07-15.md").read_text()
        self.assertIn("apply-rule-diff", log_text)
        self.assertIn("reject-rule-diff", log_text)
        self.assertIn("Rule appended to config/routing-rules.md", log_text)
        self.assertIn("No write — config/routing-rules.md unchanged", log_text)
        self.assertEqual(log_text.count("### "), 2)

        # Batch archived, not left in inbox/rule-diffs/.
        self.assertFalse(self.batch_path.exists())
        archived_text = result["archived_to"].read_text()
        self.assertEqual(result["archived_to"].parent, self.brain_path / "archive" / "rule-diffs")
        self.assertIn("status: resolved", archived_text)
        self.assertIn("[x] (applied) Approve", archived_text)
        self.assertIn("[x] (logged) Reject", archived_text)

    def test_one_decided_one_undecided_stays_pending_but_processes_the_decided_one(self):
        text = BATCH_TEXT.replace("- [ ] Approve\n- [ ] Reject", "- [x] Approve\n- [ ] Reject", 1)
        self._write_batch(text)

        result = rule_diff_review.apply_batch(self.brain_path, self.batch_path, now=self.now)

        self.assertEqual(result["applied"], ["1"])
        self.assertFalse(result["batch_resolved"])
        self.assertTrue(self.batch_path.exists())
        text_after = self.batch_path.read_text()
        self.assertIn("status: pending", text_after)
        self.assertIn("[x] (applied) Approve", text_after)
        self.assertIn("- [ ] Approve\n- [ ] Reject", text_after)  # diff 2 untouched

    def test_rerun_after_full_resolution_does_not_duplicate_log_entries(self):
        text = self._approve_diff1_reject_diff2(BATCH_TEXT)
        self._write_batch(text)
        rule_diff_review.apply_batch(self.brain_path, self.batch_path, now=self.now)

        # Batch now archived; running again against the archived copy
        # (simulating a stray re-invocation) must not re-log or re-append.
        archived_path = self.brain_path / "archive" / "rule-diffs" / "2026-07-15-routing-rules.md"
        result = rule_diff_review.apply_batch(self.brain_path, archived_path, now=self.now)

        self.assertEqual(result["applied"], [])
        self.assertEqual(result["rejected"], [])
        log_text = (self.brain_path / "log" / "2026-07-15.md").read_text()
        # Each entry mentions its action type twice (the "### HH:MM — <type>"
        # heading plus the "**action type:**" field) — two entries total
        # (one apply, one reject) means exactly two headings, not four.
        self.assertEqual(log_text.count("### "), 2)
        self.assertEqual(log_text.count("apply-rule-diff"), 2)
        self.assertEqual(log_text.count("reject-rule-diff"), 2)

    def test_fewer_than_two_evidence_links_is_reported_and_left_pending(self):
        text = BATCH_TEXT.replace(
            "**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]\n\n- [ ] Approve\n- [ ] Reject\n\n### Diff 2",
            "**Evidence:** [[log/2026-07-08#14:32 — file-email]]\n\n- [x] Approve\n- [ ] Reject\n\n### Diff 2",
        )
        self._write_batch(text)

        result = rule_diff_review.apply_batch(self.brain_path, self.batch_path, now=self.now)

        self.assertEqual(result["applied"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("evidence", result["errors"][0])
        self.assertFalse(result["batch_resolved"])
        ruleset_text = (self.brain_path / "config" / "routing-rules.md").read_text()
        self.assertNotIn("sonia", ruleset_text)

    def test_both_boxes_ticked_is_an_error(self):
        text = BATCH_TEXT.replace(
            "### Diff 1 — sonia-email-to-work\n\n```\nif: source == \"email\" and contains(\"sonia\")\nthen: route -> areas/work/_inbox.md\nconfidence: High\n```\n\n**Why:** Two corrections in the last week moved SONIA curve emails from Home to Work.\n\n**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]\n\n- [ ] Approve\n- [ ] Reject",
            "### Diff 1 — sonia-email-to-work\n\n```\nif: source == \"email\" and contains(\"sonia\")\nthen: route -> areas/work/_inbox.md\nconfidence: High\n```\n\n**Why:** Two corrections in the last week moved SONIA curve emails from Home to Work.\n\n**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]\n\n- [x] Approve\n- [x] Reject",
        )
        self._write_batch(text)

        result = rule_diff_review.apply_batch(self.brain_path, self.batch_path, now=self.now)

        self.assertEqual(result["applied"], [])
        self.assertEqual(result["rejected"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("both Approve and Reject", result["errors"][0])

    def test_target_ruleset_file_missing_raises(self):
        (self.brain_path / "config" / "routing-rules.md").unlink()
        text = BATCH_TEXT.replace("- [ ] Approve\n- [ ] Reject", "- [x] Approve\n- [ ] Reject")
        self._write_batch(text)
        with self.assertRaises(rule_diff_review.RuleDiffReviewError):
            rule_diff_review.apply_batch(self.brain_path, self.batch_path, now=self.now)


if __name__ == "__main__":
    unittest.main()
