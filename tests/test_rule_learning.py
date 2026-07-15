import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import heartbeat  # noqa: E402
import rule_learning  # noqa: E402


def _log_text(entries: str) -> str:
    return f"# Action Log — 2026-07-08\n\n{entries}"


ENTRY_SONIA_1 = (
    "### 14:32 — file-email\n\n"
    "- **entry id:** a1b2c3d4\n"
    "- **actor:** EA\n"
    "- **trigger:** Triage (Routine)\n"
    "- **input link:** inbox/raw/email/2026-07-08-sonia-curve.md\n"
    "- **action type:** file-email\n"
    "- **action:** Filed under Home > Finances.\n"
    "- **confidence:** Medium\n"
    "- **outcome:** Filed to areas/home/_inbox/\n"
    "- **parent reference:** —\n"
    "- **feedback:** corrected — should have gone to Work, this is a SONIA curve email\n"
)

ENTRY_SONIA_2 = (
    "### 09:15 — file-email\n\n"
    "- **entry id:** e5f6a7b8\n"
    "- **actor:** EA\n"
    "- **trigger:** Triage (Routine)\n"
    "- **input link:** inbox/raw/email/2026-07-12-sonia-swaps.md\n"
    "- **action type:** file-email\n"
    "- **action:** Filed under Home > Finances.\n"
    "- **confidence:** Medium\n"
    "- **outcome:** Filed to areas/home/_inbox/\n"
    "- **parent reference:** —\n"
    "- **feedback:** corrected — SONIA swaps email, should route to Work not Home\n"
)

ENTRY_UNRELATED_VALIDATED = (
    "### 08:00 — file-capture\n\n"
    "- **entry id:** c9d0e1f2\n"
    "- **actor:** EA\n"
    "- **trigger:** Triage (Routine)\n"
    "- **input link:** inbox/raw/voice/2026-07-08-buy-milk.md\n"
    "- **action type:** file-capture\n"
    "- **action:** Filed under Home.\n"
    "- **confidence:** High\n"
    "- **outcome:** Filed to areas/home/_inbox/\n"
    "- **parent reference:** —\n"
    "- **feedback:** validated\n"
)

ENTRY_UNRELATED_UNSET = (
    "### 07:00 — file-capture\n\n"
    "- **entry id:** 11223344\n"
    "- **actor:** EA\n"
    "- **trigger:** Triage (Routine)\n"
    "- **input link:** inbox/raw/voice/2026-07-08-call-dentist.md\n"
    "- **action type:** file-capture\n"
    "- **action:** Filed under Health.\n"
    "- **confidence:** High\n"
    "- **outcome:** Filed to areas/health/_inbox/\n"
    "- **parent reference:** —\n"
    "- **feedback:** —\n"
)


class TestParseLogEntries(unittest.TestCase):
    def test_parses_fields_from_heading_and_bullets(self):
        entries = rule_learning.parse_log_entries(_log_text(ENTRY_SONIA_1), "2026-07-08")
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["time"], "14:32")
        self.assertEqual(e["action_type"], "file-email")
        self.assertEqual(e["actor"], "EA")
        self.assertEqual(e["feedback"], "corrected — should have gone to Work, this is a SONIA curve email")

    def test_multiple_entries_in_one_file(self):
        entries = rule_learning.parse_log_entries(
            _log_text(ENTRY_SONIA_1 + "\n" + ENTRY_UNRELATED_VALIDATED), "2026-07-08"
        )
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]["feedback"], "validated")

    def test_empty_text_returns_no_entries(self):
        self.assertEqual(rule_learning.parse_log_entries("", "2026-07-08"), [])


class TestFindCorrections(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "log").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_log(self, date_str, entries):
        (self.brain_path / "log" / f"{date_str}.md").write_text(_log_text(entries))

    def test_finds_only_corrected_entries_across_files(self):
        self._write_log("2026-07-08", ENTRY_SONIA_1 + "\n" + ENTRY_UNRELATED_VALIDATED)
        self._write_log("2026-07-12", ENTRY_SONIA_2 + "\n" + ENTRY_UNRELATED_UNSET)

        corrections = rule_learning.find_corrections(self.brain_path)

        self.assertEqual(len(corrections), 2)
        self.assertEqual(corrections[0]["date"], "2026-07-08")
        self.assertEqual(corrections[0]["detail"], "should have gone to Work, this is a SONIA curve email")
        self.assertEqual(corrections[0]["link"], "log/2026-07-08#14:32 — file-email")
        self.assertEqual(corrections[1]["link"], "log/2026-07-12#09:15 — file-email")

    def test_no_log_dir_returns_empty(self):
        empty_brain = Path(tempfile.mkdtemp())
        self.assertEqual(rule_learning.find_corrections(empty_brain), [])

    def test_since_filters_out_earlier_dates(self):
        self._write_log("2026-07-08", ENTRY_SONIA_1)
        self._write_log("2026-07-12", ENTRY_SONIA_2)

        corrections = rule_learning.find_corrections(self.brain_path, since=dt.date(2026, 7, 10))

        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["date"], "2026-07-12")

    def test_validated_and_unset_feedback_are_not_corrections(self):
        self._write_log("2026-07-08", ENTRY_UNRELATED_VALIDATED + "\n" + ENTRY_UNRELATED_UNSET)
        self.assertEqual(rule_learning.find_corrections(self.brain_path), [])


