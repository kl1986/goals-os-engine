# Protocol: Execute (v1.4)

Reads an approved Triage Plan and performs actions per ticked row. Supports generic, internal/reversible actions (`file-capture` or `discard-capture`) and `agent-dispatched` actions. For agent-dispatched actions, the output is QA'd by the Reviewer gate before surfacing. v1.1 (16/07/2026, `capture-source-plugins` map, ticket 09/15) generalizes `file-capture-today`'s insert-before-next-heading mechanic to any file — a `file#heading` destination (e.g. `people/Example Person.md#🗣️ To Discuss`) files section-targeted, not just to today's daily note. No new action type — see the `file-capture` row below. v1.2 (21/07/2026, ticket 14) adds an optional per-source post-action hook — see "Per-source hooks" below — with zero new action types; Execute itself stays fully generic. v1.3 (25/07/2026, `meeting-processing` component, ADR-0028) passes the ticked row's destination to that hook as `--destination`, so a hook honours the answer the user already gave by ticking rather than re-deriving it — see "Per-source hooks". Still zero new action types and still no source-specific knowledge: Execute forwards a string it already parsed. v1.4 (27/07/2026, ADR-0031) reads the new task-list Row shape, adds a whole-Plan refusal for any Row that cannot be read as an actionable Row (a malformed Row block, or a blank destination), and re-groups the Plan under `## <destination>` headings as part of its own write — see "Row state machine", "Refusals" and "Grouping" below.

## Out of scope, explicitly

- **No outward-facing action types dispatched by Execute itself.** Execute's own two action types (`file-capture`, `discard-capture`) stay internal/reversible. A per-source hook (below) *can* trigger an outward-facing effect (e.g. email's Gmail archive, `config/action-types.md`'s `email-archive-inbox`), but that's the hook's own action type, tracked separately — Execute's dispatch logic never gains a third type of its own.
- **No auto-execute on confidence.** Every row needs an explicit `[x]` tick before Execute acts, regardless of the `confidence` column. Confidence-driven autonomy is graduation, Phase 5 (ADR-0006).

## The action types

Registered in `config/action-types.md` (materialised at onboarding), all currently `internal & reversible` / `confirm-first`:

