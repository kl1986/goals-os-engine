# Protocol: Triage (v0.5)

Classifies Raw Captures against structured routing rules and writes a Triage Plan — the confirm-first review gate between Capture and Execute. Introduces `inbox/triage/` as the Brain's first new layout convention since Phase 1. v0.1 (16/07/2026, `capture-source-plugins` map, ticket 09/15) extends Pass B's classification scope to also consider `people/` as a valid destination — see "Pass B and Person Hubs" below. v0.2 (27/07/2026, ADR-0031) changed the Row shape into task list items. v0.5 (ADR-0036) unifies each Triage Row onto a single line with optional indented keeper option checkboxes (`- [ ] Act on this`, `- [ ] Area · \`path\``, `- [ ] Project · \`path\``, `- [ ] Bin it instead`), and stores Pass A metadata in frontmatter rules.

## Principle 10 — classify-only

This Protocol can write **nothing capture-derived but a Triage Plan file.** That's structural, not a policy choice: Raw Captures are untrusted input (PRD Principle 10), and a Triage Plan is inert — a list of proposed routes awaiting a human tick — so nothing captured can itself trigger an action just by being classified. Execution only ever happens from an approved plan, in `execute.md`.

The one exception is bookkeeping: each run also bumps its own `Triage` row in `config/routine-state.md` (`heartbeat.update_last_run`), so Heartbeat's due-check reflects that Triage actually ran. This write is fixed — a routine name and a timestamp, never anything read from a capture — so nothing an attacker controls can influence it; it doesn't reopen the surface Principle 10 closes.

## Two-pass classification

- **Pass A — deterministic rule match.** `scripts/triage.py`'s `match_captures()` checks every un-triaged capture against `config/routing-rules.md`'s `if`/`then` rules. Zero LLM calls, fully reproducible. A match routes the capture with the rule's destination and confidence, recording rule metadata into frontmatter `rules:`.
- **Pass B — model classification (unmatched only).** Anything Pass A can't resolve is the Adapter's job, done in-session: the model proposes a destination and confidence for the row. The script's own output for a Pass-B item is always `unmatched` — **never a guess** — so a bad automatic classification can't slip in disguised as Pass A.

## Pass B and Person Hubs

Pass B considers `people/` a valid destination folder, same standing as `areas/` and `projects/` — it reads `people/_aliases.md` and the `people/` folder listing as context (the same cheap-first-index pattern `wiki/_index.md` already establishes for the Wiki) before deciding whether a capture is person-specific. This is ordinary Pass B judgment, not a new capability or a dedicated resolver script — no `people.py`-style fuzzy-matching/graduated-trust logic is ported from v1; Triage's structural confirm-first-always model (every row needs an explicit tick regardless of confidence) already gives the user the same safety net a wrong guess needs, for free.

When Pass B judges a capture person-specific, it proposes a **section-targeted** destination — `people/<Full Name>.md#<heading>` (see `people-tracking.md`'s schema for the four sections) — rather than a bare file path, since a Person Hub has real markdown sections and a blind end-of-file append would land content in the wrong place. `execute.md`'s `file-capture` action type implements the `file#heading` destination form.

Which section is also ordinary Pass B judgment, not a dedicated classifier: outbound framing ("raise X with Example Person", "ask Example Person about Y") routes to `## 🗣️ To Discuss`; inbound framing ("waiting on Example Person for Y", "Example Person owes me X") routes to `## ⏳ Waiting For`. Unlike `routing-rules.md`'s deterministic `if`/`then` DSL (built for a non-linguistic signal like sender address — see ticket 03's `route.py` precedent), outbound-vs-inbound framing is a natural-language judgment call squarely inside what Pass B already does — no dedicated classifier script is warranted here.

Name resolution is also Pass B's own in-session judgment, reading the alias table and hub listing as context — not a ported script. A wrong guess (typo, ambiguous name) just gets corrected by the user editing the Row's destination before ticking, the same as any other Pass B misclassification — one edit, in place; the heading is regenerated on the next write.

## Routing rules (`config/routing-rules.md`)

A hand-written `if`/`then` DSL, not YAML — deliberately, since the Engine carries zero third-party dependencies and this shape needs no parser library:

```
if: source == "text" and contains("milk")
then: route -> areas/household/_inbox.md
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
rules:
  2026-07-11-140203-buy-milk.md:
    rule: a1b2c3d4
    confidence: High
---

# Triage Plan — text — 2026-07-11

## areas/household/_inbox.md

- [ ] Remember to buy milk on the way home → `areas/household/_inbox.md` [[inbox/raw/text/2026-07-11-140203-buy-milk.md]]

## unmatched

- [ ] Octopus Energy — £21.97 payment on 3rd August → `unmatched` [[inbox/raw/email/2026-07-11-140500-octopus.md]]
    - [ ] Act on this
    - [ ] Area · `areas/finances/_inbox.md`
    - [ ] Project · `projects/goals-os/_inbox.md`
    - [ ] Bin it instead
```

