# Protocol: Action Log entry schema (v0)

Defines the structured entry every agent appends to the Brain's Action Log (`log/YYYY-MM-DD.md`) whenever it takes an action — the single audit trail and the substrate the learning loop reads (ADR-0005). This is the Engine's first Protocol: a markdown-defined, runtime-independent spec any Adapter must implement identically.

## Entry format

Each entry is a level-3 heading (`### HH:MM — <action type>`, 24h clock, local time) followed by the eight fields as a bullet list. Entries are appended in chronological order within the day's file and are never edited or deleted after the fact — except `feedback`, which starts unset and is filled in later.

```markdown
### 14:32 — file-email

- **entry id:** a1b2c3d4
- **actor:** EA
- **trigger:** Execute (Routine)
- **input link:** inbox/raw/email/2026-07-11-school-newsletter.md
- **action type:** file-email
- **action:** Filed under Kids > School comms; no reply needed.
- **confidence:** High
- **outcome:** Filed to areas/kids/_inbox/
- **parent reference:** —
- **feedback:** —
```

A worked example spanning several entries: [`examples/action-log/2026-07-11.md`](./examples/action-log/2026-07-11.md).

## Fields

| Field | Meaning |
|---|---|
| `entry id` | A unique identifier for this log entry (e.g., an 8-character hex string). |
| `actor` | The agent that **executed** the action — a System agent (`EA`, `Librarian`, `Coach`), an Area agent (the Brain-chosen name for that area's agent), or a Capability agent noted with its commissioner, e.g. `Researcher (via Will)`. Always the executor, never the approver. |
| `trigger` | What caused this action to run: a Routine name (`Triage`, `Capture sweep`, …), a direct user instruction, or another agent's delegation (`commissioned by Will`). Distinguishes routine-driven autonomy from a one-off ask. When the action was produced via a rule-set match (e.g. Execute acting on a Triage Plan's Pass A row), the value gets a `— rule <8-hex-id>` suffix (e.g. `Execute (Routine) — rule 7f3a9c21`) naming the specific rule that fired, computed by `scripts/triage.py`'s `compute_rule_id()`; entries with no rule match keep the bare Routine name. |
| `input link` | A relative path (or `[[wikilink]]` when the Brain is opened in Obsidian) to the Raw Capture, project note, or other source file this action acted on or derived from. `—` when the action has no single input, e.g. a scheduled Routine firing with nothing new to act on. |
| `action type` | The named category this action belongs to (`file-email`, `send-holding-reply`, …) — the unit graduation operates on (ADR-0006). Every action type carries a risk tier (internal & reversible vs outward-facing/hard-to-reverse) and a current autonomy level (confirm-first vs autonomous), both tracked in `config/`, never inferred from a single entry. |
| `action` | A one-line, human-readable description of what was actually done — specific enough that a user skimming the day's log understands the entry without opening the input link. |
| `confidence` | The acting agent's self-assessed confidence at the point of decision (`High` / `Medium` / `Low`). Determines, together with the action type's current autonomy level, whether the action executed immediately or awaited confirmation. |
| `outcome` | What actually happened — success or failure plus a short specific (`Filed to areas/kids/_inbox/`, `Failed — API timeout, retried once`). Written by the acting agent immediately; never backfilled or inferred later. |
| `parent reference` | A unique ID linking this action to a parent action (e.g. a capability commission chained to an execute dispatch). `—` if this action has no parent. |
| `feedback` | The user's judgement, written after the fact. **`—` means "not yet reviewed" — it is never itself a signal of approval.** For internal & reversible action types, an unreviewed entry that has aged past the review window counts as approval when the graduation routine computes it (ADR-0006), but the field stays `—`; only an explicit validation (e.g. `✓`) or a correction (free text stating what the user would have wanted) is ever written into the slot. Corrections must carry enough detail to update a routing rule. |

## Sharding contingency (ADR-0005 amendment)

The default is one file per day: `log/YYYY-MM-DD.md`, all actors appending to the same file. If concurrent multi-agent writes make single-file contention a real problem, the write pattern shards to **one file per actor per day**: `log/YYYY-MM-DD-<actor>.md`. The entry schema is unchanged either way — `actor` stays present in every entry even when redundant with the filename, so entries remain self-describing if a script later merges shards into one review surface. Sharding is a documented fallback, not the default; a Brain only shards once contention is observed.

## Non-goals (v0)

- No numeric confidence scale — `High`/`Medium`/`Low` only, revisit if the graduation engine needs finer granularity.
- No enforced controlled vocabulary for `action type` yet — the Brain's `config/` is the source of truth for which types exist and their risk tier; this Protocol only fixes the entry shape.
- No script implementation here — this is the schema spec; the Adapter/scripts that stamp entries and compute graduation live elsewhere.
