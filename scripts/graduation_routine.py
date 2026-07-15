#!/usr/bin/env python3
"""Graduation check Routine: the deterministic write side of the graduation engine.

Implements protocols/routine-graduation.md — the two-pass "Graduation
check" Routine (ticket 04's resolution): Pass (i) feedback
classification/normalization (ticket 01), Pass (ii) per-action-type
graduation counting (ticket 03). `scripts/graduation.py` (ticket 03,
unmodified here) supplies both passes' pure decision logic
(`find_unclassified_feedback`, `compute_graduation_state`); this module
adds only the write side-effects: the mechanical Pass-(i) field
overwrite, and Pass (ii)'s `config/action-types.md` edit + Action Log
entries + this Routine's own `config/routine-state.md` bump.

Fully automatic, zero confirmation — matches Version Control's
silent-automatic pattern, not Triage's confirm-first Plan pattern. The
actual *judgement* calls (what a free-text feedback comment should be
classified as) are made in-session by this Routine's Adapter binding
(`adapters/claude-code/skills/graduation-check/`), mirroring Triage's
Pass B — this script only performs the deterministic write once that
judgement exists.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import graduation  # noqa: E402 — reuse its decision engine unmodified
import heartbeat  # noqa: E402 — reuse its table parser + routine-state bump
import log_action  # noqa: E402 — reuse its Action Log entry builder/writer

ROUTINE_NAME = "Graduation check"

GRADUATE_ACTION_TYPE = "graduate-action-type"
DEMOTE_ACTION_TYPE = "demote-action-type"
PROPOSE_RULE_DIFF_ACTION_TYPE = "propose-rule-diff"

# Belt-and-suspenders (ticket 06 acceptance criterion 6): this write-side
# code must never flip Autonomy level or log a graduate/demote entry for
# these three types, even if compute_graduation_state()'s output somehow
# included one of them. This is a second, independent check — the real
# exclusion is graduation.py's own FIXED_AUTONOMOUS skip inside
# compute_graduation_state() — not a substitute for it. Kept as its own
# literal set (not derived from graduation.py's BOUNDARY_ACTION_TYPES or
# FIXED_AUTONOMOUS logic) so a bug in that module's exclusion can't
# silently disable this one too.
EXCLUDED_FROM_WRITE = {GRADUATE_ACTION_TYPE, DEMOTE_ACTION_TYPE, PROPOSE_RULE_DIFF_ACTION_TYPE}

DEFAULT_ACTOR = "scripts"
DEFAULT_TRIGGER = "Graduation check (Routine)"

_ENTRY_ID_LINE_RE = re.compile(r'^-\s*\*\*entry id:\*\*\s*(.+?)\s*$', re.MULTILINE)
_FEEDBACK_LINE_RE = re.compile(r'^-\s*\*\*feedback:\*\*.*$', re.MULTILINE)
_FIELD_LINE_RE = re.compile(r'^-\s*\*\*[\w ]+:\*\*.*$', re.MULTILINE)


def _is_canonical_feedback(value: str) -> bool:
    # Delegates to graduation.py's own canonical-shape check rather than
    # re-deriving the same —/validated/corrected rule here — one source
    # of truth for what counts as a classified value, so the two modules
    # can't silently drift apart on the definition.
    return graduation._is_canonical_feedback(value)


# --------------------------------------------------------------------------
# Pass (i) — feedback classification write-back (mechanical only)
# --------------------------------------------------------------------------

def write_feedback_classification(log_path: Path, entry_id: str, new_value: str) -> bool:
    """Overwrite one Action Log entry's `feedback:` line in place, by entry id.

    Mechanical only — the classification *decision* (what new_value should
    be) is made in-session by this Routine's Adapter binding (Pass (i)'s
    judgement step); this function only performs the deterministic text
    overwrite once that decision exists. Creates **no** new Action Log
    entry — per ticket 04's resolution, normalizing an existing entry's
    own field is not itself a loggable action.

    Returns True if the entry was found and its feedback line updated
    (or added, if the entry was malformed and missing the field
    entirely); False if `log_path` or the entry id doesn't exist —
    silent no-op, mirroring heartbeat.update_last_run()'s precedent.
    """
    if not log_path.exists():
        return False
    text = log_path.read_text()
    blocks = re.split(r'(?=^### )', text, flags=re.MULTILINE)

    for i, block in enumerate(blocks):
        m = _ENTRY_ID_LINE_RE.search(block)
        if not m or m.group(1) != entry_id:
            continue

        if _FEEDBACK_LINE_RE.search(block):
            new_block = _FEEDBACK_LINE_RE.sub(f"- **feedback:** {new_value}", block, count=1)
        else:
            field_matches = list(_FIELD_LINE_RE.finditer(block))
            if not field_matches:
                return False
            insert_at = field_matches[-1].end()
            new_block = block[:insert_at] + f"\n- **feedback:** {new_value}" + block[insert_at:]

        blocks[i] = new_block
        log_path.write_text("".join(blocks))
        return True

    return False


# --------------------------------------------------------------------------
# Pass (ii) — graduation counting write-back
# --------------------------------------------------------------------------

def _split_table_line(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator_row(cells: list) -> bool:
    return bool(cells) and all(re.fullmatch(r':?-+:?', c) for c in cells)


def update_action_type_autonomy(path: Path, action_type: str, new_level: str) -> bool:
    """Rewrite one row's `Autonomy level` cell in `config/action-types.md`.

    Mirrors heartbeat.update_last_run()'s shape (silent no-op if the file
    or the row doesn't exist) but for the 4-column action-types table
    (`Action type | Risk tier | Autonomy level | Notes`) instead of the
    2-column routine-state table.
    """
    if not path.exists():
        return False
    text = path.read_text()
    lines = text.splitlines()

    header = None
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = _split_table_line(line)

        if header is None:
            if "Action type" in cells and "Autonomy level" in cells:
                header = cells
            continue

        if _is_separator_row(cells) or len(cells) != len(header):
            continue

        row = dict(zip(header, cells))
        if row.get("Action type") != action_type:
            continue

        autonomy_idx = header.index("Autonomy level")
        cells[autonomy_idx] = new_level
        lines[i] = "| " + " | ".join(cells) + " |"
        path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
        return True

    return False


def apply_graduation_changes(brain_path, state: dict, now: dt.datetime = None,
                              actor: str = DEFAULT_ACTOR, trigger: str = DEFAULT_TRIGGER) -> list:
    """Act on compute_graduation_state()'s verdicts.

    For every action type whose decision is "graduate" or "demote": flip
    `config/action-types.md`'s Autonomy level cell, then append a
    `graduate-action-type`/`demote-action-type` Action Log entry whose
    `outcome` field uses the fixed `` `<type>` → <direction> (<reason>) ``
    convention `graduation.py`'s `_find_last_boundary()` parses (see that
    module's docstring) — drifting from this exact shape would silently
    break future graduation counting for this type.

    Belt-and-suspenders: `EXCLUDED_FROM_WRITE` is checked here
    independently of `compute_graduation_state()`'s own FIXED_AUTONOMOUS
    skip — even if that exclusion ever had a bug and let one of those
    three types leak into `state`, this loop refuses to act on it.

    A row that no longer exists in `config/action-types.md` (or the file
    itself is missing) is also skipped with no Action Log entry — nothing
    was actually flipped, so nothing should be recorded as having changed.

    Returns a list of {"action_type", "decision", "new_level", "outcome"}
    dicts, one per real change made — empty if nothing changed.
    """
    now = now or dt.datetime.now()
    brain_path = Path(brain_path)
    action_types_path = brain_path / "config" / "action-types.md"

    changes = []
    for action_type, info in state.items():
        if action_type in EXCLUDED_FROM_WRITE:
            continue

        decision = info.get("decision")
        if decision == "graduate":
            new_level = "autonomous"
            heading_type = GRADUATE_ACTION_TYPE
        elif decision == "demote":
            new_level = "confirm-first"
            heading_type = DEMOTE_ACTION_TYPE
        else:
            continue

        if not update_action_type_autonomy(action_types_path, action_type, new_level):
            continue

        outcome = f"`{action_type}` → {new_level} ({info.get('reason', '')})"
        entry = log_action.build_entry(
            actor=actor,
            trigger=trigger,
            action_type=heading_type,
            action=f"Action type '{action_type}' {decision}d based on Action Log history.",
            confidence="High",
            outcome=outcome,
            time_str=now.strftime("%H:%M"),
        )
        log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)

        changes.append({
            "action_type": action_type, "decision": decision,
            "new_level": new_level, "outcome": outcome,
        })

    return changes


def run_counting_pass(brain_path, now: dt.datetime = None,
                       actor: str = DEFAULT_ACTOR, trigger: str = DEFAULT_TRIGGER) -> dict:
    """Pass (ii), end to end: compute, apply, then bump this Routine's own row.

    The routine-state bump happens regardless of whether anything
    changed — mirrors triage.run()'s "bumped regardless" precedent (the
    Routine ran and checked, even when nothing was due for a state
    change), so acceptance criterion 1's no-op case still produces
    exactly one write (the timestamp).
    """
    now = now or dt.datetime.now()
    brain_path = Path(brain_path)

    state = graduation.compute_graduation_state(brain_path, now=now)
    changes = apply_graduation_changes(brain_path, state, now=now, actor=actor, trigger=trigger)

    heartbeat.bump(brain_path, ROUTINE_NAME, now)

    return {"state": state, "changes": changes}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain (contains config/ and log/)")
    sub = p.add_subparsers(dest="command", required=True)

    classify_p = sub.add_parser(
        "classify",
        help="Pass (i) write-back: overwrite one Action Log entry's feedback line in place.",
    )
    classify_p.add_argument("--log-file", required=True, help="Path to the log/YYYY-MM-DD.md file containing the entry")
    classify_p.add_argument("--entry-id", required=True)
    classify_p.add_argument("--value", required=True, help='"validated" | "corrected — <detail>" | "—"')

    sub.add_parser("count", help="Pass (ii): compute graduation state, apply changes, bump routine-state.")

    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    if args.command == "classify":
        if not _is_canonical_feedback(args.value):
            sys.exit(f"Not a canonical feedback value: {args.value!r} (must be —, validated, or corrected — <detail>)")
        log_path = Path(args.log_file).expanduser().resolve()
        ok = write_feedback_classification(log_path, args.entry_id, args.value)
        if not ok:
            sys.exit(f"Entry {args.entry_id!r} not found in {log_path}")
        print(f"Classified {args.entry_id} → {args.value!r} in {log_path}")
        return

    if args.command == "count":
        result = run_counting_pass(brain_path)
        if not result["changes"]:
            print("Nothing to report.")
            return
        for change in result["changes"]:
            print(f"  - {change['action_type']}: {change['decision']} → {change['new_level']}")
        return


if __name__ == "__main__":
    main()
