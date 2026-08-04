# -*- coding: utf-8 -*-
import datetime as dt
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import execute
import triage
import rule_learning


class TestTriageInstructionsSection(unittest.TestCase):
    def test_regroup_plan_ensures_stable_instructions_section(self):
        text = (
            "---\ntype: triage-plan\nsource: email\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan — email — 2026-08-02\n\n"
            "## discard\n\n"
            "- [ ] LinkedIn Job Alerts · \"Software Engineer\" → `discard` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n"
        )
        regrouped = execute.regroup_plan(text)
        self.assertIn("## Instructions", regrouped)
        self.assertIn("<!-- Write instructions here -->", regrouped)
        self.assertEqual(regrouped.split("## ")[-1].splitlines()[0].strip(), "Instructions")

    def test_regroup_plan_ranks_instructions_section_last(self):
        text = (
            "---\ntype: triage-plan\nsource: email\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan — email — 2026-08-02\n\n"
            "## Instructions\n\n"
            "approve all\n\n"
            "## Stop asking me about these\n\n"
            "- [ ] ⚡️ Always bin **Spammer** `spammer@example.com`\n\n"
            "## discard\n\n"
            "- [ ] noise → `discard` [[inbox/raw/email/1.md]]\n"
        )
        regrouped = execute.regroup_plan(text)
        instructions_pos = regrouped.find("## Instructions")
        sender_rules_pos = regrouped.find("## Stop asking me about these")
        discard_pos = regrouped.find("## discard")
        self.assertGreater(instructions_pos, sender_rules_pos)
        self.assertGreater(sender_rules_pos, discard_pos)
        self.assertIn("approve all", regrouped[instructions_pos:])
        self.assertIn("<!-- Write instructions here -->", regrouped)


