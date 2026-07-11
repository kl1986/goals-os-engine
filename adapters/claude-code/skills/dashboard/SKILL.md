---
name: dashboard
description: Regenerate <brain>/Dashboard.md — overdue Routines, pending Triage Plans, and today's Action Log summary. Safe to run any time; always fully overwrites the file. Use at the start of a session, or whenever the user wants a status surface.
allowed-tools:
  - Bash
triggers:
  - show my dashboard
  - /dashboard
---

# dashboard

The Claude Code binding for `protocols/dashboard.md`. All the computation lives in `scripts/dashboard.py` — never hand-write or hand-edit `Dashboard.md`; it's a pure derivation, regenerated in full every run.

## What to do

1. Determine the Brain path (ask if ambiguous).
2. Run:

```bash
python3 <path-to-goals-os-engine>/scripts/dashboard.py --brain "<path-to-brain>"
```

3. Relay the same summary back in-session (overdue routines, pending plans, today's log count) so the user doesn't need to open the file to get the headline — then point them at `Dashboard.md` for the full picture and its links.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines what the Dashboard surfaces and why it's read/link-only; `scripts/dashboard.py` is the portable implementation; this file is only the Claude Code binding. This skill never ticks a Triage Plan row or writes Action Log feedback on the user's behalf — those affordances are links, not actions this skill takes.
