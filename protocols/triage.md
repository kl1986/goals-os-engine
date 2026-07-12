# Protocol: Triage (v0)

Classifies Raw Captures against structured routing rules and writes a Triage Plan — the confirm-first review gate between Capture and Execute. Introduces `inbox/triage/` as the Brain's first new layout convention since Phase 1.

## Principle 10 — classify-only

This Protocol can write **nothing but a Triage Plan file.** That's structural, not a policy choice: Raw Captures are untrusted input (PRD Principle 10), and a Triage Plan is inert — a table of proposed routes awaiting a human tick — so nothing captured can itself trigger an action just by being classified. Execution only ever happens from an approved plan, in `execute.md`.

## Two-pass classification

- **Pass A — deterministic rule match.** `scripts/triage.py`'s `match_captures()` checks every un-triaged capture against `config/routing-rules.md`'s `if`/`then` rules. Zero LLM calls, fully reproducible. A match routes the capture with the rule's destination and confidence.
- **Pass B — model classification (unmatched only).** Anything Pass A can't resolve is the Adapter's job, done in-session: the model proposes a destination and confidence for the row. The script's own output for a Pass-B item is always `unmatched` — **never a guess** — so a bad automatic classification can't slip in disguised as Pass A.

## Routing rules (`config/routing-rules.md`)

A hand-written `if`/`then` DSL, not YAML — deliberately, since the Engine carries zero third-party dependencies and this shape needs no parser library:

```
if: source == "voice" and contains("milk")
then: route -> areas/home/_inbox.md
confidence: High
```

`source` is required; `contains("...")` is an optional case-insensitive substring match against the capture's title + body. `confidence` defaults to `Medium` if omitted. Rules are additive-only — a Brain grows this file as routing patterns emerge; nothing here is machine-generated except by an explicit, confirm-first rule-learning step (PRD §7, Phase 5).

## Triage Plan file

`inbox/triage/{date}-{source}.md`:

```markdown
---
type: triage-plan
source: voice
date: 2026-07-11
status: pending
---

# Triage Plan — voice — 2026-07-11

| # | capture | preview | route | destination | confidence | approve |
|---|---|---|---|---|---|---|
| 1 | [[inbox/raw/voice/2026-07-11-140203-buy-milk]] | Remember to buy milk on the way home. | Pass A | areas/home/_inbox.md | High | [ ] |
| 2 | [[inbox/raw/voice/2026-07-11-140500-standup-notes]] | discussed the roadmap | Pass B | areas/work/_inbox.md | Medium | [ ] |
```

`status` is `pending` until every row is executed, then flips to `executed` and the file moves to `archive/triage/` (see `execute.md`). Every row needs an explicit `[x]` tick before Execute will act on it — regardless of confidence; auto-execution on confidence is graduation, Phase 5.

A destination of literal `discard` (rather than a real path) tells Execute to archive the Raw Capture with nothing filed — the right call when Pass B decides an item isn't worth keeping. Pass A never writes `discard`; only in-session Pass B classification does.

## Idempotency

Re-running Triage never duplicates a row, even across a day boundary: `write_triage_plan()` checks the `capture` column of *every still-open* plan for that source (`inbox/triage/*-{source}.md`, any date — executed plans have already moved to `archive/triage/`) and only appends genuinely new captures. A capture that's still un-executed the next day doesn't get a second row in tomorrow's plan just because Triage ran again. Existing rows — including any Pass-B edits or ticks already made — are left untouched.

## Adapter binding

See [`adapters/claude-code/skills/triage-plan/`](../adapters/claude-code/skills/triage-plan/). Its `allowed-tools` are scoped so it can only write inside `inbox/triage/` — never `inbox/raw/`, never a destination folder. That scoping is what makes Principle 10 real, not just documented.

## Non-goals (v0)

- No auto-execution of any row regardless of confidence or route — every row needs an explicit human tick (Phase 5 is graduation).
- No rule-learning from feedback yet — routing rules are hand-edited only in Phase 2.
- No cross-source triage in one run — the CLI sweeps one `--source` at a time; the Adapter loops if a full sweep across sources is wanted.
