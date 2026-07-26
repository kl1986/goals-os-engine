#!/usr/bin/env python3
"""Goals OS schema and structure enforcer — three checks, one tool.

Implements the `goals-os-schema-and-structure-enforcer` ticket's decisions
(25/07/2026). Pure Python, zero LLM calls, same house shape as
`triage.py` / `version_control.py` (argparse, `--brain`).

Three checks, all resolved against **one canonical slug map** derived from
the Brain's `projects/<slug>/` and `areas/<slug>/` directories:

**(a) Ticket frontmatter schema** — every `tasks/**/*.md` carries the full
ADR-0015 key set, `status` is in the ADR-0025 vocabulary, `type` is in the
ADR-0015 vocabulary, and any non-blank `created`/`resolved` is a valid ISO
date. `kanban_order` is Base Board-managed and is never read for
conformance, never written, and never normalised.

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

## Modes

`--dry-run` (the **default**) reports and writes nothing at all — no Brain
writes, no change log, no Action Log entry. `--apply` opts in to repair.
The ticket's "auto-fix always" governs the tool's *capability* (it repairs
in one pass rather than being a report-only linter); a bare invocation is
still inert, because this thing renames folders.

## Safety guard (required by the ticket)

`--apply` refuses to run against a **dirty** Brain working tree, and
otherwise lays down an empty marker commit immediately before the first fix
so any bad move is a one-command `git reset --hard <sha>`.

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

SKIP_DIR_NAMES = {".git", ".obsidian", "__pycache__", ".trash", "node_modules"}


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


def set_frontmatter_value(text: str, key: str, value: str) -> str:
    """Rewrite one existing frontmatter key's value, leaving every other
    line — `kanban_order` included — byte-identical."""
    m = tn.FRONTMATTER_RE.match(text)
    if not m:
        return text
    lines = m.group(2).splitlines()
    for i, line in enumerate(lines):
        key_match = tn.FRONTMATTER_KEY_RE.match(line)
        if key_match and key_match.group(1) == key:
            lines[i] = f"{key}: {value}".rstrip()
            break
    else:
        return text
    return text[: m.start(2)] + "\n".join(lines) + text[m.end(2):]


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

        missing = tn.missing_keys(text)
        if missing:
            findings.append(Finding(
                "a", "missing-keys", rel,
                f"missing ADR-0015 key(s): {', '.join(missing)}",
                fixable=True,
                fix_desc=f"backfill {len(missing)} key(s) blank (type -> task)",
            ))

        values = parse_frontmatter(text)
        for key, allowed, aliases in (
            ("status", STATUS_VALUES, STATUS_ALIASES),
            ("type", TYPE_VALUES, TYPE_ALIASES),
        ):
            if key not in values:
                continue  # already reported as a missing key
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

        for key in DATE_KEYS:
            raw = values.get(key, "")
            if not raw.strip():
                continue  # blank is legitimate (an unresolved ticket)
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
            if target.exists():
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


def _in_clean_git_repo(path: Path):
    """`(ok, reason)` — whether a rename at `path` is git-reversible."""
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
    status = subprocess.run(
        ["git", "-C", toplevel, "status", "--porcelain"],
        capture_output=True, text=True,
    )
    if status.stdout.strip():
        return False, f"the git repository at {toplevel} has a dirty working tree"
    return True, None


def fix_structure_finding(brain_path: Path, code_root: Path, files_root: Path,
                          finding: Finding):
    """Rename a drifted directory to its canonical slug, then rewrite every
    inbound `[[wikilink]]` in the Brain that named the old directory.

    Returns `(True, note)` on success, `(False, reason)` when the rename is
    refused — the Brain's pre-fix marker commit only protects the Brain repo,
    so a directory outside a clean git repo is reported, never moved.
    """
    label, name = finding.path.rsplit("/", 1)
    root = next(r for r in structure_roots(brain_path, code_root, files_root)
                if r.label == label)
    src = root.path / name
    dest = root.path / tn.slugify(name)
    if not src.is_dir() or dest.exists():
        return False, "source vanished or destination now exists"

    ok, reason = _in_clean_git_repo(src)
    if not ok:
        return False, reason

    src.rename(dest)
    rewritten = rewrite_wikilink_targets(brain_path, {name: dest.name})
    note = f"renamed to {label}/{dest.name}"
    if rewritten:
        note += f"; rewrote {rewritten} inbound wikilink(s)"
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


def iter_wikilinks(text: str):
    """`(target, line_number)` for every wikilink outside a fenced code
    block. Links inside fences are documentation of syntax, not references."""
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in WIKILINK_RE.finditer(line):
            target = m.group(1).strip()
            if target:
                yield target, lineno


def check_links(brain_path: Path, slug_map: dict) -> list:
    index = build_link_index(brain_path)
    findings = []

    for path in brain_notes(brain_path):
        if path.suffix != ".md":
            continue
        rel = path.relative_to(brain_path).as_posix()
        seen = set()
        for target, lineno in iter_wikilinks(path.read_text(errors="replace")):
            if target.lower() in index or target in seen:
                continue
            seen.add(target)
            candidates = index.get(tn.slugify(target), set())
            fixed = next(iter(candidates)) if len(candidates) == 1 else None
            findings.append(Finding(
                "c", "broken-wikilink", f"{rel}:{lineno}",
                f"[[{target}]] resolves to no note in the Brain",
                fixable=fixed is not None,
                fix_desc=f"repoint to [[{fixed}]]" if fixed else None,
                blocked_reason=None if fixed else "no single unambiguous note to repoint at",
                fix_args={"old": target, "new": fixed, "line": lineno} if fixed else None,
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


def rewrite_wikilink_targets(brain_path: Path, mapping: dict) -> int:
    """Repoint `[[old]]` -> `[[new]]` across every note, preserving any
    `#heading` and `|alias` the link carried. Returns the file count."""
    lowered = {k.lower(): v for k, v in mapping.items()}
    changed = 0
    for path in brain_notes(brain_path):
        if path.suffix != ".md":
            continue
        text = path.read_text(errors="replace")

        def _sub(m):
            target = m.group(1).strip()
            new = lowered.get(target.lower())
            if new is None:
                return m.group(0)
            return f"[[{new}{m.group(2) or ''}{m.group(3) or ''}]]"

        new_text = WIKILINK_RE.sub(_sub, text)
        if new_text != text:
            path.write_text(new_text)
            changed += 1
    return changed


def fix_link_finding(brain_path: Path, finding: Finding) -> bool:
    """Repoint every occurrence of this broken target within the one file
    the finding names — a finding is raised once per (file, target), so
    repairing only the first line number would leave later repeats broken."""
    path = brain_path / finding.path.rsplit(":", 1)[0]
    old = finding.fix_args["old"]
    new = finding.fix_args["new"]
    text = path.read_text(errors="replace")

    def _sub(m):
        if m.group(1).strip().lower() != old.lower():
            return m.group(0)
        return f"[[{new}{m.group(2) or ''}{m.group(3) or ''}]]"

    new_text = WIKILINK_RE.sub(_sub, text)
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
    )


def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def guard_brain_repo(brain_path: Path, now: dt.datetime) -> str:
    """Refuse a dirty tree; otherwise lay down the pre-fix marker commit.

    Returns the marker commit's short SHA — the one-command revert point
    the ticket's safety guard requires (`git reset --hard <sha>`).
    """
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
    message = f"Pre-fix checkpoint — schema enforce {now.strftime('%Y-%m-%d %H:%M')}"
    commit = _git(brain_path, "commit", "--allow-empty", "-m", message)
    if commit.returncode != 0:
        raise RuntimeError(f"pre-fix commit failed: {commit.stderr.strip()}")
    return _git(brain_path, "rev-parse", "--short", "HEAD").stdout.strip()


def apply_fixes(brain_path: Path, code_root: Path, files_root: Path,
                findings: list) -> list:
    """Apply every fixable finding. Structure renames run first — they move
    the files the other checks name, so a later pass would go stale.
    Returns change-log lines, one per file actually changed."""
    changes = []
    ordered = (
        [f for f in findings if f.check == "b" and f.fixable]
        + [f for f in findings if f.check == "a" and f.fixable]
        + [f for f in findings if f.check == "c" and f.fixable]
    )
    for finding in ordered:
        try:
            if finding.check == "b":
                ok, note = fix_structure_finding(brain_path, code_root, files_root, finding)
                if ok:
                    changes.append(f"{finding.path}: {note}")
                else:
                    finding.fixable = False
                    finding.blocked_reason = note
                continue
            if finding.check == "a":
                ok = fix_ticket_finding(brain_path, finding)
            else:
                ok = fix_link_finding(brain_path, finding)
            if ok:
                changes.append(f"{finding.path}: {finding.fix_desc}")
        except OSError as exc:
            finding.fixable = False
            finding.blocked_reason = f"failed: {exc}"
    return changes


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

    marker = guard_brain_repo(brain_path, now)
    changes = apply_fixes(brain_path, code_root, files_root, findings)
    unfixable = [f for f in findings if not f.fixable]
    write_change_log(log_file, now, marker, changes, unfixable)
    log_to_action_log(brain_path, now, marker, changes, unfixable, actor, trigger)
    result.update({"applied": True, "changes": changes, "marker": marker})
    return result


def format_report(findings: list, applied: bool) -> str:
    if not findings:
        return "No schema or structure findings."
    labels = {"a": "(a) ticket frontmatter", "b": "(b) folder/naming", "c": "(c) cross-note integrity"}
    out = []
    for check in ("a", "b", "c"):
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

    print(format_report(result["findings"], result["applied"]))
    if result["applied"]:
        print(f"\nPre-fix commit {result['marker']} — revert with: "
              f"git -C \"{brain_path}\" reset --hard {result['marker']}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
