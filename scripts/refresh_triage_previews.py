#!/usr/bin/env python3
"""Regenerate the preview line of every Row in the open Triage Plans.

A Row's preview is **derived data** — it is produced from the Raw Capture at
write time and read by nobody but a human. When the way it is derived improves,
already-written Rows keep the old one forever, because Triage never rewrites an
existing Row (that is the idempotency guarantee protecting ticks and hand
edits). This re-derives them in place.

The motivating case: an email capture's body opens with `**From:**` /
`**Subject:**` headers, so the old blind first-60-characters preview spent its
whole budget on the From line, address included, and truncated before the
subject:

    **From:** "ICAS / CA Weekly" <Update@update.icas.com> **Sub…

The subject — the one field anyone triages on — was invisible on every email
Row. `triage.preview_for()` now composes `Sender — Subject` instead; this
applies that to the Rows already written.

Only the preview line changes. The task line (tick state, executed marker, row
number, destinations, route/confidence/rule) and the capture wikilink are
untouched, so nothing this script does can alter what Execute will do — it is
a cosmetic rewrite of the one line that exists to be read.

A Row is skipped, not failed, when its Raw Capture is gone (already executed
and archived, or moved) or when re-derivation yields nothing. A Plan holding a
Row block that cannot be read is refused whole and left untouched, naming the
row — same discipline as the other migrations here.

`archive/triage/` is never touched: an archived Plan is a record of what was
executed, and re-deriving its previews would edit the audit trail to no
benefit.

Idempotent: a Row whose preview already matches the current derivation is left
alone, so a second run reports nothing to do.

Run manually with `--brain`; `--dry-run` reports what would change and writes
nothing.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import execute  # noqa: E402
import triage  # noqa: E402

FRONTMATTER_RE = re.compile(r'^---\n.*?\n---\n', re.DOTALL)


def capture_body(capture_path: Path) -> str:
    """A Raw Capture's body — everything after its frontmatter block.

    Matches what Triage itself passes to the preview builder, so a refreshed
    preview is identical to what a fresh write would have produced rather than
    merely similar."""
    return FRONTMATTER_RE.sub("", capture_path.read_text(encoding="utf-8"), count=1)


def refresh_text(text: str, brain_path: Path, source: str):
    """`(new_text, refreshed, skipped, problem_row)`. Reads captures; does not write."""
    lines = text.splitlines()
    refreshed = skipped = 0
    for start, end, row, problem in execute._scan_blocks(text):
        if problem:
            return text, 0, 0, row["n"]
        # The block is [task line, preview line(s)…, capture link]. The preview
        # is everything between, which the writer always emits as exactly one
        # line; anything else is left alone rather than collapsed.
        if end - start != 3:
            skipped += 1
            continue
        capture_path = brain_path / row["capture"]
        if not capture_path.exists():
            skipped += 1
            continue
        # Only re-derive where there is a *structured* derivation to re-derive
        # from — today, an email's From/Subject headers. The generic preview is
        # the first N characters of the body Triage was handed at stamp time,
        # and this script only has the capture file: stripping its frontmatter
        # leaves the `# Title` heading that the stamped body did not have, so
        # a generic refresh would rewrite good previews into worse ones
        # (`Send a message…` → `# Send a message…`). Refresh what improves,
        # skip what would merely differ.
        new_preview = triage.structured_preview(capture_body(capture_path), source)
        if not new_preview:
            skipped += 1
            continue
        indent = re.match(r'^[ \t]*', lines[start + 1]).group(0)
        candidate = f"{indent}{new_preview}"
        if candidate == lines[start + 1]:
            continue
        lines[start + 1] = candidate
        refreshed += 1
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), refreshed, skipped, None


def refresh(brain_path: Path, dry_run: bool = False) -> dict:
    triage_dir = brain_path / "inbox" / "triage"
    refreshed, skipped, refused = {}, {}, {}
    if not triage_dir.is_dir():
        return {"refreshed": refreshed, "skipped": skipped, "refused": refused}

    for plan in sorted(triage_dir.glob("*.md")):
        # `<date>-<source>.md` — the source decides how a preview is derived.
        source = plan.stem.split("-", 3)[-1]
        text = plan.read_text(encoding="utf-8")
        new_text, count, n_skipped, problem = refresh_text(text, brain_path, source)
        if problem:
            refused[plan.name] = f"row {problem}: malformed Row block"
            continue
        if n_skipped:
            skipped[plan.name] = n_skipped
        if not count:
            continue
        refreshed[plan.name] = count
        if not dry_run:
            plan.write_text(new_text, encoding="utf-8")
    return {"refreshed": refreshed, "skipped": skipped, "refused": refused}


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

    result = refresh(brain_path, dry_run=args.dry_run)
    refreshed, skipped, refused = result["refreshed"], result["skipped"], result["refused"]

    if refreshed:
        total = sum(refreshed.values())
        prefix = "Would refresh" if args.dry_run else "Refreshed"
        print(f"{prefix} the preview on {total} row(s) across {len(refreshed)} open plan(s):")
        for name, count in refreshed.items():
            print(f"  - {name}: {count} row(s)")
    elif not refused:
        print("Nothing to refresh — every Row's preview already matches the "
              "current derivation.")

    if skipped:
        total = sum(skipped.values())
        print(f"\nSkipped {total} row(s) whose Raw Capture is missing or whose "
              f"block is not the standard three lines:")
        for name, count in skipped.items():
            print(f"  - {name}: {count} row(s)")

    if refused:
        print(f"\n{len(refused)} plan(s) REFUSED and left untouched:", file=sys.stderr)
        for name, reason in refused.items():
            print(f"  {name}: {reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