| Destination | Action type | What happens |
|---|---|---|
| a real path, e.g. `areas/household/_inbox.md` | `file-capture` | Appends a dated bullet — a link back to the Raw Capture plus its preview — into that **existing** file. Never creates a new area or project; the destination's parent directory must already exist. |
| a real path with a heading anchor, e.g. `people/Example Person.md#🗣️ To Discuss` | `file-capture` (same action type — a destination sub-form, not a new one) | Inserts the same dated bullet as the last line of the named `## heading` section — before the next heading, never a blind end-of-file append. Reuses `file-capture-today`'s existing insert-before-next-heading mechanic against *any* file and *any* heading, generalized rather than reinvented (ticket 09). The target **file** must already exist — a `file#heading` destination never creates it, same "never creates the destination" rule as plain `file-capture`'s directory requirement. The named heading must also already exist in that file. |
| literal `discard` | `discard-capture` | Writes no destination at all. |
| starts with `agent:` (e.g. `agent: Researcher`) | `agent-dispatched` | Routes the action through a Reviewer commission before the output surfaces. The Reviewer's pass/fail is logged as an Action Log entry chained to the original commission. |
| literal `today` | `file-capture-today` | Inserts a checkbox line as the last line of the daily note's `## Today's tasks` section (before the next heading) — never a blind end-of-file append like `file-capture`. No date prefix (the note's own filename/title is the date). Requires today's note (`<brain>/YYYY-MM-DD.md`) to already exist — this action never creates it. |

For `file-capture-today` cases: if today's note doesn't exist yet, this is an error exactly like the existing "destination directory doesn't exist" case for `file-capture` — reported, the row left untouched, doesn't block other rows in the same run, and doesn't count as done. Also note that `file-capture-today` rows DO get archived to `archive/inbox/<source>/` and marked `[x] (done)`, same as `file-capture` (only `agent-dispatched` skips those steps).

Execute also reads the Triage Plan's `rule` field (`triage.md`): for a `Pass A` row whose `rule` isn't `—`, the Action Log entry's `trigger` field becomes `Execute (Routine) — rule <rule_id>` instead of the bare `Execute (Routine)`, so a rule-driven action is traceable back to the specific rule that fired.

For `file-capture` and `discard-capture` cases: move the Raw Capture from `inbox/raw/<source>/` to `archive/inbox/<source>/` (collision-safe). `agent-dispatched` cases leave the Raw Capture in place for the Reviewer gate. For all cases, append an Action Log entry (`log_action.build_entry`/`append_entry`, dogfooding `action-log-schema.md`). Every run — whether or not any row was ticked — also bumps Execute's own row in `config/routine-state.md` (`heartbeat.bump`), so its Last-run state is accurate even though Execute is event-triggered and outside Heartbeat's overdue-checking (`routines.md`).

## Row state machine

A Triage Plan Row is a markdown task-list item (`triage.md`, ADR-0031), and its approve box has three states:

- `[ ]` — pending human review. Execute never touches it, ever.
- `[x]` — approved, ready to execute. Execute processes it this run.
- `[x] … (done)` — already executed. Left alone on any future run (idempotent — re-running Execute against a partially-worked plan never re-files or re-archives an already-done Row).

The `(done)` / `(dispatched)` marker is a **trailing suffix on the task line**, appended when the Row is executed — plain text, deliberately not a Tasks-plugin custom status, so a Plan stays readable in any markdown viewer with no plugin installed. Everything else on the line is left byte-for-byte alone, as are the Row's continuation lines (its preview and capture wikilink).

`scripts/execute.py`'s `ROW_RE` and `parse_plan_rows()` are the single owner of the Row shape; the pending-work nudge (`triage_pending.py`) and the Dashboard (`dashboard.py`) import them rather than re-deriving it, which is what keeps the three from drifting.

## Refusals

Execute refuses a Plan **whole** — with an error naming the offending row number, before filing, archiving, logging, running a hook or bumping its own Last-run — where a Row cannot be read as an actionable Row. A half-executed Plan whose remaining Rows are ambiguous is strictly worse than an untouched one, so the check runs against the Plan text before any Row is processed. Two things fail it:

**Blank destination.** A Row whose destination is empty or whitespace-only says nothing about where its capture goes. This is reachable from the ordinary correction gesture — editing a destination in place, which Obsidian autosaves mid-edit, so a scheduled Execute can see the cleared state. Left to run, it resolves to the Brain root and crashes the run part-way through, after earlier Rows have been filed, archived and logged but before the Plan is rewritten to record it — leaving the Plan and the Action Log disagreeing. Refusing before any side effect is the only outcome that keeps them consistent. (Compare the `unmatched` guard below, which is a per-row error rather than a refusal: an `unmatched` Row is merely undecided, whereas a blank destination also breaks grouping for the Rows around it.)

**Malformed Row block.** A Row's continuation lines must be exactly what Triage writes: at least two of them, of which exactly one is a bare `[[inbox/raw/…]]` capture link, and it is the last. Anything else — no capture link, two capture links, a lone line — cannot be read unambiguously, so Execute refuses instead of guessing which line is the capture.

That strictness exists because a preview is 60 characters of an *untrusted* capture body (Principle 10, `triage.md`), written into the Plan as its own line. Parsing therefore treats continuation lines as **content, never structure**: each Row's continuation lines are consumed with it in one forward pass and are never re-examined as possible Row starts, so a capture body shaped like a Row line is inert preview text rather than an injected Row. The arity rule closes the mirror image — a preview that is itself a bare wikilink can never be silently adopted as the Row's capture. Where the two readings are genuinely ambiguous, Execute fails loudly and never in favour of capture-derived text. Triage additionally escapes both shapes at write time, so a Plan written after ADR-0031 never contains them; the parser rule is what protects Plans that were hand-edited or written earlier.

A Row sitting under a heading that does not match its destination is **not** a refusal, and is not an error of any kind. The `## <destination>` heading is regenerated output, never read for comparison (ADR-0031): a Row executes to its own destination wherever it sits, and Execute's own write regroups it. That is what makes re-routing a capture a single in-place edit of the Row line.

## Grouping

Execute's write — the same one that stamps the `(done)`/`(dispatched)` markers — also re-groups the Plan: every Row block is placed under a `## <destination>` heading derived from that Row's own destination, headings that are needed are created, and headings left with nothing under them are dropped. Row blocks move verbatim, so tick state, executed markers, numbering and continuation lines are untouched. Grouping runs *after* the Rows have executed and never influences which Rows execute. `scripts/execute.py`'s `regroup_plan()` owns this and `scripts/triage.py` calls the same function on its own write, so the two cannot drift.

