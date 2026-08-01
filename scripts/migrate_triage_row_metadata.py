#!/usr/bin/env python3
"""One-time migration: wrap a Triage Row's classification metadata in `%%…%%`.

Implements ADR-0033's conversion step. Every still-open Plan in
`inbox/triage/` has its Row lines rewritten so the `route · confidence · rule`
triple sits inside an Obsidian comment and disappears from the reading
surface, leaving the checkbox, the row number and the destinations — the
things being approved — as the whole visible line.

Nothing else about a Row changes: its number, destinations, route,
confidence, rule identifier, tick state, executed marker, preview and capture
wikilink are all preserved verbatim, and continuation lines are never
touched. Grouping and heading structure are left exactly as found — this
migration does not call `regroup_plan()`, because moving a user's Rows around
is not what they asked for by running it.

Strictly this migration is optional: the `%%` is optional on read, so an
unconverted Plan parses and executes unchanged. It exists because Execute's
write path deliberately does not normalise Row lines, so an already-open Plan
would otherwise keep showing metadata until Triage next wrote to it.

`archive/triage/` is deliberately untouched — an archived Plan is a historical
record of what was executed, not something anyone will tick again, and
rewriting it would edit the audit trail to no benefit.

Idempotent: a Row already wrapped is left alone, so a second run reports
nothing to do rather than double-wrapping. A Plan holding a Row line this
script cannot read is **refused whole and left untouched**, naming the line —
the same discipline as `migrate_triage_plan_rows.py`, and for the same reason:
a partial rewrite of a file the user is mid-approval on is worse than none.

Run manually against a live Brain with `--brain`; `--dry-run` reports what
would change and writes nothing.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import execute  # noqa: E402 — ROW_RE is the single owner of the Row shape

# A Row line whose metadata is not yet wrapped. Deliberately built from
# execute.DESTINATION_LIST_RE rather than re-describing the destination field,
# so this cannot drift from the shape Execute actually reads.
UNWRAPPED_ROW_RE = re.compile(
    r'^(?P<head>[ \t]*- \[[ x]\]\s+\*\*\d+\*\*\s+→\s+'
    rf'{execute.DESTINATION_LIST_RE})'
    r'\s+(?P<meta>·\s+Pass [AB]\s+·[^%]*?)'
    r'(?P<marker>\s+\((?:done|dispatched)\))?\s*$'
)
# Anything that starts like a Row but is neither already-wrapped nor cleanly
# unwrapped — the case that must refuse rather than be skipped silently.
ROW_START_RE = re.compile(r'^[ \t]*- \[[ x]\]\s+\*\*\d+\*\*\s+→')


# An all-dash metadata segment: Pass B, no confidence, no rule. It states
# nothing the absence of the segment does not (ADR-0036), so it is stripped
# rather than wrapped. A Pass A segment carries a real rule id and is kept.
EMPTY_META_RE = re.compile(
    r'\s*%%·\s*Pass B\s*·\s*[—-]\s*·\s*[—-]\s*%%'
)


def strip_empty_metadata(text: str):
    """`(new_text, stripped)` — remove zero-information metadata segments."""
    out, stripped = [], 0
    for line in text.splitlines():
        if execute.ROW_RE.match(line):
            new_line = EMPTY_META_RE.sub("", line)
            if new_line != line:
                stripped += 1
                line = new_line
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), stripped


def convert_text(text: str):
    """`(new_text, converted_count, problem_line)`. Pure — no I/O.

    `problem_line` is the first Row-shaped line that is neither already
    wrapped nor convertible; when it is set the caller must discard
    `new_text` and refuse the file.
    """
    text, _ = strip_empty_metadata(text)
    out, converted = [], 0
    for line in text.splitlines():
        m = UNWRAPPED_ROW_RE.match(line)
        if m:
            marker = m.group("marker") or ""
            out.append(f"{m.group('head')} %%{m.group('meta').strip()}%%{marker}")
            converted += 1
            continue
        if ROW_START_RE.match(line) and not execute.ROW_RE.match(line):
            return text, 0, line
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), converted, None


def migrate(brain_path: Path, dry_run: bool = False) -> dict:
    triage_dir = brain_path / "inbox" / "triage"
    converted, refused = {}, {}
    if not triage_dir.is_dir():
        return {"converted": converted, "refused": refused}

    for plan in sorted(triage_dir.glob("*.md")):
        text = plan.read_text(encoding="utf-8")
        new_text, count, problem = convert_text(text)
        if problem:
            refused[plan.name] = f"unreadable Row line: {problem.strip()!r}"
            continue
        # Keyed on the text actually changing, not on the wrap count: a Plan
        # whose Rows only needed their empty metadata stripped has nothing to
        # wrap, and an earlier cut keyed on `count` skipped exactly those —
        # which today is 123 of the Brain's 124 Rows, i.e. the whole point.
        if new_text == text:
            continue
        converted[plan.name] = count or len(
            [line for line in text.splitlines() if EMPTY_META_RE.search(line)])
        if not dry_run:
            plan.write_text(new_text, encoding="utf-8")
    return {"converted": converted, "refused": refused}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain", required=True, help="Path to the Brain (contains inbox/triage/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change and write nothing.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    result = migrate(brain_path, dry_run=args.dry_run)
    converted, refused = result["converted"], result["refused"]

    if converted:
        total = sum(converted.values())
        prefix = "Would wrap" if args.dry_run else "Wrapped"
        print(f"{prefix} the metadata on {total} row(s) across {len(converted)} open plan(s):")
        for name, count in converted.items():
            print(f"  - {name}: {count} row(s)")
    elif not refused:
        print("Nothing to convert — every open Triage Plan already hides its "
              "Row metadata (ADR-0033).")

    if refused:
        print(f"\n{len(refused)} plan(s) REFUSED and left untouched:", file=sys.stderr)
        for name, reason in refused.items():
            print(f"  {name}: {reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
