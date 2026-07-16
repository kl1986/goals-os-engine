---
name: triage-plan
description: Classify un-triaged Raw Captures for one source into a Triage Plan file — Pass A via script (deterministic rule match), Pass B in-session for anything unmatched. Writes only inside inbox/triage/. Use when the user wants to triage captures for a source.
allowed-tools:
  - Bash
  - Read
  - Edit
triggers:
  - triage my captures
  - /triage-plan
---

# triage-plan

The Claude Code binding for `protocols/triage.md`. Principle 10 (classify-only) is enforced here structurally: this skill's `allowed-tools` let it edit files only under `inbox/triage/` — never `inbox/raw/`, never a destination area/project file. If a task seems to need writing anywhere else, that's Execute's job (`execute-triage` skill), not this one.

## What to do

1. Determine the Brain path and the `--source` to triage (ask if ambiguous).
2. Run Pass A:

```bash
python3 <path-to-goals-os-engine>/scripts/triage.py --brain "<path-to-brain>" --source "<source>"
```

This writes/updates `inbox/triage/{date}-{source}.md`. It reports how many captures were routed (Pass A) vs left `unmatched` (Pass B pending).

3. If any rows are `Pass B | unmatched`, open the plan file and classify each one yourself, in-session: read the capture (follow its `[[inbox/raw/...]]` link if the preview isn't enough), decide a `destination` and a `confidence`, and edit that row's `destination` and `confidence` cells directly. **Never tick the `approve` box yourself** — that's the user's call, not this skill's.
   - Destination is normally an existing file under `areas/` or `projects/` — never invent a new area/project — or the literal word `discard` if it isn't worth keeping.
   - Also check whether the capture is **person-specific** (raising something with someone, or waiting on them for something) — read `people/_aliases.md` and the `people/` folder listing as context, same as you'd check `areas/`/`projects/`. If so, propose a section-targeted destination instead: `people/<Full Name>.md#🗣️ To Discuss` for outbound framing ("ask Kat about X", "raise Y with Kat") or `people/<Full Name>.md#⏳ Waiting For` for inbound framing ("waiting on Kat for Y", "Kat owes me X"). If the name is ambiguous or you're unsure of the match, make your best guess — the user's tick is the confirm-first gate; a wrong guess just gets corrected by them editing the `destination` cell before ticking.
4. Report back: how many rows are Pass A vs Pass B, and ask the user to review and tick the ones they approve before running `execute-triage`.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the two-pass split and the classify-only constraint; `scripts/triage.py` implements Pass A and the idempotent plan-writing; this file does Pass B classification and the plan-editing, scoped by `allowed-tools` so it structurally cannot execute anything itself.
