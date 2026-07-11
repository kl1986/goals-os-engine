---
name: onboard
description: Run the Onboarding Protocol against a freshly cloned Brain — interviews the user for one Area, then materialises config/ and that Area. Safe to re-run per additional area. Use when a user has just cloned goals-os-brain-template and wants it turned into a working Brain.
allowed-tools:
  - Bash
  - AskUserQuestion
triggers:
  - onboard my brain
  - /onboard
---

# onboard

The Claude Code binding for `protocols/onboarding.md`. This skill runs the interview; all the actual file-writing is deterministic and lives in `scripts/onboard.py` — never write config or area files yourself, always go through the script so the no-clobber guarantee holds.

## What to do

1. Confirm the Brain path (the cloned `goals-os-brain-template` currently in use — ask if ambiguous).
2. Ask the user, one area at a time:
   - Which life area to set up first (e.g. "Work", "Health")?
   - What name they want for that area's Area agent (can just reuse the area name)?
   - Whether they want to override the autonomy-policy defaults — run `python3 scripts/onboard.py --help` to see the current `--review-window-days` / `--graduation-min-sessions` defaults; most users should take them as-is.
3. Run the script for that area:

```bash
python3 <path-to-goals-os-engine>/scripts/onboard.py \
  --brain "<path-to-brain>" \
  --area-name "<Area Name>" \
  --area-agent "<Agent Name>" \
  [--review-window-days N] [--graduation-min-sessions N]
```

4. Report back what was created vs skipped (the script prints both). If everything was skipped, tell the user this Brain — or this area — is already onboarded; nothing was touched.
5. Ask if they want to onboard another area now. If yes, repeat from step 2 with a new `--area-name`; `config/` will be skipped (already present) and only the new area's files get created.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the behaviour and the idempotency contract; `scripts/onboard.py` is the portable, runtime-agnostic implementation; this file is only the Claude Code binding. Any other Runtime implements the same interview shape over the same script.
