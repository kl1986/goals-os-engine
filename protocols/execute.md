# Protocol: Execute (v0)

Reads an approved Triage Plan and performs exactly one of two generic, internal/reversible actions per ticked row — `file-capture` or `discard-capture` — then archives the Raw Capture and logs an Action Log entry. Deliberately not agent dispatch: Area/Capability agents don't exist until Phase 3.

## Out of scope, explicitly

- **No Area/Capability agent routing.** Every action in Phase 2 is one of the two generic types below — nothing is commissioned to an agent.
- **No outward-facing action types.** None exist yet; none are built here.
- **No auto-execute on confidence.** Every row needs an explicit `[x]` tick before Execute acts, regardless of the `confidence` column. Confidence-driven autonomy is graduation, Phase 5 (ADR-0006).

## The two action types

Registered in `config/action-types.md` (materialised at onboarding), both `internal & reversible` / `confirm-first`:

| Destination cell | Action type | What happens |
|---|---|---|
| a real path, e.g. `areas/home/_inbox.md` | `file-capture` | Appends a dated bullet — a link back to the Raw Capture plus its preview — into that **existing** file. Never creates a new area or project; the destination's parent directory must already exist. |
| literal `discard` | `discard-capture` | Writes no destination at all. |

Both cases then: move the Raw Capture from `inbox/raw/<source>/` to `archive/inbox/<source>/` (collision-safe), and append one Action Log entry (`log_action.build_entry`/`append_entry`, dogfooding `action-log-schema.md`).

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

## Non-goals (v0)

- No agent dispatch (Phase 3).
- No auto-execution regardless of confidence (Phase 5).
- No new action types beyond `file-capture`/`discard-capture` — that's the next Execute ticket's problem, once Area/Capability agents exist.
