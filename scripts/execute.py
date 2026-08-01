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

# A Row is a single-line markdown task-list item (ADR-0036).
# The shape:
#
#     - [ ] <preview> → `<destination>` [[<capture_link>]]
#
# A keeper Row (destination `unmatched` or `?`) carries indented option checkboxes:
#     - [ ] Act on this
#     - [ ] Area · `areas/finances/_inbox.md`
#     - [ ] Project · `projects/goals-os/_inbox.md`
#     - [ ] Bin it instead
#
# The `## <destination>` heading is presentation only, in the strong sense: it is
# **regenerated output and is never read for comparison** (ADR-0031). The Row
# line carries its own destination(s), so ROW_RE stays **line-local**:
# approve, preview, destination(s), and capture wikilink are recoverable from
# one line with no document state and no heading-driven parse. That is what lets
# triage_pending.py and dashboard.py import parse_plan_rows() and keep working.
#
# Pass A metadata (`rule`, `confidence`) lives in Plan YAML frontmatter under a
# `rules:` block mapping capture filename to rule details. Pass B rows carry zero
# frontmatter rule entries. Execute reads this `rules:` block to record which
# specific rule produced an action on the Action Log's `trigger` field.
#
# Multi-destination support: A Row may name several destinations, comma-separated,
# each individually backticked (e.g. `→ \`dest1\`, \`dest2\``).
#
# `check_row_blocks()` refuses any Plan holding legacy three-line Rows or malformed
# Row blocks upfront to protect open Plans from silent archive or execution
# without approval.
DESTINATION_LIST_RE = r'`[^`]*`(?:\s*,\s*`[^`]*`)*'
ROW_RE = re.compile(
    r'^- (?P<tick>\[[ x]\])'
    r'\s+(?P<preview>.*?)'
    rf'\s+→\s+(?P<destinations>{DESTINATION_LIST_RE})'
    r'\s+\[\[(?P<capture>inbox/raw/[^\]]+)\]\]'
    r'(?:\s+\((?P<marker>done|dispatched)\))?\s*$'
)
# Pulls the individual destinations back out of the matched list.
DESTINATION_RE = re.compile(r'`([^`]*)`')

# Indented option checkboxes for keeper rows.
OPTION_LINE_RE = re.compile(
    r'^[ \t]+- \[(?P<tick>[ x])\]\s+(?P<label>[^·\n]+?)(?:\s+·\s+`(?P<value>[^`]+)`)?\s*$'
)

# The Plan's one section that holds no Rows: a checkbox per sender offering to
# turn "this is noise" into a routing rule (ADR-0035). It is prose as far as
# every Row reader is concerned — its checkboxes are not Row-shaped, so
# ROW_RE never matches them and Execute cannot act on them — but `regroup_plan`
# needs to know the name to rank it last, and `triage_sender_rules.py` needs it
# to find and rebuild the section. Named here because this module owns Plan
# layout; nothing else should hardcode the string.
SENDER_RULES_HEADING = "Stop asking me about these"
# A continuation line of the Row above it: indented, non-blank. A blank line,
# a heading, or the next Row all end the block.
ROW_CONTINUATION_RE = re.compile(r'^[ \t]+(?P<text>\S.*?)[ \t]*$')
CAPTURE_LINE_RE = re.compile(r'^\[\[(?P<capture>inbox/raw/[^\]]+)\]\]$')
HEADING_RE = re.compile(r'^##\s+(?P<heading>.+?)\s*$')
FRONTMATTER_STATUS_RE = re.compile(r'^status:\s*\S+\s*$', re.MULTILINE)


class ExecuteError(Exception):
    pass


def split_destination_list(field: str) -> list:
    """The individual destinations of a Row's destination field, in order.

    Empties are preserved rather than dropped: a Row reading ``→ `areas/x`, ` ` ``
    has said something incomplete, and `check_row_blocks()` must be able to see
    the blank to refuse the Plan. Silently dropping it would file to `areas/x`
    and call the half-typed edit done."""
    return [d.strip() for d in DESTINATION_RE.findall(field or "")]


def render_destination_list(destinations) -> str:
    """The destination field as written back to a Row line."""
    return ", ".join(f"`{d}`" for d in destinations)


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


