#!/usr/bin/env python3
"""One-time migration: Project notes' `## Next action` lines -> tickets.

Implements ticket 27's Execution Plan item 2 (ADR-0017, ADR-0020). Walks
every Project note under `projects/*/*.md`; for each `- [ ]` line under
that note's `## Next action` section, in file order, creates a new
`status: prioritised` ticket under `tasks/projects/<slug>/`, filename
slugified from the line's own text (ADR-0020 — no slug/number prefix; a
title collision within the same folder gets a `-2`, `-3`... suffix),
then deletes the `## Next action` section (heading + body) from the
Project note entirely — per `project-tracking.md` v1, that section no
longer exists in the schema at all.

Run once, manually, against a live Brain (`--brain`). Not itself
idempotent in the sense of "safe to run twice for the same content" —
a Project note with no `## Next action` section left (because this
script already deleted it) simply has nothing left to migrate, so a
second run is a no-op for that note, same as any other already-migrated
source.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

# Matches from the `## Next action` heading up to (not including) the next
# `## ` heading or end of string — used both to extract the body (group 1)
# and, separately, to delete the whole section (heading included).
NEXT_ACTION_SECTION_RE = re.compile(r"\n## Next action\s*\n(.*?)(?=\n## |\Z)", re.DOTALL)
NEXT_ACTION_FULL_RE = re.compile(r"\n## Next action\s*\n.*?(?=\n## |\Z)", re.DOTALL)
CHECKBOX_LINE_RE = re.compile(r"^- \[ \] (.+)$")

BLANK_FIELDS = ("priority", "component", "parent", "assignee", "github", "goal")
MAX_SLUG_LENGTH = 60


def slugify(text: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Lowercase, hyphenated, punctuation-stripped. Truncated to
    `max_length` at the last word boundary before the limit (ADR-0020) —
    a Next-action line can be a full free-text sentence, and the
    *filename* shouldn't run to 150+ characters even though the ticket's
    own H1 (built from the verbatim line) is never truncated."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > max_length:
        truncated = slug[:max_length]
        if "-" in truncated:
            truncated = truncated.rsplit("-", 1)[0]
        slug = truncated
    return slug or "untitled"


def _unique_path(dest_dir: Path, filename: str) -> Path:
    """`dest_dir/filename`, or a `-2`, `-3`, ... suffixed variant if that
    already exists — a title collision within the same folder is the
    exceptional case, not the norm, but silently overwriting one would be
    worse."""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while (dest_dir / f"{stem}-{counter}{suffix}").exists():
        counter += 1
    return dest_dir / f"{stem}-{counter}{suffix}"


def _build_ticket_text(title: str, created: str) -> str:
    lines = ["---", "status: prioritised", "type: task"]
    for key in BLANK_FIELDS:
        lines.append(f"{key}: ")
    lines.append(f"created: {created}")
    lines.append("resolved: ")
    lines.append("---")
    frontmatter = "\n".join(lines)
    return f"{frontmatter}\n\n# {title}\n"


def migrate_project_note(note_path: Path, tasks_projects_dir: Path, slug: str, created: str) -> int:
    """Migrate one Project note's `## Next action` lines into tickets under
    `tasks_projects_dir/<slug>/`, then delete the section from the note.
    Returns the count of tickets created (0 if the section was absent,
    or present but empty — both are no-ops for ticket creation, though an
    empty section is still deleted, since it no longer belongs in the
    schema either way)."""
    text = note_path.read_text()
    section_match = NEXT_ACTION_SECTION_RE.search(text)
    if not section_match:
        return 0

    checkbox_lines = []
    for raw_line in section_match.group(1).splitlines():
        m = CHECKBOX_LINE_RE.match(raw_line.strip())
        if m:
            title = m.group(1).strip()
            if title:
                checkbox_lines.append(title)

    count = 0
    if checkbox_lines:
        slug_dir = tasks_projects_dir / slug
        slug_dir.mkdir(parents=True, exist_ok=True)

        for title in checkbox_lines:
            ticket_path = _unique_path(slug_dir, f"{slugify(title)}.md")
            ticket_path.write_text(_build_ticket_text(title, created))
            count += 1

    new_text = NEXT_ACTION_FULL_RE.sub("", text, count=1)
    if new_text != text:
        note_path.write_text(new_text)

    return count


def migrate(brain_path: Path, now: dt.datetime = None) -> dict:
    """Walk every Project note, migrating each one's `## Next action`
    lines to tickets. Returns `{slug: tickets_created}` for every Project
    that had at least one line migrated — Projects with an absent or
    empty section are omitted entirely (matches ADR-0017's "no-op for
    nothing to migrate" posture)."""
    now = now or dt.datetime.now()
    created = now.strftime("%Y-%m-%d")
    brain_path = Path(brain_path)
    projects_dir = brain_path / "projects"
    tasks_projects_dir = brain_path / "tasks" / "projects"

    summary = {}
    if not projects_dir.is_dir():
        return summary

    for slug_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        slug = slug_dir.name
        for note_path in sorted(slug_dir.glob("*.md")):
            count = migrate_project_note(note_path, tasks_projects_dir, slug, created)
            if count:
                summary[slug] = summary.get(slug, 0) + count

    return summary


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    summary = migrate(brain_path)
    if not summary:
        print("Nothing to migrate — no Project note had a non-empty '## Next action' section.")
        return

    total = sum(summary.values())
    print(f"Migrated {total} ticket(s) across {len(summary)} project(s):")
    for slug, count in summary.items():
        print(f"  - {slug}: {count} ticket(s) created")


if __name__ == "__main__":
    main()
