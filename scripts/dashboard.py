#!/usr/bin/env python3
"""Generate Dashboard.md — a pure derivation, safe to overwrite every run.

Implements protocols/dashboard.md: surfaces overdue Routines (via
heartbeat.py), pending Triage Plans (via execute.py's row parsing), and a
same-day Action Log summary. Read/link-only — writes <brain>/Dashboard.md,
plus bumping its own "Dashboard" row in config/routine-state.md
afterward (bookkeeping only — see protocols/dashboard.md); approval and
feedback happen in the linked files, not here.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import execute  # noqa: E402


def _pending_plan_summary(path: Path) -> dict:
    text = path.read_text()
    rows = execute.parse_plan_rows(text)
    ticked = sum(1 for r in rows if r["approve"] in ("[x]", "[x] (done)"))
    return {"path": path, "total": len(rows), "ticked": ticked, "pending": len(rows) - ticked}


def _pending_plans(brain_path: Path) -> list:
    triage_dir = brain_path / "inbox" / "triage"
    if not triage_dir.is_dir():
        return []

    plans = []
    for path in sorted(triage_dir.glob("*.md")):
        status_match = re.search(r'^status:\s*(\S+)', path.read_text(), re.MULTILINE)
        if status_match and status_match.group(1) == "pending":
            plans.append(_pending_plan_summary(path))
    return plans


def _action_log_summary(brain_path: Path, date_str: str) -> dict:
    log_path = brain_path / "log" / f"{date_str}.md"
    if not log_path.exists():
        return {"exists": False, "entry_count": 0, "unreviewed": 0, "date_str": date_str}

    text = log_path.read_text()
    entry_count = len(re.findall(r'^### ', text, re.MULTILINE))
    unreviewed = len(re.findall(r'^\s*-\s*\*\*feedback:\*\*\s*—\s*$', text, re.MULTILINE))
    return {"exists": True, "entry_count": entry_count, "unreviewed": unreviewed, "date_str": date_str}


def compute_dashboard_data(brain_path: Path, now: dt.datetime = None) -> dict:
    now = now or dt.datetime.now()
    manifest = heartbeat.parse_manifest()
    routine_state = heartbeat.parse_routine_state(brain_path / "config" / "routine-state.md")
    return {
        "generated": now.strftime(heartbeat.TIMESTAMP_FORMAT),
        "date_str": now.strftime("%Y-%m-%d"),
        "overdue": heartbeat.compute_overdue(manifest, routine_state, now=now),
        "pending_plans": _pending_plans(brain_path),
        "action_log": _action_log_summary(brain_path, now.strftime("%Y-%m-%d")),
    }


def render_dashboard(data: dict) -> str:
    lines = [
        "---",
        "type: dashboard",
        f"generated: {data['generated']}",
        "---",
        "",
        f"# Dashboard — {data['date_str']}",
        "",
        "## Overdue routines",
        "",
    ]

    if data["overdue"]:
        for item in data["overdue"]:
            lines.append(f"- {item['routine']} (last run: {item['last_run']})")
    else:
        lines.append("Nothing overdue.")

    lines += ["", "## Pending Triage Plans", ""]
    if data["pending_plans"]:
        for plan in data["pending_plans"]:
            rel = plan["path"].as_posix().split("inbox/triage/", 1)[-1]
            lines.append(
                f"- [[inbox/triage/{rel}]] — {plan['total']} row(s), "
                f"{plan['ticked']} ticked, {plan['pending']} awaiting approval"
            )
    else:
        lines.append("No pending Triage Plans.")

    lines += ["", "## Today's Action Log", ""]
    log = data["action_log"]
    if log["exists"]:
        lines.append(f"- {log['entry_count']} entr{'y' if log['entry_count'] == 1 else 'ies'} logged today ([[log/{log['date_str']}]])")
        lines.append(f"- {log['unreviewed']} awaiting your feedback (marked `—`)")
    else:
        lines.append("No Action Log entries yet today.")

    lines += [
        "",
        "---",
        "",
        "Read/link-only: approve Triage Plan rows in their own files, and write feedback directly into today's Action Log. "
        "This file is regenerated every run — don't edit it by hand.",
        "",
    ]
    return "\n".join(lines)


def write_dashboard(brain_path: Path, now: dt.datetime = None) -> Path:
    now = now or dt.datetime.now()
    data = compute_dashboard_data(brain_path, now=now)
    text = render_dashboard(data)
    path = brain_path / "Dashboard.md"
    path.write_text(text)

    # Bumped after computing "overdue" above, so this run's own Dashboard
    # entry (if it was overdue coming in) still shows in what it renders.
    heartbeat.bump(brain_path, "Dashboard", now)
    return path


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    path = write_dashboard(brain_path)
    print(f"Dashboard written to {path}")


if __name__ == "__main__":
    main()
