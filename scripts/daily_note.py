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


def _project_next_actions(brain_path: Path) -> list:
    projects_dir = brain_path / "projects"
    if not projects_dir.is_dir():
        return []
        
    items = []
    for path in sorted(projects_dir.glob("*/*.md")):
        text = path.read_text()
        status_match = re.search(r'^status:\s*Active\s*$', text, re.MULTILINE)
        if not status_match:
            continue
            
        section_match = re.search(r"^## Next actions?\s*\n(.*?)(?=\n## |\Z)", text, re.MULTILINE | re.DOTALL)
        if not section_match:
            continue
            
        for line in section_match.group(1).splitlines():
            task_match = re.match(r"^- \[ \] (.+)$", line)
            if task_match:
                verbatim = task_match.group(1).rstrip()
                if not verbatim:
                    continue
                rel_path = path.relative_to(brain_path).as_posix()
                rendered = (
                    f"- [ ] {verbatim} — [[{path.stem}]] "
                    f"<!-- daily-note-src: {rel_path} | {verbatim} -->"
                )
                items.append({
                    "project_path": rel_path,
                    "project_name": path.stem,
                    "verbatim": verbatim,
                    "rendered": rendered,
                })
                break
                
    items.sort(key=lambda x: x["project_path"])
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
            candidate_match = re.search(r"<!-- daily-note-src: (?P<path>[^|]+) \| (?P<verbatim>.+?) -->", candidate_line)
            if not candidate_match:
                return False
            cand_path, cand_verb = candidate_match.group("path").strip(), candidate_match.group("verbatim").strip()
            for line in existing_lines:
                m = re.search(r"<!-- daily-note-src: (?P<path>[^|]+) \| (?P<verbatim>.+?) -->", line)
                if m:
                    if m.group("path").strip() == cand_path and m.group("verbatim").strip() == cand_verb:
                        return True
            return False
            
        text = _append_new_lines_to_section(text, "Project next actions", project_existing_ok, project_lines)
        text = _replace_section(text, "Waiting for", waiting_lines)
        
        if text != original_text:
            note_path.write_text(text)
            
    heartbeat.bump(brain_path, "Daily note", now)
    return note_path


def close_daily_note(brain_path: Path, now: dt.datetime = None) -> dict:
    """Reconcile ticked Project-next-actions lines against their source projects,
    then move <brain>/{date}.md to <brain>/archive/daily-notes/{date}.md.
    Bumps heartbeat 'Close daily note'. Returns a summary dict."""
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
        for line in section_match.group(1).splitlines():
            if not re.match(r"^- \[[xX]\] (.+)$", line):
                continue
                
            src_match = re.search(r"<!-- daily-note-src: (?P<path>[^|]+) \| (?P<verbatim>.+?) -->", line)
            if not src_match:
                continue
                
            captured_path_str = src_match.group("path").strip()
            captured_verbatim = src_match.group("verbatim").strip()
            
            project_path = brain_path / captured_path_str
            hit = False
            
            if project_path.exists():
                proj_text = project_path.read_text()
                proj_section_match = re.search(r"^## Next actions?\s*\n(.*?)(?=\n## |\Z)", proj_text, re.MULTILINE | re.DOTALL)
                if proj_section_match:
                    proj_lines = proj_section_match.group(1).splitlines()
                    expected_line = f"- [ ] {captured_verbatim}"
                    
                    found_idx = -1
                    for i, pline in enumerate(proj_lines):
                        if pline.rstrip() == expected_line:
                            found_idx = i
                            break
                            
                    if found_idx != -1:
                        hit = True
                        del proj_lines[found_idx]
                        new_next_action_body = ""
                        for pline in proj_lines:
                            new_next_action_body += f"{pline}\n"
                        proj_text = proj_text[:proj_section_match.start(1)] + new_next_action_body + proj_text[proj_section_match.end(1):]
                        
                        notes_match = re.search(r"^## Notes & progress\s*\n(.*?)(?=\n## |\Z)", proj_text, re.MULTILINE | re.DOTALL)
                        if notes_match:
                            notes_body = notes_match.group(1)
                            done_entry = f"{now.strftime('%d/%m/%Y')} — {captured_verbatim} (done, via daily note)"
                            new_notes_body = notes_body
                            if new_notes_body and not new_notes_body.endswith("\n"):
                                new_notes_body += "\n"
                            new_notes_body += f"{done_entry}\n"
                            proj_text = proj_text[:notes_match.start(1)] + new_notes_body + proj_text[notes_match.end(1):]
                        
                        project_path.write_text(proj_text)
                        
                        entry = log_action.build_entry(
                            actor="EA",
                            trigger="Close daily note (Routine)",
                            action_type="daily-note-writeback",
                            action=f"Wrote back daily-note line to {captured_path_str}.",
                            confidence="Medium",
                            outcome="Written back — removed from Next action, logged in Notes & progress",
                            input_link=captured_path_str,
                        )
                        log_action.append_entry(brain_path, date_str, entry)
                        summary["reconciled"] += 1
                        
            if not hit:
                entry = log_action.build_entry(
                    actor="EA",
                    trigger="Close daily note (Routine)",
                    action_type="daily-note-writeback",
                    action=f"Reconciled daily-note line for {captured_path_str}.",
                    confidence="Medium",
                    outcome="Row not found at source, no write-back performed",
                    input_link=captured_path_str,
                )
                log_action.append_entry(brain_path, date_str, entry)
                summary["misses"].append({"project_path": captured_path_str, "verbatim": captured_verbatim})
                
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
