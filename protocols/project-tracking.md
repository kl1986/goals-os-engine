# Protocol: Project tracking (v1)

Defines the shape of a Project note in `projects/` and the rule for keeping it current. Projects are lighter-weight than Areas: they're not agent-owned (no name/tone interview, no charter) — an Area agent only *reads* them during a Planning session (per `planning-session.md` and PRD §4.4) when deciding what tickets to create next. Unlike Areas, Projects need no onboarding-style materialise script; any Adapter creates or updates a Project note directly, following this schema.

A Project's open work no longer lives on the note itself: as of v1 (ADR-0017), it lives only as tickets under `tasks/projects/<slug>/`, per `docs/agents/issue-tracker.md`'s schema. The Project note's `## Backlog` is free text only — future phases and ideas not yet worth a ticket, not a task list.

## Schema

One folder per project: `projects/<slug>/<Project Name>.md`.

```yaml
---
type: project
status: Active | Simmering | Incubating | Complete
goal: <one-line outcome>
due-date: YYYY-MM-DD | blank
area: <a goals-os-brain Area slug — must match a folder under areas/>
lead: Kelvin | <agent or teammate name>
tags:
  - project
---

## Why this matters


## Backlog
<!-- Free-text notes on future phases/ideas — NOT a checkbox task list. Open work lives only as tickets under tasks/projects/<slug>/, never here. -->

## Notes & progress
<!-- Dated entries, oldest first. Starts empty on a new or migrated Project note — this is where an Adapter appends going forward. When an input advances this Project, it receives a one-line dated entry linking back to the source (backlink discipline). -->

## Related

```

`area:` is the Area **slug**, not a human-readable name — this is what lets an Area agent filter its own Projects programmatically during a Planning session. `lead:` carries who's actually driving the work (Kelvin, or a named teammate) — there is no separate folder split for this; everyone's Project notes live flat under `projects/<slug>/`.

## Sections dropped from v1, and why

v1's Project template also had `Agent Tasks` and `Files` sections; this schema deliberately drops both:

- **Agent Tasks** — v1's table addressed named sub-agent personas (alex/jamie/dave/grace) that don't exist in Goals OS's Capability-agent model (Researcher/Analyst/Writer/Reviewer/Coder, commissioned via `commission.md`, not persistent per-project directs). Any genuinely open work item from a pre-cutover Agent Tasks table becomes a ticket under `tasks/projects/<slug>/` instead (per ADR-0017 below — not a note section at all).
- **Files** — a Project's folder (`projects/<slug>/`) already holds whatever's attached to it directly; nothing indexes those files by name elsewhere in `goals-os-brain` (Areas and People don't have a Files section either), so a separate list would just duplicate what `ls` already shows.

`Notes & progress` **is kept** in the schema (unlike the two above) — a migrated Project's historical entries don't carry over (current-state-only, per ticket 04's resolution), but the section itself stays, empty, for whoever updates the note next. This mirrors `people-tracking.md`'s `Log` section: migration drops history, not the place to write new history.

## v0 → v1: `## Next action` dropped (ADR-0017)

v0 of this schema had a `## Next action` checkbox section between `Why this matters` and `Backlog`. It's dropped entirely in v1 — heading and prose both — now that tickets under `tasks/projects/<slug>/` are the single store for a Project's open work (`docs/agents/issue-tracker.md`, ADR-0015). Two stores for the same thing (a checkbox list here, and a ticket board) invited exactly the drift ADR-0017 closes: a Project note could say one thing was next while its tickets said another. `## Backlog` is redefined at the same time — it was never meant to be a second task list, but its old one-line comment ("Future phases, not yet scheduled") was easy to read as one; it's now explicit that it's free-text notes only, and that any of it worth acting on becomes a ticket, not a bullet promoted in place.

A one-time migration script (`scripts/migrate_next_actions.py`) moved every existing Project's `- [ ]` Next-action line into a `status: prioritised` ticket and deleted the section from the note — see that script for the mechanics; this Protocol only documents the resulting shape.

## How a Project note gets created or updated

No script. Whichever Adapter (or Kelvin directly) is creating or updating a Project note writes the file following this schema, then logs the change via the already-existing generic `log-action` skill (`action-log-schema.md`) — `action type` is `project-update` (or `project-create` for a new one), `input link` is the Project note's path. `actor` follows `action-log-schema.md`'s closed taxonomy: `EA` when no more specific Area/Capability agent is directing the change (the common case for a direct migration or ad hoc update), or the addressing Area agent's name when a Planning session is what triggered the update. Never a Protocol's own name — a Protocol isn't an agent and can't be the executor.

## Non-goals (v1)

- No Charter, no persistent per-project agent identity — Projects are read, not directed.
- No automated ticket creation from a Project note — an Area agent decides what tickets to create in-session (`planning-session.md`); nothing computes this today.
- No historical/completed-project migration mechanism — this Protocol covers active Projects only. Archived projects stay wherever they already are.
