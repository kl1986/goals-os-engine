import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import graduation  # noqa: E402

NOW = dt.datetime(2026, 7, 15, 12, 0)  # "today", for every test that needs a fixed clock


# --------------------------------------------------------------------------
# Fixture-builder helpers — hand-written Brain directories, no real-Vault
# dependency, mirroring tests/test_heartbeat.py's tempdir pattern.
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


def _entry(time, action_type, entry_id="e1", feedback="—", outcome="Done", actor="claude-session-01-01-2026"):
    return (
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
        f"- **feedback:** {feedback}\n\n"
    )


def _boundary_entry(time, target_type, direction, entry_id="b1"):
    outcome = f"`{target_type}` → {direction} (test boundary)"
    heading_type = "graduate-action-type" if direction == "autonomous" else "demote-action-type"
    return _entry(time, heading_type, entry_id=entry_id, feedback="—", outcome=outcome)


class BrainFixture:
    """A tempdir Brain with config/action-types.md, config/autonomy-policy.md,
    and log/YYYY-MM-DD.md files, built up by successive `.log()` calls."""

    def __init__(self, action_type_rows, **policy_overrides):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        (self.path / "config").mkdir()
        (self.path / "log").mkdir()
        (self.path / "config" / "action-types.md").write_text(_action_types_md(action_type_rows))
        (self.path / "config" / "autonomy-policy.md").write_text(_autonomy_policy_md(**policy_overrides))

    def log(self, date_str, *entry_texts):
        """Append entry_texts to log/{date_str}.md, creating it if needed."""
        log_path = self.path / "log" / f"{date_str}.md"
        existing = log_path.read_text() if log_path.exists() else ""
        log_path.write_text(existing + "".join(entry_texts))
        return self

    def cleanup(self):
        self._tmp.cleanup()


class GraduationTestCase(unittest.TestCase):
    """Base class: tracks fixtures created via self.brain(...) and cleans them up."""

    def setUp(self):
        self._fixtures = []

    def tearDown(self):
        for fixture in self._fixtures:
            fixture.cleanup()

    def brain(self, action_type_rows, **policy_overrides):
        fixture = BrainFixture(action_type_rows, **policy_overrides)
        self._fixtures.append(fixture)
        return fixture


# --------------------------------------------------------------------------
# parse_log_entries / config parsing — small building-block tests
# --------------------------------------------------------------------------

class TestParseLogEntries(unittest.TestCase):
    def test_parses_one_entry_into_time_type_and_fields(self):
        text = _entry("09:12", "file-capture", entry_id="abc123", feedback="validated")
        entries = graduation.parse_log_entries(text)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["time"], "09:12")
        self.assertEqual(e["heading_action_type"], "file-capture")
        self.assertEqual(e["fields"]["entry id"], "abc123")
        self.assertEqual(e["fields"]["feedback"], "validated")

    def test_parses_multiple_entries_in_one_file(self):
        text = _entry("09:00", "file-capture", entry_id="a") + _entry("10:00", "project-update", entry_id="b")
        entries = graduation.parse_log_entries(text)
        self.assertEqual([e["fields"]["entry id"] for e in entries], ["a", "b"])

    def test_empty_text_returns_no_entries(self):
        self.assertEqual(graduation.parse_log_entries(""), [])


