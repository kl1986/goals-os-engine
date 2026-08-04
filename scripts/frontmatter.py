#!/usr/bin/env python3
"""YAML Frontmatter utilities for Goals OS Engine.

Leaf module with no dependencies on scripts/ so it can be safely imported by
low-dependency flows (e.g. Call Companion) without transitively pulling in
dashboard, execute, or subprocess.
"""

import re

FRONTMATTER_RE = re.compile(r"^(---\r?\n)(.*?)(\r?\n---\r?\n)", re.DOTALL)
FRONTMATTER_KEY_RE = re.compile(r"^([\w-]+):")

PLANNING_METADATA_KEYS = (
    "planned_for", "planning_lane", "estimate_minutes", "call_suitable", "critical"
)


def _is_continuation_line(lines: list, idx: int) -> bool:
    if idx >= len(lines):
        return False
    line = lines[idx]
    if line.startswith(" ") or line.startswith("\t"):
        return True
    if not line.strip():
        for k in range(idx + 1, len(lines)):
            if lines[k].startswith(" ") or lines[k].startswith("\t"):
                return True
            if FRONTMATTER_KEY_RE.match(lines[k]):
                return False
    return False


def _update_frontmatter(text: str, updates: dict) -> str:
    """Set (or add) top-level frontmatter keys in place, scoped to the
    leading ``---\\n...\\n---\\n`` block only, so a `status:`-shaped word
    later in the body is never touched. Existing keys are overwritten;
    keys not already present are appended at the end of the frontmatter
    block.

    If `status` is set to `done` (or a done alias), temporary planning metadata
    and criticality keys are cleared (removed from frontmatter).
    """
    fm_match = FRONTMATTER_RE.match(text)
    if not fm_match:
        return text

    newline = "\r\n" if ("\r\n" in fm_match.group(1) or "\r\n" in fm_match.group(3)) else "\n"

    effective_updates = dict(updates)
    if effective_updates.get("status") in ("done", "complete", "completed", "closed"):
        for k in PLANNING_METADATA_KEYS:
            if k not in effective_updates:
                effective_updates[k] = None

    lines = re.split(r"\r?\n", fm_match.group(2))
    new_lines = []
    emitted_keys = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        key_match = FRONTMATTER_KEY_RE.match(line)
        if key_match and key_match.group(1) in effective_updates:
            key = key_match.group(1)
            val = effective_updates[key]
            if val is not None and key not in emitted_keys:
                new_lines.append(f"{key}: {val}".rstrip())
                emitted_keys.add(key)
            i += 1
            while _is_continuation_line(lines, i):
                i += 1
        else:
            new_lines.append(line)
            i += 1

    for key, value in effective_updates.items():
        if value is not None and key not in emitted_keys:
            new_lines.append(f"{key}: {value}".rstrip())

    new_fm_body = newline.join(new_lines)
    return text[:fm_match.start(2)] + new_fm_body + text[fm_match.end(2):]


def parse_frontmatter_dict(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm = {}
    lines = re.split(r"\r?\n", m.group(2))
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1].strip()
            fm[k] = v
    return fm
