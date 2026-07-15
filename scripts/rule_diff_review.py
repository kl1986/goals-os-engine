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
    r'^-\s*\[(?P<mark>[ xX])\]\s*(?:\((?P<state>applied|logged)\)\s*)?(?P<label>Approve|Reject)\s*$',
    re.MULTILINE,
)
FRONTMATTER_STATUS_RE = re.compile(r'^status:\s*\S+\s*$', re.MULTILINE)
FRONTMATTER_RULESET_RE = re.compile(r'^ruleset:\s*(\S+)\s*$', re.MULTILINE)


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


def _is_malformed(diff: dict) -> str:
    """Return an error reason string, or "" if the diff is well-formed."""
    if not diff["rule_block"].strip():
        return "missing rule block"
    if not diff["why"]:
        return "missing '**Why:**' line"
    if len(diff["evidence"]) < 2:
        return "fewer than 2 evidence links"
    if diff["approve_ticked"] and diff["reject_ticked"]:
        return "both Approve and Reject ticked"
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

    diffs = parse_batch(text)
    applied, rejected, errors = [], [], []
    replacements = []  # (start, end, new_text) — applied back-to-front so offsets stay valid

    for diff in diffs:
        if _is_processed(diff):
            continue
        if not _is_decided(diff):
            continue  # still undecided — leave it for a future run

        reason = _is_malformed(diff)
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