def _parse_plan_rules_frontmatter(text: str) -> dict:
    """Read Pass A rule metadata stored in Plan frontmatter.

    Returns dict mapping capture_filename -> {'rule': rule_id, 'confidence': confidence}.
    """
    fm_match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if not fm_match:
        return {}
    fm_text = fm_match.group(1)
    rules_dict = {}

    rules_match = re.search(r'^rules:\s*\n(.*?)(?=\n[a-z0-9_-]+:|\Z)', fm_text, re.MULTILINE | re.DOTALL)
    if not rules_match:
        rules_inline = re.search(r'^rules:\s*\{(.*?)\}', fm_text, re.MULTILINE | re.DOTALL)
        if rules_inline:
            for entry in re.finditer(r'([\w.-]+):\s*\{([^}]+)\}', rules_inline.group(1)):
                fname = entry.group(1).strip()
                props = {}
                for kv in entry.group(2).split(','):
                    if ':' in kv:
                        k, v = kv.split(':', 1)
                        props[k.strip()] = v.strip().strip("'\"")
                if fname:
                    rules_dict[fname] = props
        return rules_dict

    rules_block = rules_match.group(1)
    current_file = None
    for line in rules_block.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        m_file = re.match(r'^([\w.-]+):\s*(?:\{(.*?)\})?$', line_stripped)
        if m_file:
            current_file = m_file.group(1)
            rules_dict[current_file] = rules_dict.get(current_file, {})
            if m_file.group(2):
                for kv in m_file.group(2).split(','):
                    if ':' in kv:
                        k, v = kv.split(':', 1)
                        rules_dict[current_file][k.strip()] = v.strip().strip("'\"")
            continue
        m_prop = re.match(r'^(rule|confidence):\s*(.+)$', line_stripped)
        if m_prop and current_file:
            rules_dict[current_file][m_prop.group(1)] = m_prop.group(2).strip().strip("'\"")

    return rules_dict


ALLOWED_OPTION_LABELS = {"Act on this", "Area", "Project", "Bin it instead"}


def _row_dict(match: re.Match, options: list, frontmatter_rules: dict, n: int) -> dict:
    """The Row dict every consumer reads: the same key set the table shape
    exposed, so triage_pending.py and dashboard.py need no change."""
    d = match.groupdict()
    marker = d.pop("marker")
    tick = d.pop("tick")
    capture = d["capture"]
    preview = d["preview"]

    capture_filename = Path(capture).name
    rule_meta = frontmatter_rules.get(capture_filename) or frontmatter_rules.get(capture)
    if rule_meta:
        d["route"] = "Pass A"
        d["rule"] = rule_meta.get("rule", "—")
        d["confidence"] = rule_meta.get("confidence", "—")
    else:
        d["route"] = "Pass B"
        d["rule"] = "—"
        d["confidence"] = "—"

    d["approve"] = f"{tick} ({marker})" if marker else tick
    d["n"] = str(n)
    d["options"] = options
    d["capture"] = capture
    d["preview"] = preview

    ticked_destinations = []
    if options:
        for opt in options:
            if opt["tick"] == "x":
                if opt["label"] == "Act on this":
                    ticked_destinations.append("today")
                elif opt["label"] == "Bin it instead":
                    ticked_destinations.append("discard")
                elif opt.get("value") and opt["value"] != "…":
                    ticked_destinations.append(opt["value"])

    task_line_destinations = split_destination_list(d.pop("destinations"))
    d["task_line_destinations"] = task_line_destinations

    if ticked_destinations:
        d["destinations"] = ticked_destinations
    else:
        d["destinations"] = task_line_destinations

    d["destination"] = d["destinations"][0] if d["destinations"] else ""
    return d


def _read_block(continuations: list) -> tuple:
    """`(options, problem)` for one Row's continuation lines."""
    if not continuations:
        return [], None
    options = []
    for line in continuations:
        m = OPTION_LINE_RE.match(line)
        if not m:
            return [], f"unrecognised continuation line {line.strip()!r}"
        tick = m.group("tick")
        label = m.group("label").strip()
        value = m.group("value").strip() if m.group("value") else None
        if label not in ALLOWED_OPTION_LABELS:
            return [], f"invalid keeper option label {label!r} — only 'Act on this', 'Area', 'Project', and 'Bin it instead' are allowed"
        if label in ("Area", "Project") and (not value or value == "…"):
            return [], f"option {label!r} requires a valid destination path"
        options.append({"tick": tick, "label": label, "value": value, "text": line.strip()})
    return options, None


