#!/usr/bin/env python3
"""Deterministic graduation engine for per-action-type autonomy state.

Implements protocols/action-log-schema.md's `feedback` slot (ADR-0005) and
ADR-0006's risk-tiered graduation. Pure Python, zero LLM calls, no side
effects: reads a Brain's config/ and log/ files and returns decisions —
never writes config/action-types.md or the Action Log itself (ticket 06's
Adapter acts on the verdict).

`find_unclassified_feedback(brain_path)` is the deterministic detector
half of the feedback-classification pass (Pass-A-style, mirroring
Triage's Pass A/B split): flags any entry whose `feedback` line isn't one
of the three canonical shapes (`—`, `validated`, `corrected — <detail>`).
Pure detection, no classification judgement.

`compute_graduation_state(brain_path, now=None)` is the counting engine.
For each `confirm-first` type in config/action-types.md, it counts
qualifying instances since that type's last graduate/demote boundary and
decides whether it's earned autonomy. For each `autonomous` type, it
checks for a `corrected` entry since its last boundary and demotes
instantly if found. Any row whose Autonomy level is the exact literal
`autonomous (fixed)` (the engine's own state-change/proposal events —
today `graduate-action-type`, `demote-action-type`, `propose-rule-diff`)
is skipped entirely and unconditionally, even against its own corrected
feedback — evaluating them would be circular. Plain `autonomous` (no
`(fixed)` suffix) is processed normally. Settings are read at runtime
from config/autonomy-policy.md, never hardcoded.

Boundary-parsing convention: a graduate-action-type/demote-action-type
entry's `outcome` field always starts with the target type in backticks
followed by the direction, e.g. `` `file-capture` → autonomous (5
qualifying instances across 4 distinct days) ``. Parsed via regex
`` `([\\w-]+)` → (autonomous|confirm-first) ``; no match found means
"count since Brain inception." Ticket 06's write-side code must stamp
outcomes in this exact format or this parser won't find the boundary.

CLI: `graduation.py --brain <path>` mirrors heartbeat.py's convention —
prints unclassified-feedback candidates and any non-"none" graduation
decisions, a single "Nothing to report." line if there's nothing to
surface.
"""

import argparse
import datetime as dt
import re
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402 — reuse its markdown-table parser

FIXED_AUTONOMOUS = "autonomous (fixed)"
INTERNAL_REVERSIBLE = "internal & reversible"

# The 3 graduation-threshold settings a decision needs, travelling
# together as one value rather than as separate parameters.
GraduationThresholds = namedtuple("GraduationThresholds", "window_days min_qualifying min_sessions")

_ENTRY_HEADING_RE = re.compile(r'^###\s+(\d{2}:\d{2})\s+—\s+(.+?)\s*$', re.MULTILINE)
_FIELD_RE = re.compile(r'^\s*-\s*\*\*([\w ]+):\*\*\s*(.*?)\s*$')
_LOG_DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')
_BOUNDARY_OUTCOME_RE = re.compile(r'`([\w-]+)`\s*→\s*(autonomous|confirm-first)')
_CORRECTED_RE = re.compile(r'^corrected\s*—\s*.+$')

BOUNDARY_ACTION_TYPES = {"graduate-action-type", "demote-action-type"}


# --------------------------------------------------------------------------
# Log parsing
# --------------------------------------------------------------------------

def parse_log_entries(text: str) -> list:
    """Parse one Action Log day-file's text into entry dicts.

    Each entry: {"time": "HH:MM", "heading_action_type": str, "fields": {...}}.
    `fields` keys are the lowercased field names exactly as they appear
    after `**` in the bullet list (e.g. "entry id", "action type",
    "feedback") — matches protocols/action-log-schema.md's entry shape.
    """
    entries = []
    for block in re.split(r'(?=^### )', text, flags=re.MULTILINE):
        heading = _ENTRY_HEADING_RE.match(block)
        if not heading:
            continue
        time_str, heading_action_type = heading.groups()
        fields = {}
        for line in block.splitlines():
            m = _FIELD_RE.match(line)
            if m:
                fields[m.group(1).strip().lower()] = m.group(2).strip()
        entries.append({
            "time": time_str,
            "heading_action_type": heading_action_type.strip(),
            "fields": fields,
        })
    return entries


def _date_from_log_filename(path: Path):
    m = _LOG_DATE_RE.match(path.stem)
    return m.group(1) if m else None


def _iter_log_files(brain_path: Path) -> list:
    log_dir = brain_path / "log"
    if not log_dir.is_dir():
        return []
    return sorted(log_dir.glob("*.md"))


