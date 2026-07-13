#!/usr/bin/env python3
"""Sweep inbox/_dropzone/ into real Raw Captures via stamp().

The first real puller for PRD §8's "Capture sweep" routine (Wayfinder
ticket 05, Cutover alignment map). iOS Shortcuts write bare files —
no naming discipline, no frontmatter — into inbox/_dropzone/<...>/,
deliberately outside inbox/raw/ so nothing there is ever touched twice
(Principle 2). This script is the only thing that turns a drop-zone
file into a Raw Capture, and it deletes the original once stamp()
has written it successfully.

Drop-zone layout encodes source + modality via folder path alone, so
the Shortcut side never has to write frontmatter (ADR-0011):

    inbox/_dropzone/meetings/      -> source=meetings
    inbox/_dropzone/text/voice/    -> source=text, input-modality=voice
    inbox/_dropzone/text/typed/    -> source=text, input-modality omitted
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stamp  # noqa: E402

# (relative path under inbox/_dropzone/, source, input_modality)
DROPZONE_TARGETS = [
    (("meetings",), "meetings", None),
    (("text", "voice"), "text", "voice"),
    (("text", "typed"), "text", None),
]

MAX_TITLE_LEN = 60


def derive_title(source: str, body: str, captured_at: dt.datetime) -> str:
    if source == "meetings":
        return f"Meeting {captured_at.strftime('%Y-%m-%d %H:%M')}"
    first_line = body.strip().splitlines()[0] if body.strip() else ""
    if 0 < len(first_line) <= MAX_TITLE_LEN:
        return first_line
    collapsed = " ".join(body.split())
    return collapsed[:MAX_TITLE_LEN].rstrip() or "Capture"


def sweep(brain_path: Path) -> list:
    """Process every file across all drop-zone targets. Returns stamped paths."""
    dropzone_root = brain_path / "inbox" / "_dropzone"
    stamped = []

    for subpath_parts, source, input_modality in DROPZONE_TARGETS:
        folder = dropzone_root.joinpath(*subpath_parts)
        if not folder.is_dir():
            continue

        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.name.startswith("."):
                continue

            body = f.read_text().strip()
            if not body:
                print(f"Skipped (empty): {f}", file=sys.stderr)
                continue

            captured_at = dt.datetime.fromtimestamp(f.stat().st_mtime)
            title = derive_title(source, body, captured_at)

            path = stamp.stamp(
                brain_path, source, title, body,
                now=captured_at, input_modality=input_modality,
            )
            stamped.append(path)
            f.unlink()
            print(f"Swept {f.name} -> {path}")

    return stamped


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    args = p.parse_args(argv)

    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    stamped = sweep(brain_path)
    if not stamped:
        print("Dropzone sweep: nothing to do.")


if __name__ == "__main__":
    main()