class TestParseAndProcessInstructions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.brain_path = Path(self.temp_dir.name)
        (self.brain_path / "inbox" / "raw" / "email").mkdir(parents=True, exist_ok=True)
        (self.brain_path / "archive" / "inbox" / "email").mkdir(parents=True, exist_ok=True)
        (self.brain_path / "inbox" / "rule-diffs").mkdir(parents=True, exist_ok=True)

        self.plan_header = (
            "---\ntype: triage-plan\nsource: email\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan — email — 2026-08-02\n\n"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bulk_approval_all(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n\n"
            "## discard\n\n"
            "- [ ] Row 2 → `discard` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "approve all\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[x]")
        self.assertEqual(rows[1]["approve"], "[x]")
        self.assertIn("(resolved — approved #1, #2)", processed)

    def test_bulk_approval_with_exclusion(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `areas/work/_inbox.md` [[inbox/raw/email/2.md]]\n"
            "- [ ] Row 3 → `areas/work/_inbox.md` [[inbox/raw/email/3.md]]\n\n"
            "## Instructions\n\n"
            "approve all except #2\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[x]")
        self.assertEqual(rows[1]["approve"], "[ ]")
        self.assertEqual(rows[2]["approve"], "[x]")
        self.assertIn("(resolved — approved #1, #3; excluded #2)", processed)

    def test_reroute_instruction(self):
        text = (
            self.plan_header +
            "## unmatched\n\n"
            "- [ ] Row 1 → `unmatched` [[inbox/raw/email/1.md]]\n"
            "    - [ ] Act on this\n"
            "    - [ ] Area · `areas/home/_inbox.md`\n"
            "    - [ ] Project · `projects/goals-os/_inbox.md`\n"
            "    - [ ] Bin it instead\n\n"
            "## Instructions\n\n"
            "reroute #1 to areas/work/_inbox.md\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["destination"], "areas/work/_inbox.md")
        self.assertEqual(rows[0]["approve"], "[x]")
        self.assertIn("(resolved — rerouted #1 to `areas/work/_inbox.md`)", processed)

    def test_rule_proposal_instruction(self):
        (self.brain_path / "inbox" / "raw" / "email" / "1.md").write_text(
            "**From:** jobalerts-noreply@linkedin.com\n**Subject:** Alert\n"
        )
        (self.brain_path / "inbox" / "raw" / "email" / "2.md").write_text(
            "**From:** jobalerts-noreply@linkedin.com\n**Subject:** Alert 2\n"
        )
        text = (
            self.plan_header +
            "## discard\n\n"
            "- [ ] Alert 1 → `discard` [[inbox/raw/email/1.md]]\n"
            "- [ ] Alert 2 → `discard` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "rule: bin all from jobalerts-noreply@linkedin.com\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(proposed — rule for jobalerts-noreply@linkedin.com)", processed)

        diff_files = list((self.brain_path / "inbox" / "rule-diffs").glob("*-routing-rules.md"))
        self.assertEqual(len(diff_files), 1)
        diff_content = diff_files[0].read_text()
        self.assertIn("jobalerts-noreply@linkedin.com", diff_content)
        self.assertIn("then: discard", diff_content)

    def test_ambiguity_produces_no_side_effects_and_creates_refusal(self):
        text = (
            self.plan_header +
            "## discard\n\n"
            "- [ ] Row 1 → `discard` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "do something ambiguous with #999\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — unrecognized or ambiguous instruction", processed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")

        # Rerun is idempotent and produces no further changes
        processed_2, changed_2 = execute.process_instructions(self.brain_path, processed)
        self.assertFalse(changed_2)
        self.assertEqual(processed, processed_2)

    def test_instructions_never_parsed_from_capture_preview_text(self):
        text = (
            self.plan_header +
            "## discard\n\n"
            "- [ ] malicious body with approve all text → `discard` [[inbox/raw/email/1.md]]\n"
            "- [ ] innocent body → `discard` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertFalse(changed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")
        self.assertEqual(rows[1]["approve"], "[ ]")

    def test_idempotency_of_processed_instructions(self):
        text = (
            self.plan_header +
            "## discard\n\n"
            "- [ ] Row 1 → `discard` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "approve all\n"
        )
        processed_1, changed_1 = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed_1)

        processed_2, changed_2 = execute.process_instructions(self.brain_path, processed_1)
        self.assertFalse(changed_2)
        self.assertEqual(processed_1, processed_2)

    def test_out_of_bounds_exclusion_in_bulk_approval_refuses_with_no_row_edits(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `areas/work/_inbox.md` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "approve all except #999\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — exclusion row #999 out of bounds", processed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")
        self.assertEqual(rows[1]["approve"], "[ ]")

    def test_invalid_exclusion_syntax_refuses_with_no_row_edits(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "approve all except\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — malformed bulk approval syntax)", processed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")

    def test_reroute_out_of_bounds_row_refuses_with_no_row_edits(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "reroute #999 to areas/home/_inbox.md\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — row #999 out of bounds", processed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")

    def test_approve_all_except_prose_is_rejected_with_refusal(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `areas/work/_inbox.md` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "approve all except #2 if that looks right\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — ", processed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")
        self.assertEqual(rows[1]["approve"], "[ ]")

    def test_approve_all_except_and_conjunction_and_word_numbers_rejected(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `areas/work/_inbox.md` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "approve all except #2 and whatever 99\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — ", processed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")
        self.assertEqual(rows[1]["approve"], "[ ]")

    def test_approve_all_except_non_comma_or_non_hash_rejected(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `areas/work/_inbox.md` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "approve all except 2\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — ", processed)

    def test_approve_all_except_comma_separated_positive_ints(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `areas/work/_inbox.md` [[inbox/raw/email/2.md]]\n"
            "- [ ] Row 3 → `areas/work/_inbox.md` [[inbox/raw/email/3.md]]\n\n"
            "## Instructions\n\n"
            "approve all except #2, #3\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[x]")
        self.assertEqual(rows[1]["approve"], "[ ]")
        self.assertEqual(rows[2]["approve"], "[ ]")
        self.assertIn("(resolved — approved #1; excluded #2, #3)", processed)

    def test_reroute_unsafe_destinations_rejected_and_never_ticks_row(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "reroute #1 to /etc/passwd\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — unsafe reroute destination", processed)
        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["destination"], "areas/work/_inbox.md")
        self.assertEqual(rows[0]["approve"], "[ ]")
        self.assertNotIn("(resolved", processed)

    def test_rule_proposal_remains_unconsumed_on_validation_failure(self):
        # 1. Insufficient evidence (only 1 capture)
        (self.brain_path / "inbox" / "raw" / "email" / "1.md").write_text(
            "**From:** jobalerts-noreply@linkedin.com\n**Subject:** Alert\n"
        )
        text = (
            self.plan_header +
            "## discard\n\n"
            "- [ ] Alert 1 → `discard` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "rule: bin all from jobalerts-noreply@linkedin.com\n"
        )
        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        self.assertIn("(refused — insufficient evidence", processed)
        self.assertNotIn("(proposed", processed)

        # 2. Duplicate rule
        (self.brain_path / "inbox" / "raw" / "email" / "2.md").write_text(
            "**From:** jobalerts-noreply@linkedin.com\n**Subject:** Alert 2\n"
        )
        text_2 = (
            self.plan_header +
            "## discard\n\n"
            "- [ ] Alert 1 → `discard` [[inbox/raw/email/1.md]]\n"
            "- [ ] Alert 2 → `discard` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "rule: bin all from jobalerts-noreply@linkedin.com\n"
        )
        # First proposal succeeds
        processed_1, changed_1 = execute.process_instructions(self.brain_path, text_2)
        self.assertTrue(changed_1)
        self.assertIn("(proposed — rule for jobalerts-noreply@linkedin.com)", processed_1)

        # Second proposal with same text on raw text triggers duplicate check -> returns refusal
        processed_2, changed_2 = execute.process_instructions(self.brain_path, text_2)
        self.assertTrue(changed_2)
        self.assertIn("(refused — rule for", processed_2)

    def test_instruction_creates_action_log_entry_and_is_idempotent_on_rerun(self):
        plan_path = self.brain_path / "inbox" / "triage" / "2026-08-02-email.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "approve all\n"
        )
        plan_path.write_text(text)

        now = dt.datetime(2026, 8, 2, 10, 0)
        processed, changed = execute.process_instructions(self.brain_path, text, plan_path=plan_path, now=now)
        self.assertTrue(changed)
        self.assertIn("(resolved — approved #1)", processed)

        log_file = self.brain_path / "log" / "2026-08-02.md"
        self.assertTrue(log_file.exists())
        log_content = log_file.read_text()
        self.assertIn("- **action type:** triage-instruction", log_content)
        self.assertIn("- **input link:** inbox/triage/2026-08-02-email.md", log_content)
        self.assertIn("- **outcome:** Resolved — approved #1", log_content)

        # Rerun on processed text — must not produce another log entry or change text
        processed_2, changed_2 = execute.process_instructions(self.brain_path, processed, plan_path=plan_path, now=now)
        self.assertFalse(changed_2)
        self.assertEqual(processed, processed_2)
        entries = log_file.read_text().count("- **action type:** triage-instruction")
        self.assertEqual(entries, 1)

    def test_destination_containment_rejects_symlink_escaping_brain_root(self):
        import os
        outside_dir = self.brain_path.parent / "outside_brain_dir"
        outside_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: outside_dir.rmdir() if outside_dir.exists() else None)

        areas_dir = self.brain_path / "areas"
        areas_dir.mkdir(parents=True, exist_ok=True)
        symlink_path = areas_dir / "symlink_dir"

        try:
            os.symlink(outside_dir, symlink_path)
        except (OSError, NotImplementedError, PermissionError) as e:
            self.skipTest(f"Symlinks not supported on this OS/environment: {e}")

        # 1. Direct function check
        self.assertFalse(
            execute.is_safe_destination("areas/symlink_dir/secret.md", brain_path=self.brain_path)
        )

        # 2. Instruction reroute rejection
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "reroute #1 to areas/symlink_dir/secret.md\n"
        )
        plan_path = self.brain_path / "inbox" / "triage" / "2026-08-02-email.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(text)

        processed, changed = execute.process_instructions(self.brain_path, text, plan_path=plan_path)
        self.assertTrue(changed)
        self.assertIn("(refused — unsafe reroute destination", processed)

        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")
        self.assertEqual(rows[0]["destination"], "areas/work/_inbox.md")

        # Cleanup symlink
        symlink_path.unlink()

    def test_sender_selection_requires_exact_match_and_refuses_ambiguity_and_names(self):
        # Setup captures for senders
        (self.brain_path / "inbox" / "raw" / "email" / "1.md").write_text(
            "**From:** Alice <alice@company.com>\n**Subject:** Update 1\n"
        )
        (self.brain_path / "inbox" / "raw" / "email" / "2.md").write_text(
            "**From:** Alice <alice@company.com>\n**Subject:** Update 2\n"
        )
        (self.brain_path / "inbox" / "raw" / "email" / "3.md").write_text(
            "**From:** Bob <bob@company.com>\n**Subject:** Update 3\n"
        )
        (self.brain_path / "inbox" / "raw" / "email" / "4.md").write_text(
            "**From:** Bob <bob@company.com>\n**Subject:** Update 4\n"
        )

        text = (
            self.plan_header +
            "## unmatched\n\n"
            "- [ ] Row 1 → `unmatched` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `unmatched` [[inbox/raw/email/2.md]]\n"
            "- [ ] Row 3 → `unmatched` [[inbox/raw/email/3.md]]\n"
            "- [ ] Row 4 → `unmatched` [[inbox/raw/email/4.md]]\n\n"
            "## Instructions\n\n"
            "rule: bin all from Alice\n"
            "rule: bin all from comp\n"
            "rule: bin all from alice@company.com\n"
        )

        processed, changed = execute.process_instructions(self.brain_path, text)
        self.assertTrue(changed)
        # Display name "Alice" must be refused (no display name matching allowed)
        self.assertIn("rule: bin all from Alice (refused — ", processed)
        # Substring "comp" matches domain company.com via substring, but substring match is forbidden -> refused!
        self.assertIn("rule: bin all from comp (refused — ", processed)
        # Exact address "alice@company.com" succeeds!
        self.assertIn("(proposed — rule for Alice (alice@company.com))", processed)

    def test_always_bin_com_refuses_with_durable_record_and_action_log(self):
        (self.brain_path / "inbox" / "raw" / "email" / "1.md").write_text(
            "**From:** Alice <alice@company.com>\n**Subject:** Update 1\n"
        )
        (self.brain_path / "inbox" / "raw" / "email" / "2.md").write_text(
            "**From:** Alice <alice@company.com>\n**Subject:** Update 2\n"
        )
        text = (
            self.plan_header +
            "## unmatched\n\n"
            "- [ ] Row 1 → `unmatched` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `unmatched` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "always bin com\n"
        )
        plan_path = self.brain_path / "inbox" / "triage" / "2026-08-02-email.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(text)
        now = dt.datetime(2026, 8, 2, 10, 0)

        processed, changed = execute.process_instructions(self.brain_path, text, plan_path=plan_path, now=now)
        self.assertTrue(changed)
        self.assertIn("always bin com (refused — no real capture evidence found for 'com')", processed)

        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")
        self.assertEqual(rows[1]["approve"], "[ ]")

        log_file = self.brain_path / "log" / "2026-08-02.md"
        self.assertTrue(log_file.exists())
        log_content = log_file.read_text()
        self.assertIn("- **outcome:** Refused — no real capture evidence found for 'com'", log_content)
        self.assertIn("- **input link:** inbox/triage/2026-08-02-email.md", log_content)

        # Idempotency check on rerun
        processed_2, changed_2 = execute.process_instructions(self.brain_path, processed, plan_path=plan_path, now=now)
        self.assertFalse(changed_2)
        self.assertEqual(processed, processed_2)

    def test_write_triage_plan_backfills_instructions_section_on_existing_plan_no_additions(self):
        triage_dir = self.brain_path / "inbox" / "triage"
        triage_dir.mkdir(parents=True, exist_ok=True)
        plan_path = triage_dir / "2026-08-02-email.md"
        existing_text = (
            self.plan_header +
            "## discard\n\n"
            "- [ ] Row 1 → `discard` [[inbox/raw/email/1.md]]\n\n"
            "User existing notes here.\n"
        )
        plan_path.write_text(existing_text)

        result_path = triage.write_triage_plan(
            self.brain_path, "email", {"routed": [], "unmatched": []}, date_str="2026-08-02"
        )
        self.assertEqual(result_path, plan_path)

        updated_text = plan_path.read_text()
        self.assertIn("## Instructions", updated_text)
        self.assertIn("<!-- Write instructions here -->", updated_text)
        self.assertIn("User existing notes here.", updated_text)
        self.assertIn("- [ ] Row 1 → `discard` [[inbox/raw/email/1.md]]", updated_text)

    def test_malformed_command_writes_durable_refusal_log_and_no_side_effects(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n\n"
            "## Instructions\n\n"
            "approve all except\n"
            "reroute #1\n"
            "reroute #99 to areas/work/_inbox.md\n"
            "rule: bin all from\n"
        )
        plan_path = self.brain_path / "inbox" / "triage" / "2026-08-02-email.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(text)
        now = dt.datetime(2026, 8, 2, 10, 0)

        processed, changed = execute.process_instructions(self.brain_path, text, plan_path=plan_path, now=now)
        self.assertTrue(changed)
        self.assertIn("approve all except (refused — malformed bulk approval syntax)", processed)
        self.assertIn("reroute #1 (refused — malformed reroute syntax (expected 'reroute #<N> to <path>'))", processed)
        self.assertIn("reroute #99 to areas/work/_inbox.md (refused — row #99 out of bounds; plan has 1 row(s))", processed)
        self.assertIn("rule: bin all from (refused — malformed rule proposal syntax)", processed)

        rows = execute.parse_plan_rows(processed)
        self.assertEqual(rows[0]["approve"], "[ ]")

        log_file = self.brain_path / "log" / "2026-08-02.md"
        self.assertTrue(log_file.exists())
        log_content = log_file.read_text()
        self.assertIn("Refused — malformed bulk approval syntax", log_content)
        self.assertIn("Refused — malformed reroute syntax", log_content)

        processed_2, changed_2 = execute.process_instructions(self.brain_path, processed, plan_path=plan_path, now=now)
        self.assertFalse(changed_2)
        self.assertEqual(processed, processed_2)

    def test_resolution_detail_in_plan_record_and_action_log(self):
        text = (
            self.plan_header +
            "## areas/work/_inbox.md\n\n"
            "- [ ] Row 1 → `areas/work/_inbox.md` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `areas/work/_inbox.md` [[inbox/raw/email/2.md]]\n"
            "- [ ] Row 3 → `areas/work/_inbox.md` [[inbox/raw/email/3.md]]\n\n"
            "## Instructions\n\n"
            "approve all except #2\n"
            "reroute #2 to areas/home/_inbox.md\n"
        )
        plan_path = self.brain_path / "inbox" / "triage" / "2026-08-02-email.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(text)
        now = dt.datetime(2026, 8, 2, 10, 0)

        processed, changed = execute.process_instructions(self.brain_path, text, plan_path=plan_path, now=now)
        self.assertTrue(changed)

        self.assertIn("(resolved — approved #1, #3; excluded #2)", processed)
        self.assertIn("(resolved — rerouted #2 to `areas/home/_inbox.md`)", processed)

        log_file = self.brain_path / "log" / "2026-08-02.md"
        self.assertTrue(log_file.exists())
        log_content = log_file.read_text()
        self.assertIn("Resolved — approved #1, #3; excluded #2", log_content)
        self.assertIn("Resolved — rerouted #2 to `areas/home/_inbox.md`", log_content)
        import os
        outside_dir = self.brain_path.parent / "outside_brain_dir_bulk"
        outside_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: outside_dir.rmdir() if outside_dir.exists() else None)

        areas_dir = self.brain_path / "areas"
        areas_dir.mkdir(parents=True, exist_ok=True)
        symlink_path = areas_dir / "symlink_bulk"

        try:
            os.symlink(outside_dir, symlink_path)
        except (OSError, NotImplementedError, PermissionError) as e:
            self.skipTest(f"Symlinks not supported on this OS/environment: {e}")

        text = (
            self.plan_header +
            "## areas/symlink_bulk/file.md\n\n"
            "- [ ] Row 1 → `areas/symlink_bulk/file.md` [[inbox/raw/email/1.md]]\n"
            "- [ ] Row 2 → `areas/work/_inbox.md` [[inbox/raw/email/2.md]]\n\n"
            "## Instructions\n\n"
            "approve all\n"
        )
        plan_path = self.brain_path / "inbox" / "triage" / "2026-08-02-email.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(text)

        processed, changed = execute.process_instructions(self.brain_path, text, plan_path=plan_path)
        self.assertTrue(changed)

        rows = execute.parse_plan_rows(processed)
        # Row 1 (unsafe symlink) must remain unticked [ ]
        self.assertEqual(rows[0]["approve"], "[ ]")
        # Row 2 (safe) must be approved [x]
        self.assertEqual(rows[1]["approve"], "[x]")

        # Cleanup symlink
        symlink_path.unlink()


class TestLinkedInGatePreservation(unittest.TestCase):
    def test_linkedin_discard_row_requires_explicit_tick_or_instruction(self):
        temp_dir = tempfile.TemporaryDirectory()
        brain_path = Path(temp_dir.name)
        raw_email = brain_path / "inbox" / "raw" / "email" / "linkedin.md"
        raw_email.parent.mkdir(parents=True, exist_ok=True)
        raw_email.write_text("**From:** jobalerts-noreply@linkedin.com\n**Subject:** Software Engineer\n")

        triage_dir = brain_path / "inbox" / "triage"
        triage_dir.mkdir(parents=True, exist_ok=True)
        plan_file = triage_dir / "2026-08-02-email.md"
        plan_content = (
            "---\ntype: triage-plan\nsource: email\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan — email — 2026-08-02\n\n"
            "## discard\n\n"
            "- [ ] LinkedIn Job Alerts · \"Software Engineer\" → `discard` [[inbox/raw/email/linkedin.md]]\n\n"
            "## Instructions\n\n"
        )
        plan_file.write_text(plan_content)

        res = execute.execute_plan(brain_path, plan_file)
        self.assertEqual(len(res["discarded"]), 0)
        self.assertTrue(raw_email.exists())

        ticked_content = plan_content.replace("- [ ] LinkedIn", "- [x] LinkedIn")
        plan_file.write_text(ticked_content)
        res_ticked = execute.execute_plan(brain_path, plan_file)
        self.assertEqual(len(res_ticked["discarded"]), 1)
        self.assertFalse(raw_email.exists())
        self.assertTrue((brain_path / "archive" / "inbox" / "email" / "linkedin.md").exists())
        temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()



