# 0036. One-line Triage Rows with nested option boxes on keepers

- **Status:** accepted
- **Date:** 2026-08-01
- **Deciders:** Kelvin, Coder, Reviewer
- **Consulted:** `protocols/triage.md`, `protocols/execute.md`
- **Informed:** engine repo, library repo

## Context

ADR-0031 replaced markdown table rows with markdown task-list items, and ADR-0033 wrapped classification metadata (`route · confidence · rule`) in Obsidian comment markers (`%%…%%`). However, each Row still spent three lines (task line, preview, capture link) plus a metadata segment per email. In Edit mode — Kelvin's primary working mode in Obsidian — capture wikilinks and comment wrappers were clutter rather than concealment, and a 23-Row Plan spent 23 lines on bookkeeping wikilinks that Kelvin never clicks.

Furthermore, a keeper Row (an email needing a decision) had nowhere to express its target destination except by hand-typing a path inside backticks, introducing friction on mobile.

## Decision

1. **One-line Triage Rows**: Collapse each Row into a single line:
   ```markdown
   - [ ] <preview> → `<destination>` [[<capture_link>]]
   ```
   The capture wikilink is placed inline at the end of the task line. Row numbers leave the line and are derived from document order in `_scan_blocks()`. Error messages reference the preview instead of positional row numbers.

2. **Nested Option Boxes on Keepers**: A keeper Row (destination `unmatched` or `?`) carries option boxes as nested checkboxes:
   ```markdown
   - [ ] Octopus Energy — £21.97 payment on 3rd August → `?`
       - [ ] Act on this
       - [x] Area · `areas/finances/_inbox.md`
       - [ ] Project · `projects/goals-os/_inbox.md`
       - [ ] Bin it instead
   ```
   - Ticking `Area` / `Project` sets the Row's destination(s).
   - Ticking `Bin it instead` sets `discard`.
   - Ticking `Act on this` adds `today` to destinations (`file-capture-today` action).
   - Noise/discard Rows carry zero continuation lines.

3. **Frontmatter Rules Block**: Move surviving Pass A metadata (`rule`, `confidence`) from on-line comments into Plan YAML frontmatter under a `rules:` block keyed by capture filename.

4. **Supersession**: This ADR supersedes ADR-0031's continuation-arity rule and ADR-0033's `%%` comment wrapper. The comment wrapper was removed because Kelvin works in Edit mode, where it was clutter rather than concealment — the premise was never checked with him during ADR-0033's design.

5. **Fail-Closed Gate**: `execute.py`'s `check_row_blocks()` refuses any Plan holding legacy three-line Rows or malformed Row blocks upfront to protect open Plans from silent archive or execution without approval.

## Consequences

- Email Triage Plans present a clean, single-line representation per email in Edit mode.
- Mobile triage friction is removed via nested checkbox options.
- The parser remains anchored at column 0 (`^- `) for task lines while unambiguously scanning indented option lines.
- Legacy Plans require migration (`migrate_triage_rows_one_line.py`) before execution.
