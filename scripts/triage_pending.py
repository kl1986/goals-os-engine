#!/usr/bin/env python3
"""Report how many Triage rows are sitting unexecuted in open Triage Plans.

The nudge half of the Triage automation gap. A launchd job already runs
Pass A nightly, so "Triage is overdue" stopped being the useful signal —
`config/routine-state.md` reads green every morning while the queue grows.
The failure mode this reports on is the one that replaced it: plans are
produced on schedule, but their rows are never executed, so captures pile
up invisibly (email went 11 -> 32 -> 55 unmatched across three days while
every run looked healthy).

So this counts *rows awaiting action*, not *days since the last run*, and
splits them by what each row is actually waiting for:

- **awaiting Pass B** — the row's destination is still `unmatched`, so no
  routing rule matched and only model judgement can resolve it. Pass A
  cannot clear these no matter how often it runs.
- **awaiting Execute** — the row is routed but the `approve` box is
  unticked, so it is waiting on a human tick.

Pure Python, zero LLM calls. Reads only; never writes, never executes a
row. Designed to be cheap enough to run on every session start.

Usage:
    python3 triage_pending.py --brain PATH [--format line|report] [--quiet-if-zero]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import execute  # noqa: E402 — reuses ROW_RE/parse_plan_rows so the two cannot drift

UNRESOLVED_DESTINATIONS = {"unmatched", "?"}
CLOSED_STATUSES = {"executed", "archived", "done", "complete", "completed"}


def is_open_plan(text: str) -> bool:
    """A plan is open unless its frontmatter marks it executed/archived.

    Deliberately permissive: anything that isn't explicitly finished counts
    as open, so a new status value shows up in the nudge rather than
    silently vanishing from it.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("status:"):
            return stripped.split(":", 1)[1].strip().lower() not in CLOSED_STATUSES
        if stripped.startswith("#"):
            break  # past the frontmatter; no status key means open
    return True


def row_is_pending(row: dict) -> bool:
    """Unticked rows with valid actionable destinations only."""
    if not row["approve"].strip().startswith("[ ]"):
        return False
    dest = row.get("destination", "").strip()
    return bool(dest) and dest not in ("—", "-")


def row_awaits_pass_b(row: dict) -> bool:
    return row.get("destination", "").strip().lower() in UNRESOLVED_DESTINATIONS


def scan_plans(triage_dir: Path) -> dict:
    """Count pending rows across every open plan, grouped by source.

    Returns {"awaiting_pass_b": int, "awaiting_execute": int,
             "migration_required": int, "plans": int,
             "by_source": {source: (pass_b, execute)},
             "oldest": str|None}.
    """
    awaiting_pass_b = 0
    awaiting_execute = 0
    migration_required = 0
    plans = 0
    by_source = {}
    oldest = None

    if not triage_dir.is_dir():
        return {"awaiting_pass_b": 0, "awaiting_execute": 0, "migration_required": 0,
                "plans": 0, "by_source": {}, "oldest": None}

    for plan in sorted(triage_dir.glob("*.md")):
        try:
            text = plan.read_text(encoding="utf-8")
        except OSError:
            continue
        if not is_open_plan(text):
            continue

        parts = plan.stem.split("-", 3)
        source = parts[3] if len(parts) == 4 else plan.stem

        if execute.requires_migration(text):
            migration_required += 1
            plans += 1
            by_source.setdefault(source, (0, 0))
            if oldest is None:
                oldest = plan.stem
            continue

        rows = [r for r in execute.parse_plan_rows(text) if row_is_pending(r)]
        if not rows:
            continue
        plans += 1
        pass_b = sum(1 for r in rows if row_awaits_pass_b(r))
        to_execute = len(rows) - pass_b
        awaiting_pass_b += pass_b
        awaiting_execute += to_execute

        prev = by_source.get(source, (0, 0))
        by_source[source] = (prev[0] + pass_b, prev[1] + to_execute)
        if oldest is None:
            oldest = plan.stem

    return {"awaiting_pass_b": awaiting_pass_b, "awaiting_execute": awaiting_execute,
            "migration_required": migration_required, "plans": plans,
            "by_source": by_source, "oldest": oldest}


def format_line(counts: dict) -> str:
    total = counts["awaiting_pass_b"] + counts["awaiting_execute"]
    mig = counts.get("migration_required", 0)
    if total == 0 and mig == 0:
        return "Triage: nothing pending."
    bits = []
    if counts["awaiting_pass_b"]:
        bits.append(f"{counts['awaiting_pass_b']} awaiting Pass B")
    if counts["awaiting_execute"]:
        bits.append(f"{counts['awaiting_execute']} awaiting Execute")
    if mig:
        bits.append(f"{mig} plan(s) require migration")
    line = (f"Triage: {total} row(s) pending across {counts['plans']} open plan(s) "
            f"— {', '.join(bits)}.")
    if counts["oldest"]:
        line += f" Oldest: {counts['oldest']}."
    return line


def format_report(counts: dict) -> str:
    lines = [format_line(counts)]
    for source, (pass_b, to_exec) in sorted(counts["by_source"].items()):
        lines.append(f"  {source:<10} {pass_b:>4} awaiting Pass B, {to_exec:>4} awaiting Execute")
    if counts.get("migration_required"):
        lines.append("  Legacy plans require migration (run python3 scripts/migrate_triage_rows_one_line.py).")
    if counts["awaiting_pass_b"]:
        lines.append("  Pass A cannot clear the Pass B rows — they need routing rules "
                     "(config/routing-rules.md) or a session.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain", required=True, help="Path to the Brain.")
    parser.add_argument("--format", choices=["line", "report"], default="line",
                        help="line: one-line nudge (default). report: per-source breakdown.")
    parser.add_argument("--quiet-if-zero", action="store_true",
                        help="Print nothing when there is nothing pending — for a "
                             "session-start hook that should stay silent on a clean queue.")
    args = parser.parse_args(argv)

    counts = scan_plans(Path(args.brain).expanduser() / "inbox" / "triage")
    total = counts["awaiting_pass_b"] + counts["awaiting_execute"] + counts.get("migration_required", 0)
    if total == 0 and args.quiet_if_zero:
        return 0
    print(format_report(counts) if args.format == "report" else format_line(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
