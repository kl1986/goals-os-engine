# Protocol: Project tracking (v0)

Defines the shape of a Project note in `projects/` and the rule for keeping it current. Projects are lighter-weight than Areas: they're not agent-owned (no name/tone interview, no charter) — an Area agent only *reads* them to surface next actions during a Planning session (per `planning-session.md` and PRD §4.4). Unlike Areas, Projects need no onboarding-style materialise script; any Adapter creates or updates a Project note directly, following this schema.

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


## Next action
<!-- Open items only. -->
- [ ]

## Backlog
<!-- Future phases, not yet scheduled. -->

## Notes & progress
<!-- Dated entries, oldest first. Starts empty on a new or migrated Project note — this is where an Adapter appends going forward. -->

## Related

```

`area:` is the Area **slug**, not a human-readable name — this is what lets an Area agent filter its own Projects programmatically during a Planning session. `lead:` carries who's actually driving the work (Kelvin, or a named teammate) — there is no separate folder split for this; everyone's Project notes live flat under `projects/<slug>/`.

## Sections dropped from v1, and why

v1's Project template also had `Agent Tasks` and `Files` sections; this schema deliberately drops both:

- **Agent Tasks** — v1's table addressed named sub-agent personas (alex/jamie/dave/grace) that don't exist in Goals OS's Capability-agent model (Researcher/Analyst/Writer/Reviewer/Coder, commissioned via `commission.md`, not persistent per-project directs). Any genuinely open work item from a v1 Agent Tasks table folds into `Next action` as a plain item instead.
- **Files** — a Project's folder (`projects/<slug>/`) already holds whatever's attached to it directly; nothing indexes those files by name elsewhere in `goals-os-brain` (Areas and People don't have a Files section either), so a separate list would just duplicate what `ls` already shows.

`Notes & progress` **is kept** in the schema (unlike the two above) — a migrated Project's historical entries don't carry over (current-state-only, per ticket 04's resolution), but the section itself stays, empty, for whoever updates the note next. This mirrors `people-tracking.md`'s `Log` section: migration drops history, not the place to write new history.

## How a Project note gets created or updated

No script. Whichever Adapter (or Kelvin directly) is creating or updating a Project note writes the file following this schema, then logs the change via the already-existing generic `log-action` skill (`action-log-schema.md`) — `action type` is `project-update` (or `project-create` for a new one), `input link` is the Project note's path. `actor` follows `action-log-schema.md`'s closed taxonomy: `EA` when no more specific Area/Capability agent is directing the change (the common case for a direct migration or ad hoc update), or the addressing Area agent's name when a Planning session is what triggered the update. Never a Protocol's own name — a Protocol isn't an agent and can't be the executor.

## Non-goals (v0)

- No Charter, no persistent per-project agent identity — Projects are read, not directed.
- No automated next-action extraction — an Area agent reads the note in-session; nothing computes this today.
- No historical/completed-project migration mechanism — this Protocol covers active Projects only. Archived projects stay wherever they already are.
