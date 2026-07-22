---
name: daily-note-generate
description: Create or additively refresh <brain>/YYYY-MM-DD.md — today's daily note (Today's tasks, Project next actions, Waiting for, Notes). A brand-new day always gets a fresh file, with any still-unchecked Today's-tasks lines carried forward from the most recent archived note. Re-running the same day only adds new rows; it never touches or reorders existing lines. Use each morning, or whenever the user wants their daily note (re)generated.
allowed-tools:
  - Bash
triggers:
  - generate my daily note
  - refresh my daily note
  - /daily-note-generate
---

# daily-note-generate

The Claude Code binding for the "Daily note" Routine in `protocols/daily-note.md`. All the logic — the four-section schema, additive-only same-day refresh, carry-forward of unchecked tasks, the Project-next-actions scan (ADR-0018: `tasks/projects/*/` + `tasks/areas/*/` tickets with `status: prioritised` or `status: in-progress`, one row per matching ticket, Project tickets gated on the parent Project note's `status: Active`, Area tickets unconditional), and the Waiting For scan (reusing `dashboard.py`'s `_open_waiting_for`) — lives in `scripts/daily_note.py`'s `generate_daily_note`. This skill only calls it and relays the result.

## What to do

1. Determine the Brain path (ask if ambiguous).
2. Run:

```bash
python3 <path-to-goals-os-engine>/scripts/daily_note.py --brain "<path-to-brain>" generate
```

3. Relay the path it wrote to. If this was a brand-new day and tasks were carried forward from yesterday's archived note, mention how many. Point the user at the file for `## Notes` and manual `## Today's tasks` additions — those are theirs to edit freely.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the schema, the additive-only refresh rule, and what may vs. may not be carried forward; `scripts/daily_note.py` is the portable implementation; this file is only the Claude Code binding. This skill never hand-edits `<brain>/YYYY-MM-DD.md` itself and never invents a fifth section. Each Project-next-actions row links directly to its source ticket via a plain `[[ticket file]]` wikilink (ADR-0018) — no `daily-note-src` comment exists in this schema at all; the wikilink itself is the stable reference the "Close daily note" Routine's write-back relies on.
