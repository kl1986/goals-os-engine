# Ticket schema: no Epic, schema-only assignee, descriptive (not automated) goal linkage

The ticket type set is Story, Task, Bug, Subtask, Research — no Epic. A Project or Area already plays the epic role of "the thing tickets ladder up to," so a separate Epic type would create two competing containers. Decided 21/07/2026.

`assignee` is a plain descriptive frontmatter field (human or agent name), with no dispatch mechanism behind it — Goals OS v2 has no agent-wakeup/dispatch mechanism yet, so this ticket schema only builds the data layer, not delivery.

`goal:` is likewise a free-text frontmatter field linking a ticket to an Area's Current Goals, for traceability only. The "auto-highlight the global backlog by active goals" behaviour ticket 08 asked to explore is descoped: goals aren't structured, individually-addressable data today, and building that is a separate effort.

`github:` (format `owner/repo#number`) is an optional cross-reference to a matching GitHub issue, set only when a ticket has corresponding tracked code work.

**Amended 23/07/2026 ([[0025-awaiting-review-a-sixth-ticket-status|ADR-0025]]):** The authoritative ticket status value set is `backlog | prioritised | in-progress | awaiting-review | done | deprioritized`, adding `awaiting-review` to express work committed and verified but pending human review/push.

**Rejected:** Epic as a ticket type (redundant with Project/Area); active goal-based auto-prioritization in this ticket's scope (blocked on goals becoming structured data, which is out of scope here).
