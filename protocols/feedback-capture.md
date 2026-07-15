# Protocol: Feedback capture mechanics (v0)

Defines how the Action Log's `feedback` field (`protocols/action-log-schema.md`, ADR-0005) actually gets written after the fact. ADR-0006's graduation engine treats `feedback` as a fully specified, countable field — this Protocol is what makes that true: the exact value set, the two real write paths, and what happens to non-standard input. Scope is capture-and-write mechanics only — no new Dashboard or EA UX beyond what's described here (Phase 5, Wayfinder ticket 01).

## Value set

Three canonical values, one line each:

| Value | Meaning |
|---|---|
| `—` | Unset — not yet reviewed. Never itself a signal of approval (ADR-0006). |
| `validated` | Kelvin explicitly confirmed the action was right. |
| `corrected — <detail>` | Kelvin explicitly said the action was wrong. The detail is **always present** on the same line as the tag — a free-text note or link explaining what was wrong (e.g. `feedback: corrected — should have filed under Home, not Work`), matching the existing one-line-per-field prose style used for `action:`/`outcome:` elsewhere in the schema. A bare `corrected` tag would be enough for the graduation engine's counting logic, but is a dead end for the rule-learning mechanism (`protocols/rule-learning.md`), which needs the *why* to update a structured rule, not just the *that*. |

## Write paths

There are exactly **two** real write paths. `Dashboard.md` is not one of them.

1. **Hand-edited log** — Kelvin opens `log/YYYY-MM-DD.md` in Obsidian and types the value directly over the entry's `feedback: —` line.
2. **EA-mediated conversational** — Kelvin raises feedback in chat. The EA resolves which entry it means by **recency + confirm-back**: it guesses from context/timing, states which entry it resolved to, and only writes after Kelvin confirms (e.g. "Marking the Chatham SONIA email filing — 09:12 — as corrected, that the one?"). This catches mis-attribution cheaply without requiring Kelvin to cite an entry id for what's meant to be a low-friction path.

### Dashboard is never a write target

`Dashboard.md` stays pure-derivation, per its own protocol (`protocols/dashboard.md`): it is read/link-only and executes nothing. Its "today's Action Log" section links into `log/{today}.md` so Kelvin can spot which entries need a look, but the write itself always routes through one of the two paths above — never on the Dashboard. This is the same read-only-roll-up guarantee `protocols/dashboard.md` already commits to for Triage Plans and Waiting For items; feedback is a third instance of the same rule, not an exception to it.

## Classification/normalization of non-standard input

Applies only to the hand-edited-log path — the EA-mediated path already normalizes through its own confirm-back conversation, so nothing further is needed there.

Any non-empty `feedback` value that doesn't match the canonical set above (free-text Kelvin typed straight into the log that isn't exactly `validated` or `corrected — <detail>`) is treated as raw text and classified at the **next Graduation-check Heartbeat run** (`protocols/routines.md`, the same session-start touchpoint the graduation engine itself uses — see `protocols/risk-tier-classification.md` and ADR-0006 — rather than a second, separately-invented trigger). The Heartbeat pass rewrites the raw text in place to a canonical value so the log stays clean for any human or agent reading it later.

- On low classification confidence, it **falls back to `—`** (not-yet-reviewed) — it never guesses between `validated` and `corrected`.
- It never blocks on a clarifying question — there is no live conversation to ask into for an offline hand-edit.

## Idempotency and conflicts

**Last-write-wins. No conflict-detection mechanism.** A single entry's `feedback` field can be written more than once (e.g. Kelvin corrects something via chat, then later hand-edits the log to `validated`); whichever write happens last stands, with no surfaced conflict. The Brain is git-tracked (`protocols/version-control.md`) and ADR-0005 already treats git diffs as the audit trail underneath the Action Log — if a prior value is ever needed, `git log`/`git diff` on the log file recovers it. This is the vault's existing "git history is authoritative" convention applied here, not new machinery.

## Non-goals (v0)

- No new Dashboard UI for giving feedback (checkboxes, buttons) — out of scope per the map's own destination-naming.
- No structured feedback beyond the three values above (e.g. no severity scale, no numeric rating).
- No conflict resolution beyond last-write-wins.
