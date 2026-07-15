# Protocol: Risk-tier classification (v0)

Defines the taxonomy and decision procedure behind `config/action-types.md`'s `Risk tier` column — the property ADR-0006's graduation engine reads as a plain per-type lookup. This is a classification **criteria** doc, not a schema change: `config/action-types.md`'s shape is unaffected (Phase 5, Wayfinder ticket 02).

## Taxonomy

Two values only, locked — no third tier:

- **`internal & reversible`** — filing, tagging, drafting. An unreviewed entry aged past the review window counts as approval (`protocols/feedback-capture.md`, `config/autonomy-policy.md`); the graduation engine grows autonomy for this tier organically, without requiring review effort on every instance.
- **`outward-facing / hard-to-reverse`** — sending, deleting, spending, messaging people. Graduates only on explicit `validated` feedback; silence (`—`) never counts, no matter how old.

A correction (`feedback: corrected — <detail>`) instantly demotes the action type in either tier, resetting its qualifying count to zero (ADR-0006).

Nothing in real use has forced a third tier. Resist adding one for an action type that seems "outward-facing but trivially reversible" (e.g. a draft that hasn't sent yet) — apply the decision procedure below instead; it already resolves that case correctly (see the worked example).

## Decision procedure

An action type is **`outward-facing / hard-to-reverse`** if *either*:

- **(a)** its effect reaches outside the Brain's own git-tracked files — it sends, spends, messages a real person, or touches an external system, **or**
- **(b)** even fully confined to the Brain, a plain `git revert` of the change would **not** be a complete, true undo of its real consequence — identity dissolution, cascading references, anything other content may already depend on.

Otherwise: **`internal & reversible`** — a `git revert` is a true, complete undo.

Apply this test to any new action type when it's first defined (e.g. by the Librarian charter, `protocols/charters/librarian.md`, or any Adapter introducing a new type) and whenever an existing type is next touched (see "Incremental, not retroactive" below).

### Worked example (the precedent this procedure is grounded in)

`config/action-types.md` already contains the one real case this test had to resolve correctly:

- **`wiki-audit-merge-duplicate`** → `outward-facing / hard-to-reverse`. Merging two Wiki articles discards a separate identity that other content may already reference — test (b) fails: a `git revert` restores the deleted article's text, but doesn't automatically restore every backlink and downstream assumption that treated the merge as settled. Not a complete undo.
- **`wiki-audit-delete-stale`** → `internal & reversible`, despite ADR-0006's example prose listing "deleting" under the harder tier. A plain deletion's `git revert` *is* a complete undo — the file comes back exactly as it was, nothing else in the Brain had time to build on its absence. Test (b) passes; it stays internal.

The lesson: don't pattern-match on the verb (delete, merge, send) — apply tests (a) and (b) to what actually happens and whether reverting truly undoes it.

## No schema change

`config/action-types.md` stays exactly as-is: `Action type | Risk tier | Autonomy level | Notes`. No per-action-type threshold-override column. Thresholds (review window, minimum qualifying instances, minimum session spread) are set once per risk tier as Brain config (`config/autonomy-policy.md`) — every action type within a tier graduates under the same rule. The existing `Autonomy level` column (`confirm-first` / `autonomous`) is the flag the graduation engine flips on graduation or demotion; this protocol only governs how `Risk tier` gets assigned, not that column.

Rule-diff proposals (`protocols/rule-learning.md`) get `internal & reversible` by default under this same test: a rule change doesn't reach outside the Brain, and reverting it is a complete undo of the rule going forward — no identity-dissolution problem the way merging Wiki articles has.

## Incremental, not retroactive

This is a classification criteria doc, not a retroactive audit. Existing action types in `config/action-types.md` keep their current tier as-is; they get re-tagged only incrementally, whenever each type is next touched for some other reason (a Wiki Compile/Audit ticket, a new Protocol revision, etc.) — never in a bulk pass applying this procedure to all 16 rows at once.

## See also

- ADR-0006 (`docs/adr/0006-risk-tiered-graduation.md`) — the tiers' origin and the silence-as-approval / explicit-only-for-outward rules this taxonomy feeds.
- `protocols/feedback-capture.md` — the `feedback` field values the graduation engine counts per tier.
- `config/autonomy-policy.md` — the uniform per-tier thresholds (review window, qualifying count, session spread, review-debt cap).

## Non-goals (v0)

- No third tier, no per-type threshold overrides — see above.
- No retroactive re-tagging pass — see above.
- No script/automation here — this is a criteria doc for a human or agent classifying a *new* action type by hand; the graduation engine itself only ever reads the `Risk tier` column, it never computes one.
