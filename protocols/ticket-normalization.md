# Protocol: Ticket normalization (v0)

The Routine that keeps every ticket under `tasks/**/*.md` conforming to ADR-0015's schema and `docs/agents/issue-tracker.md`'s naming convention (`<slug>-<number>-<short-desc>.md`), even when a ticket was created by a path that doesn't fill in the whole shape — chiefly Base Board's quick-add, which only ever sets `status` and `kanban_order` on a new card (confirmed live: `tasks/projects/return-on-constraints/bye.md` and `return-on-constraints-1.md`, both real files with only those two keys, no title, no body, and a filename that isn't a valid ticket ID at all). Left alone, these cards are invisible to anything that expects a full ADR-0015 ticket — `daily-note.md`'s Project-next-actions scan, Heartbeat-adjacent tooling, a human scanning the board — because they're missing the fields that scan relies on (ADR-0018 fixed this).

Cadence **daily**, heartbeat-checkable (`protocols/routines.md`'s manifest — same shape as every other daily Routine). Risk tier **internal & reversible**: every write is either a blank-field backfill or a rename/relocate within `tasks/`, nothing destructive, nothing touching content outside `tasks/`. Owner **EA**.

## What it scans

Every file under `tasks/**/*.md`. For each one, checks whether its frontmatter is missing **any** of ADR-0015's keys:

```
status, type, priority, component, parent, assignee, github, goal, created, resolved
```

`kanban_order` is deliberately excluded from this check — it's Base-Board-managed (the board writes it on drag; nothing here should ever touch it) and isn't part of what makes a ticket's frontmatter "complete" for this Routine's purposes.

A file with every one of those ten keys already present — even if some values are blank — is **fully conforming** and is left completely untouched: no backfill, no rename, no Action Log entry. This is what makes the Routine idempotent — a ticket this Routine (or `scripts/migrate_next_actions.py`) already normalized has nothing missing on the next pass, so it's simply skipped.

## What it does, per non-conforming file

1. **Backfill.** Every missing key is added to the frontmatter block as blank (`key: `), with one exception: `type` defaults to `task` if it's the one missing (a ticket with no declared type is far more likely to be a plain task than any of the other four `type` values). Existing values — blank or not — are never overwritten.

2. **Rename/re-ID**, using the file's own location to infer a slug:
   - If the file sits at exactly `tasks/projects/<slug>/<file>.md` or `tasks/areas/<slug>/<file>.md`, `<slug>` is that folder's name. The Routine scans that folder's existing `<slug>-N-...md` siblings for the highest `N` already in use and renames the file to `<slug>-<N+1>-<short-desc>.md`.
   - `<short-desc>` is a slugified form of the file's H1 title (its first `# ` line). A file with no H1 at all (the `bye.md`/`return-on-constraints-1.md` case — no title, no body) gets a generic `# Untitled ticket` H1 inserted so it isn't left without a title, and `<short-desc>` is `untitled`.
   - A file with **no inferable slug** — e.g. quick-added directly under `tasks/` itself, or under `tasks/projects/` or `tasks/areas/` without a `<slug>/` subfolder at all — has nothing to number it against. Instead of a rename, it's **relocated to `tasks/_unfiled/`**, keeping its own filename (frontmatter backfill from step 1 still applies; only the rename/re-ID step is skipped). This surfaces it for a human to re-file properly rather than inventing a slug that isn't there.

3. **Log.** One Action Log entry per file actually modified (`actor: EA`, `trigger: Ticket normalization (Routine)`, `action type: ticket-normalize`) — `input link` is the file's new path, `outcome` states which keys were backfilled and where the file ended up. A fully-conforming file that was skipped gets no entry — nothing happened to log.

## Execution — fully automatic

Same posture as `routine-graduation.md`'s Pass (ii): zero confirmation, no Plan to approve, no judgement call that needs a human. Everything here is mechanical — "is this key present," "what's the next free number," "does this file have an H1" — nothing requires reading the file for meaning. The one place this Routine comes closest to a judgement call (slugifying a title into a short-desc) is pure string transformation, not interpretation.

## No-op behaviour

If every file under `tasks/**/*.md` already conforms, nothing is renamed, nothing is backfilled, and no Action Log entries are written — matching `routine-graduation.md`'s and `version-control.md`'s silent no-op precedent. The one write that always happens, success or no-op, is this Routine's own `Ticket normalization` row in `config/routine-state.md` (bumped via `heartbeat.bump()`), so Heartbeat's due-check reflects that the Routine actually ran.

## Adapter binding

See [`adapters/claude-code/skills/ticket-normalization/`](../adapters/claude-code/skills/ticket-normalization/). `scripts/ticket_normalization.py` is the full implementation — detection, backfill, rename/relocate, and the Action Log/heartbeat writes; the Adapter binding only calls it and relays the summary. No in-session judgement is required, so unlike `graduation-check`'s Pass (i), this Adapter supplies nothing of its own.

## Non-goals (v0)

- No structured `blocking`/`blocked-by` frontmatter field — out of scope for this ticket (ADR-0019's non-goals).
- No de-duplication of near-identical tickets, no content quality checks beyond "does a title exist" — this Routine only makes a ticket file *shape-conforming*, never judges whether its content is any good.
- No re-running against tickets outside `tasks/` (e.g. a stray task list embedded in a Project note) — `project-tracking.md` v1 (ADR-0017) already removed that possibility going forward, and this Routine doesn't reach into non-ticket files to find task-shaped content to convert.
- No automatic Base Board re-sort — `kanban_order` is never written by this Routine; the board itself re-derives ordering the next time it's opened.
