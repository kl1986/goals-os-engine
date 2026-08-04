#!/usr/bin/env python3
"""The "Stop asking me about these" section: turn a repeat sender into a rule.

Implements ADR-0035. Two verbs:

  --write   (re)build the section at the foot of every open email Triage Plan:
            one unticked checkbox per sender that still costs a decision.
  --apply   turn each ticked checkbox into a proposed rule diff in
            `inbox/rule-diffs/`, then mark that checkbox `(proposed)`.

Why it exists: the same senders recur every morning — 6 LinkedIn Job Alerts
and 2 Well-Man Cars in a single 12-row Plan — and until now the only way to
stop being asked was to hand-write a rule in `config/routing-rules.md`, which
means leaving the page, knowing the file exists, and knowing the syntax. The
decision "this sender is always noise" is one the user is *already making*
while triaging; this puts it one tap from where they make it.

**The checkboxes are not Rows.** They carry no row number, no destination and
no capture link, so `execute.ROW_RE` cannot match them and Execute can neither
act on them nor be confused by them. They are prose under a heading, which
`regroup_plan` preserves and ranks last.

**A tick proposes; it does not apply.** The tick is a direct human
instruction, but it still lands in `inbox/rule-diffs/` rather than in
`config/routing-rules.md`, because that surface already owns rule changes:
additive-only writes, the de-dup key that stops a rejected rule being
re-proposed forever, an Action Log entry, and archival. Writing the rule
directly would be one tap cheaper and would bypass all four.

A sender is offered only when it is not already covered: `is_duplicate()`
checks the rule this checkbox *would* propose against every pending, applied
and rejected diff, so an approved sender stops appearing and a rejected one
never comes back.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import execute  # noqa: E402
import rule_learning  # noqa: E402
import triage  # noqa: E402

RULESET = "routing-rules"
FROM_RE = re.compile(r'^\*\*From:\*\*\s*(.+?)\s*$', re.MULTILINE)
ADDRESS_RE = re.compile(r'<([^>]+)>')
# `- [ ] ⚡️ Always bin **Name** `address` · 8 today` — deliberately not
# Row-shaped. The `· N today` tally is optional and must be tolerated here:
# `build_section()` emits it whenever a sender appears more than once, and an
# earlier cut of this pattern stopped at the closing backtick, so exactly the
# senders worth making a rule for were the ones whose ticks were silently
# ignored. Anything trailing is captured and preserved rather than reparsed.
CHECKBOX_RE = re.compile(
    r'^- (?P<tick>\[[ x]\])\s+⚡️\s+Always bin\s+\*\*(?P<name>[^*]+)\*\*\s+'
    r'`(?P<address>[^`]+)`(?P<tally>[^()\n]*?)'
    r'(?P<marker>\s+\(proposed[^\n]*\))?\s*$'
)
# Rows whose destination still costs a decision. A Row already routed to a real
# destination by a rule is not a candidate — its sender is handled.
UNRESOLVED = {"unmatched", "discard", "?"}


def rule_block_for(address: str, source: str = "email") -> str:
    return (f'if: source == "{source}" and contains("{address}")\n'
            "then: discard\n"
            "confidence: High")


def _capture_sender(brain_path: Path, capture: str):
    """`(display_name, address)` for a capture, or None."""
    path = brain_path / capture
    if not path.exists():
        return None
    match = FROM_RE.search(path.read_text(encoding="utf-8"))
    if not match:
        return None
    raw = match.group(1).strip()
    address_match = ADDRESS_RE.search(raw)
    if address_match:
        address = address_match.group(1).strip()
        name = triage._sanitize(ADDRESS_RE.sub("", raw)).strip('" ').strip()
        return (name or address, address)
    elif raw:
        return (raw, raw)
    return None


def candidates(brain_path: Path, text: str) -> list:
    """`[(name, match_on, count, captures), …]`, commonest first, for senders
    still costing a decision in this Plan and not already covered by a rule.

    `captures` are that sender's Raw Captures in this Plan — the evidence a
    proposed diff carries, and the reason a tick clears the review surface's
    >=2-evidence bar without that bar being weakened for anyone else."""
    seen = {}
    for row in execute.parse_plan_rows(text):
        if row["destination"].strip().lower() not in UNRESOLVED:
            continue
        sender = _capture_sender(brain_path, row["capture"])
        if not sender:
            continue
        name, address = sender
        entry = seen.setdefault(address, {"name": name, "count": 0, "captures": []})
        entry["count"] += 1
        entry["captures"].append(row["capture"])
    # Collapse a domain whose local parts vary to the domain itself. Some
    # senders randomise the local part per message —
    # `no-reply-OR7ml8it56ifoQf1S_QVhQ@mail.anthropic.com` — so a rule keyed on
    # the full address would match exactly the one capture that produced it and
    # never fire again: a dead rule, proposed once per message, cluttering the
    # list it exists to shorten. Matching on the domain is what the user means
    # by "this sender". A domain seen with a single stable local part keeps the
    # full address, which stays the tighter match where it works.
    by_domain = {}
    for address, entry in seen.items():
        domain = address.rpartition("@")[2].lower()
        by_domain.setdefault(domain, []).append((address, entry))

    merged = {}
    for domain, items in by_domain.items():
        if len(items) > 1:
            merged[domain] = {
                "name": items[0][1]["name"],
                "count": sum(entry["count"] for _, entry in items),
                "captures": [c for _, entry in items for c in entry["captures"]],
            }
        else:
            address, entry = items[0]
            merged[address] = entry

    out = []
    for match_on, entry in merged.items():
        if rule_learning.is_duplicate(brain_path, RULESET, rule_block_for(match_on)):
            continue
        out.append((entry["name"], match_on, entry["count"], entry["captures"]))
    return sorted(out, key=lambda item: (-item[2], item[0].lower()))


def _strip_section(text: str) -> str:
    """Remove an existing section, so --write rebuilds rather than appends."""
    pattern = re.compile(
        rf'\n*##\s+{re.escape(execute.SENDER_RULES_HEADING)}\n.*?(?=\n## |\Z)',
        re.DOTALL,
    )
    return pattern.sub("", text)


def build_section(rows: list) -> str:
    lines = [f"## {execute.SENDER_RULES_HEADING}", ""]
    for name, address, count, _captures in rows:
        suffix = f" · {count} today" if count > 1 else ""
        lines.append(f"- [ ] ⚡️ Always bin **{name}** `{address}`{suffix}")
    return "\n".join(lines) + "\n"


def write_section(brain_path: Path, text: str) -> tuple:
    """`(new_text, offered)`. Ticked boxes are preserved across a rebuild."""
    already_ticked = [
        line for line in text.splitlines()
        if (m := CHECKBOX_RE.match(line)) and m.group("tick") == "[x]"
    ]
    stripped = _strip_section(text)
    rows = candidates(brain_path, stripped)
    if not rows and not already_ticked:
        return stripped if stripped != text else text, 0
    section = build_section(rows)
    if already_ticked:
        # A tick not yet applied must survive the rebuild — losing it would
        # silently drop an instruction the user has already given.
        section = section.rstrip("\n") + "\n" + "\n".join(already_ticked) + "\n"
    new_text = stripped.rstrip("\n") + "\n\n" + section
    return execute.regroup_plan(new_text), len(rows)


def apply_section(brain_path: Path, text: str) -> tuple:
    """`(new_text, proposed, skipped)` — ticked boxes become rule diffs."""
    lines = text.splitlines()
    proposed, skipped = [], []
    # The captures behind each offered sender, so a ticked box carries real,
    # checkable evidence into the diff. The review surface requires >=2
    # evidence links (it was built for machine-detected correction patterns);
    # a sender that recurs enough to be worth a rule has >=2 captures in the
    # Plan by definition, so the bar is met honestly rather than relaxed.
    evidence_for = {
        match_on: captures
        for _name, match_on, _count, captures in candidates(brain_path, text)
    }
    for i, line in enumerate(lines):
        match = CHECKBOX_RE.match(line)
        if not match or match.group("tick") != "[x]" or match.group("marker"):
            continue
        address = match.group("address")
        name = match.group("name")
        block = rule_block_for(address)
        if rule_learning.is_duplicate(brain_path, RULESET, block):
            skipped.append(name)
            continue
        evidence = evidence_for.get(address, [])
        if len(evidence) < 2:
            # One sighting is not yet a pattern, and the review surface would
            # refuse the diff on arrival. Say so here rather than writing a
            # diff that fails validation later, out of sight of the tick.
            skipped.append(f"{name} (only {len(evidence)} capture(s) as evidence)")
            continue
        rule_learning.write_diff(
            brain_path, RULESET,
            slug=re.sub(r'[^a-z0-9]+', "-", name.lower()).strip("-") + "-is-noise",
            rule_block=block,
            why=(f"Kelvin ticked “Always bin {name}” on a Triage Plan — a direct "
                 f"instruction that mail from {address} is noise, made while "
                 "triaging it (ADR-0035)."),
            evidence_links=evidence,
            evidence_basis="sender-marked-noise",
        )
        desc = f"{name} ({address})" if name != address else address
        lines[i] = line + f" (proposed — rule for {desc})"
        proposed.append(name)
    return "\n".join(lines) + "\n", proposed, skipped


def propose_rule_from_instruction(
    brain_path: Path | None, text: str, sender_target: str, why_text: str = None
) -> tuple[bool, str]:
    """Validate and propose a sender rule from an instruction line.

    Reuses existing triage_sender_rules validation:
      - Real sender/capture evidence from `brain_path / capture`
      - Requires exactly one exact candidate match (address or domain); substring/name/first-match selection is rejected
      - Minimum evidence threshold (>= 2 real captures for that sender/domain in this Plan)
      - Duplicate check via `rule_learning.is_duplicate()`
      - No fabricated evidence / dummy path

    Returns `(success: bool, detail: str)`.
    """
    if not brain_path or not brain_path.is_dir():
        return False, "Brain path required to validate evidence"

    query_clean = sender_target.strip("`\"' ").lower()
    if query_clean.startswith("@"):
        query_clean = query_clean[1:]
    if not query_clean:
        return False, "Empty sender target"

    # Map unresolved rows in plan text to real sender evidence in brain_path
    seen = {}
    for row in execute.parse_plan_rows(text):
        if row["destination"].strip().lower() not in UNRESOLVED:
            continue
        sender = _capture_sender(brain_path, row["capture"])
        if not sender:
            continue
        name, address = sender
        entry = seen.setdefault(address, {"name": name, "count": 0, "captures": []})
        entry["count"] += 1
        entry["captures"].append(row["capture"])

    if not seen:
        return False, f"no real capture evidence found for {sender_target!r}"

    # Collect exact address candidates and domain candidates from evidence in Plan
    address_candidates = {}
    domain_candidates = {}

    for address, entry in seen.items():
        domain = address.rpartition("@")[2].lower()
        address_candidates[address.lower()] = {
            "match_on": address,
            "name": entry["name"],
            "address": address,
            "domain": domain,
            "captures": entry["captures"],
        }

        if domain not in domain_candidates:
            domain_candidates[domain] = {
                "match_on": domain,
                "name": entry["name"],
                "address": domain,
                "domain": domain,
                "captures": [],
            }

    # Populate domain captures (aggregate across all addresses in that domain)
    for address, entry in seen.items():
        domain = address.rpartition("@")[2].lower()
        domain_candidates[domain]["captures"].extend(entry["captures"])

    # Find matching candidates using EXACT match on candidate address or domain ONLY.
    # Substring matching, display name matching, and first-match selection are explicitly forbidden.
    matched_candidates = []

    for addr_lower, candidate in address_candidates.items():
        if query_clean == addr_lower:
            matched_candidates.append(candidate)

    for domain_lower, candidate in domain_candidates.items():
        if query_clean == domain_lower:
            matched_candidates.append(candidate)

    if len(matched_candidates) == 0:
        return False, f"no real capture evidence found for {sender_target!r}"
    if len(matched_candidates) > 1:
        return False, f"ambiguous sender selection for {sender_target!r}: matches multiple candidates"

    match_entry = matched_candidates[0]
    match_on = match_entry["match_on"]
    evidence = match_entry["captures"]
    if len(evidence) < 2:
        return False, f"insufficient evidence: only {len(evidence)} capture(s) found (requires >= 2)"

    name = match_entry["name"]
    desc = f"{name} ({match_on})" if name != match_on else match_on
    block = rule_block_for(match_on)

    if rule_learning.is_duplicate(brain_path, RULESET, block):
        return False, f"rule for {desc} is already covered"

    slug = re.sub(r'[^a-z0-9]+', "-", name.lower()).strip("-") + "-is-noise"
    rule_learning.write_diff(
        brain_path, RULESET,
        slug=slug,
        rule_block=block,
        why=why_text or f"User instruction in Triage Plan: bin all from {sender_target}",
        evidence_links=evidence,
        evidence_basis="triage-instruction",
    )
    return True, f"rule for {desc}"


def run(brain_path: Path, apply: bool = False, dry_run: bool = False) -> dict:
    triage_dir = brain_path / "inbox" / "triage"
    result = {"plans": {}, "proposed": [], "skipped": []}
    if not triage_dir.is_dir():
        return result
    for plan in sorted(triage_dir.glob("*-email.md")):
        text = plan.read_text(encoding="utf-8")
        if apply:
            new_text, proposed, skipped = apply_section(brain_path, text)
            result["proposed"] += proposed
            result["skipped"] += skipped
        else:
            new_text, offered = write_section(brain_path, text)
            if offered:
                result["plans"][plan.name] = offered
        if new_text != text and not dry_run:
            plan.write_text(new_text, encoding="utf-8")
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain", required=True)
    parser.add_argument("--apply", action="store_true",
                        help="Turn ticked checkboxes into proposed rule diffs.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    result = run(brain_path, apply=args.apply, dry_run=args.dry_run)
    if args.apply:
        if result["proposed"]:
            print(f"Proposed {len(result['proposed'])} rule diff(s) in inbox/rule-diffs/:")
            for name in result["proposed"]:
                print(f"  - {name}")
            print("\nApprove them with the rule-diff-review surface.")
        else:
            print("No ticked senders to propose.")
        if result["skipped"]:
            print(f"\nSkipped {len(result['skipped'])} already covered by a rule: "
                  + ", ".join(result["skipped"]))
    else:
        if result["plans"]:
            prefix = "Would offer" if args.dry_run else "Offering"
            print(f"{prefix} sender rules across {len(result['plans'])} plan(s):")
            for name, count in result["plans"].items():
                print(f"  - {name}: {count} sender(s)")
        else:
            print("No senders to offer — every repeat sender is already covered.")


if __name__ == "__main__":
    main()
