#!/usr/bin/env python3
"""Generate and close the daily note.

Implements protocols/daily-note.md: creates or additively refreshes
the daily note, and reconciles ticked project actions to their sources.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import log_action  # noqa: E402
import dashboard  # noqa: E402
import md_sections  # noqa: E402


def _render_section(heading: str, content_lines: list) -> str:
    """`heading` without the leading '## '. Returns e.g. 'Foo\n' (empty) or
    'Foo\nline1\nline2\n' (with content) — always ends with exactly one \n,
    never a trailing blank line of its own (the caller joins sections with
    '\n' as separator to produce exactly one blank line between them)."""
    out = f"## {heading}\n"
    for line in content_lines:
        out += f"{line}\n"
    return out


# Hoisted to scripts/md_sections.py so dashboard.py and execute.py can share it
# without a circular import. Kept as a module-level alias because this module was
# its original home; see md_sections.SECTION_BODY for why `[ \t]*\n`, not `\s*\n`.
_SECTION_BODY = md_sections.SECTION_BODY


_CRITICAL_EMBED = "![[tasks/all-tickets.base#Critical work]]"
_NOW_EMBED = "![[tasks/all-tickets.base#Today]]"
_CALL_COMPANION_EMBED = "![[tasks/all-tickets.base#Call Companion]]"
_TOMORROW_CANDIDATES_EMBED = "![[tasks/all-tickets.base#Tomorrow candidates]]"
_DAILY_PRIORITIES_EMBED = "![[tasks/all-tickets.base#Daily priorities]]"

SECTIONS_ORDER = (
    "Critical",
    "Available time",
    "Now",
    "Call Companion",
    "Drafts to review and send",
    "Later today",
    "Tomorrow candidates",
    "Today's tasks",
    "Daily priorities",
    "Project next actions",
    "Waiting for",
    "Proposed from meetings",
    "Notes",
)


def _append_new_lines_to_section(text: str, heading: str, existing_ok: callable, new_candidates: list) -> str:
    match = re.search(_SECTION_BODY.format(re.escape(heading)), text, re.MULTILINE | re.DOTALL)
    if not match:
        return text

    existing_body = match.group(1)
    existing_lines = existing_body.splitlines()
    
    lines_to_add = []
    for line in new_candidates:
        if not existing_ok(line, existing_lines):
            lines_to_add.append(line)
            
    if not lines_to_add:
        return text
        
    new_body = existing_body
    if new_body and not new_body.endswith("\n"):
        new_body += "\n"
    for line in lines_to_add:
        new_body += f"{line}\n"
        
    return text[:match.start(1)] + new_body + text[match.end(1):]


def _ensure_section(text: str, heading: str, before_heading: str | list | tuple = None) -> str:
    """Insert an empty `## {heading}` section before the first matching anchor in
    `before_heading` if it isn't already present, appending at the end if no anchor is found.

    Needed because a daily note generated before a new section existed has no
    such heading, and `_append_new_lines_to_section` is a no-op without one —
    the section would silently never appear on the day the Engine is upgraded.
    Inserting a heading is still additive-only: it adds lines and touches,
    reorders and removes none."""
    if re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE):
        return text

    if isinstance(before_heading, str):
        anchors = [before_heading]
    elif before_heading:
        anchors = list(before_heading)
    else:
        anchors = []

    for anchor_name in anchors:
        anchor = re.search(rf"^## {re.escape(anchor_name)}\s*$", text, re.MULTILINE)
        if anchor:
            return text[:anchor.start()] + f"## {heading}\n\n" + text[anchor.start():]

    if not text.endswith("\n"):
        text += "\n"
    return text + f"\n## {heading}\n"


def _replace_section(text: str, heading: str, new_lines: list) -> str:
    """Wholesale-replace a section's body — used for Waiting For, which is a
    pure read-only mirror (decision 7: no checkboxes, no daily-note-src
    comment, nothing a user can meaningfully edit in place). Unlike Project
    next actions or Today's tasks, there's no hand-typed or ticked content to
    protect here, so recomputing the section fresh every call (same posture
    Dashboard already takes for this exact scan) avoids stale-plus-fresh
    duplicate lines when a hub's waiting-for text changes mid-day."""
    match = re.search(_SECTION_BODY.format(re.escape(heading)), text, re.MULTILINE | re.DOTALL)
    if not match:
        return text
    new_body = "".join(f"{line}\n" for line in new_lines)
    return text[:match.start(1)] + new_body + text[match.end(1):]


