# Protocol: People tracking (v0)

Defines the shape of a Person Hub note in `people/` and the rule for keeping it current. Like Projects, Person Hubs are lighter-weight than Areas: not agent-owned, no charter, no persistent identity — an Adapter creates or updates a hub directly, following this schema. Unlike Projects, a hub isn't read during a Planning session for next actions; it's read ad hoc, whenever the user is about to talk to or delegate to that person.

## Schema

One note per person: `people/<Full Name>.md`.

```yaml
---
type: person
name: <Full Name>
aliases: []
email:
role: <their role/title>
areas: []
cadence:
tags:
  - person
created: YYYY-MM-DD
---

## 🗣️ To Discuss
<!-- Open agenda items to raise next time you speak to this person. -->

## ⏳ Waiting For
<!-- Things delegated to this person, awaiting their reply or deliverable. #waiting-for items. -->

## 🧠 Context
<!-- Durable relationship facts: role, reporting line, preferences, what matters to them. -->

## 🗓️ Log
<!-- Dated entries, oldest first. -->
- YYYY-MM-DD — created
```

`areas:` is a **list** of goals-os-brain Area slugs (unlike Projects' singular `area:`) — a person can legitimately span more than one Area (e.g. a contact touching both `work` and `ho-lee-fook`). Each value must match a folder under `areas/`.

## `#waiting-for` and the read-only roll-up guarantee

A hub is the **only** place a delegation to that person gets logged — never a second file, never the Dashboard. `protocols/dashboard.md` (v0.1) reads `people/*.md` and surfaces every open `#waiting-for` item as a read-only, pure-derivation section, the same way it already surfaces pending Triage Plans. Closing an item still happens on the hub (mark it done / strike it through), not on the Dashboard.

## Alias registry

`people/_aliases.md` is a flat lookup table (name-variant → canonical hub), migrated from v1 as data. No Adapter resolves names against it yet — capture.md/triage.md don't do name resolution in v0 — but it's kept current (add a row when a hub is created) so it's ready whenever that lands.

## How a Person Hub gets created or updated

No script. Whichever Adapter (or Kelvin directly) is creating or updating a hub writes the file following this schema, then logs the change via the existing generic `log-action` skill (`action-log-schema.md`) — `action type` is `person-create` (or `person-update`), `actor` is whoever made the change, `input link` is the hub's path.

## Non-goals (v0)

- No Charter, no persistent per-person agent identity.
- No To Discuss roll-up — only Waiting For is surfaced on the Dashboard (see `dashboard.md`'s non-goals).
- No name-resolution mechanism consuming `_aliases.md` yet — that's a future `capture.md`/`triage.md` concern.
- No historical migration mechanism — this Protocol covers current-state hubs only; whatever a person's v1 Log held stays in v1.
