# Goals OS Engine

The distributable core of **Goals OS** — a protocol-first, multi-agent personal operating system whose purpose is getting the user to their goals with an increasing share of the work done away from keyboard.

The Engine contains **zero user data**. It ships protocols, schemas, core routines, and runtime adapters — the part of the system every user shares and every upgrade touches. Nothing personal ever lives here; that all lives in a user's private **Brain** (cloned from a [Brain Template](https://github.com/kl1986/goals-os-brain-template)), so upgrading the Engine never clobbers a user's learnings.

## Language

See [`CONTEXT.md`](./CONTEXT.md) for the full glossary (Engine, Library, Brain, Protocol, Adapter, Action Log, and the rest of the system's vocabulary).

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
