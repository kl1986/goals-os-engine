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
