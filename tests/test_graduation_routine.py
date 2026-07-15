import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import graduation  # noqa: E402
import graduation_routine as gr  # noqa: E402
import heartbeat  # noqa: E402

NOW = dt.datetime(2026, 7, 15, 12, 0)  # "today", for every test that needs a fixed clock


# --------------------------------------------------------------------------
# Fixture-builder helpers — hand-written Brain directories, no real-Vault
# dependency, mirroring tests/test_heartbeat.py's and test_graduation.py's
# tempdir pattern.
# --------------------------------------------------------------------------

def _action_types_md(rows):
    lines = ["| Action type | Risk tier | Autonomy level | Notes |", "|---|---|---|---|"]
    for action_type, risk_tier, autonomy, notes in rows:
        lines.append(f"| {action_type} | {risk_tier} | {autonomy} | {notes} |")
    return "\n".join(lines) + "\n"


def _autonomy_policy_md(window_days=1, min_qualifying=5, min_sessions=3, debt_max=20):
    return (
        "| Setting | Default | Meaning |\n"
        "|---|---|---|\n"
        f"| review-window-days | {window_days} | ... |\n"
        f"| graduation-min-qualifying | {min_qualifying} | ... |\n"
        f"| graduation-min-sessions | {min_sessions} | ... |\n"
        f"| review-debt-max | {debt_max} | ... |\n"
    )


def _routine_state_md(rows):
    lines = ["| Routine | Last run |", "|---|---|"]
    for routine, last_run in rows:
        lines.append(f"| {routine} | {last_run} |")
    return "\n".join(lines) + "\n"


def _entry(time, action_type, entry_id="e1", feedback="—", outcome="Done",
           actor="claude-session-01-01-2026", include_feedback=True):
    text = (
        f"### {time} — {action_type}\n\n"
        f"- **entry id:** {entry_id}\n"
        f"- **actor:** {actor}\n"
        f"- **trigger:** Direct instruction\n"
        f"- **input link:** —\n"
        f"- **action type:** {action_type}\n"
        f"- **action:** did the thing\n"
        f"- **confidence:** High\n"
        f"- **outcome:** {outcome}\n"
        f"- **parent reference:** —\n"
    )
    if include_feedback:
        text += f"- **feedback:** {feedback}\n\n"
    else:
        text += "\n"
    return text


class BrainFixture:
    """A tempdir Brain with config/action-types.md, config/autonomy-policy.md,
    config/routine-state.md, and log/YYYY-MM-DD.md files, built up by
    successive `.log()` calls."""

    def __init__(self, action_type_rows, routine_state_rows=None, **policy_overrides):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        (self.path / "config").mkdir()
        (self.path / "log").mkdir()
        (self.path / "config" / "action-types.md").write_text(_action_types_md(action_type_rows))
        (self.path / "config" / "autonomy-policy.md").write_text(_autonomy_policy_md(**policy_overrides))
        routine_state_rows = routine_state_rows if routine_state_rows is not None else [("Graduation check", "never")]
        (self.path / "config" / "routine-state.md").write_text(_routine_state_md(routine_state_rows))

    def log(self, date_str, *entry_texts):
        log_path = self.path / "log" / f"{date_str}.md"
        existing = log_path.read_text() if log_path.exists() else ""
        log_path.write_text(existing + "".join(entry_texts))
        return self

    def action_types_text(self):
        return (self.path / "config" / "action-types.md").read_text()

    def routine_state_text(self):
        return (self.path / "config" / "routine-state.md").read_text()

    def log_text(self, date_str):
        return (self.path / "log" / f"{date_str}.md").read_text()

    def log_files(self):
        return list((self.path / "log").glob("*.md"))

    def cleanup(self):
        self._tmp.cleanup()


class RoutineTestCase(unittest.TestCase):
    def setUp(self):
        self._fixtures = []

    def tearDown(self):
        for fixture in self._fixtures:
            fixture.cleanup()

    def brain(self, action_type_rows, routine_state_rows=None, **policy_overrides):
        fixture = BrainFixture(action_type_rows, routine_state_rows, **policy_overrides)
        self._fixtures.append(fixture)
        return fixture


# --------------------------------------------------------------------------
# write_feedback_classification — Pass (i)'s mechanical write-back
# --------------------------------------------------------------------------

