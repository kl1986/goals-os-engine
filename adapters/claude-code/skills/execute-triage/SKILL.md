---
name: execute-triage
description: Execute a Triage Plan's [x]-ticked rows — files or discards each Raw Capture, archives it, and logs an Action Log entry. Never touches [ ] rows. Use when the user has ticked rows in a Triage Plan and wants them acted on.
allowed-tools:
  - Bash
triggers:
  - execute my triage plan
  - /execute-triage
---

# execute-triage

The Claude Code binding for `protocols/execute.md`. All the logic — which rows are ticked, how `file-capture`/`discard-capture` behave, archiving, Action Log entries, and plan completion — lives in `scripts/execute.py`. This skill only calls it and relays the result.

`execute.py` also checks, per row, whether that row's source has an
`execute_hook.py` in its `goals-os-library` plugin folder — if so, it's
called right after the capture is filed/discarded and archived, with the
outcome. This is how a source-specific external-service side effect can run
(e.g. `email`'s `execute_hook.py` archives the Gmail thread once its Triage
row is actually acted on, ticket 14) without `execute.py` itself knowing
anything about Gmail or any other plugin. Most sources have no hook, so this
is a silent no-op for them. `--config-dir`/`--library-path` (or
`$GOALS_OS_LIBRARY_PATH`) override the defaults if a Brain's layout ever
deviates from the standard `<brain>/config` + sibling-repo convention — the
plain invocation below normally needs neither.

## What to do

1. Determine the Brain path and which Triage Plan to run — a specific path, or sweep `inbox/triage/*.md` for files with any `[x]` rows if the user doesn't name one (ask if ambiguous which plan they mean).
2. For each plan, run:

```bash
python3 <path-to-goals-os-engine>/scripts/execute.py --brain "<path-to-brain>" --plan "<path-to-plan-or-relative-to-brain>"
```

3. Report back: how many rows were filed, how many discarded, how many dispatched, and relay any errors verbatim (a row referencing a missing Raw Capture, a destination directory that doesn't exist, a still-`unmatched` destination, or — for a `file#heading` destination like a Person Hub row — the target file or the named heading not existing — none of these crash the run, but they need the user's attention).
   - One error is different: if a Row can't be read as an actionable Row — its block is malformed (no capture wikilink, two of them, or a lone continuation line), or its destination is blank — `execute.py` **refuses the whole Plan**, exits non-zero, and names the offending row number. Nothing was acted on. Relay it and offer to repair that Row — do not re-run until it's fixed. A blank destination usually means a correction was saved half-typed; ask what the destination should be rather than guessing.

4. If there are any `agent-dispatched` rows, you MUST capture the `log_id` printed in the script output (e.g. `Dispatched row 1 (inbox/raw/x.md) with log_id: a1b2c3d4`). Then invoke the `commission` skill to dispatch them to the Reviewer gate. Frame a clear task, wait for the Reviewer's pass/fail, and append the result as a chained Action Log entry **by passing the captured `log_id` to the commission skill as the parent reference**. Then, if it passed, update that Row's trailing marker in the Triage Plan from `(dispatched)` to `(done)` — the marker is a suffix on the task line, so change only that word and leave the rest of the line and the Row's continuation lines alone.
5. If the plan's every row is now done, tell the user it's been archived to `archive/triage/`.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the two action types and the row state machine; `scripts/execute.py` is the portable, runtime-agnostic implementation; this file is only the Claude Code binding. This skill never invents a third action type or files something into a destination the plan didn't already name — that's the Protocol's job to define, not this Adapter's to improvise.
