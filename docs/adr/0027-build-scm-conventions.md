# Build SCM conventions

A Build cuts one branch per Ticket, `build/<ticket-slug>`. A Ticket that is blocked branches **off its blocker's branch rather than off main, and starts the moment the blocker commits** — no merge, no push, no human in between. Independent Tickets run concurrently in separate worktrees of the same repo; dependent ones chain, and the whole Batch converges at the single push gate. This is what ADR-0023 bought: under the previous design a dependent Ticket waited on the user's commit approval, so a Batch stalled at its first Ticket the moment nobody was watching. Decided 23/07/2026.

Commits follow Conventional Commits with the **scope taken from the Ticket's `component:` field** — `feat(v2-shippable-core): …`. Traceability to the specific Ticket rides in a machine-readable trailer instead:

```
Ticket: tasks/projects/goals-os/<filename>.md
```

**Why the scope isn't the ticket.** Existing history scopes commits by ticket ID — `feat(goals-os-27):`, `refactor(ticket-16):` — but ADR-0020 abolished slug-number IDs entirely, so there is no such string left to write. ADR-0020's replacement, "reference it via `[[wikilink]]`", is something a commit message cannot express. `component:` is already in the frontmatter, is short, and is unaffected by ADR-0020; the trailer carries the precise identity in a form both git and a script can read. Using the Ticket's own slug as the scope was rejected only for length — slugs run to ~60 characters and would repeat on every commit for that Ticket.

**Consequences.** Merge commits to main, matching existing history rather than imposing squash or rebase. Push is the gate (ADR-0023) and PRs stay optional per repo, since current history merges directly to main and never opens one. Existing commit-message practice is already inconsistent — bare `feat:` and plain sentences sit alongside scoped commits — so this convention governs Build output and is not a retroactive claim about the log.
