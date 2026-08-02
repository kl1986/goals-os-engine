#!/usr/bin/env python3
r"""One-time migration: Triage Plan Rows (3-line format) -> One-line Rows with nested keeper options.

Implements ADR-0036's conversion step. Every still-open Plan in
`inbox/triage/` is rewritten from the old 3-line shape into:
- One-line per Row: `- [ ] preview → \`destination\` [[capture]]`
- Nested option boxes on keeper Rows (destination `unmatched` or `?`)
- Pass A metadata (route/confidence/rule) lifted into Plan frontmatter `rules:` block

Idempotent: a Plan already converted is a no-op.
`archive/triage/` is deliberately untouched.

Run manually against a live Brain with `--brain`; `--dry-run` reports what
would change and writes nothing.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import execute  # noqa: E402
import triage  # noqa: E402

OLD_ROW_LINE_RE = re.compile(
    r'^[ \t]*- (?P<tick>\[[ x]\])'
    r'\s+\*\*(?P<n>\d+)\*\*'
    rf'\s+→\s+(?P<destinations>{execute.DESTINATION_LIST_RE})'
    r'(?:\s+(?P<meta_open>%%)?·\s+(?P<route>Pass [AB])'
    r'\s+·\s+(?P<confidence>[^·%]*?)'
    r'\s+·\s+(?P<rule>[^·%]*?)'
    r'(?(meta_open)\s*%%|))?'
    r'(?:\s+\((?P<marker>done|dispatched)\))?\s*$'
)
OLD_CAPTURE_LINE_RE = re.compile(r'^[ \t]*\[\[(?P<capture>inbox/raw/[^\]]+)\]\]$')


class UnconvertiblePlanError(Exception):
    pass


def parse_old_blocks(text: str) -> list:
    """`[(start, end, row_dict), ...]` for old-style 3-line blocks."""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        m = OLD_ROW_LINE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        # Expecting line i+1 preview, line i+2 capture link
        if i + 2 < len(lines):
            cap_m = OLD_CAPTURE_LINE_RE.match(lines[i + 2])
            if cap_m:
                preview = lines[i + 1].strip()
                capture = cap_m.group("capture")
                row = m.groupdict()
                row["preview"] = preview
                row["capture"] = capture
                row["destinations"] = execute.split_destination_list(row["destinations"])
                row["destination"] = row["destinations"][0] if row["destinations"] else ""
                row["approve"] = f"{row['tick']} ({row['marker']})" if row.get("marker") else row["tick"]
                out.append((i, i + 3, row))
                i = i + 3
                continue
        # If we couldn't parse old block cleanly
        i += 1
    return out


def convert_plan_text(text: str) -> tuple:
    """`(new_text, count)` or raises UnconvertiblePlanError."""
    # Check if already in new format
    old_blocks = parse_old_blocks(text)
    if not old_blocks:
        if re.search(r'^\s*\|', text, re.MULTILINE):
            import migrate_triage_plan_rows
            try:
                old_table_rows = migrate_triage_plan_rows.parse_old_rows(text)
                offenders = migrate_triage_plan_rows.unparseable_table_lines(text)
                if offenders:
                    raise UnconvertiblePlanError(
                        f"Refusing to convert — {len(offenders)} table line(s) could not be parsed as a Triage Plan row"
                    )
                if not old_table_rows:
                    raise UnconvertiblePlanError("Legacy table present but no rows could be parsed")
                converted_table_text = migrate_triage_plan_rows.convert_plan_text(text)
                errors = execute.check_row_blocks(converted_table_text)
                if errors:
                    raise UnconvertiblePlanError(f"Converted legacy table failed check_row_blocks: {errors[0]}")
                return converted_table_text, len(old_table_rows)
            except migrate_triage_plan_rows.UnconvertiblePlanError as e:
                raise UnconvertiblePlanError(str(e)) from e
        # Check if already valid new format or no rows
        errors = execute.check_row_blocks(text)
        if not errors:
            return text, 0
        raise UnconvertiblePlanError(f"Plan holds unparseable row lines: {errors[0]}")

    lines = text.splitlines()
    # Collect old row dicts for verification
    old_rows_snapshot = []
    pass_a_rules = []
    replacements = {}  # start -> new_block_text

    for start, end, row in old_blocks:
        old_rows_snapshot.append({
            "approve": row["approve"],
            "destinations": row["destinations"],
            "capture": row["capture"],
            "preview": row["preview"],
        })
        route = row.get("route") or "Pass B"
        rule = row.get("rule") or "—"
        conf = row.get("confidence") or "—"
        if route == "Pass A":
            pass_a_rules.append((Path(row["capture"]).name, rule, conf))

        new_block = triage.build_row_block(
            n=int(row["n"]),
            capture_link=row["capture"],
            preview=row["preview"],
            route=route,
            destination=row["destinations"],
            confidence=conf,
            rule=rule,
            tick=row.get("tick") or "[ ]",
        )
        if row.get("marker"):
            # Append marker to task line
            lines_block = new_block.splitlines()
            lines_block[0] = execute._mark_executed(lines_block[0], row["marker"])
            new_block = "\n".join(lines_block)

        replacements[start] = (end, new_block)

    # Rebuild document
    new_lines = []
    i = 0
    while i < len(lines):
        if i in replacements:
            end, new_block = replacements[i]
            new_lines.append(new_block)
            i = end
        else:
            new_lines.append(lines[i])
            i += 1

    new_text = "\n".join(new_lines) + ("\n" if text.endswith("\n") else "")

    if pass_a_rules:
        new_text = triage._update_frontmatter_rules(new_text, pass_a_rules)

    new_text = execute.regroup_plan(new_text)

    # Verification Bar
    errors = execute.check_row_blocks(new_text)
    if errors:
        raise UnconvertiblePlanError(f"Converted text failed check_row_blocks: {errors[0]}")

    new_rows = execute.parse_plan_rows(new_text)
    if len(new_rows) != len(old_rows_snapshot):
        raise UnconvertiblePlanError(f"Row count mismatch: expected {len(old_rows_snapshot)}, got {len(new_rows)}")

    new_rows_by_capture = {}
    for r in new_rows:
        new_rows_by_capture.setdefault(r["capture"], []).append(r)

    for old_r in old_rows_snapshot:
        cap = old_r["capture"]
        matching = new_rows_by_capture.get(cap, [])
        if not matching:
            raise UnconvertiblePlanError(f"Missing converted row for capture {cap!r}")
        new_r = matching.pop(0)
        for field in ("approve", "destinations", "capture", "preview"):
            if old_r[field] != new_r[field]:
                raise UnconvertiblePlanError(
                    f"Field mismatch on row {old_r['preview']!r} ({field}): expected {old_r[field]!r}, got {new_r[field]!r}"
                )

    return new_text, len(old_blocks)


def migrate_brain(brain_path: Path, dry_run: bool = False) -> dict:
    triage_dir = brain_path / "inbox" / "triage"
    converted = {}
    refused = {}
    if not triage_dir.is_dir():
        return {"converted": converted, "refused": refused}

    for plan in sorted(triage_dir.glob("*.md")):
        text = plan.read_text(encoding="utf-8")
        try:
            new_text, count = convert_plan_text(text)
            if count > 0:
                converted[plan.name] = count
                if not dry_run:
                    plan.write_text(new_text, encoding="utf-8")
        except UnconvertiblePlanError as e:
            refused[plan.name] = str(e)

    return {"converted": converted, "refused": refused}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain directory does not exist: {brain_path}")

    result = migrate_brain(brain_path, dry_run=args.dry_run)
    converted, refused = result["converted"], result["refused"]

    if converted:
        total = sum(converted.values())
        prefix = "Would convert" if args.dry_run else "Converted"
        print(f"{prefix} {total} row(s) across {len(converted)} open plan(s):")
        for name, count in converted.items():
            print(f"  - {name}: {count} row(s)")
    else:
        print("Nothing to convert — all open Plans are already in the new shape.")

    if refused:
        print(f"\n{len(refused)} plan(s) REFUSED and left untouched:", file=sys.stderr)
        for name, reason in refused.items():
            print(f"  {name}: {reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
