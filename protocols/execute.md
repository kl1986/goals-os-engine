# Protocol: Execute (v1.1)

Reads an approved Triage Plan and performs actions per ticked row. Supports generic, internal/reversible actions (`file-capture` or `discard-capture`) and `agent-dispatched` actions. For agent-dispatched actions, the output is QA'd by the Reviewer gate before surfacing. v1.1 (16/07/2026, `capture-source-plugins` map, ticket 09/15) generalizes `file-capture-today`'s insert-before-next-heading mechanic to any file — a `file#heading` destination (e.g. `people/Kat.md#🗣️ To Discuss`) files section-targeted, not just to today's daily note. No new action type — see the `file-capture` row below.

## Out of scope, explicitly

- **No outward-facing action types.** None exist yet; none are built here.
- **No auto-execute on confidence.** Every row needs an explicit `[x]` tick before Execute acts, regardless of the `confidence` column. Confidence-driven autonomy is graduation, Phase 5 (ADR-0006).

## The action types

Registered in `config/action-types.md` (materialised at onboarding), all currently `internal & reversible` / `confirm-first`:

| Destination cell | Action type | What happens |
|---|---|---|
| a real path, e.g. `areas/home/_inbox.md` | `file-capture` | Appends a dated bullet — a link back to the Raw Capture plus its preview — into that **existing** file. Never creates a new area or project; the destination's parent directory must already exist. |
| a real path with a heading anchor, e.g. `people/Kat.md#🗣️ To Discuss` | `file-capture` (same action type — a destination sub-form, not a new one) | Inserts the same dated bullet as the last line of the named `## heading` section — before the next heading, never a blind end-of-file append. Reuses `file-capture-today`'s existing insert-before-next-heading mechanic against *any* file and *any* heading, generalized rather than reinvented (ticket 09). The target **file** must already exist — a `file#heading` destination never creates it, same "never creates the destination" rule as plain `file-capture`'s directory requirement. The named heading must also already exist in that file. |
| literal `discard` | `discard-capture` | Writes no destination at all. |
| starts with `agent:` (e.g. `agent: Researcher`) | `agent-dispatched` | Routes the action through a Reviewer commission before the output surfaces. The Reviewer's pass/fail is logged as an Action Log entry chained to the original commission. |
| literal `today` | `file-capture-today` | Inserts a checkbox line as the last line of the daily note's `## Today's tasks` section (before the next heading) — never a blind end-of-file append like `file-capture`. No date prefix (the note's own filename/title is the date). Requires today's note (`<brain>/YYYY-MM-DD.md`) to already exist — this action never creates it. |

For `file-capture-today` cases: if today's note doesn't exist yet, this is an error exactly like the existing "destination directory doesn't exist" case for `file-capture` — reported, the row left untouched, doesn't block other rows in the same run, and doesn't count as done. Also note that `file-capture-today` rows DO get archived to `archive/inbox/<source>/` and marked `[x] (done)`, same as `file-capture` (only `agent-dispatched` skips those steps).

Execute also reads the Triage Plan's `rule` column (`triage.md`): for a `Pass A` row whose `rule` cell isn't `—`, the Action Log entry's `trigger` field becomes `Execute (Routine) — rule <rule_id>` instead of the bare `Execute (Routine)`, so a rule-driven action is traceable back to the specific rule that fired.

For `file-capture` and `discard-capture` cases: move the Raw Capture from `inbox/raw/<source>/` to `archive/inbox/<source>/` (collision-safe). `agent-dispatched` cases leave the Raw Capture in place for the Reviewer gate. For all cases, append an Action Log entry (`log_action.build_entry`/`append_entry`, dogfooding `action-log-schema.md`). Every run — whether or not any row was ticked — also bumps Execute's own row in `config/routine-state.md` (`heartbeat.bump`), so its Last-run state is accurate even though Execute is event-triggered and outside Heartbeat's overdue-checking (`routines.md`).

## Row state machine

A Triage Plan row's `approve` cell has three states:

- `[ ]` — pending human review. Execute never touches it, ever.
- `[x]` — approved, ready to execute. Execute processes it this run.
- `[x] (done)` — already executed. Left alone on any future run (idempotent — re-running Execute against a partially-worked plan never re-files or re-archives an already-done row).

## Plan completion

Once a run leaves zero rows in the `[ ]` state (every row is either not yet touched-but-none-are-`[ ]`, i.e. all have been ticked and executed across this or prior runs), the plan's frontmatter `status` flips from `pending` to `executed` and the file moves from `inbox/triage/` to `archive/triage/` (collision-safe). A plan with even one row still `[ ]` stays open in `inbox/triage/`.

## Error handling

A row that can't be executed (Raw Capture missing, destination directory doesn't exist, destination still reads `unmatched`, — for `file-capture-today` specifically — today's daily note doesn't exist yet, or — for a `file#heading` destination specifically — the target file doesn't exist yet or exists but has no matching `## heading` section) is reported as an error and left untouched — it does not block the other rows in the same run, and does not count as "done" for the completion check.

## Adapter binding

See [`adapters/claude-code/skills/execute-triage/`](../adapters/claude-code/skills/execute-triage/).

## Non-goals (v1)

- No auto-execution regardless of confidence (Phase 5).