def _scan_blocks(text: str) -> list:
    """`[(start, end, row_dict, problem), ...]` in file order. Pure — no I/O."""
    lines = text.splitlines()
    frontmatter_rules = _parse_plan_rules_frontmatter(text)
    out = []
    i = 0
    row_count = 1
    current_heading = None
    sender_checkbox_re = re.compile(
        r'^- \[[ x]\]\s+⚡️\s+Always bin\s+\*\*[^*]+\*\*\s+`[^`]+`'
    )
    while i < len(lines):
        line = lines[i]
        hm = HEADING_RE.match(line)
        if hm:
            current_heading = hm.group("heading").strip()
            i += 1
            continue

        if re.match(r'^[ \t]*- \[[ x]\]', line):
            m = ROW_RE.match(line)
            if not m:
                if current_heading == SENDER_RULES_HEADING and sender_checkbox_re.match(line):
                    i += 1
                    continue
                # Unrecognised or legacy task line
                row = {
                    "n": str(row_count),
                    "preview": line.strip(),
                    "destinations": [],
                    "destination": "",
                    "capture": "",
                    "route": "Pass B",
                    "rule": "—",
                    "confidence": "—",
                    "approve": line.strip()[2:5],
                    "options": [],
                }
                out.append((i, i + 1, row, f"unrecognised or legacy Row line {line.strip()!r}"))
                row_count += 1
                i += 1
                continue

            continuations = []
            j = i + 1
            while j < len(lines):
                if ROW_RE.match(lines[j]) or lines[j].startswith("- ["):
                    break
                if HEADING_RE.match(lines[j]):
                    break
                if not lines[j].strip():
                    break
                continuations.append(lines[j])
                j += 1
            options, problem = _read_block(continuations)
            row = _row_dict(m, options, frontmatter_rules, row_count)
            out.append((i, j, row, problem))
            row_count += 1
            i = j
            continue

        elif re.match(r'^\s*\|', line):
            row = {
                "n": str(row_count),
                "preview": line.strip(),
                "destinations": [],
                "destination": "",
                "capture": "",
                "route": "Pass B",
                "rule": "—",
                "confidence": "—",
                "approve": "[ ]",
                "options": [],
            }
            out.append((i, i + 1, row, f"legacy markdown-table Row line {line.strip()!r}"))
            row_count += 1
            i += 1
            continue

        i += 1
    return out


def _parse_blocks(text: str) -> list:
    """`[(line_index, row_dict, problem), ...]` in file order — `_scan_blocks`
    without the block end, which only the re-grouper needs."""
    return [(start, row, problem) for start, _, row, problem in _scan_blocks(text)]


def parse_plan_rows(text: str) -> list:
    """Return every valid Row as a dict, in file order. Pure — no I/O."""
    return [row for _, row, problem in _parse_blocks(text) if not problem]


