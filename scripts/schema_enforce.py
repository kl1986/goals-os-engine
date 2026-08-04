#!/usr/bin/env python3
"""Goals OS schema and structure enforcer — four checks, one tool.

Implements the `goals-os-schema-and-structure-enforcer` ticket's decisions
(25/07/2026). Pure Python, zero LLM calls, same house shape as
`triage.py` / `version_control.py` (argparse, `--brain`).

Checks (a)–(c) resolve against **one canonical slug map** derived from the
Brain's `projects/<slug>/` and `areas/<slug>/` directories; (d) stands on its
own:

**(a) Ticket frontmatter schema** — every `tasks/**/*.md` carries the full
ADR-0015 key set, `status` is in the ADR-0025 vocabulary, `type` is in the
ADR-0015 vocabulary, and any non-blank `created`/`resolved` is a valid ISO
date. `kanban_order` is Base Board-managed and is never read for
conformance, never written, and never normalised. Tickets whose frontmatter status
is already canonical `done` (`status: done`) are explicitly exempted from schema
enforcement. Non-canonical status aliases (e.g. `complete`, `closed`) are not
exempted; they are reported and repaired to `done`, clearing any planning
metadata in the process.

**(b) Folder/naming traceability** — a Project/Area slug is the same string
in `projects/<slug>/`, `tasks/projects/<slug>/`, `Code/projects/<name>/`
and `Files/`. Two finding kinds:

- `naming-mismatch` — a directory name that isn't already its own canonical
  slug (`Code/projects/Goals OS/` vs the `goals-os` slug used everywhere
  else). Only raised for roots whose convention *is* the slug; `Files/`
  mirrors the Areas in Title Case by long-standing vault convention (root
  `CLAUDE.md`), so `Files/` roots are traceability-checked only and never
  case-flagged.
- `orphan` — a directory with no counterpart in the canonical slug map
  (a `tasks/projects/<slug>/` with no `projects/<slug>/`, and so on).

**(c) Cross-note integrity** — `[[wikilinks]]` that resolve to no note in
the Brain, and tickets filed under a `tasks/<projects|areas>/<slug>/` whose
Project/Area does not exist.

**(d) `CLAUDE.md` caveat expiry** — a "wait for the dependent ticket" caveat
in always-loaded context must name the ticket that clears it, so it can
expire itself. A caveat is marked with the literal `**Caveat**` token and
must carry a `[[wikilink]]` to a ticket under `tasks/`. Three finding kinds:

- `caveat-expired` — the named ticket is `status: done`, so the caveat may
  now be stale. This is the whole point of the check: the last stale caveat
  outlived its dependencies by weeks and told agents not to write a status
  the pipeline required.
- `caveat-unlinked` — a caveat naming no ticket at all; nothing can expire it.
- `caveat-unresolved-ticket` — it links a note that is not a ticket, so there
  is no status to clear on. Check (c) stays quiet about these because the
  link resolves perfectly well; it just cannot ever go `done`.

**Never fixable, by construction.** Removing a caveat means rewriting the
prose around it and judging whether the surrounding sentence is still true.
`apply_fixes` routes only (a)/(b)/(c), so a (d) finding cannot be applied
even by mistake.

## Modes

`--dry-run` (the **default**) reports and writes nothing at all — no Brain
writes, no change log, no Action Log entry. `--apply` opts in to repair.
The ticket's "auto-fix always" governs the tool's *capability* (it repairs
in one pass rather than being a report-only linter); a bare invocation is
still inert, because this thing renames folders.

## Safety guard (required by the ticket)

`--apply` refuses to run against a **dirty** Brain working tree, and
otherwise lays down an empty marker commit immediately before the first fix
so any bad move is a one-command `git reset --hard <sha>`. It then commits
its own output, so the next run meets a clean tree rather than aborting on
dirt this tool created. With nothing fixable to do it writes nothing at all
— no marker commit, no change log, no Action Log entry — so a scheduled
`--apply` on a conforming Brain is a true no-op.

`archive/` and `inbox/raw/` are the Brain's immutable record: they are
indexed and checked, and never written to.

That guard only covers the Brain repo. A path outside it — notably
`Code/projects/<name>/`, which lives under `Documents/` and is not inside
any git repository — therefore cannot be renamed reversibly, so a rename
there is **reported, never applied**, with the reason stated. A code root
that *is* inside a clean git repo is renamed normally.

## Relationship to `ticket_normalization.py`

This tool **extends** that Routine, it does not replace or fight it. Key
*presence* backfill reuses `ticket_normalization`'s own REQUIRED_KEYS and
`backfill_frontmatter()` verbatim, so both produce byte-identical results
and either can run first. This tool adds *value* conformance (vocabulary,
dates), which the Routine has no notion of. It deliberately does **not**
rename ticket files to their slugified H1 or quarantine to `tasks/_unfiled/`
— that is ADR-0019/ADR-0020 work and stays owned by the Routine.
"""

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import log_action  # noqa: E402
import ticket_normalization as tn  # noqa: E402

DEFAULT_LOG_FILE = "~/Library/Logs/goals-os-schema-enforce.log"

# Reused verbatim from the sibling Routine so the two never disagree about
# what "the ADR-0015 key set" is. `kanban_order` is excluded there too.
REQUIRED_KEYS = tn.REQUIRED_KEYS

STATUS_VALUES = (
    "backlog", "prioritised", "in-progress",
    "awaiting-review", "done", "deprioritized",
)
TYPE_VALUES = ("story", "task", "bug", "subtask", "research")

# Blank means "the plugin/author never set it"; these are the schema defaults.
BLANK_DEFAULTS = {"status": "backlog", "type": "task"}

# Spelling variants that map unambiguously onto a vocabulary value.
STATUS_ALIASES = {
    "prioritized": "prioritised",
    "deprioritised": "deprioritized",
    "todo": "backlog",
    "to-do": "backlog",
    "wip": "in-progress",
    "in-review": "awaiting-review",
    "complete": "done",
    "completed": "done",
    "closed": "done",
}
TYPE_ALIASES = {"feature": "story", "chore": "task", "spike": "research"}

DATE_KEYS = ("created", "resolved")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UK_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")

