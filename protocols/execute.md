# Protocol: Execute (v1.4)

Reads an approved Triage Plan and performs actions per ticked row. Supports generic, internal/reversible actions (`file-capture` or `discard-capture`) and `agent-dispatched` actions. For agent-dispatched actions, the output is QA'd by the Reviewer gate before surfacing. v1.1 (16/07/2026, `capture-source-plugins` map, ticket 09/15) generalizes `file-capture-today`'s insert-before-next-heading mechanic to any file — a `file#heading` destination (e.g. `people/Example Person.md#🗣️ To Discuss`) files section-targeted, not just to today's daily note. No new action type — see the `file-capture` row below. v1.2 (21/07/2026, ticket 14) adds an optional per-source post-action hook — see "Per-source hooks" below — with zero new action types; Execute itself stays fully generic. v1.3 (25/07/2026, `meeting-processing` component, ADR-0028) passes the ticked row's destination to that hook as `--destination`, so a hook honours the answer the user already gave by ticking rather than re-deriving it — see "Per-source hooks". Still zero new action types and still no source-specific knowledge: Execute forwards a string it already parsed. v1.4 (27/07/2026, ADR-0031) reads the new task-list Row shape and adds two whole-Plan refusals — see "Row state machine" and "Refusals" below.

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

Execute refuses a Plan **whole** — with an error naming the offending row number, before filing, archiving, logging, running a hook or bumping its own Last-run — in two cases. A half-executed Plan whose remaining Rows are ambiguous is strictly worse than an untouched one, so both checks run against the Plan text before any Row is processed.

**Heading disagreement.** A Plan groups its Rows under `## <destination>` headings for readability. The heading is presentation; the Row line's own destination is authoritative (ADR-0031). Where the two disagree, the Plan is saying two different things about where a capture goes, so Execute refuses rather than silently acting on the authoritative reading. A Row sitting under no heading at all cannot disagree with one and is left alone; the comparison ignores case, so `## discard` above a `Discard` destination is not a refusal.

**Malformed Row block.** A Row's continuation lines must be exactly what Triage writes: at least two of them, of which exactly one is a bare `[[inbox/raw/…]]` capture link, and it is the last. Anything else — no capture link, two capture links, a lone line — cannot be read unambiguously, so Execute refuses instead of guessing which line is the capture.

That strictness exists because a preview is 60 characters of an *untrusted* capture body (Principle 10, `triage.md`), written into the Plan as its own line. Parsing therefore treats continuation lines as **content, never structure**: each Row's continuation lines are consumed with it in one forward pass and are never re-examined as possible Row starts, so a capture body shaped like a Row line is inert preview text rather than an injected Row. The arity rule closes the mirror image — a preview that is itself a bare wikilink can never be silently adopted as the Row's capture. Where the two readings are genuinely ambiguous, Execute fails loudly and never in favour of capture-derived text. Triage additionally escapes both shapes at write time, so a Plan written after ADR-0031 never contains them; the parser rule is what protects Plans that were hand-edited or written earlier.

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
