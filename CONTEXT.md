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

## Direction

**Goal**:
A finite outcome the user wants to achieve, with a success condition and a horizon. Each Goal has exactly one owning Area; Projects, Tickets, and other Areas may contribute without co-owning it. A Goal can be achieved, missed, paused, or abandoned.
_Avoid_: using Goal for an ongoing habit, baseline, or quality bar

**Goal status**:
The evidence-backed assessment of an active Goal's trajectory: `on-track`, `at-risk`, or `off-track`. It is accompanied by evidence and a next review date, rather than a percentage-complete estimate.
_Avoid_: percentage progress when no objective completion measure exists

**Project**:
A bounded, coordinated body of work that may contribute to one or more Goals, including Goals owned by other Areas. A Project never gains ownership of a Goal by contributing to it.

**Ticket**:
A trackable unit of work within a Project or Area. It may contribute directly to one or more Goals, but does not inherit a Project's Goal contributions as its own.

**Goal contribution**:
An explicit bare link from a Project or Ticket to a Goal that it advances. It expresses contribution, not ownership or priority; a Project's contribution is context for its Tickets, not an inherited claim. The system normally establishes Project contributions during planning or Project creation/reframing, never by bulk inference; a user is never required to maintain them on Tickets.

**Commitment**:
An ongoing behaviour or protected floor the user intends to maintain while pursuing Goals. It is evaluated as maintained or breached, never as complete.
_Avoid_: recurring Goal, maintenance Goal

**Standard**:
A quality or operating baseline that should remain true while the user pursues Goals. Falling below it signals a problem; meeting it does not itself complete a Goal.
_Avoid_: Goal when the desired state is continuous

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

**Triage Plan**:
The inert, per-source proposal listing each un-triaged Raw Capture and where Triage thinks it should go. Inert is the point: it is a set of proposals awaiting a human, so nothing captured can trigger an action merely by being classified. Lives in `inbox/triage/` until every Row is executed, then moves to `archive/triage/`.
_Avoid_: Triage queue, inbox (a Plan is a proposal about captures, not the captures themselves)

**Row**:
One Raw Capture's proposed routing within a Triage Plan — its destination, how that destination was arrived at (Pass A rule match or Pass B model classification), and its approval state. The unit the user reviews and Execute acts on. A Row carries its own destination and is authoritative; where a Plan groups Rows for readability, the grouping is regenerated from those destinations and is never read back (ADR-0031), so correcting a Row is one in-place edit.

**Approve**:
The user's explicit per-Row consent for Execute to act on it. Required on every Row regardless of confidence — confidence never substitutes for approval, since acting on confidence alone is graduation (ADR-0006), a separate mechanism. Approving is distinct from *correcting*, which is editing a Row's destination before approving it.
_Avoid_: Confirm (that's the general confirm-first stance), tick (that's the gesture, not the act)

