# Protocol: Rule-diff review surface (v0)

The confirm-first review gate for a proposed rule-set change (PRD §7, Phase 5 — Learning). Ticket 05's generic rule-learning mechanism detects a recurring correction pattern and proposes a diff; this Protocol defines the file that diff lands in, how Kelvin approves or rejects it, and what happens next. It is a dedicated surface — not folded into Triage Plans or Execute — but mirrors their location/lifecycle convention exactly (destination-naming decision, 14/07/2026; wayfinder ticket 06's resolution, 15/07/2026).

This doc is the **sole source of truth for the file format** a rule-diff proposal-writer (ticket 07, not yet built) must produce. It is deliberately precise enough to implement against without further clarification — read it in full before writing a proposal-writer or a consumer of this format.

## Location

`inbox/rule-diffs/{date}-{ruleset-slug}.md` — one batch file per day per rule-set, mirroring `inbox/triage/{date}-{source}.md` exactly (`protocols/triage.md`).

`{ruleset-slug}` is the target config file's basename without extension — e.g. `routing-rules` for `config/routing-rules.md`. **A batch file targets exactly one rule-set.** This is a deliberate consequence of the location convention (one file per date per ruleset-slug), not an accident: ticket 05's diff shape names "target rule-set file" as one of four fields per diff, but since every diff in a given batch file shares the same target by construction, that field is expressed **once, at the batch level**, via the frontmatter `ruleset` field — never repeated per diff. The target rule-set file's path is always `config/{ruleset}.md`, derived deterministically from `ruleset`; there is no free-text path field anywhere in the format.

## File format

```markdown
---
type: rule-diff-batch
ruleset: routing-rules
date: 2026-07-15
status: pending
---

# Rule diffs — routing-rules — 2026-07-15

### Diff 1 — sonia-email-to-work

```
if: source == "email" and contains("sonia")
then: route -> areas/work/_inbox.md
confidence: High
```

**Why:** Two corrections in the last week moved SONIA curve emails from Home to Work; this rule would have caught both automatically.

**Evidence:** [[log/2026-07-08#14:32 — file-email]], [[log/2026-07-12#09:15 — file-email]]

- [ ] Approve
- [ ] Reject
```

(A batch file may contain more than one `### Diff N — ...` section, each independently decided — same "one file, everything pending in one place" property as a Triage Plan.)

### Frontmatter

| Field | Meaning |
|---|---|
| `type` | Always `rule-diff-batch`. |
| `ruleset` | The target config file's basename without extension (e.g. `routing-rules`). Target path = `config/{ruleset}.md`. |
| `date` | `YYYY-MM-DD`, the date this batch file was created (matches the filename's date segment). |
| `status` | `pending` while any diff in the file is undecided; `resolved` once every diff has an explicit Approve or Reject tick (see Lifecycle). |

### Per-diff section

Each diff is a `###`-headed section, in file order, numbered `Diff 1`, `Diff 2`, … within that batch file (the number is a display label, not a global identifier — de-dup uses `diff_key()`, see below):

1. **Heading:** `### Diff {n} — {slug}` — `slug` is a short, free-text, kebab-case-by-convention label for human readability. Not normative, not parsed for meaning, not used as an identifier anywhere.
2. **Rule block:** a fenced code block (` ``` ` / ` ``` `, no language tag), containing the proposed rule **verbatim, in the target rule-set's own native syntax** — exactly the text that gets appended if approved. This mechanism never parses that syntax; it only treats the fenced block as an opaque, complete, appendable unit (ticket 05).
3. **`**Why:**` line** — one line, plain English, the rationale.
4. **`**Evidence:**` line** — one line, a comma-separated list of `[[wikilink]]`s to the ≥2 justifying Action Log correction entries, each pointing at a specific entry's heading: `[[log/YYYY-MM-DD#HH:MM — <action type>]]` (matches `action-log-schema.md`'s `### HH:MM — <action type>` heading exactly, so the link resolves to that entry in Obsidian). **Fewer than two links makes the diff malformed** — see Error handling.
5. **Decision checklist** — exactly two checkbox lines, in this order:
   ```
   - [ ] Approve
   - [ ] Reject
   ```
   Both start unticked. Kelvin (or an Adapter acting only on his explicit instruction) ticks **at most one**. Never tick a box on this surface automatically or speculatively — same discipline as Triage Plan approval.

