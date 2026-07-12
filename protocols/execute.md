# Protocol: Execute (v1)

Reads an approved Triage Plan and performs actions per ticked row. Supports generic, internal/reversible actions (`file-capture` or `discard-capture`) and `agent-dispatched` actions. For agent-dispatched actions, the output is QA'd by the Reviewer gate before surfacing.

## Out of scope, explicitly

- **No outward-facing action types.** None exist yet; none are built here.
- **No auto-execute on confidence.** Every row needs an explicit `[x]` tick before Execute acts, regardless of the `confidence` column. Confidence-driven autonomy is graduation, Phase 5 (ADR-0006).

## The action types

Registered in `config/action-types.md` (materialised at onboarding), all currently `internal & reversible` / `confirm-first`:

| Destination cell | Action type | What happens |
|---|---|---|
| a real path, e.g. `areas/home/_inbox.md` | `file-capture` | Appends a dated bullet — a link back to the Raw Capture plus its preview — into that **existing** file. Never creates a new area or project; the destination's parent directory must already exist. |
| literal `discard` | `discard-capture` | Writes no destination at all. |
| starts with `agent:` (e.g. `agent: Researcher`) | `agent-dispatched` | Routes the action through a Reviewer commission before the output surfaces. The Reviewer's pass/fail is logged as an Action Log entry chained to the original commission. |

For all cases: move the Raw Capture from `inbox/raw/<source>/` to `archive/inbox/<source>/` (collision-safe), and append an Action Log entry (`log_action.build_entry`/`append_entry`, dogfooding `action-log-schema.md`). Every run — whether or not any row was ticked — also bumps Execute's own row in `config/routine-state.md` (`heartbeat.bump`), so its Last-run state is accurate even though Execute is event-triggered and outside Heartbeat's overdue-checking (`routines.md`).

## Row state machine

A Triage Plan row's `approve` cell has three states:

- `[ ]` — pending human review. Execute never touches it, ever.
- `[x]` — approved, ready to execute. Execute processes it this run.
- `[x] (done)` — already executed. Left alone on any future run (idempotent — re-running Execute against a partially-worked plan never re-files or re-archives an already-done row).

## Plan completion

Once a run leaves zero rows in the `[ ]` state (every row is either not yet touched-but-none-are-`[ ]`, i.e. all have been ticked and executed across this or prior runs), the plan's frontmatter `status` flips from `pending` to `executed` and the file moves from `inbox/triage/` to `archive/triage/` (collision-safe). A plan with even one row still `[ ]` stays open in `inbox/triage/`.

## Error handling

A row that can't be executed (Raw Capture missing, destination directory doesn't exist, destination still reads `unmatched`) is reported as an error and left untouched — it does not block the other rows in the same run, and does not count as "done" for the completion check.

## Adapter binding

See [`adapters/claude-code/skills/execute-triage/`](../adapters/claude-code/skills/execute-triage/).

## Non-goals (v1)

- No auto-execution regardless of confidence (Phase 5).
