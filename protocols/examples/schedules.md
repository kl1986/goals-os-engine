---
type: config
config: schedules
---

# Schedules

<!--
The sole source of truth for timing in this Brain (ADR-0030). Read by the
Engine's scripts/heartbeat.py (cadence for due-checking) and by
scripts/sync_schedules.py (the Scheduler Adapter, which renders one Managed
launchd .plist per enabled row with a Command). Schema: the Engine's
protocols/schedules.md — read that before editing.

Columns
  Label    unique identifier for the row. For a row that renders a Job it is
           used verbatim as the launchd Label and plist filename, so use
           reverse-DNS form there (e.g. com.you.goals-os-triage). Cadence-only
           rows never reach launchd, so a bare slug is fine.
  Routine  the Routine this Schedule times, or — for a standalone job
  Command  the command to run, backtick-quoted, shell-quoting honoured; — for none
  Kind     fixed-interval (fires on a clock) | poll (an event-trigger, checked often)
  Timing   fixed-interval: `HH:MM`, `<days> HH:MM` (e.g. `Mon-Fri 14:00`, `Sun 20:07`),
           or a bare cadence word (hourly/daily/weekly/fortnightly/monthly/quarterly)
           which declares cadence only and renders no job.
           poll: an interval — `900s`, `15m`, `1h`.
  Enabled  yes | no — no switches the Schedule off for launchd *and* Heartbeat
  Log      one path (both streams) or `out ; err`
  Env      `KEY=value; KEY2=value2`
  Options  `cwd=<dir>; run-at-load=true|false`

This starter table declares cadence only — every Command is —, so a freshly
cloned Brain gets working Heartbeat due-checking and creates no launchd jobs
until you deliberately add a Command. fixed-interval rows are
heartbeat-checkable; poll rows are event-triggered and excluded from
due-checking by design.
-->

| Label | Routine | Command | Kind | Timing | Enabled | Log | Env | Options |
|---|---|---|---|---|---|---|---|---|
| capture-sweep | Capture sweep | — | poll | — | yes | — | — | — |
| compile | Compile | — | fixed-interval | daily | yes | — | — | — |
| graduation-check | Graduation check | — | fixed-interval | daily | yes | — | — | — |
| triage | Triage | — | fixed-interval | daily | yes | — | — | — |
| execute | Execute | — | poll | — | yes | — | — | — |
| dashboard | Dashboard | — | fixed-interval | daily | yes | — | — | — |
| daily-note-generate | Daily note | — | fixed-interval | daily | yes | — | — | — |
| daily-note-close | Close daily note | — | fixed-interval | daily | yes | — | — | — |
| planning-session | Planning session | — | fixed-interval | weekly | yes | — | — | — |
| ticket-normalization | Ticket normalization | — | fixed-interval | daily | yes | — | — | — |
| weekly-review | Weekly Review | — | fixed-interval | weekly | yes | — | — | — |
| coaching-session | Coaching session | — | fixed-interval | monthly | yes | — | — | — |
| goal-review | Goal review | — | fixed-interval | quarterly | yes | — | — | — |
| upgrade-review | Upgrade review | — | fixed-interval | fortnightly | yes | — | — | — |
| architecture-review | Architecture review | — | fixed-interval | quarterly | yes | — | — | — |
| version-control | Version control | — | fixed-interval | daily | yes | — | — | — |
| rule-learning | Rule learning | — | fixed-interval | weekly | yes | — | — | — |
| metrics-pulse | Metrics pulse | — | fixed-interval | weekly | yes | — | — | — |

## Notes

- **Row order mirrors the Engine's `protocols/routines.md` manifest** — in
  particular Graduation check sits above Triage, the session-start ordering
  that manifest documents.
- A Routine declared here but not `implemented` in the manifest (Weekly
  Review, Coaching session, …) is still never flagged overdue: Heartbeat
  requires both an implemented manifest row *and* a heartbeat-checkable
  Schedule.
- Adding a `Command` (and a clock time, or a poll interval) turns a row into
  a real Job. Run the Engine's `scripts/sync_schedules.py --brain <brain>
  --dry-run` first, always.
