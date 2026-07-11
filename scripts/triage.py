#!/usr/bin/env python3
"""Classify-only Triage: Pass A deterministic rule matching + Triage Plan writing.

Implements protocols/triage.md's Principle-10 constraint — this script can
write nothing but a Triage Plan file. Pass A (this script) matches
captures against config/routing-rules.md, a hand-written if/then DSL (not
YAML — zero third-party deps, no parser library needed). Anything Pass A
can't resolve comes back as "unmatched"; Pass B (in-session model
classification) is the Adapter's job, not this script's.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

IF_RE = re.compile(
    r'^if:\s*source\s*==\s*"([^"]+)"(?:\s+and\s+contains\("([^"]+)"\))?\s*$', re.IGNORECASE
)
THEN_RE = re.compile(r'^then:\s*route\s*->\s*(.+?)\s*$', re.IGNORECASE)
CONFIDENCE_RE = re.compile(r'^confidence:\s*(High|Medium|Low)\s*$', re.IGNORECASE)

TRIAGE_PLAN_HEADER = ["#", "capture", "preview", "route", "destination", "confidence", "approve"]


def parse_routing_rules(text: str) -> list:
    """Parse the if/then/confidence blocks in a routing-rules.md file.

    Lines starting with `#` (commented-out starter examples) are skipped.
    A rule is complete once it has both an `if:` and a `then:` line;
    `confidence:` is optional and defaults to "Medium".
    """
    rules = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = IF_RE.match(line)
        if m:
            if current and "destination" in current:
                rules.append(current)
            current = {"source": m.group(1), "contains": m.group(2)}
            continue
        m = THEN_RE.match(line)
        if m and current is not None:
            current["destination"] = m.group(1)
            continue
        m = CONFIDENCE_RE.match(line)
        if m and current is not None:
            current["confidence"] = m.group(1).capitalize()
            continue
    if current and "destination" in current:
        rules.append(current)
    for rule in rules:
        rule.setdefault("confidence", "Medium")
    return rules


def _rule_matches(capture: dict, rule: dict) -> bool:
    if capture.get("source") != rule.get("source"):
        return False
    keyword = rule.get("contains")
    if keyword:
        haystack = f"{capture.get('title', '')} {capture.get('body', '')}".lower()
        if keyword.lower() not in haystack:
            return False
    return True


def match_captures(captures: list, rules: list) -> dict:
    """Pass A: deterministic rule matching. Pure — no file I/O."""
    routed, unmatched = [], []
    for capture in captures:
        rule = next((r for r in rules if _rule_matches(capture, r)), None)
        if rule:
            routed.append({**capture, "destination": rule["destination"], "confidence": rule["confidence"]})
        else:
            unmatched.append(capture)
    return {"routed": routed, "unmatched": unmatched}


def read_captures(brain_path: Path, source: str) -> list:
    """Read every Raw Capture currently in inbox/raw/<source>/."""
    source_dir = brain_path / "inbox" / "raw" / source
    if not source_dir.is_dir():
        return []

    captures = []
    for path in sorted(source_dir.glob("*.md")):
        text = path.read_text()
        id_match = re.search(r'^id:\s*(.+)$', text, re.MULTILINE)
        title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        body_start = title_match.end() if title_match else 0
        body = text[body_start:].strip()
        captures.append({
            "id": id_match.group(1).strip() if id_match else path.stem,
            "source": source,
            "title": title_match.group(1).strip() if title_match else path.stem,
            "body": body,
            "path": f"inbox/raw/{source}/{path.name}",
        })
    return captures


def _sanitize(text: str) -> str:
    """Keep a table cell on one line and pipe-safe."""
    return text.replace("\n", " ").replace("|", "/").strip()


def _preview(body: str, length: int = 60) -> str:
    text = _sanitize(body)
    return text if len(text) <= length else text[: length - 1] + "…"


def _existing_ids(text: str) -> set:
    return set(re.findall(r'\[\[(inbox/raw/[^\]]+)\]\]', text))


def _row_id(capture: dict) -> str:
    return capture.get("path", f"inbox/raw/{capture['source']}/{capture['id']}.md")


def _build_row(n: int, capture: dict, route: str, destination: str, confidence: str) -> str:
    return (
        f"| {n} | [[{_row_id(capture)}]] | {_preview(capture.get('body', ''))} "
        f"| {route} | {destination} | {confidence} | [ ] |"
    )


def write_triage_plan(brain_path: Path, source: str, match_result: dict, date_str: str = None) -> Path:
    """Write or update inbox/triage/{date}-{source}.md.

    Idempotent: captures already present (by Raw Capture path) are left
    untouched — their row, tick-state, and any Pass-B edits survive a
    re-run. Only genuinely new captures get appended.
    """
    date_str = date_str or dt.datetime.now().strftime("%Y-%m-%d")
    triage_dir = brain_path / "inbox" / "triage"
    triage_dir.mkdir(parents=True, exist_ok=True)
    plan_path = triage_dir / f"{date_str}-{source}.md"

    existing_text = plan_path.read_text() if plan_path.exists() else ""
    already_present = _existing_ids(existing_text)

    new_rows = []
    if plan_path.exists():
        row_count = len(re.findall(r'^\|\s*\d+\s*\|', existing_text, re.MULTILINE))
    else:
        row_count = 0

    for capture in match_result.get("routed", []):
        if _row_id(capture) in already_present:
            continue
        row_count += 1
        new_rows.append(_build_row(row_count, capture, "Pass A", capture["destination"], capture["confidence"]))

    for capture in match_result.get("unmatched", []):
        if _row_id(capture) in already_present:
            continue
        row_count += 1
        new_rows.append(_build_row(row_count, capture, "Pass B", "unmatched", "—"))

    if not plan_path.exists():
        header = (
            "---\n"
            "type: triage-plan\n"
            f"source: {source}\n"
            f"date: {date_str}\n"
            "status: pending\n"
            "---\n\n"
            f"# Triage Plan — {source} — {date_str}\n\n"
            f"| {' | '.join(TRIAGE_PLAN_HEADER)} |\n"
            f"|{'---|' * len(TRIAGE_PLAN_HEADER)}\n"
        )
        plan_path.write_text(header + "\n".join(new_rows) + ("\n" if new_rows else ""))
    elif new_rows:
        with plan_path.open("a") as f:
            f.write("\n".join(new_rows) + "\n")

    return plan_path


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--source", required=True, help="Sweep inbox/raw/<source>/ for un-triaged captures")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    rules_path = brain_path / "config" / "routing-rules.md"
    rules = parse_routing_rules(rules_path.read_text()) if rules_path.exists() else []

    captures = read_captures(brain_path, args.source)
    if not captures:
        print(f"No Raw Captures found in inbox/raw/{args.source}/.")
        return

    result = match_captures(captures, rules)
    plan_path = write_triage_plan(brain_path, args.source, result)

    print(f"Pass A: {len(result['routed'])} routed, {len(result['unmatched'])} unmatched (Pass B pending).")
    print(f"Triage Plan: {plan_path}")


if __name__ == "__main__":
    main()
