# Goals OS

Glossary for Goals OS — the clean-slate v2 of the second brain: a distributable, multi-agent, self-improving personal operating system built on plain markdown, whose purpose is getting the user to their goals with an increasing share of the work done away from keyboard. This context is distinct from the current vault's system glossary (`Vault/_System/CONTEXT.md`), which describes the v1 prototype.

## Language

**Engine**:
The distributable core — protocols, schemas, core routines, and runtime adapters. Contains zero user data; upgrading it never touches a user's Brain.
_Avoid_: System repo, core, framework

**Library**:
The repo of optional, individually installable plugins and skills that extend the Engine.
_Avoid_: Plugin repo, marketplace (unless referring to the mechanism)

**Brain**:
A user's private repo holding everything personal: the knowledge base, goals, agent memories, routing rules, audit logs, and config overrides. Forked/cloned from a Brain Template. One repo = one person's whole life.
_Avoid_: Vault (that's the Obsidian container), knowledge base (that's just the content layer — Wiki + curated layer; the Brain also holds memories, routing rules, logs, and config)

**Brain Template**:
The blank, example-populated starting Brain a new user clones to begin.

**Runtime**:
An agentic CLI capable of executing the Engine's protocols (e.g. Claude Code, Codex CLI, Gemini CLI). The Engine is runtime-agnostic; each runtime is driven through an Adapter.

**Adapter**:
The thin mapping layer that binds the Engine's protocols onto one Runtime (its skill/agent/hook formats). Claude Code is the reference Adapter.

**Protocol**:
A markdown-defined, runtime-independent specification of a behaviour (e.g. triage, weekly review). Protocols are what the Engine ships; Adapters make them executable.

## Agents

**System agent**:
A singleton agent shipped by the Engine that maintains the machine itself: the EA, the Librarian, and the Coach.
_Avoid_: Specialist agent, top-level role

**EA**:
The System agent that is the user's default front door — captures, triages, routes, and delegates everything inbound. Optimises throughput.
_Avoid_: Jarvis (informal only), assistant

**Librarian**:
The System agent that synthesises knowledge from raw inputs into the Wiki and runs the self-improvement loop over the system's own definitions.

**Coach**:
The System agent that optimises direction: reviews goals, progress, and attention across all areas and gives critical feedback. Advisory-only.

**Area agent**:
A persistent agent instantiated in the user's Brain from the Engine's generic Area CEO charter — one per life area. Owns that area's goals, strategy, and memory; directs Capability agents, never executes.
_Avoid_: Area Lead (v1 term), CEO alone (ambiguous)

**Capability agent**:
An ephemeral, tool-scoped worker (Researcher, Analyst, Writer, Reviewer, Coder…) commissioned by System or Area agents. Extendable via the Library.
_Avoid_: Worker, subagent (that's a runtime mechanism)

**Charter**:
The markdown spec defining an agent's role, tool scope, and delegation relationships. Every System, Area, and Capability agent has exactly one.

**Generic charter**:
An Engine-owned Charter defining a role once for every Brain (e.g. "the Area CEO charter," "the EA charter").

**Instance**:
A Brain-owned Charter materialised from a generic charter for one named, concrete agent — e.g. `Will`, materialised from the Area CEO generic charter for the Work area. Currently only Area agents have instances; System and Capability agents are addressed directly from their generic charter.
_Avoid_: Charter alone when the generic/instance distinction matters — be specific.

## Learning

**Action Log**:
The single append-only record in the Brain to which every agent action writes a structured entry. The audit trail and the substrate the learning loop feeds on.
_Avoid_: Dashboard, delegation log

**Feedback**:
A user judgement written into an Action Log entry's feedback slot — validation, or a correction stating what the user would have wanted.

**Action type**:
A named category of agent action (e.g. "file email", "send holding reply") that carries a risk tier and an autonomy level. Graduation operates on action types, never individual actions.

**Risk tier**:
An action type's classification as *internal & reversible* or *outward-facing / hard-to-reverse*. Determines whether silence can count as validation.

**Graduation**:
The promotion of an action type from confirm-first to autonomous after sufficient validated feedback; any correction demotes it back.
_Avoid_: Auto-execute (v1 term)

## Knowledge

**Raw Capture**:
An un-synthesised input (voice transcript, email, web clip, note) stamped with frontmatter and stored immutably as markdown. The ground truth everything else derives from.

**Wiki**:
The machine-compiled, concept-organised knowledge layer. A pure function of Raw sources plus validated feedback — never directly human-edited.
_Avoid_: Knowledge base (that's the content layer as a whole — Wiki + curated layer; say Wiki specifically)

**Curated layer**:
The human-authored layer of decisions, standards, and goals per area. The machine reads it; only the user writes it. Boundary test: decided it → curated; learned it → Wiki.

**Resynthesis guarantee**:
The Engine invariant that the Wiki can be dropped and rebuilt from Raw Captures + feedback at any time, by any model, with no human work lost. A safety property, not a determinism claim — rebuilds may differ in wording.

## Operations

**Routine**:
A recurring behaviour declared in the Engine's Routine manifest (name, protocol, cadence, risk tier), with last-run state recorded in the Brain.

**Heartbeat**:
The due-check at every session start that finds overdue Routines and nudges or auto-runs them per their autonomy level.

**Tune**:
The Librarian's report-only loop proposing upgrades to agent and skill definitions, grounded in cited knowledge. Brain-owned targets apply locally on approval; Engine-owned targets become upstream contributions.

**Upgrade routine**:
The periodic external-research cycle that scans new releases/approaches, distils findings into the Brain's knowledge base, and feeds Tune.

**AFK ratio**:
Share of actions executed autonomously rather than confirm-first — the primary fitness metric, alongside cycle time, goal progress, and review debt/correction rate.