# `[[Target]]`, `[[Target|alias]]`, `[[Target#heading]]`. A leading `!` (an
# embed) is excluded — embeds routinely point at images and other
# non-note assets, which is not what (c) is about.
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]|#]+)((?:#[^\[\]|]*)?)(\|[^\[\]]*)?\]\]")
FENCE_RE = re.compile(r"^(```|~~~)")
INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")

SKIP_DIR_NAMES = {".git", ".obsidian", "__pycache__", ".trash", "node_modules"}

# The literal token that makes a `CLAUDE.md` caveat greppable (check (d)).
# An unmarked caveat is undetectable by anything short of reading the prose,
# which is exactly how the last one survived for weeks.
CAVEAT_MARKER = "**Caveat**"

# `inbox/raw/` captures are immutable on arrival and everything under
# `archive/` is the executed record of them, so no repair may ever write
# there — the audit trail has to stay byte-identical to what was filed.
IMMUTABLE_ROOTS = ("archive", "inbox/raw")


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

class Finding:
    """One problem, plus whether this tool can mechanically repair it."""

    def __init__(self, check, kind, path, detail, fixable=False,
                 fix_desc=None, blocked_reason=None, fix_args=None):
        self.check = check              # "a" | "b" | "c"
        self.kind = kind
        self.path = path                # display path, string
        self.detail = detail
        self.fixable = fixable
        self.fix_desc = fix_desc
        self.blocked_reason = blocked_reason
        # Machine-readable arguments for the fixer, so no fixer ever has to
        # re-parse a human-readable `detail`/`fix_desc` string.
        self.fix_args = fix_args or {}

    def __repr__(self):
        return f"<Finding {self.check}/{self.kind} {self.path}: {self.detail}>"

    def line(self):
        prefix = f"[{self.check}/{self.kind}] {self.path}: {self.detail}"
        if self.fixable:
            return f"{prefix} -> FIX: {self.fix_desc}"
        if self.blocked_reason:
            return f"{prefix} -> NOT FIXABLE: {self.blocked_reason}"
        return f"{prefix} -> NOT FIXABLE"


# --------------------------------------------------------------------------
# Canonical slug map
# --------------------------------------------------------------------------

def _child_dirs(parent: Path):
    if not parent.is_dir():
        return []
    return sorted(
        p for p in parent.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and p.name not in SKIP_DIR_NAMES and not p.name.startswith("_")
    )


def build_slug_map(brain_path: Path) -> dict:
    """`{slug: kind}` for every Project and Area directory in the Brain.

    A directory whose name is not already its own slug (`projects/Goals OS/`)
    contributes its *canonical* slug, so downstream roots are measured
    against the slug the rest of the Brain actually uses, not against the
    drifted spelling. The drifted directory itself is reported by check (b).
    """
    slug_map = {}
    for kind, sub in (("project", "projects"), ("area", "areas")):
        for d in _child_dirs(brain_path / sub):
            slug_map.setdefault(tn.slugify(d.name), kind)
    return slug_map


# --------------------------------------------------------------------------
# Frontmatter helpers
# --------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict:
    """`{key: raw string value}` for the file's frontmatter block, or `{}`."""
    m = tn.FRONTMATTER_RE.match(text)
    if not m:
        return {}
    values = {}
    for line in m.group(2).splitlines():
        key_match = tn.FRONTMATTER_KEY_RE.match(line)
        if key_match:
            values[key_match.group(1)] = line.split(":", 1)[1].strip()
    return values


def block_keys(text: str) -> set:
    """Frontmatter keys whose value continues onto following indented lines.

    `status:\\n  - backlog` is a perfectly good YAML block sequence, but this
    module's frontmatter helpers are line-based: rewriting the `status:` line
    alone would strand the `- backlog` item and leave unparseable YAML. Such
    keys are reported and never rewritten.
    """
    m = tn.FRONTMATTER_RE.match(text)
    if not m:
        return set()
    lines = m.group(2).splitlines()
    blocks = set()
    for i, line in enumerate(lines):
        key_match = tn.FRONTMATTER_KEY_RE.match(line)
        if not key_match:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if nxt[:1] in (" ", "\t") and nxt.strip():
            blocks.add(key_match.group(1))
    return blocks


PLANNING_LANE_VALUES = ("now", "later", "call", "tomorrow-candidate")
PLANNING_LANE_ALIASES = {
    "tomorrow_candidate": "tomorrow-candidate",
    "tomorrow candidate": "tomorrow-candidate",
    "tomorrow": "tomorrow-candidate",
}

BOOLEAN_VALUES = ("true", "false")
BOOLEAN_ALIASES = {
    "yes": "true",
    "no": "false",
    "y": "true",
    "n": "false",
    "true": "true",
    "false": "false",
}


PLANNING_KEYS = (
    "planned_for", "planning_lane", "estimate_minutes", "call_suitable", "critical"
)

CONTROLLED_KEYS = tuple(REQUIRED_KEYS) + tuple(PLANNING_KEYS)


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
            if tn.FRONTMATTER_KEY_RE.match(lines[k]):
                return False
    return False


def block_keys(text: str) -> set:
    """Frontmatter keys whose value continues onto following indented lines.

    `status:\\n  - backlog` is a perfectly good YAML block sequence, but this
    module's frontmatter helpers are line-based: rewriting the `status:` line
    alone would strand the `- backlog` item and leave unparseable YAML. Such
    keys are reported and never rewritten.
    """
    m = tn.FRONTMATTER_RE.match(text)
    if not m:
        return set()
    lines = m.group(2).splitlines()
    blocks = set()
    for i, line in enumerate(lines):
        key_match = tn.FRONTMATTER_KEY_RE.match(line)
        if not key_match:
            continue
        if _is_continuation_line(lines, i + 1):
            blocks.add(key_match.group(1))
    return blocks


def _normalise_estimate(raw: str):
    stripped = raw.strip().strip("\"'")
    m_digits = re.match(r"^([0-9]+)$", stripped)
    if m_digits:
        try:
            val = int(m_digits.group(1))
            if val > 0:
                return str(val)
        except ValueError:
            return None
    m = re.match(r"^([0-9]+)\s*(?:mins?|m)?$", stripped, re.IGNORECASE)
    if m:
        try:
            val = int(m.group(1))
            if val > 0:
                return str(val)
        except ValueError:
            return None
    return None


