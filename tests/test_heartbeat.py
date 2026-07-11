import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import heartbeat  # noqa: E402


class TestParseTable(unittest.TestCase):
    def test_parses_rows_into_dicts(self):
        text = (
            "| Routine | Last run |\n"
            "|---|---|\n"
            "| Triage | never |\n"
            "| Dashboard | 2026-07-01 09:00 |\n"
        )
        rows = heartbeat.parse_table(text)
        self.assertEqual(
            rows,
            [
                {"Routine": "Triage", "Last run": "never"},
                {"Routine": "Dashboard", "Last run": "2026-07-01 09:00"},
            ],
        )

    def test_empty_text_returns_no_rows(self):
        self.assertEqual(heartbeat.parse_table(""), [])


class TestComputeOverdue(unittest.TestCase):
    def _row(self, routine, cadence, status):
        return {"Routine": routine, "Cadence": cadence, "Phase 2 status": status}

    def test_never_run_implemented_heartbeat_checkable_is_overdue(self):
        manifest = [self._row("Triage", "daily — heartbeat-checkable", "implemented (ticket 09)")]
        overdue = heartbeat.compute_overdue(manifest, {"Triage": "never"})
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["routine"], "Triage")

    def test_unimplemented_routine_never_flagged(self):
        manifest = [
            self._row("Weekly Review", "weekly — heartbeat-checkable", "declared, not implemented (Phase 6)")
        ]
        overdue = heartbeat.compute_overdue(manifest, {"Weekly Review": "never"})
        self.assertEqual(overdue, [])

    def test_event_triggered_implemented_routine_never_flagged(self):
        manifest = [self._row("Execute", "on approval — event-triggered", "implemented (ticket 10)")]
        overdue = heartbeat.compute_overdue(manifest, {"Execute": "never"})
        self.assertEqual(overdue, [])

    def test_within_cadence_window_not_overdue(self):
        now = dt.datetime(2026, 7, 11, 10, 0)
        manifest = [self._row("Dashboard", "morning — heartbeat-checkable (daily)", "implemented (ticket 11)")]
        last_run = (now - dt.timedelta(hours=2)).strftime(heartbeat.TIMESTAMP_FORMAT)
        overdue = heartbeat.compute_overdue(manifest, {"Dashboard": last_run}, now=now)
        self.assertEqual(overdue, [])

    def test_past_cadence_window_is_overdue(self):
        now = dt.datetime(2026, 7, 11, 10, 0)
        manifest = [self._row("Dashboard", "morning — heartbeat-checkable (daily)", "implemented (ticket 11)")]
        last_run = (now - dt.timedelta(days=2)).strftime(heartbeat.TIMESTAMP_FORMAT)
        overdue = heartbeat.compute_overdue(manifest, {"Dashboard": last_run}, now=now)
        self.assertEqual(len(overdue), 1)

    def test_real_manifest_parses_and_flags_only_the_three_daily_routines(self):
        manifest = heartbeat.parse_manifest()
        routine_state = {row["Routine"]: "never" for row in manifest}
        overdue = heartbeat.compute_overdue(manifest, routine_state)
        overdue_names = {item["routine"] for item in overdue}
        self.assertEqual(overdue_names, {"Triage", "Dashboard", "Version control"})


if __name__ == "__main__":
    unittest.main()
