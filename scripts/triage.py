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
# Reuses ROW_RE (so the writer and the parser cannot drift) and regroup_plan
# (so the Row shape's owner also owns where a Row sits). One-directional:
# execute imports heartbeat/log_action/md_sections and nothing here, so there
# is no cycle.
import execute  # noqa: E402
import heartbeat  # noqa: E402
import md_sections  # noqa: E402

IF_RE = re.compile(
    r'^if:\s*source\s*==\s*"([^"]+)"(?:\s+and\s+contains\("([^"]+)"\))?\s*$', re.IGNORECASE
)
THEN_RE = re.compile(r'^then:\s*route\s*->\s*(.+?)\s*$', re.IGNORECASE)
# `then: discard` — a rule may say a capture is noise, not just where it goes.
# Until ADR-0034 the rule format could only name a file destination, so the
# single most repetitive judgement in the Brain ("this sender is noise") was
# the one thing Pass A could not express: 25 of 32 rows on the 23/07 email plan
# were discards, every one decided by a model, every one due to recur. The
# safety property is unchanged and is what makes this affordable — a `discard`
# rule proposes a Row that still needs an explicit tick, and a discarded
# capture is archived, not deleted (protocols/capture.md), so the worst case
# is one unticked Row and a capture recoverable from archive/inbox/.
THEN_DISCARD_RE = re.compile(r'^then:\s*discard\s*$', re.IGNORECASE)
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
    # A `then: discard` rule hashes over `discard`, matching the grammar
    # THEN_DISCARD_RE accepts. `then: route -> discard` deliberately hashes to
    # the *same* id: both parse to the same destination and Execute treats them
    # identically (`action_type_for`), so they are one rule written two ways,
    # and the id answers "which rule fired" — a question about behaviour.
    destination = rule.get("destination", "")
    then_clause = "discard" if destination == "discard" else f"route -> {destination}"
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
        if THEN_DISCARD_RE.match(line) and current is not None:
            # The literal Execute already understands (`action_type_for`), so
            # a Pass A discard and a Pass B discard are the same Row downstream.
            current["destination"] = "discard"
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
    - `→` is replaced with `->` so a preview cannot inject the Row destination
      delimiter.

    Both render as the literal characters in Obsidian, so the preview reads
    unchanged. This closes the production path only; `execute._parse_blocks`
    is what makes the same text inert in a hand-edited or already-written Plan.

    The pipe replacement predates ADR-0031 (previews used to be table cells) and
    is kept: it costs nothing and a stray pipe in a preview is still noise."""
    cleaned = text.replace("\n", " ").replace("|", "/").replace("→", "->").strip()
    cleaned = cleaned.replace("[[", "\\[\\[")
    if cleaned.startswith("- "):
        cleaned = "\\" + cleaned
    return cleaned


def _preview(body: str, length: int = 60) -> str:
    text = _sanitize(body)
    return text if len(text) <= length else text[: length - 1] + "…"


# An email capture's body opens with `**From:**` / `**Subject:**` headers
# (the email plugin's `build_capture_body()`), so a blind first-N-characters
# preview spends its whole budget on the From line — address included — and
# truncates mid-word before the Subject ever appears:
#
#     **From:** "ICAS / CA Weekly" <Update@update.icas.com> **Sub…
#
# The subject is the one field a person triages on, and it was invisible on
# every email Row in the Brain. These pull the two fields out and compose
# `Sender — Subject` instead, dropping the labels and the raw address, which
# buys back roughly forty characters of the thing worth reading.
EMAIL_FROM_RE = re.compile(r'^\*\*From:\*\*\s*(.+?)\s*$', re.MULTILINE)
EMAIL_SUBJECT_RE = re.compile(r'^\*\*Subject:\*\*\s*(.+?)\s*$', re.MULTILINE)
EMAIL_ADDRESS_RE = re.compile(r'\s*<[^>]*>\s*')
# Sender is capped well below the whole so a long display name can never crowd
# out the subject; the subject takes whatever is left.
EMAIL_SENDER_LEN = 28
EMAIL_PREVIEW_LEN = 90


def _email_preview(body: str):
    """`Sender — Subject` for an email capture, or None if it doesn't look like
    one (in which case the caller falls back to the generic preview).

    The extracted fields are still untrusted capture content — a `Subject:`
    header is attacker-controlled in exactly the way a body is — so they go
    through `_sanitize()` and the length cap the same as any other preview.
    Principle 10 is enforced here, not assumed from the header shape."""
    subject_match = EMAIL_SUBJECT_RE.search(body)
    if not subject_match:
        return None
    subject = _sanitize(subject_match.group(1))
    from_match = EMAIL_FROM_RE.search(body)
    sender = _sanitize(EMAIL_ADDRESS_RE.sub("", from_match.group(1))).strip('" ') if from_match else ""
    if sender and len(sender) > EMAIL_SENDER_LEN:
        sender = sender[: EMAIL_SENDER_LEN - 1] + "…"
    composed = f"**{sender}** — {subject}" if sender else subject
    if len(composed) > EMAIL_PREVIEW_LEN:
        composed = composed[: EMAIL_PREVIEW_LEN - 1] + "…"
    return composed


def structured_preview(body: str, source: str = None):
    """The preview derived from a capture's *structure* rather than from the
    first N characters of its text, or None where no such derivation exists.

    Separated from `preview_for()` so a caller that only has the capture file
    — `refresh_triage_previews.py` — can tell "I can do better than what is
    written" from "I would merely produce something different". The generic
    fallback is position-based and depends on exactly the body Triage was
    handed at stamp time, which is not recoverable from the file alone."""
    if source == "email":
        return _email_preview(body)
    return None


def preview_for(body: str, source: str = None) -> str:
    """The preview line for a capture, source-aware where it pays to be."""
    return structured_preview(body, source) or _preview(body)


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


DEFAULT_KEEPER_OPTIONS = [
    ("Act on this", None),
    ("Area", "areas/home/_inbox.md"),
    ("Project", "projects/goals-os/_inbox.md"),
    ("Bin it instead", None),
]


def build_row_block(n: int, capture_link: str, preview: str, route: str = "Pass B",
                    destination: str = "unmatched", confidence: str = "—", rule: str = "—",
                    tick: str = "[ ]") -> str:
    """One Row as a markdown task-list item plus any continuation option lines.

    Target shape (ADR-0036):
    - [ ] <preview> → `<destination>` [[<capture_link>]]

    Keepers (destination `?` or `unmatched`) carry option boxes as nested checkboxes:
        - [ ] Act on this
        - [ ] Area · `areas/home/_inbox.md`
        - [ ] Project · `projects/goals-os/_inbox.md`
        - [ ] Bin it instead
    """
    destinations = [destination] if isinstance(destination, str) else list(destination)
    task_line = f"- {tick} {preview or '—'} → {execute.render_destination_list(destinations)} [[{capture_link}]]"

    is_keeper = any(d.strip().lower() in ("unmatched", "?") for d in destinations)
    if not is_keeper:
        return task_line

    lines = [task_line]
    for label, val in DEFAULT_KEEPER_OPTIONS:
        if val:
            lines.append(f"{ROW_INDENT}- [ ] {label} · `{val}`")
        else:
            lines.append(f"{ROW_INDENT}- [ ] {label}")

    return "\n".join(lines)


def _build_row(n: int, capture: dict, route: str, destination: str, confidence: str, rule: str = "—") -> str:
    return build_row_block(
        n, _row_id(capture),
        preview_for(capture.get("body", ""), capture.get("source")),
        route, destination, confidence, rule,
    )


def next_row_number(text: str) -> int:
    """One past the highest row number already in the Plan."""
    rows = execute.parse_plan_rows(text)
    if not rows:
        return 1
    return max((int(r["n"]) for r in rows if r.get("n", "").isdigit()), default=len(rows)) + 1


def insert_row_block(text: str, destination: str, block: str) -> str:
    """Insert `block` at the end of the `## {destination}` section, creating
    that heading at end-of-file when it does not exist yet."""
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


def _update_frontmatter_rules(text: str, pass_a_rules: list) -> str:
    """Ensure Pass A rule metadata is stored in frontmatter under rules: block."""
    if not pass_a_rules:
        return text

    existing_rules = execute._parse_plan_rules_frontmatter(text)
    for fname, r_id, conf in pass_a_rules:
        existing_rules[fname] = {"rule": r_id, "confidence": conf or "High"}

    rules_lines = ["rules:"]
    for fname, meta in existing_rules.items():
        rules_lines.append(f"  {fname}:")
        rules_lines.append(f"    rule: {meta['rule']}")
        rules_lines.append(f"    confidence: {meta['confidence']}")
    rules_text = "\n".join(rules_lines)

    fm_match = re.match(r'^(---\n.*?\n)(---(?:\n|\Z))', text, re.DOTALL)
    if not fm_match:
        return text

    header, footer = fm_match.groups()
    if re.search(r'^rules:\s*', header, re.MULTILINE):
        new_header = re.sub(r'^rules:\s*\n.*?(?=\n[a-z0-9_-]+:|\Z)', rules_text + "\n", header, flags=re.MULTILINE | re.DOTALL)
    else:
        new_header = header.rstrip("\n") + "\n" + rules_text + "\n"

    return new_header + text[fm_match.end(1):]


def write_triage_plan(brain_path: Path, source: str, match_result: dict, date_str: str = None) -> Path:
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

    pass_a_additions = []
    for capture, route, destination, confidence, rule in pending:
        if _row_id(capture) in already_present:
            continue
        text = insert_row_block(
            text, destination,
            _build_row(n, capture, route, destination, confidence, rule),
        )
        if route == "Pass A":
            capture_fname = Path(_row_id(capture)).name
            pass_a_additions.append((capture_fname, rule, confidence))
        n += 1
        added += 1

    if not plan_exists and not added:
        return plan_path

    if pass_a_additions:
        text = _update_frontmatter_rules(text, pass_a_additions)

    if f"## {execute.INSTRUCTIONS_HEADING}" not in text:
        text = text.rstrip("\n") + f"\n\n## {execute.INSTRUCTIONS_HEADING}\n\n{execute.DEFAULT_INSTRUCTIONS_PROSE}\n"

    new_text = execute.regroup_plan(text)
    if not plan_exists or new_text != plan_path.read_text():
        plan_path.write_text(new_text)
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