def set_frontmatter_value(text: str, key: str, value: str | None) -> str:
    """Rewrite one existing frontmatter key's value, leaving every other
    line — `kanban_order` included — byte-identical.
    If value is None, the line is removed from frontmatter.
    Removes all duplicate occurrences of `key` and their continuation lines.
    Atomically clears planning fields if `key == "status"` and `value == "done"`.

    Refuses (returns `text` unchanged) when the key's value continues onto
    following indented lines; see `block_keys`.
    """
    m = tn.FRONTMATTER_RE.match(text)
    if not m:
        return text
    if key in block_keys(text):
        return text

    if key in PLANNING_KEYS and parse_frontmatter(text).get("status") == "done":
        value = None

    keys_to_clear = {key}
    if key == "status" and value == "done":
        keys_to_clear.update(PLANNING_KEYS)

    lines = m.group(2).splitlines()
    new_lines = []
    emitted = False
    i = 0
    while i < len(lines):
        line = lines[i]
        key_match = tn.FRONTMATTER_KEY_RE.match(line)
        if key_match and key_match.group(1) in keys_to_clear:
            matched_key = key_match.group(1)
            if matched_key == key and value is not None and not emitted:
                new_lines.append(f"{key}: {value}".rstrip())
                emitted = True
            i += 1
            while _is_continuation_line(lines, i):
                i += 1
        else:
            new_lines.append(line)
            i += 1

    if value is not None and not emitted:
        new_lines.append(f"{key}: {value}".rstrip())

    return text[: m.start(2)] + "\n".join(new_lines) + text[m.end(2):]


def _normalise_enum(raw: str, allowed, aliases):
    """Canonical value for `raw`, or None if it can't be mapped safely."""
    candidate = re.sub(r"\s+", "-", raw.strip().strip("\"'").lower())
    if candidate in allowed:
        return candidate
    return aliases.get(candidate)


def _normalise_date(raw: str):
    stripped = raw.strip().strip("\"'")
    if ISO_DATE_RE.match(stripped):
        try:
            dt.date.fromisoformat(stripped)
            return stripped
        except ValueError:
            return None
    uk = UK_DATE_RE.match(stripped)
    if uk:
        day, month, year = (int(g) for g in uk.groups())
        try:
            return dt.date(year, month, day).isoformat()
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# Check (a) — ticket frontmatter schema
# --------------------------------------------------------------------------

def ticket_files(brain_path: Path):
    tasks_dir = brain_path / "tasks"
    if not tasks_dir.is_dir():
        return []
    return sorted(p for p in tasks_dir.rglob("*.md") if p.is_file())


