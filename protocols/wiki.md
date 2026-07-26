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

The Librarian compiles archived raw captures and validated feedback into Wiki articles. The Compile verb reads exclusively from the `archive/inbox/<source>/` directories (already-triaged, Execute-processed captures or explicitly direct-archived captures), and **never** reads the live `inbox/raw/` queue.

- **Concept assignment**: Concept assignment is model-driven. The Librarian reads `wiki/_index.md`'s current concept list and the archived capture's content, and the model decides which existing concept the item belongs to, or whether it spawns a new one. There is no deterministic pre-filter.
- **Invocation & Scope**: There is no separate "resynthesis command." Compile is invoked in two ways:
  - **Incremental Routine (default)**: Heartbeat's daily due-check runs Compile with no scope argument. It scans everything archived or newly-validated since the last run, groups by concept, and resynthesizes any concept with **≥1** new item.
  - **On-demand (manual)**: Can be invoked manually with an optional scope argument: a specific concept slug (forcing that concept's resynthesis even with no new material), or `--full` (resynthesize every concept from scratch, ignoring the "≥1 new item" gate).
- **Exceptional-rebuild gate**: The `--full` scope argument acts as an exceptional, costed operation (ADR-0010). It requires a plain confirmation ("this will resynthesize all N concepts from scratch") and an explicit tick before proceeding. No token-cost estimate is provided, as no token-budgeting model exists in the Engine yet.
- **Routine-state bookkeeping**: As a heartbeat-checkable (daily) Routine, every successful Compile run bumps its own row in `config/routine-state.md` to track when it last ran.
- **Model routing**: The default model tier (`claude-sonnet-5`) performs synthesis as it is bounded summarization. This is explicitly configured in `config/model-routing.md` under `wiki-compile`.
- **Backlink discipline**: Compile maintains one merged, dated `## Sources` section per article. Each entry follows the format `- YYYY-MM-DD — [[archive/inbox/<source>/<id>]]`, appended every run it resynthesizes that concept based on a new input. Consistent with the flat structure, it avoids duplicating a "Decision Log" separate from sources.

### Per-source feedback

`config/wiki-source-feedback.md` is the durable, editable record for a correction about one archived source. It is deliberately separate from the capture so Raw remains immutable (ADR-0029). Its table has one row per source:

| Capture | Directive | Concept |
|---|---|---|
| `[[archive/inbox/youtube/example]]` | `exclude` | |
| `[[archive/inbox/youtube/another-example]]` | `force-concept` | `agent-systems` |

- `exclude` removes the capture from future synthesis. If it was previously cited, Compile forces the affected article to be fully resynthesized without it.
- `force-concept` makes the capture eligible only for the supplied lowercase-hyphenated concept. Compile forces both that target and every article which had previously cited the capture, so a source cannot silently remain assigned to the old concept.
- Use `scripts/wiki_librarian.py ... source-feedback-set` or edit the table. Malformed rows are ignored rather than guessed. The target must already be an archived capture; live Raw is never a feedback target.

## Audit

Audit checks the Wiki for stale, dead, duplicate, and orphaned articles. The verb is split into two passes:
- **Mechanical checks**: Dead links (broken wikilinks) and orphaned articles (a file not listed in the index, or an index entry pointing nowhere). These are pure script diffs and require zero LLM calls.
- **Semantic checks**: Stale articles (content superseded by newer captures) and duplicate articles (two articles that represent one concept). These require a model's semantic judgment.

All Audit findings are **confirm-first** in Phase 4. There is no auto-fix shortcut. Each finding's action type is explicitly tagged with its eventual ADR-0006 risk tier (e.g., `wiki-audit-fix-dead-link` is internal & reversible; `wiki-audit-merge-duplicate` is outward/hard-to-reverse) so Phase 5's graduation engine can pick it up automatically in the future without further design work.

Once a finding is confirmed and approved, **Audit executes its own actions directly**. Unlike the Triage and Execute split (which exists because Triage handles untrusted capture content), Audit's input is the already-trusted Wiki, so it does not require a separate execute-style handoff. Furthermore, there is no `archive/wiki/` folder for deleted articles. Since the Wiki is not treated as precious and is freely rebuildable (ADR-0010), git history serves as the safety net, and any deletions or merges are performed as direct file operations.

## v1 migration stance

In migrating from the v1 Brain, the v2 Wiki **starts empty**. The v1 Wiki's existing articles are left fully intact and readable in the v1 archive but are not treated as a live source for v2's Wiki.

Seeding them into v2 was explicitly rejected because v1 articles are already-synthesized content. Processing them would mean either a compile-of-a-compile (losing fidelity to the original sources) or copying them straight into `wiki/` and bypassing Compile entirely (which violates ADR-0010's resynthesis guarantee, as they would have no v2-native Raw Capture behind them). A topic already covered in v1 will only get a fresh v2 article once new Raw Captures naturally warrant Compile building one.
