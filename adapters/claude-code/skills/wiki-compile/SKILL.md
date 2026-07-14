---
name: wiki-compile
description: Run the Librarian's Compile verb — resynthesize Wiki concept articles (wiki/<slug>.md) from archived Raw Captures (archive/inbox/<source>/) plus validated feedback. Incremental by default (only concepts with ≥1 new item since last run); pass a concept slug to force one concept, or --full to force every concept (requires an explicit confirmation first — an exceptional, costed rebuild per ADR-0010). Use when the user wants their Wiki updated/resynthesized, or when Heartbeat flags Compile as overdue.
allowed-tools:
  - Bash
  - Read
  - Write
triggers:
  - compile the wiki
  - run compile
  - resynthesize the wiki
  - /wiki-compile
---

# wiki-compile

The Claude Code binding for the "Compile" Routine in `protocols/wiki.md` and the Librarian charter (`protocols/charters/librarian.md`). Concept assignment and article synthesis are always model-driven (ticket 02) — this skill does that in-session; `scripts/wiki_librarian.py` only does the deterministic half (scanning, writing, index maintenance, `heartbeat.bump`, Action Log entries).

## What to do

1. Determine the Brain path and the scope (ask if ambiguous): default (incremental), a specific concept slug, or `--full`.
2. If scope is `--full`: this is the exceptional-rebuild gate (ADR-0010) — state the scope in plain terms ("this will resynthesize all N concepts from scratch") using the concept count from `wiki/_index.md`, and get an explicit tick/confirmation from the user *before* proceeding. Never skip this for `--full`; the script does not gate it itself.
3. Run the scan:

```bash
python3 <path-to-goals-os-engine>/scripts/wiki_librarian.py --brain "<path-to-brain>" compile-scan [--scope <concept-slug>|--scope full]
```

This bumps Compile's own `config/routine-state.md` row regardless of outcome (the Routine ran and checked, even with 0 new captures) and prints the current index, any new (not-yet-cited) archived captures, and any concepts the scope argument forces.

4. For every concept that needs resynthesizing (a `forced_concepts` entry, or — in default/incremental mode — any existing or new concept you judge at least one new capture belongs to):
   - Read `wiki/_index.md` and the concept's current article (if it exists), plus every relevant new capture (follow the `archive/inbox/<source>/<id>` paths from the scan output).
   - Decide, in-session, which existing concept each new capture belongs to, or whether it spawns a new one — there is no rule-based pre-filter for this (ticket 02); it is always your judgement call.
   - Draft the concept's full resynthesized article body. The whole body is replaced each run under the resynthesis guarantee (ADR-0010) — don't hand-append to the old body, write the complete article fresh.
   - Write the body to a temp file, then run:

```bash
python3 <path-to-goals-os-engine>/scripts/wiki_librarian.py --brain "<path-to-brain>" compile-apply \
  --concept-slug "<slug>" --concept-title "<Title>" --body-file "<tmp-body-path>" \
  --sources-json '[["<YYYY-MM-DD>", "archive/inbox/<source>/<id>"], ...]'
```

   This performs the mechanical write (creates/overwrites `wiki/<slug>.md`, appends only the not-yet-cited `source_refs` to its `## Sources` section, adds a `wiki/_index.md` row if the concept is new) and logs a `wiki-compile` Action Log entry.

5. Report back: which concepts were resynthesized (new vs. updated), how many new captures were consumed, and any captures you couldn't clearly assign to a concept (flag these rather than guessing).

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the incremental trigger, the resynthesis guarantee, and the `--full` gate; `scripts/wiki_librarian.py` is the portable, deterministic half (scan + mechanical write + bookkeeping); this file does the model-driven concept assignment and article synthesis, scoped so it never invents a Sources entry the script didn't confirm exists and never skips the `--full` confirmation gate.
