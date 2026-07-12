#!/usr/bin/env python3
"""Planning session Routine: the deterministic bookkeeping half.

Implements protocols/planning-session.md. The substantive work of a
session — decomposing goals, editing an area note's `## Standard` and
`## Current goals` — happens in-session, done directly by the Adapter
(the same non-scriptable split as Triage's Pass B, triage.py). This
script only does the bookkeeping every Routine-implementing script
does: append a dated entry to the area's `_memory.md` Session log, log
the session to the Action Log, and bump `Planning session`'s own row
in config/routine-state.md.
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import log_action  # noqa: E402

SESSION_LOG_HEADING = "## Session log"


def append_memory_entry(memory_path: Path, notes: str, now: dt.datetime = None) -> Path:
    """Append a dated entry under `_memory.md`'s `## Session log` heading.

    Never rewrites a prior entry — always appended after whatever's
    already there. Adds the heading itself if this Brain's memory file
    predates it (defensive; onboard.py's template always ships one).
    """
    now = now or dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    entry = f"### {date_str}\n\n{notes}\n"

    text = memory_path.read_text() if memory_path.exists() else ""
    if SESSION_LOG_HEADING not in text:
        text = text.rstrip("\n") + f"\n\n{SESSION_LOG_HEADING}\n" if text else f"{SESSION_LOG_HEADING}\n"

    memory_path.write_text(text.rstrip("\n") + "\n\n" + entry)
    return memory_path


def run(brain_path: Path, area_note: str, area_agent: str, notes: str,
        outcome: str, confidence: str = "High", now: dt.datetime = None) -> dict:
    """Run the bookkeeping half of one Planning session.

    `area_note` is the area note's Brain-relative path (e.g.
    "areas/work/Work.md") — its parent directory is where `_memory.md`
    lives, and it's used as-is as the Action Log entry's input link.
    `confidence` is the Area agent's own self-assessed confidence for
    this session (action-log-schema.md) — the Adapter passes whatever
    the conversation actually warranted, never a fixed value.
    """
    now = now or dt.datetime.now()

    memory_path = (brain_path / area_note).parent / "_memory.md"
    append_memory_entry(memory_path, notes, now=now)

    heartbeat.bump(brain_path, "Planning session", now)

    entry = log_action.build_entry(
        actor=area_agent,
        trigger="Planning session (Routine)",
        action_type="planning-session",
        action=notes,
        confidence=confidence,
        outcome=outcome,
        input_link=area_note,
        time_str=now.strftime("%H:%M"),
    )
    log_path = log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)

    return {"memory_path": memory_path, "log_path": log_path}


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--area-note", required=True, help='Brain-relative path, e.g. "areas/work/Work.md"')
    p.add_argument("--area-agent", required=True, help='The Area agent\'s name, e.g. "Will"')
    p.add_argument("--notes", required=True, help="One-paragraph summary of what the session decided")
    p.add_argument("--outcome", required=True, help="Short outcome, e.g. 'Updated Current goals.'")
    p.add_argument("--confidence", required=True, choices=log_action.CONFIDENCE_LEVELS,
                    help="The Area agent's own self-assessed confidence for this session")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    result = run(
        brain_path, args.area_note, args.area_agent, args.notes, args.outcome,
        confidence=args.confidence,
    )
    print(f"Memory entry appended: {result['memory_path']}")
    print(f"Action Log entry appended: {result['log_path']}")
    print("Planning session Routine bumped in config/routine-state.md.")


if __name__ == "__main__":
    main()
