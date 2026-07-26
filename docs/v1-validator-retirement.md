# Retiring the v1 validators

`scripts/schema_enforce.py` is the v2 enforcer. It replaces two v1 Claude Code
skills, `validate-schema` and `vault-lint`, both of which target retired paths
and neither of which knows anything about the v2 **ticket** schema.

This document is the retirement plan. **Nothing here has been deleted by the
build**, deliberately: both skills live in
`<vault-root>/.claude/skills/`,
and `Documents/` is **not a git repository**. Removing untracked, unversioned
files there is irreversible, so it is Kelvin's call and Kelvin's hand.

## Why each one goes

| Skill | Targets | Verdict |
|---|---|---|
| `validate-schema` | `Vault/_Templates/SCHEMAS.md` typed notes (`project`\|`area`\|`daily`\|`intelligence`) | **Retire.** `_Templates/` is inert in v2 (root `CLAUDE.md`: "old Obsidian templates — inert; protocols are the live mechanism"). It has no notion of the ADR-0015 ticket schema, which is what actually drifts. |
| `vault-lint` | Cross-note structure + queue health, over `0-Inbox/`, `3-Resources/`, `4-Archive/` | **Retire, checks folded in.** Its broken-link and orphan checks are check (c) and check (b) of the enforcer, against live v2 paths. Its PARA paths (`0-Inbox`, `3-Resources`, `4-Archive`) no longer exist in the Brain. |

Coverage after retirement:

| v1 check | v2 home |
|---|---|
| frontmatter shape of typed notes | `schema_enforce.py` check (a), for tickets — the only frontmatter contract v2 actually enforces |
| broken `[[wikilinks]]` | `schema_enforce.py` check (c) |
| orphan notes (zero inbound links) | **not carried over** — see "Not carried over" below |
| stale inbox queue / raw mutated / stale projects | **not carried over** — see below |
| Wiki article content | out of scope by the ticket; `protocols/wiki.md` / the Librarian owns it |

### Not carried over

The enforcer answers "is this structurally valid?", not "is this being worked
on?". Three `vault-lint` checks are *hygiene* judgements rather than schema
conformance, and the enforcer deliberately does not inherit them:

- **orphan notes** (zero inbound links) — a note with no backlinks is not
  malformed, and the Brain has surfaces for this already (`Dashboard.md`, the
  Librarian's Audit verb).
- **stale inbox queue** — Heartbeat and `Dashboard.md` already report pending
  Triage Plans and Dropzone counts.
- **stale projects/areas** — `protocols/planning-session.md` territory.

None of them are silently lost — but none of them are in this ticket's three
checks either, so bringing them across would be scope this build did not have.

## Files Kelvin must delete by hand

```
~/…/Documents/.claude/skills/validate-schema/SKILL.md
~/…/Documents/.claude/skills/validate-schema/scripts/validate.py
~/…/Documents/.claude/skills/validate-schema/scripts/__pycache__/     (whole dir)
~/…/Documents/.claude/skills/validate-schema/                          (the now-empty dir)

~/…/Documents/.claude/skills/vault-lint/SKILL.md
~/…/Documents/.claude/skills/vault-lint/scripts/lint.py
~/…/Documents/.claude/skills/vault-lint/                               (the now-empty dir)
```

(`<vault-root>` is the directory containing both the Brain repo and `Code/` — this
Engine repo is public, so the operator's absolute home path is deliberately not
written down here.)

## Callers that break on deletion — fix these first

`validate-schema` is not only invoked by hand. Two other skills shell out to its
script, and both will start failing silently once it is gone:

| Caller | Line | What it does |
|---|---|---|
| `.claude/skills/dream/SKILL.md` | ~271 | `python3 …/validate-schema/scripts/validate.py --json` |
| `.claude/skills/librarian/SKILL.md` | ~63, ~89 | "run `validate-schema` (`validate.py --json`)"; "`validate-schema` clean on `type: wiki` notes" |

Both use it to check **Wiki-note** frontmatter (`type: wiki`, `tags: [wiki]`) —
which is exactly the case the enforcer does **not** cover, because validating
Wiki articles is out of scope for this ticket. So deleting `validate-schema`
removes a capability those two skills currently rely on. Decide first:

1. drop the schema step from `dream` and `librarian`, or
2. extend the enforcer with a Wiki-note frontmatter check (a separate ticket).

Until one of those is done, deleting `validate-schema` leaves two dangling
callers. `vault-lint` has no programmatic callers and can go immediately.

## Already done in the Engine

- `docs/migration-guide.md` no longer tells the migration to run
  `validate-schema`; it names `scripts/schema_enforce.py` instead.
