#!/usr/bin/env python3
"""Due-check a Brain's Routines against the Engine's manifest.

Implements protocols/routines.md's Heartbeat half: reads this repo's
manifest table and a Brain's config/routine-state.md (last-run only) and
reports which heartbeat-checkable, implemented Routines are overdue.
Pure Python, zero LLM calls, nudge-only — never runs anything itself.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

CADENCE_DAYS = {
    "hourly": 1 / 24,
    "daily": 1,
    "weekly": 7,
    "fortnightly": 14,
    "monthly": 30,
    "quarterly": 90,
}

MANIFEST_PATH = Path(__file__).parent.parent / "protocols" / "routines.md"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


def parse_table(text: str) -> list:
    """Parse the first markdown table in `text` into a list of row dicts."""
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        return []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:  # skip header + --- separator row
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def parse_manifest(path: Path = MANIFEST_PATH) -> list:
    return parse_table(path.read_text())


def parse_routine_state(path: Path) -> dict:
    if not path.exists():
        return {}
    rows = parse_table(path.read_text())
    return {r["Routine"]: r["Last run"] for r in rows if "Routine" in r and "Last run" in r}


def update_last_run(path: Path, routine: str, timestamp_str: str) -> bool:
    """Rewrite one Routine's Last-run cell in a 2-column routine-state.md.

    Shared by every script that implements a Routine (version_control.py,
    triage.py, execute.py, dashboard.py, stamp.py) — each bumps its own
    row after a successful run, so this due-check reflects reality. A
    silent no-op if the file or the row doesn't exist (e.g. a Brain not
    yet onboarded) — the routine still ran; there's just nowhere to
    record it. Returns True if the row was found and updated.
    """
    if not path.exists():
        return False
    text = path.read_text()
    if not any(r.get("Routine") == routine for r in parse_table(text)):
        return False

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"| {routine} |"):
            lines[i] = f"| {routine} | {timestamp_str} |"
            break
    path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
    return True


def bump(brain_path: Path, routine: str, now: dt.datetime) -> bool:
    """Convenience wrapper: bump `routine`'s row in `<brain_path>/config/routine-state.md`.

    Every Routine-implementing script's own call site reduces to this one
    line — the `config/routine-state.md` path and the timestamp format
    stay in one place (here) rather than repeated at each call site.
    """
    return update_last_run(brain_path / "config" / "routine-state.md", routine, now.strftime(TIMESTAMP_FORMAT))


def _cadence_days(cadence_cell: str):
    match = re.search(
        r"\b(hourly|daily|weekly|fortnightly|monthly|quarterly)\b", cadence_cell.lower()
    )
    return CADENCE_DAYS[match.group(1)] if match else None


def compute_overdue(manifest: list, routine_state: dict, now: dt.datetime = None) -> list:
    """Return the heartbeat-checkable, implemented Routines that are due.

    Only Routines whose manifest row is marked "implemented" (Phase 2
    status) *and* whose cadence is heartbeat-checkable are evaluated at
    all — event-triggered Routines and declared-not-implemented ones are
    silently skipped, by design (ADR-0007, protocols/routines.md).
    """
    now = now or dt.datetime.now()
    overdue = []
    for row in manifest:
        status = row.get("Phase 2 status", "")
        cadence_cell = row.get("Cadence", "")
        if not status.startswith("implemented"):
            continue
        if "heartbeat-checkable" not in cadence_cell:
            continue
        days = _cadence_days(cadence_cell)
        if days is None:
            continue

        routine = row["Routine"]
        last_run = routine_state.get(routine, "never")

        if last_run == "never":
            overdue.append({"routine": routine, "last_run": "never", "cadence_days": days})
            continue

        try:
            last_dt = dt.datetime.strptime(last_run, TIMESTAMP_FORMAT)
        except ValueError:
            # Unparseable timestamp — surface it rather than silently skip.
            overdue.append({"routine": routine, "last_run": last_run, "cadence_days": days})
            continue

        if (now - last_dt).total_seconds() / 86400 >= days:
            overdue.append({"routine": routine, "last_run": last_run, "cadence_days": days})

    return overdue


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain (contains config/routine-state.md)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    manifest = parse_manifest()
    routine_state = parse_routine_state(brain_path / "config" / "routine-state.md")
    overdue = compute_overdue(manifest, routine_state)

    if not overdue:
        print("Nothing overdue.")
        return

    print("Overdue routines:")
    for item in overdue:
        print(f"  - {item['routine']} (last run: {item['last_run']})")


if __name__ == "__main__":
    main()
