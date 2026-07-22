# Protocol: Planning session (v0)

The Routine `protocols/charters/area-ceo.md` exists to run (ticket 16): one Area agent, planning with the user — chat today, voice per ADR-0009 later (PRD §9) — decomposing the area's goals into next actions. `routines.md`'s manifest has declared this Routine since Phase 2 ("declared, not implemented (Phase 3), owner: Area agents"); this Protocol implements it, proven against Will/Work.

## What a session does

1. **Reads** — the Area agent's own charter (`charters/area-ceo.md`) plus its area's note (`areas/<slug>/<Area Name>.md`) and `_memory.md`, per that charter's Session behaviour section. Prior continuity comes from `_memory.md`'s Session log; nothing is re-decided from scratch each time.
2. **Conversation** — chat with the user (or voice later, ADR-0009): revisit the `## Standard` only if it's genuinely stale or the user raises it (most sessions leave it alone), and decompose `## Current goals` into concrete next actions.
3. **Writes, in-session** — the Area agent edits its own area note directly: `## Current goals` (most sessions), `## Standard` (first session, or a genuine revision). This is free text the conversation actually produced — never placeholder copy, never invented content the user didn't say. Not scriptable, for the same reason Triage's Pass B classification isn't (`triage.md`): there's no fixed algorithm for deciding what a person's goals are.

   When the conversation decomposes `## Current goals` into concrete next actions, those next actions are never appended as lines on the area note itself — `## Next action` no longer exists anywhere in the schema (ADR-0017; `project-tracking.md`'s Backlog is free text only, and Areas never had a Next-action section in the first place). Instead, the Area agent creates a ticket file directly under `tasks/areas/<slug>/`, per `docs/agents/issue-tracker.md`'s schema: `status: prioritised`, `type: task`, `created: <today, ISO YYYY-MM-DD>`, and `goal:` set to a free-text link back to the specific `## Current goals` bullet that drove it (not a structured reference — same free-text convention the schema uses elsewhere). One ticket per next action agreed in the session.
4. **Writes, bookkeeping** (`scripts/planning_session.py`, deterministic, no LLM judgement) — once the conversation has something worth recording:
   - Appends a dated entry to `_memory.md`'s `## Session log`.
   - Appends one Action Log entry (`action-log-schema.md`): `actor` is the Area agent's name (e.g. `Will`), `trigger` is `Planning session (Routine)`.
   - Bumps its own `Planning session` row in `config/routine-state.md` (`heartbeat.bump`), the same fixed, non-conversation-derived bookkeeping write every Routine-implementing script makes (`heartbeat.py`'s `update_last_run` docstring: version_control.py, triage.py, execute.py, dashboard.py, stamp.py, and now this one).

## Cadence

Weekly / on demand, heartbeat-checkable (`routines.md`'s manifest, ADR-0007) — `scripts/heartbeat.py`'s due-check flags `Planning session` overdue once its `config/routine-state.md` row is more than 7 days stale, the same mechanism every other heartbeat-checkable Routine uses. No auto-run: Heartbeat only ever nudges (`routines.md`'s own non-goal).

## Adapter binding

See [`adapters/claude-code/skills/planning-session/`](../adapters/claude-code/skills/planning-session/) — the Claude Code binding that instantiates an addressable Area agent (the generic Area CEO charter, specialised in-session to one area's note + `_memory.md`) and runs the conversation, then calls `scripts/planning_session.py` for the bookkeeping half.

## Non-goals (v0)

- **No Capability agent commissioning mid-session.** The Area agent directs at the conversation level only here; commissioning a Researcher/Writer mid-session is ticket 17's job.
- **No voice interface.** Chat only in this ticket; ADR-0009's voice dialogue plugin is a separate, later Adapter.
- **No cross-area batch planning.** One area, one Area agent, per invocation — migrating the mechanism to the remaining areas is tickets 19–23, not this Protocol.
- **No enforcement that a session actually happened before the bookkeeping script runs.** Like `log_action.py`, the script trusts its caller (the Adapter) to only invoke it after a real conversation — the same trust boundary every other script-callable-from-the-Adapter already has.