def check_tickets(brain_path: Path) -> list:
    findings = []
    for path in ticket_files(brain_path):
        rel = path.relative_to(brain_path).as_posix()
        text = path.read_text()

        m = tn.FRONTMATTER_RE.match(text)
        if not m:
            continue
        fm_lines = m.group(2).splitlines()

        status_lines = []
        for line in fm_lines:
            km = tn.FRONTMATTER_KEY_RE.match(line)
            if km and km.group(1) == "status":
                status_lines.append(line.split(":", 1)[1].strip())

        if len(status_lines) == 1 and status_lines[0] == "done":
            continue

        values = parse_frontmatter(text)

        duplicate_handled_keys = set()
        key_occurrences = {}
        for line in fm_lines:
            km = tn.FRONTMATTER_KEY_RE.match(line)
            if km and km.group(1) in CONTROLLED_KEYS:
                k = km.group(1)
                v = line.split(":", 1)[1].strip()
                key_occurrences.setdefault(k, []).append(v)

        for key, raw_vals in key_occurrences.items():
            if len(raw_vals) > 1:
                duplicate_handled_keys.add(key)
                unique_non_blank = list(dict.fromkeys(v for v in raw_vals if v.strip()))

                normalized_vals = []
                for v in unique_non_blank:
                    norm = v
                    if key == "status":
                        norm = _normalise_enum(v, STATUS_VALUES, STATUS_ALIASES) or v
                    elif key == "type":
                        norm = _normalise_enum(v, TYPE_VALUES, TYPE_ALIASES) or v
                    elif key in DATE_KEYS or key == "planned_for":
                        norm = _normalise_date(v) or v
                    elif key == "planning_lane":
                        norm = _normalise_enum(v, PLANNING_LANE_VALUES, PLANNING_LANE_ALIASES) or v
                    elif key == "estimate_minutes":
                        norm = _normalise_estimate(v) or v
                    elif key in ("call_suitable", "critical"):
                        norm = _normalise_enum(v, BOOLEAN_VALUES, BOOLEAN_ALIASES) or v
                    normalized_vals.append(norm)

                unique_normalized = list(dict.fromkeys(normalized_vals))
                if len(unique_normalized) > 1:
                    findings.append(Finding(
                        "a", f"duplicate-{key}", rel,
                        f"`{key}` has duplicate contradictory values: {raw_vals}",
                        fixable=False,
                        blocked_reason=f"duplicate key `{key}` has contradictory values: {raw_vals}",
                    ))
                else:
                    canonical_val = unique_normalized[0] if unique_normalized else ""
                    if not canonical_val and key in BLANK_DEFAULTS:
                        canonical_val = BLANK_DEFAULTS[key]
                    findings.append(Finding(
                        "a", f"duplicate-{key}", rel,
                        f"`{key}` has duplicate occurrences",
                        fixable=True,
                        fix_desc=f"canonicalise duplicate {key}",
                        fix_args={"key": key, "value": canonical_val if canonical_val else None},
                    ))

        missing = tn.missing_keys(text)
        if missing:
            findings.append(Finding(
                "a", "missing-keys", rel,
                f"missing ADR-0015 key(s): {', '.join(missing)}",
                fixable=True,
                fix_desc=f"backfill {len(missing)} key(s) blank (type -> task)",
            ))

        blocks = block_keys(text)
        for key in sorted(blocks & (set(("status", "type")) | set(DATE_KEYS) | set(PLANNING_KEYS))):
            findings.append(Finding(
                "a", f"multiline-{key}", rel,
                f"`{key}` is a multi-line YAML value",
                blocked_reason="its value continues onto indented lines — rewriting "
                               "the key line alone would produce invalid YAML",
            ))

        for key, allowed, aliases in (
            ("status", STATUS_VALUES, STATUS_ALIASES),
            ("type", TYPE_VALUES, TYPE_ALIASES),
        ):
            if key not in values or key in blocks or key in duplicate_handled_keys:
                continue
            raw = values[key]
            if not raw.strip():
                findings.append(Finding(
                    "a", f"blank-{key}", rel, f"`{key}` is blank",
                    fixable=True,
                    fix_desc=f"set {key}: {BLANK_DEFAULTS[key]}",
                    fix_args={"key": key, "value": BLANK_DEFAULTS[key]},
                ))
                continue
            if raw.strip() in allowed:
                continue
            fixed = _normalise_enum(raw, allowed, aliases)
            findings.append(Finding(
                "a", f"invalid-{key}", rel,
                f"`{key}: {raw}` is not in the vocabulary {list(allowed)}",
                fixable=fixed is not None,
                fix_desc=f"set {key}: {fixed}" if fixed else None,
                blocked_reason=None if fixed else "no unambiguous vocabulary value to map it onto",
                fix_args={"key": key, "value": fixed} if fixed else None,
            ))

        for key in DATE_KEYS + ("planned_for",):
            if key in blocks or key in duplicate_handled_keys:
                continue
            raw = values.get(key, "")
            if not raw.strip():
                continue
            if ISO_DATE_RE.match(raw.strip()) and _normalise_date(raw):
                continue
            fixed = _normalise_date(raw)
            findings.append(Finding(
                "a", f"invalid-date-{key}", rel,
                f"`{key}: {raw}` is not an ISO YYYY-MM-DD date",
                fixable=fixed is not None,
                fix_desc=f"set {key}: {fixed}" if fixed else None,
                blocked_reason=None if fixed else "cannot be parsed as a date",
                fix_args={"key": key, "value": fixed} if fixed else None,
            ))

        if "planning_lane" in values and "planning_lane" not in blocks and "planning_lane" not in duplicate_handled_keys:
            raw = values["planning_lane"]
            if raw.strip():
                if raw.strip() not in PLANNING_LANE_VALUES:
                    fixed = _normalise_enum(raw, PLANNING_LANE_VALUES, PLANNING_LANE_ALIASES)
                    findings.append(Finding(
                        "a", "invalid-planning_lane", rel,
                        f"`planning_lane: {raw}` is not in the vocabulary {list(PLANNING_LANE_VALUES)}",
                        fixable=fixed is not None,
                        fix_desc=f"set planning_lane: {fixed}" if fixed else None,
                        blocked_reason=None if fixed else "no unambiguous vocabulary value to map it onto",
                        fix_args={"key": "planning_lane", "value": fixed} if fixed else None,
                    ))

        if "estimate_minutes" in values and "estimate_minutes" not in blocks and "estimate_minutes" not in duplicate_handled_keys:
            raw = values["estimate_minutes"]
            if raw.strip():
                is_valid = False
                stripped = raw.strip().strip("\"'")
                if re.match(r"^[0-9]+$", stripped):
                    try:
                        if int(stripped) > 0:
                            is_valid = True
                    except ValueError:
                        pass
                if not is_valid:
                    fixed = _normalise_estimate(raw)
                    findings.append(Finding(
                        "a", "invalid-estimate_minutes", rel,
                        f"`estimate_minutes: {raw}` is not a positive integer",
                        fixable=fixed is not None,
                        fix_desc=f"set estimate_minutes: {fixed}" if fixed else None,
                        blocked_reason=None if fixed else "cannot be parsed as a positive integer",
                        fix_args={"key": "estimate_minutes", "value": fixed} if fixed else None,
                    ))

        for bool_key in ("call_suitable", "critical"):
            if bool_key in values and bool_key not in blocks and bool_key not in duplicate_handled_keys:
                raw = values[bool_key]
                if raw.strip():
                    if raw.strip().lower() not in BOOLEAN_VALUES:
                        fixed = _normalise_enum(raw, BOOLEAN_VALUES, BOOLEAN_ALIASES)
                        findings.append(Finding(
                            "a", f"invalid-{bool_key}", rel,
                            f"`{bool_key}: {raw}` is not a boolean",
                            fixable=fixed is not None,
                            fix_desc=f"set {bool_key}: {fixed}" if fixed else None,
                            blocked_reason=None if fixed else "cannot be parsed as a boolean",
                            fix_args={"key": bool_key, "value": fixed} if fixed else None,
                        ))

    return findings


def fix_ticket_finding(brain_path: Path, finding: Finding) -> bool:
    path = brain_path / finding.path
    text = path.read_text()
    if finding.kind == "missing-keys":
        new_text = tn.backfill_frontmatter(text, tn.missing_keys(text))
    else:
        new_text = set_frontmatter_value(
            text, finding.fix_args["key"], finding.fix_args["value"])
    if new_text == text:
        return False
    path.write_text(new_text)
    return True


# --------------------------------------------------------------------------
# Check (b) — folder/naming traceability
# --------------------------------------------------------------------------

class Root:
    """One place a Project/Area slug is expected to show up.

    `enforce_case=False` marks a root whose directories are Title Case by
    vault convention (`Files/` mirrors the Areas) — traceability is still
    checked there, spelling is not.
    """

    def __init__(self, label, path, expect, enforce_case=True):
        self.label = label
        self.path = path
        self.expect = expect  # "project" | "area" | "any"
        self.enforce_case = enforce_case


def structure_roots(brain_path: Path, code_root: Path, files_root: Path) -> list:
    return [
        Root("projects", brain_path / "projects", "project"),
        Root("areas", brain_path / "areas", "area"),
        Root("tasks/projects", brain_path / "tasks" / "projects", "project"),
        Root("tasks/areas", brain_path / "tasks" / "areas", "area"),
        Root("Code/projects", code_root / "projects", "project"),
        Root("Files/projects", files_root / "projects", "project", enforce_case=False),
        Root("Files/areas", files_root / "areas", "area", enforce_case=False),
    ]


