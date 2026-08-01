#!/usr/bin/env python3
"""Review surface for proposed rule-set diffs (Phase 5 — Learning).

Implements protocols/rule-diff-review.md: parses
inbox/rule-diffs/{date}-{ruleset-slug}.md batch files, applies
Approve/Reject decisions (append to the target rule-set file for Approve,
log-only for Reject), logs an Action Log entry per decision, and archives
the batch file once every diff in it is decided. This script never
proposes a diff itself — it only reviews/applies ones already written by
hand or (once built) ticket 07's rule-learning proposal script, which
must produce files conforming exactly to the format this Protocol
defines.
"""

import argparse
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent))
import log_action  # noqa: E402

DIFF_HEADER_RE = re.compile(r'^###\s+Diff\s+(\d+)\s+—\s+(.+?)\s*$', re.MULTILINE)
CODE_BLOCK_RE = re.compile(r'```\n(.*?)\n```', re.DOTALL)
WHY_RE = re.compile(r'^\*\*Why:\*\*\s*(.+)$', re.MULTILINE)
EVIDENCE_LINE_RE = re.compile(r'^\*\*Evidence:\*\*\s*(.+)$', re.MULTILINE)
EVIDENCE_LINK_RE = re.compile(r'\[\[([^\]]+)\]\]')
CHECKBOX_RE = re.compile(
    r'^-[ \t]*\[(?P<mark>[ xX])\][ \t]*(?:\((?P<state>applied|logged)\)[ \t]*)?(?P<label>Approve|Reject)[ \t]*$',
    re.MULTILINE,
)
FRONTMATTER_STATUS_RE = re.compile(r'^status:\s*\S+\s*$', re.MULTILINE)
FRONTMATTER_RULESET_RE = re.compile(r'^ruleset:\s*(\S+)\s*$', re.MULTILINE)
FRONTMATTER_EVIDENCE_BASIS_RE = re.compile(r'^evidence-basis:\s*(\S+)\s*$', re.MULTILINE)
# Bases whose evidence is Raw Captures rather than Action Log corrections,
# validated identically. `bootstrap-raw-captures` was the one-off seeding
# pass; `sender-marked-noise` is a user ticking "Always bin <sender>" on a
# Triage Plan (ADR-0035), whose evidence is the captures from that sender
# sitting in the Plan they ticked it on. Distinct names because the record
# should say which one produced a rule, identical validation because the
# question — do these captures exist? — is the same.
RAW_CAPTURE_EVIDENCE_BASES = {"bootstrap-raw-captures", "sender-marked-noise"}
ROUTING_IF_RE = re.compile(r'^if:\s*source\s*==\s*"[^"]+"', re.IGNORECASE)
ROUTING_THEN_RE = re.compile(r'^then:\s*route\s*->\s*.+$', re.IGNORECASE)


class RuleDiffReviewError(Exception):
    pass


def diff_key(ruleset: str, rule_block: str) -> str:
    """Content-addressed de-dup key for a proposed rule-diff.

    See protocols/rule-diff-review.md's "De-dup key" section — ticket 07's
    proposal-writer must compute this before writing a new diff and skip
    proposing if it matches a diff already pending, already applied
    (present verbatim in the target file), or already rejected (recorded
    in an archived batch file for this ruleset).
    """
    normalized = rule_block.strip()
    return hashlib.sha256(f"{ruleset}\n{normalized}".encode("utf-8")).hexdigest()[:12]


def parse_batch(text: str) -> list:
    """Return every diff section in a batch file as a dict, in file order.

    Pure — no I/O. Each dict carries enough to both act on the diff
    (rule_block, evidence, decision state) and to locate + rewrite its
    checkbox line in-place (checkbox_start/checkbox_end, absolute offsets
    into `text`) once a decision has been applied.
    """
    headers = list(DIFF_HEADER_RE.finditer(text))
    diffs = []
    for i, header in enumerate(headers):
        body_start = header.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[body_start:body_end]

        code_match = CODE_BLOCK_RE.search(body)
        why_match = WHY_RE.search(body)
        evidence_match = EVIDENCE_LINE_RE.search(body)
        evidence = EVIDENCE_LINK_RE.findall(evidence_match.group(1)) if evidence_match else []

        checkboxes = {m.group("label"): m for m in CHECKBOX_RE.finditer(body)}
        approve = checkboxes.get("Approve")
        reject = checkboxes.get("Reject")

        def _offsets(match):
            if match is None:
                return None, None
            return body_start + match.start(), body_start + match.end()

        approve_start, approve_end = _offsets(approve)
        reject_start, reject_end = _offsets(reject)

        diffs.append({
            "n": header.group(1),
            "slug": header.group(2).strip(),
            "rule_block": code_match.group(1) if code_match else "",
            "why": why_match.group(1).strip() if why_match else "",
            "evidence": evidence,
            "approve_ticked": bool(approve) and approve.group("mark").lower() == "x",
            "approve_state": approve.group("state") if approve else None,
            "approve_start": approve_start,
            "approve_end": approve_end,
            "reject_ticked": bool(reject) and reject.group("mark").lower() == "x",
            "reject_state": reject.group("state") if reject else None,
            "reject_start": reject_start,
            "reject_end": reject_end,
        })
    return diffs


