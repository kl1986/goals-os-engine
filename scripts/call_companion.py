#!/usr/bin/env python3
"""Call Companion curation flow for Goals OS Engine.

Implements protocols/call-companion.md.
A bounded, interactive planning flow that reads only unclassified active
tickets, defaults to at most 20 ordered by priority, proposes call_suitable
and estimate_minutes, and writes frontmatter only upon explicit confirmation.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import frontmatter  # noqa: E402
import log_action  # noqa: E402

H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)

SKIP_DIR_NAMES = {".git", ".obsidian", "__pycache__", ".trash", "node_modules"}
NON_ACTIVE_STATUSES = {"done", "deprioritized", "completed", "closed", "deprioritised"}

TRUTHY_VALUES = {True, "true", "True", "yes", "y", "1"}
FALSY_VALUES = {False, "false", "False", "no", "n", "0"}


def parse_frontmatter_dict(text: str) -> dict:
    return frontmatter.parse_frontmatter_dict(text)


def _extract_title(text: str, fallback: str) -> str:
    m = frontmatter.FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text
    h1_match = H1_RE.search(body)
    return h1_match.group(1).strip() if h1_match else fallback


def _priority_rank(priority_str: str) -> int:
    if not priority_str:
        return 3
    p = str(priority_str).strip().lower()
    if p == "high":
        return 0
    if p == "medium":
        return 1
    if p == "low":
        return 2
    return 3


def validate_call_suitable(val) -> str:
    if val in TRUTHY_VALUES:
        return "true"
    if val in FALSY_VALUES:
        return "false"
    raise ValueError(f"Invalid call_suitable value: {val!r} (must be boolean or boolean alias)")


def validate_estimate_minutes(val) -> str:
    if isinstance(val, bool) or isinstance(val, float):
        raise ValueError(f"Invalid estimate_minutes value: {val!r} (must be exact positive integer)")
    if isinstance(val, int):
        if val <= 0:
            raise ValueError(f"Invalid estimate_minutes value: {val!r} (must be exact positive integer)")
        return str(val)
    if isinstance(val, str):
        s = val.strip()
        if not s.isdigit():
            raise ValueError(f"Invalid estimate_minutes value: {val!r} (must be exact positive integer)")
        num = int(s)
        if num <= 0 or s != str(num):
            raise ValueError(f"Invalid estimate_minutes value: {val!r} (must be exact positive integer)")
        return str(num)
    raise ValueError(f"Invalid estimate_minutes value: {val!r} (must be exact positive integer)")


def gather_candidates(brain_path: Path | str, limit: int = 20) -> list[dict]:
    """Gather unclassified active tickets, ordered by priority, hard capped at limit.

    Read-only stage.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError(f"limit must be a positive integer, got: {limit!r}")

    brain_path = Path(brain_path).expanduser().resolve()
    candidates = []

    tasks_dir = brain_path / "tasks"
    if not tasks_dir.is_dir():
        return []

    for category in ("projects", "areas"):
        base_dir = tasks_dir / category
        if not base_dir.is_dir():
            continue

        for path in sorted(base_dir.rglob("*.md")):
            if not path.is_file():
                continue

            rel_path = path.relative_to(brain_path)
            if any(part in SKIP_DIR_NAMES or part.startswith(".") for part in rel_path.parts):
                continue

            # Must sit under tasks/<category>/<slug>/
            parts = rel_path.parts
            if len(parts) < 4:
                continue

            text = path.read_text(encoding="utf-8")
            if not frontmatter.FRONTMATTER_RE.match(text):
                continue

            fm = parse_frontmatter_dict(text)

            # Active check
            status = fm.get("status", "").strip().lower()
            if status in NON_ACTIVE_STATUSES:
                continue

            # Unclassified check
            call_suitable = fm.get("call_suitable", None)
            if call_suitable is not None:
                cs_val = str(call_suitable).strip().lower()
                if cs_val not in ("", "null", "~"):
                    # Explicitly classified (e.g. true, false, yes, no)
                    continue

            title = _extract_title(text, path.stem)
            rel_path_str = rel_path.as_posix()
            priority_val = fm.get("priority", "")

            candidates.append({
                "path": rel_path_str,
                "abs_path": path,
                "title": title,
                "priority": priority_val,
                "status": status,
                "frontmatter": fm,
                "content": text,
            })

    # Priority ordering: high > medium > low > blank, then stable by path
    candidates.sort(key=lambda c: (_priority_rank(c["priority"]), c["path"]))

    return candidates[:limit]


