# Protocol: Rule-learning mechanism (v0)

The generic, weekly pattern-detector that closes the learning loop: when the same kind of `corrected — <detail>` feedback (`protocols/action-log-schema.md`) keeps showing up against a rule-set's decisions, this mechanism proposes a new rule for a human to review, rather than the same miss recurring silently forever (PRD §6, Phase 5 — Learning, wayfinder ticket 05's resolution).

This doc defines the generic contract; the one real instance today is `config/routing-rules.md` (read by `scripts/triage.py`). It is written generically enough that Phase 4's deferred Wiki Audit auto-fix rules, or any future capability agent's own rule-set, can plug in without a second mechanism.

## Minimal rule-set contract

A `config/` file is eligible for rule-learning if it:

1. Holds discrete, self-contained rule units in its own native plain-text format. This mechanism never parses that syntax beyond what's needed to append a complete new unit — it treats each unit as opaque.
2. Has an existing protocol/script that reads it and produces decisions (e.g. `protocols/triage.md` / `scripts/triage.py` for `config/routing-rules.md`).
3. Follows the additive-only convention — new units are appended, existing ones are never edited, reordered, or removed by any automated process.

## Diffs are additive-only, always

Same discipline as `protocols/rule-diff-review.md`'s Approve step: a proposed diff is always a new rule unit to append, never an edit to or removal of an existing one.

## Proposal trigger

A diff is only proposed once a **recurring pattern** is found: **≥2 `corrected — <detail>` Action Log entries whose free-text payloads point at the same underlying miss**. A single correction, however clear-cut, is not a pattern — it stays as a data point in the Action Log, not a proposal.

Deciding whether two corrections point at "the same underlying miss" is genuine semantic judgement, not scriptable pattern-matching (two corrections can use entirely different wording for the same miss, or similar wording for unrelated misses). This mechanism splits accordingly, mirroring `protocols/triage.md`'s Pass A/B split:

- **Scanning** (deterministic, scriptable): find every `corrected — <detail>` entry across the Action Log and extract its evidence link. `scripts/rule_learning.py`'s `find_corrections()`.
- **Grouping** (LLM-assisted, in-session): decide which scanned corrections share an underlying miss, and if a group has ≥2 members, draft the rule block + rationale that would have caught them. This runs at the Adapter layer (`adapters/claude-code/skills/rule-learning/`), not in the script.
- **Writing + idempotency** (deterministic, scriptable): given an Adapter-supplied group, check the ≥2 threshold and the de-dup rules below, then write the diff and log the proposal. `scripts/rule_learning.py`'s `propose_group()` / `run()`.

## Diff shape

