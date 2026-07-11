#!/usr/bin/env python3
"""Append one Action Log entry to a Brain's log/ folder.

Implements protocols/action-log-schema.md (v0). Runtime-agnostic — callable
from any Adapter, not just the Claude Code one. See that Protocol doc for
field semantics.
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

CONFIDENCE_LEVELS = ("High", "Medium", "Low")


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain (contains log/)")
    p.add_argument("--actor", required=True)
    p.add_argument("--trigger", required=True)
    p.add_argument("--action-type", required=True)
    p.add_argument("--action", required=True, help="One-line description of what was done")
    p.add_argument("--confidence", required=True, choices=CONFIDENCE_LEVELS)
    p.add_argument("--outcome", required=True)
    p.add_argument("--input-link", default="—")
    p.add_argument("--feedback", default="—")
    p.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today")
    p.add_argument("--time", default=None, help="HH:MM 24h, defaults to now")
    return p.parse_args(argv)


def build_entry(actor, trigger, action_type, action, confidence, outcome,
                 input_link="—", feedback="—", time_str=None):
    time_str = time_str or dt.datetime.now().strftime("%H:%M")
    return (
        f"### {time_str} — {action_type}\n\n"
        f"- **actor:** {actor}\n"
        f"- **trigger:** {trigger}\n"
        f"- **input link:** {input_link}\n"
        f"- **action type:** {action_type}\n"
        f"- **action:** {action}\n"
        f"- **confidence:** {confidence}\n"
        f"- **outcome:** {outcome}\n"
        f"- **feedback:** {feedback}\n"
    )


def append_entry(brain_path: Path, date_str: str, entry: str) -> Path:
    log_dir = brain_path / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{date_str}.md"

    if not log_file.exists():
        log_file.write_text(f"# Action Log — {date_str}\n\n{entry}")
    else:
        with log_file.open("a") as f:
            f.write(f"\n{entry}")

    return log_file


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    now = dt.datetime.now()
    date_str = args.date or now.strftime("%Y-%m-%d")
    time_str = args.time or now.strftime("%H:%M")

    entry = build_entry(
        actor=args.actor, trigger=args.trigger, action_type=args.action_type,
        action=args.action, confidence=args.confidence, outcome=args.outcome,
        input_link=args.input_link, feedback=args.feedback, time_str=time_str,
    )
    log_file = append_entry(brain_path, date_str, entry)
    print(f"Appended entry to {log_file}")


if __name__ == "__main__":
    main()