def check_structure(brain_path: Path, code_root: Path, files_root: Path,
                    slug_map: dict) -> list:
    findings = []
    for root in structure_roots(brain_path, code_root, files_root):
        for d in _child_dirs(root.path):
            display = f"{root.label}/{d.name}"
            slug = tn.slugify(d.name)
            kind = slug_map.get(slug)

            if kind is None:
                findings.append(Finding(
                    "b", "orphan", display,
                    f"slug `{slug}` has no Project or Area in the Brain",
                    blocked_reason="no canonical slug to reconcile against — needs a human decision",
                ))
            elif kind != root.expect:
                findings.append(Finding(
                    "b", "wrong-kind", display,
                    f"slug `{slug}` is an {kind} but sits under a {root.expect} root",
                    blocked_reason="moving it would change what the slug means — needs a human decision",
                ))

            if not root.enforce_case or d.name == slug:
                continue

            target = d.parent / slug
            # Renaming onto a slug that resolves to nothing — or to the wrong
            # kind of thing — would launder a real filing question into a
            # cosmetic rename, so it is reported and left alone.
            if _collides(d, target):
                blocked = (f"{root.label}/{slug} already exists — merging two "
                           f"directories is not a mechanical rename")
            elif kind != root.expect:
                blocked = (f"`{slug}` is not a {root.expect} slug in the Brain — "
                           f"resolve the orphan/wrong-kind finding first")
            else:
                blocked = None
            findings.append(Finding(
                "b", "naming-mismatch", display,
                f"directory name is not its canonical slug `{slug}`",
                fixable=blocked is None,
                fix_desc=f"rename to {root.label}/{slug}" if blocked is None else None,
                blocked_reason=blocked,
            ))
    return findings


def _collides(src: Path, dest: Path) -> bool:
    """Is `dest` a *different* directory entry than `src`?

    `dest.exists()` alone is not the question on a case-insensitive
    filesystem: APFS answers True for `…/alpha` when `…/Alpha` is the very
    directory being renamed, which would misreport every pure case-only
    drift as an unfixable collision.
    """
    if not dest.exists():
        return False
    try:
        return not os.path.samefile(src, dest)
    except OSError:
        return True


def _in_clean_git_repo(path: Path, clean_repos: set = None):
    """`(ok, reason)` — whether a rename at `path` is git-reversible.

    `clean_repos` memoises repositories already found clean earlier in the
    same run: this tool's own first rename dirties the tree, and refusing
    every later rename over dirt the tool itself created would mean only one
    rename per repo per run ever succeeded.
    """
    probe = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        return False, (
            f"{path.parent} is not inside a git repository, so a rename here "
            f"could not be reverted"
        )
    toplevel = probe.stdout.strip()
    if clean_repos is not None and toplevel in clean_repos:
        return True, None
    status = subprocess.run(
        ["git", "-C", toplevel, "status", "--porcelain"],
        capture_output=True, text=True,
    )
    if status.stdout.strip():
        return False, f"the git repository at {toplevel} has a dirty working tree"
    if clean_repos is not None:
        clean_repos.add(toplevel)
    return True, None


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def fix_structure_finding(brain_path: Path, code_root: Path, files_root: Path,
                          finding: Finding, clean_repos: set = None):
    """Rename a drifted directory to its canonical slug, then repoint the
    `[[path/form/links]]` that the move actually broke.

    A directory name and a wikilink target are different namespaces: a link
    is resolved by *note filename*, so `[[Goals OS]]` names the note
    `Goals OS.md`, not the folder `projects/Goals OS/`. Rewriting bare names
    off the back of a folder rename therefore silently repointed links that
    were valid — and left the path-form links that a folder rename genuinely
    does break (`[[projects/Goals OS/note]]`) untouched. Only path-form links
    whose leading segments are the renamed directory are rewritten, and a
    rename outside the Brain rewrites nothing at all (a link target is always
    Brain-relative, so no Brain link can name a `Code/` or `Files/` folder).

    Returns `(True, note)` on success, `(False, reason)` when the rename is
    refused — the Brain's pre-fix marker commit only protects the Brain repo,
    so a directory outside a clean git repo is reported, never moved.
    """
    label, name = finding.path.rsplit("/", 1)
    root = next(r for r in structure_roots(brain_path, code_root, files_root)
                if r.label == label)
    src = root.path / name
    dest = root.path / tn.slugify(name)
    if not src.is_dir() or _collides(src, dest):
        return False, "source vanished or destination now exists"

    inside_brain = _is_inside(src, brain_path)
    if not inside_brain:
        # The Brain's own pre-fix marker commit already makes every
        # Brain-internal rename revertible, so only foreign trees need their
        # own reversibility proof.
        ok, reason = _in_clean_git_repo(src, clean_repos)
        if not ok:
            return False, reason

    src.rename(dest)
    note = f"renamed to {label}/{dest.name}"
    if inside_brain:
        old_rel = src.resolve().relative_to(brain_path.resolve()).as_posix()
        new_rel = dest.resolve().relative_to(brain_path.resolve()).as_posix()
        rewritten = rewrite_path_links(brain_path, old_rel, new_rel)
        if rewritten:
            note += f"; repointed path links in {rewritten} note(s)"
    return True, note


# --------------------------------------------------------------------------
# Check (c) — cross-note integrity
# --------------------------------------------------------------------------

def brain_notes(brain_path: Path):
    for path in sorted(brain_path.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES or part.startswith(".")
               for part in path.relative_to(brain_path).parts):
            continue
        yield path


def is_writable(brain_path: Path, path: Path) -> bool:
    """False for the Brain's immutable record (`archive/`, `inbox/raw/`).

    Those files are still *indexed and checked* — a broken link in the
    archive is worth knowing about — but no repair may rewrite one, so the
    audit trail stays byte-identical to what was filed.
    """
    rel = path.relative_to(brain_path).as_posix()
    return not any(rel == root or rel.startswith(root + "/")
                   for root in IMMUTABLE_ROOTS)


def build_link_index(brain_path: Path) -> dict:
    """`{lowercased link target: {actual stems}}`.

    Obsidian resolves a wikilink by bare filename anywhere in the vault, but
    a link may equally be written as a vault-relative path, with or without
    the `.md` extension (`[[people/Amy Collins.md]]`) — all three spellings
    are live in this Brain, so all three are indexed.
    """
    index = {}
    for path in brain_notes(brain_path):
        rel = path.relative_to(brain_path)
        for key in (path.name, path.stem,
                    rel.as_posix(), rel.with_suffix("").as_posix()):
            index.setdefault(key.lower(), set()).add(path.stem)
    return index


