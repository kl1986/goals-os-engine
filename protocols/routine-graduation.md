# Protocol: Graduation check (v0)

The Routine that fires the graduation engine (ADR-0006, `scripts/graduation.py`, ticket 03) and the feedback-classification pass (ADR-0005's `feedback` slot, `protocols/action-log-schema.md`, ticket 01) — the payoff of the "Phase 5" deferral `protocols/routines.md` and `heartbeat.py` both named explicitly. Piggybacks on the existing Heartbeat due-checker (ADR-0007) rather than inventing a new due-checking mechanism: `scripts/heartbeat.py` needs **zero code changes** — it's a generic, pure due-checker, and adding this Routine's manifest row is all `compute_overdue()` needs to flag it when overdue.

## Two-pass shape

One combined Routine, **"Graduation check,"** cadence `daily` — internally two ordered passes, mirroring Triage's Pass A/B precedent exactly (`protocols/triage.md`) rather than proliferating manifest rows for steps that always run together in a fixed order:

- **Pass (i) — feedback classification.** Deterministic *detection* (`scripts/graduation.py`'s `find_unclassified_feedback()`) finds any Action Log entry whose `feedback` field isn't one of the three canonical shapes (`—` / `validated` / `corrected — <detail>`). The actual classification *judgement* — is this hand-written comment an approval or a correction? — is genuine model reasoning, done in-session by this Routine's Adapter binding (same shape as Triage's in-session Pass B). The decision is written back **in place**, into the existing entry's own `feedback:` line, via `scripts/graduation_routine.py`'s `write_feedback_classification()`. **No new Action Log entry is created for this step** — normalizing an existing field is not itself a loggable action (ticket 04's resolution); logging every field-normalization would be noisy for something with no real-world consequence beyond tidying already-logged data.

- **Pass (ii) — graduation counting.** Fully deterministic, zero LLM calls: `scripts/graduation.py`'s `compute_graduation_state()` re-evaluates every non-fixed action type in `config/action-types.md` against the Action Log, using `config/autonomy-policy.md`'s thresholds. Any `graduate`/`demote` decision is acted on by `scripts/graduation_routine.py`'s `apply_graduation_changes()`: it flips that type's `Autonomy level` cell in `config/action-types.md` (`confirm-first` ↔ `autonomous`; no schema change) **and** appends a new Action Log entry (`graduate-action-type` / `demote-action-type`) — a real autonomy change deserves the same audit trail as any other action.

## Boundary `outcome` format (fixed — do not drift)

Every `graduate-action-type` / `demote-action-type` entry's `outcome` field must start with the target type in backticks, the direction, and a parenthesized reason:

```
`file-capture` → autonomous (5 qualifying instances across 4 distinct days)
`file-capture` → confirm-first (corrected feedback on entry a1b2c3d4 (2026-07-14 09:12))
```

`scripts/graduation.py`'s `_find_last_boundary()` parses this exact shape (regex `` `([\w-]+)` → (autonomous|confirm-first) ``) to find each type's most recent graduate/demote boundary and count only entries since it. `scripts/graduation_routine.py`'s `apply_graduation_changes()` is the single write path that stamps this format — if a future change ever writes a graduate/demote entry any other way, graduation counting silently breaks (it would count since Brain inception instead of since the real boundary). There is deliberately only one code path that writes these entries.

## Belt-and-suspenders exclusion

`scripts/graduation.py`'s `compute_graduation_state()` already skips any action type whose `Autonomy level` is the exact literal `autonomous (fixed)` — today `graduate-action-type`, `demote-action-type`, and `propose-rule-diff` themselves (evaluating them would be circular: a correction on a graduation-decision entry can't be allowed to demote the graduation mechanism). `scripts/graduation_routine.py`'s `apply_graduation_changes()` carries a **second, independent** check against the same three names (`EXCLUDED_FROM_WRITE`), applied at the point side effects actually get written — not a duplicate of the engine's own exclusion, but a guard against the engine's exclusion ever having a bug. Neither `config/action-types.md` nor the Action Log is ever written for one of these three types by this Routine, regardless of what `compute_graduation_state()`'s output says.

## Execution trigger — fully automatic

Zero confirmation for both passes — no judgement call needs a human. Pass (i)'s in-session classification step never blocks on a live question (this Routine runs offline, unattended): if the free text isn't confidently either `validated` or `corrected`, it's written back as `—` ("not yet reviewed") rather than guessed. Pass (ii) is pure counting/date arithmetic. This matches **Version Control's** silent-automatic pattern (`protocols/version-control.md`) — not **Triage's** confirm-first Plan pattern, which surfaces a document for a human to tick. Nothing this Routine does waits for approval.

## No-op behaviour

Zero visible output and zero new Action Log entries if neither pass finds anything to do — matches Version Control's existing silent no-op-on-clean-tree pattern exactly. The one write that always happens, success or no-op, is this Routine's own `Graduation check` row in `config/routine-state.md` (bumped via `heartbeat.bump()`) — the Routine ran and checked, even when there was nothing to change, so Heartbeat's due-check reflects reality. This mirrors Triage's own precedent of bumping its `routine-state.md` row unconditionally.

## Ordering

Runs **before Triage** in session-start sequence. `protocols/routines.md`'s manifest table lists the `Graduation check` row immediately before the `Triage` row for this reason. A type that graduates mid-Heartbeat should be able to auto-execute matching high-confidence items of that type in the *same* session's Triage/Execute pass, rather than sitting idle for an entire extra session (PRD §6).

## Adapter binding

See [`adapters/claude-code/skills/graduation-check/`](../adapters/claude-code/skills/graduation-check/). `scripts/graduation.py` (unmodified, ticket 03) is the pure decision engine; `scripts/graduation_routine.py` is this ticket's deterministic write side (the Pass-(i) field overwrite, and Pass (ii)'s config edit + Action Log entries + routine-state bump); the Adapter binding supplies only Pass (i)'s in-session classification judgement and calls both scripts in the right order — it performs zero judgement of its own in Pass (ii), and zero confirmation in either pass.

## Non-goals (v0)

- No rule-learning / pattern-detection here — a recurring-correction pattern proposing a routing-rule diff is a separate, weekly, LLM-assisted batch pass (`protocols/rule-learning.md`, Phase 5 ticket 05), deliberately not folded into this daily silent Routine.
- No real scheduler (cron/launchd) binding — this Routine fires via the Heartbeat nudge (a manually invocable session-start check) same as every other Routine; a real scheduler binding is a later Adapter-layer addition (ADR-0007 layer 2).
- No EA charter wiring in this ticket — `protocols/charters/ea.md`'s Routing table isn't extended to dispatch this Routine by name; it fires from the Heartbeat nudge or direct invocation, same as `version-control` today.