**Wiki**:
The machine-compiled, concept-organised knowledge layer. A pure function of Raw sources plus validated feedback — never directly human-edited.
_Avoid_: Knowledge base (that's the content layer as a whole — Wiki + curated layer; say Wiki specifically)

**Curated layer**:
The human-authored layer of decisions, standards, and goals per area. The user is its author; the machine reads it and may write into it only through a registered action type (`project-update`, `person-update`, `area-update`, `ticket-create`, and a structuring mechanism's own writes — ADR-0028), every such write being logged and git-reversible. Boundary test: decided it → curated; learned it → Wiki.

**Event layer**:
The mixed human/machine layer of records of things that happened, at `meetings/` — a fourth layer alongside Raw, Wiki, and Curated (ADR-0028). The user authors agenda notes in it; a structuring mechanism augments those and writes new notes into it. Distinct from the Wiki in being event-organised rather than concept-organised, and not resynthesizable — it is written once, not rebuilt.
_Avoid_: Meeting notes folder (half of what lands there may not be a meeting), derived layer (that's the Wiki)

**Structuring**:
Turning a long-form transcript into a readable note plus its downstream effects (backlinks, Person Hub items, tickets). Distinct from Triage, which only classifies, and from Compile, which synthesises concepts across many sources.
_Avoid_: Processing, summarising (structuring produces a shaped artefact, not a précis)

**Resynthesis guarantee**:
The Engine invariant that the Wiki can be dropped and rebuilt from Raw Captures + feedback at any time, by any model, with no human work lost. A safety property, not a determinism claim — rebuilds may differ in wording.

## Operations

**Routine**:
A recurring behaviour declared in the Engine's Routine manifest (name, protocol, risk tier, owner), with its **timing** declared as a Schedule in the Brain and last-run state recorded in the Brain. The manifest says what a Routine *is*; `config/schedules.md` says when it runs (ADR-0030).

**Heartbeat**:
The due-check at every session start that finds overdue Routines and nudges or auto-runs them per their autonomy level. Layer 1 of ADR-0007's triggering stack; reads cadence from the Brain's Schedules.

**Tune**:
The Librarian's report-only loop proposing upgrades to agent and skill definitions, grounded in cited knowledge. Brain-owned targets apply locally on approval; Engine-owned targets become upstream contributions.

**Upgrade routine**:
The periodic external-research cycle that scans new releases/approaches, distils findings into the Brain's knowledge base, and feeds Tune.

**AFK ratio**:
Share of actions executed autonomously rather than confirm-first — the primary fitness metric, alongside cycle time, goal progress, and review debt/correction rate.

**Call Companion curation**:
A bounded, interactive planning flow that reads unclassified active Tickets, proposes `call_suitable` and `estimate_minutes`, and writes frontmatter only upon explicit user confirmation.

**Build clone**:
The non-synced plain clone of a Brain that `/build` operates in when a Ticket's `target_repo` is the Brain (ADR-0039). Work reaches the Brain by push and the Version control routine's pull, never by editing the iCloud-synced tree directly. The vault stays canonical; the Build clone is disposable.
_Avoid_: calling it a mirror or a backup — it holds no state the remote does not, and is not a recovery artefact

## Scheduling

**Schedule**:
One row in the Brain's `config/schedules.md` declaring *when* a Routine or a standalone script runs — both trigger and timing. The **sole source of truth for timing** (ADR-0030); the only place timing is ever edited. Has a **kind**: *fixed-interval* (fires on a clock — heartbeat-checkable) or *poll* (an event-trigger such as "on new raw," realised as a frequent check — excluded from due-checking).
_Avoid_: Cron entry (a Schedule is declarative and runtime-independent; launchd is one binding of it), cadence (retired — see below)

**Job**:
The concrete launchd `.plist` that realises a Schedule. Either realises a Routine's Schedule, or is a *standalone* scheduled script with no Routine (capture pullers, vault backup) — both are first-class rows.
_Avoid_: Task, cron job (Job means the realised artefact specifically, not the work it performs)

**Managed Job / Unmanaged Job**:
**Managed** = generated and owned by the Scheduler Adapter, marked by the namespaced `GoalsOSManaged` key in the plist so ownership is decidable from the file alone. **Unmanaged** = any hand-written plist, including third-party ones; the adapter **never touches** one and refuses loudly on a Label collision.

**Scheduler Adapter**:
`scripts/sync_schedules.py` plus `protocols/schedules.md` — ADR-0007's layer 2. Renders and reconciles Managed Jobs from the Brain's Schedules, idempotently. It schedules a **trigger** and is indifferent to what that trigger invokes: a Python script and an Unattended Session are the same thing to it, a `ProgramArguments` list.
_Avoid_: "it cannot fire an unattended agent session" — it can, and does (ADR-0037). This phrasing appeared here and in `sync_schedules.py`'s own out-of-scope note, and left three tickets parked for a month behind a blocker that did not exist.

**Unattended Session**:
A scheduled agentic session (`claude -p /<skill>`) that performs LLM judgement with no human present — Triage Pass B, rule-learning's grouping step. A first-class Command kind in a Schedule (ADR-0037), distinguished from a script by running with permission prompting disabled and being confined to Proposal Surfaces.
_Avoid_: session runner (there is no separate runner component — `launchd` plus the Runtime's own headless mode is the whole mechanism)

**Proposal Surface**:
A location where a write takes no effect until a human approves it — `inbox/triage/`, `inbox/rule-diffs/`, `log/`. The set an Unattended Session may write. Confirm-first is preserved here structurally, by what the session can reach, rather than by prompting — the only form of it that survives having no human present.
_Avoid_: sandbox (the confinement is about consequence, not isolation)

**Cadence** (retired from the Engine):
How often a Routine runs. Formerly a column in the Engine's `protocols/routines.md` manifest; since ADR-0030 it lives only in the Brain, derived from a Schedule's kind and Timing. Do not reintroduce a cadence field to any Engine file — that is the double-source-of-truth ADR-0030 collapsed.
_Avoid_: using "cadence" as if the Engine owned it; say "the Routine's Schedule"
