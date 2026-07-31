#!/usr/bin/env python3
"""One-time migration: Triage Plan table rows -> task-list Rows grouped by destination.

Implements ADR-0031's conversion step. Every still-open Plan in
`inbox/triage/` is rewritten from the old markdown table (`| # | capture |
preview | route | destination | confidence | rule | approve |`) into
`## <destination>` sections of markdown task-list items, so the approve
checkbox is tappable in Obsidian. Each Row keeps its number, destination,
route, confidence, rule identifier, preview, capture wikilink, and its
existing `[ ]` / `[x]` / `[x] (done)` / `[x] (dispatched)` state.

`archive/triage/` is deliberately untouched — an archived Plan is a
historical record of what was executed, not something anyone will ever tick
again, and rewriting it would edit the audit trail to no benefit.

Idempotent in the same sense as the other migrations here: a Plan with no
table rows left (already converted, or never had any) is a no-op, so a second
run reports nothing to do rather than mangling the converted shape. Run
manually against a live Brain with `--brain`; `--dry-run` reports what would
change and writes nothing.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import execute  # noqa: E402 — the single owner of Row parsing and group ordering
import triage  # noqa: E402 — reuses the Row builder rather than re-deriving the new shape

# The pre-ADR-0031 table row. The `rule` column is optional: it was itself a
# later addition, and a Brain can still hold a Plan written before it, whose
# rows would otherwise be silently dropped by a converter that demanded 8
# columns. A row without it converts with `—`, which is exactly what a Row
# that predates rule-identifier tracking means.
# `destination`, `confidence` and `rule` are cell-bounded (`[^|]*?`), not `.*?`:
# a row carrying an EXTRA cell would otherwise still match, with the fields
# shifted — `| … | High | e1 | extra | [ ] |` parsing as confidence `High | e1`
# and rule `extra`. Nothing is lost in that case, but the converted Row is
# garbled, so it belongs with the other malformed shapes that refuse the file.
# `preview` stays `.*?` — a pre-ADR-0031 preview was a table cell and a
# hand-edited one can legitimately contain a pipe.
OLD_ROW_RE = re.compile(
    r'^\|\s*(?P<n>\d+)\s*\|\s*\[\[(?P<capture>[^\]]+)\]\]\s*\|\s*(?P<preview>.*?)\s*\|'
    r'\s*(?P<route>Pass [AB])\s*\|\s*(?P<destination>[^|]*?)\s*\|\s*(?P<confidence>[^|]*?)\s*\|'
    r'(?:\s*(?P<rule>[^|]*?)\s*\|)?'
    r'\s*(?P<tick>\[[ x]\])(?:\s*\((?P<marker>done|dispatched)\))?\s*\|\s*$'
)
TABLE_LINE_RE = re.compile(r'^\s*\|')
TABLE_SEPARATOR_RE = re.compile(r'^\s*\|[\s\-:|]+\|\s*$')
HEADER_CELLS = {"#", "capture", "preview", "route", "destination",
                "confidence", "rule", "approve"}


class UnconvertiblePlanError(Exception):
    """A Plan holds a table line this script cannot parse.

    Raised rather than skipped, because the conversion rewrites the file from
    the rows it *did* parse: a line it silently ignored would be deleted, and
    with it the user's approval state and any Pass-B destination/confidence
    work — the one thing in a Plan that isn't recoverable from
    `inbox/raw/`. Hand-editing on a phone produces exactly these: `[X]` from
    iOS autocapitalise, a dropped trailing cell, a note typed into the approve
    cell. This is a destructive, hand-run script aimed at a live Brain, so an
    unparseable line must stop it loudly and let a human look."""


def parse_old_rows(text: str) -> list:
    """Every old-shape table row, in file order, as dicts."""
    rows = []
    for line in text.splitlines():
        m = OLD_ROW_RE.match(line)
        if m:
            rows.append(m.groupdict())
    return rows


def _is_header_line(line: str) -> bool:
    cells = [c.strip().lower() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(cell in HEADER_CELLS for cell in cells)


def unparseable_table_lines(text: str) -> list:
    """`[(line_number, line), ...]` for every table line that is neither the
    header, the separator, nor a row this script can parse."""
    offenders = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not TABLE_LINE_RE.match(line):
            continue
        if (TABLE_SEPARATOR_RE.match(line) or _is_header_line(line)
                or OLD_ROW_RE.match(line)):
            continue
        offenders.append((lineno, line.strip()))
    return offenders


def _converted_block(row: dict) -> str:
    """One old row rendered in the new shape, approval state preserved."""
    block = triage.build_row_block(
        int(row["n"]), row["capture"], row["preview"], row["route"],
        row["destination"], row["confidence"], row["rule"] or "—",
    )
    if row["tick"] == "[x]":
        block = block.replace("- [ ] ", "- [x] ", 1)
    if row["marker"]:
        task_line, rest = block.split("\n", 1)
        block = f"{task_line} ({row['marker']})\n{rest}"
    return block


def convert_plan_text(text: str) -> str:
    """Return the converted Plan, or `text` unchanged if there is nothing to
    convert (no old-shape rows — already migrated, or an empty stub).

    Non-table lines are preserved verbatim and in order, so the frontmatter,
    the H1 and any hand-written note in the Plan survive; only the table
    itself is replaced. Destination groups appear in the order they first
    occur in the file, and Rows keep their file order within a group, so a
    converted Plan reads as close to the original as the new shape allows.

    Raises `UnconvertiblePlanError` if the file holds a table line that is
    neither the header, the separator, nor a parseable row — see that
    exception. Nothing is written when it raises."""
    offenders = unparseable_table_lines(text)
    if offenders:
        raise UnconvertiblePlanError(
            "Refusing to convert — "
            f"{len(offenders)} table line(s) could not be parsed as a Triage "
            "Plan row, and converting would delete them along with their "
            "approval state. Fix them by hand and re-run:\n  "
            + "\n  ".join(f"line {lineno}: {line}" for lineno, line in offenders)
        )

    rows = parse_old_rows(text)
    if not rows:
        return text

    kept = [
        line for line in text.splitlines()
        if not TABLE_LINE_RE.match(line)
    ]
    head = "\n".join(kept).rstrip("\n")

    grouped = {}
    for row in rows:
        grouped.setdefault(row["destination"], []).append(row)

    sections = [
        f"## {destination}\n\n" + "\n\n".join(_converted_block(r) for r in group) + "\n"
        for destination, group in grouped.items()
    ]
    # Hand the result to the one owner of group ordering rather than emitting a
    # near-miss. Grouping here follows the order destinations first appear,
    # which was a regroup fixed point until ADR-0034 pinned the discard group
    # last; going through `regroup_plan()` keeps "a converted Plan is already
    # regrouped" true by construction instead of by coincidence, and immune to
    # the next ordering rule as well.
    return execute.regroup_plan(head + "\n\n" + "\n".join(sections))


def convert_plan_file(plan_path: Path, dry_run: bool = False) -> int:
    """Convert one Plan in place. Returns the number of Rows converted (0 if
    it was already in the new shape or had no rows at all). Raises
    `UnconvertiblePlanError` — before writing, so also under `--dry-run` —
    if the Plan holds a table line this script cannot parse."""
    text = plan_path.read_text()
    new_text = convert_plan_text(text)
    if new_text == text:
        return 0
    if not dry_run:
        plan_path.write_text(new_text)
    return len(parse_old_rows(text))


def migrate(brain_path: Path, dry_run: bool = False) -> dict:
    """Convert every open Plan under `inbox/triage/`.

    Returns `{"converted": {plan_filename: rows_converted},
    "refused": {plan_filename: reason}}` — Plans with nothing to do are
    omitted from both. A refused Plan is left byte-for-byte untouched and does
    not stop the other Plans converting; the caller reports it and exits
    non-zero, so a refusal is impossible to miss but one bad file doesn't
    block the rest of the backlog."""
    triage_dir = Path(brain_path) / "inbox" / "triage"
    converted, refused = {}, {}
    if not triage_dir.is_dir():
        return {"converted": converted, "refused": refused}
    for plan_path in sorted(triage_dir.glob("*.md")):
        try:
            count = convert_plan_file(plan_path, dry_run=dry_run)
        except UnconvertiblePlanError as e:
            refused[plan_path.name] = str(e)
            continue
        if count:
            converted[plan_path.name] = count
    return {"converted": converted, "refused": refused}


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would be converted; write nothing.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    result = migrate(brain_path, dry_run=args.dry_run)
    converted, refused = result["converted"], result["refused"]

    if converted:
        total = sum(converted.values())
        prefix = "Would convert" if args.dry_run else "Converted"
        print(f"{prefix} {total} row(s) across {len(converted)} open plan(s):")
        for name, count in converted.items():
            print(f"  - {name}: {count} row(s)")
    elif not refused:
        print("Nothing to convert — every open Triage Plan is already in the "
              "task-list shape (ADR-0031).")

    if refused:
        print(f"\n{len(refused)} plan(s) REFUSED and left untouched:",
              file=sys.stderr)
        for name, reason in refused.items():
            print(f"  {name}: {reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
