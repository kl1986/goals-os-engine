# Protocol: Onboarding (v0)

Turns a freshly cloned, blank Brain Template into a working, personalised Brain — the mechanism ADR-0004 promises as "install = plugin + clone + onboarding run." Runnable any number of times: once per area, or again after a crash, without ever clobbering what's already there.

## What it does

1. **Interview** (the Adapter's job, not the script) — ask the user:
   - Which life area do they want an Area agent for, to start? (Onboarding is re-runnable per area — more can be added later, one run each.)
   - What name/tone for that Area agent? (The Engine ships a generic Area CEO charter; the name and tone are Brain content, chosen here — see `CONTEXT.md`'s note that "Will/Harry/etc. are Kelvin's Brain content, not product.")
   - Any autonomy-policy overrides to the defaults — review window, graduation minimum sessions (ADR-0006)?
2. **Materialise** (`scripts/onboard.py`, deterministic, no LLM judgement) — for the Brain passed in:
   - `config/model-routing.md`, `config/autonomy-policy.md`, `config/routine-state.md` — created only if missing.
   - `areas/<slug>/<Area Name>.md` + `areas/<slug>/_memory.md` for the requested area — created only if missing.
3. **Record** — the run itself appends an Action Log entry (dogfoods `action-log-schema.md`, ticket 03), so onboarding is visible in the same audit trail as everything else the Brain will ever log. `actor` is `EA` — onboarding has no dedicated agent identity of its own, and `action-log-schema.md`'s `actor` field is a closed taxonomy (System/Area/Capability agent); a Protocol's own name is never a valid `actor` (corrected 12/07/2026 — earlier onboarding runs had logged `actor: Onboarding Protocol`, fixed retroactively in the Brain's log).

## Idempotency contract

`scripts/onboard.py` never overwrites a file that already exists. Re-running onboarding — by accident, to add a second area, or because a Runtime crashed mid-run — is always safe: existing config and areas are left exactly as the user last edited them; only the pieces that are still missing get created. The script reports what it created vs skipped so the Adapter can relay that back to the user.

## Adapter binding

See [`adapters/claude-code/skills/onboard/`](../adapters/claude-code/skills/onboard/) for the Claude Code binding — it runs the interview conversationally, then calls the script once per requested area.

## Non-goals (v0)

- No multi-area batch onboarding in one script call — one area per invocation; the Adapter loops if the user wants several up front.
- No uniqueness check on Area agent names across the Brain — a human editing two areas with the same agent name notices quickly; not worth machinery yet.
- No un-onboarding / reset command — deleting the generated files by hand and re-running is sufficient for v0.