class TestParseConfig(unittest.TestCase):
    def test_parse_autonomy_policy_reads_ints(self):
        fixture = BrainFixture([], window_days=2, min_qualifying=7, min_sessions=4, debt_max=15)
        try:
            policy = graduation.parse_autonomy_policy(fixture.path)
            self.assertEqual(policy["review-window-days"], 2)
            self.assertEqual(policy["graduation-min-qualifying"], 7)
            self.assertEqual(policy["graduation-min-sessions"], 4)
            self.assertEqual(policy["review-debt-max"], 15)
        finally:
            fixture.cleanup()

    def test_missing_policy_file_returns_empty_dict(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            self.assertEqual(graduation.parse_autonomy_policy(Path(tmp.name)), {})
        finally:
            tmp.cleanup()

    def test_parse_action_types_reads_rows(self):
        fixture = BrainFixture([("file-capture", "internal & reversible", "confirm-first", "notes here")])
        try:
            rows = graduation.parse_action_types(fixture.path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Action type"], "file-capture")
            self.assertEqual(rows[0]["Risk tier"], "internal & reversible")
        finally:
            fixture.cleanup()


# --------------------------------------------------------------------------
# find_unclassified_feedback
# --------------------------------------------------------------------------

class TestFindUnclassifiedFeedback(GraduationTestCase):
    def test_flags_free_text_feedback(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", entry_id="x1", feedback="yep good"))
        candidates = graduation.find_unclassified_feedback(b.path)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["entry_id"], "x1")
        self.assertEqual(candidates[0]["feedback"], "yep good")

    def test_ignores_unset_dash(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", feedback="—"))
        self.assertEqual(graduation.find_unclassified_feedback(b.path), [])

    def test_ignores_validated(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", feedback="validated"))
        self.assertEqual(graduation.find_unclassified_feedback(b.path), [])

    def test_ignores_corrected_with_detail(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", feedback="corrected — should have filed under Kids"))
        self.assertEqual(graduation.find_unclassified_feedback(b.path), [])

    def test_bare_corrected_with_no_detail_is_flagged(self):
        # The canonical shape requires a payload after "corrected — ".
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", feedback="corrected"))
        candidates = graduation.find_unclassified_feedback(b.path)
        self.assertEqual(len(candidates), 1)

    def test_entry_missing_feedback_field_entirely_is_surfaced_not_skipped(self):
        # A malformed entry (no `feedback:` line at all) is also "not one
        # of the 3 canonical shapes" — surface it rather than hide it,
        # matching heartbeat.py's precedent of surfacing malformed data.
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        malformed = (
            "### 09:00 — file-capture\n\n"
            "- **entry id:** m1\n"
            "- **actor:** claude-session-01-01-2026\n"
            "- **trigger:** Direct instruction\n"
            "- **input link:** —\n"
            "- **action type:** file-capture\n"
            "- **action:** did the thing\n"
            "- **confidence:** High\n"
            "- **outcome:** Done\n"
            "- **parent reference:** —\n\n"
        )
        b.log("2026-07-10", malformed)
        candidates = graduation.find_unclassified_feedback(b.path)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["entry_id"], "m1")
        self.assertEqual(candidates[0]["feedback"], "")

    def test_no_log_dir_returns_no_candidates(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            self.assertEqual(graduation.find_unclassified_feedback(Path(tmp.name)), [])
        finally:
            tmp.cleanup()


# --------------------------------------------------------------------------
# compute_graduation_state — the core counting engine
# --------------------------------------------------------------------------

class TestGraduationCounting(GraduationTestCase):
    def test_internal_reversible_graduates_on_5_qualifying_across_3_days(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        # Aged well past the 1-day review window (now = 15/07, entries early July).
        b.log("2026-07-01", _entry("09:00", "file-capture", entry_id="a1", feedback="validated"))
        b.log("2026-07-01", _entry("10:00", "file-capture", entry_id="a2", feedback="—"))
        b.log("2026-07-02", _entry("09:00", "file-capture", entry_id="a3", feedback="validated"))
        b.log("2026-07-03", _entry("09:00", "file-capture", entry_id="a4", feedback="—"))
        b.log("2026-07-03", _entry("10:00", "file-capture", entry_id="a5", feedback="validated"))

        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["decision"], "graduate")
        self.assertEqual(state["file-capture"]["qualifying_count"], 5)
        self.assertEqual(state["file-capture"]["qualifying_days"], 3)

    def test_internal_reversible_does_not_graduate_confined_to_1_day(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        # 5 qualifying instances (== threshold) but all on a single day.
        b.log(
            "2026-07-01",
            _entry("09:00", "file-capture", entry_id="a1", feedback="validated"),
            _entry("10:00", "file-capture", entry_id="a2", feedback="validated"),
            _entry("11:00", "file-capture", entry_id="a3", feedback="validated"),
            _entry("12:00", "file-capture", entry_id="a4", feedback="validated"),
            _entry("13:00", "file-capture", entry_id="a5", feedback="validated"),
        )
        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["decision"], "none")
        self.assertEqual(state["file-capture"]["qualifying_count"], 5)
        self.assertEqual(state["file-capture"]["qualifying_days"], 1)

    def test_internal_reversible_does_not_graduate_confined_to_2_days(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        # 6 qualifying instances (>= threshold of 5) but only 2 distinct days.
        b.log(
            "2026-07-01",
            _entry("09:00", "file-capture", entry_id="a1", feedback="validated"),
            _entry("10:00", "file-capture", entry_id="a2", feedback="validated"),
            _entry("11:00", "file-capture", entry_id="a3", feedback="—"),
        )
        b.log(
            "2026-07-02",
            _entry("09:00", "file-capture", entry_id="a4", feedback="validated"),
            _entry("10:00", "file-capture", entry_id="a5", feedback="validated"),
            _entry("11:00", "file-capture", entry_id="a6", feedback="—"),
        )
        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["decision"], "none")
        self.assertEqual(state["file-capture"]["qualifying_count"], 6)
        self.assertEqual(state["file-capture"]["qualifying_days"], 2)

    def test_outward_facing_does_not_graduate_on_aged_dash_alone(self):
        b = self.brain([("wiki-audit-merge-duplicate", "outward-facing / hard-to-reverse", "confirm-first", "-")])
        for i, date_str in enumerate(["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"]):
            b.log(date_str, _entry("09:00", "wiki-audit-merge-duplicate", entry_id=f"o{i}", feedback="—"))

        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["wiki-audit-merge-duplicate"]["decision"], "none")
        self.assertEqual(state["wiki-audit-merge-duplicate"]["qualifying_count"], 0)

    def test_outward_facing_graduates_on_explicit_validated_only(self):
        b = self.brain([("wiki-audit-merge-duplicate", "outward-facing / hard-to-reverse", "confirm-first", "-")])
        for i, date_str in enumerate(["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"]):
            b.log(date_str, _entry("09:00", "wiki-audit-merge-duplicate", entry_id=f"o{i}", feedback="validated"))

        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["wiki-audit-merge-duplicate"]["decision"], "graduate")
        self.assertEqual(state["wiki-audit-merge-duplicate"]["qualifying_count"], 5)

    def test_review_debt_over_threshold_suspends_aged_dash_but_not_validated(self):
        # Low debt-max (2) blown by a pile of unrelated aged-`—` entries on a
        # second action type — proves the suspension is global/system-wide,
        # not scoped to the type under test.
        b = self.brain(
            [
                ("file-capture", "internal & reversible", "confirm-first", "-"),
                ("project-update", "internal & reversible", "confirm-first", "-"),
            ],
            debt_max=2,
        )
        # file-capture: 3 validated (count regardless of debt) + 2 aged-`—`
        # (would qualify without debt suspension, spread across 3 days).
        b.log("2026-07-01", _entry("09:00", "file-capture", entry_id="a1", feedback="validated"))
        b.log("2026-07-02", _entry("09:00", "file-capture", entry_id="a2", feedback="validated"))
        b.log("2026-07-03", _entry("09:00", "file-capture", entry_id="a3", feedback="validated"))
        b.log("2026-07-04", _entry("09:00", "file-capture", entry_id="a4", feedback="—"))
        b.log("2026-07-05", _entry("09:00", "file-capture", entry_id="a5", feedback="—"))
        # Debt padding on an unrelated type: 3 aged-`—` entries, pushing
        # system-wide debt to 5 (well over debt_max=2).
        b.log("2026-07-01", _entry("09:30", "project-update", entry_id="d1", feedback="—"))
        b.log("2026-07-02", _entry("09:30", "project-update", entry_id="d2", feedback="—"))
        b.log("2026-07-03", _entry("09:30", "project-update", entry_id="d3", feedback="—"))

        debt = graduation.review_debt(b.path, now=NOW)
        self.assertGreater(debt, 2)

        state = graduation.compute_graduation_state(b.path, now=NOW)
        # Only the 3 validated instances qualify — the 2 aged-`—` ones on
        # file-capture are suspended by system-wide debt.
        self.assertEqual(state["file-capture"]["qualifying_count"], 3)
        self.assertEqual(state["file-capture"]["decision"], "none")

    def test_review_debt_under_threshold_lets_aged_dash_qualify_normally(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")], debt_max=20)
        b.log("2026-07-01", _entry("09:00", "file-capture", entry_id="a1", feedback="validated"))
        b.log("2026-07-02", _entry("09:00", "file-capture", entry_id="a2", feedback="—"))
        b.log("2026-07-03", _entry("09:00", "file-capture", entry_id="a3", feedback="—"))
        b.log("2026-07-04", _entry("09:00", "file-capture", entry_id="a4", feedback="validated"))
        b.log("2026-07-05", _entry("09:00", "file-capture", entry_id="a5", feedback="—"))

        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["decision"], "graduate")
        self.assertEqual(state["file-capture"]["qualifying_count"], 5)

    def test_corrected_entry_demotes_autonomous_type_instantly(self):
        b = self.brain([("file-capture", "internal & reversible", "autonomous", "-")])
        b.log("2026-07-10", _entry(
            "09:00", "file-capture", entry_id="a1",
            feedback="corrected — should have filed under Rentals",
        ))
        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["decision"], "demote")
        self.assertIn("a1", state["file-capture"]["reason"])

    def test_autonomous_type_with_no_corrections_stays_none(self):
        b = self.brain([("file-capture", "internal & reversible", "autonomous", "-")])
        b.log("2026-07-10", _entry("09:00", "file-capture", entry_id="a1", feedback="validated"))
        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["decision"], "none")

    def test_demotion_resets_count_so_next_pass_starts_from_zero(self):
        # A pre-demotion history of 4 validated instances across 4 days
        # (one qualifying instance short of graduating), THEN a demote
        # boundary entry, THEN 2 more validated instances after the
        # boundary. If the count carried over instead of resetting, the
        # post-boundary total would look like 6/5 (graduate); since the
        # engine must start counting fresh from the boundary, only the 2
        # post-boundary instances should be visible.
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-01", _entry("09:00", "file-capture", entry_id="pre1", feedback="validated"))
        b.log("2026-07-02", _entry("09:00", "file-capture", entry_id="pre2", feedback="validated"))
        b.log("2026-07-03", _entry("09:00", "file-capture", entry_id="pre3", feedback="validated"))
        b.log("2026-07-04", _entry("09:00", "file-capture", entry_id="pre4", feedback="validated"))
        b.log("2026-07-05", _boundary_entry("09:00", "file-capture", "confirm-first", entry_id="boundary1"))
        b.log("2026-07-06", _entry("09:00", "file-capture", entry_id="post1", feedback="validated"))
        b.log("2026-07-07", _entry("09:00", "file-capture", entry_id="post2", feedback="validated"))

        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["qualifying_count"], 2)
        self.assertEqual(state["file-capture"]["qualifying_days"], 2)
        self.assertEqual(state["file-capture"]["decision"], "none")


