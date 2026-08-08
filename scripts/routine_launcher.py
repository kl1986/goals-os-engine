#!/usr/bin/env python3
"""
Routine Launcher Dispatcher
Maps a whitelist of Routine identifiers to deterministic engine scripts or headless Claude commands.
Emits macOS notifications upon completion or failure.
"""

import argparse
import os
import subprocess
import sys

ROUTINES = {
    "generate-daily-note": {
        "name": "Generate Daily Note",
        "type": "script",
        "command": [sys.executable, "scripts/daily_note.py", "generate"]
    },
    "close-daily-note": {
        "name": "Close Daily Note",
        "type": "script",
        "command": [sys.executable, "scripts/daily_note.py", "close"]
    },
    "triage": {
        "name": "Triage (Email)",
        "type": "script",
        "command": [sys.executable, "scripts/triage.py", "--source", "email"]
    },
    "refresh-dashboard": {
        "name": "Refresh Dashboard",
        "type": "script",
        "command": [sys.executable, "scripts/dashboard.py"]
    },
    "rule-learning": {
        "name": "Rule Learning",
        "type": "script",
        "command": [sys.executable, "scripts/rule_learning.py", "scan"]
    }
}

def notify_macos(message: str, title: str = "Routine Launcher") -> None:
    try:
        subprocess.run(
            [
                "osascript",
                "-e", "on run argv",
                "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
                "-e", "end run",
                "--", message, title
            ],
            check=True,
            capture_output=True
        )
    except Exception as e:
        print(f"Warning: Failed to send macOS notification: {e}", file=sys.stderr)

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Goals OS Routine Launcher Dispatcher")
    parser.add_argument("routine", help="The identifier of the routine to launch")
    parser.add_argument("--brain", help="Path to the Brain")

    args = parser.parse_args(argv)

    brain_path = args.brain or os.environ.get("GOALS_OS_BRAIN_PATH")
    if not brain_path:
        print("Error: --brain argument or GOALS_OS_BRAIN_PATH environment variable is required.", file=sys.stderr)
        notify_macos("Error: Brain path is missing.", title="Routine Launcher")
        sys.exit(1)

    routine_id = args.routine

    if routine_id not in ROUTINES:
        print(f"Error: Unknown routine identifier '{routine_id}'.", file=sys.stderr)
        notify_macos(f"Error: Unknown routine '{routine_id}'.", title="Routine Launcher")
        sys.exit(1)

    routine = ROUTINES[routine_id]
    cmd = routine["command"].copy()
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if routine["type"] == "script":
        cmd[1] = os.path.join(repo_root, cmd[1])
        cmd.insert(2, "--brain")
        cmd.insert(3, brain_path)

    try:
        subprocess.run(cmd, check=True)
        notify_macos(f"{routine['name']} completed successfully.", title=routine['name'])
    except subprocess.CalledProcessError as e:
        print(f"Error: Routine {routine_id} failed with exit code {e.returncode}", file=sys.stderr)
        notify_macos(f"{routine['name']} failed.", title=routine['name'])
        sys.exit(e.returncode)
    except Exception as e:
        print(f"Error launching routine {routine_id}: {e}", file=sys.stderr)
        notify_macos(f"{routine['name']} failed.", title=routine['name'])
        sys.exit(1)

if __name__ == "__main__":
    main()
