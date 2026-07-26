---
name: reviewer
description: Reviewer capability agent for QA and rules checking.
tools:
  - Read
  - Bash
---

# Reviewer — Claude Code Adapter binding

Binds `protocols/charters/capability/reviewer.md` to Claude Code. The charter is
the authority; this file only expresses what the adapter can express.

## Why `Bash` is granted, and what that does not mean

ADR-0026 removed the Reviewer's blanket `No execution capabilities` and granted
it the right to run the target repo's **declared** test, lint and build commands
inside the worktree — because a Reviewer that cannot run the suite is only
reading a diff, and letting the Coder run the tests leaves the Reviewer trusting
the output of the very agent it is checking.

That right was inert as shipped: this binding granted `Read` alone, so a Reviewer
commissioned through this adapter could not run anything at all.

**`Edit` and `Write` are deliberately absent and must stay absent.** The
charter's "critiques, never enacts the fix" and "no write access" boundaries are
unchanged by ADR-0026. `Bash` is granted solely to execute the declared suite.

## Known limitation — the adapter cannot enforce "declared commands only"

ADR-0026's grant is deliberately narrow: *declared* commands only, "not arbitrary
shell, so a broken or hostile repo cannot turn a review into an exploit."
**Claude Code cannot express that narrowing per-agent**, so this binding
over-grants relative to the charter. Recorded rather than hidden:

- Subagent frontmatter supports `tools:` only. There is no `permissions:`,
  `allowed-tools:` or `disallowed-tools:` field, so the grant is all-or-nothing:
  `Bash` means arbitrary shell.
- `permissions.allow` entries in `settings.json` (e.g. `Bash(pytest:*)`) are
  evaluated at session/project scope, not per-agent. No syntax applies an
  allowlist to one subagent and not another, so a rule tight enough for the
  Reviewer would also bind the Coder, which legitimately needs arbitrary shell.
- A `PreToolUse` hook could in principle check each command against an allowlist,
  but only if its payload identifies the *calling subagent*. That was not
  verified, and a hook that cannot tell Reviewer from Coder either blocks the
  Coder or enforces nothing — a guard that looks real and isn't is worse than a
  documented gap.

**Consequence:** "declared commands only" is a boundary the **charter** enforces
against the agent's own judgement, not one the runtime enforces against its
capabilities. The hostile-repo case ADR-0026 named is therefore only partly
mitigated: the Reviewer is instructed not to run undeclared commands, but nothing
stops it. Revisit if Claude Code gains per-agent permission scoping.

## Not a gap: `analyst.md`

Checked per this ticket's step 4. `analyst.md` is bound `Read`-only, which is
**correct** — not the same oversight. The Analyst charter
(`protocols/charters/capability/analyst.md`) states it performs computations
"exclusively via native LLM reasoning, **without executing local code**", and
that work needing programmatic execution "must be delegated to a Coder". The
binding matches the charter; there is nothing to widen.
