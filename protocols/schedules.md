# Protocol: Schedules (v0)

The Brain's `config/schedules.md` is the **sole source of truth for timing** in Goals OS (ADR-0030). One row is a **Schedule**. Two things read it and nothing else parses it:

| Layer | Reader | Uses |
|---|---|---|
| 1 — Heartbeat | `scripts/heartbeat.py` | cadence, to due-check Routines at session start |
| 2 — Scheduler Adapter | `scripts/sync_schedules.py` | renders one Managed launchd `.plist` per enabled row that names a Command |

Both go through `scripts/schedules.py`, which owns the parse and the validation.

## Vocabulary

- **Schedule** — one row: *when* a Routine or a standalone script runs, both trigger and timing. Has a **kind**: *fixed-interval* (fires on a clock) or *poll* (an event-trigger — "on new raw" — realised as a frequent check).
- **Job** — the concrete `.plist` that realises a Schedule. Either realises a Routine's Schedule, or is a standalone scheduled script with no Routine (capture pullers, `vault-backup`). Both are first-class rows.
- **Managed Job** — generated and owned by `sync_schedules.py`; carries the `GoalsOSManaged` marker key. **Unmanaged Job** — any hand-written plist. The adapter **never touches an Unmanaged plist**, and refuses loudly if a row's Label collides with one.
- **Scheduler Adapter** — `sync_schedules.py` plus this schema: ADR-0007's layer 2.

Cadence is **retired from the Engine** — it is not a column in `protocols/routines.md` any more; a Schedule's kind and Timing are where cadence lives.

## Schema

A single Markdown table, found by its `Label` header cell (so the file may carry prose and header comments above it). Nine columns, all required, `—` for "none":

| Column | Meaning |
|---|---|
| **Label** | Unique row identifier. For a row that renders a Job it is used **verbatim** as the launchd `Label` and as the plist filename (`<Label>.plist`), so use reverse-DNS form there — `com.you.goals-os-triage`. Must match `[A-Za-z0-9][A-Za-z0-9._-]*`. |
| **Routine** | The Routine (by its `protocols/routines.md` name) whose cadence this row declares, or `—` for a standalone Job. |
| **Command** | The command to run, backtick-quoted; shell quoting is honoured (`shlex`), so paths with spaces work. Becomes `ProgramArguments`. `—` means the row declares cadence only and renders **no Job**. Leading `~` in any argument is expanded. |
| **Kind** | `fixed-interval` or `poll`. |
| **Timing** | *fixed-interval*: a clock time — `HH:MM`, or `<days> HH:MM` where days is `Sun`…`Sat`, a range (`Mon-Fri`) or a list (`Mon,Wed,Fri`) — **or** a bare cadence word (`hourly`, `daily`, `weekly`, `fortnightly`, `monthly`, `quarterly`), which declares cadence only and renders no Job. *poll*: an interval, `900s` / `15m` / `1h`. |
| **Enabled** | `yes` / `no`. `no` switches the Schedule off for launchd **and** for Heartbeat. |
| **Log** | One path (both streams share it) or `out ; err`. `~` expanded. |
| **Env** | `KEY=value; KEY2=value2` → `EnvironmentVariables`. Values with `~` expanded. launchd gives a job almost no environment, so `PATH` and `HOME` are usually needed. |
| **Options** | Process context that isn't timing: `cwd=<dir>` → `WorkingDirectory`, `run-at-load=true|false` → `RunAtLoad`. No other keys are accepted. |

Because `|` delimits cells, a Command containing a literal pipe cannot be expressed — put it in a wrapper script and schedule that.

### Rendering

- *fixed-interval* → `StartCalendarInterval`. One clock entry renders a dict; a multi-day spec renders an array of dicts, one per weekday (launchd `Weekday`: 0 = Sunday).
- *poll* → `StartInterval` in seconds.
- Cadence derived for Heartbeat: no day spec → daily; N weekdays → 7/N days; a bare cadence word → that word. *poll* rows are event-triggered and carry no cadence.

## Reconcile

`sync_schedules.py --brain <brain> [--dry-run] [--launch-agents-dir DIR] [--no-load] [--allow-removals]` converges the LaunchAgents directory to the table, and is safe to re-run:

1. Parse and validate the **whole** table. One malformed row aborts the run with every problem listed, before any filesystem write. A file with no readable table at all — prose only, zero bytes, a renamed or re-cased `Label` column — is an error, never an empty schedule.
2. Refuse if any desired Label already exists as a plist without the `GoalsOSManaged` marker.
3. Plan: create / update / unchanged / remove. "Unchanged" compares the *semantic* plist keys, so the generated-at comment never causes a needless rewrite.
4. Refuse a **removal-only** plan — one that removes Managed Jobs and creates none. Deleting a row on purpose is still possible with `--allow-removals`.
5. Apply: `launchctl bootout` then `bootstrap` each written Job (falling back to legacy `unload`/`load`); Managed plists no longer in the table are booted out and deleted.

`--dry-run` prints the plan plus a unified diff per changed file and writes nothing. Run it first, always.

## Out of scope

- **What a job does.** This schema only says when.
- **Running an unattended agent session.** The adapter fires a *trigger*. If a consumer needs an unattended Claude session it must supply the runner itself as the row's Command (e.g. `claude -p /some-command`) — the adapter does not invent a session runner, and any consumer that needs one (e.g. unattended Triage Pass B) still depends on that separate capability.