def _all_entries(brain_path: Path) -> list:
    """Every entry across every `log/*.md` file, as (date_str, path, entry) triples.

    Sorted chronologically (date then time, both lexicographically
    sortable in their fixed-width formats). Grouping downstream is by
    `date_str` — the day file an entry falls in — never by `actor`
    (one non-conforming `actor` value exists in the real log; this
    parser doesn't depend on that field at all).
    """
    results = []
    for log_path in _iter_log_files(brain_path):
        date_str = _date_from_log_filename(log_path)
        if date_str is None:
            continue
        for entry in parse_log_entries(log_path.read_text()):
            results.append((date_str, log_path, entry))
    results.sort(key=lambda triple: (triple[0], triple[1].name, triple[2]["time"]))
    return results


def _entry_datetime(date_str: str, time_str: str):
    try:
        return dt.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Config parsing
# --------------------------------------------------------------------------

def parse_autonomy_policy(brain_path: Path) -> dict:
    """Read config/autonomy-policy.md's Setting/Default table into a dict.

    Values that parse as ints are converted; anything else is kept as
    the raw string. Missing file/rows yield an empty dict — callers fall
    back to their own defaults.
    """
    path = brain_path / "config" / "autonomy-policy.md"
    if not path.exists():
        return {}
    policy = {}
    for row in heartbeat.parse_table(path.read_text()):
        setting, default = row.get("Setting"), row.get("Default")
        if not setting or default is None:
            continue
        try:
            policy[setting] = int(default)
        except ValueError:
            policy[setting] = default
    return policy


def parse_action_types(brain_path: Path) -> list:
    """Read config/action-types.md's registered rows (list of dicts)."""
    path = brain_path / "config" / "action-types.md"
    if not path.exists():
        return []
    return heartbeat.parse_table(path.read_text())


# --------------------------------------------------------------------------
# 1. find_unclassified_feedback
# --------------------------------------------------------------------------

def _is_canonical_feedback(value: str) -> bool:
    return value == "—" or value == "validated" or bool(_CORRECTED_RE.match(value))


def find_unclassified_feedback(brain_path) -> list:
    """Flag Action Log entries whose `feedback` isn't one of the 3 canonical shapes.

    Pure detection (Pass-A style) — no judgement about what the entry
    *should* be classified as. Returns a list of
    {"entry_id": str, "file": Path, "feedback": str} dicts, one per
    non-conforming entry. An entry missing the `feedback` field entirely
    is also surfaced (feedback: "") rather than silently skipped — it's
    not one of the 3 canonical shapes either, and heartbeat.py's own
    precedent is to surface malformed data rather than hide it.
    """
    brain_path = Path(brain_path)
    candidates = []
    for log_path in _iter_log_files(brain_path):
        for entry in parse_log_entries(log_path.read_text()):
            feedback = entry["fields"].get("feedback", "")
            if _is_canonical_feedback(feedback):
                continue
            candidates.append({
                "entry_id": entry["fields"].get("entry id", ""),
                "file": log_path,
                "feedback": feedback,
            })
    return candidates


# --------------------------------------------------------------------------
# 2. compute_graduation_state
# --------------------------------------------------------------------------

def _review_debt_from_entries(all_entries: list, window_days: float, now: dt.datetime) -> int:
    count = 0
    for date_str, _path, entry in all_entries:
        if entry["fields"].get("feedback") != "—":
            continue
        entry_dt = _entry_datetime(date_str, entry["time"])
        if entry_dt is None:
            continue
        if (now - entry_dt).total_seconds() / 86400 >= window_days:
            count += 1
    return count


def review_debt(brain_path, now: dt.datetime = None) -> int:
    """Count of Action Log entries, system-wide across every type/tier,
    with `feedback: —` older than `review-window-days`, as of `now`.

    Deliberately global, not per-type (tests whether review activity has
    broadly stalled). A small, separately-named, swappable contract —
    Phase 6 can replace the formula without touching anything else in
    this module, as long as it keeps returning a comparable count.
    """
    brain_path = Path(brain_path)
    now = now or dt.datetime.now()
    policy = parse_autonomy_policy(brain_path)
    window_days = policy.get("review-window-days", 1)
    return _review_debt_from_entries(_all_entries(brain_path), window_days, now)


def _find_last_boundary(all_entries: list, action_type: str):
    """Most recent graduate/demote Action Log entry naming `action_type`.

    Parses the fixed `` `<type>` → <direction> `` prefix in the
    `outcome` field of `graduate-action-type`/`demote-action-type`
    entries (see module docstring). Returns a datetime, or None if no
    boundary entry exists yet (count since Brain inception).
    """
    latest = None
    for date_str, _path, entry in all_entries:
        if entry["heading_action_type"] not in BOUNDARY_ACTION_TYPES:
            continue
        outcome = entry["fields"].get("outcome", "")
        m = _BOUNDARY_OUTCOME_RE.search(outcome)
        if not m or m.group(1) != action_type:
            continue
        entry_dt = _entry_datetime(date_str, entry["time"])
        if entry_dt is None:
            continue
        if latest is None or entry_dt > latest:
            latest = entry_dt
    return latest


