#!/usr/bin/env python3
"""Weekly rule-learning pass (Phase 5 — Learning).

Implements protocols/rule-learning.md: scans the Action Log for
`corrected — <detail>` entries and, once an Adapter's LLM has grouped a
recurring pattern (>=2 similar corrections against the same underlying
miss), writes a new rule-diff proposal into inbox/rule-diffs/, in the
exact format protocols/rule-diff-review.md defines.

Pure-Python vs Adapter-judgement split (mirrors scripts/triage.py's Pass
A/B split):

  - find_corrections()      — pure. Scans every log/*.md file for
                               `corrected — <detail>` entries and returns
                               them with a ready-to-cite evidence link.
                               No judgement involved.
  - propose_group() / run() — pure. Given an Adapter-supplied group
                               (a slug, a proposed rule block, a
                               rationale, and >=2 evidence links already
                               judged to point at the same underlying
                               miss), enforces the >=2 threshold, checks
                               the de-dup rules, writes the diff file,
                               logs a `propose-rule-diff` entry, and
                               bumps this Routine's row in
                               config/routine-state.md.

Deciding *which* scanned corrections share an underlying miss, and
drafting the rule block + rationale for a group, is genuine semantic
judgement — that step runs in-session at the Adapter layer
(adapters/claude-code/skills/rule-learning/), never in this script.
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import log_action  # noqa: E402
import rule_diff_review  # noqa: E402

ENTRY_HEADER_RE = re.compile(r'^###\s+(\d{2}:\d{2})\s+—\s+(.+?)\s*$', re.MULTILINE)
FIELD_RE = re.compile(r'^-\s*\*\*([^:*]+):\*\*\s*(.*)$', re.MULTILINE)
CORRECTED_RE = re.compile(r'^corrected\s*[—-]\s*(.+)$', re.IGNORECASE)
DATE_FROM_FILENAME_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')
DIFF_NUMBER_RE = re.compile(r'^###\s+Diff\s+(\d+)\s+—', re.MULTILINE)
STATUS_PENDING_RE = re.compile(r'^status:\s*pending\s*$', re.MULTILINE)


class RuleLearningError(Exception):
    pass


def parse_log_entries(text: str, date_str: str) -> list:
    """Every Action Log entry in one day's file, as a dict of its fields.

    Pure — no I/O. Mirrors action-log-schema.md's `### HH:MM — <action
    type>` heading + `- **field:** value` bullet-list shape exactly.
    """
    headers = list(ENTRY_HEADER_RE.finditer(text))
    entries = []
    for i, header in enumerate(headers):
        body_start = header.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[body_start:body_end]
        fields = {m.group(1).strip().lower(): m.group(2).strip() for m in FIELD_RE.finditer(body)}
        entries.append({
            "date": date_str,
            "time": header.group(1),
            "action_type": header.group(2).strip(),
            **fields,
        })
    return entries


def find_corrections(brain_path: Path, since: dt.date = None) -> list:
    """Every `corrected — <detail>` Action Log entry across log/*.md.

    Pure — no judgement, just extraction. Each returned dict carries the
    entry's fields plus `detail` (the free-text payload after "corrected
    — ") and `link` (the exact `log/YYYY-MM-DD#HH:MM — <action type>`
    text an Evidence line cites, per protocols/rule-diff-review.md).
    """
    log_dir = brain_path / "log"
    if not log_dir.is_dir():
        return []

    corrections = []
    for path in sorted(log_dir.glob("*.md")):
        date_match = DATE_FROM_FILENAME_RE.match(path.stem)
        if not date_match:
            continue
        date_str = date_match.group(1)
        if since and dt.date.fromisoformat(date_str) < since:
            continue

        for entry in parse_log_entries(path.read_text(), date_str):
            feedback = entry.get("feedback", "")
            match = CORRECTED_RE.match(feedback)
            if not match:
                continue
            corrections.append({
                **entry,
                "detail": match.group(1).strip(),
                "link": f"log/{date_str}#{entry['time']} — {entry['action_type']}",
            })
    return corrections


def _open_batch_diff_keys(brain_path: Path, ruleset: str) -> set:
    """diff_key() of every diff in a still-`pending` batch file for this ruleset."""
    inbox_dir = brain_path / "inbox" / "rule-diffs"
    keys = set()
    if not inbox_dir.is_dir():
        return keys
    for path in inbox_dir.glob(f"*-{ruleset}.md"):
        text = path.read_text()
        if not STATUS_PENDING_RE.search(text):
            continue
        for diff in rule_diff_review.parse_batch(text):
            if diff["rule_block"].strip():
                keys.add(rule_diff_review.diff_key(ruleset, diff["rule_block"]))
    return keys


def _rejected_diff_keys(brain_path: Path, ruleset: str) -> set:
    """diff_key() of every diff recorded as Reject in an archived batch for this ruleset."""
    archive_dir = brain_path / "archive" / "rule-diffs"
    keys = set()
    if not archive_dir.is_dir():
        return keys
    for path in archive_dir.glob(f"*-{ruleset}.md"):
        for diff in rule_diff_review.parse_batch(path.read_text()):
            if diff["reject_ticked"] and diff["rule_block"].strip():
                keys.add(rule_diff_review.diff_key(ruleset, diff["rule_block"]))
    return keys


def _already_in_target_file(brain_path: Path, ruleset: str, rule_block: str) -> bool:
    """Covers "already applied" — an approved diff lives verbatim in the target file."""
    target_path = brain_path / "config" / f"{ruleset}.md"
    if not target_path.exists():
        return False
    return rule_block.strip() in target_path.read_text()


def is_duplicate(brain_path: Path, ruleset: str, rule_block: str) -> bool:
    """protocols/rule-diff-review.md's de-dup key, checked against all three
    documented cases: already pending, already applied, already rejected.
    """
    key = rule_diff_review.diff_key(ruleset, rule_block)
    if key in _open_batch_diff_keys(brain_path, ruleset):
        return True
    if _already_in_target_file(brain_path, ruleset, rule_block):
        return True
    if key in _rejected_diff_keys(brain_path, ruleset):
        return True
    return False


def _next_diff_number(text: str) -> int:
    numbers = [int(n) for n in DIFF_NUMBER_RE.findall(text)]
    return max(numbers, default=0) + 1


def _format_diff_section(n: int, slug: str, rule_block: str, why: str, evidence_links: list) -> str:
    evidence = ", ".join(f"[[{link}]]" for link in evidence_links)
    block = rule_block.strip("\n")
    return (
        f"### Diff {n} — {slug}\n\n"
        f"```\n{block}\n```\n\n"
        f"**Why:** {why}\n\n"
        f"**Evidence:** {evidence}\n\n"
        "- [ ] Approve\n"
        "- [ ] Reject\n"
    )


def write_diff(brain_path: Path, ruleset: str, slug: str, rule_block: str, why: str,
               evidence_links: list, date_str: str = None) -> Path:
    """Append a new diff section to inbox/rule-diffs/{date}-{ruleset}.md,
    creating the batch file (with frontmatter) if it doesn't exist yet —
    exactly matching protocols/rule-diff-review.md's file format.
    """
    date_str = date_str or dt.datetime.now().strftime("%Y-%m-%d")
    diffs_dir = brain_path / "inbox" / "rule-diffs"
    diffs_dir.mkdir(parents=True, exist_ok=True)
    batch_path = diffs_dir / f"{date_str}-{ruleset}.md"

    if batch_path.exists():
        existing = batch_path.read_text()
        section = _format_diff_section(_next_diff_number(existing), slug, rule_block, why, evidence_links)
        if existing and not existing.endswith("\n"):
            existing += "\n"
        batch_path.write_text(existing + "\n" + section)
    else:
        section = _format_diff_section(1, slug, rule_block, why, evidence_links)
        header = (
            "---\n"
            "type: rule-diff-batch\n"
            f"ruleset: {ruleset}\n"
            f"date: {date_str}\n"
            "status: pending\n"
            "---\n\n"
            f"# Rule diffs — {ruleset} — {date_str}\n\n"
        )
        batch_path.write_text(header + section)

    return batch_path


def _rel(path: Path, brain_path: Path) -> str:
    try:
        return path.relative_to(brain_path).as_posix()
    except ValueError:
        return path.as_posix()


def propose_group(brain_path: Path, ruleset: str, slug: str, rule_block: str, why: str,
                   evidence: list, confidence: str = "Medium", now: dt.datetime = None) -> dict:
    """Evaluate one Adapter-supplied similarity group and, if it clears the
    >=2 threshold and isn't a duplicate, write the diff and log a
    `propose-rule-diff` Action Log entry.

    `evidence` is a list of evidence-link strings (protocols/rule-diff-
    review.md's `log/YYYY-MM-DD#HH:MM — <action type>` shape, no
    brackets) — typically the `link` values of >=2 find_corrections()
    entries the Adapter judged to share an underlying miss.
    """
    now = now or dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    if len(evidence) < 2:
        return {"written": False, "reason": "fewer than 2 justifying corrections"}

    if is_duplicate(brain_path, ruleset, rule_block):
        return {"written": False, "reason": "duplicate — already pending, applied, or rejected"}

    batch_path = write_diff(brain_path, ruleset, slug, rule_block, why, evidence, date_str=date_str)
    input_link = _rel(batch_path, brain_path)

    entry = log_action.build_entry(
        actor="EA",
        trigger="Rule learning (Routine)",
        action_type="propose-rule-diff",
        action=f"Proposed rule diff ({slug}) for config/{ruleset}.md.",
        confidence=confidence,
        outcome=f"Diff written to {input_link}",
        input_link=input_link,
        entry_id=uuid4().hex[:8],
        time_str=now.strftime("%H:%M"),
    )
    log_action.append_entry(brain_path, date_str, entry)

    return {"written": True, "batch_path": batch_path}


def run(brain_path: Path, ruleset: str, groups: list, now: dt.datetime = None) -> dict:
    """Process every Adapter-supplied group for one ruleset, then bump this
    Routine's row in config/routine-state.md regardless of outcome — the
    pass ran and checked, even when nothing new qualified (same
    convention as scripts/triage.py's run()).
    """
    now = now or dt.datetime.now()
    written, skipped = [], []

    for group in groups:
        result = propose_group(
            brain_path, ruleset,
            slug=group["slug"], rule_block=group["rule_block"], why=group["why"],
            evidence=group["evidence"], confidence=group.get("confidence", "Medium"),
            now=now,
        )
        if result["written"]:
            written.append(result)
        else:
            skipped.append({**group, "reason": result["reason"]})

    heartbeat.bump(brain_path, "Rule learning", now)

    return {"written": written, "skipped": skipped}


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    sub = p.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser(
        "scan", help="Print every corrected Action Log entry as JSON, for the Adapter's similarity pass."
    )
    scan_p.add_argument("--since", default=None, help="YYYY-MM-DD — only scan entries from this date onward")

    propose_p = sub.add_parser(
        "propose", help="Write diffs for Adapter-supplied similarity groups, and bump the Rule learning routine."
    )
    propose_p.add_argument("--ruleset", required=True, help="Target rule-set slug, e.g. routing-rules")
    propose_p.add_argument(
        "--groups-file", required=True,
        help="Path to a JSON file: a list of {slug, rule_block, why, evidence, confidence?}",
    )

    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    if args.command == "scan":
        since = dt.date.fromisoformat(args.since) if args.since else None
        corrections = find_corrections(brain_path, since=since)
        print(json.dumps(corrections, indent=2, default=str))
        return

    if args.command == "propose":
        groups_path = Path(args.groups_file)
        if not groups_path.exists():
            sys.exit(f"Groups file not found: {groups_path}")
        groups = json.loads(groups_path.read_text())

        result = run(brain_path, args.ruleset, groups)

        print(f"Written: {len(result['written'])}, skipped: {len(result['skipped'])}")
        for skip in result["skipped"]:
            print(f"  ! {skip.get('slug', '?')}: {skip['reason']}")


if __name__ == "__main__":
    main()
