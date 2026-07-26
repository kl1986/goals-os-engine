# Protocol: Routine manifest (v0)

The Engine's single source of truth for every Routine's **protocol binding, risk tier, and owner** (ADR-0007, PRD §8). **Timing is not here.** Per **ADR-0030** cadence left the Engine entirely: a Routine's cadence is declared as a **Schedule** in the Brain's `config/schedules.md` (schema: [`schedules.md`](./schedules.md)), the one surface where timing is edited. Risk tier stays Engine-owned because it drives autonomy policy. A Brain's `config/routine-state.md` only ever records *when a Routine last ran*.

## Manifest

| Routine | Protocol | Risk tier | Owner | Phase 2 status |
|---|---|---|---|---|
| Capture sweep | [`capture.md`](./capture.md) | internal & reversible | scripts | implemented (ticket 08) |
| Compile | [`wiki.md`](./wiki.md) | internal & reversible (`wiki-compile`) | Librarian | implemented (Phase 4 execution) |
| Graduation check | [`routine-graduation.md`](./routine-graduation.md) | internal & reversible | scripts | implemented (execution batch) |
| Triage | [`triage.md`](./triage.md) | classify-only, writes nothing but a Triage Plan (Principle 10) | EA | implemented (ticket 09) |
| Execute | [`execute.md`](./execute.md) | varies by action type — see `config/action-types.md` | EA → agents | implemented (ticket 10) |
| Dashboard | [`dashboard.md`](./dashboard.md) | internal & reversible (read/link-only, executes nothing) | EA | implemented (ticket 11) |
| Daily note | [`daily-note.md`](./daily-note.md) | internal & reversible | EA | implemented |
| Close daily note | [`daily-note.md`](./daily-note.md) | internal & reversible | EA | implemented |
| Planning session | [`planning-session.md`](./planning-session.md) | internal & reversible (area note + memory + Action Log only, conversational) | Area agents | implemented (ticket 16) |
| Ticket normalization | [`ticket-normalization.md`](./ticket-normalization.md) | internal & reversible | scripts | implemented (ticket 27) |
| Weekly Review | — | — | EA + Librarian + Coach | declared, not implemented (Phase 6) |
| Coaching session | — | — | Coach | declared, not implemented (Phase 6) |
| Goal review | — | — | Coach + Area agents | declared, not implemented (Phase 6) |
| Upgrade review | — | — | Librarian | declared, not implemented (Phase 7) |
| Architecture review | — | — | Librarian + user | declared, not implemented (Phase 7) |
| Version control | [`version-control.md`](./version-control.md) | internal & reversible | scripts | implemented (ticket 12) |
| Rule learning | [`rule-learning.md`](./rule-learning.md) | internal & reversible | EA | implemented (execution batch) |
| Metrics pulse | — | — | scripts | declared, not implemented (Phase 6) |

Every Routine above needs a row in the Brain's `config/schedules.md` to be due-checked at all. The Engine ships a starter table at [`examples/schedules.md`](./examples/schedules.md) — one row per Routine here, cadence only — which the Brain Template ships as its `config/schedules.md` so a fresh Brain boots with working due-checking (ADR-0030).

## Heartbeat-checkable vs event-triggered

The distinction survives ADR-0030 unchanged; it now derives from the **kind** of the Routine's Schedule rather than from a Cadence cell here:

- **heartbeat-checkable** — Schedule kind *fixed-interval*. Its Timing is either a clock time (`06:05`, `Mon-Fri 14:00`) or a bare cadence word (hourly/daily/weekly/fortnightly/monthly/quarterly). `scripts/heartbeat.py` computes whether it's overdue by comparing `config/routine-state.md`'s last-run timestamp against that interval.
- **event-triggered** — Schedule kind *poll*: "on new raw," "on approval," "on demand." These fire on their event, not a clock — realised, where automated at all, as a frequent check rather than a wall-clock time — and are **excluded from due-checking by design**. Heartbeat never flags them, overdue or otherwise.

`scripts/heartbeat.py` only evaluates a Routine at all if its Phase 2 status here starts with `implemented` *and* it has a *fixed-interval* Schedule in the Brain — a declared-but-unimplemented Routine (e.g. Weekly Review) is never flagged overdue even though its cadence is nominally fixed, because it doesn't exist yet to run.

## Session-start ordering

Heartbeat's due-check can flag several overdue Routines in one session; where a Routine's own Protocol specifies a required order relative to another, that ordering is documented here and reflected in the table's row order above, not enforced by `heartbeat.py` itself (still a pure reporter — see below). **Graduation check runs before Triage** — its row sits immediately above Triage's in the table for that reason: a type that graduates mid-Heartbeat can auto-execute matching high-confidence items of that type in the *same* session's Triage/Execute pass, rather than sitting idle for an entire extra session (`routine-graduation.md`). The starter Schedules table mirrors this row order for the same reason.

## Non-goals (v0)

- No auto-run of anything, regardless of risk tier or how overdue a Routine is — graduation-driven autonomy is Phase 5, and Graduation check itself is the first Routine to exercise it (`routine-graduation.md`); every other Routine here is still nudge-then-invoke. Heartbeat itself only ever reports; it never dispatches.
- Real scheduler binding is **no longer a non-goal** — it exists. The Scheduler Adapter (`scripts/sync_schedules.py`, [`schedules.md`](./schedules.md)) is ADR-0007's layer 2: it renders launchd Jobs from the Brain's Schedules. Heartbeat (layer 1) remains a manually invocable nudge checked at session start, and every Routine stays manually invocable (layer 3). What the adapter still does *not* do is run an unattended agent **session** — it fires a trigger; the session runner is a separate capability.
