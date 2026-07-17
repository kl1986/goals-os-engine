# Protocol: Dashboard (v0.3)

A generated, Obsidian-renderable `Dashboard.md` at the Brain root — PRD §9's "day's plan and approve/feedback affordances" surface, for Phase 2's implemented Routines. v0.1 (12/07/2026, personal-migration Wayfinder map, ticket 05) added a fourth source: open Waiting For items scanned from `people/*.md`, per `protocols/people-tracking.md`. v0.2 (Phase 5 — Learning, ticket 05/06) adds a fifth: pending rule-diff reviews scanned from `inbox/rule-diffs/*.md`, per `protocols/rule-diff-review.md`. v0.3 (`capture-source-plugins` Wayfinder map, ticket 08/13) adds a sixth: pending-item counts scanned from `Files/dropzone/*` — restoring v1's "N items waiting" nudge.

## Pure derivation

The Dashboard is safe to overwrite every run, unlike the append-only Action Log. `scripts/dashboard.py` computes everything fresh from source each time — overdue Routines (via `heartbeat.py`), pending Triage Plans (via `execute.py`'s row parsing), pending rule-diff reviews (via `rule_diff_review.py`'s diff parsing), open Waiting For items (scanned from `people/*.md`), today's Action Log, and pending Dropzone item counts (scanned from `Files/dropzone/*`) — and rewrites the whole file. There is no dashboard history; yesterday's `Dashboard.md` is gone the moment today's run happens.

After writing the file, it also bumps its own `Dashboard` row in `config/routine-state.md` (`heartbeat.update_last_run`), so Heartbeat's due-check reflects that this run happened. The bump comes *after* computing the "overdue" section, so this run's own render still shows whatever was true coming in — the Dashboard reports on itself honestly, then updates state for whoever asks next (Heartbeat, or tomorrow's Dashboard).

## What "approve/feedback affordances" means in Phase 2

The Dashboard itself is **read/link-only — it executes nothing.** "Affordances" means:

- Links into the actual Triage Plan files (`inbox/triage/*.md`) — approval happens by ticking a row there, not on the Dashboard.
- Links into the actual rule-diff batch files (`inbox/rule-diffs/*.md`) — approving or rejecting a diff happens by ticking a checkbox there, not on the Dashboard (`protocols/rule-diff-review.md`).
- A link into today's Action Log (`log/YYYY-MM-DD.md`) — feedback is written there, not on the Dashboard.
- Links into the Person Hub each open Waiting For item came from (`people/<Full Name>.md`) — closing an item happens by editing the hub, never on the Dashboard. This is the same read-only-roll-up guarantee `protocols/people-tracking.md` commits to: the Dashboard is never a second place to log a delegation.

The sixth section (Dropzone) has no per-item affordance — it's a pure count nudge, same as v1's, with nothing to tick or open per item. Processing happens through each dropzone's own capability (e.g. `webexpenses`, `kids-homework`, `save-recipe`), never on the Dashboard.

## Contents

Six sections, computed independently:

1. **Overdue routines** — `heartbeat.compute_overdue()`'s output verbatim.
2. **Pending Triage Plans** — every `inbox/triage/*.md` file with `status: pending`, with a ticked/unticked row count.
3. **Pending review** — every `inbox/rule-diffs/*.md` file with `status: pending`, with a decided/undecided diff count (`protocols/rule-diff-review.md`).
4. **Waiting For** — every open `#waiting-for` item across `people/*.md` (unticked and not struck-through), as a flat list ordered by hub filename (so one person's items sit together without a nested heading), each linking back to its hub.
5. **Today's Action Log** — entry count for `log/{today}.md`, plus how many entries still carry the `feedback: —` placeholder (not yet reviewed).
6. **📁 Dropzone awaiting processing** — a top-level (non-recursive) file count for each of `Files/dropzone/Expenses/`, `Files/dropzone/Homework/`, and `Files/dropzone/Recipes/`, rendered as `- <name>: <count> waiting` (same bulleted-list shape as every other section). Dotfiles (e.g. `.DS_Store`) at the top level don't count. `Files/dropzone/` sits outside the Brain entirely — a sibling of the Brain root under the Documents root (`Documents/Vault/` vs `Documents/Files/dropzone/`), resolved at runtime as `<brain>/../Files/dropzone`, not a path inside the Brain. If the folder is missing, all three counts render as `0` rather than omitting the section. Restores v1's "N items waiting" nudge (`capture-source-plugins` wayfinder ticket 08).

## Placement

`<brain>/Dashboard.md` — the Brain root, singular. Not `log/dashboard-{date}.md`: this is "today's surface," not history, so it doesn't accrete a file per day.

## Adapter binding

See [`adapters/claude-code/skills/dashboard/`](../adapters/claude-code/skills/dashboard/).

## Non-goals (v0.1)

- No live checkboxes or buttons inside `Dashboard.md` itself — Obsidian markdown, not an app.
- No project next-actions rollup — that needs Area agent output (Phase 3+).
- No metrics (AFK ratio, cycle time, …) — Metrics pulse is a later Routine (Phase 6).
- No To Discuss rollup — only Waiting For is surfaced here; To Discuss items stay hub-only for now (no stated need for a cross-hub view yet).
