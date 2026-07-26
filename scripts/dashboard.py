#!/usr/bin/env python3
"""Generate Dashboard.md — a pure derivation, safe to overwrite every run.

Implements protocols/dashboard.md: surfaces overdue Routines (via
heartbeat.py), pending Triage Plans (via execute.py's row parsing),
pending rule-diff reviews (via rule_diff_review.py's diff parsing), a
same-day Action Log summary, open Waiting For items (scanned from
people/*.md), open proposed items (scanned from meetings/*.md), and
pending Dropzone item counts (scanned from Files/dropzone/*, a sibling of
the Brain root, not inside it). Read/link-only — writes
<brain>/Dashboard.md, plus bumping its own "Dashboard" row in
config/routine-state.md afterward (bookkeeping only — see
protocols/dashboard.md); approval and feedback happen in the linked
files, not here — Waiting For items are only ever logged on a Person Hub,
and a proposed item is only ever approved in its own meeting note.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import execute  # noqa: E402
import md_sections  # noqa: E402
import rule_diff_review  # noqa: E402


def _wikilink(path: Path, root_dir: str) -> str:
    rel = path.as_posix().split(f"{root_dir}/", 1)[-1]
    return f"[[{root_dir}/{rel}]]"


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


def _pending_rule_diff_summary(path: Path) -> dict:
    text = path.read_text()
    diffs = rule_diff_review.parse_batch(text)
    decided = sum(
        1 for d in diffs
        if d["approve_state"] is not None or d["reject_state"] is not None
    )
    return {"path": path, "total": len(diffs), "decided": decided, "pending": len(diffs) - decided}


def _pending_rule_diffs(brain_path: Path) -> list:
    diffs_dir = brain_path / "inbox" / "rule-diffs"
    if not diffs_dir.is_dir():
        return []

    batches = []
    for path in sorted(diffs_dir.glob("*.md")):
        status_match = re.search(r'^status:\s*(\S+)', path.read_text(), re.MULTILINE)
        if status_match and status_match.group(1) == "pending":
            batches.append(_pending_rule_diff_summary(path))
    return batches


def _open_waiting_for(brain_path: Path) -> list:
    people_dir = brain_path / "people"
    if not people_dir.is_dir():
        return []

    items = []
    for path in sorted(people_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        text = path.read_text()
        name_match = re.search(r'^name:\s*(.+)$', text, re.MULTILINE)
        name = name_match.group(1).strip() if name_match else path.stem

        section_match = re.search(
            md_sections.SECTION_BODY.format('.*Waiting For'), text, re.MULTILINE | re.DOTALL
        )
        if not section_match:
            continue

        for line in section_match.group(1).splitlines():
            stripped = line.strip()
            if "#waiting-for" not in stripped:
                continue
            if stripped.startswith("- [x]") or "~~" in stripped:
                continue
            item_text = re.sub(r'^-\s*(\[\s?\]\s*)?', "", stripped).strip()
            items.append({"person": name, "path": path, "text": item_text})
    return items


def _open_proposed_items(brain_path: Path) -> list:
    """Every unticked `- [ ]` line under a `## Proposed` heading across
    `meetings/*.md`, per protocols/dashboard.md v0.5.

    The `meetings` plugin writes items it cannot safely auto-file — new Person
    Hubs, ambiguous names, "this looked resolved, close it?" — into a meeting
    note's `## Proposed` section, because confirm-first is impossible in a
    headless hook. Nothing surfaced them, so they were written and then missed.

    Returns per-item dicts (the same shape `_open_waiting_for` returns) rather
    than per-note ones: the Dashboard groups these by note, while the daily
    note renders them per item, and one scan serves both. Non-destructive —
    this never ticks, edits, or moves a meeting note.
    """
    meetings_dir = brain_path / "meetings"
    if not meetings_dir.is_dir():
        return []

    items = []
    for path in sorted(meetings_dir.glob("*.md")):
        if path.name.startswith("_") or path.name == "README.md":
            continue
        text = path.read_text()
        title_match = re.search(r'^# (.+)$', text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else path.stem

        # `[ \t]*\n`, not `\s*\n`: `\s` matches newlines, so on an empty
        # `## Proposed` section the match would run on into the following
        # sections and scoop up unrelated `- [ ]` lines as proposed items.
        section_match = re.search(
            r'^## .*Proposed[ \t]*\n(.*?)(?=\n## |\Z)', text, re.MULTILINE | re.DOTALL
        )
        if not section_match:
            continue

        for line in section_match.group(1).splitlines():
            stripped = line.strip()
            if not stripped.startswith("- [ ]"):
                continue
            if "~~" in stripped:
                continue
            item_text = stripped[len("- [ ]"):].strip()
            if not item_text:
                continue
            items.append({"meeting": title, "path": path, "text": item_text})
    return items


def _proposed_by_note(items: list) -> list:
    """Collapse `_open_proposed_items()` output to one row per meeting note,
    preserving scan order (already sorted by filename)."""
    by_path = {}
    for item in items:
        key = item["path"]
        if key not in by_path:
            by_path[key] = {"meeting": item["meeting"], "path": key, "count": 0}
        by_path[key]["count"] += 1
    return list(by_path.values())


def _awaiting_review_tickets(brain_path: Path) -> list:
    tasks_dir = brain_path / "tasks"
    if not tasks_dir.is_dir():
        return []

    tickets = []
    for path in sorted(tasks_dir.glob("**/*.md")):
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        text = path.read_text()
        status_match = re.search(r'^status:\s*(\S+)', text, re.MULTILINE)
        if status_match and status_match.group(1) == "awaiting-review":
            title_match = re.search(r'^# (.+)$', text, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else path.stem
            tickets.append({"title": title, "path": path})
    return tickets


DROPZONE_SUBFOLDERS = ("Expenses", "Homework", "Recipes")


def _dropzone_counts(brain_path: Path) -> list:
    # Files/dropzone/ lives outside the Brain entirely — a sibling of the
    # Brain root under the Documents root (Documents/Vault vs
    # Documents/Files/dropzone), not a path inside brain_path.
    dropzone_dir = brain_path.parent / "Files" / "dropzone"

    counts = []
    for name in DROPZONE_SUBFOLDERS:
        subfolder = dropzone_dir / name
        if subfolder.is_dir():
            count = sum(
                1 for p in subfolder.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
        else:
            count = 0
        counts.append({"name": name, "count": count})
    return counts


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
    return {
        "generated": now.strftime(heartbeat.TIMESTAMP_FORMAT),
        "date_str": now.strftime("%Y-%m-%d"),
        # Cadence comes from the Brain's config/schedules.md (ADR-0030); a Brain
        # without one simply has no overdue section, and heartbeat warns.
        "overdue": heartbeat.overdue_for_brain(brain_path, now=now),
        "pending_plans": _pending_plans(brain_path),
        "pending_rule_diffs": _pending_rule_diffs(brain_path),
        "awaiting_review_tickets": _awaiting_review_tickets(brain_path),
        "waiting_for": _open_waiting_for(brain_path),
        "proposed_from_meetings": _proposed_by_note(_open_proposed_items(brain_path)),
        "action_log": _action_log_summary(brain_path, now.strftime("%Y-%m-%d")),
        "dropzone": _dropzone_counts(brain_path),
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
            link = _wikilink(plan["path"], "inbox/triage")
            lines.append(
                f"- {link} — {plan['total']} row(s), "
                f"{plan['ticked']} ticked, {plan['pending']} awaiting approval"
            )
    else:
        lines.append("No pending Triage Plans.")

    lines += ["", "## Pending review", ""]
    if data["pending_rule_diffs"]:
        for batch in data["pending_rule_diffs"]:
            link = _wikilink(batch["path"], "inbox/rule-diffs")
            lines.append(
                f"- {link} — {batch['total']} diff(s), "
                f"{batch['decided']} decided, {batch['pending']} awaiting review"
            )
    else:
        lines.append("No pending rule-diff reviews.")

    lines += ["", "## Tickets awaiting review", ""]
    if data.get("awaiting_review_tickets"):
        for ticket in data["awaiting_review_tickets"]:
            link = _wikilink(ticket["path"], "tasks")
            lines.append(f"- **{ticket['title']}** ({link})")
    else:
        lines.append("No tickets awaiting review.")

    lines += ["", "## Waiting For", ""]
    if data["waiting_for"]:
        for item in data["waiting_for"]:
            link = _wikilink(item["path"], "people")
            lines.append(f"- **{item['person']}** — {item['text']} ({link})")
    else:
        lines.append("Nothing open.")

    lines += ["", "## Proposed from meetings", ""]
    if data.get("proposed_from_meetings"):
        for note in data["proposed_from_meetings"]:
            link = _wikilink(note["path"], "meetings")
            plural = "" if note["count"] == 1 else "s"
            lines.append(
                f"- **{note['meeting']}** — {note['count']} proposed item{plural} ({link})"
            )
    else:
        lines.append("Nothing proposed.")

    lines += ["", "## Today's Action Log", ""]
    log = data["action_log"]
    if log["exists"]:
        lines.append(f"- {log['entry_count']} entr{'y' if log['entry_count'] == 1 else 'ies'} logged today ([[log/{log['date_str']}]])")
        lines.append(f"- {log['unreviewed']} awaiting your feedback (marked `—`)")
    else:
        lines.append("No Action Log entries yet today.")

    lines += ["", "## 📁 Dropzone awaiting processing", ""]
    for item in data["dropzone"]:
        lines.append(f"- {item['name']}: {item['count']} waiting")

    lines += [
        "",
        "---",
        "",
        "Read/link-only: approve Triage Plan rows and rule-diff reviews in their own files, and write feedback directly into today's Action Log. "
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
