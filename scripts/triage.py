#!/usr/bin/env python3
"""Classify-only Triage: Pass A deterministic rule matching + Triage Plan writing.

Implements protocols/triage.md's Principle-10 constraint — this script can
write nothing capture-derived but a Triage Plan file (it also bumps its
own fixed, non-capture-derived "Triage" row in config/routine-state.md —
see protocols/triage.md). Pass A (this script) matches captures against
config/routing-rules.md, a hand-written if/then DSL (not YAML — zero
third-party deps, no parser library needed). Anything Pass A can't
resolve comes back as "unmatched"; Pass B (in-session model
classification) is the Adapter's job, not this script's.
"""

import argparse
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import execute  # noqa: E402 — reuses ROW_RE so the writer and the parser cannot drift
import heartbeat  # noqa: E402
import md_sections  # noqa: E402

IF_RE = re.compile(
    r'^if:\s*source\s*==\s*"([^"]+)"(?:\s+and\s+contains\("([^"]+)"\))?\s*$', re.IGNORECASE
)
THEN_RE = re.compile(r'^then:\s*route\s*->\s*(.+?)\s*$', re.IGNORECASE)
CONFIDENCE_RE = re.compile(r'^confidence:\s*(High|Medium|Low)\s*$', re.IGNORECASE)

# Continuation lines of a Row's task line. Four spaces, not the six that would
# align under the checkbox text: a list item's content column here is 2, so six
# spaces is exactly the indented-code-block threshold inside the item. CommonMark
# says indented code cannot interrupt a paragraph, so six would in fact render as
# text today — but only for as long as the continuation lines stay glued to the
# task line. One hand-inserted blank line and the capture wikilink would silently
# become a code block, unclickable, in the very file this change exists to make
# tappable. Four spaces is unambiguously item content under every reading.
ROW_INDENT = " " * 4

PLAN_PREAMBLE = (
    "---\n"
    "type: triage-plan\n"
    "source: {source}\n"
    "date: {date}\n"
    "status: pending\n"
    "---\n\n"
    "# Triage Plan — {source} — {date}\n"
)


def compute_rule_id(rule: dict) -> str:
    """First 8 hex chars of a SHA-1 hash over a rule's normalized
    if:/then:/confidence: text — a stable identifier for "which rule
    fired", recorded on the Action Log's `trigger` field (see
    `protocols/action-log-schema.md`).

    Built from the rule's already-parsed fields (not the raw source
    lines), so it's naturally invariant to whitespace-only edits in
    `config/routing-rules.md` — `parse_routing_rules()` already collapses
    those before this ever sees the rule. No DSL syntax change, no
    migration of existing rules required.

    Note: the reconstructed text mirrors IF_RE/THEN_RE/CONFIDENCE_RE's
    grammar above. If that grammar's shape ever changes, update both in
    the same change — a drift between them would silently change every
    existing rule's id.
    """
    if_clause = f'source == "{rule.get("source", "")}"'
    if rule.get("contains"):
        if_clause += f' and contains("{rule["contains"]}")'
    then_clause = f'route -> {rule.get("destination", "")}'
    confidence_clause = rule.get("confidence", "Medium")
    text = f"if: {if_clause} then: {then_clause} confidence: {confidence_clause}"
    normalized = " ".join(text.split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]


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
            routed.append({
                **capture,
                "destination": rule["destination"],
                "confidence": rule["confidence"],
                "rule_id": compute_rule_id(rule),
            })
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
    """Keep a preview on one line, and structurally inert.

    A preview is 60 characters of an *untrusted* capture's own body (PRD
    Principle 10), written into a Plan as its own line. Two markdown escapes
    stop that text from becoming Plan structure rather than content:

    - a leading `- ` is escaped, so the line cannot be shaped like a Row. A body
      of ``- [ ] **9** → `discard` · Pass A · High · x`` fits inside the 60-char
      cap and is otherwise a well-formed Row line;
    - `[[` is escaped, so the line cannot be shaped like a capture wikilink, and
      cannot inject a link into the Plan at all. This also keeps a hostile body
      out of `_existing_ids()`, which scans the whole Plan for
      `[[inbox/raw/…]]` — an unescaped one in a preview would suppress a real
      capture's Row as an apparent duplicate.

    Both render as the literal characters in Obsidian, so the preview reads
    unchanged. This closes the production path only; `execute._parse_blocks`
    is what makes the same text inert in a hand-edited or already-written Plan.

    The pipe replacement predates ADR-0031 (previews used to be table cells) and
    is kept: it costs nothing and a stray pipe in a preview is still noise."""
    cleaned = text.replace("\n", " ").replace("|", "/").strip()
    cleaned = cleaned.replace("[[", "\\[\\[")
    if cleaned.startswith("- "):
        cleaned = "\\" + cleaned
    return cleaned