def _frontmatter_field(text: str, key: str):
    """Read one top-level frontmatter key's raw value, or None if absent/blank."""
    match = re.search(rf'^{re.escape(key)}:\s*(.*?)\s*$', text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


import frontmatter  # noqa: E402

FRONTMATTER_KEY_RE = frontmatter.FRONTMATTER_KEY_RE
_is_continuation_line = frontmatter._is_continuation_line
PLANNING_METADATA_KEYS = frontmatter.PLANNING_METADATA_KEYS
_update_frontmatter = frontmatter._update_frontmatter




def _ticket_title(text: str, fallback: str) -> str:
    """The ticket note's H1 (first '# ' line), or `fallback` (the filename
    stem) if the ticket has no title line at all."""
    match = re.search(r'^# (.+)$', text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return fallback


def _project_statuses(brain_path: Path) -> dict:
    """<slug> -> Project note's `status:` value, reading every `.md` file
    under `projects/<slug>/` and keeping the one whose frontmatter has
    `type: project` (per `project-tracking.md`'s schema). A project folder
    can hold other loose, non-Project markdown files alongside the real
    Project note (e.g. `projects/goals-os/` has `CONTEXT.md`, PRDs,
    shared-context notes, etc.) — picking "the alphabetically-first file"
    is not safe, since one of those could easily sort first and have no
    `status:` (or the wrong one) at all. Files without `type: project` are
    skipped entirely, regardless of alphabetical order."""
    projects_dir = brain_path / "projects"
    if not projects_dir.is_dir():
        return {}

    statuses = {}
    for slug_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        for note_path in sorted(slug_dir.glob("*.md")):
            text = note_path.read_text()
            if _frontmatter_field(text, "type") != "project":
                continue
            status = _frontmatter_field(text, "status")
            if status is not None:
                statuses[slug_dir.name] = status
            break
    return statuses


def _ticket_item(brain_path: Path, ticket_path: Path):
    """Return a rendering dict for `ticket_path` if it's an active/actionable
    ticket (prioritised, in-progress, awaiting-review, etc.), else None (silently
    skipped — not an error). Uses a denylist (backlog, done, deprioritized) so
    future active status values fail safe (ADR-0025). Render awaiting-review items
    with a distinct '[Awaiting review]' prefix."""
    text = ticket_path.read_text()
    status = _frontmatter_field(text, "status")
    if status is None or status in ("backlog", "done", "deprioritized"):
        return None

    title = _ticket_title(text, ticket_path.stem)
    rel_path = ticket_path.relative_to(brain_path).as_posix()
    if status == "awaiting-review":
        rendered = f"- [ ] [Awaiting review] {title} — [[{ticket_path.stem}]]"
    else:
        rendered = f"- [ ] {title} — [[{ticket_path.stem}]]"

    return {
        "ticket_path": rel_path,
        "ticket_file": ticket_path.stem,
        "title": title,
        "rendered": rendered,
    }


def _project_next_actions(brain_path: Path) -> list:
    """Scan `tasks/projects/*/` and `tasks/areas/*/` for active tickets
    (prioritised, in-progress, awaiting-review, etc. — ADR-0018, ADR-0025) —
    no per-Project/Area cap, one row per matching ticket. A `tasks/projects/<slug>/`
    ticket only surfaces if the parent Project note (`projects/<slug>/...`) has
    `status: Active`; a `tasks/areas/<slug>/` ticket surfaces unconditionally
    (Areas have no lifecycle status field)."""
    tasks_dir = brain_path / "tasks"
    if not tasks_dir.is_dir():
        return []

    items = []

    project_statuses = _project_statuses(brain_path)
    projects_tasks_dir = tasks_dir / "projects"
    if projects_tasks_dir.is_dir():
        for slug_dir in sorted(p for p in projects_tasks_dir.iterdir() if p.is_dir()):
            if project_statuses.get(slug_dir.name) != "Active":
                continue
            for ticket_path in sorted(slug_dir.glob("*.md")):
                item = _ticket_item(brain_path, ticket_path)
                if item:
                    items.append(item)

    areas_tasks_dir = tasks_dir / "areas"
    if areas_tasks_dir.is_dir():
        for slug_dir in sorted(p for p in areas_tasks_dir.iterdir() if p.is_dir()):
            for ticket_path in sorted(slug_dir.glob("*.md")):
                item = _ticket_item(brain_path, ticket_path)
                if item:
                    items.append(item)

    items.sort(key=lambda x: x["ticket_path"])
    return items


def _render_waiting_for_lines(items: list) -> list:
    return [f"- {item['text']} — [[{item['path'].stem}]]" for item in items]


def _render_proposed_lines(items: list) -> list:
    """Plain bullets, NOT checkboxes — the same reasoning as Waiting For: a
    checkbox here would be a false affordance, since approving a proposed item
    happens in its own meeting note and ticking a mirror would silently do
    nothing (protocols/daily-note.md v3)."""
    return [f"- {item['text']} — [[{item['path'].stem}]]" for item in items]


_DRAFT_HEADER_RE = re.compile(
    r"^- \[(?P<check>[ xX])\] \[(?P<tag>draft|sent|discarded|carried-forward)\] (?P<desc>.+?) [—–-] \[\[(?P<link>[^\]]+)\]\]$"
)
_DRAFT_SUBCHECK_RE = re.compile(
    r"^[ \t]+- \[(?P<check>[ xX])\] (?P<label>Send|Discard|Carry forward)$"
)


class Draft:
    def __init__(
        self,
        description: str,
        wikilink: str,
        state: str = "draft",
        header_check: str = " ",
        tag: str = "draft",
        checked_option: str | None = None,
        raw_lines: list = None,
        extra_lines: list = None,
    ):
        self.description = description
        self.wikilink = wikilink
        self.state = state  # "draft", "sent", "discarded", "carried-forward"
        self.header_check = header_check
        self.tag = tag
        self.checked_option = checked_option
        self.raw_lines = raw_lines or []
        self.extra_lines = extra_lines or []

    def render(self) -> list:
        res = [
            f"- [ ] [{self.state}] {self.description} — [[{self.wikilink}]]",
            "    - [ ] Send",
            "    - [ ] Discard",
            "    - [ ] Carry forward",
        ]
        if self.extra_lines:
            res.extend(self.extra_lines)
        return res

    def render_archived(self) -> list:
        check_str = "x" if self.state in ("sent", "discarded") else " "
        send_chk = "x" if self.state == "sent" else " "
        disc_chk = "x" if self.state == "discarded" else " "
        carry_chk = "x" if self.state == "carried-forward" else " "
        res = [
            f"- [{check_str}] [{self.state}] {self.description} — [[{self.wikilink}]]",
            f"    - [{send_chk}] Send",
            f"    - [{disc_chk}] Discard",
            f"    - [{carry_chk}] Carry forward",
        ]
        if self.extra_lines:
            res.extend(self.extra_lines)
        return res


def _parse_draft_lines(lines: list) -> list:
    drafts = []
    i = 0
    while i < len(lines):
        line = lines[i]
        header_match = _DRAFT_HEADER_RE.match(line)
        if header_match:
            header_check = header_match.group("check")
            tag = header_match.group("tag")
            desc = header_match.group("desc").strip()
            link = header_match.group("link").strip()
            block_lines = [line]

            checked_options = []
            extra_lines = []
            j = i + 1
            while j < len(lines):
                if lines[j].startswith(" ") or lines[j].startswith("\t"):
                    block_lines.append(lines[j])
                    sub_match = _DRAFT_SUBCHECK_RE.match(lines[j])
                    if sub_match:
                        if sub_match.group("check").lower() == "x":
                            checked_options.append(sub_match.group("label"))
                    else:
                        extra_lines.append(lines[j])
                    j += 1
                else:
                    break
            i = j - 1

            checked_option = None
            if len(checked_options) > 1:
                sys.stderr.write(
                    f"Warning: Multiple draft options checked for '{desc}': {', '.join(checked_options)}. Using '{checked_options[0]}'.\n"
                )
                checked_option = checked_options[0]
            elif len(checked_options) == 1:
                checked_option = checked_options[0]

            if checked_option == "Send":
                state = "sent"
            elif checked_option == "Discard":
                state = "discarded"
            elif checked_option == "Carry forward":
                state = "carried-forward"
            elif header_check.lower() == "x":
                state = "sent"
                checked_option = "Send"
            else:
                state = tag

            drafts.append(
                Draft(
                    description=desc,
                    wikilink=link,
                    state=state,
                    header_check=header_check,
                    tag=tag,
                    checked_option=checked_option,
                    raw_lines=block_lines,
                    extra_lines=extra_lines,
                )
            )
        i += 1
    return drafts


def _parse_draft_blocks(text: str) -> list:
    match = re.search(
        _SECTION_BODY.format(re.escape("Drafts to review and send")),
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []

    section_body = match.group(1)
    return _parse_draft_lines(section_body.splitlines())


def parse_drafts(text: str) -> list:
    return _parse_draft_blocks(text)


def _rewrite_closed_drafts(text: str) -> str:
    match = re.search(
        _SECTION_BODY.format(re.escape("Drafts to review and send")),
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return text

    section_body = match.group(1)
    drafts = _parse_draft_blocks(text)
    if not drafts:
        return text

    new_lines = []
    lines = section_body.splitlines()
    i = 0
    draft_idx = 0
    while i < len(lines):
        line = lines[i]
        header_match = _DRAFT_HEADER_RE.match(line)
        if header_match:
            d = drafts[draft_idx]
            draft_idx += 1

            final_state = "carried-forward" if d.state in ("draft", "carried-forward") else d.state
            archived_draft = Draft(
                description=d.description,
                wikilink=d.wikilink,
                state=final_state,
                extra_lines=d.extra_lines,
            )
            new_lines.extend(archived_draft.render_archived())

            j = i + 1
            while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t")):
                j += 1
            i = j - 1
        else:
            new_lines.append(line)
        i += 1

    new_body = "".join(f"{line}\n" for line in new_lines)
    return text[:match.start(1)] + new_body + text[match.end(1):]


def _carry_forward_drafts(brain_path: Path) -> list:
    archive_dir = brain_path / "archive" / "daily-notes"
    if not archive_dir.is_dir():
        return []

    files = sorted(archive_dir.glob("*.md"))
    if not files:
        return []

    latest_file = files[-1]
    text = latest_file.read_text()
    drafts = parse_drafts(text)
    carried_lines = []
    seen = set()
    for d in drafts:
        if d.state in ("draft", "carried-forward"):
            key = d.wikilink
            if key not in seen:
                seen.add(key)
                carried_lines.extend(d.render())
    return carried_lines



def _extract_unchecked_tasks(text: str, heading: str) -> list:
    section_match = re.search(
        _SECTION_BODY.format(re.escape(heading)), text, re.MULTILINE | re.DOTALL
    )
    if not section_match:
        return []
    carried = []
    for line in section_match.group(1).splitlines():
        task_match = re.match(r"^- \[ \] (.+)$", line)
        if task_match:
            verbatim = task_match.group(1).strip()
            if verbatim:
                carried.append(line)
    return carried


def _carry_forward_tasks(brain_path: Path) -> list:
    archive_dir = brain_path / "archive" / "daily-notes"
    if not archive_dir.is_dir():
        return []

    files = sorted(archive_dir.glob("*.md"))
    if not files:
        return []

    latest_file = files[-1]
    text = latest_file.read_text()
    carried = []
    seen = set()
    for heading in ("Today's tasks", "Now", "Later today"):
        tasks = _extract_unchecked_tasks(text, heading)
        for line in tasks:
            if line.strip() not in seen:
                carried.append(line)
        seen.update(line.strip() for line in tasks)
    return carried


def generate_daily_note(brain_path: Path, now: dt.datetime = None) -> Path:
    """Create or additively refresh <brain>/{date}.md. Bumps heartbeat 'Daily note'."""
    now = now or dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    note_path = brain_path / f"{date_str}.md"
    
    # Auto-archive any older daily notes before proceeding
    for path in brain_path.glob("????-??-??.md"):
        if path.name == f"{date_str}.md":
            continue
        try:
            note_date = dt.datetime.strptime(path.stem, "%Y-%m-%d")
            close_daily_note(brain_path, note_date)
        except ValueError:
            pass
            
    project_items = _project_next_actions(brain_path)
    project_lines = [item["rendered"] for item in project_items]
    
    waiting_items = dashboard._open_waiting_for(brain_path)
    waiting_lines = _render_waiting_for_lines(waiting_items)

    proposed_items = dashboard._open_proposed_items(brain_path)
    proposed_lines = _render_proposed_lines(proposed_items)

    if not note_path.exists():
        carried_tasks = _carry_forward_tasks(brain_path)
        today_lines = carried_tasks if carried_tasks else ["- [ ]"]

        carried_draft_lines = _carry_forward_drafts(brain_path)

        heading_str = f"{now.strftime('%A')}, {now.day} {now.strftime('%B')} {now.year}"

        body_sections = [
            _render_section("Critical", [_CRITICAL_EMBED]),
            _render_section("Available time", []),
            _render_section("Now", [_NOW_EMBED]),
            _render_section("Call Companion", [_CALL_COMPANION_EMBED]),
            _render_section("Drafts to review and send", carried_draft_lines),
            _render_section("Later today", []),
            _render_section("Tomorrow candidates", [_TOMORROW_CANDIDATES_EMBED]),
            _render_section("Today's tasks", today_lines),
            _render_section("Daily priorities", [_DAILY_PRIORITIES_EMBED]),
            _render_section("Project next actions", project_lines),
            _render_section("Waiting for", waiting_lines),
            _render_section("Proposed from meetings", proposed_lines),
            _render_section("Notes", []),
        ]

        content = (
            "---\n"
            "type: daily-note\n"
            f"date: {date_str}\n"
            "tags:\n"
            "  - daily-note\n"
            "---\n"
            "\n"
            f"# {heading_str}\n"
            "\n"
            + "\n".join(body_sections)
        )
        note_path.write_text(content)
    else:
        text = note_path.read_text()
        original_text = text

        def literal_existing_ok(candidate_line: str, existing_lines: list) -> bool:
            return candidate_line.strip() in {line.strip() for line in existing_lines}

        def project_existing_ok(candidate_line: str, existing_lines: list) -> bool:
            # The `[[ticket file]]` wikilink is the stable identity now (no
            # daily-note-src comment) — dedupe on that, not the visible
            # title text, so a same-day rerun survives the ticket's own H1
            # changing mid-day just as it survived hand-edits before.
            candidate_match = re.search(r"\[\[([^\]]+)\]\]", candidate_line)
            if not candidate_match:
                return False
            cand_target = candidate_match.group(1).strip()
            for line in existing_lines:
                m = re.search(r"\[\[([^\]]+)\]\]", line)
                if m and m.group(1).strip() == cand_target:
                    return True
            return False

        def proposed_existing_ok(candidate_line: str, existing_lines: list) -> bool:
            # Exact-line match. Unlike a ticket, a proposed item has no stable
            # identity beyond its own text — several items share one meeting
            # note, so the `[[note]]` wikilink alone would collapse them all
            # into one and suppress every item after the first.
            return candidate_line.strip() in {line.strip() for line in existing_lines}

        for i, heading in enumerate(SECTIONS_ORDER):
            before_headings = SECTIONS_ORDER[i + 1:]
            text = _ensure_section(text, heading, before_headings)

        embed_map = {
            "Critical": _CRITICAL_EMBED,
            "Now": _NOW_EMBED,
            "Call Companion": _CALL_COMPANION_EMBED,
            "Tomorrow candidates": _TOMORROW_CANDIDATES_EMBED,
            "Daily priorities": _DAILY_PRIORITIES_EMBED,
        }
        for heading, embed_str in embed_map.items():
            text = _append_new_lines_to_section(
                text,
                heading,
                literal_existing_ok,
                [embed_str],
            )

        carried_draft_lines = _carry_forward_drafts(brain_path)
        if carried_draft_lines:
            existing_drafts = parse_drafts(text)
            existing_wikilinks = {d.wikilink for d in existing_drafts}
            carried_drafts = _parse_draft_lines(carried_draft_lines)
            new_draft_lines = []
            for d in carried_drafts:
                if d.wikilink not in existing_wikilinks:
                    new_draft_lines.extend(d.render())
            if new_draft_lines:
                text = _append_new_lines_to_section(
                    text, "Drafts to review and send", lambda line, existing: False, new_draft_lines
                )


        text = _append_new_lines_to_section(text, "Project next actions", project_existing_ok, project_lines)
        text = _replace_section(text, "Waiting for", waiting_lines)
        # Additive-only, unlike Waiting For's wholesale replace: the ticket
        # requires rows be added for items not already present and existing
        # lines never touched or reordered.
        text = _append_new_lines_to_section(text, "Proposed from meetings", proposed_existing_ok, proposed_lines)

        if text != original_text:
            note_path.write_text(text)
            
    heartbeat.bump(brain_path, "Daily note", now)
    return note_path


def _find_ticket_file(tasks_dir: Path, ticket_file: str):
    """Locate `<ticket_file>.md` anywhere under `tasks/**/` — the wikilink
    target is a filename stem, not a path, since ADR-0018 links directly to
    the ticket rather than a parent Project/Area note. Returns the first
    match, or None if not found."""
    if not tasks_dir.is_dir():
        return None
    matches = list(tasks_dir.rglob(f"{ticket_file}.md"))
    return matches[0] if matches else None


def close_daily_note(brain_path: Path, now: dt.datetime = None) -> dict:
    """Reconcile ticked Project-next-actions lines against their source
    tickets (ADR-0018), then move <brain>/{date}.md to
    <brain>/archive/daily-notes/{date}.md. Bumps heartbeat 'Close daily
    note'. Returns a summary dict."""
    now = now or dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    note_path = brain_path / f"{date_str}.md"

    summary = {"reconciled": 0, "misses": [], "archived_to": None}

    if not note_path.exists():
        heartbeat.bump(brain_path, "Close daily note", now)
        return summary

    text = note_path.read_text()
    section_match = re.search(
        _SECTION_BODY.format(re.escape("Project next actions")), text, re.MULTILINE | re.DOTALL
    )
    if section_match:
        tasks_dir = brain_path / "tasks"
        for line in section_match.group(1).splitlines():
            if not re.match(r"^- \[[xX]\] (.+)$", line):
                continue

            link_match = re.search(r"\[\[([^\]]+)\]\]", line)
            if not link_match:
                continue
            ticket_file = link_match.group(1).strip()

            ticket_path = _find_ticket_file(tasks_dir, ticket_file)

            if ticket_path is not None:
                ticket_text = ticket_path.read_text()
                new_text = _update_frontmatter(ticket_text, {
                    "status": "done",
                    "resolved": date_str,
                })
                ticket_path.write_text(new_text)

                rel_path = ticket_path.relative_to(brain_path).as_posix()
                entry = log_action.build_entry(
                    actor="EA",
                    trigger="Close daily note (Routine)",
                    action_type="daily-note-writeback",
                    action=f"Wrote back daily-note line to {rel_path}.",
                    confidence="Medium",
                    outcome="Written back — status set to done in ticket frontmatter, temporary planning metadata and criticality cleared",
                    input_link=rel_path,
                )
                log_action.append_entry(brain_path, date_str, entry)
                summary["reconciled"] += 1
            else:
                entry = log_action.build_entry(
                    actor="EA",
                    trigger="Close daily note (Routine)",
                    action_type="daily-note-writeback",
                    action=f"Reconciled daily-note line for [[{ticket_file}]].",
                    confidence="Medium",
                    outcome="Row not found at source, no write-back performed",
                    input_link=ticket_file,
                )
                log_action.append_entry(brain_path, date_str, entry)
                summary["misses"].append({"ticket_file": ticket_file})

    text = note_path.read_text()
    text = _rewrite_closed_drafts(text)
    note_path.write_text(text)

    archive_dir = brain_path / "archive" / "daily-notes"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_path = archive_dir / f"{date_str}.md"
    note_path.rename(archived_path)
    summary["archived_to"] = archived_path

    heartbeat.bump(brain_path, "Close daily note", now)
    return summary


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("action", choices=["generate", "close"], help="Action to perform: generate or close")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")
        
    if args.action == "generate":
        path = generate_daily_note(brain_path)
        print(f"Daily note written to {path}")
    elif args.action == "close":
        summary = close_daily_note(brain_path)
        print(f"Reconciled {summary['reconciled']}, missed {len(summary['misses'])}, archived to {summary['archived_to']}")


if __name__ == "__main__":
    main()
