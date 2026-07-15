# Protocol: Routine manifest (v0)

The Engine's single source of truth for every Routine's cadence and risk tier (ADR-0007, PRD §8). A Brain's `config/routine-state.md` only ever records *when a Routine last ran* — it never duplicates cadence or risk tier again; that duplication was a Phase 1 defect (`config/routine-state.md` originally hardcoded cadence per-Brain) fixed by this Protocol.

## Manifest

| Routine | Protocol | Cadence | Risk tier | Owner | Phase 2 status |
|---|---|---|---|---|---|
| Capture sweep | [`capture.md`](./capture.md) | continuous/hourly — event-triggered (fires per manual capture call; no automated puller exists yet, so the "hourly" cadence is aspirational) | internal & reversible | scripts | implemented (ticket 08) |
| Compile | [`wiki.md`](./wiki.md) | on new archived captures / daily — heartbeat-checkable | internal & reversible (`wiki-compile`) | Librarian | implemented (Phase 4 execution) |
| Graduation check | [`routine-graduation.md`](./routine-graduation.md) | daily — heartbeat-checkable | internal & reversible | scripts | implemented (execution batch) |
| Triage | [`triage.md`](./triage.md) | on new raw / daily — heartbeat-checkable (daily fallback) | classify-only, writes nothing but a Triage Plan (Principle 10) | EA | implemented (ticket 09) |
| Execute | [`execute.md`](./execute.md) | on approval — event-triggered | varies by action type — see `config/action-types.md` | EA → agents | implemented (ticket 10) |
| Dashboard | [`dashboard.md`](./dashboard.md) | morning — heartbeat-checkable (daily) | internal & reversible (read/link-only, executes nothing) | EA | implemented (ticket 11) |
| Daily note | [`daily-note.md`](./daily-note.md) | morning — heartbeat-checkable (daily) | internal & reversible | EA | implemented |
| Close daily note | [`daily-note.md`](./daily-note.md) | evening — heartbeat-checkable (daily) | internal & reversible | EA | implemented |
| Planning session | [`planning-session.md`](./planning-session.md) | weekly / on demand — heartbeat-checkable (weekly) | internal & reversible (area note + memory + Action Log only, conversational) | Area agents | implemented (ticket 16) |
| Weekly Review | — | weekly — heartbeat-checkable | — | EA + Librarian + Coach | declared, not implemented (Phase 6) |
| Coaching session | — | monthly — heartbeat-checkable | — | Coach | declared, not implemented (Phase 6) |
| Goal review | — | quarterly / on demand — heartbeat-checkable (quarterly) | — | Coach + Area agents | declared, not implemented (Phase 6) |
| Upgrade review | — | fortnightly — heartbeat-checkable | — | Librarian | declared, not implemented (Phase 7) |
| Architecture review | — | quarterly — heartbeat-checkable | — | Librarian + user | declared, not implemented (Phase 7) |
| Version control | [`version-control.md`](./version-control.md) | daily — heartbeat-checkable | internal & reversible | scripts | implemented (ticket 12) |
| Rule learning | [`rule-learning.md`](./rule-learning.md) | weekly — heartbeat-checkable | internal & reversible | EA | implemented (execution batch) |
| Metrics pulse | — | weekly — heartbeat-checkable | — | scripts | declared, not implemented (Phase 6) |

## Heartbeat-checkable vs event-triggered

A Routine's Cadence cell says explicitly which it is:

- **heartbeat-checkable** — a fixed interval (hourly/daily/weekly/fortnightly/monthly/quarterly). `scripts/heartbeat.py` can compute whether it's overdue by comparing `config/routine-state.md`'s last-run timestamp against that interval.
- **event-triggered** — "on new raw," "on approval," "on demand," or similar. These fire on their event, not a clock, and are **excluded from due-checking by design** — Heartbeat never flags them, overdue or otherwise.

`scripts/heartbeat.py` only evaluates a Routine at all if its Phase 2 status starts with `implemented` *and* its cadence is heartbeat-checkable — a declared-but-unimplemented Routine (e.g. Weekly Review) is never flagged overdue even though its cadence is nominally fixed, because it doesn't exist yet to run.

## Session-start ordering

Heartbeat's due-check can flag several overdue Routines in one session; where a Routine's own Protocol specifies a required order relative to another, that ordering is documented here and reflected in the table's row order above, not enforced by `heartbeat.py` itself (still a pure reporter — see below). **Graduation check runs before Triage** — its row sits immediately above Triage's in the table for that reason: a type that graduates mid-Heartbeat can auto-execute matching high-confidence items of that type in the *same* session's Triage/Execute pass, rather than sitting idle for an entire extra session (`routine-graduation.md`).

## Non-goals (v0)

- No real scheduler (cron/launchd) binding — Heartbeat is a manually invocable nudge, checked at session start; a real scheduler binding is a later Adapter-layer addition (ADR-0007 layer 2).
- No auto-run of anything, regardless of risk tier or how overdue a Routine is — graduation-driven autonomy is Phase 5, and Graduation check itself is the first Routine to exercise it (`routine-graduation.md`); every other Routine here is still nudge-then-invoke. Heartbeat itself only ever reports; it never dispatches.
