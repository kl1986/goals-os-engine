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
import heartbeat  # noqa: E402


def _git(brain_path: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(brain_path), *args], capture_output=True, text=True)


def run(brain_path: Path, now: dt.datetime = None) -> dict:
    now = now or dt.datetime.now()

    status = _git(brain_path, "status", "--porcelain")
    changed_files = [ln for ln in status.stdout.splitlines() if ln.strip()]
    if not changed_files:
        return {"committed": False, "commit_hash": None, "tag": None, "pushed": False}

    # Bump routine-state before staging, so the checkpoint commit records its own run.
    heartbeat.bump(brain_path, "Version control", now)

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
