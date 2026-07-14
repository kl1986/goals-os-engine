# Protocol: Daily note (v1)

A single, once-daily "command centre" note at the Brain root. Distinct from the pure-derivation Dashboard, the daily note is additive-only within a day and accumulates edits (ticked checkboxes) the user makes during the day. It is governed by two Routines: "Daily note" (generation, morning) and "Close daily note" (reconciliation + archive, evening).

## Schema

`<brain>/YYYY-MM-DD.md` — the Brain root, singular. Not a `daily-notes/` subfolder.

```yaml
---
type: daily-note
date: YYYY-MM-DD
tags:
  - daily-note
---
```

Unlike the Dashboard, there is no `generated:` timestamp because this file is user-edited, not purely derived.

Body, in this exact order:

```markdown
# <Weekday, D Month YYYY>

## Today's tasks
- [ ]

## Project next actions

## Waiting for

## Notes
```

## Daily note Routine (Generation & refresh)

The generation Routine (cadence morning, heartbeat-checkable daily, risk tier internal & reversible, owner EA) uses `scripts/daily_note.py`'s `generate_daily_note` plus an Adapter skill.

- Each new calendar day always gets a brand-new file. There is no cross-day continuation of the same file.
- Re-invoking generation within the same day is **additive only**. It only ever adds rows for anything not already present (new project next-actions, new triaged captures filed via the `today` destination, new Waiting For items). It never touches, reorders, or removes an existing line. This is different from `dashboard.md`, which fully overwrites every run.
- **Carry-forward:** Generation scans the most recently archived note (`archive/daily-notes/`, picking the lexicographically-latest filename) for any still-unchecked `## Today's tasks` line, and copies it verbatim into the new day's `## Today's tasks`. This is origin-blind: a manually-typed task and a capture-derived task carry forward identically. This is the **only** section needing carry-forward. `## Project next actions` and `## Waiting for` are live mirrors of an external source (project notes, person hubs), so an unresolved item naturally persists at the source without carry-forward logic here.

On completion, it bumps its own "Daily note" row in `config/routine-state.md` (`heartbeat.bump`), matching every other Routine.

## Project next-actions sourcing

Computed as part of the same generation scan (read-only, nothing changes on the project note at generation time).

- **Filter:** Every project under `projects/*/*.md` with frontmatter `status: Active` (a deliberate stopgap, no other filter).
- Takes the first unchecked (`- [ ]`) line under that project's `## Next action` section, in file order. A project with an empty or fully-ticked `## Next action` is silently skipped (not an error).
- **Rendered:** `- [ ] {task text} — [[Project Name]]` where `Project Name` is the project note's filename without `.md`.

## Write-back mechanism

`## Project next actions` is the **one section** that carries a machine-readable reference back to its source, because its ticked items imply an action to take elsewhere (removing the item at the source). Manual entries, triaged captures, and Waiting For items never carry this reference.

The reference is an HTML comment trailing the line, invisible in Obsidian preview:
`<!-- daily-note-src: <project note path relative to brain root> | <verbatim original Next-action line text, exactly as it appears after "- [ ] "> -->`

Full example:
```markdown
- [ ] Order shelves for the shed — [[Clear the garage]] <!-- daily-note-src: projects/clear-the-garage/Clear the garage.md | Order shelves for the shed -->
```

- Matching is by this verbatim text, not a line number or index. This is robust to the source list reordering, and survives the user hand-editing the *visible* task wording in the daily note (reconciliation only ever reads the comment, never the visible text).
- **What "written back" means:** Run by the "Close daily note" Routine (evening) over every ticked `## Project next actions` line. The matched source line is removed entirely from the project's `## Next action` section, and a dated done-entry is appended to that project's `## Notes & progress` section. E.g. `13/07/2026 — Order shelves for the shed (done, via daily note)` (date in DD/MM/YYYY, British convention).
- **Conflict handling:** If the exact verbatim text can't be found in the project's current `## Next action` (e.g. edited, removed, or already done another way), it does **not** silently drop it. The daily-note checkbox stays ticked as-is, but an Action Log entry is written recording the miss (outcome `"Row not found at source, no write-back performed"`). This is the same "report, don't swallow" posture `execute.md` uses for unfileable Triage rows.

## Close daily note Routine

A thin, mechanical bookend Routine (cadence evening, heartbeat-checkable daily, risk tier internal & reversible, owner EA). Uses `scripts/daily_note.py`'s `close_daily_note` plus an Adapter skill.

What it does, in order, nothing more:
1. Runs the write-back reconciliation above over every ticked `## Project next actions` line (parses `daily-note-src`, matches at source, removes + appends done-entry, or logs the miss per-line — no separate summary log entry on top of the per-line ones).
2. Moves `<brain>/YYYY-MM-DD.md` to `<brain>/archive/daily-notes/YYYY-MM-DD.md`.

It bumps its own "Close daily note" row in `config/routine-state.md`. Note explicitly: carry-forward (scanning yesterday's archive for unchecked Today's-tasks lines) is **NOT** this routine's job — that is the *next morning's* generation step reading backward. Close-daily-note is a thin, mechanical bookend with no new judgement calls.

## Waiting For section

Computed by the same Daily-note generation skill. One more scan of `people/*.md` (the same source `dashboard.py`'s `_open_waiting_for()` already scans, per `protocols/people-tracking.md`). 

Read-only, no write-back, and no `daily-note-src` comment ever. `people-tracking.md`'s existing rule ("a hub is the only place a delegation ever gets logged — never a second file, never the Dashboard") applies here too; the daily note is exactly such a second surface.

Renders as plain bullets, NOT checkboxes (a checkbox would be a false affordance — ticking it would silently do nothing): `- {item text} — [[Person Hub]]`. Ordered by hub filename, with items for the same person grouped together (same shape the Dashboard already uses).

## Triage / Execute destination

A new `today` destination literal (parallel to the existing `discard` literal) produces action type `file-capture-today`. Full mechanics are documented in [`execute.md`](./execute.md); do not duplicate them here.

## Adapter binding

See [`adapters/claude-code/skills/daily-note-generate/`](../adapters/claude-code/skills/daily-note-generate/) and [`adapters/claude-code/skills/daily-note-close/`](../adapters/claude-code/skills/daily-note-close/).

## Non-goals (v1)

- No live checkboxes with real effects beyond what's described (ticking a Project next-actions box only does something once Close daily note runs, not instantly).
- No Waiting-For write-back (closing an item always happens on the Person Hub, never here).
- No delegation-from-daily-note (assigning a task to a person/agent from within the daily note is not yet specified).
- No cross-day continuation of the same file (a new day is always a new file, carry-forward is copy-only).
- No metrics/AFK ratio (later Routine, Phase 6, same as Dashboard's non-goal).