class TestBoundaryParsing(GraduationTestCase):
    def test_finds_most_recent_boundary_among_several(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-01", _boundary_entry("09:00", "file-capture", "autonomous", entry_id="b1"))
        b.log("2026-07-03", _boundary_entry("09:00", "file-capture", "confirm-first", entry_id="b2"))
        # A pre-b2 entry (should NOT count) and a post-b2 entry (should count).
        b.log("2026-07-02", _entry("09:00", "file-capture", entry_id="pre", feedback="validated"))
        b.log("2026-07-04", _entry("09:00", "file-capture", entry_id="post", feedback="validated"))

        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["qualifying_count"], 1)

    def test_no_boundary_entry_counts_since_inception(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-01", _entry("09:00", "file-capture", entry_id="a1", feedback="validated"))
        b.log("2026-07-02", _entry("09:00", "file-capture", entry_id="a2", feedback="validated"))
        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["qualifying_count"], 2)

    def test_boundary_for_a_different_type_is_ignored(self):
        b = self.brain([("file-capture", "internal & reversible", "confirm-first", "-")])
        b.log("2026-07-01", _boundary_entry("09:00", "project-update", "autonomous", entry_id="b1"))
        b.log("2026-07-02", _entry("09:00", "file-capture", entry_id="a1", feedback="validated"))
        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertEqual(state["file-capture"]["qualifying_count"], 1)