### Processed-state marker

Once a decision has been applied by the adapter, the ticked line gains a parenthetical marker immediately after `[x]`, mirroring Triage/Execute's `[x] (done)` / `[x] (dispatched)` convention:

- `- [x] (applied) Approve`
- `- [x] (logged) Reject`

A bare `[x] Approve` / `[x] Reject` (no marker) means "decided, not yet processed" — the next run picks it up. A marker present means "already processed" — every future run skips it untouched. This is what makes re-running idempotent (see Idempotency).

## Approve

1. Append the diff's rule block, unmodified, to the end of `config/{ruleset}.md` — **additive-only**: never edit, reorder, or remove anything already in that file. The append is a **new fenced code block** (blank line, then ` ``` `, the rule block, ` ``` `), not an insertion into an existing fence — this keeps the append syntax-agnostic (no parsing of what's already there) and is safe because every reader of a rule-set file (e.g. `scripts/triage.py`'s `parse_routing_rules()`) scans the whole file for `if:`/`then:`/`confidence:`-shaped lines regardless of fence boundaries, not just the first fenced block.
2. Write an Action Log entry (`action-log-schema.md`):
   - `action type`: `apply-rule-diff`
   - `action`: `Applied rule diff (Diff {n} — {slug}) to config/{ruleset}.md.`
   - `outcome`: `Rule appended to config/{ruleset}.md`
   - `input link`: the batch file's path relative to the Brain (e.g. `inbox/rule-diffs/2026-07-15-routing-rules.md`)
   - `confidence`: fixed `High` for every `apply-rule-diff`/`reject-rule-diff` entry — see "On the `confidence` field" below.
   - `actor`: `EA` (matches `execute.py`'s convention for adapter-executed, human-approved actions).
   - `trigger`: `Rule diff review`.
3. Risk tier: `internal & reversible` (ticket 02's default for rule-diff proposals); autonomy level: `confirm-first` by default (ticket 01), graduatable via ticket 03's engine unmodified (see Graduation, below).

## Reject

1. **No write to the rule-set file** — the target file is untouched.
2. Write an Action Log entry:
   - `action type`: `reject-rule-diff`
   - `action`: `Rejected rule diff (Diff {n} — {slug}) — no change to config/{ruleset}.md.`
   - `outcome`: `No write — config/{ruleset}.md unchanged`
   - same `input link` / `confidence` / `actor` / `trigger` conventions as Approve.

This entry is **required**, not optional bookkeeping: a rejected diff leaves no trace in the rule-set file itself, so without a logged record, ticket 07's weekly pattern-detector has no memory that this exact pattern was already considered and declined — it would re-propose the identical diff the following week. The Action Log entry is that memory.

## On the `confidence` field

`action-log-schema.md`'s `confidence` field is normally the acting agent's self-assessed confidence in a classification. Ticket 05's diff shape — `{target rule-set file, rule block, ≥2 evidence links, rationale}` — deliberately has no confidence input; the diff isn't a classification, it's a human-confirmed decision on a proposal. Rather than inventing an unspecified fifth field, both `apply-rule-diff` and `reject-rule-diff` entries hardcode `confidence: High`. This is a deliberate simplification, not an oversight — flag it if a future ticket needs finer granularity here.

## De-dup key (for ticket 07)

Ticket 07's proposal-writer must not re-propose a diff that's already pending, already applied, or already rejected. The de-dup key is a **content hash of the rule block**, not the evidence set (two detections of "the same" pattern can cite slightly different correction entries as evidence, but the proposed rule block itself is what actually matters for "have we seen this exact proposal before"):

```python
def diff_key(ruleset: str, rule_block: str) -> str:
    normalized = rule_block.strip()
    return hashlib.sha256(f"{ruleset}\n{normalized}".encode("utf-8")).hexdigest()[:12]
```

(Implemented as `rule_diff_review.diff_key()` in this repo — import it rather than reimplementing the formula.)

Before writing a new diff for a given `ruleset`, ticket 07 must compute `diff_key(ruleset, candidate_rule_block)` and skip proposing if it matches any of:

1. **Any diff — decided or undecided — in a currently open batch file for that ruleset** (`inbox/rule-diffs/*-{ruleset}.md` with `status: pending`). Covers "already proposed, awaiting or mid-review."
2. **A rule block already present verbatim in the target file itself** (`config/{ruleset}.md`). Covers "already applied" — once approved, the rule literally lives in the target file, so this check alone is sufficient for the applied case without needing to scan `archive/rule-diffs/`.
3. **Any diff recorded as `Reject` in an archived batch file for that ruleset** (`archive/rule-diffs/*-{ruleset}.md`). Covers "already rejected" — rejection leaves no trace in the target file, so this is the *only* place that memory lives. This is the one respect in which rule-diff idempotency must look further back than Triage's precedent (`triage.md`'s idempotency check only scans still-open plans, because an executed Triage row's completion is witnessed by the capture having moved to `archive/inbox/` — but a rejected rule-diff has no equivalent physical trace outside the Action Log and the archived batch file itself).

## Lifecycle

Mirrors `protocols/triage.md` / `protocols/execute.md`'s Triage Plan lifecycle exactly:

- `status: pending` while any diff in the batch file is undecided (neither `[x] (applied)` nor `[x] (logged)`).
- Once every diff in the file carries a processed marker, `status` flips to `resolved` and the file moves from `inbox/rule-diffs/` to `archive/rule-diffs/` (collision-safe rename, same as `execute.py`'s `_move_collision_safe`).
- A batch file with even one still-undecided diff (or one that errored — see Error handling) stays `pending`, stays in `inbox/rule-diffs/`, and is left otherwise untouched by that run.

## Idempotency

Re-running the adapter's apply logic against a batch file never re-applies or re-logs a diff whose checkbox already carries a `(applied)`/`(logged)` marker — it is skipped outright, exactly like Execute's `[x] (done)` rows. This is what makes "run it again" always safe, independent of the ticket-07 de-dup concern above (which is about never *writing* a duplicate proposal in the first place — a different idempotency guarantee, at a different layer).

## Error handling

A diff is malformed and refused (reported, left untouched, doesn't block other diffs in the same batch file, doesn't count toward `resolved`) if any of:

- The rule block is empty or missing.
- The `**Why:**` line is missing.
- Fewer than two `[[wikilink]]`s appear on the `**Evidence:**` line.
- **Both** `Approve` and `Reject` are ticked at once.

This mirrors `execute.md`'s error-handling shape (a bad row is reported and skipped, not a run-aborting failure).

## Graduation behaviour

Unchanged from ticket 05/06's resolution: `apply-rule-diff` is `internal & reversible` and graduatable via ticket 03's engine, unmodified. Graduating removes the need to explicitly tick Approve — a diff still **appears** on this surface every time a pattern is detected; silence within the review window applies it instead of requiring a click (ticket 03's existing `—`-ages-into-approval mechanic, reused as-is). This surface's rendering and file format don't change based on autonomy level — only whether a human tick or a review-window timeout is what ultimately marks the diff `(applied)`.

This surface is **not itself a Heartbeat-checked Routine** — it has no `config/routine-state.md` row and isn't swept by `heartbeat.py`'s `compute_overdue()`. It's invoked on demand (same as `execute-triage`), and its pending state is surfaced passively via `Dashboard.md`'s `## Pending review` section (see below). Wiring an automatic sweep is ticket 07/a later ticket's job, not this one's.

## Dashboard integration

`Dashboard.md` gains a `## Pending review` section, same read-only-pointer pattern as the existing `## Pending Triage Plans` section (`protocols/dashboard.md`): one line per `inbox/rule-diffs/*.md` file with `status: pending`, linking to the file and showing a decided/pending diff count. Never a write target — approving or rejecting happens by ticking a box in the batch file itself, not on the Dashboard. See `scripts/dashboard.py`'s `_pending_rule_diffs()` / `_pending_rule_diff_summary()`.

## Adapter binding

See [`adapters/claude-code/skills/rule-diff-review/`](../adapters/claude-code/skills/rule-diff-review/). All the logic — parsing, applying, archiving — lives in `scripts/rule_diff_review.py`; the skill only calls it and relays the result, same division of labour as `execute-triage`/`execute.py`.

## Non-goals (v0)

- No proposal-writing here — that's ticket 07, building against this doc as a fixed contract.
- No automatic Heartbeat sweep of `inbox/rule-diffs/` — invoked on demand only (see Graduation behaviour, above).
- No cross-ruleset batch file — one file always targets exactly one rule-set.
- No numeric/self-assessed confidence — fixed `High` for both decision outcomes (see "On the `confidence` field").
