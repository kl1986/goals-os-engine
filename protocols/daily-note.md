# Protocol: Daily note (v4)

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

## Daily priorities
![[tasks/all-tickets.base#Daily priorities]]

## Project next actions

## Waiting for

## Proposed from meetings

## Notes
```

v3 (meeting-processing) adds `## Proposed from meetings`. It gets its own heading rather than folding into an existing section: `## Waiting for` is a wholesale-replaced mirror and `## Today's tasks` carries hand-typed content, while this section is additive-only — three different edit semantics in one heading would be a trap. A separate heading also keeps the source obvious when an item needs chasing back to its meeting note.

v4 adds `## Daily priorities` immediately after `## Today's tasks`. It is a static named-view embed of the Brain's shared `tasks/all-tickets.base#Daily priorities` Base Board view, not a second task store: dragging a card writes its `status` directly to the source ticket's frontmatter. Generation ensures the one fixed embed is present on new and pre-existing daily notes without duplicating it or touching any other user-authored content.

## Daily note Routine (Generation & refresh)

The generation Routine (risk tier internal & reversible, owner EA; Schedule *fixed-interval*, a morning clock time — heartbeat-checkable daily — in the Brain's `config/schedules.md`) uses `scripts/daily_note.py`'s `generate_daily_note` plus an Adapter skill.

- Each new calendar day always gets a brand-new file. There is no cross-day continuation of the same file.
- Re-invoking generation within the same day is **additive only**. It only ever adds rows for anything not already present (new project next-actions, new triaged captures filed via the `today` destination, new Waiting For items, new proposed items from meetings). It never touches, reorders, or removes an existing line. This is different from `dashboard.md`, which fully overwrites every run.
- A note generated before a section existed has no such heading, and appending into a missing heading is a silent no-op. Generation therefore **inserts** a missing `## Daily priorities` heading (immediately before `## Project next actions`) and `## Proposed from meetings` heading (immediately before `## Notes`) rather than skipping either section for the day. Inserting a heading is still additive-only: it adds lines and touches, reorders and removes none.
- **Carry-forward:** Generation scans the most recently archived note (`archive/daily-notes/`, picking the lexicographically-latest filename) for any still-unchecked `## Today's tasks` line, and copies it verbatim into the new day's `## Today's tasks`. This is origin-blind: a manually-typed task and a capture-derived task carry forward identically. This is the **only** section needing carry-forward. `## Project next actions` and `## Waiting for` are live mirrors of an external source (project notes, person hubs), so an unresolved item naturally persists at the source without carry-forward logic here.

On completion, it bumps its own "Daily note" row in `config/routine-state.md` (`heartbeat.bump`), matching every other Routine.

## Project next-actions sourcing (ADR-0018)

Computed as part of the same generation scan (read-only, nothing changes at the source at generation time).

- **Source:** ticket files under `tasks/projects/*/*.md` and `tasks/areas/*/*.md` (`docs/agents/issue-tracker.md`'s schema, ADR-0015) — no longer a Project note's own `## Next action` section, which no longer exists (`project-tracking.md` v1, ADR-0017).
- **Filter:** any ticket with active/actionable frontmatter `status` (`status: prioritised`, `status: in-progress`, or `status: awaiting-review` — evaluated via denylist excluding `backlog`, `done`, and `deprioritized` so future active statuses fail safe, ADR-0025). **No per-Project/Area cap** — every matching ticket renders its own row, not just the first.
- **Project gating:** a ticket under `tasks/projects/<slug>/` only surfaces if the parent Project note (`projects/<slug>/<Project Name>.md`) has `status: Active` — the ticket's own folder name (`<slug>`) is how the parent Project note is resolved. A ticket whose parent Project isn't Active is silently skipped (not an error), same posture as v1's project-status filter.
- **Area gating:** a ticket under `tasks/areas/<slug>/` surfaces unconditionally — Areas have no lifecycle status field to gate on.
- **Rendered:** `- [ ] {ticket title} — [[<ticket file>]]` for `prioritised` and `in-progress` tickets; `- [ ] [Awaiting review] {ticket title} — [[<ticket file>]]` for `awaiting-review` tickets (distinctly rendering items that need a decision rather than effort), where `{ticket title}` is the ticket note's H1 (its first `# ` line) and `<ticket file>` is the ticket's filename stem — the wikilink resolves directly to the ticket, not to the parent Project/Area note.

## Write-back mechanism

`## Project next actions` is the **one section** whose ticked items imply an action to take elsewhere (marking the ticket done at its source). Manual entries, triaged captures, and Waiting For items never carry any such reference.

Unlike v1, there is **no `<!-- daily-note-src -->` HTML comment** — the `[[ticket file]]` wikilink itself is the stable reference back to the source (a ticket has a permanent identity — its filename — that a Next-action line's free text never had), so nothing else needs to travel alongside the visible line.

- **What "written back" means:** Run by the "Close daily note" Routine (evening) over every ticked `## Project next actions` line. It parses the `[[ticket file]]` wikilink out of the line, locates that ticket file under `tasks/**/`, and writes `status: done` plus `resolved: <today, ISO YYYY-MM-DD>` directly into the ticket's own frontmatter. No second store, nothing to reconcile against a Notes & progress section.
- **Conflict handling:** if the linked ticket file can't be found under `tasks/**/` (e.g. renamed, moved, or deleted since this morning's generation), it does **not** silently drop it. The daily-note checkbox stays ticked as-is, but an Action Log entry is written recording the miss (outcome `"Row not found at source, no write-back performed"`). This is the same "report, don't swallow" posture `execute.md` uses for unfileable Triage rows, and v1's own miss-path before it.

## Close daily note Routine

A thin, mechanical bookend Routine (risk tier internal & reversible, owner EA; Schedule *fixed-interval*, an evening clock time — heartbeat-checkable daily — in the Brain's `config/schedules.md`). Uses `scripts/daily_note.py`'s `close_daily_note` plus an Adapter skill.

What it does, in order, nothing more:
1. Runs the write-back reconciliation above over every ticked `## Project next actions` line (parses the `[[ticket file]]` wikilink, locates the ticket under `tasks/**/`, writes `status: done` + `resolved:` to its frontmatter, or logs the miss per-line — no separate summary log entry on top of the per-line ones).
2. Moves `<brain>/YYYY-MM-DD.md` to `<brain>/archive/daily-notes/YYYY-MM-DD.md`.

It bumps its own "Close daily note" row in `config/routine-state.md`. Note explicitly: carry-forward (scanning yesterday's archive for unchecked Today's-tasks lines) is **NOT** this routine's job — that is the *next morning's* generation step reading backward. Close-daily-note is a thin, mechanical bookend with no new judgement calls.

## Waiting For section

Computed by the same Daily-note generation skill. One more scan of `people/*.md` (the same source `dashboard.py`'s `_open_waiting_for()` already scans, per `protocols/people-tracking.md`). 

Read-only, no write-back, and no `daily-note-src` comment ever. `people-tracking.md`'s existing rule ("a hub is the only place a delegation ever gets logged — never a second file, never the Dashboard") applies here too; the daily note is exactly such a second surface.

Renders as plain bullets, NOT checkboxes (a checkbox would be a false affordance — ticking it would silently do nothing): `- {item text} — [[Person Hub]]`. Ordered by hub filename, with items for the same person grouped together (same shape the Dashboard already uses).

## Proposed from meetings section (v3)

Computed by the same generation scan, reusing `dashboard._open_proposed_items()` — the same source `dashboard.py` scans, exactly as `## Waiting for` reuses `_open_waiting_for()`. The `meetings` plugin writes items it can't safely auto-file into a meeting note's `## Proposed` section because confirm-first is impossible in a headless hook; without a surface they'd be written and then missed.

- **Source:** every unticked `- [ ]` line under a `## Proposed` heading in `meetings/*.md`, ordered by note filename. Struck-through (`~~`) lines are skipped; so are `README.md` and `_`-prefixed files.
- **Rendered:** `- {item text} — [[meeting note]]` — plain bullets, NOT checkboxes, for the identical reason Waiting For uses none: approval happens in the meeting note, so a tick here would be a false affordance.
- **Additive-only**, unlike Waiting For's wholesale replace. Rows are added for items not already present and existing lines are never touched or reordered. Dedupe is on the **exact rendered line**, not the `[[note]]` wikilink — several items share one meeting note, so deduping on the link would collapse them and suppress every item after the first.
- **Read-only, no write-back.** The scan never ticks, edits, or moves a meeting note, and nothing here ever writes back to one. The same rule `people-tracking.md` states for delegations applies: the note is the only place an item is ever resolved, and the daily note is exactly such a second surface.

## Triage / Execute destination

A new `today` destination literal (parallel to the existing `discard` literal) produces action type `file-capture-today`. Full mechanics are documented in [`execute.md`](./execute.md); do not duplicate them here.

## Adapter binding

See [`adapters/claude-code/skills/daily-note-generate/`](../adapters/claude-code/skills/daily-note-generate/) and [`adapters/claude-code/skills/daily-note-close/`](../adapters/claude-code/skills/daily-note-close/).

## Non-goals (v3)

- No live checkboxes with real effects beyond what's described (ticking a Project next-actions box only does something once Close daily note runs, not instantly).
- No Waiting-For write-back (closing an item always happens on the Person Hub, never here).
- No proposed-item write-back and no auto-action on one (approving, filing, or dismissing a proposed item always happens in its own meeting note, never here). `## Project next actions` remains the **one** section whose ticked items imply an action elsewhere.
- No delegation-from-daily-note (assigning a task to a person/agent from within the daily note is not yet specified).
- No cross-day continuation of the same file (a new day is always a new file, carry-forward is copy-only).
- No metrics/AFK ratio (later Routine, Phase 6, same as Dashboard's non-goal).
- No rename of the `## Project next actions` heading, despite it now also carrying Area tickets — flagged as a candidate follow-up only (ADR-0018), not actioned here.
