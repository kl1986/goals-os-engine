# The Engine ADR series is canonical; the Brain keeps no series of its own

`goals-os-engine/docs/adr/` is the single ADR series for Goals OS. The records currently in `Vault/projects/goals-os/docs/adr/` that have no Engine counterpart are de-personalised and renumbered into it; `Vault/projects/goals-os/docs/adr/` becomes a pointer to the Engine series rather than a second store. A new ADR takes the next free Engine number, always. Decided 04/08/2026.

**Why:** an ADR number is a citation key, and this one had stopped resolving. Two live series had diverged and both were being written to:

| Number | Engine `docs/adr/` | Brain `projects/goals-os/docs/adr/` |
|---|---|---|
| 0001–0028 | present | present (near-identical; Engine's are de-personalised) |
| 0029 | `durable-wiki-source-feedback` (26/07) | `release-before-full-v1-parity` (25/07) |
| 0030 | *absent* | `cadence-ownership-moves-to-the-brain` (25/07) |
| 0031 | `triage-rows-are-task-list-items-grouped-by-destination` | **two files** — `meeting-hub-writes-…` *and* `today-extends-the-daily-note` |
| 0032 | `the-build-pipeline-is-sized-per-ticket…` | `routines-use-a-whitelisted-macos-launcher` |
| 0033 | `a-triage-row-may-name-several-destinations…` | `today-planning-is-ticket-metadata-rendered-by-bases` |

So "ADR-0029" named two different decisions depending on which repo you read, "ADR-0031" named *three*, and the collision ran to 0033. The failure is silent in the worst way: a reader following a citation gets a plausible, well-written, wrong ADR and no signal that it is wrong.

**It was already load-bearing when it was found.** `goals-os-engine/protocols/routines.md` cites ADR-0030 for the cadence decision — a record that exists only in the Brain series. An Engine reader following an Engine protocol's own citation dead-ends today. That is exactly the failure [[write-the-missing-adr-files-0012-to-0028]] was raised to fix; that ticket backfilled 0012–0028 into the Engine without reconciling the tail, so the collision survived it and then grew by four more numbers.

**Why the Engine and not the Brain,** given the Brain series is further ahead: the Engine is the distributable artefact and contains zero user data by definition (`CONTEXT.md`). Decisions about protocols, schemas and the build pipeline are decisions about the thing other people install; they belong with it. The Brain-only records are already the *same* decisions written with Kelvin's name in them, not different decisions — de-personalising them is the normal Engine-copy transform, not a rewrite. The reverse direction would have made the private repo the source of truth for the public one.

**Numbering is now unambiguous by construction.** One series, one highest number, next-free-wins. The alternative we rejected — two deliberate series on non-colliding ranges (Engine 0001–0999, Brain 1000+) — would have made a bare number unambiguous again while leaving the harder problem untouched: a reader still has to know two places exist, protocols would still cite across the boundary, and the de-personalised Engine copies of 0001–0028 would remain duplicated records that can drift from their Brain twins independently. The split was never deliberate; it was drift, and formalising drift is not reconciliation.

**Consequences.** Every citation of Brain 0029–0033 must be repointed across all three repos plus the Brain — grep, do not assume. The two files both numbered 0031 must be separated before either can move. Engine 0030 is free and takes `cadence-ownership-moves-to-the-brain`, which repairs the `protocols/routines.md` dead-end citation without touching that protocol at all. Anything written between this decision and its execution goes to the next free *Engine* number.

**Rejected:** *two deliberate non-colliding series* — see above; *merging into the Brain series* — makes the private repo canonical for the public artefact; *leaving it and documenting the ambiguity* — the ambiguity is silent at the point of use, which is the one place documentation cannot reach.
