---
name: commission
description: Commission a Capability agent (Researcher, Analyst, Writer, Reviewer, Coder) to perform a scoped task. Use when you need legwork done that exceeds your own boundaries, such as web searching, drafting a document, analyzing data, or writing code.
allowed-tools:
  - Bash
  - Read
  - Agent
triggers:
  - /commission
  - commission a capability agent
---

# commission

The Claude Code binding for [`protocols/commissioning.md`](../../../protocols/commissioning.md). This skill enacts the PRD §5 requirement for Capability agents by spawning a scoped subagent context.

## What to do

1. **Verify Role:** Check which Capability agent role is requested (Researcher, Analyst, Writer, Reviewer, or Coder). If missing or ambiguous, ask the user or the commissioning agent.
2. **Determine Model Routing:** Read `config/model-routing.md` in the Brain to see which LLM to use. For example, map `Analyst` and `Coder` to `reasoning-heavy` (if defined), and `Researcher`, `Writer`, `Reviewer` to `default`.
3. **Execute Subagent Task:** Invoke a subagent process to fulfill the task using Claude Code's native `Agent` tool. 
   - Set the `subagent_type` to the requested role in lowercase (e.g., `researcher`, `coder`). The harness will automatically load the allowed tools for that agent from `.claude/agents/<role>.md`.
   - Pass the model resolved in step 2.
   - Provide the task framing and constraints as the prompt to the `Agent` tool.
4. **Log the Commission:** Once the task is completed and output is ready, you MUST log the commission using the deterministic script so that the Action Log records the event properly:
   ```bash
   python3 <path-to-goals-os-engine>/scripts/commission.py \
     --brain "<path-to-brain>" \
     --commissioning-agent "<Your Agent Name, e.g. EA or Will>" \
     --capability-role "<Role Name>" \
     --task-summary "<One sentence summary of the prompt>" \
     --outcome "<Short outcome summary>" \
     --confidence "<High|Medium|Low>"
   ```
5. **Return Output:** Present the subagent's findings or output back to the user/session.

## Contract this Adapter fulfils

`protocols/commissioning.md` defines the boundaries, task framing, and logging rules. This skill is the mechanism that enacts it in Claude Code, ensuring that the work is performed under the correct scope and recorded against the commissioning agent's name.
