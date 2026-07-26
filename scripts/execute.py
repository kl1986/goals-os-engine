#!/usr/bin/env python3
"""Execute an approved Triage Plan's ticked rows.

Implements protocols/execute.md's minimal generic action type: exactly two
internal/reversible actions, `file-capture` and `discard-capture` — no
Area/Capability agent dispatch (Phase 3), no auto-execute on confidence
(graduation is Phase 5). Every row must already carry an explicit `[x]`
tick; unticked rows are left untouched for a future run.

Optional per-source hook (ticket 14): after a capture is filed or discarded
(and moved to archive/inbox/<source>/), Execute checks whether that source's
plugin folder in goals-os-library defines an `execute_hook.py` and, if so,
calls it with the archived capture's path and outcome. This is the only
extension point where a source-specific side effect (e.g. email's Gmail
archive) can run — see `_run_source_execute_hook()`. Most sources have no
hook; Execute itself stays fully generic and never imports/knows about any
plugin directly.
"""

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import log_action  # noqa: E402
import md_sections  # noqa: E402

# The `rule` column (8th, between `confidence` and `approve`) is a
# breaking schema change from the 7-column Triage Plan shape — a
# pre-change row without it simply won't match this regex and will be
# silently skipped by parse_plan_rows(). This is an intentional choice,
# not an oversight: the real Brain's inbox/triage/ was verified empty at
# merge time (no in-flight plans to preserve), so no graceful-fallback
# parsing was built. If a Brain with in-flight pre-change plans ever
# adopts this version, those plans' rows won't parse until hand-migrated
# to add a `rule` column (use `—` for every existing row — they predate
# rule-identifier tracking).
ROW_RE = re.compile(
    r'^\|\s*(?P<n>\d+)\s*\|\s*\[\[(?P<capture>[^\]]+)\]\]\s*\|\s*(?P<preview>.*?)\s*\|'
    r'\s*(?P<route>Pass [AB])\s*\|\s*(?P<destination>.*?)\s*\|\s*(?P<confidence>.*?)\s*\|'
    r'\s*(?P<rule>.*?)\s*\|'
    r'\s*(?P<approve>\[[ x]\](?:\s*\((?:done|dispatched)\))?)\s*\|\s*$'
)
FRONTMATTER_STATUS_RE = re.compile(r'^status:\s*\S+\s*$', re.MULTILINE)


class ExecuteError(Exception):
    pass


def action_type_for(destination: str) -> str:
    cleaned = destination.strip().lower()
    if cleaned.startswith("agent:"):
        return "agent-dispatched"
    if cleaned == "discard":
        return "discard-capture"
    if cleaned == "today":
        return "file-capture-today"
    return "file-capture"


def split_destination(destination: str) -> tuple:
    """Split a `file-capture` destination into `(file_path, heading)`.

    `heading` is `None` for a plain file destination — existing behavior,
    a blind end-of-file append. A `file#heading` destination (e.g.
    `people/Kat.md#🗣️ To Discuss`) targets a specific `## heading`
    section: content is inserted before the next heading, never appended
    blindly at EOF (protocols/execute.md, ticket 09's generalization of
    `file-capture-today`'s existing insert-before-heading mechanic to any
    file/heading, not just today's daily note)."""
    if "#" in destination:
        file_path, heading = destination.split("#", 1)
        return file_path.strip(), heading.strip()
    return destination.strip(), None


def parse_plan_rows(text: str) -> list:
    """Return every table row as a dict, in file order. Pure — no I/O."""
    rows = []
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if m:
            rows.append(m.groupdict())
    return rows


def _mark_done(line: str, match: re.Match) -> str:
    start, end = match.span("approve")
    return line[:start] + "[x] (done)" + line[end:]


def _mark_dispatched(line: str, match: re.Match) -> str:
    start, end = match.span("approve")
    return line[:start] + "[x] (dispatched)" + line[end:]


def resolve_library_path(explicit: str | None = None) -> Path:
    """goals-os-library checkout, to look up an optional per-source
    execute_hook.py (ticket 14). Precedence: explicit --library-path >
    $GOALS_OS_LIBRARY_PATH > sibling-repo convention (goals-os-library next
    to this engine's own repo checkout — the documented
    Code/projects/Goals OS/{goals-os-engine,goals-os-library} topology,
    mirrored from fetch.py's own reverse lookup of goals-os-engine). Never
    required to exist — most sources have no hook."""
    candidate = explicit or os.environ.get("GOALS_OS_LIBRARY_PATH")
    if candidate:
        return Path(candidate).expanduser().resolve()
    engine_repo_root = Path(__file__).resolve().parent.parent
    return engine_repo_root.parent / "goals-os-library"


