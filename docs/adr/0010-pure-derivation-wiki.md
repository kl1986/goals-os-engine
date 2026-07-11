# The Wiki is purely machine-derived; the resynthesis guarantee is an Engine invariant

The synthesised knowledge layer (Wiki) is a pure function of (Raw Captures + validated feedback) and may be dropped and rebuilt at any time by any model — no human work can be lost because none lives there. Human knowledge (decisions, standards, goals) lives only in the curated layer, which the machine reads but does not own. A human "edit" to a Wiki article is expressed as feedback that the next synthesis incorporates, not a direct edit. Carries v1's decided-vs-learned boundary into the Engine as law. Decided 11/07/2026.

**Rejected:** mixed layer with protected human blocks (resynthesis becomes a merge problem); snapshot-and-rebuild over human edits (silently buries human effort in git history).

**Amended 11/07/2026 (adversarial review):** the guarantee is a **safety property, not a determinism claim**. LLM synthesis is non-deterministic — two rebuilds will differ in wording and emphasis; what is guaranteed is that rebuilding is always *permitted* and *loses no human work*, because none lives in the Wiki. Resynthesis is **incremental by default** (per article/concept, triggered by new sources or feedback); full-vault rebuilds are an exceptional, costed operation, not a routine.