def default_provider(candidates: list[dict]) -> list[dict]:
    """Default deterministic proposal provider if no model/custom provider supplied."""
    proposals = []
    for c in candidates:
        text = c["content"].lower()
        title = c["title"].lower()
        call_kw = any(kw in title or kw in text for kw in ("call", "discuss", "phone", "talk", "meeting", "sync"))
        proposals.append({
            "path": c["path"],
            "call_suitable": call_kw,
            "estimate_minutes": 30 if call_kw else 15,
            "rationale": "Keywords match call/discussion." if call_kw else "Standard task review.",
        })
    return proposals


def propose(candidates: list[dict], provider=None) -> list[dict]:
    """Generate proposals using an injected provider. Writes nothing to disk.

    The provider is called exactly once with the list of candidates.
    Proposals produced do not carry confirmation markers.
    """
    if not candidates:
        return []

    if provider is None:
        provider = default_provider

    res = provider(candidates)
    if not isinstance(res, list):
        raise TypeError(f"Provider must return a list of proposals, got {type(res).__name__}")

    if len(res) > len(candidates):
        raise ValueError(f"Provider returned more proposals ({len(res)}) than candidate count ({len(candidates)})")

    valid_candidate_paths = {c["path"] for c in candidates}
    seen_paths = set()
    proposals = []

    for p in res:
        if not isinstance(p, dict):
            path = getattr(p, "path", None)
            cs_raw = getattr(p, "call_suitable", False)
            est_raw = getattr(p, "estimate_minutes", 30)
            rat = getattr(p, "rationale", "")
        else:
            path = p.get("path")
            cs_raw = p.get("call_suitable", False)
            est_raw = p.get("estimate_minutes", 30)
            rat = p.get("rationale", "")

        if not path or not isinstance(path, str):
            raise ValueError(f"Proposal missing valid path: {p!r}")

        if path not in valid_candidate_paths:
            raise ValueError(f"Provider returned path '{path}' which is not in candidate list")

        if path in seen_paths:
            raise ValueError(f"Provider returned duplicate proposal path: '{path}'")
        seen_paths.add(path)

        cs_canonical = validate_call_suitable(cs_raw)
        cs_val = True if cs_canonical == "true" else False
        est_val = int(validate_estimate_minutes(est_raw))

        proposals.append({
            "path": path,
            "call_suitable": cs_val,
            "estimate_minutes": est_val,
            "rationale": rat,
            "confirmed": False,
        })

    return proposals


def _is_valid_candidate_file(brain_path: Path, path_str: str) -> bool:
    """Validate that path_str points to an active unclassified candidate ticket inside brain_path/tasks."""
    if not path_str or not isinstance(path_str, str) or "\n" in path_str or "\r" in path_str:
        return False
    ticket_file = (brain_path / path_str).resolve()
    tasks_dir = (brain_path / "tasks").resolve()
    if not ticket_file.is_file() or not ticket_file.is_relative_to(tasks_dir):
        return False
    rel = ticket_file.relative_to(brain_path)
    parts = rel.parts
    if len(parts) < 4 or parts[0] != "tasks" or parts[1] not in ("projects", "areas"):
        return False
    if any(part in SKIP_DIR_NAMES or part.startswith(".") for part in parts):
        return False
    text = ticket_file.read_text(encoding="utf-8")
    if not frontmatter.FRONTMATTER_RE.match(text):
        return False
    fm = frontmatter.parse_frontmatter_dict(text)
    status = fm.get("status", "").strip().lower()
    if status in NON_ACTIVE_STATUSES:
        return False
    call_suitable = fm.get("call_suitable", None)
    if call_suitable is not None:
        cs_val = str(call_suitable).strip().lower()
        if cs_val not in ("", "null", "~"):
            return False
    return True