**v0.5 (01/08/2026, ADR-0036)** collapses each Row into a single line (`- [ ] <preview> → \`<destination>\` [[<capture_link>]]`), superseding ADR-0031's three-line continuation rule and ADR-0033's `%%` comment wrapper. The capture wikilink sits inline at the end of the task line. Positional row numbers leave the task line and are derived from document order during parsing (`scripts/execute.py`'s `_scan_blocks()`).

Pass A metadata (`rule` identifier and `confidence`) lives in Plan YAML frontmatter under a `rules:` block mapping capture filename to rule details. Pass B rows carry zero frontmatter rule entries. Execute reads this `rules:` block to record which specific rule produced an action, on the Action Log's `trigger` field (`action-log-schema.md`).

A multi-destination Row is supported by listing comma-separated destinations with each destination backticked (e.g. `→ \`dest1\`, \`dest2\``): the capture is archived once, the per-source `execute_hook.py` fires once, and one Action Log entry names every destination. Two combinations are refused as whole-Plan refusals alongside the blank destination — `discard` combined with a real destination (a contradiction), and the same destination listed twice (a duplicate entry). A Row groups under its **first** destination; the heading is regenerated output as before and is never read back.

Keeper Rows (destination `unmatched` or `?`) carry indented option checkboxes for friction-free triage on mobile:
- `- [ ] Act on this` (maps destination to `today`)
- `- [ ] Area · \`<path>\`` (sets destination to the specified Area path)
- `- [ ] Project · \`<path>\`` (sets destination to the specified Project path)
- `- [ ] Bin it instead` (maps destination to `discard`)

Noise/discard Rows carry zero continuation option lines.

The `## <destination>` heading is **presentation only** — it groups Rows sharing a destination so they can be approved as a run. It is *regenerated output*, never read for comparison (ADR-0031): the Row line's own destination is authoritative, parsing stays line-local (`scripts/execute.py`'s `ROW_RE`, the single owner of the Row shape), and both write paths — Triage's own and Execute's — pass the whole Plan through `execute.regroup_plan()`, which moves each Row block under the heading its destination names, creating headings that are needed and dropping ones left empty.

**Re-routing a Row is a single edit**: change the destination on the Row line (or tick one of its keeper option boxes) and stop. The Row executes to its edited destination wherever it currently sits, and the next write regroups it. Editing a *heading* achieves nothing and is reverted on the next write, because the heading has no authority.

`status` is `pending` until every Row is executed, then flips to `executed` and the file moves to `archive/triage/` (see `execute.md`). Every Row needs an explicit `[x]` tick before Execute will act on it — regardless of confidence; auto-execution on confidence is graduation, Phase 5.

A Brain holding Plans in older formats (3-line task list or pre-ADR-0031 markdown tables) converts them with `scripts/migrate_triage_rows_one_line.py --brain <brain>`. It rewrites every open Plan in `inbox/triage/` into the ADR-0036 single-line shape with nested keeper options and frontmatter rules, preserving approval states and verifying acceptance fields post-regroup. Legacy 3-line or table-based Rows cause whole-Plan refusals in Execute until converted.

A destination of literal `discard` (rather than a real path) tells Execute to archive the Raw Capture with nothing filed — the right call when an item isn't worth keeping.

**v0.4 (31/07/2026, ADR-0034):** Pass A can now write `discard` too. A rule may say `then: discard` in place of `then: route -> <path>`, so "this sender is noise" — the most repetitive judgement in the Brain, and 25 of 32 Rows on the 23/07 email Plan — is expressible as a deterministic rule instead of a per-capture model decision. It parses to the same `discard` literal Pass B writes, so the Row is identical downstream and Execute is unchanged. (`then: route -> discard` is accepted as the same rule and shares its id.)

The `discard` group is **pinned below every other group** in a Plan, whatever its Rows' positions, so the Rows wanting a decision are what you land on and Obsidian's native heading fold collapses the noise out of sight. Note this is a `##` heading rather than a callout: a callout's lines start `> `, which `ROW_RE` does not match, so Rows inside one would be invisible to Execute, the nudge and the Dashboard.

Noise Rows are **not pre-ticked**. "Default to noise" means classified as noise, not approved as noise — every Row still needs an explicit `[x]`, and pre-ticking would make Triage's write an approval on the user's behalf, which is graduation (Phase 5), not classification.

## Idempotency

Re-running Triage never duplicates a Row, even across a day boundary: `write_triage_plan()` checks the capture wikilink of *every still-open* plan for that source (`inbox/triage/*-{source}.md`, any date — executed plans have already moved to `archive/triage/`) and only adds genuinely new captures. That check matches on the `[[inbox/raw/...]]` wikilink and is format-agnostic, so it held across the ADR-0031 conversion. A capture that's still un-executed the next day doesn't get a second Row in tomorrow's plan just because Triage ran again. Existing Rows — including any Pass-B edits or ticks already made — are left untouched. A new Row is inserted under its own `## <destination>` heading, which is created if it does not exist yet, rather than appended at end-of-file, and the whole Plan is re-grouped before it is written, so a Plan whose Rows were re-routed by hand converges instead of accumulating Rows under stale headings.

## Adapter binding

See [`adapters/claude-code/skills/triage-plan/`](../adapters/claude-code/skills/triage-plan/). Its `allowed-tools` are scoped so it can only write inside `inbox/triage/` — never `inbox/raw/`, never a destination folder. That scoping is what makes Principle 10 real, not just documented.

## Non-goals (v0)

- No auto-execution of any row regardless of confidence or route — every row needs an explicit human tick (Phase 5 is graduation).
- No rule-learning from feedback yet — routing rules are hand-edited only in Phase 2.
- No cross-source triage in one run — the CLI sweeps one `--source` at a time; the Adapter loops if a full sweep across sources is wanted.
