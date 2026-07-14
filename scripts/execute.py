#!/usr/bin/env python3
"""Execute an approved Triage Plan's ticked rows.

Implements protocols/execute.md's minimal generic action type: exactly two
internal/reversible actions, `file-capture` and `discard-capture` — no
Area/Capability agent dispatch (Phase 3), no auto-execute on confidence
(graduation is Phase 5). Every row must already carry an explicit `[x]`
tick; unticked rows are left untouched for a future run.
"""

import argparse
import datetime as dt
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import log_action  # noqa: E402

ROW_RE = re.compile(
    r'^\|\s*(?P<n>\d+)\s*\|\s*\[\[(?P<capture>[^\]]+)\]\]\s*\|\s*(?P<preview>.*?)\s*\|'
    r'\s*(?P<route>Pass [AB])\s*\|\s*(?P<destination>.*?)\s*\|\s*(?P<confidence>.*?)\s*\|'
    r'\s*(?P<approve>\[[ x]\](?:\s*\((?:done|dispatched)\))?)\s*\|\s*$'
)
FRONTMATTER_STATUS_RE = re.compile(r'^status:\s*\S+\s*$', re.MULTILINE)


class ExecuteError(Exception):
    pass


def action_type_for(destination: str) -> str:
    cleaned = destination.strip().lower()
    if cleaned.startswith("agent:"):
        return "agent-dispatched"
    if cleaned == "discard":
        return "discard-capture"
    if cleaned == "today":
        return "file-capture-today"
    return "file-capture"


def parse_plan_rows(text: str) -> list:
    """Return every table row as a dict, in file order. Pure — no I/O."""
    rows = []
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if m:
            rows.append(m.groupdict())
    return rows


def _mark_done(line: str, match: re.Match) -> str:
    start, end = match.span("approve")
    return line[:start] + "[x] (done)" + line[end:]


def _mark_dispatched(line: str, match: re.Match) -> str:
    start, end = match.span("approve")
    return line[:start] + "[x] (dispatched)" + line[end:]