def _run_source_execute_hook(
    source: str, raw_path: Path, outcome: str, destination: str,
    config_dir: Path, library_path: Path,
) -> None:
    """Optional per-source side effect, run only if that source's plugin
    folder defines execute_hook.py (e.g. email/execute_hook.py — ticket 14:
    Gmail archiving fires only once a Triage row is actually filed or
    discarded, never at sweep time). A no-op for every source without one.
    A hook failure is logged but never blocks Execute — the capture's own
    file-write/archive-move has already happened by this point.

    `destination` is the Triage row's own destination cell, forwarded as
    `--destination` so a hook can honour the answer the user already gave by
    ticking the row instead of re-deriving it and producing a second,
    uncoordinated answer (execute.md v1.3). It is always passed — the caller
    substitutes the literal `discard` for a discard row — so a hook may read
    it unconditionally rather than branching on its absence. Forwarding a
    string Execute has already parsed gives Execute no source-specific
    knowledge."""
    hook = library_path / "plugins" / "claude-code" / "skills" / source / "execute_hook.py"
    if not hook.exists():
        return
    try:
        subprocess.run(
            [sys.executable, str(hook),
             "--config-dir", str(config_dir),
             "--raw-capture", str(raw_path),
             "--outcome", outcome,
             "--destination", destination],
            check=False,
        )
    except OSError as e:
        print(f"  ! source hook for {source!r} failed to run: {e}", file=sys.stderr)