**Group order comes from the Rows, never from the headings.** Each group sits at the document position of its destination's *first* Row; Rows keep document order within their group; numbering is global and untouched. A heading has no say in ordering any more than it has in routing — it is output, never input (ADR-0031). In a well-grouped Plan the two orders agree, so this is invisible; where they disagree it is what stops a heading hand-edit from becoming a reorder. Renaming or deleting a heading leaves its group exactly where it was, with its Rows in the same order — the edit is reverted in place, and nothing the user was reading moves. Re-routing a Row to a destination that has no heading yet opens that group where the Row already sits, so re-routing the last Row still appends its group at the end. The one heading with no Rows to sort by is one kept alive by prose written under it; it holds its own document position, carrying that prose with it.

Re-grouping is **idempotent**, and has to be: it runs on every Execute whether or not anything was ticked, so a Plan that was not a fixed point would grow every night. Only text that reads back as what it was written as may be emitted — which is why a Row with a blank destination is held ungrouped above the groups rather than given a `## ` heading (nothing parses `## ` back as a heading), and why prose belonging to no heading is hoisted into the preamble rather than left below the groups.

## Plan completion

Once a run leaves zero rows in the `[ ]` state (every row is either not yet touched-but-none-are-`[ ]`, i.e. all have been ticked and executed across this or prior runs), the plan's frontmatter `status` flips from `pending` to `executed` and the file moves from `inbox/triage/` to `archive/triage/` (collision-safe). A plan with even one row still `[ ]` stays open in `inbox/triage/`.

## Per-source hooks (ticket 14)

After a `file-capture`/`file-capture-today`/`discard-capture` row's Raw
Capture is archived to `archive/inbox/<source>/`, Execute checks whether
that source has an `execute_hook.py` at
`<goals-os-library>/plugins/claude-code/skills/<source>/execute_hook.py`
(`resolve_library_path()` — explicit `--library-path` > `$GOALS_OS_LIBRARY_PATH`
> sibling-repo default). If it exists, it's called with `--config-dir`, the
archived capture's final path (`--raw-capture`), `--outcome` (`filed` for
either file variant, `discarded` for discard), and `--destination` (v1.3). If
it doesn't exist — true for every source except `email` today — this is a no-op.

`--destination` carries the row's own destination cell: the file path for a
`file-capture` row (heading fragment included, so `people/Example Person.md#🗣️ To Discuss`
arrives whole), the literal `today` for `file-capture-today`, and the literal
`discard` for a discard row — canonicalised, since `action_type_for()` matches
that cell case-insensitively. It is passed on **every** hook invocation, so a
hook reads it unconditionally and never branches on its absence.

The flag exists because a hook otherwise cannot know which destination the
human ticked, and would have to re-derive it — producing a second,
uncoordinated answer to a question the tick already settled. Whether a hook
*honours* the ticked destination or treats it as a hint it may override when
uninformative is the hook's own business; Execute only guarantees delivery.
Passing it costs Execute no source-specific knowledge: it forwards a string it
already parsed to choose the action type.

This is the only extension point for a source-specific side effect, and it
exists specifically so a source's own plugin code (which *does* know about
its external service) can act once Execute has already recorded a fully
human-confirmed outcome for that row — Execute itself never gains
source-specific knowledge or a source-specific action type. A hook failure
is logged to stderr but never blocks Execute or fails the row — the capture
has already been filed/discarded and archived by the time the hook runs.

`email`'s hook (ticket 14) archives the corresponding Gmail thread — this
was originally built to fire at *sweep* time instead (before any Triage
step), then deliberately moved here, per direct instruction, so the Gmail
mutation stays tied to the user's own tick on the row rather than firing the
moment mail is swept.

## Error handling

A row that can't be executed (Raw Capture missing, destination directory doesn't exist, destination still reads `unmatched`, — for `file-capture-today` specifically — today's daily note doesn't exist yet, or — for a `file#heading` destination specifically — the target file doesn't exist yet or exists but has no matching `## heading` section) is reported as an error and left untouched — it does not block the other rows in the same run, and does not count as "done" for the completion check.

## Adapter binding

See [`adapters/claude-code/skills/execute-triage/`](../adapters/claude-code/skills/execute-triage/).

## Non-goals (v1)

- No auto-execution regardless of confidence (Phase 5).