def _mask_inline_code(line: str) -> str:
    """`line` with every inline-code span blanked to same-length filler.

    Offsets are preserved, so a match on the masked line indexes straight
    back into the real one.
    """
    return INLINE_CODE_RE.sub(lambda m: "\x00" * len(m.group(0)), line)


def iter_link_matches(text: str):
    """`(lineno, match, line_offset)` for every wikilink in live prose.

    The single place that decides what counts as a link. Excluded: YAML
    frontmatter (rewriting a value there is a YAML edit, not a prose edit),
    fenced code blocks and inline code (documentation of the syntax, not
    references). Detection and repair both walk this, so a link the scan
    ignores can never be rewritten by the fixer, and vice versa.
    """
    m = tn.FRONTMATTER_RE.match(text)
    body_start = m.end() if m else 0
    in_fence = False
    pos = 0
    for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
        line_start, pos = pos, pos + len(line)
        if line_start < body_start:
            continue
        bare = line.rstrip("\n")
        if FENCE_RE.match(bare.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in WIKILINK_RE.finditer(_mask_inline_code(bare)):
            yield lineno, match, line_start


def iter_wikilinks(text: str):
    """`(target, line_number)` for every wikilink this tool considers real."""
    for lineno, match, _offset in iter_link_matches(text):
        target = match.group(1).strip()
        if target:
            yield target, lineno


def rewrite_links_in_text(text: str, sub) -> str:
    """Apply `sub(match) -> replacement or None` to exactly the links
    `iter_link_matches` yields, splicing by absolute offset."""
    out = []
    last = 0
    for _lineno, match, offset in iter_link_matches(text):
        replacement = sub(match)
        if replacement is None:
            continue
        start, end = offset + match.start(), offset + match.end()
        out.append(text[last:start])
        out.append(replacement)
        last = end
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


def check_links(brain_path: Path, slug_map: dict) -> list:
    index = build_link_index(brain_path)
    findings = []

    for path in brain_notes(brain_path):
        if path.suffix != ".md":
            continue
        rel = path.relative_to(brain_path).as_posix()
        writable = is_writable(brain_path, path)
        seen = set()
        for target, lineno in iter_wikilinks(path.read_text(errors="replace")):
            if target.lower() in index or target in seen:
                continue
            seen.add(target)
            candidates = index.get(tn.slugify(target), set())
            fixed = next(iter(candidates)) if len(candidates) == 1 else None
            if fixed and not writable:
                blocked = ("this file is part of the Brain's immutable record "
                           "and is never rewritten")
            elif fixed:
                blocked = None
            else:
                blocked = "no single unambiguous note to repoint at"
            findings.append(Finding(
                "c", "broken-wikilink", f"{rel}:{lineno}",
                f"[[{target}]] resolves to no note in the Brain",
                fixable=blocked is None,
                fix_desc=f"repoint to [[{fixed}]]" if blocked is None else None,
                blocked_reason=blocked,
                fix_args={"old": target, "new": fixed, "line": lineno} if blocked is None else None,
            ))

    for path in ticket_files(brain_path):
        parts = path.relative_to(brain_path).parts
        if len(parts) < 4 or parts[0] != "tasks" or parts[1] not in ("projects", "areas"):
            continue
        slug = parts[2]
        expect = "project" if parts[1] == "projects" else "area"
        if slug_map.get(slug) != expect:
            findings.append(Finding(
                "c", "ticket-orphan-parent", path.relative_to(brain_path).as_posix(),
                f"filed under `{parts[1]}/{slug}` but no such {expect} exists in the Brain",
                blocked_reason="needs a human decision about which Project/Area owns it",
            ))
    return findings


def rewrite_path_links(brain_path: Path, old_rel: str, new_rel: str) -> int:
    """Repoint path-form `[[old/dir/note]]` links after a directory rename.

    Only links whose leading path segments *are* the renamed directory are
    touched. A bare `[[Note]]` is never rewritten here: it names a note
    filename, which a directory rename does not change.
    """
    prefix = old_rel.lower() + "/"
    changed = 0
    for path in brain_notes(brain_path):
        if path.suffix != ".md" or not is_writable(brain_path, path):
            continue
        text = path.read_text(errors="replace")

        def _sub(m):
            target = m.group(1).strip()
            if not target.lower().startswith(prefix):
                return None
            repointed = new_rel + target[len(old_rel):]
            return f"[[{repointed}{m.group(2) or ''}{m.group(3) or ''}]]"

        new_text = rewrite_links_in_text(text, _sub)
        if new_text != text:
            path.write_text(new_text)
            changed += 1
    return changed


def fix_link_finding(brain_path: Path, finding: Finding) -> bool:
    """Repoint every occurrence of this broken target within the one file
    the finding names — a finding is raised once per (file, target), so
    repairing only the first line number would leave later repeats broken.

    Rewrites exactly the links `check_links` looked at, so a `[[…]]` inside
    a fence, inline code or frontmatter is left alone even when the same
    spelling was flagged in live prose elsewhere in the file.
    """
    path = brain_path / finding.path.rsplit(":", 1)[0]
    if not is_writable(brain_path, path):
        return False
    old = finding.fix_args["old"]
    new = finding.fix_args["new"]
    text = path.read_text(errors="replace")

    def _sub(m):
        if m.group(1).strip().lower() != old.lower():
            return None
        return f"[[{new}{m.group(2) or ''}{m.group(3) or ''}]]"

    new_text = rewrite_links_in_text(text, _sub)
    if new_text == text:
        return False
    path.write_text(new_text)
    return True


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def scan(brain_path: Path, code_root: Path, files_root: Path) -> list:
    slug_map = build_slug_map(brain_path)
    return (
        check_tickets(brain_path)
        + check_structure(brain_path, code_root, files_root, slug_map)
        + check_links(brain_path, slug_map)
        + check_caveats(brain_path)
    )


def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


# --------------------------------------------------------------------------
# Check (d) — CLAUDE.md caveat expiry
# --------------------------------------------------------------------------

def claude_md_files(brain_path: Path):
    """Every `CLAUDE.md` in the Brain — the always-loaded-context surface.

    Scoped to that filename on purpose. A conditional sentence in an ordinary
    note is prose a reader chooses to open; the same sentence in a `CLAUDE.md`
    is a standing instruction every agent is handed unasked, and that is the
    only place a caveat can outlive its cause without anyone noticing.
    """
    return sorted(p for p in brain_notes(brain_path) if p.name == "CLAUDE.md")


def iter_caveats(text: str):
    """`(line, lineno, [wikilink targets])` for each `**Caveat**` line.

    The marker is the whole mechanism: caveats are only greppable if they are
    *marked*, and sniffing for "not yet"/"wait for" prose would misfire on
    every sentence that merely describes one.

    Fenced blocks are skipped, and inline code is masked before the line is
    read, so a marker that is being *discussed* rather than *declared* does not
    trip the check — `**Caveat**` in backticks is documentation. (The live Brain
    caught this the moment the convention was written down: the sentence
    explaining the token flagged itself.) Masking preserves offsets, so a
    genuine caveat about a code symbol is still found on the same line.
    """
    in_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(raw.strip()):
            in_fence = not in_fence
            continue
        line = _mask_inline_code(raw)
        if in_fence or CAVEAT_MARKER not in line:
            continue
        targets = [m.group(1).strip() for m in WIKILINK_RE.finditer(line)]
        yield raw, lineno, targets


def _ticket_status(brain_path: Path, target: str):
    """The `status:` of the ticket a caveat names, or None if it names no
    ticket. Resolved the way Obsidian resolves a wikilink — by bare filename
    — but restricted to `tasks/`, because only a ticket has a status that can
    ever clear the caveat."""
    stem = target.split("/")[-1].removesuffix(".md").lower()
    for path in ticket_files(brain_path):
        if path.stem.lower() == stem:
            return parse_frontmatter(path.read_text(errors="replace")).get("status", "")
    return None


def check_caveats(brain_path: Path) -> list:
    """Caveats in always-loaded context that can no longer expire on their own.

    A `CLAUDE.md` caveat must name the ticket that clears it, so a stale one
    surfaces itself instead of waiting for an agent to notice mid-way through
    unrelated work. Nothing here is ever auto-repaired: removing a caveat means
    rewriting the prose around it, and judging whether the surrounding sentence
    still says something true. That is a human's call, so check (d) reports and
    stops. (`apply_fixes` only routes checks (a)/(b)/(c), so this is structural,
    not merely conventional.)
    """
    findings = []
    for path in claude_md_files(brain_path):
        rel = path.relative_to(brain_path).as_posix()
        for _line, lineno, targets in iter_caveats(path.read_text(errors="replace")):
            where = f"{rel}:{lineno}"
            statuses = {t: _ticket_status(brain_path, t) for t in targets}
            tickets = {t: s for t, s in statuses.items() if s is not None}

            if not targets:
                findings.append(Finding(
                    "d", "caveat-unlinked", where,
                    "caveat names no clearing ticket, so nothing can ever expire it",
                    blocked_reason="a human must say which ticket clears it",
                ))
                continue
            if not tickets:
                named = ", ".join(f"[[{t}]]" for t in targets)
                findings.append(Finding(
                    "d", "caveat-unresolved-ticket", where,
                    f"caveat links {named}, which is not a ticket under `tasks/` — "
                    "it has no status that could clear the caveat",
                    blocked_reason="a human must say which ticket clears it",
                ))
                continue

            done = [t for t, s in tickets.items() if s.strip().lower() == "done"]
            if done and len(done) == len(tickets):
                named = ", ".join(f"[[{t}]]" for t in done)
                findings.append(Finding(
                    "d", "caveat-expired", where,
                    f"caveat is still live but {named} is `status: done` — "
                    "it may now be stale, and stale caveats obstruct",
                    blocked_reason="removing a caveat rewrites prose — needs a human",
                ))
    return findings


def guard_brain_repo(brain_path: Path):
    """Refuse to apply against a non-repo or dirty Brain working tree."""
    probe = _git(brain_path, "rev-parse", "--show-toplevel")
    if probe.returncode != 0:
        raise RuntimeError(
            f"{brain_path} is not a git repository — refusing to apply fixes, "
            f"because folder renames would not be revertible."
        )
    status = _git(brain_path, "status", "--porcelain")
    if status.stdout.strip():
        raise RuntimeError(
            "Brain working tree is dirty — refusing to apply fixes.\n"
            "Commit or stash your changes first, so the pre-fix commit is a "
            "clean revert point:\n"
            f"  git -C \"{brain_path}\" status"
        )


def marker_commit(brain_path: Path, now: dt.datetime) -> str:
    """Lay down the pre-fix marker commit and return its short SHA — the
    one-command revert point the ticket's safety guard requires."""
    message = f"Pre-fix checkpoint — schema enforce {now.strftime('%Y-%m-%d %H:%M')}"
    commit = _git(brain_path, "commit", "--allow-empty", "-m", message)
    if commit.returncode != 0:
        raise RuntimeError(f"pre-fix commit failed: {commit.stderr.strip()}")
    return _git(brain_path, "rev-parse", "--short", "HEAD").stdout.strip()


def commit_fixes(brain_path: Path, now: dt.datetime, changes: list):
    """Commit what this run wrote, so the next `--apply` meets a clean tree.

    Without this the tool's own output is the dirt that makes run 2 abort.
    """
    if _git(brain_path, "add", "-A").returncode != 0:
        return None
    if not _git(brain_path, "status", "--porcelain").stdout.strip():
        return None
    message = (f"Schema enforce — {len(changes)} fix(es) "
               f"{now.strftime('%Y-%m-%d %H:%M')}")
    commit = _git(brain_path, "commit", "-m", message)
    if commit.returncode != 0:
        raise RuntimeError(f"post-fix commit failed: {commit.stderr.strip()}")
    return _git(brain_path, "rev-parse", "--short", "HEAD").stdout.strip()


def apply_fixes(brain_path: Path, code_root: Path, files_root: Path,
                findings: list):
    """Apply every fixable finding. Structure renames run first — they move
    the files the other checks name.

    Because a rename invalidates the display paths of every (a)/(c) finding
    underneath it, the (a)/(c) half is **re-derived against the mutated tree**
    once any rename lands: otherwise those findings point at paths that no
    longer exist (the repair then fails into `blocked_reason` while the run
    still reports success), and a `ticket-orphan-parent` raised for a
    directory the same run was about to rename would be a false positive.

    Returns `(changes, findings)` — change-log lines, one per file actually
    changed, and the finding list the report should show.
    """
    changes = []
    clean_repos = set()
    structure = [f for f in findings if f.check == "b" and f.fixable]
    renamed = False
    for finding in structure:
        try:
            ok, note = fix_structure_finding(brain_path, code_root, files_root,
                                             finding, clean_repos)
            if ok:
                changes.append(f"{finding.path}: {note}")
                renamed = True
            else:
                finding.fixable = False
                finding.blocked_reason = note
        except OSError as exc:
            finding.fixable = False
            finding.blocked_reason = f"failed: {exc}"

    if renamed:
        fresh = scan(brain_path, code_root, files_root)
        findings = ([f for f in findings if f.check == "b"]
                    + [f for f in fresh if f.check != "b"])

    for finding in [f for f in findings if f.check in ("a", "c") and f.fixable]:
        try:
            ok = (fix_ticket_finding(brain_path, finding) if finding.check == "a"
                  else fix_link_finding(brain_path, finding))
            if ok:
                changes.append(f"{finding.path}: {finding.fix_desc}")
        except OSError as exc:
            finding.fixable = False
            finding.blocked_reason = f"failed: {exc}"
    return changes, findings


def write_change_log(log_file: Path, now: dt.datetime, marker: str,
                     changes: list, unfixable: list) -> Path:
    log_file = Path(log_file).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"=== {now.strftime('%Y-%m-%d %H:%M')} — schema enforce (apply) ===",
        f"pre-fix commit: {marker}",
        f"fixed: {len(changes)}  unfixable: {len(unfixable)}",
    ]
    lines += [f"  FIXED     {c}" for c in changes]
    lines += [f"  UNFIXABLE {f.line()}" for f in unfixable]
    with log_file.open("a") as handle:
        handle.write("\n".join(lines) + "\n")
    return log_file