# --------------------------------------------------------------------------
# Fixed-autonomous exclusion — the one item flagged for explicit coverage.
# --------------------------------------------------------------------------

class TestFixedAutonomousExclusion(GraduationTestCase):
    def test_fixed_autonomous_types_never_appear_in_result_even_with_corrections(self):
        b = self.brain([
            ("graduate-action-type", "internal & reversible", "autonomous (fixed)", "-"),
            ("demote-action-type", "internal & reversible", "autonomous (fixed)", "-"),
            ("propose-rule-diff", "internal & reversible", "autonomous (fixed)", "-"),
            ("file-capture", "internal & reversible", "confirm-first", "-"),
        ])
        # Each fixed type gets a `corrected` entry on its OWN log entry —
        # per the ticket, this must NOT demote it, because it's never
        # evaluated at all.
        b.log("2026-07-10", _entry(
            "09:00", "graduate-action-type", entry_id="g1",
            feedback="corrected — this graduation call was wrong",
            outcome="`file-capture` → autonomous (5 qualifying instances across 3 distinct days)",
        ))
        b.log("2026-07-10", _entry(
            "10:00", "demote-action-type", entry_id="d1",
            feedback="corrected — this demotion call was wrong",
            outcome="`file-capture` → confirm-first (corrected feedback found)",
        ))
        b.log("2026-07-10", _entry(
            "11:00", "propose-rule-diff", entry_id="r1",
            feedback="corrected — this rule proposal was wrong",
        ))
        # A normal type too, to prove the exclusion is targeted, not global.
        b.log("2026-07-11", _entry("09:00", "file-capture", entry_id="f1", feedback="validated"))

        state = graduation.compute_graduation_state(b.path, now=NOW)

        self.assertNotIn("graduate-action-type", state)
        self.assertNotIn("demote-action-type", state)
        self.assertNotIn("propose-rule-diff", state)
        self.assertIn("file-capture", state)

    def test_plain_autonomous_without_fixed_suffix_is_processed_normally(self):
        # Guards against an over-broad exclusion matching on "autonomous"
        # as a prefix rather than the exact fixed-marker string.
        b = self.brain([("file-capture", "internal & reversible", "autonomous", "-")])
        b.log("2026-07-10", _entry(
            "09:00", "file-capture", entry_id="a1", feedback="corrected — wrong area",
        ))
        state = graduation.compute_graduation_state(b.path, now=NOW)
        self.assertIn("file-capture", state)
        self.assertEqual(state["file-capture"]["decision"], "demote")


if __name__ == "__main__":
    unittest.main()
