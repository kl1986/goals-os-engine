#!/usr/bin/env python3
"""One-off migration: config/routine-state.md from 3 columns to 2.

Ticket 07 moves cadence out of the Brain and into the Engine's manifest
(protocols/routines.md) — the old `Routine | Cadence | Last run` shape
duplicated cadence per-Brain, a second source of truth. This script
rewrites an existing Brain's routine-state.md to `Routine | Last run`
only, preserving any non-"never" last-run values. Idempotent: no-ops if
the file is already 2-column or absent.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from heartbeat import parse_table  # noqa: E402

NEW_HEADER = "| Routine | Last run |"
NEW_SEPARATOR = "|---|---|"


def migrate(text: str) -> tuple:
    """Return (new_text, changed). `changed` is False if already migrated."""
    rows = parse_table(text)
    if not rows:
        return text, False

    if "Cadence" not in rows[0]:
        return text, False  # already 2-column

    lines = text.splitlines()
    table_start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("|"))
    table_end = table_start + 1  # header
    while table_end < len(lines) and lines[table_end].strip().startswith("|"):
        table_end += 1

    new_table = [NEW_HEADER, NEW_SEPARATOR]
    for row in rows:
        new_table.append(f"| {row['Routine']} | {row['Last run']} |")

    new_lines = lines[:table_start] + new_table + lines[table_end:]
    return "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), True


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    path = brain_path / "config" / "routine-state.md"
    if not path.exists():
        print(f"{path} does not exist — nothing to migrate.")
        return

    text = path.read_text()
    new_text, changed = migrate(text)
    if not changed:
        print(f"{path} is already 2-column — no-op.")
        return

    path.write_text(new_text)
    print(f"Migrated {path} to the 2-column (Routine | Last run) shape.")


if __name__ == "__main__":
    main()
