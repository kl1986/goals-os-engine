#!/usr/bin/env python3
"""One-time migration: drop the <slug>-<number> ID prefix from every
existing ticket filename, and fix up any `Blocked by:` references that
pointed at the old ID.

Implements ADR-0020. Every ticket at `tasks/projects/<slug>/<file>.md` or
`tasks/areas/<slug>/<file>.md` is renamed to a filename slugified from
its own H1 title (truncated to ~60 characters at a word boundary for
long titles; a genuine title collision within the same folder gets a
`-2`, `-3`... suffix). A ticket whose slugified filename already matches
its current name is left untouched. Ticket content (frontmatter, body)
is never modified except for `Blocked by:` lines, which are rewritten
from the old bare `<slug>-<number>` token(s) to `[[wikilink]]`(s)
pointing at the ticket's new filename.

Run once, manually, against a live Brain (`--brain`). Safe to run twice
— a second pass finds every ticket already at its correctly-slugified
name (nothing to rename) and every `Blocked by:` line already using
wikilinks (nothing to fix), so it's a no-op.
"""

import argparse
import re
import sys
from pathlib import Path

MAX_SLUG_LENGTH = 60

H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)
BLOCKED_BY_RE = re.compile(r"^(> Blocked by: )(.+)$", re.MULTILINE)
WIKILINK_RE = re.compile(r"^\[\[.+\]\]$")


def slugify(text: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Lowercase, hyphenated, punctuation-stripped. Truncated to
    `max_length` at the last word boundary before the limit."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > max_length:
        truncated = slug[:max_length]
        if "-" in truncated:
            truncated = truncated.rsplit("-", 1)[0]
        slug = truncated
    return slug or "untitled"


def _unique_path(dest_dir: Path, filename: str, exclude: Path = None) -> Path:
    def _taken(candidate: Path) -> bool:
        return candidate.exists() and candidate != exclude

    candidate = dest_dir / filename
    if not _taken(candidate):
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while _taken(dest_dir / f"{stem}-{counter}{suffix}"):
        counter += 1
    return dest_dir / f"{stem}-{counter}{suffix}"


def _properly_filed_tickets(brain_path: Path):
    """Every `tasks/<projects|areas>/<slug>/<file>.md` ticket — mirrors
    ticket_normalization.py's own filing boundary. `tasks/_unfiled/` and
    anything directly under `tasks/` are out of scope (nothing to infer
    a slug from, so nothing this script touches)."""
    tasks_dir = brain_path / "tasks"
    if not tasks_dir.is_dir():
        return []
    tickets = []
    for kind in ("projects", "areas"):
        kind_dir = tasks_dir / kind
        if not kind_dir.is_dir():
            continue
        for slug_dir in sorted(p for p in kind_dir.iterdir() if p.is_dir()):
            tickets.extend(sorted(slug_dir.glob("*.md")))
    return tickets


def _old_id_token(path: Path) -> str:
    """The bare `<slug>-<number>` ID a `Blocked by:` line would have used
    for this file under the old ADR-0014 convention (e.g. "goals-os-11"
    for a file named either `goals-os-11.md` or
    `goals-os-11-scheduler-adapter-implementation.md`) — distinct from
    the full old filename stem, since `Blocked by:` never included the
    short-desc suffix. Returns None if the filename doesn't match that
    shape at all (nothing to map)."""
    slug = path.parent.name
    m = re.match(rf"^{re.escape(slug)}-(\d+)", path.stem)
    return f"{slug}-{m.group(1)}" if m else None


def rename_tickets(brain_path: Path):
    """Rename every properly-filed ticket to a slug of its own title.

    Returns `(manifest, lookup)`:
    - `manifest`: `{old_stem: new_stem}`, exactly one entry per ticket
      actually renamed (omits ones already at their correct name) — the
      real old filename, for reporting.
    - `lookup`: `manifest` plus one extra entry per renamed ticket whose
      old filename matched the bare `<slug>-<number>` shape, keyed by
      that bare ID — a `Blocked by:` line never included the
      short-desc suffix, so it needs this second string to resolve.
      Pass `lookup` (not `manifest`) to `fix_blocked_by_references()`.
    """
    brain_path = Path(brain_path)
    manifest = {}
    lookup = {}
    for path in _properly_filed_tickets(brain_path):
        text = path.read_text()
        m = H1_RE.search(text)
        title = m.group(1).strip() if m else "Untitled ticket"
        new_stem_target = slugify(title)
        if path.stem == new_stem_target:
            continue  # already at the correct name

        old_id_token = _old_id_token(path)
        new_path = _unique_path(path.parent, f"{new_stem_target}.md", exclude=path)
        new_path.write_text(text)
        if new_path != path:
            path.unlink()

        manifest[path.stem] = new_path.stem
        lookup[path.stem] = new_path.stem
        if old_id_token is not None:
            lookup[old_id_token] = new_path.stem

    return manifest, lookup


def fix_blocked_by_references(brain_path: Path, lookup: dict) -> list:
    """Rewrite every `> Blocked by: <old-id>[, <old-id>...]` line found
    across every properly-filed ticket, replacing any token that matches
    a key in `lookup` (pass `rename_tickets()`'s second return value,
    not its first — this needs the bare-ID aliases too) with a
    `[[new-stem]]` wikilink. A token that's already a wikilink, or
    doesn't match anything in `lookup`, is left untouched (it may
    already be on the new convention, or reference something outside
    this pass's scope). Returns the list of ticket paths whose
    `Blocked by` line was changed."""
    brain_path = Path(brain_path)
    changed = []
    for path in _properly_filed_tickets(brain_path):
        text = path.read_text()

        def _rewrite(match):
            prefix, tokens_str = match.group(1), match.group(2)
            tokens = [t.strip() for t in tokens_str.split(",")]
            new_tokens = []
            for token in tokens:
                if WIKILINK_RE.match(token):
                    new_tokens.append(token)
                elif token in lookup:
                    new_tokens.append(f"[[{lookup[token]}]]")
                else:
                    new_tokens.append(token)
            return prefix + ", ".join(new_tokens)

        new_text = BLOCKED_BY_RE.sub(_rewrite, text)
        if new_text != text:
            path.write_text(new_text)
            changed.append(path)

    return changed


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    manifest, lookup = rename_tickets(brain_path)
    if manifest:
        print(f"Renamed {len(manifest)} ticket(s):")
        for old_stem, new_stem in manifest.items():
            print(f"  - {old_stem}.md -> {new_stem}.md")
    else:
        print("No tickets needed renaming.")

    changed = fix_blocked_by_references(brain_path, lookup)
    if changed:
        print(f"\nFixed 'Blocked by' references in {len(changed)} ticket(s):")
        for path in changed:
            print(f"  - {path.relative_to(brain_path).as_posix()}")
    else:
        print("\nNo 'Blocked by' references needed fixing.")


if __name__ == "__main__":
    main()