def log_to_action_log(brain_path: Path, now: dt.datetime, marker: str,
                      changes: list, unfixable: list, actor: str, trigger: str):
    entry = log_action.build_entry(
        actor=actor,
        trigger=trigger,
        # `ticket-normalize` is the existing registered-in-practice type for
        # mechanical conformance repair of the Brain's own structure; no new
        # type is invented here.
        action_type="ticket-normalize",
        action=(
            f"Schema/structure enforce: fixed {len(changes)} item(s), "
            f"{len(unfixable)} left for a human. Pre-fix commit {marker}."
        ),
        confidence="High",
        outcome=f"{len(changes)} fix(es) applied; revert with git reset --hard {marker}",
        input_link="tasks/",
        time_str=now.strftime("%H:%M"),
    )
    return log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)


def run(brain_path: Path, code_root: Path, files_root: Path, apply: bool = False,
        log_file=DEFAULT_LOG_FILE, now: dt.datetime = None,
        actor: str = "EA", trigger: str = "Schema enforce") -> dict:
    now = now or dt.datetime.now()
    findings = scan(brain_path, code_root, files_root)
    result = {"findings": findings, "applied": False, "changes": [], "marker": None}
    if not apply:
        return result

    guard_brain_repo(brain_path)
    if not any(f.fixable for f in findings):
        # Nothing to repair: no marker commit, no change log, no Action Log
        # entry. A nightly `--apply` on a conforming Brain must be a no-op,
        # not 365 empty commits and 365 log entries a year.
        return result

    marker = marker_commit(brain_path, now)
    changes, findings = apply_fixes(brain_path, code_root, files_root, findings)
    unfixable = [f for f in findings if not f.fixable]
    write_change_log(log_file, now, marker, changes, unfixable)
    log_to_action_log(brain_path, now, marker, changes, unfixable, actor, trigger)
    commit_fixes(brain_path, now, changes)
    result.update({"applied": True, "changes": changes, "marker": marker,
                   "findings": findings})
    return result


