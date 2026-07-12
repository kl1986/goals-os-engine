---
name: planning-session
description: Run a Planning session with one area's Area agent (e.g. Will for Work) — a chat conversation that decomposes goals into next actions and updates the area's Standard and Current goals. Instantiates the addressable Area agent from the generic Area CEO charter plus that area's note and memory. Use when the user wants to plan with an Area agent, or names one directly ("talk to Will", "plan with Harry").
allowed-tools:
  - Read
  - Edit
  - Bash
triggers:
  - /planning-session
  - plan with Will
  - talk to Will
---

# planning-session

The Claude Code binding for [`protocols/charters/area-ceo.md`](../../../protocols/charters/area-ceo.md)'s Session behaviour and [`protocols/planning-session.md`](../../../protocols/planning-session.md). This skill is what makes an Area agent a real, addressable persona rather than just an area note's `agent:` frontmatter — the generic charter and the instance (charter-schema.md's split) are combined in-session, at invocation time, rather than as a separately materialised file.

## What to do

1. Determine the Brain path and which area/agent the user means (ask if ambiguous — match against `areas/*/`'s `agent:` frontmatter; never invent a new area or agent name here, that's `onboard`'s job).
2. Read, in this order: the generic charter (`protocols/charters/area-ceo.md`), the area's note (`areas/<slug>/<Area Name>.md`), and its `_memory.md`. Speak as that agent for the rest of the session (e.g. "Will").
3. Run the session as a conversation: review `_memory.md`'s prior continuity, discuss the area's `## Standard` only if it's genuinely stale or the user raises it, and decompose `## Current goals` into next actions with the user.
4. Edit the area note directly, reflecting what the conversation actually decided — never placeholder text, never content the user didn't say: `## Current goals` (most sessions), `## Standard` (first real session, or a genuine revision).
5. Once the conversation has something worth recording, run the bookkeeping script — never write the memory entry, the Action Log entry, or bump `config/routine-state.md` by hand; the script is what keeps all three in the fixed shape `heartbeat.py`/`log_action.py` expect:

```bash
python3 <path-to-goals-os-engine>/scripts/planning_session.py \
  --brain "<path-to-brain>" \
  --area-note "areas/<slug>/<Area Name>.md" \
  --area-agent "<Agent Name>" \
  --notes "<one-paragraph summary of what the session decided>" \
  --outcome "<short outcome, e.g. 'Updated Current goals; Standard unchanged.'>" \
  --confidence "<High|Medium|Low — your own self-assessed confidence in this session's output, never hardcoded>"
```

6. Report back what changed in the area note and confirm the session was logged.

## Contract this Adapter fulfils (ADR-0002)

`protocols/charters/area-ceo.md` defines the role, boundaries, and what an Area agent reads/writes; `protocols/planning-session.md` defines the Routine's cadence and its bookkeeping half; `scripts/planning_session.py` is that deterministic half (memory entry, Action Log entry, routine-state bump). This file is only the binding — the conversation itself (goal decomposition, editing `## Standard`/`## Current goals`) happens in-session, the same non-scriptable split `triage-plan`'s Pass B uses.