class TestWriteFeedbackClassification(RoutineTestCase):
    def test_overwrites_feedback_line_in_place(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", entry_id="x1", feedback="yep good"))
        log_path = b.path / "log" / "2026-07-10.md"

        ok = gr.write_feedback_classification(log_path, "x1", "validated")

        self.assertTrue(ok)
        text = log_path.read_text()
        self.assertIn("- **feedback:** validated", text)
        self.assertNotIn("yep good", text)

    def test_only_touches_the_named_entry(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log(
            "2026-07-10",
            _entry("09:00", "file-capture", entry_id="x1", feedback="yep good"),
            _entry("10:00", "file-capture", entry_id="x2", feedback="—"),
        )
        log_path = b.path / "log" / "2026-07-10.md"

        gr.write_feedback_classification(log_path, "x1", "validated")

        entries = graduation.parse_log_entries(log_path.read_text())
        by_id = {e["fields"]["entry id"]: e["fields"]["feedback"] for e in entries}
        self.assertEqual(by_id["x1"], "validated")
        self.assertEqual(by_id["x2"], "—")

    def test_creates_no_new_action_log_entries(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", entry_id="x1", feedback="yep good"))
        log_path = b.path / "log" / "2026-07-10.md"
        before = len(graduation.parse_log_entries(log_path.read_text()))

        gr.write_feedback_classification(log_path, "x1", "validated")

        after = len(graduation.parse_log_entries(log_path.read_text()))
        self.assertEqual(before, after)

    def test_writes_correction_payload_verbatim(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", entry_id="x1", feedback="nah wrong area"))
        log_path = b.path / "log" / "2026-07-10.md"

        gr.write_feedback_classification(log_path, "x1", "corrected — should have filed under Kids")

        entries = graduation.parse_log_entries(log_path.read_text())
        self.assertEqual(entries[0]["fields"]["feedback"], "corrected — should have filed under Kids")

    def test_appends_feedback_field_when_entirely_missing(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", entry_id="m1", include_feedback=False))
        log_path = b.path / "log" / "2026-07-10.md"

        ok = gr.write_feedback_classification(log_path, "m1", "—")

        self.assertTrue(ok)
        entries = graduation.parse_log_entries(log_path.read_text())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["fields"]["feedback"], "—")

    def test_unknown_entry_id_is_a_noop(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", entry_id="x1", feedback="yep good"))
        log_path = b.path / "log" / "2026-07-10.md"

        ok = gr.write_feedback_classification(log_path, "does-not-exist", "validated")

        self.assertFalse(ok)
        self.assertIn("yep good", log_path.read_text())

    def test_missing_file_is_a_noop_not_a_crash(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            missing = Path(tmp.name) / "does-not-exist.md"
            ok = gr.write_feedback_classification(missing, "x1", "validated")
            self.assertFalse(ok)
        finally:
            tmp.cleanup()


# --------------------------------------------------------------------------
# update_action_type_autonomy — Pass (ii)'s config/action-types.md write
# --------------------------------------------------------------------------

class TestUpdateActionTypeAutonomy(RoutineTestCase):
    def test_flips_only_the_named_row(self):
        b = self.brain([
            ("file-capture", "internal & reversible", "confirm-first", "-"),
            ("project-update", "internal & reversible", "confirm-first", "-"),
        ])
        path = b.path / "config" / "action-types.md"

        ok = gr.update_action_type_autonomy(path, "file-capture", "autonomous")

        self.assertTrue(ok)
        rows = graduation.parse_action_types(b.path)
        by_type = {r["Action type"]: r["Autonomy level"] for r in rows}
        self.assertEqual(by_type["file-capture"], "autonomous")
        self.assertEqual(by_type["project-update"], "confirm-first")

    def test_unknown_action_type_is_a_noop(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        path = b.path / "config" / "action-types.md"

        ok = gr.update_action_type_autonomy(path, "does-not-exist", "autonomous")

        self.assertFalse(ok)

    def test_missing_file_is_a_noop_not_a_crash(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            missing = Path(tmp.name) / "does-not-exist.md"
            ok = gr.update_action_type_autonomy(missing, "file-capture", "autonomous")
            self.assertFalse(ok)
        finally:
            tmp.cleanup()


# --------------------------------------------------------------------------
# apply_graduation_changes — write side effects for a decision dict
# --------------------------------------------------------------------------

class TestApplyGraduationChanges(RoutineTestCase):
    def test_graduate_decision_flips_config_and_logs_correctly_shaped_entry(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        state = {
            "file-capture": {
                "decision": "graduate",
                "reason": "5 qualifying instances across 3 distinct days (threshold 5/3)",
            }
        }

        changes = gr.apply_graduation_changes(b.path, state, now=NOW)

        self.assertEqual(len(changes), 1)
        rows = graduation.parse_action_types(b.path)
        self.assertEqual(rows[0]["Autonomy level"], "autonomous")

        entries = graduation.parse_log_entries(b.log_text("2026-07-15"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["heading_action_type"], "graduate-action-type")
        outcome = entries[0]["fields"]["outcome"]
        m = graduation._BOUNDARY_OUTCOME_RE.search(outcome)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "file-capture")
        self.assertEqual(m.group(2), "autonomous")

    def test_demote_decision_flips_config_and_logs_correctly_shaped_entry(self):
        b = self.brain([("file-capture", "internal & reversible", "autonomous", "-")])
        state = {"file-capture": {"decision": "demote", "reason": "corrected feedback on entry a1"}}

        changes = gr.apply_graduation_changes(b.path, state, now=NOW)

        self.assertEqual(len(changes), 1)
        rows = graduation.parse_action_types(b.path)
        self.assertEqual(rows[0]["Autonomy level"], "confirm-first")

        entries = graduation.parse_log_entries(b.log_text("2026-07-15"))
        self.assertEqual(entries[0]["heading_action_type"], "demote-action-type")
        outcome = entries[0]["fields"]["outcome"]
        m = graduation._BOUNDARY_OUTCOME_RE.search(outcome)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "file-capture")
        self.assertEqual(m.group(2), "confirm-first")

    def test_none_decision_writes_nothing(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        state = {"file-capture": {"decision": "none", "reason": "need threshold 5/3"}}

        changes = gr.apply_graduation_changes(b.path, state, now=NOW)

        self.assertEqual(changes, [])
        self.assertEqual(b.log_files(), [])

    def test_no_writes_when_config_row_is_absent(self):
        b = self.brain([("project-update", "internal & reversible", "confirm-first", "-")])
        state = {"file-capture": {"decision": "graduate", "reason": "..."}}

        changes = gr.apply_graduation_changes(b.path, state, now=NOW)

        self.assertEqual(changes, [])
        self.assertEqual(b.log_files(), [])

    def test_belt_and_suspenders_never_writes_excluded_types_even_if_present_in_state(self):
        # Simulates a hypothetical bug in graduation.py's own
        # FIXED_AUTONOMOUS exclusion: these three types are hand-fed
        # into `state` directly, bypassing compute_graduation_state()
        # entirely, to prove this second, independent check refuses to
        # act on them regardless of what the decision engine says.
        b = self.brain([
            ("graduate-action-type", "internal & reversible", "autonomous (fixed)", "-"),
            ("demote-action-type", "internal & reversible", "autonomous (fixed)", "-"),
            ("propose-rule-diff", "internal & reversible", "autonomous (fixed)", "-"),
        ])
        state = {
            "graduate-action-type": {"decision": "demote", "reason": "should never happen"},
            "demote-action-type": {"decision": "demote", "reason": "should never happen"},
            "propose-rule-diff": {"decision": "graduate", "reason": "should never happen"},
        }

        changes = gr.apply_graduation_changes(b.path, state, now=NOW)

        self.assertEqual(changes, [])
        text_after = b.action_types_text()
        self.assertEqual(text_after.count("autonomous (fixed)"), 3)
        self.assertNotIn("| confirm-first |", text_after)
        self.assertEqual(b.log_files(), [])

    def test_belt_and_suspenders_is_targeted_not_global(self):
        # A normal type alongside the excluded ones still gets acted on —
        # proves the exclusion is scoped to the three named types, not a
        # global "state is fishy, do nothing" bail-out.
        b = self.brain([
            ("graduate-action-type", "internal & reversible", "autonomous (fixed)", "-"),
            ("file-capture", "internal & reversible", "confirm-first", "-"),
        ])
        state = {
            "graduate-action-type": {"decision": "demote", "reason": "should never happen"},
            "file-capture": {"decision": "graduate", "reason": "5/3"},
        }

        changes = gr.apply_graduation_changes(b.path, state, now=NOW)

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["action_type"], "file-capture")
        rows = {r["Action type"]: r["Autonomy level"] for r in graduation.parse_action_types(b.path)}
        self.assertEqual(rows["graduate-action-type"], "autonomous (fixed)")
        self.assertEqual(rows["file-capture"], "autonomous")


# --------------------------------------------------------------------------
# run_counting_pass — Pass (ii) end to end, including the routine-state bump
# --------------------------------------------------------------------------

class TestRunCountingPass(RoutineTestCase):
    def test_noop_writes_nothing_but_bumps_routine_state(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        before_config = b.action_types_text()

        result = gr.run_counting_pass(b.path, now=NOW)

        self.assertEqual(result["changes"], [])
        self.assertEqual(b.action_types_text(), before_config)
        self.assertEqual(b.log_files(), [])
        self.assertIn("| Graduation check | 2026-07-15 12:00 |", b.routine_state_text())

    def test_graduating_type_flips_config_logs_and_bumps_routine_state(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-01", _entry("09:00", "file-capture", entry_id="a1", feedback="validated"))
        b.log("2026-07-02", _entry("09:00", "file-capture", entry_id="a2", feedback="validated"))
        b.log("2026-07-03", _entry("09:00", "file-capture", entry_id="a3", feedback="validated"))
        b.log("2026-07-04", _entry("09:00", "file-capture", entry_id="a4", feedback="validated"))
        b.log("2026-07-05", _entry("09:00", "file-capture", entry_id="a5", feedback="validated"))

        result = gr.run_counting_pass(b.path, now=NOW)

        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["action_type"], "file-capture")
        rows = graduation.parse_action_types(b.path)
        self.assertEqual(rows[0]["Autonomy level"], "autonomous")
        self.assertIn("| Graduation check | 2026-07-15 12:00 |", b.routine_state_text())

    def test_demoting_type_flips_config_and_logs(self):
        b = self.brain([("file-capture", "internal & reversible", "autonomous", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", entry_id="a1", feedback="corrected — wrong area"))

        result = gr.run_counting_pass(b.path, now=NOW)

        self.assertEqual(len(result["changes"]), 1)
        rows = graduation.parse_action_types(b.path)
        self.assertEqual(rows[0]["Autonomy level"], "confirm-first")

    def test_bumps_regardless_even_when_routine_state_row_is_absent(self):
        # heartbeat.bump()/update_last_run() silently no-ops if the row
        # doesn't exist (e.g. Brain not yet onboarded with ticket 01's
        # scaffolding) — the Routine still ran and returned a result,
        # just nothing was recorded, mirroring that documented precedent.
        b = self.brain(
            [("file-capture", "internal & reversible", "confirm-first", "-")],
            routine_state_rows=[("Triage", "never")],
        )

        result = gr.run_counting_pass(b.path, now=NOW)

        self.assertEqual(result["changes"], [])
        self.assertIn("Triage", b.routine_state_text())
        self.assertNotIn("Graduation check", b.routine_state_text())


# --------------------------------------------------------------------------
# Heartbeat integration — acceptance criterion 5
# --------------------------------------------------------------------------

class TestHeartbeatIntegration(unittest.TestCase):
    def test_flags_graduation_check_overdue_then_stops_after_bump(self):
        manifest = [{
            "Routine": "Graduation check",
            "Cadence": "daily — heartbeat-checkable",
            "Phase 2 status": "implemented (execution batch)",
        }]
        now = dt.datetime(2026, 7, 15, 9, 0)

        overdue = heartbeat.compute_overdue(manifest, {"Graduation check": "never"}, now=now)
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["routine"], "Graduation check")

        tmp = tempfile.TemporaryDirectory()
        try:
            brain_path = Path(tmp.name)
            (brain_path / "config").mkdir()
            (brain_path / "config" / "routine-state.md").write_text(
                "| Routine | Last run |\n|---|---|\n| Graduation check | never |\n"
            )
            heartbeat.bump(brain_path, "Graduation check", now)
            routine_state = heartbeat.parse_routine_state(brain_path / "config" / "routine-state.md")

            overdue_after = heartbeat.compute_overdue(manifest, routine_state, now=now)
            self.assertEqual(overdue_after, [])
        finally:
            tmp.cleanup()

    def test_real_manifest_includes_graduation_check_row_before_triage(self):
        manifest = heartbeat.parse_manifest()
        row = next((r for r in manifest if r.get("Routine") == "Graduation check"), None)
        self.assertIsNotNone(row, "protocols/routines.md is missing its 'Graduation check' row")
        self.assertIn("daily", row["Cadence"])
        self.assertIn("heartbeat-checkable", row["Cadence"])
        self.assertTrue(row["Phase 2 status"].startswith("implemented"))

        names = [r["Routine"] for r in manifest]
        self.assertLess(
            names.index("Graduation check"), names.index("Triage"),
            "Graduation check must run before Triage in session-start sequencing",
        )


if __name__ == "__main__":
    unittest.main()