def _move_collision_safe(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    counter = 2
    while dest.exists():
        dest = dest_dir / f"{src.stem}-{counter}{src.suffix}"
        counter += 1
    src.rename(dest)
    return dest


def _file_capture(brain_path: Path, destination_rel: str, entry_line: str):
    dest_path = brain_path / destination_rel
    if not dest_path.parent.is_dir():
        raise ExecuteError(
            f"Destination directory does not exist: {dest_path.parent} "
            "— Execute never creates a new area/project."
        )
    if dest_path.exists():
        with dest_path.open("a") as f:
            f.write(entry_line)
    else:
        dest_path.write_text(entry_line)


def _file_capture_today(brain_path: Path, date_str: str, entry_line: str):
    """Heading-aware insert of `entry_line` as the last line of today's
    `## Today's tasks` section (before the next heading, not EOF).

    Requires <brain>/{date_str}.md to already exist — this action never
    creates it (protocols/daily-note.md, protocols/execute.md)."""
    note_path = brain_path / f"{date_str}.md"
    if not note_path.exists():
        raise ExecuteError(
            f"Today's daily note does not exist yet: {note_path} "
            "— file-capture-today never creates it."
        )
    text = note_path.read_text()
    match = re.search(r"^## Today's tasks\s*\n(.*?)(?=\n## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise ExecuteError(
            f"Today's daily note has no '## Today's tasks' section: {note_path}"
        )
    body = match.group(1)
    if body and not body.endswith("\n"):
        body += "\n"
    body += entry_line
    note_path.write_text(text[:match.start(1)] + body + text[match.end(1):])


def execute_plan(brain_path: Path, plan_path: Path, now: dt.datetime = None) -> dict:
    now = now or dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    text = plan_path.read_text()
    rows = parse_plan_rows(text)

    filed, discarded, agent_dispatched, skipped, errors = [], [], [], [], []
    lines = text.splitlines()

    for i, line in enumerate(lines):
        m = ROW_RE.match(line)
        if not m:
            continue
        row = m.groupdict()
        if row["approve"] != "[x]":
            continue  # untouched: still "[ ]" (pending) or already "[x] (done)"

        source_match = re.match(r'^inbox/raw/([^/]+)/(.+)$', row["capture"])
        if not source_match:
            errors.append(f"Row {row['n']}: unrecognised capture path {row['capture']!r}")
            continue
        source, filename = source_match.groups()
        raw_path = brain_path / row["capture"]
        if not raw_path.exists():
            errors.append(f"Row {row['n']}: Raw Capture not found at {row['capture']}")
            continue

        destination = row["destination"]
        if destination.strip().lower() == "unmatched":
            errors.append(f"Row {row['n']}: destination is still 'unmatched' — resolve Pass B before approving.")
            continue

        action_type = action_type_for(destination)
        log_id = uuid.uuid4().hex[:8]
        row["log_id"] = log_id
        try:
            if action_type == "file-capture":
                entry_line = f"- {date_str} — [[{row['capture']}]] — {row['preview']}\n"
                _file_capture(brain_path, destination, entry_line)
                outcome = f"Filed to {destination}"
                action_desc = f"Filed capture (row {row['n']}) to {destination}."
                filed.append(row["capture"])
            elif action_type == "file-capture-today":
                entry_line = f"- [ ] {row['preview']} — [[{row['capture']}]]\n"
                _file_capture_today(brain_path, date_str, entry_line)
                outcome = "Filed to today's daily note"
                action_desc = f"Filed capture (row {row['n']}) to today's daily note."
                filed.append(row["capture"])
            elif action_type == "agent-dispatched":
                outcome = f"Dispatched to {destination} (Reviewer gate pending)"
                action_desc = f"Dispatched capture (row {row['n']}) to {destination}."
                agent_dispatched.append(row)
            else:
                outcome = "Discarded — no destination filed"
                action_desc = f"Discarded capture (row {row['n']}) — no destination."
                discarded.append(row["capture"])
        except ExecuteError as e:
            errors.append(f"Row {row['n']}: {e}")
            continue

        if action_type != "agent-dispatched":
            _move_collision_safe(raw_path, brain_path / "archive" / "inbox" / source)

        entry = log_action.build_entry(
            actor="EA",
            trigger="Execute (Routine)",
            action_type=action_type,
            action=action_desc,
            confidence=row["confidence"] or "Medium",
            outcome=outcome,
            input_link=row["capture"],
            entry_id=log_id,
        )
        log_action.append_entry(brain_path, date_str, entry)

        if action_type == "agent-dispatched":
            lines[i] = _mark_dispatched(line, m)
        else:
            lines[i] = _mark_done(line, m)

    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    plan_path.write_text(new_text)

    remaining = [r for r in parse_plan_rows(new_text) if r["approve"] == "[ ]"]
    archived_to = None
    if not remaining:
        final_text = FRONTMATTER_STATUS_RE.sub("status: executed", new_text, count=1)
        plan_path.write_text(final_text)
        archived_to = _move_collision_safe(plan_path, brain_path / "archive" / "triage")

    # Bumped after processing, regardless of outcome — Execute ran and
    # checked, even when nothing was ticked this time.
    heartbeat.bump(brain_path, "Execute", now)

    return {
        "filed": filed, "discarded": discarded, "agent_dispatched": agent_dispatched,
        "errors": errors, "plan_executed": archived_to is not None, "archived_to": archived_to,
    }


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--plan", required=True, help="Path to the Triage Plan file (relative to --brain or absolute)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = brain_path / plan_path
    if not plan_path.exists():
        sys.exit(f"Triage Plan not found: {plan_path}")

    result = execute_plan(brain_path, plan_path)

    print(f"Filed: {len(result['filed'])}, discarded: {len(result['discarded'])}, dispatched: {len(result['agent_dispatched'])}, errors: {len(result['errors'])}")
    for row in result["agent_dispatched"]:
        print(f"  -> Dispatched row {row['n']} ({row['capture']}) with log_id: {row['log_id']}")
    for err in result["errors"]:
        print(f"  ! {err}")
    if result["plan_executed"]:
        print(f"All rows executed — plan archived to {result['archived_to']}")


if __name__ == "__main__":
    main()
