---
name: version-control
description: Commit, push, and tag a Brain checkpoint (git add -A, generated commit message, git push, brain-{timestamp} tag). No-ops cleanly on a clean tree. Use when the user wants to back up/checkpoint their Brain, or when Heartbeat flags Version control as overdue.
allowed-tools:
  - Bash
triggers:
  - checkpoint my brain
  - back up my brain
  - /version-control
---

# version-control

The Claude Code binding for `protocols/version-control.md`. All the git plumbing lives in `scripts/version_control.py` — never run `git commit`/`git push` yourself outside the script; the generated message and tag format are part of the Protocol's contract.

## What to do

1. Determine the Brain path (ask if ambiguous).
2. Run:

```bash
python3 <path-to-goals-os-engine>/scripts/version_control.py --brain "<path-to-brain>"
```

3. Relay the result: if it reports "Clean tree — nothing to commit," tell the user there was nothing to back up. Otherwise report the commit hash and tag, and flag clearly if the push failed (the commit still happened locally — that's not silently swallowed).

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the checkpoint mechanics (no-op on clean, generated message, push, tag); `scripts/version_control.py` is the portable implementation; this file is only the Claude Code binding. This skill never sets up unattended scheduling — it only fires when invoked, whether that's a direct ask or a Heartbeat nudge.
