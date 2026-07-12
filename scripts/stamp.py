#!/usr/bin/env python3
"""Stamp captured text into an immutable Raw Capture.

Implements protocols/capture.md — Phase 2's only capture path (manual/
text). Brain-path-aware port of v1's stamp.py: pure file I/O, zero LLM
calls, collision-safe naming, `source` is an open string.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "capture"


def build_frontmatter(date_str: str, source: str, capture_id: str) -> str:
    return (
        "---\n"
        "type: raw\n"
        f"date: {date_str}\n"
        f"source: {source}\n"
        f"id: {capture_id}\n"
        "raw: true\n"
        "---\n"
    )


def stamp(brain_path: Path, source: str, title: str, body: str, now: dt.datetime = None) -> Path:
    """Write one Raw Capture under inbox/raw/<source>/ and return its path.

    Filename doubles as the frontmatter `id`: `{date}-{HHMMSS}-{slug}`,
    with a numeric suffix appended on any collision — safe even for two
    captures with the same title in the same second.
    """
    now = now or dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    slug = slugify(title)

    dest_dir = brain_path / "inbox" / "raw" / source
    dest_dir.mkdir(parents=True, exist_ok=True)

    base_id = f"{date_str}-{time_str}-{slug}"
    capture_id = base_id
    counter = 2
    while (dest_dir / f"{capture_id}.md").exists():
        capture_id = f"{base_id}-{counter}"
        counter += 1

    path = dest_dir / f"{capture_id}.md"
    content = build_frontmatter(date_str, source, capture_id) + f"\n# {title}\n\n{body}\n"
    path.write_text(content)

    # Bumped after writing, so a crash mid-write never falsely records a run.
    heartbeat.bump(brain_path, "Capture sweep", now)
    return path


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--source", required=True, help="Open string, e.g. voice/email/meetings/web — no fixed list imposed")
    p.add_argument("--title", required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--body", help="Capture body text")
    group.add_argument("--body-file", help="Path to a file containing the capture body")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    body = args.body if args.body is not None else Path(args.body_file).expanduser().read_text()

    path = stamp(brain_path, args.source, args.title, body)
    print(f"Stamped: {path}")


if __name__ == "__main__":
    main()
