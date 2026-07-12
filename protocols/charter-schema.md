# Protocol: Charter schema (v0)

Defines the generic markdown format every agent Charter uses — System, Area, and Capability alike (CONTEXT.md's three agent kinds, PRD §5) — so Phase 3's charters (EA, Area CEO, Researcher, Analyst, Writer, Reviewer, Coder) share one schema instead of drifting into five ad hoc shapes. Mirrors how `action-log-schema.md` (ADR-0005) fixed one entry shape before anything wrote to it.

A Charter is the markdown spec that defines an agent's role, tool scope, and delegation relationships (CONTEXT.md). Every agent the system addresses or commissions has exactly one.

## Two charter shapes

- **Generic charter** (`scope: generic`) — Engine-owned, one per role, ships as-is in `protocols/charters/`. Defines the role once for every Brain: what an EA is, what an Area CEO is, what a Researcher is.
- **Instance** (`scope: instance`) — Brain-owned, one per named, concrete agent, materialised from a generic charter. Currently only **Area agents** have instances — e.g. `Will`, materialised from the Area CEO generic charter for the Work area (`areas/work/Work.md`'s `agent: Will` frontmatter, onboarding ticket 05; the remaining areas get their instances from the migration tickets, 19–23). System agents (EA, Librarian, Coach) are Engine singletons addressed directly from their generic charter; Capability agents are ephemeral and commissioned directly from theirs. Neither has a separate per-Brain instance file today — if that changes, this Protocol is the place to extend.

## Frontmatter fields

```markdown
---
type: charter
charter-kind: area
scope: instance
extends: protocols/charters/area-ceo.md
agent: Will
directs: Capability agents
commissioned-by: —
tool-scope: see body
memory: areas/work/_memory.md
---
```

| Field | Meaning |
|---|---|
| `charter-kind` | `system` \| `area` \| `capability` — which of CONTEXT.md's three agent kinds this charter defines. Fixed per charter; never changes between generic and instance. |
| `scope` | `generic` or `instance` (see above). |
| `extends` | For `scope: instance` only — relative path to the generic charter this instance was materialised from. Absent (`—`) for `scope: generic`. |
| `agent` | The agent's name. For `scope: generic`, the role name (`EA`, `Area CEO`, `Researcher`). For `scope: instance`, the Brain-chosen persona name (`Will`). |
| `directs` | What this agent commissions or delegates to, if anything. System and Area agents direct Capability agents; Capability agents direct nothing — they're the leaf of the delegation tree (CONTEXT.md's Capability agent entry). `none` for Capability charters. |
| `commissioned-by` | Capability charters only — who may commission this agent (`System agents`, `Area agents`, or `both`). `—` for System/Area charters: those are addressed directly by the user, never commissioned by another agent. |
| `tool-scope` | What this agent may read, write, or execute — the enforcement boundary a commissioning mechanism checks against (ticket 17). Narrowest and most load-bearing for Capability agents; for System/Area agents it bounds their own direct actions, since they direct rather than execute (PRD §5). `see body` when the scope needs more than a one-line table cell — spell it out in the charter's body instead. |
| `memory` | Where this agent's persistent continuity lives, or `none`. Area agents: `areas/<slug>/_memory.md` (onboarding ticket 05). Capability agents: always `none` — ephemeral per commission, nothing persists between one (CONTEXT.md). System agents: Engine-defined per charter, out of scope for this Protocol to fix in advance — the EA/Librarian/Coach charters (this phase and later) each settle it themselves. |

## Body

Free text below the frontmatter, structured under three headings every charter includes:

- **Role & purpose** — one paragraph, in the agent's own voice-neutral terms, of what this agent is for. Should read as a tighter restatement of its `CONTEXT.md` glossary entry, not a departure from it.
- **Boundaries** — what this agent must never do, stated explicitly rather than left implicit. Every charter restates PRD Principle 5 ("autonomy is earned, never assumed") in its own terms; Area charters additionally restate "directs, never executes" (PRD §5); System agents restate whatever their own non-negotiables are (e.g. the EA's classify-only triage, PRD §2.10).
- **Session behaviour** — what this agent reads before acting (its own charter, plus `memory` if it has any) and what it writes back when a session ends.

## Worked example (stub)

A minimal stub proving the shape holds — not a real charter. Tickets 15 (EA), 16 (Area CEO), and 17 (Capability workforce) write the real ones to `protocols/charters/`.

```markdown
---
type: charter
charter-kind: area
scope: generic
agent: Area CEO
directs: Capability agents
commissioned-by: —
tool-scope: see body
memory: areas/<slug>/_memory.md (per instance)
---

# Area CEO

## Role & purpose
Owns one life area's goals, strategy, and memory. Plans with the user
(chat or voice); directs Capability agents for legwork.

## Boundaries
Directs, never executes (PRD §5) — any action beyond planning-level
direction is commissioned to a Capability agent, never done directly.

## Session behaviour
Reads its area note and `_memory.md` before each session; writes
continuity notes back to `_memory.md` when the session ends.
```

An instance materialised from it (`scope: instance`) carries the same three body headings, specialised to that area, plus the frontmatter shown in "Frontmatter fields" above.

## Non-goals (v0)

- No script implementation — this is the schema spec; materialising an instance from a generic charter, via a Claude Code Adapter binding, is tickets 15/16/17's job.
- No enforcement mechanism for `tool-scope` — declaring the boundary is this Protocol's job; checking it at commission time is ticket 17's commissioning contract.
- No charter written in full here — EA, Area CEO, and the Capability roles are drafted for real in tickets 15, 16, and 17 respectively.
