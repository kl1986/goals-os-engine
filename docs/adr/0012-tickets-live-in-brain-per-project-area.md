# Tickets live in the Brain, organized per Project/Area, not a separate repo

Ticket 08 initially called for tasks living in "a separate task management repo," but ADR-0003 already put all user-specific operational state in the Brain and explicitly rejected a fourth state repo. Ticket status/assignee/priority is exactly that kind of state, so tickets stay in the Brain: a global `tasks/` folder at the goals-os project root, with `tasks/projects/<slug>/` and `tasks/areas/<slug>/` subfolders holding the actual ticket files — mirroring the vault's existing `projects/<slug>/` / `areas/<slug>/` split. Decided 21/07/2026.

The 15 existing tickets under `scratch/v2-shippable-core/issues/` migrate into `tasks/projects/goals-os/` (renumbered per ADR-0014, tagged `component: v2-shippable-core`). The effort's `map.md` stays put at `scratch/v2-shippable-core/map.md` — only the ticket files move.

**Rejected:** a dedicated task-management repo (revisits ADR-0003 for no real benefit here).
