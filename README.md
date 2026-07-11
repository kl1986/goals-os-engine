# Goals OS Engine

The distributable core of **Goals OS** — a protocol-first, multi-agent personal operating system whose purpose is getting the user to their goals with an increasing share of the work done away from keyboard.

The Engine contains **zero user data**. It ships protocols, schemas, core routines, and runtime adapters — the part of the system every user shares and every upgrade touches. Nothing personal ever lives here; that all lives in a user's private **Brain** (cloned from a [Brain Template](https://github.com/kl1986/goals-os-brain-template)), so upgrading the Engine never clobbers a user's learnings.

## Language

See [`CONTEXT.md`](./CONTEXT.md) for the full glossary (Engine, Library, Brain, Protocol, Adapter, Action Log, and the rest of the system's vocabulary).

## Protocols

Markdown-defined, runtime-independent behaviour specs — what the Engine ships; Adapters make them executable. See [`protocols/`](./protocols/):

| Protocol | Defines |
|-----|----------|
| [`action-log-schema.md`](./protocols/action-log-schema.md) | The Action Log entry schema (v0) — the fields every agent action appends to the Brain's `log/`, per ADR-0005/0006. |
| [`onboarding.md`](./protocols/onboarding.md) | Turns a blank Brain clone into a working, personalised Brain (v0) — interview + idempotent materialisation of `config/` and one Area at a time, per ADR-0004. |

## Adapters

Runtime bindings for the Protocols above — see [`adapters/`](./adapters/). Claude Code is the reference Adapter (ADR-0002):

| Adapter | Status |
|---|---|
| [`claude-code/`](./adapters/claude-code/) | First live Protocol execution proven — `log-action` skill appends schema-valid Action Log entries to a cloned Brain. |

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

## Status

Early scaffold — Phase 1 of the roadmap. Not yet installable.

## Licence

MIT — see [LICENSE](./LICENSE).
