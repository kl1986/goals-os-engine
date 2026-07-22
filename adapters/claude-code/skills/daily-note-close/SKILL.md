---
name: daily-note-close
description: Close out today's daily note — reconcile every ticked "## Project next actions" line back to its source ticket (parse the [[ticket file]] wikilink, write status: done + resolved: <today> directly into that ticket's frontmatter, or log a miss if the ticket can't be found), then archive <brain>/YYYY-MM-DD.md to <brain>/archive/daily-notes/YYYY-MM-DD.md. Use in the evening, or whenever the user wants their daily note wrapped up for the day.
allowed-tools:
  - Bash
triggers:
  - close my daily note
  - wrap up my daily note
  - /daily-note-close
---

# daily-note-close

The Claude Code binding for the "Close daily note" Routine in `protocols/daily-note.md`. All the logic — parsing ticked `## Project next actions` lines, resolving each line's `[[ticket file]]` wikilink to the ticket file under `tasks/**/` (ADR-0018), the write-back (`status: done` + `resolved: <today, ISO YYYY-MM-DD>` written straight into that ticket's own frontmatter) or the miss (Action Log entry, checkbox left as-is), and the archive move — lives in `scripts/daily_note.py`'s `close_daily_note`. This skill only calls it and relays the result.

## What to do

1. Determine the Brain path (ask if ambiguous).
2. Run:

```bash
python3 <path-to-goals-os-engine>/scripts/daily_note.py --brain "<path-to-brain>" close
```

3. Relay how many Project-next-actions lines were reconciled and how many were misses (a miss means the linked ticket file couldn't be found under `tasks/**/` — flag these to the user, since no write-back happened for them even though the Action Log has the detail). Confirm the note was archived to `archive/daily-notes/`.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the reconciliation rule (the `[[ticket file]]` wikilink is the stable reference, not a verbatim-text match or line number) and the miss-handling posture (report, don't silently drop); `scripts/daily_note.py` is the portable implementation; this file is only the Claude Code binding. This skill never carries tasks forward itself — that's the *next morning's* `daily-note-generate` skill's job, not this one's — and it never touches `## Waiting for` (read-only, no write-back, ever).
