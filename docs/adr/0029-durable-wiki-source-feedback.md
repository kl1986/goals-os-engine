# Durable source feedback lives beside immutable Raw captures

Wiki corrections that target a single archived capture are stored in the Brain's `config/wiki-source-feedback.md`, not written into the capture or directly into the derived article. Each directive either excludes the capture from future synthesis or forces it into one named concept. Compile treats directives as constraints and resynthesizes every affected concept, so a forced source moves rather than being silently duplicated. Decided 26/07/2026.

**Why:** Raw Captures are immutable evidence, while the Wiki is derived and replaceable (ADR-0010). Putting a post-hoc judgement in either layer would respectively corrupt provenance or be lost on the next rebuild. A small, explicit third record preserves both properties and can be edited or removed in git.

**Rejected:** adding `wiki-status` or concept metadata to Raw (breaks immutability); a Gemini `wiki-worthy` pre-filter (silently discards source material); append-only feedback on the Wiki article (does not reliably move a source between concepts during resynthesis).
