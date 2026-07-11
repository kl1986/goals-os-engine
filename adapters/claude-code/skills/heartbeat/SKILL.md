---
name: heartbeat
description: Report which Routines are overdue against the Engine's manifest (protocols/routines.md) and a Brain's config/routine-state.md. Nudge-only — never runs anything. Use at the start of a session, or whenever the user wants to know what's due.
allowed-tools:
  - Bash
triggers:
  - heartbeat
  - what's overdue
  - /heartbeat
---

# heartbeat

The Claude Code binding for `protocols/routines.md`'s due-check. All the logic — which Routines are heartbeat-checkable, which are implemented, and the overdue comparison — lives in `scripts/heartbeat.py`; this skill only calls it and relays the result.

## What to do

1. Determine the Brain path — the Brain currently in use (ask if ambiguous; never guess).
2. Run:

```bash
python3 <path-to-goals-os-engine>/scripts/heartbeat.py --brain "<path-to-brain>"
```

3. Relay the output as-is. If routines are overdue, name them and point at the relevant skill to run them (`triage-plan`, `dashboard`, `version-control`) — but never run them yourself without being asked. This is a nudge, not a dispatch.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines what's checkable and why; `scripts/heartbeat.py` is the portable, runtime-agnostic implementation; this file is only the Claude Code binding. Heartbeat never auto-runs a Routine regardless of how overdue it is — auto-run tied to autonomy level is Phase 5 (ADR-0006), not built here.
