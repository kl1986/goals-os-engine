# Goals OS v1 to v2 Migration Guide

This document outlines the upgrade path from Goals OS v1 to the v2 architecture. v2 introduces a stricter folder structure, a declarative routing system, and separated Engine/Library repositories.

## Overview

The primary invariant of v2 is that **the Engine structurally cannot touch your Brain** other than through controlled, additive appends (`_memory.md`, daily notes, Action Logs) and the single mutable bottleneck (`inbox/triage/`). 

Migrating an existing v1 Vault involves mapping your old content into the v2 `goals-os-brain-template` structure. This must be done manually or via a custom script, as the Engine respects the invariant of not rewriting your Brain.

## 1. Content Porting Mapping

You will need to move your folders to align with the new structure. Ensure you rename the folders exactly as specified.

| v1 Path | v2 Path | Notes |
|---------|---------|-------|
| `1-Projects/` | `projects/` | Move all active projects here. |
| `2-Areas/` | `areas/` | Move all area folders here. Ensure they contain a `_memory.md`. |
| `3-Resources/People/` | `people/` | Move all people profiles and related data here. |
| `3-Resources/Wiki/` | `wiki/` | Move all wiki documents to the top-level wiki directory. |
| `4-Archives/` | `archive/` | Move all archived content here. |
| `Daily/` | `(root daily notes)` | v2 writes daily notes directly to `<brain>/YYYY-MM-DD.md`. Old notes can be archived. |
| `0-Inbox/Raw/` | `inbox/raw/<source>/` | Move unprocessed captures here, sorting them into per-source subdirectories. |

## 2. Schema Validation

v2 enforces specific YAML frontmatter schemas for configuration files.
- Move your settings to `config/`.
- Ensure all config files include the `type: config` frontmatter.
- Create `config/routing-rules.md` (for deterministic Pass A rules) and `config/autonomy-policy.md`.
- Review the `goals-os-brain-template/config/` examples for the exact required schemas.

**Post-Migration Step:** The migration process must include running the `validate-schema` skill across the migrated files to flag any legacy frontmatter and ensure adherence to v2 specs.

## 3. Wiki Migration

If you extensively used the Wiki feature in v1, you must migrate those documents to the new `wiki/` top-level directory (i.e. `3-Resources/Wiki/` -> `wiki/`). 
- Ensure `scripts/wiki_librarian.py` can index them. Links should be relative to the Brain root or standard Obsidian wikilinks `[[Filename]]`.

## 4. The Resynthesis Option

Because v2 changes the fundamental routing and execution logic, you have the option of a "Resynthesis" approach instead of a direct mapping:
1. Start with a fresh clone of `goals-os-brain-template`.
2. Run `onboard.py` to recreate your Areas clean.
3. Manually copy over active Project next actions and Area memories.
4. Place all other legacy v1 files into an `archive/legacy-v1/` folder.
5. Retrieve old captures and inbox items to process. You can compile your legacy inbox artifacts by running the Librarian's Compile verb over the migrated `archive/inbox/`. Explicitly, run:
   ```bash
   PYTHONPATH=. python3 scripts/wiki_librarian.py --compile archive/inbox/
   ```
   *(Note: If the compile feature is not fully implemented in the Librarian per AGENTS.md, use `grep_search` or standard search indexing to rely on search capabilities to retrieve old notes as needed, while starting fresh with v2's strict triage pipeline.)*

This is highly recommended for most users to ensure the new `routine-state.md` and heartbeat mechanics function correctly without legacy cruft.
