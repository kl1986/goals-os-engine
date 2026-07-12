# Protocol: Commissioning

The generic contract for a System or Area agent handing a task to a Capability agent and receiving its output (PRD §5). Until this protocol, every agent/skill ran against the entire toolset. This mechanism ensures strict tool-scoping and ephemeral lifetimes for the leaf-node workers (Researcher, Analyst, Writer, Reviewer, Coder).

## The Contract

When a System agent (e.g., EA) or an Area agent (e.g., Will for Work) reaches a point in its session where it needs legwork (e.g., running a search, drafting text, reviewing a plan), it **must not** execute that work directly. Instead, it commissions a Capability agent.

### 1. Task Framing

The commissioning agent must provide a structured framing to the Capability agent. This framing includes:
- **Target Role:** Which capability agent is being commissioned (e.g., "Researcher", "Writer").
- **Task Description:** A clear, self-contained prompt detailing what the agent must do. It cannot rely on the commissioning agent's memory or context unless explicitly included in this prompt.
- **Constraints:** Any specific bounds on the output (format, length, specific files to check).

### 2. Tool-Scope Enforcement

The commissioned Capability agent inherits *only* the tool permissions granted by its specific charter (`protocols/charters/capability/*.md`).
- A `Researcher` cannot write files.
- A `Writer` cannot execute bash scripts.
- A `Coder` is restricted to the `Code/` directory.

The runtime adapter (e.g., Claude Code) is responsible for enforcing these limits (e.g., by omitting `Edit` tools from the subagent's allowed tools, or instructing the model via system prompt).

### 3. Execution and Return

- **Ephemeral Context:** The Capability agent starts with a blank context, reads its generic charter and the task framing, executes its tools, and produces a final output.
- **Return to Sender:** The output is returned directly to the commissioning agent's session. The Capability agent's session is then destroyed. Nothing persists in memory.

### 4. Action Log Logging (ADR-0005)

Every commission event is appended to the Brain's Action Log.
- **Actor:** The Capability agent noted with its commissioner, e.g., `Researcher (via Will)`. Always the executor, never the approver.
- **Action Type:** `Commission Capability Agent`
- **Details:** The name of the capability role and a summary of the task.

This ensures accountability remains with the persistent agents that direct the system.

## Runtime Binding

This protocol is enacted by the runtime adapter (e.g., the `commission` skill in Claude Code). The adapter:
1. Reads `config/model-routing.md` to select the LLM for the task.
2. Constructs the subagent environment or prompt.
3. Invokes the subagent.
4. Executes `scripts/commission.py` to record the event in the Action Log.
5. Returns the subagent's output to the commissioning agent's chat context.
