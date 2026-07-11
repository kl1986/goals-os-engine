# Protocol: Capture (v0)

Turns arbitrary captured text into an immutable Raw Capture under `inbox/raw/<source>/` — the ground truth everything downstream (Triage, Wiki compilation) derives from, never edited or deleted after the fact (Principle 2). This is the manifest's "Capture sweep" row's only Phase 2 implementation.

## Frontmatter contract

```markdown
---
type: raw
date: 2026-07-11
source: voice
id: 2026-07-11-140203-buy-milk
raw: true
---

# Buy milk

Remember to buy milk on the way home.
```

| Field | Meaning |
|---|---|
| `type` | Always `raw` — marks this file as an unprocessed Capture, distinct from curated/Wiki content. |
| `date` | `YYYY-MM-DD`, the capture's stamp date. |
| `source` | An **open string** — `voice`, `email`, `meetings`, `web`, or any other source a Brain configures. No fixed enum is imposed by the Engine (per `inbox/raw/README.md`). |
| `id` | The filename stem, doubling as a stable reference other files can link to (e.g. an Execute action's `input link`). |
| `raw` | Always `true` — a second, redundant-by-design marker so a script can filter Raw Captures by frontmatter alone without parsing `type`. |

## Per-source subfolder convention

Every Capture lands in `inbox/raw/<source>/`, one file per capture. `<source>` subfolders are created on first use — nothing is pre-provisioned; a Brain accretes only the source folders it actually captures into.

## Immutability contract (Principle 2)

Once written, a Raw Capture file is never edited or deleted. Triage and synthesis only *read* from `inbox/raw/`; the one and only mutation any downstream Protocol performs is moving the file to `archive/inbox/<source>/` once Execute has processed it (see `execute.md`). Anything that looks like "fixing" a Raw Capture happens by capturing a correction as a new file, not by touching the original.

## Collision-safe naming

The filename (and `id`) is `{date}-{HHMMSS}-{slug-of-title}`. If a second capture in the same source lands in the same second with the same title (vanishingly rare for manual capture, but possible under scripted/batch use), a numeric suffix (`-2`, `-3`, …) is appended until the name is free. `scripts/stamp.py`'s `stamp()` function guarantees this — never construct a Raw Capture filename by hand.

## Non-goals (v0)

- **Manual/text capture only.** Phase 2 ships one path: a human (or an Adapter skill on their behalf) supplies source + title + body. No Gmail fetcher, no voice-transcription pipeline, no meeting-recorder integration — those are Library plugins, later phases (§12 of the PRD; roadmap Phase 3+).
- The manifest's "continuous/hourly" cadence for Capture sweep is therefore aspirational until a real puller exists — Phase 2's Capture sweep is event-triggered (fires per manual invocation), not due-checked (`protocols/routines.md`).
- No dedup or near-duplicate detection across captures — every call to `stamp()` writes a new file.
