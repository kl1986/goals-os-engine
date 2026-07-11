---
name: capture
description: Stamp a piece of text (a thought, a note, anything the user wants captured) into an immutable Raw Capture under inbox/raw/<source>/. Manual/text capture only in Phase 2 — no email/voice/meeting fetchers. Use whenever the user wants to capture something into their Brain.
allowed-tools:
  - Bash
triggers:
  - capture this
  - /capture
---

# capture

The Claude Code binding for `protocols/capture.md`. All the file-writing is deterministic and lives in `scripts/stamp.py` — never write a Raw Capture file yourself; always go through the script so the frontmatter contract and collision-safe naming hold.

## What to do

1. Determine the Brain path (ask if ambiguous; never guess).
2. Gather from the user: `source` (open string — `voice`, `email`, `meetings`, `web`, or anything else; ask if unclear), a short `title`, and the `body` text.
3. Run:

```bash
python3 <path-to-goals-os-engine>/scripts/stamp.py \
  --brain "<path-to-brain>" \
  --source "<source>" \
  --title "<title>" \
  --body "<body text>"
```

Use `--body-file <path>` instead of `--body` if the content is long or came from a file.

4. Confirm back to the user which file was written (the script prints the path).

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the frontmatter contract and immutability guarantee; `scripts/stamp.py` is the portable, runtime-agnostic implementation; this file is only the Claude Code binding. Manual/text capture is the only Phase 2 capture path — no automated pulling of email, voice, or meetings yet (those are Library plugins, later phases).
