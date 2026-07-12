# Protocol: Wiki

The Wiki is the central curated knowledge layer, synthesized from raw captures.

## Structure

The `wiki/` directory uses a flat structure. It contains:
- Concept articles directly at the root (`wiki/<concept-slug>.md`).
- A single `wiki/_index.md` listing all of the articles.

There is no multi-tier hierarchy. Because of the resynthesis guarantee (ADR-0010), the entire Wiki can be dropped and rebuilt at any time, meaning this flat structure can easily be re-generated into a deeper hierarchy in the future if scale requires it.

## Navigation

When an agent (EA, Area agents, the Coach, the Librarian itself) needs to read information from the Wiki, there is no formal "Query" verb or protocol. Instead, agents must follow a **cheap-first read pattern**:
- Check the `wiki/_index.md` file first to locate the relevant article(s).
- Read the full `wiki/<concept-slug>.md` articles only after locating them in the index.

This establishes a documented token-frugal default, preventing agents from improvising their own unoptimized read patterns or searching the whole directory at once.

## Compile

The Librarian compiles archived raw captures and validated feedback into Wiki articles. The Compile verb reads exclusively from the `archive/inbox/<source>/` directories (already-triaged, Execute-processed captures), and **never** reads the live `inbox/raw/` queue.

- **Concept assignment**: Concept assignment is model-driven. The Librarian reads `wiki/_index.md`'s current concept list and the archived capture's content, and the model decides which existing concept the item belongs to, or whether it spawns a new one. There is no deterministic pre-filter.
- **Incremental trigger**: Compile is its own Routine, batched per run. Each run scans everything archived or newly-validated since the last Compile run, groups by concept, and resynthesizes any concept that received **≥1** new item. This is batched to save tokens, as resynthesis is always permitted and never lossy (ADR-0010).
- **Routine-state bookkeeping**: As a heartbeat-checkable (daily) Routine, every successful Compile run bumps its own row in `config/routine-state.md` to track when it last ran.
- **Model routing**: The default model tier (`claude-sonnet-5`) performs synthesis as it is bounded summarization. This is explicitly configured in `config/model-routing.md` under `wiki-compile`.

## Audit

Audit checks the Wiki for stale, dead, duplicate, and orphaned articles. The verb is split into two passes:
- **Mechanical checks**: Dead links (broken wikilinks) and orphaned articles (a file not listed in the index, or an index entry pointing nowhere). These are pure script diffs and require zero LLM calls.
- **Semantic checks**: Stale articles (content superseded by newer captures) and duplicate articles (two articles that represent one concept). These require a model's semantic judgment.

All Audit findings are **confirm-first** in Phase 4. There is no auto-fix shortcut. Each finding's action type is explicitly tagged with its eventual ADR-0006 risk tier (e.g., `wiki-audit-fix-dead-link` is internal & reversible; `wiki-audit-merge-duplicate` is outward/hard-to-reverse) so Phase 5's graduation engine can pick it up automatically in the future without further design work.

Once a finding is confirmed and approved, **Audit executes its own actions directly**. Unlike the Triage and Execute split (which exists because Triage handles untrusted capture content), Audit's input is the already-trusted Wiki, so it does not require a separate execute-style handoff. Furthermore, there is no `archive/wiki/` folder for deleted articles. Since the Wiki is not treated as precious and is freely rebuildable (ADR-0010), git history serves as the safety net, and any deletions or merges are performed as direct file operations.
