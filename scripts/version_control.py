#!/usr/bin/env python3
"""Version control Routine: commit, push, and tag a Brain checkpoint.

Implements protocols/version-control.md — pure git plumbing via
subprocess, no LLM-generated commit message. Off-site backup is simply a
`git push` to the Brain's existing private remote; no secondary target.
No-ops cleanly when the working tree is already clean.
"""

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from heartbeat import parse_table, TIMESTAMP_FORMAT  # noqa: E402


def _git(brain_path: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(brain_path), *args], capture_output=True, text=True)


def update_last_run(path: Path, routine: str, timestamp_str: str) -> bool:
    """Rewrite one Routine's Last-run cell in a 2-column routine-state.md. Returns True if found."""
    if not path.exists():
        return False
    text = path.read_text()
    if not any(r.get("Routine") == routine for r in parse_table(text)):
        return False

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"| {routine} |"):
            lines[i] = f"| {routine} | {timestamp_str} |"
            break
    path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
    return True


def run(brain_path: Path, now: dt.datetime = None) -> dict:
    now = now or dt.datetime.now()

    status = _git(brain_path, "status", "--porcelain")
    changed_files = [ln for ln in status.stdout.splitlines() if ln.strip()]
    if not changed_files:
        return {"committed": False, "commit_hash": None, "tag": None, "pushed": False}

    # Bump routine-state before staging, so the checkpoint commit records its own run.
    update_last_run(brain_path / "config" / "routine-state.md", "Version control", now.strftime(TIMESTAMP_FORMAT))

    _git(brain_path, "add", "-A")

    date_str = now.strftime("%Y-%m-%d")
    message = f"Brain checkpoint {date_str} — {len(changed_files)} file(s) changed"
    commit_result = _git(brain_path, "commit", "-m", message)
    if commit_result.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit_result.stderr}")

    commit_hash = _git(brain_path, "rev-parse", "--short", "HEAD").stdout.strip()

    push_result = _git(brain_path, "push")
    pushed = push_result.returncode == 0

    tag = f"brain-{now.strftime('%Y-%m-%d-%H%M')}"
    _git(brain_path, "tag", tag)
    if pushed:
        _git(brain_path, "push", "origin", tag)

    return {"committed": True, "commit_hash": commit_hash, "tag": tag, "pushed": pushed}


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    result = run(brain_path)
    if not result["committed"]:
        print("Clean tree — nothing to commit.")
        return

    print(f"Committed {result['commit_hash']}, tagged {result['tag']}.")
    print("Pushed to origin." if result["pushed"] else "Commit created locally — push failed, check your remote/network.")


if __name__ == "__main__":
    main()
