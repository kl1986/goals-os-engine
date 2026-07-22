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


def _render_section(heading: str, content_lines: list) -> str:
    """`heading` without the leading '## '. Returns e.g. 'Foo\n' (empty) or
    'Foo\nline1\nline2\n' (with content) — always ends with exactly one \n,
    never a trailing blank line of its own (the caller joins sections with
    '\n' as separator to produce exactly one blank line between them)."""
    out = f"## {heading}\n"
    for line in content_lines:
        out += f"{line}\n"
    return out


def _append_new_lines_to_section(text: str, heading: str, existing_ok: callable, new_candidates: list) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)", text, re.MULTILINE | re.DOTALL)
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


def _replace_section(text: str, heading: str, new_lines: list) -> str:
    """Wholesale-replace a section's body — used for Waiting For, which is a
    pure read-only mirror (decision 7: no checkboxes, no daily-note-src
    comment, nothing a user can meaningfully edit in place). Unlike Project
    next actions or Today's tasks, there's no hand-typed or ticked content to
    protect here, so recomputing the section fresh every call (same posture
    Dashboard already takes for this exact scan) avoids stale-plus-fresh
    duplicate lines when a hub's waiting-for text changes mid-day."""
    match = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)", text, re.MULTILINE | re.DOTALL)
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


def _update_frontmatter(text: str, updates: dict) -> str:
    """Set (or add) top-level frontmatter keys in place, scoped to the
    leading ``---\\n...\\n---\\n`` block only, so a `status:`-shaped word
    later in the body is never touched. Existing keys are overwritten;
    keys not already present are appended at the end of the frontmatter
    block (defensive — ADR-0015 tickets should already carry every key,
    even if blank)."""
    fm_match = re.match(r"^(---\n)(.*?)(\n---\n)", text, re.DOTALL)
    if not fm_match:
        return text

    lines = fm_match.group(2).split("\n")
    remaining = dict(updates)
    for i, line in enumerate(lines):
        key_match = re.match(r"^([\w-]+):.*$", line)
        if key_match and key_match.group(1) in remaining:
            key = key_match.group(1)
            lines[i] = f"{key}: {remaining.pop(key)}"
    for key, value in remaining.items():
        lines.append(f"{key}: {value}")

    new_fm_body = "\n".join(lines)
    return text[:fm_match.start(2)] + new_fm_body + text[fm_match.end(2):]


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
    """Return a rendering dict for `ticket_path` if it's a prioritised/
    in-progress ticket, else None (silently skipped — not an error)."""
    text = ticket_path.read_text()
    status = _frontmatter_field(text, "status")
    if status not in ("prioritised", "in-progress"):
        return None

    title = _ticket_title(text, ticket_path.stem)
    rel_path = ticket_path.relative_to(brain_path).as_posix()
    return {
        "ticket_path": rel_path,
        "ticket_file": ticket_path.stem,
        "title": title,
        "rendered": f"- [ ] {title} — [[{ticket_path.stem}]]",
    }


def _project_next_actions(brain_path: Path) -> list:
    """Scan `tasks/projects/*/` and `tasks/areas/*/` for `status: prioritised`
    or `status: in-progress` tickets (ADR-0018) — no per-Project/Area cap,
    one row per matching ticket. A `tasks/projects/<slug>/` ticket only
    surfaces if the parent Project note (`projects/<slug>/...`) has
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


def _carry_forward_tasks(brain_path: Path) -> list:
    archive_dir = brain_path / "archive" / "daily-notes"
    if not archive_dir.is_dir():
        return []
    
    files = sorted(archive_dir.glob("*.md"))
    if not files:
        return []
        
    latest_file = files[-1]
    text = latest_file.read_text()
    section_match = re.search(r"^## Today's tasks\s*\n(.*?)(?=\n## |\Z)", text, re.MULTILINE | re.DOTALL)
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
    
    if not note_path.exists():
        carried_tasks = _carry_forward_tasks(brain_path)
        today_lines = carried_tasks if carried_tasks else ["- [ ]"]
        
        heading_str = f"{now.strftime('%A')}, {now.day} {now.strftime('%B')} {now.year}"
        
        body_sections = [
            _render_section("Today's tasks", today_lines),
            _render_section("Project next actions", project_lines),
            _render_section("Waiting for", waiting_lines),
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
            
        text = _append_new_lines_to_section(text, "Project next actions", project_existing_ok, project_lines)
        text = _replace_section(text, "Waiting for", waiting_lines)
        
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
    section_match = re.search(r"^## Project next actions\s*\n(.*?)(?=\n## |\Z)", text, re.MULTILINE | re.DOTALL)
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
                    outcome="Written back — status set to done in ticket frontmatter",
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
