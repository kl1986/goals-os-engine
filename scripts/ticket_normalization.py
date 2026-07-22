#!/usr/bin/env python3
"""Ticket normalization Routine: backfill missing ADR-0015 frontmatter keys
and rename/re-ID non-conforming ticket files.

Implements protocols/ticket-normalization.md (ADR-0019, ticket 27's
Execution Plan item 5). Scans `tasks/**/*.md` for any file missing at
least one ADR-0015 frontmatter key (`kanban_order` excluded — Base
Board-managed, not part of this check). A file with every key already
present is left completely untouched (this is what makes a second run
idempotent). For every non-conforming file:

- Backfills each missing key as blank, except `type`, which defaults to
  `task` if missing.
- Infers a `<slug>` from the file's immediate parent folder under
  `tasks/projects/<slug>/` or `tasks/areas/<slug>/`, finds the next free
  `<slug>-N` number among siblings in that folder, and renames the file
  to `<slug>-N-<short-desc>.md` (short-desc slugified from the file's H1
  title; if there's no H1 at all, short-desc is `untitled` and an
  `# Untitled ticket` H1 is inserted so the file isn't left titleless).
- A file with no inferable slug (e.g. sitting directly under `tasks/`,
  not inside a `tasks/projects/<slug>/` or `tasks/areas/<slug>/`
  subfolder) is relocated to `tasks/_unfiled/` instead — frontmatter is
  still backfilled, but it keeps its own filename; there's no `<slug>-N`
  to number it against.

Logs one Action Log entry per file modified.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import log_action  # noqa: E402

ROUTINE_NAME = "Ticket normalization"

# ADR-0015's frontmatter keys, excluding `kanban_order` (Base Board-managed,
# not part of this check per ADR-0019's resolution).
REQUIRED_KEYS = (
    "status", "type", "priority", "component", "parent",
    "assignee", "github", "goal", "created", "resolved",
)

FRONTMATTER_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)
FRONTMATTER_KEY_RE = re.compile(r"^([\w-]+):")
H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def _existing_frontmatter_keys(text: str) -> set:
    fm_match = FRONTMATTER_RE.match(text)
    if not fm_match:
        return set()
    keys = set()
    for line in fm_match.group(2).splitlines():
        m = FRONTMATTER_KEY_RE.match(line)
        if m:
            keys.add(m.group(1))
    return keys


def missing_keys(text: str) -> list:
    """ADR-0015 keys not present in `text`'s frontmatter, in REQUIRED_KEYS
    order — empty if the file already conforms (nothing to do at all)."""
    existing = _existing_frontmatter_keys(text)
    return [k for k in REQUIRED_KEYS if k not in existing]


def backfill_frontmatter(text: str, missing: list) -> str:
    """Append each key in `missing` to the file's frontmatter block, blank
    except `type: task`. Creates a frontmatter block from scratch (all
    REQUIRED_KEYS) if the file somehow has none at all."""
    fm_match = FRONTMATTER_RE.match(text)
    if not fm_match:
        fm_lines = [f"{k}: {'task' if k == 'type' else ''}" for k in REQUIRED_KEYS]
        return "---\n" + "\n".join(fm_lines) + "\n---\n\n" + text.lstrip("\n")

    lines = fm_match.group(2).splitlines()
    for key in missing:
        value = "task" if key == "type" else ""
        lines.append(f"{key}: {value}")
    new_block = "\n".join(lines)
    return text[: fm_match.start(2)] + new_block + text[fm_match.end(2):]


def _body_after_frontmatter(text: str):
    fm_match = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
    if not fm_match:
        return text, 0
    return text[fm_match.end():], fm_match.end()


def h1_title(text: str):
    body, _ = _body_after_frontmatter(text)
    m = H1_RE.search(body)
    return m.group(1).strip() if m else None


def ensure_title(text: str, fallback_title: str) -> str:
    """Insert `# {fallback_title}` as the file's H1 if it has none at all
    (a known-malformed ticket with only `status`/`kanban_order` and no
    body). Leaves an existing H1 completely alone."""
    body, idx = _body_after_frontmatter(text)
    if H1_RE.search(body):
        return text
    new_body = f"\n# {fallback_title}\n\n{body.lstrip(chr(10))}"
    return text[:idx] + new_body


def infer_slug(rel_path: Path):
    """`<slug>` if `rel_path` is exactly `tasks/<projects|areas>/<slug>/<file>.md`,
    else None (no inferable slug — the file moves to `tasks/_unfiled/`
    instead of being renamed/re-IDed)."""
    parts = rel_path.parts
    if len(parts) == 4 and parts[0] == "tasks" and parts[1] in ("projects", "areas"):
        return parts[2]
    return None


def next_free_number(slug_dir: Path, slug: str, exclude: Path = None) -> int:
    """Highest existing `<slug>-N` number among `slug_dir`'s siblings, plus
    one (1 if none) — never collides with an existing ticket."""
    highest = 0
    if slug_dir.is_dir():
        prefix = f"{slug}-"
        for path in slug_dir.glob(f"{prefix}*.md"):
            if exclude is not None and path == exclude:
                continue
            rest = path.stem[len(prefix):]
            m = re.match(r"^(\d+)", rest)
            if m:
                highest = max(highest, int(m.group(1)))
    return highest + 1


def _unique_path(dest_dir: Path, filename: str) -> Path:
    """`dest_dir/filename`, or a `-2`, `-3`, ... suffixed variant if that
    already exists (defensive — two differently-malformed files landing
    under `tasks/` with the same bare name is an edge case, not the
    common path, but silently overwriting one would be worse)."""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while (dest_dir / f"{stem}-{counter}{suffix}").exists():
        counter += 1
    return dest_dir / f"{stem}-{counter}{suffix}"


def normalize_file(path: Path, brain_path: Path, now: dt.datetime,
                    actor: str = "EA", trigger: str = "Ticket normalization (Routine)"):
    """Normalize one ticket file if it's missing any ADR-0015 key.

    Returns None if the file already conforms (untouched — this is the
    idempotency guarantee: a second run over an already-normalized file
    finds nothing missing and does nothing). Otherwise returns a summary
    dict and logs one Action Log entry for the change made."""
    text = path.read_text()
    missing = missing_keys(text)
    if not missing:
        return None

    new_text = backfill_frontmatter(text, missing)
    rel_path = path.relative_to(brain_path)
    slug = infer_slug(rel_path)

    if slug is not None:
        title = h1_title(new_text)
        if title is None:
            new_text = ensure_title(new_text, "Untitled ticket")
            short_desc = "untitled"
        else:
            short_desc = slugify(title)

        slug_dir = path.parent
        next_num = next_free_number(slug_dir, slug, exclude=path)
        new_path = slug_dir / f"{slug}-{next_num}-{short_desc}.md"
        action = "renamed"
    else:
        unfiled_dir = brain_path / "tasks" / "_unfiled"
        unfiled_dir.mkdir(parents=True, exist_ok=True)
        new_path = _unique_path(unfiled_dir, path.name)
        action = "unfiled"

    new_path.write_text(new_text)
    if new_path != path:
        path.unlink()

    new_rel_path = new_path.relative_to(brain_path).as_posix()
    old_rel_path = rel_path.as_posix()

    entry = log_action.build_entry(
        actor=actor,
        trigger=trigger,
        action_type="ticket-normalize",
        action=f"Normalized ticket {old_rel_path} -> {new_rel_path} "
                f"(backfilled {len(missing)} missing field(s): {', '.join(missing)}).",
        confidence="High",
        outcome=f"Ticket {action} to {new_rel_path}",
        input_link=new_rel_path,
        time_str=now.strftime("%H:%M"),
    )
    log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)

    return {
        "old_path": path, "new_path": new_path,
        "action": action, "missing": missing,
    }


def normalize(brain_path: Path, now: dt.datetime = None) -> list:
    """Scan `tasks/**/*.md` and normalize every non-conforming file.

    Snapshots the file list up front so files created/renamed mid-run
    (e.g. a ticket relocated to `tasks/_unfiled/`) are never
    re-processed within the same pass. Always bumps this Routine's own
    `config/routine-state.md` row, even if nothing needed changing."""
    now = now or dt.datetime.now()
    brain_path = Path(brain_path)
    tasks_dir = brain_path / "tasks"

    changes = []
    if tasks_dir.is_dir():
        paths = sorted(tasks_dir.rglob("*.md"))
        for path in paths:
            if not path.is_file():
                continue
            result = normalize_file(path, brain_path, now)
            if result:
                changes.append(result)

    heartbeat.bump(brain_path, ROUTINE_NAME, now)
    return changes


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    changes = normalize(brain_path)
    if not changes:
        print("Nothing to normalize.")
        return

    print(f"Normalized {len(changes)} ticket(s):")
    for change in changes:
        old_rel = change["old_path"].relative_to(brain_path).as_posix()
        new_rel = change["new_path"].relative_to(brain_path).as_posix()
        print(f"  - {old_rel} -> {new_rel} ({change['action']})")


if __name__ == "__main__":
    main()