def _is_decided(diff: dict) -> bool:
    """Ticked, either box, regardless of whether it's been processed yet."""
    return diff["approve_ticked"] or diff["reject_ticked"]


def _is_processed(diff: dict) -> bool:
    return diff["approve_state"] is not None or diff["reject_state"] is not None


def _has_live_routing_rule(target_path: Path) -> bool:
    """Return whether a routing-rules file contains an uncommented rule.

    Bootstrap evidence is intentionally only supported for the initial empty
    routing-rules file. The reader's native DSL is an if/then pair, so this
    stays narrow rather than trying to infer emptiness for arbitrary rule-set
    syntaxes.
    """
    current_has_if = False
    for raw_line in target_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ROUTING_IF_RE.match(line):
            current_has_if = True
        elif current_has_if and ROUTING_THEN_RE.match(line):
            return True
    return False


def _wikilink_path(brain_path: Path, link: str) -> Path:
    """Resolve a Brain-relative wikilink target, accepting omitted `.md`."""
    path_part = link.split("#", 1)[0]
    path = brain_path / path_part
    return path if path.suffix else path.with_suffix(".md")


def _is_malformed(diff: dict, evidence_basis: str, brain_path: Path) -> str:
    """Return an error reason string, or "" if the diff is well-formed."""
    if not diff["rule_block"].strip():
        return "missing rule block"
    if not diff["why"]:
        return "missing '**Why:**' line"
    if len(diff["evidence"]) < 2:
        return "fewer than 2 evidence links"
    if diff["approve_ticked"] and diff["reject_ticked"]:
        return "both Approve and Reject ticked"
    if evidence_basis in RAW_CAPTURE_EVIDENCE_BASES:
        if any(not link.startswith("inbox/raw/") for link in diff["evidence"]):
            return "raw-capture evidence must link only to inbox/raw/ captures"
        if any(not _wikilink_path(brain_path, link).is_file() for link in diff["evidence"]):
            return "raw-capture evidence links a Raw Capture that does not exist"
    elif evidence_basis == "corrections":
        if any(not link.startswith("log/") for link in diff["evidence"]):
            return "normal evidence must link only to Action Log corrections"
        for link in diff["evidence"]:
            _, separator, heading = link.partition("#")
            log_path = _wikilink_path(brain_path, link)
            if not separator or not heading or not log_path.is_file():
                return "normal evidence links an Action Log correction that does not exist"
            entry = log_path.read_text().split(f"### {heading}", 1)
            if len(entry) != 2:
                return "normal evidence links an Action Log correction that does not exist"
            entry_body = entry[1].split("\n### ", 1)[0]
            if not re.search(r'^- \*\*feedback:\*\* corrected\s+—\s+.+$', entry_body, re.MULTILINE):
                return "normal evidence must link to an Action Log correction"
    return ""


def _append_rule_block(target_path: Path, rule_block: str):
    if not target_path.exists():
        raise RuleDiffReviewError(f"Target rule-set file does not exist: {target_path}")
    existing = target_path.read_text()
    if existing and not existing.endswith("\n"):
        existing += "\n"
    block = rule_block.strip("\n")
    target_path.write_text(existing + f"\n```\n{block}\n```\n")


