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

## Related

```

`area:` is the Area **slug**, not a human-readable name — this is what lets an Area agent filter its own Projects programmatically during a Planning session. `lead:` carries who's actually driving the work (Kelvin, or a named teammate) — there is no separate folder split for this; everyone's Project notes live flat under `projects/<slug>/`.

## How a Project note gets created or updated

No script. Whichever Adapter (or Kelvin directly) is creating or updating a Project note writes the file following this schema, then logs the change via the already-existing generic `log-action` skill (`action-log-schema.md`) — `action type` is `project-update` (or `project-create` for a new one), `actor` is whoever made the change, `input link` is the Project note's path.

## Non-goals (v0)

- No Charter, no persistent per-project agent identity — Projects are read, not directed.
- No automated next-action extraction — an Area agent reads the note in-session; nothing computes this today.
- No historical/completed-project migration mechanism — this Protocol covers active Projects only. Archived projects stay wherever they already are.
