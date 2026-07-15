---
name: graduation-check
description: Fully automatic Routine — classifies any non-canonical Action Log feedback (Pass i) and re-evaluates every action type's graduation/demotion state (Pass ii), flipping config/action-types.md and logging any change. Zero confirmation, no Plan to approve. Runs before Triage in session-start sequence. Use when Heartbeat flags "Graduation check" as overdue, or when the user asks to run a graduation check directly.
allowed-tools:
  - Bash
  - Read
triggers:
  - graduation check
  - /graduation-check
---

# graduation-check

The Claude Code binding for `protocols/routine-graduation.md`. Unlike `triage-plan` (which surfaces a Plan file for a human to tick) this Routine is **fully automatic — it never asks for confirmation and never produces a document awaiting approval.** It matches `version-control`'s silent-automatic shape, not `triage-plan`'s confirm-first one. Every write happens through `scripts/graduation.py` (decisions) and `scripts/graduation_routine.py` (side effects) — never a direct hand-edit of `config/action-types.md` or a log file, so the write format stays exactly what those scripts expect.

## What to do

1. Determine the Brain path (ask if ambiguous; never guess).

2. **Pass (i) — feedback classification.** Find anything non-canonical:

```bash
python3 <path-to-goals-os-engine>/scripts/graduation.py --brain "<path-to-brain>"
```

   This prints every Action Log entry whose `feedback` field isn't `—`, `validated`, or `corrected — <detail>` (deterministic detection only — no judgement here). For each one:
   - Read the entry (its `action`, `input link`, and the free-text `feedback` itself) to judge whether the user meant an approval or a correction.
   - **Never ask the user a clarifying question — this pass runs offline, unattended, with no live conversation to fall back on.** If you can't confidently tell `validated` from `corrected`, write `—` ("not yet reviewed") rather than guessing between the two. A `corrected` classification must carry a free-text detail payload (`corrected — <what should have happened>`), never bare.
   - Write the decision back with the deterministic script — never hand-edit the log file directly, so the write stays mechanical and format-safe:

```bash
python3 <path-to-goals-os-engine>/scripts/graduation_routine.py --brain "<path-to-brain>" classify \
  --log-file "<path from graduation.py's output>" --entry-id "<entry-id>" --value "<validated|corrected — detail|—>"
```

   This overwrites only that entry's `feedback:` line in place. **No Action Log entry is created for this step** — normalizing an existing entry's own field is not itself a loggable action (ticket 04's resolution).

3. **Pass (ii) — graduation counting.** Fully deterministic, no LLM judgement — run this unconditionally, even if Pass (i) found nothing to classify:

```bash
python3 <path-to-goals-os-engine>/scripts/graduation_routine.py --brain "<path-to-brain>" count
```

   This re-evaluates every action type's graduation/demotion state (`scripts/graduation.py`'s `compute_graduation_state()`, reused unmodified), flips `config/action-types.md`'s `Autonomy level` cell for anything that crossed a threshold, appends a `graduate-action-type`/`demote-action-type` Action Log entry for each real change, and bumps this Routine's own row in `config/routine-state.md` — regardless of outcome, so Heartbeat's due-check reflects that the check actually ran.

4. Report back plainly, in one or two lines: if both passes found nothing, say so ("Graduation check: nothing to report — feedback and autonomy state are unchanged."). Otherwise state how many entries were classified (a count, not the raw text) and which action types graduated or demoted, with the reason each script reported.

## Contract this Adapter fulfils (ADR-0002)

`protocols/routine-graduation.md` defines the two-pass shape, the fixed `outcome` format, and the belt-and-suspenders exclusion; `scripts/graduation.py` (ticket 03, unmodified) is the pure decision engine for both passes; `scripts/graduation_routine.py` is this ticket's deterministic write side (the Pass-(i) field overwrite, and Pass (ii)'s config edit, Action Log entries, and routine-state bump); this file is only the Claude Code binding that supplies Pass (i)'s in-session judgement and calls both scripts in order. It performs zero judgement of its own in Pass (ii), and zero confirmation in either pass — this Routine never waits on the user, unlike `triage-plan`.