def apply_confirmed(brain_path: Path | str, confirmed: list[dict], now: dt.datetime = None) -> dict[str, list[dict]]:
    """Write call_suitable & estimate_minutes for ONLY confirmed proposals and log to Action Log.

    Rejected and omitted tickets are untouched (byte-identical).
    Validates all confirmed proposals in a first pass before making any writes.
    Returns {"applied": [...], "skipped": [...]}.
    """
    brain_path = Path(brain_path).expanduser().resolve()
    tasks_dir = (brain_path / "tasks").resolve()

    now = now or dt.datetime.now()
    results = []
    skipped = []

    if not confirmed:
        return {"applied": results, "skipped": skipped}

    # Pass 1: Validate EVERY proposal before making any writes or log entries
    validated_proposals = []
    for prop in confirmed:
        if not isinstance(prop, dict):
            path_str = getattr(prop, "path", None)
            is_confirmed = getattr(prop, "confirmed", False)
            cs_raw = getattr(prop, "call_suitable", None)
            est_raw = getattr(prop, "estimate_minutes", None)
        else:
            path_str = prop.get("path")
            is_confirmed = prop.get("confirmed", False)
            cs_raw = prop.get("call_suitable")
            est_raw = prop.get("estimate_minutes")

        if is_confirmed is not True:
            raise ValueError(f"Proposal for '{path_str}' is not confirmed.")

        if not path_str or not isinstance(path_str, str) or "\n" in path_str or "\r" in path_str:
            raise ValueError(f"Invalid proposal path: {path_str!r}")

        ticket_file = (brain_path / path_str).resolve()
        if not ticket_file.is_relative_to(tasks_dir):
            raise ValueError(f"Path '{path_str}' is outside tasks directory: {ticket_file}")

        if not _is_valid_candidate_file(brain_path, path_str):
            raise ValueError(f"Path '{path_str}' is not a valid candidate returned by gather_candidates")

        cs_val = validate_call_suitable(cs_raw)
        est_val = validate_estimate_minutes(est_raw)

        validated_proposals.append({
            "path": path_str,
            "ticket_file": ticket_file,
            "cs_val": cs_val,
            "est_val": est_val,
        })

    # Pass 2: Execute writes for validated proposals
    for prop_item in validated_proposals:
        path_str = prop_item["path"]
        ticket_file = prop_item["ticket_file"]
        cs_val = prop_item["cs_val"]
        est_val = prop_item["est_val"]

        with open(ticket_file, "r", encoding="utf-8", newline="") as f:
            text = f.read()

        new_text = frontmatter._update_frontmatter(text, {
            "call_suitable": cs_val,
            "estimate_minutes": est_val,
        })

        if new_text == text:
            skipped.append({"path": path_str, "reason": "No frontmatter changes made"})
            continue

        with open(ticket_file, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)

        entry = log_action.build_entry(
            actor="EA",
            trigger="Call Companion curation",
            action_type="ticket-planning-update",
            action=f"Updated call_suitable={cs_val}, estimate_minutes={est_val}",
            confidence="High",
            outcome=f"Updated ticket planning metadata on {path_str}",
            input_link=path_str,
            time_str=now.strftime("%H:%M"),
        )
        log_path = log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)
        results.append({"path": path_str, "log_path": log_path})

    return {"applied": results, "skipped": skipped}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--limit", type=int, default=20, help="Max candidates to gather (default: 20)")
    args = p.parse_args(argv)
    if args.limit <= 0:
        p.error(f"--limit must be a positive integer, got {args.limit}")
    return args


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    candidates = gather_candidates(brain_path, limit=args.limit)
    if not candidates:
        print("No unclassified active tickets found.")
        return

    print(f"Gathered {len(candidates)} candidate(s) for Call Companion curation:")
    for c in candidates:
        print(f"  - [{c['priority'] or 'blank'}] {c['path']}: {c['title']}")

    proposals = propose(candidates)
    print("\nProposed curation (no writes made without explicit confirmation):")
    for p in proposals:
        print(f"  - {p['path']} -> call_suitable: {p['call_suitable']}, estimate_minutes: {p['estimate_minutes']} ({p['rationale']})")


if __name__ == "__main__":
    main()