def format_report(findings: list, applied: bool) -> str:
    if not findings:
        return "No schema or structure findings."
    labels = {"a": "(a) ticket frontmatter", "b": "(b) folder/naming",
              "c": "(c) cross-note integrity", "d": "(d) CLAUDE.md caveat expiry"}
    out = []
    for check in ("a", "b", "c", "d"):
        group = [f for f in findings if f.check == check]
        if not group:
            continue
        out.append(f"\n{labels[check]} — {len(group)} finding(s)")
        for finding in group:
            out.append(f"  {finding.line()}")
    fixable = sum(1 for f in findings if f.fixable)
    verb = "Applied" if applied else "Fixable"
    out.append(f"\n{len(findings)} finding(s); {verb}: {fixable}; "
               f"needs a human: {len(findings) - fixable}")
    if not applied:
        out.append("Report mode (default) — nothing was written. Re-run with --apply to repair.")
    return "\n".join(out)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--code-root", default=None,
                   help="Code/ tree root (default: <brain>/../Code)")
    p.add_argument("--files-root", default=None,
                   help="Files/ tree root (default: <brain>/../Files)")
    p.add_argument("--log-file", default=DEFAULT_LOG_FILE,
                   help=f"Change log path (default: {DEFAULT_LOG_FILE})")
    p.add_argument("--apply", action="store_true",
                   help="Repair what can be repaired. Off by default — this "
                        "tool renames folders, so a bare run only reports.")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit no-op flag; report mode is already the default.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")
    if args.apply and args.dry_run:
        sys.exit("--apply and --dry-run are mutually exclusive.")

    code_root = Path(args.code_root).expanduser() if args.code_root else brain_path.parent / "Code"
    files_root = Path(args.files_root).expanduser() if args.files_root else brain_path.parent / "Files"

    try:
        result = run(brain_path, code_root, files_root, apply=args.apply,
                     log_file=args.log_file)
    except RuntimeError as exc:
        sys.exit(str(exc))

    print(format_report(result["findings"], result["applied"] or args.apply))
    if result["applied"]:
        print(f"\nPre-fix commit {result['marker']} — revert with: "
              f"git -C \"{brain_path}\" reset --hard {result['marker']}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
