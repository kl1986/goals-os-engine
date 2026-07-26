# Base Board view supersedes the board file + sync script — frontmatter is the single source of truth

ADR-0013 kept two surfaces — a `tasks/kanban.md` board file plus each ticket's
`status:` frontmatter — bridged by `ticket_sync.py`, because "the Obsidian Kanban
plugin has no mechanism to update a linked note's frontmatter when a card is
dragged." That premise no longer holds. The Base Board plugin
(`mderazon/obsidian-base-board`, an Obsidian **Bases** view, `type: kanban`)
renders a drag-and-drop board *directly over note frontmatter* and writes the
grouped property back to the markdown on drag. This is exactly the
"frontmatter-as-truth with a live board" option ADR-0013 rejected — and it
rejected it only on the assumption that it would cost the drag-and-drop UX, which
Base Board provides. Decided 22/07/2026.

Consequences: ticket frontmatter becomes the **single source of truth**. The
board is a pure view (`tasks/tickets.base`, grouped by `status`); agents edit
frontmatter, the human drags cards, both write the same markdown — there is no
second store and therefore nothing to reconcile. `tasks/kanban.md` and
`goals-os-engine/scripts/ticket_sync.py` (+ its tests) are **retired**. Ticket
`goals-os-26` (automatic sync + freshest-wins merge) is closed as superseded: the
board↔frontmatter divergence it was designed to resolve can no longer occur.

The `status` column labels in `tickets.base` (`boardColumns`) must match the
ADR-0015 status vocabulary exactly (`backlog | prioritised | in-progress | done |
deprioritized`), since a drag now writes the column label straight into
frontmatter. Base Board also maintains a `kanban_order` property per note for
manual ordering — accepted as a plugin-managed field outside the ADR-0015 set.

**Requires:** the Bases core plugin (Obsidian 1.9+) and the Base Board community
plugin — so the board is only available inside the Obsidian app. This is
acceptable because agents/scripts operate on frontmatter directly and never
needed the board; the board was always a human-only surface.

**Rejected:** keeping `ticket_sync.py` as a headless/CI fallback (it only exists
to reconcile a second store that no longer exists — dead weight once
`tasks/kanban.md` is gone); adopting Base Board's default "in progress" column
label (a space-form value would silently diverge from the hyphenated
`in-progress` used by tickets, ADR-0015, and any status query).