def _move_collision_safe(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    counter = 2
    while dest.exists():
        dest = dest_dir / f"{src.stem}-{counter}{src.suffix}"
        counter += 1
    src.rename(dest)
    return dest


def _insert_before_next_heading(text: str, heading: str, entry_line: str) -> str:
    """Insert `entry_line` as the last line of the `## {heading}` section
    (before the next `## ` heading, or EOF if it's the last section) —
    never a blind end-of-file append.

    Shared by `file-capture-today` (fixed heading, today's daily note)
    and a `file#heading`-form `file-capture` destination (any file, any
    heading) — the same mechanic generalized rather than duplicated
    (ticket 09 / protocols/execute.md)."""
    pattern = re.compile(
        md_sections.SECTION_BODY.format(re.escape(heading)), re.MULTILINE | re.DOTALL
    )
    match = pattern.search(text)
    if not match:
        return None
    body = match.group(1)
    if body and not body.endswith("\n"):
        body += "\n"
    body += entry_line
    return text[:match.start(1)] + body + text[match.end(1):]


def _file_capture(brain_path: Path, destination_rel: str, entry_line: str):
    file_rel, heading = split_destination(destination_rel)
    dest_path = brain_path / file_rel

    if heading:
        if not dest_path.exists():
            raise ExecuteError(
                f"Destination file does not exist: {dest_path} "
                "— a file#heading destination never creates the file."
            )
        text = dest_path.read_text()
        new_text = _insert_before_next_heading(text, heading, entry_line)
        if new_text is None:
            raise ExecuteError(
                f"Destination file has no '## {heading}' section: {dest_path}"
            )
        dest_path.write_text(new_text)
        return

    if not dest_path.parent.is_dir():
        raise ExecuteError(
            f"Destination directory does not exist: {dest_path.parent} "
            "— Execute never creates a new area/project."
        )
    if dest_path.exists():
        with dest_path.open("a") as f:
            f.write(entry_line)
    else:
        dest_path.write_text(entry_line)


def _file_capture_today(brain_path: Path, date_str: str, entry_line: str):
    """Heading-aware insert of `entry_line` as the last line of today's
    `## Today's tasks` section (before the next heading, not EOF).

    Requires <brain>/{date_str}.md to already exist — this action never
    creates it (protocols/daily-note.md, protocols/execute.md)."""
    note_path = brain_path / f"{date_str}.md"
    if not note_path.exists():
        raise ExecuteError(
            f"Today's daily note does not exist yet: {note_path} "
            "— file-capture-today never creates it."
        )
    text = note_path.read_text()
    new_text = _insert_before_next_heading(text, "Today's tasks", entry_line)
    if new_text is None:
        raise ExecuteError(
            f"Today's daily note has no '## Today's tasks' section: {note_path}"
        )
    note_path.write_text(new_text)


def execute_plan(
    brain_path: Path, plan_path: Path, now: dt.datetime = None,
    config_dir: Path = None, library_path: Path = None,
) -> dict:
    now = now or dt.datetime.now()
    config_dir = Path(config_dir) if config_dir else brain_path / "config"
    library_path = Path(library_path) if library_path else resolve_library_path(None)
    date_str = now.strftime("%Y-%m-%d")
    text = plan_path.read_text()
    rows = parse_plan_rows(text)

    filed, discarded, agent_dispatched, skipped, errors = [], [], [], [], []
    lines = text.splitlines()

    for i, line in enumerate(lines):
        m = ROW_RE.match(line)
        if not m:
            continue
        row = m.groupdict()
        if row["approve"] != "[x]":
            continue  # untouched: still "[ ]" (pending) or already "[x] (done)"

        source_match = re.match(r'^inbox/raw/([^/]+)/(.+)$', row["capture"])
        if not source_match:
            errors.append(f"Row {row['n']}: unrecognised capture path {row['capture']!r}")
            continue
        source, filename = source_match.groups()
        raw_path = brain_path / row["capture"]
        if not raw_path.exists():
            errors.append(f"Row {row['n']}: Raw Capture not found at {row['capture']}")
            continue

        destination = row["destination"]
        if destination.strip().lower() == "unmatched":
            errors.append(f"Row {row['n']}: destination is still 'unmatched' — resolve Pass B before approving.")
            continue

        action_type = action_type_for(destination)
        log_id = uuid.uuid4().hex[:8]
        row["log_id"] = log_id
        try:
            if action_type == "file-capture":
                entry_line = f"- {date_str} — [[{row['capture']}]] — {row['preview']}\n"
                _file_capture(brain_path, destination, entry_line)
                outcome = f"Filed to {destination}"
                action_desc = f"Filed capture (row {row['n']}) to {destination}."
                filed.append(row["capture"])
            elif action_type == "file-capture-today":
                entry_line = f"- [ ] {row['preview']} — [[{row['capture']}]]\n"
                _file_capture_today(brain_path, date_str, entry_line)
                outcome = "Filed to today's daily note"
                action_desc = f"Filed capture (row {row['n']}) to today's daily note."
                filed.append(row["capture"])
            elif action_type == "agent-dispatched":
                outcome = f"Dispatched to {destination} (Reviewer gate pending)"
                action_desc = f"Dispatched capture (row {row['n']}) to {destination}."
                agent_dispatched.append(row)
            else:
                outcome = "Discarded — no destination filed"
                action_desc = f"Discarded capture (row {row['n']}) — no destination."
                discarded.append(row["capture"])
        except ExecuteError as e:
            errors.append(f"Row {row['n']}: {e}")
            continue

        if action_type != "agent-dispatched":
            archived_capture_path = _move_collision_safe(raw_path, brain_path / "archive" / "inbox" / source)
            outcome_kind = "discarded" if action_type == "discard-capture" else "filed"
            # A discard row gets the canonical literal rather than its raw cell,
            # which `action_type_for()` matched case-insensitively — so a `Discard`
            # tick still reaches the hook as `discard`. Every other row forwards
            # its cell verbatim, heading fragment included (execute.md v1.3).
            hook_destination = "discard" if action_type == "discard-capture" else destination
            _run_source_execute_hook(
                source, archived_capture_path, outcome_kind, hook_destination,
                config_dir, library_path,
            )

        # `rule` is always present in the groupdict (ROW_RE has no `?` on
        # that capture group) — the empty-string/"—" check below is the
        # real guard, this is just direct access, not a fallback.
        rule_id = row["rule"]
        if row["route"] == "Pass A" and rule_id and rule_id != "—":
            trigger = f"Execute (Routine) — rule {rule_id}"
        else:
            trigger = "Execute (Routine)"

        entry = log_action.build_entry(
            actor="EA",
            trigger=trigger,
            action_type=action_type,
            action=action_desc,
            confidence=row["confidence"] or "Medium",
            outcome=outcome,
            input_link=row["capture"],
            entry_id=log_id,
        )
        log_action.append_entry(brain_path, date_str, entry)

        if action_type == "agent-dispatched":
            lines[i] = _mark_dispatched(line, m)
        else:
            lines[i] = _mark_done(line, m)

    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    plan_path.write_text(new_text)

    remaining = [r for r in parse_plan_rows(new_text) if r["approve"] == "[ ]"]
    archived_to = None
    if not remaining:
        final_text = FRONTMATTER_STATUS_RE.sub("status: executed", new_text, count=1)
        plan_path.write_text(final_text)
        archived_to = _move_collision_safe(plan_path, brain_path / "archive" / "triage")

    # Bumped after processing, regardless of outcome — Execute ran and
    # checked, even when nothing was ticked this time.
    heartbeat.bump(brain_path, "Execute", now)

    return {
        "filed": filed, "discarded": discarded, "agent_dispatched": agent_dispatched,
        "errors": errors, "plan_executed": archived_to is not None, "archived_to": archived_to,
    }


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--plan", required=True, help="Path to the Triage Plan file (relative to --brain or absolute)")
    p.add_argument("--config-dir", default=None,
                    help="Brain config/ dir, passed to any per-source execute_hook.py. "
                         "Defaults to <brain>/config.")
    p.add_argument("--library-path", default=None,
                    help="goals-os-library checkout, to look up per-source execute_hook.py. "
                         "Falls back to $GOALS_OS_LIBRARY_PATH, then a sibling-repo default.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = brain_path / plan_path
    if not plan_path.exists():
        sys.exit(f"Triage Plan not found: {plan_path}")

    config_dir = Path(args.config_dir).expanduser().resolve() if args.config_dir else None
    library_path = resolve_library_path(args.library_path)

    result = execute_plan(brain_path, plan_path, config_dir=config_dir, library_path=library_path)

    print(f"Filed: {len(result['filed'])}, discarded: {len(result['discarded'])}, dispatched: {len(result['agent_dispatched'])}, errors: {len(result['errors'])}")
    for row in result["agent_dispatched"]:
        print(f"  -> Dispatched row {row['n']} ({row['capture']}) with log_id: {row['log_id']}")
    for err in result["errors"]:
        print(f"  ! {err}")
    if result["plan_executed"]:
        print(f"All rows executed — plan archived to {result['archived_to']}")


if __name__ == "__main__":
    main()
