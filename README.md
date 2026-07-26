# Goals OS Engine

The distributable core of **Goals OS** — a protocol-first, multi-agent personal operating system whose purpose is getting the user to their goals with an increasing share of the work done away from keyboard.

The Engine contains **zero user data**. It ships protocols, schemas, core routines, and runtime adapters — the part of the system every user shares and every upgrade touches. Nothing personal ever lives here; that all lives in a user's private **Brain** (cloned from a [Brain Template](https://github.com/kl1986/goals-os-brain-template)), so upgrading the Engine never clobbers a user's learnings.

## Language

See [`CONTEXT.md`](./CONTEXT.md) for the full glossary (Engine, Library, Brain, Protocol, Adapter, Action Log, and the rest of the system's vocabulary).

## Start here

Read the [user guide](./docs/user-guide.md) for the daily Capture → Triage →
Execute → Compile lifecycle, the reference Brain's drop zones, Heartbeat, and
the boundary between the Brain and the Engine. Architecture-level decisions
are recorded in the [ADRs](./docs/adr/).

## Protocols

Markdown-defined, runtime-independent behaviour specs — what the Engine ships; Adapters make them executable. See [`protocols/`](./protocols/):

| Protocol | Defines |
|-----|----------|
| [`action-log-schema.md`](./protocols/action-log-schema.md) | The Action Log entry schema (v0) — the fields every agent action appends to the Brain's `log/`, per ADR-0005/0006. |
| [`onboarding.md`](./protocols/onboarding.md) | Turns a blank Brain clone into a working, personalised Brain (v0) — interview + idempotent materialisation of `config/` and one Area at a time, per ADR-0004. |
| [`routines.md`](./protocols/routines.md) | The Routine manifest (v0) — protocol binding, risk tier, owner and Phase 2 status per Routine. Timing is **not** here; see below. |
| [`schedules.md`](./protocols/schedules.md) | The Schedules schema (v0) — the Brain's `config/schedules.md` is the sole source of truth for timing (ADR-0030), read by Heartbeat for cadence and by the Scheduler Adapter to generate launchd Jobs. |

## Adapters

Runtime bindings for the Protocols above — see [`adapters/`](./adapters/). Claude Code is the reference Adapter (ADR-0002):

| Adapter | Status |
|---|---|
| [`claude-code/`](./adapters/claude-code/) | First live Protocol execution proven — `log-action` skill appends schema-valid Action Log entries to a cloned Brain. |

**Scheduler Adapter** — `scripts/sync_schedules.py` is ADR-0007's layer 2: it renders one Managed launchd `.plist` per enabled row of a Brain's `config/schedules.md` and reconciles `~/Library/LaunchAgents/` to that table, idempotently. It never touches a hand-written (Unmanaged) plist. Dry-run first:

```
python3 scripts/sync_schedules.py --brain /path/to/brain --dry-run
```

It schedules a *trigger* — it is not a session runner, so a consumer wanting an unattended agent session supplies that runner itself as the row's Command.

## Decisions

See [`docs/adr/`](./docs/adr/) for the architecture decision records this repo was scaffolded against:

| ADR | Decision |
|-----|----------|
| 0001 | Clean-slate v2 |
| 0002 | Protocol-first runtime |
| 0003 | Three-repo topology (Engine / Library / Brain) |
| 0004 | Plugin + template distribution |
| 0005 | Unified Action Log |
| 0006 | Risk-tiered graduation |
| 0007 | Declarative routines with due-checking |
| 0008 | Two-lane self-improvement |
| 0009 | Voice in core, dialogue as plugin |
| 0010 | Pure-derivation Wiki |
| 0011 | Capture `source` encodes routing intent, not input modality |
| 0012 | Tickets live in the Brain, organised per Project/Area |
| 0013 | Global Kanban board with synchronised ticket frontmatter |
| 0014 | Ticket identity uses slug-scoped local numbering |
| 0015 | Ticket schema has no Epic and descriptive goal linkage |
| 0016 | Base Board supersedes the board file and sync script |
| 0017 | Tickets are a Project's sole store of open work |
| 0018 | Daily notes source tickets and include Areas |
| 0019 | Ticket normalisation and an unfiled quarantine |
| 0020 | Ticket filenames use descriptions rather than IDs |
| 0021 | Build ships as a Library plugin and Charters gain ownership |
| 0022 | A Project declares its repos; a Ticket does not |
| 0023 | A Build gates at push, not commit |
| 0024 | Build vendors its engineering skills |
| 0025 | `awaiting-review` is a sixth ticket status |
| 0026 | Build adds a Surveyor and Reviewer execution rights |
| 0027 | Build SCM conventions |
| 0028 | Meetings are a fourth content layer structured by an Execute hook |
| 0029 | Durable, immutable-source Wiki feedback |
| 0030 | Cadence ownership moves from the Engine manifest to the Brain's `config/schedules.md` (lives in the Brain's `docs/adr/`) |

## Status

Early scaffold — Phase 1 of the roadmap. Not yet installable.

## Licence

MIT — see [LICENSE](./LICENSE).