def _entries_since_boundary(all_entries: list, action_type: str, boundary_dt):
    relevant = []
    for date_str, _path, entry in all_entries:
        if entry["heading_action_type"] != action_type:
            continue
        entry_dt = _entry_datetime(date_str, entry["time"])
        if boundary_dt is not None:
            if entry_dt is None or entry_dt <= boundary_dt:
                continue
        relevant.append((date_str, entry))
    return relevant


def _graduation_decision(relevant, risk_tier, thresholds, debt_suspended, now):
    """thresholds: a GraduationThresholds bundling the 3 policy numbers
    this decision needs — keeps them travelling together as one value
    rather than as separate parameters."""
    qualifying_days = set()
    qualifying_count = 0
    for date_str, entry in relevant:
        feedback = entry["fields"].get("feedback", "")
        qualifies = False
        if feedback == "validated":
            qualifies = True
        elif feedback == "—" and risk_tier == INTERNAL_REVERSIBLE and not debt_suspended:
            entry_dt = _entry_datetime(date_str, entry["time"])
            if entry_dt is not None and (now - entry_dt).total_seconds() / 86400 >= thresholds.window_days:
                qualifies = True
        if qualifies:
            qualifying_count += 1
            qualifying_days.add(date_str)

    graduated = qualifying_count >= thresholds.min_qualifying and len(qualifying_days) >= thresholds.min_sessions
    decision = "graduate" if graduated else "none"
    verb = "" if graduated else "need "
    reason = (
        f"{qualifying_count} qualifying instances across {len(qualifying_days)} distinct days "
        f"({verb}threshold {thresholds.min_qualifying}/{thresholds.min_sessions})"
    )
    return {
        "decision": decision,
        "reason": reason,
        "qualifying_count": qualifying_count,
        "qualifying_days": len(qualifying_days),
    }


def _demotion_decision(relevant):
    for date_str, entry in relevant:
        feedback = entry["fields"].get("feedback", "")
        if _CORRECTED_RE.match(feedback):
            entry_id = entry["fields"].get("entry id", "?")
            reason = f"corrected feedback on entry {entry_id} ({date_str} {entry['time']})"
            return {"decision": "demote", "reason": reason}
    return {"decision": "none", "reason": "no corrections since last boundary"}


def compute_graduation_state(brain_path, now: dt.datetime = None) -> dict:
    """Decide graduate/demote/none for every non-fixed action type.

    Returns {action_type: {"decision": "graduate"|"demote"|"none", "reason": str, ...}}.
    This is a pure decision function — it does not write
    config/action-types.md or the Action Log; the caller (ticket 06) acts
    on the returned verdicts.
    """
    brain_path = Path(brain_path)
    now = now or dt.datetime.now()

    policy = parse_autonomy_policy(brain_path)
    thresholds = GraduationThresholds(
        window_days=policy.get("review-window-days", 1),
        min_qualifying=policy.get("graduation-min-qualifying", 5),
        min_sessions=policy.get("graduation-min-sessions", 3),
    )
    debt_max = policy.get("review-debt-max", 20)

    # Goes through the public review_debt() — not a private re-derivation
    # — so swapping review_debt()'s formula (Phase 6) actually changes
    # this engine's behaviour without any other edit needed here.
    debt_suspended = review_debt(brain_path, now=now) > debt_max

    all_entries = _all_entries(brain_path)

    result = {}
    for row in parse_action_types(brain_path):
        action_type = row.get("Action type")
        risk_tier = row.get("Risk tier", "")
        autonomy = row.get("Autonomy level", "")
        if not action_type:
            continue

        # Fixed-autonomous exclusion — hard, unconditional skip. Never
        # counted, never scanned for `corrected`, regardless of that
        # type's own log entries' feedback.
        if autonomy == FIXED_AUTONOMOUS:
            continue

        boundary_dt = _find_last_boundary(all_entries, action_type)
        relevant = _entries_since_boundary(all_entries, action_type, boundary_dt)

        if autonomy == "autonomous":
            result[action_type] = _demotion_decision(relevant)
        else:
            # "confirm-first" and any other non-fixed, non-"autonomous"
            # value default to graduation counting — mirrors
            # heartbeat.py's tolerant read of the config table.
            result[action_type] = _graduation_decision(
                relevant, risk_tier, thresholds, debt_suspended, now
            )

    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain (contains config/ and log/)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    unclassified = find_unclassified_feedback(brain_path)
    state = compute_graduation_state(brain_path)
    changes = {k: v for k, v in state.items() if v["decision"] != "none"}

    if not unclassified and not changes:
        print("Nothing to report.")
        return

    if unclassified:
        print(f"Unclassified feedback ({len(unclassified)}):")
        for item in unclassified:
            print(f"  - {item['entry_id']} ({item['file']}): {item['feedback']!r}")

    if changes:
        print("Graduation state changes:")
        for action_type, info in changes.items():
            print(f"  - {action_type}: {info['decision']} — {info['reason']}")


if __name__ == "__main__":
    main()
