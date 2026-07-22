---
name: ticket-normalization
description: Fully automatic Routine — scans tasks/**/*.md for any ticket missing an ADR-0015 frontmatter key, backfills what's missing, and renames/re-IDs it to <slug>-N-<short-desc>.md (or relocates it to tasks/_unfiled/ if no slug can be inferred). Zero confirmation, no Plan to approve. Use when Heartbeat flags "Ticket normalization" as overdue, or when the user asks to run ticket normalization directly.
allowed-tools:
  - Bash
triggers:
  - ticket normalization
  - normalize tickets
  - /ticket-normalization
---

# ticket-normalization

The Claude Code binding for `protocols/ticket-normalization.md`. Like `graduation-check`, this Routine is **fully automatic — it never asks for confirmation and never produces a document awaiting approval.** Every write happens through `scripts/ticket_normalization.py` — never a direct hand-edit of a ticket file — so backfilled frontmatter and renamed filenames stay exactly what the Protocol specifies.

## What to do

1. Determine the Brain path (ask if ambiguous; never guess).

2. Run:

```bash
python3 <path-to-goals-os-engine>/scripts/ticket_normalization.py --brain "<path-to-brain>"
```

   This scans every file under `tasks/**/*.md`, skips anything already conforming (no ADR-0015 key missing), and for everything else: backfills missing keys blank (`type` defaults to `task`), infers a `<slug>` from the file's immediate parent folder under `tasks/projects/<slug>/` or `tasks/areas/<slug>/`, renames it to the next free `<slug>-N-<short-desc>.md`, or — if no slug can be inferred at all — relocates it to `tasks/_unfiled/` under its existing name. It logs one Action Log entry per file modified and bumps this Routine's own row in `config/routine-state.md`, regardless of whether anything needed changing.

3. Report back plainly, in one or two lines: if nothing needed normalizing, say so ("Ticket normalization: nothing to report — every ticket already conforms."). Otherwise state how many files were normalized, and flag anything moved to `tasks/_unfiled/` by name — those need a human to re-file them under a real Project/Area folder, since the script can't infer where they belong.

## Contract this Adapter fulfils (ADR-0002)

`protocols/ticket-normalization.md` defines what "missing a key" means, the backfill defaults, the rename/re-ID scheme, and the no-inferable-slug fallback to `tasks/_unfiled/`; `scripts/ticket_normalization.py` is the full implementation — detection, backfill, rename/relocate, Action Log entries, and the routine-state bump; this file is only the Claude Code binding that calls it and relays the result. It performs zero judgement of its own and zero confirmation — this Routine never waits on the user, same as `graduation-check`.