def check_row_blocks(text: str) -> list:
    """Every Row that cannot be read as an actionable Row, as ready-to-print
    error strings naming the preview. Two kinds, one refusal:

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
        preview_label = f"Row \"{row['preview']}\"" if row.get("preview") else f"Row {row['n']}"
        if problem:
            errors.append(f"{preview_label}: malformed Row block — {problem}")
            continue
        destinations = row["destinations"]
        if not destinations or any(not d.strip() or d.strip() in ("—", "-") for d in destinations):
            errors.append(
                f"{preview_label}: blank destination — a Row must name where its "
                "capture goes (a path, `today`, `agent: <name>`, or `discard`)."
            )
            continue
        # Options are only permitted on keeper Rows (`unmatched` or `?`)
        is_keeper = any(d.strip().lower() in ("unmatched", "?") for d in row.get("task_line_destinations", destinations))
        if row.get("options") and not is_keeper:
            errors.append(
                f"{preview_label}: options are only permitted on keeper Rows (`unmatched` or `?`), not on discard/noise or routed Rows."
            )
            continue

        # `discard` means "file nowhere", so pairing it with a real destination
        # is a contradiction the Row cannot be executed under — and unlike a
        # blank, it looks deliberate, so acting on either reading would be
        # guessing at which half the user meant (ADR-0033).
        if len(destinations) > 1 and any(
            action_type_for(d) == "discard-capture" for d in destinations
        ):
            errors.append(
                f"{preview_label}: `discard` cannot be combined with another "
                "destination — either bin the capture or file it, not both."
            )
        if len(set(destinations)) != len(destinations):
            errors.append(
                f"{preview_label}: the same destination is listed twice — "
                "filing one capture to it twice would duplicate the entry."
            )
    return errors


OLD_TABLE_ROW_RE = re.compile(
    r'^\|\s*\d+\s*\|\s*\[\[[^\]]+\]\]\s*\|\s*.*?\s*\|\s*Pass [AB]', re.MULTILINE
)
OLD_THREE_LINE_ROW_RE = re.compile(
    r'^[ \t]*- \[[ x]\]\s+\*\*\d+\*\*\s+→\s+', re.MULTILINE
)


def requires_migration(text: str) -> bool:
    """True if text holds legacy markdown-table rows or legacy 3-line format rows."""
    if OLD_TABLE_ROW_RE.search(text) or re.search(r'^\s*\|\s*#\s*\|\s*capture\s*\|', text, re.IGNORECASE | re.MULTILINE):
        return True
    if OLD_THREE_LINE_ROW_RE.search(text):
        return True
    return False


def regroup_plan(text: str) -> str:
    """Rewrite a Plan so every Row block sits under a `## <destination>`
    heading derived from **that Row's own destination** (ADR-0031).

    The heading is regenerated output, never an input: it is never compared to
    anything, so it cannot contradict anything. An in-place edit of a Row's
    destination is therefore a complete re-routing — the Row executes to its
    edited destination, and the next write moves it under the matching heading,
    creating that heading if it is absent and dropping any heading left with
    nothing under it. The accepted trade is that a hand-edit to a *heading* is
    silently ineffective and reverted on the next write — reverted in place,
    without moving the group (see the ordering rule below).

    Ordering, chosen so the result is stable and idempotent:

    - **Groups** are ordered by the document position of each destination's
      **first Row** — never by the position of a heading. A group's identity
      and its position both come from its Rows, the only thing ADR-0031 treats
      as authoritative, so a heading influences neither: it is output, never
      input. In a well-grouped Plan first-Row order and heading order are the
      same, so this is a no-op; it differs only where a heading is out of step
      with its Rows. Renaming or deleting a heading therefore leaves its
      group's position and its Rows' order untouched (the earlier
      heading-anchored rule dropped the renamed heading, found the Rows'
      destination heading-less, and appended the whole group at the end —
      a silent reorder mid-approval). Re-routing a Row to a brand-new
      destination opens that group where the Row already sits, which is the
      arrangement that moves the fewest Rows; re-routing the *last* Row
      therefore still appends its new group at the end.
    - **A heading kept alive by prose with no Rows under it** has no first Row
      to sort by, so it sorts by its own document position — the only position
      it has, and the one that keeps its prose where the user last saw it.
      Its prose is emitted under it, so prose is never orphaned nor absorbed
      into a neighbouring section.
    - **Rows within a group** keep their document order. Numbering is global
      and untouched, so a re-routed Row keeps its number wherever it lands.

    Every sort key is a distinct line index in the same document, and each
    emitted group's key line precedes the next group's, so a second pass sorts
    the same way: the arrangement is a fixed point.

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
    heading_order, section_prose, heading_line = [], {}, {}
    group_order, groups, first_row_line = [], {}, {}
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
                    first_row_line[destination] = i  # the group's sort key
                groups[destination].append(block)
            i = end
            continue
        hm = HEADING_RE.match(lines[i])
        if hm:
            heading = hm.group("heading").strip()
            if heading not in section_prose:
                section_prose[heading] = []
                heading_order.append(heading)
                heading_line[heading] = i  # only used if no Row ever names it
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
    # Groups sort by rank first, document position second. Rank is a property
    # of the destination alone, never of the document, which is what keeps
    # re-grouping a fixed point: a second pass ranks the same way.
    #
    #   0  ordinary destinations — the Rows wanting a decision, so they come
    #      first and are what you land on
    #   1  `discard` — the bulk of a Plan and the part needing least attention
    #      (25 of the 32 Rows on the 23/07 email Plan), folded away below the
    #      decisions (ADR-0034)
    #   2  the sender-rules section — read *after* the noise it summarises,
    #      and the last thing on the page because it is optional on any given
    #      morning (ADR-0035)
    def group_key(destination):
        position = first_row_line.get(destination, heading_line.get(destination))
        if destination == SENDER_RULES_HEADING:
            rank = 2
        elif action_type_for(destination) == "discard-capture":
            rank = 1
        else:
            rank = 0
        return (rank, position)

    ordered = sorted(
        group_order + [h for h in heading_order if h not in groups],
        key=group_key,
    )
    for destination in ordered:
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

    if requires_migration(text):
        raise ExecuteError(
            f"Refusing to execute {plan_path.name} — "
            "Plan is in a legacy format and requires migration "
            "(run scripts/migrate_triage_rows_one_line.py)."
        )

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
            errors.append(f"Row \"{row['preview']}\": unrecognised capture path {row['capture']!r}")
            continue
        source, filename = source_match.groups()
        raw_path = brain_path / row["capture"]
        if not raw_path.exists():
            errors.append(f"Row \"{row['preview']}\": Raw Capture not found at {row['capture']}")
            continue

        destinations = row["destinations"]
        if any(d.strip().lower() in ("unmatched", "?") for d in destinations):
            errors.append(f"Row \"{row['preview']}\": destination is still 'unmatched' — resolve Pass B before approving.")
            continue

        destination = row["destination"]
        # The Row's action type is that of its **first** destination. On a
        # multi-destination Row every entry is a file of some kind — a mixed
        # Row is refused by `check_row_blocks()` before anything is acted on —
        # so this classifies the Row as a whole, and drives the one archive
        # move, one hook call and one Action Log entry it gets below.
        action_type = action_type_for(destination)
        log_id = uuid.uuid4().hex[:8]
        row["log_id"] = log_id
        try:
            if action_type == "agent-dispatched":
                outcome = f"Dispatched to {destination} (Reviewer gate pending)"
                action_desc = f"Dispatched capture ({row['preview']}) to {destination}."
                agent_dispatched.append(row)
            elif action_type == "discard-capture":
                outcome = "Discarded — no destination filed"
                action_desc = f"Discarded capture ({row['preview']}) — no destination."
                discarded.append(row["capture"])
            else:
                # One capture, filed to each destination in turn (ADR-0033).
                # Ordinary iteration of the single-destination path: an
                # ExecuteError on the second destination leaves the first
                # already written, so the partial write is reported against the
                # Row rather than silently swallowed — the capture is not
                # archived and the Row keeps its tick, so re-running after the
                # fix completes it. Filing twice to an already-written
                # destination is what the duplicate check refuses up front.
                written = []
                for d in destinations:
                    if action_type_for(d) == "file-capture-today":
                        _file_capture_today(
                            brain_path, date_str,
                            f"- [ ] {row['preview']} — [[{row['capture']}]]\n")
                        written.append("today's daily note")
                    else:
                        _file_capture(
                            brain_path, d,
                            f"- {date_str} — [[{row['capture']}]] — {row['preview']}\n")
                        written.append(d)
                outcome = "Filed to " + ", ".join(written)
                action_desc = f"Filed capture ({row['preview']}) to {', '.join(written)}."
                filed.append(row["capture"])
        except ExecuteError as e:
            errors.append(f"Row \"{row['preview']}\": {e}")
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

    # A Plan is finished when every Row has actually been *acted on*, which is
    # what the executed marker records — not merely when no Row is left
    # unticked. Those differ exactly when a ticked Row errors: an `unmatched`
    # destination, a missing Raw Capture, a destination directory that is not
    # there. Such a Row is `[x]` with no marker, and counting it as done
    # stamped `status: executed` on a Plan where nothing had executed and moved
    # it out of `inbox/triage/` — off the pending nudge and the Dashboard, with
    # its captures still sitting in `inbox/raw/`. Ticking a Plan's worth of
    # still-`unmatched` Rows, which is the natural thing to do on a Plan whose
    # Pass B has not been resolved, archived the lot in one run.
    remaining = [r for r in parse_plan_rows(new_text) if not r["approve"].endswith(")")]
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
        print(f"  -> Dispatched row \"{row['preview']}\" ({row['capture']}) with log_id: {row['log_id']}")
    for err in result["errors"]:
        print(f"  ! {err}")
    if result["plan_executed"]:
        print(f"All rows executed — plan archived to {result['archived_to']}")


if __name__ == "__main__":
    main()
