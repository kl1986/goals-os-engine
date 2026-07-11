---
name: log-action
description: Append a schema-valid Action Log entry to a Brain's log/ folder, per the Engine's action-log-schema Protocol (v0). Use whenever an agent takes an action in a Brain and needs to record it in the audit trail.
allowed-tools:
  - Bash
triggers:
  - log this action
  - /log-action
---

# log-action

The Claude Code binding for `protocols/action-log-schema.md`. This skill is the thin Adapter layer only — the schema itself, field semantics, and the sharding contingency all live in the Protocol doc, not here. Read that file first if the fields below are unclear.

## What to do

1. Determine the Brain path — the cloned Brain repo currently in use (ask if ambiguous; never guess).
2. Gather the required fields from context: `actor` (you, or the agent that acted), `trigger` (what caused this — a Routine, a user instruction, a delegation), `action-type` (the named category), `action` (one-line description), `confidence` (`High`/`Medium`/`Low`), `outcome` (what happened). `input-link` and `feedback` are optional — omit to default to `—`.
3. Run the Engine's script, which does the actual append (no LLM writes to the log file directly — deterministic, git-diffable):

```bash
python3 <path-to-goals-os-engine>/scripts/log_action.py \
  --brain "<path-to-brain>" \
  --actor "<actor>" \
  --trigger "<trigger>" \
  --action-type "<action-type>" \
  --action "<action>" \
  --confidence "<High|Medium|Low>" \
  --outcome "<outcome>" \
  --input-link "<input-link-or-omit>"
```

4. Confirm back to the user which `log/YYYY-MM-DD.md` file received the entry.

## Contract this Adapter fulfils (ADR-0002)

The Protocol is the spec; this skill is the mapping onto Claude Code's native skill format. Any other Runtime (Codex CLI, Gemini CLI) implements the same `scripts/log_action.py` call through its own equivalent binding — the script, not this file, is the portable part.
