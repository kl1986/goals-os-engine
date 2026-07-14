---
name: wiki-audit
description: Run the Librarian's Audit verb over the Wiki — dead links and orphaned articles (mechanical, zero LLM calls), plus stale and duplicate articles (semantic, requires model judgement). Every finding is confirm-first; nothing is fixed until the user approves it, then this skill applies the approved fix directly (repair/remove a dead link, relist an orphan, delete a stale article, or merge a duplicate). Use when the user wants the Wiki linted/audited, or periodically to keep it clean.
allowed-tools:
  - Bash
  - Read
  - Write
triggers:
  - audit the wiki
  - lint the wiki
  - check the wiki for dead links
  - /wiki-audit
---

# wiki-audit

The Claude Code binding for the "Audit" verb in `protocols/wiki.md` and the Librarian charter. Two passes, per ticket 03: dead-link/orphan checks are mechanical (script, zero LLM calls); stale/duplicate checks need your semantic judgement, done in-session. Every finding — mechanical or semantic — is confirm-first in Phase 4; nothing auto-fixes, no matter how "obviously safe" it looks.

## What to do

1. Determine the Brain path (ask if ambiguous).
2. Run the mechanical scan:

```bash
python3 <path-to-goals-os-engine>/scripts/wiki_librarian.py --brain "<path-to-brain>" audit-scan-mechanical
```

This is read-only — no writes, no Action Log entries yet. It reports dead links (a `[[wikilink]]` in a flat `wiki/*.md` article whose target doesn't resolve on disk) and orphans (an unindexed article, or a `wiki/_index.md` row pointing nowhere).

3. Read every flat article in `wiki/` (only the `wiki/<slug>.md` + `wiki/_index.md` flat shape this ticket builds — never the pre-existing `wiki/` subdirectories or root meta-files from the earlier v1 content merge; those are out of scope for this Adapter) and judge, in-session: is any article's content superseded by newer captures (**stale**)? Are any two articles really the same concept (**duplicate**)? These are never scripted — always your call.
4. Present every finding — mechanical and semantic — to the user as a single list and get an explicit confirm/tick per finding (or a batch confirmation) before applying anything. Never auto-apply a finding just because it's mechanical (ticket 03 — no Phase-4-local auto-fix shortcut for any action type).
5. For each confirmed finding, apply it directly:

```bash
# dead link — repair (give --new-link) or remove (omit it)
python3 <path-to-goals-os-engine>/scripts/wiki_librarian.py --brain "<path-to-brain>" audit-apply-fix-dead-link \
  --article-slug "<slug>" --old-link "<broken-target>" [--new-link "<replacement>"]

# orphan — relist an unindexed article, or drop a dangling index row
python3 <path-to-goals-os-engine>/scripts/wiki_librarian.py --brain "<path-to-brain>" audit-apply-relist-orphan \
  --action add --slug "<slug>" --summary "<one-line summary>"
python3 <path-to-goals-os-engine>/scripts/wiki_librarian.py --brain "<path-to-brain>" audit-apply-relist-orphan \
  --action remove --slug "<slug>"

# stale — plain delete, no archive/wiki/ folder (git history is the safety net, ADR-0010)
python3 <path-to-goals-os-engine>/scripts/wiki_librarian.py --brain "<path-to-brain>" audit-apply-delete-stale \
  --slug "<slug>"

# duplicate — merge merge-slug into keep-slug; write the merged body to a temp file first
python3 <path-to-goals-os-engine>/scripts/wiki_librarian.py --brain "<path-to-brain>" audit-apply-merge-duplicate \
  --keep-slug "<slug-to-keep>" --merge-slug "<slug-to-retire>" --body-file "<tmp-merged-body-path>"
```

   Each apply call performs the write and logs its own Action Log entry (`wiki-audit-fix-dead-link` / `wiki-audit-relist-orphan` / `wiki-audit-delete-stale` / `wiki-audit-merge-duplicate`) directly — there's no separate execute-style handoff, since Audit's input (the Wiki itself) carries none of Triage's untrusted-capture quarantine concern (ticket 03).

6. Report back: findings by category, which were confirmed and applied, and which the user declined (leave those untouched — don't re-surface a declined finding next run unless it's still true).

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the two-pass split and the confirm-first-for-everything posture; `scripts/wiki_librarian.py` implements the mechanical scan and every apply function; this file does the semantic judgement (stale/duplicate) and the confirmation gate. This skill never deletes, merges, or edits a `wiki/*.md` file without an explicit prior tick, and its tool scope stays confined to `wiki/` — no access to `inbox/raw/`, `areas/`, or `projects/` (the Librarian charter's tool-scope boundary).
