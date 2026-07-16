# Protocol: Triage (v0.1)

Classifies Raw Captures against structured routing rules and writes a Triage Plan — the confirm-first review gate between Capture and Execute. Introduces `inbox/triage/` as the Brain's first new layout convention since Phase 1. v0.1 (16/07/2026, `capture-source-plugins` map, ticket 09/15) extends Pass B's classification scope to also consider `people/` as a valid destination — see "Pass B and Person Hubs" below.

## Principle 10 — classify-only

This Protocol can write **nothing capture-derived but a Triage Plan file.** That's structural, not a policy choice: Raw Captures are untrusted input (PRD Principle 10), and a Triage Plan is inert — a table of proposed routes awaiting a human tick — so nothing captured can itself trigger an action just by being classified. Execution only ever happens from an approved plan, in `execute.md`.

The one exception is bookkeeping: each run also bumps its own `Triage` row in `config/routine-state.md` (`heartbeat.update_last_run`), so Heartbeat's due-check reflects that Triage actually ran. This write is fixed — a routine name and a timestamp, never anything read from a capture — so nothing an attacker controls can influence it; it doesn't reopen the surface Principle 10 closes.

## Two-pass classification

- **Pass A — deterministic rule match.** `scripts/triage.py`'s `match_captures()` checks every un-triaged capture against `config/routing-rules.md`'s `if`/`then` rules. Zero LLM calls, fully reproducible. A match routes the capture with the rule's destination and confidence.
- **Pass B — model classification (unmatched only).** Anything Pass A can't resolve is the Adapter's job, done in-session: the model proposes a destination and confidence for the row. The script's own output for a Pass-B item is always `unmatched` — **never a guess** — so a bad automatic classification can't slip in disguised as Pass A.

## Pass B and Person Hubs

Pass B considers `people/` a valid destination folder, same standing as `areas/` and `projects/` — it reads `people/_aliases.md` and the `people/` folder listing as context (the same cheap-first-index pattern `wiki/_index.md` already establishes for the Wiki) before deciding whether a capture is person-specific. This is ordinary Pass B judgment, not a new capability or a dedicated resolver script — no `people.py`-style fuzzy-matching/graduated-trust logic is ported from v1; Triage's structural confirm-first-always model (every row needs an explicit tick regardless of confidence) already gives Kelvin the same safety net a wrong guess needs, for free.

When Pass B judges a capture person-specific, it proposes a **section-targeted** destination — `people/<Full Name>.md#<heading>` (see `people-tracking.md`'s schema for the four sections) — rather than a bare file path, since a Person Hub has real markdown sections and a blind end-of-file append would land content in the wrong place. `execute.md`'s `file-capture` action type implements the `file#heading` destination form.

Which section is also ordinary Pass B judgment, not a dedicated classifier: outbound framing ("raise X with Kat", "ask Kat about Y") routes to `## 🗣️ To Discuss`; inbound framing ("waiting on Kat for Y", "Kat owes me X") routes to `## ⏳ Waiting For`. Unlike `routing-rules.md`'s deterministic `if`/`then` DSL (built for a non-linguistic signal like sender address — see ticket 03's `route.py` precedent), outbound-vs-inbound framing is a natural-language judgment call squarely inside what Pass B already does — no dedicated classifier script is warranted here.

Name resolution is also Pass B's own in-session judgment, reading the alias table and hub listing as context — not a ported script. A wrong guess (typo, ambiguous name) just gets corrected by Kelvin editing the `destination` cell before ticking, the same as any other Pass B misclassification.

## Routing rules (`config/routing-rules.md`)

A hand-written `if`/`then` DSL, not YAML — deliberately, since the Engine carries zero third-party dependencies and this shape needs no parser library:

```
if: source == "text" and contains("milk")
then: route -> areas/home/_inbox.md
confidence: High
```

`source` is required; `contains("...")` is an optional case-insensitive substring match against the capture's title + body. `confidence` defaults to `Medium` if omitted. `input-modality` (voice vs typed, see `capture.md`) is never a matchable field here by design (ADR-0011) — a rule that needs to discriminate by modality is a sign the capture belongs in its own `source`, not that Triage needs a second matchable dimension. Rules are additive-only — a Brain grows this file as routing patterns emerge; nothing here is machine-generated except by an explicit, confirm-first rule-learning step (PRD §7, Phase 5).

## Triage Plan file

`inbox/triage/{date}-{source}.md`:

```markdown
---
type: triage-plan
source: text
date: 2026-07-11
status: pending
---

# Triage Plan — text — 2026-07-11

| # | capture | preview | route | destination | confidence | rule | approve |
|---|---|---|---|---|---|---|---|
| 1 | [[inbox/raw/text/2026-07-11-140203-buy-milk]] | Remember to buy milk on the way home. | Pass A | areas/home/_inbox.md | High | a1b2c3d4 | [ ] |
| 2 | [[inbox/raw/text/2026-07-11-140500-standup-notes]] | discussed the roadmap | Pass B | areas/work/_inbox.md | Medium | — | [ ] |
```

`status` is `pending` until every row is executed, then flips to `executed` and the file moves to `archive/triage/` (see `execute.md`). Every row needs an explicit `[x]` tick before Execute will act on it — regardless of confidence; auto-execution on confidence is graduation, Phase 5.

The `rule` column records which `config/routing-rules.md` rule fired for a Pass A row — its first 8 hex characters of a SHA-1 hash over that rule's normalized `if:`/`then:`/`confidence:` text (`scripts/triage.py`'s `compute_rule_id()`). Pass B rows (no rule fired) always carry `—`. Execute reads this column to record which specific rule produced an action, on the Action Log's `trigger` field (`action-log-schema.md`).

A destination of literal `discard` (rather than a real path) tells Execute to archive the Raw Capture with nothing filed — the right call when Pass B decides an item isn't worth keeping. Pass A never writes `discard`; only in-session Pass B classification does.

## Idempotency

Re-running Triage never duplicates a row, even across a day boundary: `write_triage_plan()` checks the `capture` column of *every still-open* plan for that source (`inbox/triage/*-{source}.md`, any date — executed plans have already moved to `archive/triage/`) and only appends genuinely new captures. A capture that's still un-executed the next day doesn't get a second row in tomorrow's plan just because Triage ran again. Existing rows — including any Pass-B edits or ticks already made — are left untouched.

## Adapter binding

See [`adapters/claude-code/skills/triage-plan/`](../adapters/claude-code/skills/triage-plan/). Its `allowed-tools` are scoped so it can only write inside `inbox/triage/` — never `inbox/raw/`, never a destination folder. That scoping is what makes Principle 10 real, not just documented.

## Non-goals (v0)

- No auto-execution of any row regardless of confidence or route — every row needs an explicit human tick (Phase 5 is graduation).
- No rule-learning from feedback yet — routing rules are hand-edited only in Phase 2.
- No cross-source triage in one run — the CLI sweeps one `--source` at a time; the Adapter loops if a full sweep across sources is wanted.