Identical to the contract `protocols/rule-diff-review.md` (ticket 05's surface) consumes:

```
{
  target rule-set file,          # implicit — expressed once as the batch file's `ruleset` frontmatter field
  proposed new rule block,       # native syntax, verbatim-appendable
  ≥2 justifying correction entries (links),
  plain-English rationale,
}
```

## Idempotency (de-dup)

Before writing a new diff for a given `ruleset`, this mechanism must not re-propose one that's already pending, already applied, or already rejected. It reuses `protocols/rule-diff-review.md`'s documented de-dup key **unmodified** — a content hash of the proposed rule block (`rule_diff_review.diff_key(ruleset, rule_block)`), checked against:

1. Any diff — decided or undecided — in a currently open batch file for that ruleset (`inbox/rule-diffs/*-{ruleset}.md` with `status: pending`).
2. A rule block already present verbatim in the target file itself (`config/{ruleset}.md`) — covers "already applied."
3. Any diff recorded as `Reject` in an archived batch file for that ruleset (`archive/rule-diffs/*-{ruleset}.md`) — covers "already rejected," the one case that leaves no trace anywhere but the archived batch file.

See `protocols/rule-diff-review.md`'s "De-dup key" section for the full rationale; `scripts/rule_learning.py` imports `diff_key()` from `scripts/rule_diff_review.py` rather than reimplementing the formula.

## Cadence

**Weekly**, its own separate batch pass — deliberately **not** folded into the daily "Graduation check" Routine (ADR-0006, ticket 04's resolution). Graduation is pure counting/date-arithmetic; pattern-detection here is genuine semantic judgement, so it runs on a slower, its-own cadence and is never silent-automatic (see Application lifecycle).

## Application lifecycle

A proposed diff is tier `internal & reversible` (ticket 02's default for every rule-diff proposal) and is written, appears, and is decided entirely via `protocols/rule-diff-review.md`'s surface — this mechanism does no gating of its own:

- **Writing a proposal is unconfirmed** (autonomous — `propose-rule-diff` fires without a human in the loop), mirroring Triage's Pass A/B precedent where classify-and-write is unconfirmed and the gate sits at execution, not at classification.
- **Applying or rejecting the proposal is confirm-first**, via `protocols/rule-diff-review.md`'s Approve/Reject checklist — this mechanism has no special-cased graduation logic; `apply-rule-diff` is subject to ticket 03's graduation engine unmodified, same as every other internal & reversible action type.
- Once `apply-rule-diff` graduates to autonomous for a given Brain, a diff still **appears** on the review surface every time this pattern-detector proposes one — graduating removes the need to click Approve, not the visibility. Silence within the review window applies it instead (ticket 03's existing `—`-ages-into-approval mechanic, reused as-is).

## The `trigger` field, extended

`protocols/action-log-schema.md`'s `trigger` field ordinarily names a Routine or a direct instruction. For any Action Log entry produced via a rule-set match (e.g. a Triage Pass-A row that fired because of a rule this mechanism proposed and Kelvin approved), `trigger` should name which specific rule fired, not just "Triage (Routine)" — e.g. `Triage (Routine) — rule: sonia-email-to-work`. This is a small extension of the field's existing purpose (identifying *what* caused an action), not a new mechanism, and closes the loop: a future correction against that same rule's decision is itself evidence the rule needs revisiting, and the `trigger` value is what makes that traceable back to the rule. This mechanism's own `propose-rule-diff` entries use `trigger: Rule learning (Routine)` (no rule reference — there's no rule yet; the diff *is* the proposal).

## Cadence & Routine-manifest entry

Registered in `protocols/routines.md` as its own row, "Rule learning," cadence `weekly — heartbeat-checkable`, owner `EA` (the judgement-bearing layer, matching the Adapter-side grouping step above — not `scripts`, since this Routine is not silent-automatic like Version Control or Graduation check). `scripts/rule_learning.py`'s `run()` bumps its own row in `config/routine-state.md`, same convention as every other Routine-implementing script (`scripts/heartbeat.py`'s `bump()`), so `scripts/heartbeat.py`'s due-checker can flag it overdue like any other heartbeat-checkable Routine.

## Adapter binding

See [`adapters/claude-code/skills/rule-learning/`](../adapters/claude-code/skills/rule-learning/). `scripts/rule_learning.py` implements scanning, the ≥2 threshold check, the de-dup check, diff-writing (in `protocols/rule-diff-review.md`'s exact format), the `propose-rule-diff` Action Log entry, and the `config/routine-state.md` bump. The skill supplies the similarity judgement — grouping scanned corrections and drafting each group's rule block + rationale — then calls the script to do the rest, same division of labour as `triage-plan`'s Pass A (script) / Pass B (skill) split.

## Non-goals (v0)

- No proposal-writing outside this weekly pass — a single correction never triggers a proposal, regardless of how confident the classification.
- No editing or removing existing rule units — additive-only, always (see above).
- No new review surface — every proposal lands on `protocols/rule-diff-review.md`'s existing surface; this mechanism only ever writes to `inbox/rule-diffs/`, never to a `config/{ruleset}.md` file directly.
- No cross-ruleset grouping — a correction pattern is always scoped to one target rule-set; this mechanism doesn't infer which rule-set a correction belongs to (the Adapter's grouping step is responsible for that).
