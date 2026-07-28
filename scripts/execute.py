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

# A Row is a markdown task-list item, not a table row (ADR-0031) — Obsidian
# only renders task syntax as a tappable checkbox in a list item, never inside
# a table cell, and approval is the one gesture confirm-first demands on every
# single Row. The shape:
#
#     ## discard
#
#     - [ ] **7** → `discard` · Pass B · — · —
#         LinkedIn Job Alerts · "Credit Manager, Fraud at Revolut"
#         [[inbox/raw/email/2026-07-27-010011-credit-manager-fraud.md]]
#
# The `## <destination>` heading is presentation only, in the strong sense: it is
# **regenerated output and is never read for comparison** (ADR-0031). The Row
# line carries its own destination, so ROW_RE stays **line-local**:
# approve/destination/route/confidence/rule are recoverable from one line with no
# document state and no heading-driven parse. That is what lets triage_pending.py
# and dashboard.py import parse_plan_rows() and keep working — a heading-
# authoritative parse would have pushed document structure into every consumer.
#
# Because the heading is never an input, a Row sitting under the "wrong" heading
# is not an error and cannot be one: it executes to its own destination, and
# `regroup_plan()` moves it under the right heading as part of the same write.
# Re-routing a capture is therefore a single in-place edit of the Row line —
# the whole point of keeping the destination on the line.
#
# The two fields that are NOT on the Row line — `capture` and `preview` — sit on
# indented continuation lines belonging to that same list item. This is a
# deliberate, bounded relaxation of line-locality and not a return to document
# state: the continuation lines are *part of the Row*, read forward from the Row
# line, so a Row is still a self-contained block that can be read without knowing
# anything that precedes it. The alternative — keeping the capture wikilink and
# the 60-char preview on the task line — was rejected in grilling: the wikilink is
# the longest field by far, and leaving it inline pushes the checkbox and
# destination off the visible width on a phone, which is precisely the failure
# this change exists to fix.
#
# Leading whitespace is tolerated on the task line. Obsidian on mobile
# auto-indents when you press Enter inside a list, so a user correcting a
# destination on the very device this shape exists to serve can easily indent
# the following Row — and an anchored `^- ` would make that Row invisible to
# Execute, the nudge and the Dashboard simultaneously, silently dropping it from
# the queue rather than failing.
#
# ---------------------------------------------------------------------------
# Continuation lines are CONTENT, never structure.
#
# A continuation line is indented, and ROW_RE tolerates indentation, so a
# continuation line can be *shaped* like a Row. A preview is 60 characters of an
# untrusted capture's own body, so that shape is attacker-chosen: an email body of
# "- [ ] **9** → `discard` · Pass A · High · x" is under the preview cap and is a
# well-formed Row line. If the parser scanned line by line, that preview would be
# parsed as a second, phantom Row — capture-derived text injecting Plan structure,
# which is exactly what protocols/triage.md's Principle 10 exists to prevent.
#
# So parsing is a single forward pass over blocks, not a scan over lines: once a
# task line is recognised, its continuation lines are consumed as that Row's
# content and are NEVER re-examined as possible Row starts. A Row-shaped preview
# is then simply preview text, inert, on every Plan — including ones already
# written before this rule existed. (`triage._sanitize()` additionally escapes the
# shape at write time, so new Plans never contain it in the first place; that
# closes the production path, this closes hand-edited and already-written Plans.)
#
# A block's continuation lines must then be exactly what the writer emits — at
# least two of them, with exactly one bare `[[inbox/raw/…]]` line, last. That
# arity is what makes the reading unambiguous rather than positional guesswork,
# and it closes the mirror-image hazard too: a Row whose real capture line was
# deleted and whose preview is *itself* a bare wikilink no longer has that preview
# silently adopted as its capture — two capture-shaped lines, or fewer than two
# continuation lines, is a malformed block, and Execute refuses the whole Plan
# naming the row (see check_row_blocks()). Ambiguity fails loudly and never in
# favour of capture-derived text.
#
# The one place a Row-shaped line does end a block is *after* that block's capture
# line has already been seen — i.e. at a genuine block boundary. That is what lets
# a sibling Row that mobile auto-indent has glued directly onto the previous Row,
# with no blank line between, still parse as its own Row instead of being
# swallowed. It cannot be abused: a preview is a single line, so a payload cannot
# emit both a capture line and a Row line to reach that state.
# ---------------------------------------------------------------------------
ROW_RE = re.compile(
    r'^[ \t]*- (?P<tick>\[[ x]\])'
    r'\s+\*\*(?P<n>\d+)\*\*'
    r'\s+→\s+`(?P<destination>[^`]*)`'
    r'\s+·\s+(?P<route>Pass [AB])'
    r'\s+·\s+(?P<confidence>[^·]*?)'
    r'\s+·\s+(?P<rule>[^·]*?)'
    r'(?:\s+\((?P<marker>done|dispatched)\))?\s*$'
)
# A continuation line of the Row above it: indented, non-blank. A blank line,
# a heading, or the next Row all end the block.
ROW_CONTINUATION_RE = re.compile(r'^[ \t]+(?P<text>\S.*?)[ \t]*$')
CAPTURE_LINE_RE = re.compile(r'^\[\[(?P<capture>inbox/raw/[^\]]+)\]\]$')
HEADING_RE = re.compile(r'^##\s+(?P<heading>.+?)\s*$')
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
    `people/Example Person.md#🗣️ To Discuss`) targets a specific `## heading`
    section: content is inserted before the next heading, never appended
    blindly at EOF (protocols/execute.md, ticket 09's generalization of
    `file-capture-today`'s existing insert-before-heading mechanic to any
    file/heading, not just today's daily note)."""
    if "#" in destination:
        file_path, heading = destination.split("#", 1)
        return file_path.strip(), heading.strip()
    return destination.strip(), None


def _row_dict(match: re.Match, capture: str, preview: str) -> dict:
    """The Row dict every consumer reads: the same key set the table shape
    exposed, so triage_pending.py and dashboard.py need no change.

    `approve` is recomposed from the tick and the trailing `(done)`/
    `(dispatched)` marker rather than being one capture group, because the
    marker is now a suffix on the whole task line instead of a separate cell.
    Consumers still see exactly `[ ]`, `[x]`, `[x] (done)`, `[x] (dispatched)`."""
    d = match.groupdict()
    marker = d.pop("marker")
    tick = d.pop("tick")
    d["approve"] = f"{tick} ({marker})" if marker else tick
    d["capture"] = capture
    d["preview"] = preview
    return d


def _read_block(continuations: list) -> tuple:
    """`(capture, preview, problem)` for one Row's continuation lines.

    Well-formed is exactly what `triage.build_row_block()` emits: at least two
    continuation lines, of which exactly one is a bare `[[inbox/raw/…]]` link
    and it is the last. Anything else returns an empty capture and a `problem`
    string — see the block comment above ROW_RE for why this is strict rather
    than best-effort."""
    links = [i for i, body in enumerate(continuations) if CAPTURE_LINE_RE.match(body)]
    if len(continuations) >= 2 and links == [len(continuations) - 1]:
        capture = CAPTURE_LINE_RE.match(continuations[-1]).group("capture")
        return capture, " ".join(continuations[:-1]), None
    return "", " ".join(continuations), (
        f"expected a preview line followed by a single `[[inbox/raw/…]]` capture "
        f"line, but found {len(continuations)} continuation line(s) and "
        f"{len(links)} capture link(s)"
    )


def _scan_blocks(text: str) -> list:
    """`[(start, end, row_dict, problem), ...]` in file order. Pure — no I/O.

    A single forward pass: each Row's continuation lines are consumed with it
    and are never revisited as possible Row starts. `start` is the index of the
    *task* line, the only line Execute ever rewrites (the marker is appended to
    it); continuation lines are never touched. `end` is one past the block's
    last continuation line, so `lines[start:end]` is the whole Row — which is
    what `regroup_plan()` moves around verbatim."""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        m = ROW_RE.match(lines[i])
        if not m:
            i += 1
            continue
        continuations = []
        seen_capture = False
        j = i + 1
        while j < len(lines):
            # Only once this block's own capture line has been seen does a
            # Row-shaped line mean "next Row" rather than "Row-shaped content".
            if seen_capture and ROW_RE.match(lines[j]):
                break
            cm = ROW_CONTINUATION_RE.match(lines[j])
            if not cm:
                break
            body = cm.group("text")
            continuations.append(body)
            seen_capture = seen_capture or bool(CAPTURE_LINE_RE.match(body))
            j += 1
        capture, preview, problem = _read_block(continuations)
        out.append((i, j, _row_dict(m, capture, preview), problem))
        i = j
    return out


def _parse_blocks(text: str) -> list:
    """`[(line_index, row_dict, problem), ...]` in file order — `_scan_blocks`
    without the block end, which only the re-grouper needs."""
    return [(start, row, problem) for start, _, row, problem in _scan_blocks(text)]


def parse_plan_rows(text: str) -> list:
    """Return every Row as a dict, in file order. Pure — no I/O.

    Never raises and never drops a Row, whatever state the Plan is in, because
    the pending-work nudge and the Dashboard run this on every session start.
    A malformed Row comes back with an empty `capture`; `check_row_blocks()` is
    what turns that into a refusal, and only Execute acts on it."""
    return [row for _, row, _ in _parse_blocks(text)]


def check_row_blocks(text: str) -> list:
    """Every Row that cannot be read as an actionable Row, as ready-to-print
    error strings naming the row number. Two kinds, one refusal:

    - **continuation lines that aren't the writer's shape** — the capture is
      genuinely unrecoverable, so guessing is worse than stopping;
    - **a blank destination** — `→ `` ` says nothing about where the capture
      goes, and every reader of a Row would have to invent an answer.
      `_file_capture` would resolve it to the Brain root and raise an uncaught
      `IsADirectoryError` mid-run, after earlier Rows had already been filed,
      archived and logged but before the Plan was rewritten to stamp them; and
      `regroup_plan` cannot name a group after it. Refusing before any side
      effect is the only reading that leaves the Plan and the Action Log
      consistent. Same philosophy as the `unmatched` guard in `execute_plan` —
      not actionable, so refuse rather than act — raised to a whole-Plan
      refusal because, unlike `unmatched`, a blank destination also breaks the
      Rows around it."""
    errors = []
    for _, row, problem in _parse_blocks(text):
        if problem:
            errors.append(f"Row {row['n']}: malformed Row block — {problem}")
        if not row["destination"].strip():
            errors.append(
                f"Row {row['n']}: blank destination — a Row must name where its "
                "capture goes (a path, `today`, `agent: <name>`, or `discard`)."
            )
    return errors


def regroup_plan(text: str) -> str:
    """Rewrite a Plan so every Row block sits under a `## <destination>`
    heading derived from **that Row's own destination** (ADR-0031).

    The heading is regenerated output, never an input: it is never compared to
    anything, so it cannot contradict anything. An in-place edit of a Row's
    destination is therefore a complete re-routing — the Row executes to its
    edited destination, and the next write moves it under the matching heading,
    creating that heading if it is absent and dropping any heading left with
    nothing under it. The accepted trade is that a hand-edit to a *heading* is
    silently ineffective and reverted on the next write.

    Ordering, chosen so the result is stable and idempotent:

    - **Groups** keep the order of the existing `## ` headings that still
      receive at least one Row, then any destination with no heading yet, in
      the order its first Row appears. A destination edit therefore never
      reshuffles the groups around it.
    - **Rows within a group** keep their document order. Numbering is global
      and untouched, so a re-routed Row keeps its number wherever it lands.

    A Row whose destination is **blank** gets no heading at all: `## ` is not a
    heading any reader would parse back (`HEADING_RE` needs text after the
    `##`), so emitting one would be read as prose on the next pass and a fresh
    `## ` emitted below it — the file growing by two lines every run, in a Plan
    the user is actively editing. Blank-destination Rows are therefore held
    ungrouped, immediately after the preamble, which is a fixed point. Execute
    refuses such a Plan outright (`check_row_blocks`); this is what keeps the
    *other* write path — Triage's, which has no refusal — from degrading a Plan
    that a mid-edit save or a `route ->  ` rule left with a blank destination.

    Everything that is not a heading and not part of a Row block is preserved:
    frontmatter, the H1 and any prose above the first heading/Row stay as the
    preamble; prose inside a section stays with that section (and keeps that
    heading alive even with no Rows left under it); prose under no heading at
    all is hoisted into the preamble, which is where free prose lives and the
    only position for it that survives a second pass. Row blocks move verbatim
    — tick state, executed marker, indentation and continuation lines all
    byte-identical.

    Purely textual and driven only by the destination field of Row lines the
    parser already recognises. A capture's preview is content, never structure
    (see `_scan_blocks`), so capture-derived text cannot create, name or
    populate a group."""
    lines = text.splitlines()
    spans = {start: (end, row) for start, end, row, _ in _scan_blocks(text)}
    first_heading = next(
        (i for i, line in enumerate(lines) if HEADING_RE.match(line)), None
    )
    starts = [i for i in (first_heading, min(spans) if spans else None) if i is not None]
    if not starts:
        return text  # no Rows and no headings — nothing to group

    preamble = lines[:min(starts)]
    heading_order, section_prose = [], {}
    group_order, groups = [], {}
    headless_prose, ungrouped = [], []

    heading = None
    i = min(starts)
    while i < len(lines):
        if i in spans:
            end, row = spans[i]
            block = "\n".join(lines[i:end])
            destination = row["destination"].strip()
            if not destination:
                ungrouped.append(block)  # no nameable heading — see the docstring
            else:
                if destination not in groups:
                    groups[destination] = []
                    group_order.append(destination)
                groups[destination].append(block)
            i = end
            continue
        hm = HEADING_RE.match(lines[i])
        if hm:
            heading = hm.group("heading").strip()
            if heading not in section_prose:
                section_prose[heading] = []
                heading_order.append(heading)
        elif lines[i].strip():
            (section_prose[heading] if heading is not None else headless_prose).append(
                lines[i]
            )
        i += 1

    # Preamble, then anything that cannot carry a heading, then the groups.
    # Everything before the first group is where the next pass's preamble ends,
    # which is what makes this arrangement a fixed point.
    out = "\n".join(preamble).rstrip("\n")
    if headless_prose:
        out = out.rstrip("\n") + "\n\n" + "\n".join(headless_prose) + "\n"
    for block in ungrouped:
        out = out.rstrip("\n") + "\n\n" + block + "\n"
    for destination in heading_order + [d for d in group_order if d not in section_prose]:
        prose = section_prose.get(destination, [])
        blocks = groups.get(destination, [])
        if not prose and not blocks:
            continue  # heading emptied by a re-route — dropped, not preserved
        out = out.rstrip("\n") + f"\n\n## {destination}\n"
        if prose:
            out += "\n" + "\n".join(prose) + "\n"
        for block in blocks:
            out += "\n" + block + "\n"
    out = out.lstrip("\n")
    return out if out.endswith("\n") else out + "\n"


def _mark_executed(line: str, marker: str) -> str:
    """Append `(done)`/`(dispatched)` to the task line.

    The old table shape rewrote the approve *cell* by match span; there is no
    cell now, and the marker is a trailing suffix on the task line (kept as
    plain text rather than a Tasks-plugin custom status, so a Plan stays
    readable with no plugin installed)."""
    return f"{line.rstrip()} ({marker})"


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

    # Refuse the whole Plan before anything is filed, archived or logged —
    # a half-executed Plan whose remaining rows are ambiguous is strictly
    # worse than an untouched one.
    problems = check_row_blocks(text)
    if problems:
        raise ExecuteError(
            f"Refusing to execute {plan_path.name} — "
            f"{len(problems)} row(s) could not be read unambiguously, "
            "and no row was acted on. Fix the Plan and re-run:\n  "
            + "\n  ".join(problems)
        )

    filed, discarded, agent_dispatched, skipped, errors = [], [], [], [], []
    lines = text.splitlines()

    for i, row, _ in _parse_blocks(text):
        line = lines[i]
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

        lines[i] = _mark_executed(
            line, "dispatched" if action_type == "agent-dispatched" else "done"
        )

    # Re-group as part of the same write that stamps the markers: the Row line
    # is authoritative, so a destination edited in place has already executed to
    # where it now says, and this is what tidies the heading it sits under.
    # Grouping never decides which Rows execute — it runs after they have.
    new_text = regroup_plan("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
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

    try:
        result = execute_plan(brain_path, plan_path, config_dir=config_dir, library_path=library_path)
    except ExecuteError as e:
        sys.exit(str(e))

    print(f"Filed: {len(result['filed'])}, discarded: {len(result['discarded'])}, dispatched: {len(result['agent_dispatched'])}, errors: {len(result['errors'])}")
    for row in result["agent_dispatched"]:
        print(f"  -> Dispatched row {row['n']} ({row['capture']}) with log_id: {row['log_id']}")
    for err in result["errors"]:
        print(f"  ! {err}")
    if result["plan_executed"]:
        print(f"All rows executed — plan archived to {result['archived_to']}")


if __name__ == "__main__":
    main()