def _preview(body: str, length: int = 60) -> str:
    text = _sanitize(body)
    return text if len(text) <= length else text[: length - 1] + "…"


def _existing_ids(text: str) -> set:
    return set(re.findall(r'\[\[(inbox/raw/[^\]]+)\]\]', text))


def _already_triaged(triage_dir: Path, source: str) -> set:
    """Every capture already listed in *any* still-open plan for this source.

    Scans all inbox/triage/*-{source}.md, not just today's — a capture
    that's still un-executed (and so still sitting in inbox/raw/) must
    not get a second row in tomorrow's plan just because Triage runs
    again on a new day. Executed plans have already moved to
    archive/triage/, so anything left here is by definition still open.
    """
    if not triage_dir.is_dir():
        return set()
    ids = set()
    for path in triage_dir.glob(f"*-{source}.md"):
        ids |= _existing_ids(path.read_text())
    return ids


def _row_id(capture: dict) -> str:
    return capture.get("path", f"inbox/raw/{capture['source']}/{capture['id']}.md")


def build_row_block(n: int, capture_link: str, preview: str, route: str,
                    destination: str, confidence: str, rule: str = "—") -> str:
    """One Row as a markdown task-list item plus its continuation lines.

    Field set and ordering are the contract (ADR-0031): the checkbox and the
    global row number first, then the destination — the two things being
    approved — with route/confidence/rule after them, and the long fields
    (preview, then the capture wikilink) demoted to continuation lines so a
    phone-width viewport still shows the checkbox and the destination.

    The capture wikilink is always the last line, and there are always exactly
    two continuation lines: `execute._read_block` requires that arity, which is
    what makes a Row block unambiguous rather than a positional guess. An empty
    preview is written as `—` rather than an empty line, both because a blank
    line would terminate the block and orphan the capture link, and because a
    one-line block is malformed by that same rule."""
    return (
        f"- [ ] **{n}** → `{destination}` · {route} · {confidence or '—'} · {rule or '—'}\n"
        f"{ROW_INDENT}{preview or '—'}\n"
        f"{ROW_INDENT}[[{capture_link}]]"
    )


def _build_row(n: int, capture: dict, route: str, destination: str, confidence: str, rule: str = "—") -> str:
    return build_row_block(
        n, _row_id(capture), _preview(capture.get("body", "")),
        route, destination, confidence, rule,
    )


def next_row_number(text: str) -> int:
    """One past the highest row number already in the Plan.

    Derived from the row numbers themselves, not from counting rows: numbering
    is global across the destination groups and must stay stable, so a Row
    keeps its number when it is re-routed into a different group and a new Row
    never reuses a number just because the groups are unevenly filled."""
    numbers = [
        int(m.group("n"))
        for m in (execute.ROW_RE.match(line) for line in text.splitlines())
        if m
    ]
    return max(numbers, default=0) + 1


