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

## What to do

1. Determine the Brain path and which Triage Plan to run — a specific path, or sweep `inbox/triage/*.md` for files with any `[x]` rows if the user doesn't name one (ask if ambiguous which plan they mean).
2. For each plan, run:

```bash
python3 <path-to-goals-os-engine>/scripts/execute.py --brain "<path-to-brain>" --plan "<path-to-plan-or-relative-to-brain>"
```

3. Report back: how many rows were filed, how many discarded, how many dispatched, and relay any errors verbatim (a row referencing a missing Raw Capture, a destination directory that doesn't exist, or a still-`unmatched` destination — none of these crash the run, but they need the user's attention). 
4. If there are any `agent-dispatched` rows, you MUST capture the `log_id` printed in the script output (e.g. `Dispatched row 1 (inbox/raw/x.md) with log_id: a1b2c3d4`). Then invoke the `commission` skill to dispatch them to the Reviewer gate. Frame a clear task, wait for the Reviewer's pass/fail, and append the result as a chained Action Log entry **by passing the captured `log_id` to the commission skill as the parent reference**. Then update the row in the Triage Plan from `[x] (dispatched)` to `[x] (done)` if it passed.
5. If the plan's every row is now done, tell the user it's been archived to `archive/triage/`.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the two action types and the row state machine; `scripts/execute.py` is the portable, runtime-agnostic implementation; this file is only the Claude Code binding. This skill never invents a third action type or files something into a destination the plan didn't already name — that's the Protocol's job to define, not this Adapter's to improvise.