def _move_collision_safe(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    counter = 2
    while dest.exists():
        dest = dest_dir / f"{src.stem}-{counter}{src.suffix}"
        counter += 1
    src.rename(dest)
    return dest


def _rel(path: Path, brain_path: Path) -> str:
    try:
        return path.relative_to(brain_path).as_posix()
    except ValueError:
        return path.as_posix()


def apply_batch(brain_path: Path, batch_path: Path, now: dt.datetime = None) -> dict:
    """Process every decided-but-unprocessed diff in a batch file.

    Approve appends the diff's rule block to config/{ruleset}.md
    (additive-only) and logs an `apply-rule-diff` entry. Reject writes no
    file but still logs a `reject-rule-diff` entry. Diffs already
    processed (marker present) are skipped — idempotent. A malformed or
    doubly-ticked diff is reported as an error and left untouched, same
    as the rest of this run. Once every diff in the file is processed,
    the batch file flips to `status: resolved` and moves to
    archive/rule-diffs/.
    """
    now = now or dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    text = batch_path.read_text()

    ruleset_match = FRONTMATTER_RULESET_RE.search(text)
    if not ruleset_match:
        raise RuleDiffReviewError(f"Batch file missing 'ruleset:' frontmatter: {batch_path}")
    ruleset = ruleset_match.group(1)
    target_path = brain_path / "config" / f"{ruleset}.md"
    evidence_basis_match = FRONTMATTER_EVIDENCE_BASIS_RE.search(text)
    evidence_basis = evidence_basis_match.group(1) if evidence_basis_match else "corrections"
    diffs = parse_batch(text)
    if evidence_basis not in {"corrections"} | RAW_CAPTURE_EVIDENCE_BASES:
        raise RuleDiffReviewError(f"Unknown evidence basis: {evidence_basis}")
    if evidence_basis in RAW_CAPTURE_EVIDENCE_BASES:
        if ruleset != "routing-rules":
            raise RuleDiffReviewError("Raw-capture evidence is only supported for routing-rules")
        if not target_path.exists():
            raise RuleDiffReviewError(f"Target rule-set file does not exist: {target_path}")
    # The empty-file guard belongs to `bootstrap-raw-captures` alone: that
    # basis exists to seed rules into a Brain that has none, so finding live
    # rules means the bootstrap has already happened and re-running it would
    # duplicate the seed. `sender-marked-noise` is the opposite case by
    # construction — the user is ticking a sender on a Brain that is already
    # running, and will almost always have rules — so applying the guard to it
    # would make the checkbox work exactly once, on an empty config.
    if evidence_basis == "bootstrap-raw-captures":
        if _has_live_routing_rule(target_path) and not any(_is_processed(diff) for diff in diffs):
            raise RuleDiffReviewError("Bootstrap raw-capture evidence requires an empty routing-rules.md")

    applied, rejected, errors = [], [], []
    replacements = []  # (start, end, new_text) — applied back-to-front so offsets stay valid

    for diff in diffs:
        if _is_processed(diff):
            continue
        if not _is_decided(diff):
            continue  # still undecided — leave it for a future run

        reason = _is_malformed(diff, evidence_basis, brain_path)
        if reason:
            errors.append(f"Diff {diff['n']}: {reason} — refusing to process.")
            continue

        entry_id = uuid4().hex[:8]
        input_link = _rel(batch_path, brain_path)

        if diff["approve_ticked"]:
            _append_rule_block(target_path, diff["rule_block"])
            action_type = "apply-rule-diff"
            action_desc = f"Applied rule diff (Diff {diff['n']} — {diff['slug']}) to config/{ruleset}.md."
            outcome = f"Rule appended to config/{ruleset}.md"
            applied.append(diff["n"])
            marker, label = "applied", "Approve"
            start, end = diff["approve_start"], diff["approve_end"]
        else:
            action_type = "reject-rule-diff"
            action_desc = f"Rejected rule diff (Diff {diff['n']} — {diff['slug']}) — no change to config/{ruleset}.md."
            outcome = f"No write — config/{ruleset}.md unchanged"
            rejected.append(diff["n"])
            marker, label = "logged", "Reject"
            start, end = diff["reject_start"], diff["reject_end"]

        entry = log_action.build_entry(
            actor="EA",
            trigger="Rule diff review",
            action_type=action_type,
            action=action_desc,
            confidence="High",
            outcome=outcome,
            input_link=input_link,
            entry_id=entry_id,
        )
        log_action.append_entry(brain_path, date_str, entry)

        replacements.append((start, end, f"- [x] ({marker}) {label}"))

    for start, end, new in sorted(replacements, key=lambda r: r[0], reverse=True):
        text = text[:start] + new + text[end:]

    batch_path.write_text(text)

    remaining = [d for d in parse_batch(text) if not _is_processed(d)]
    archived_to = None
    if diffs and not remaining:
        final_text = FRONTMATTER_STATUS_RE.sub("status: resolved", text, count=1)
        batch_path.write_text(final_text)
        archived_to = _move_collision_safe(batch_path, brain_path / "archive" / "rule-diffs")

    return {
        "applied": applied, "rejected": rejected, "errors": errors,
        "batch_resolved": archived_to is not None, "archived_to": archived_to,
    }


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--batch", required=True, help="Path to the rule-diff batch file (relative to --brain or absolute)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    batch_path = Path(args.batch)
    if not batch_path.is_absolute():
        batch_path = brain_path / batch_path
    if not batch_path.exists():
        sys.exit(f"Rule-diff batch file not found: {batch_path}")

    result = apply_batch(brain_path, batch_path)

    print(f"Applied: {len(result['applied'])}, rejected: {len(result['rejected'])}, errors: {len(result['errors'])}")
    for err in result["errors"]:
        print(f"  ! {err}")
    if result["batch_resolved"]:
        print(f"All diffs resolved — batch archived to {result['archived_to']}")


if __name__ == "__main__":
    main()