class TestProposeGroup(unittest.TestCase):
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
        self.now = dt.datetime(2026, 7, 15, 10, 0)
        self.rule_block = (
            'if: source == "email" and contains("sonia")\n'
            "then: route -> areas/work/_inbox.md\n"
            "confidence: High"
        )
        self.evidence = [
            "log/2026-07-08#14:32 — file-email",
            "log/2026-07-12#09:15 — file-email",
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_diff_matching_ticket_05_format(self):
        result = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Two corrections moved SONIA curve emails from Home to Work.",
            self.evidence, now=self.now,
        )

        self.assertTrue(result["written"])
        batch_path = result["batch_path"]
        self.assertEqual(batch_path, self.brain_path / "inbox" / "rule-diffs" / "2026-07-15-routing-rules.md")
        text = batch_path.read_text()

        # Frontmatter
        self.assertIn("type: rule-diff-batch", text)
        self.assertIn("ruleset: routing-rules", text)
        self.assertIn("date: 2026-07-15", text)
        self.assertIn("status: pending", text)

        # Title + sectioned layout
        self.assertIn("# Rule diffs — routing-rules — 2026-07-15", text)
        self.assertIn("### Diff 1 — sonia-email-to-work", text)
        self.assertIn('if: source == "email" and contains("sonia")', text)

        # Why / Evidence / Decision
        self.assertIn("**Why:** Two corrections moved SONIA curve emails from Home to Work.", text)
        self.assertIn(
            "**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]",
            text,
        )
        self.assertIn("- [ ] Approve", text)
        self.assertIn("- [ ] Reject", text)

        # Parseable by ticket 05's own parser, round-trip.
        import rule_diff_review
        diffs = rule_diff_review.parse_batch(text)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(len(diffs[0]["evidence"]), 2)
        self.assertFalse(diffs[0]["approve_ticked"])
        self.assertFalse(diffs[0]["reject_ticked"])

    def test_evidence_links_both_justifying_entries(self):
        result = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why.", self.evidence, now=self.now,
        )
        text = result["batch_path"].read_text()
        for link in self.evidence:
            self.assertIn(f"[[{link}]]", text)

    def test_single_correction_is_not_a_pattern(self):
        result = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why.", [self.evidence[0]], now=self.now,
        )
        self.assertFalse(result["written"])
        self.assertIn("fewer than 2", result["reason"])
        self.assertFalse((self.brain_path / "inbox" / "rule-diffs").exists())

    def test_logs_correctly_shaped_propose_rule_diff_entry(self):
        rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why.", self.evidence, now=self.now,
        )
        log_text = (self.brain_path / "log" / "2026-07-15.md").read_text()
        self.assertIn("### 10:00 — propose-rule-diff", log_text)
        self.assertIn("- **actor:** EA", log_text)
        self.assertIn("- **trigger:** Rule learning (Routine)", log_text)
        self.assertIn("- **action type:** propose-rule-diff", log_text)
        self.assertIn("Proposed rule diff (sonia-email-to-work) for config/routing-rules.md.", log_text)
        self.assertIn("- **input link:** inbox/rule-diffs/2026-07-15-routing-rules.md", log_text)
        self.assertIn("Diff written to inbox/rule-diffs/2026-07-15-routing-rules.md", log_text)

    def test_rerunning_same_group_does_not_duplicate_in_open_batch(self):
        first = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why.", self.evidence, now=self.now,
        )
        self.assertTrue(first["written"])

        second = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why.", self.evidence, now=self.now,
        )
        self.assertFalse(second["written"])
        self.assertIn("duplicate", second["reason"])

        text = first["batch_path"].read_text()
        self.assertEqual(text.count("### Diff"), 1)
        log_text = (self.brain_path / "log" / "2026-07-15.md").read_text()
        self.assertEqual(log_text.count("propose-rule-diff"), 2)  # heading + field, one entry only

    def test_already_applied_in_target_file_is_a_duplicate(self):
        # Simulate the diff having already been approved: the exact rule
        # block now lives verbatim in the target ruleset file.
        target = self.brain_path / "config" / "routing-rules.md"
        target.write_text(target.read_text() + f"\n```\n{self.rule_block}\n```\n")

        result = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why.", self.evidence, now=self.now,
        )
        self.assertFalse(result["written"])
        self.assertIn("duplicate", result["reason"])

    def test_already_rejected_in_archive_is_a_duplicate(self):
        archive_dir = self.brain_path / "archive" / "rule-diffs"
        archive_dir.mkdir(parents=True)
        archived_text = (
            "---\ntype: rule-diff-batch\nruleset: routing-rules\ndate: 2026-07-01\nstatus: resolved\n---\n\n"
            "# Rule diffs — routing-rules — 2026-07-01\n\n"
            "### Diff 1 — sonia-email-to-work\n\n"
            f"```\n{self.rule_block}\n```\n\n"
            "**Why:** Old proposal.\n\n"
            "**Evidence:** [[log/2026-06-01#08:00 — file-email]], [[log/2026-06-02#08:00 — file-email]]\n\n"
            "- [ ] Approve\n"
            "- [x] (logged) Reject\n"
        )
        (archive_dir / "2026-07-01-routing-rules.md").write_text(archived_text)

        result = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why.", self.evidence, now=self.now,
        )
        self.assertFalse(result["written"])
        self.assertIn("duplicate", result["reason"])
        self.assertFalse((self.brain_path / "inbox" / "rule-diffs").exists())

    def test_second_distinct_group_same_day_appends_as_diff_2(self):
        first = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why one.", self.evidence, now=self.now,
        )
        other_rule_block = (
            'if: source == "email" and contains("unsubscribe")\n'
            "then: route -> discard\n"
            "confidence: Medium"
        )
        other_evidence = [
            "log/2026-07-09#08:00 — file-email",
            "log/2026-07-10#08:05 — file-email",
        ]
        second = rule_learning.propose_group(
            self.brain_path, "routing-rules", "junk-newsletter-discard", other_rule_block,
            "Why two.", other_evidence, now=self.now,
        )

        self.assertTrue(first["written"])
        self.assertTrue(second["written"])
        self.assertEqual(first["batch_path"], second["batch_path"])

        text = second["batch_path"].read_text()
        self.assertIn("### Diff 1 — sonia-email-to-work", text)
        self.assertIn("### Diff 2 — junk-newsletter-discard", text)
        self.assertEqual(text.count("- [ ] Approve"), 2)
        self.assertEqual(text.count("- [ ] Reject"), 2)

        import rule_diff_review
        diffs = rule_diff_review.parse_batch(text)
        self.assertEqual(len(diffs), 2)
        self.assertEqual(diffs[0]["n"], "1")
        self.assertEqual(diffs[1]["n"], "2")

    def test_different_ruleset_same_rule_block_is_not_a_duplicate(self):
        # Simulate a prior rejection recorded against a *different* ruleset —
        # de-dup is ruleset-scoped (rule_diff_review.diff_key()).
        archive_dir = self.brain_path / "archive" / "rule-diffs"
        archive_dir.mkdir(parents=True)
        archived_text = (
            "---\ntype: rule-diff-batch\nruleset: other-rules\ndate: 2026-07-01\nstatus: resolved\n---\n\n"
            "# Rule diffs — other-rules — 2026-07-01\n\n"
            "### Diff 1 — sonia-email-to-work\n\n"
            f"```\n{self.rule_block}\n```\n\n"
            "**Why:** Old proposal.\n\n"
            "**Evidence:** [[log/2026-06-01#08:00 — file-email]], [[log/2026-06-02#08:00 — file-email]]\n\n"
            "- [ ] Approve\n"
            "- [x] (logged) Reject\n"
        )
        (archive_dir / "2026-07-01-other-rules.md").write_text(archived_text)

        result = rule_learning.propose_group(
            self.brain_path, "routing-rules", "sonia-email-to-work", self.rule_block,
            "Why.", self.evidence, now=self.now,
        )
        self.assertTrue(result["written"])


class TestRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routing-rules.md").write_text(
            "---\ntype: config\nconfig: routing-rules\n---\n\n# Routing rules\n\n```\n```\n"
        )
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Rule learning | never |\n"
        )
        self.now = dt.datetime(2026, 7, 15, 10, 0)
        self.rule_block = (
            'if: source == "email" and contains("sonia")\n'
            "then: route -> areas/work/_inbox.md\n"
            "confidence: High"
        )
        self.evidence = [
            "log/2026-07-08#14:32 — file-email",
            "log/2026-07-12#09:15 — file-email",
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_bumps_rule_learning_row_even_with_no_qualifying_groups(self):
        result = rule_learning.run(self.brain_path, "routing-rules", [], now=self.now)
        self.assertEqual(result["written"], [])
        self.assertIn(
            "| Rule learning | 2026-07-15 10:00 |",
            (self.brain_path / "config" / "routine-state.md").read_text(),
        )

    def test_writes_qualifying_group_and_skips_single_correction_group(self):
        groups = [
            {
                "slug": "sonia-email-to-work",
                "rule_block": self.rule_block,
                "why": "Two corrections moved SONIA curve emails from Home to Work.",
                "evidence": self.evidence,
            },
            {
                "slug": "one-off-dentist",
                "rule_block": 'if: source == "voice" and contains("dentist")\nthen: route -> areas/health/_inbox.md\nconfidence: Low',
                "why": "Single correction only.",
                "evidence": [self.evidence[0]],
            },
        ]
        result = rule_learning.run(self.brain_path, "routing-rules", groups, now=self.now)

        self.assertEqual(len(result["written"]), 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["slug"], "one-off-dentist")
        self.assertIn(
            "| Rule learning | 2026-07-15 10:00 |",
            (self.brain_path / "config" / "routine-state.md").read_text(),
        )


class TestIsDuplicateHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_open_batches_returns_empty_set(self):
        self.assertEqual(rule_learning._open_batch_diff_keys(self.brain_path, "routing-rules"), set())

    def test_no_archive_returns_empty_set(self):
        self.assertEqual(rule_learning._rejected_diff_keys(self.brain_path, "routing-rules"), set())

    def test_missing_target_file_is_not_a_duplicate(self):
        self.assertFalse(rule_learning._already_in_target_file(self.brain_path, "routing-rules", "if: x\nthen: y"))


class TestHeartbeatIntegration(unittest.TestCase):
    """Rule learning's manifest row + routine-state.md bump under
    scripts/heartbeat.py's real due-checker (same verification style as
    ticket 06's daily-row check, adapted for this Routine's weekly cadence).
    """

    def test_manifest_row_is_weekly_heartbeat_checkable_and_implemented(self):
        manifest = heartbeat.parse_manifest()
        row = next(r for r in manifest if r["Routine"] == "Rule learning")
        self.assertIn("weekly", row["Cadence"])
        self.assertIn("heartbeat-checkable", row["Cadence"])
        self.assertTrue(row["Phase 2 status"].startswith("implemented"))

    def test_never_run_is_overdue(self):
        manifest = heartbeat.parse_manifest()
        overdue = heartbeat.compute_overdue(manifest, {"Rule learning": "never"})
        self.assertIn("Rule learning", {item["routine"] for item in overdue})

    def test_run_within_the_week_is_not_overdue(self):
        now = dt.datetime(2026, 7, 15, 10, 0)
        manifest = heartbeat.parse_manifest()
        last_run = (now - dt.timedelta(days=3)).strftime(heartbeat.TIMESTAMP_FORMAT)
        overdue = heartbeat.compute_overdue(manifest, {"Rule learning": last_run}, now=now)
        self.assertNotIn("Rule learning", {item["routine"] for item in overdue})

    def test_run_past_a_week_is_overdue(self):
        now = dt.datetime(2026, 7, 15, 10, 0)
        manifest = heartbeat.parse_manifest()
        last_run = (now - dt.timedelta(days=8)).strftime(heartbeat.TIMESTAMP_FORMAT)
        overdue = heartbeat.compute_overdue(manifest, {"Rule learning": last_run}, now=now)
        self.assertIn("Rule learning", {item["routine"] for item in overdue})

    def test_run_bumps_the_real_routine_state_shape(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            brain_path = Path(tmp.name)
            (brain_path / "config").mkdir()
            (brain_path / "config" / "routing-rules.md").write_text(
                "---\ntype: config\nconfig: routing-rules\n---\n\n# Routing rules\n\n```\n```\n"
            )
            (brain_path / "config" / "routine-state.md").write_text(
                "| Routine | Last run |\n|---|---|\n| Rule learning | never |\n"
            )
            now = dt.datetime(2026, 7, 15, 10, 0)

            rule_learning.run(brain_path, "routing-rules", [], now=now)

            state = heartbeat.parse_routine_state(brain_path / "config" / "routine-state.md")
            self.assertEqual(state["Rule learning"], "2026-07-15 10:00")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