def insert_row_block(text: str, destination: str, block: str) -> str:
    """Insert `block` at the end of the `## {destination}` section, creating
    that heading at end-of-file when it does not exist yet.

    Reuses `md_sections.SECTION_BODY` rather than re-deriving the pattern —
    read its docstring: the body of an *empty* section is the empty string, and
    appending to it needs the blank-line handling below rather than a
    `rstrip` + `\\n\\n` that would leave a doubled blank line under the
    heading."""
    pattern = re.compile(
        md_sections.SECTION_BODY.format(re.escape(destination)), re.MULTILINE | re.DOTALL
    )
    match = pattern.search(text)
    if not match:
        return f"{text.rstrip(chr(10))}\n\n## {destination}\n\n{block}\n"
    body = match.group(1)
    if not body.strip():
        new_body = f"\n{block}\n"
    else:
        new_body = f"{body.rstrip(chr(10))}\n\n{block}\n"
    return text[:match.start(1)] + new_body + text[match.end(1):]


def write_triage_plan(brain_path: Path, source: str, match_result: dict, date_str: str = None) -> Path:
    """Write or update inbox/triage/{date}-{source}.md.

    Idempotent: a capture already present in *any* still-open plan for
    this source (by Raw Capture path) is left untouched — its row,
    tick-state, and any Pass-B edits survive a re-run, and it never gets
    a second row just because Triage runs again on a later day while it's
    still un-executed. Only genuinely new captures get added.

    A new Row is inserted under its own `## <destination>` heading (created if
    absent), not appended at end-of-file — see ADR-0031 and `insert_row_block`.
    """
    date_str = date_str or dt.datetime.now().strftime("%Y-%m-%d")
    triage_dir = brain_path / "inbox" / "triage"
    triage_dir.mkdir(parents=True, exist_ok=True)
    plan_path = triage_dir / f"{date_str}-{source}.md"

    already_present = _already_triaged(triage_dir, source)
    plan_exists = plan_path.exists()
    text = plan_path.read_text() if plan_exists else PLAN_PREAMBLE.format(
        source=source, date=date_str
    )

    n = next_row_number(text)
    added = 0
    pending = [
        (c, "Pass A", c["destination"], c["confidence"], c.get("rule_id", "—"))
        for c in match_result.get("routed", [])
    ] + [
        (c, "Pass B", "unmatched", "—", "—")
        for c in match_result.get("unmatched", [])
    ]

    for capture, route, destination, confidence, rule in pending:
        if _row_id(capture) in already_present:
            continue
        text = insert_row_block(
            text, destination,
            _build_row(n, capture, route, destination, confidence, rule),
        )
        n += 1
        added += 1

    if not added:
        return plan_path  # nothing new — never create an empty stub, never rewrite

    plan_path.write_text(text)
    return plan_path


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--source", required=True, help="Sweep inbox/raw/<source>/ for un-triaged captures")
    return p.parse_args(argv)


def run(brain_path: Path, source: str, now: dt.datetime = None) -> dict:
    """Sweep, Pass-A classify, and write the plan — bumping Triage's own
    Last-run cell regardless of whether there was anything new to triage
    (the routine ran and checked; that's what Heartbeat needs to know).
    """
    now = now or dt.datetime.now()

    rules_path = brain_path / "config" / "routing-rules.md"
    rules = parse_routing_rules(rules_path.read_text()) if rules_path.exists() else []

    captures = read_captures(brain_path, source)
    result = {"routed": [], "unmatched": []}
    plan_path = None
    if captures:
        result = match_captures(captures, rules)
        plan_path = write_triage_plan(brain_path, source, result, date_str=now.strftime("%Y-%m-%d"))

    # Bumped after the sweep, regardless of outcome — Triage ran and
    # checked, even when there was nothing new to classify.
    heartbeat.bump(brain_path, "Triage", now)

    return {"captures_found": bool(captures), "routed": result["routed"], "unmatched": result["unmatched"], "plan_path": plan_path}


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    result = run(brain_path, args.source)

    if not result["captures_found"]:
        print(f"No Raw Captures found in inbox/raw/{args.source}/.")
        return

    print(f"Pass A: {len(result['routed'])} routed, {len(result['unmatched'])} unmatched (Pass B pending).")
    plan_path = result["plan_path"]
    if plan_path and plan_path.exists():
        print(f"Triage Plan: {plan_path}")
    else:
        print("Every capture is already tracked in an existing open Triage Plan — nothing new to add.")


if __name__ == "__main__":
    main()
