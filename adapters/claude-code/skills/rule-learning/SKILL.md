---
name: rule-learning
description: Weekly pass over the Action Log for recurring correction patterns — groups similar `corrected — <detail>` entries in-session, and for any group of >=2 pointing at the same underlying miss, writes a rule-diff proposal onto the rule-diff review surface. Never writes to a rule-set file itself. Use when the user runs /rule-learning, asks to look for patterns in corrections, or it's this Routine's weekly turn per Heartbeat.
allowed-tools:
  - Bash
  - Read
triggers:
  - look for rule patterns
  - /rule-learning
---

# rule-learning

The Claude Code binding for `protocols/rule-learning.md`. Mirrors `triage-plan`'s script/skill split: `scripts/rule_learning.py` does the deterministic scanning, the >=2 threshold check, the de-dup check, diff-writing (in `protocols/rule-diff-review.md`'s exact format), the `propose-rule-diff` Action Log entry, and the `config/routine-state.md` bump. This skill supplies the one genuinely judgement-based step — deciding which scanned corrections share an underlying miss, and drafting each group's rule block + rationale — then calls the script to do the rest. It never appends to a `config/{ruleset}.md` file directly; that only ever happens via `protocols/rule-diff-review.md`'s Approve step.

## What to do

1. Determine the Brain path and which rule-set(s) to check (ask if ambiguous — today's one real instance is `routing-rules`, for `config/routing-rules.md`).
2. Scan for corrections:

```bash
python3 <path-to-goals-os-engine>/scripts/rule_learning.py --brain "<path-to-brain>" scan
```

This prints every `corrected — <detail>` Action Log entry found (across all rule-sets) as JSON — each with its `action_type`, `detail`, and ready-to-cite `link`. If empty, report that and stop; nothing to propose this week.

3. **Judge similarity, in-session.** For the ruleset you're checking, group the scanned corrections whose `detail` payloads point at the same underlying miss — read each one's `input link`/`action` context if the `detail` text alone isn't enough to judge. Only a group of **2 or more** is a candidate; a single correction on a theme is not a pattern, however clear-cut it looks. For each qualifying group, draft:
   - a short, free-text, kebab-case `slug` for the diff heading
   - the proposed `rule_block` — a complete, syntactically valid unit in the target rule-set's own native syntax (e.g. an `if:`/`then:`/`confidence:` block for `routing-rules`), verbatim-appendable, additive-only (never an edit to an existing rule)
   - a one-line, plain-English `why`
   - the `evidence` list — the `link` values (no brackets) of the >=2 corrections justifying this group
4. Write the group(s) to a temp JSON file (a list of `{slug, rule_block, why, evidence, confidence?}` objects — `confidence` is your self-assessed confidence in the grouping, defaults to `Medium` if omitted), then run:

```bash
python3 <path-to-goals-os-engine>/scripts/rule_learning.py --brain "<path-to-brain>" propose --ruleset "<ruleset>" --groups-file "<path-to-json>"
```

This writes each non-duplicate group as a diff into `inbox/rule-diffs/{date}-{ruleset}.md` (matching `protocols/rule-diff-review.md`'s format exactly), logs a `propose-rule-diff` Action Log entry per diff written, and bumps this Routine's row in `config/routine-state.md`. A group is silently skipped (reported, not written) if it's a duplicate of an already-pending, already-applied, or already-rejected diff for that ruleset — safe to re-run without checking state first.
5. **Report back:** how many diffs were written vs skipped (and why, for each skip). Never tick `Approve`/`Reject` yourself, and never edit `config/{ruleset}.md` directly — point to `/rule-diff-review` (or `Dashboard.md`'s `## Pending review` section) for Kelvin to decide.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the minimal rule-set contract, the >=2-correction proposal trigger, the diff shape, and the de-dup rules (reusing `protocols/rule-diff-review.md`'s `diff_key()` unmodified); `scripts/rule_learning.py` is the portable, runtime-agnostic implementation of every deterministic part; this file supplies only the in-session similarity judgement — the same kind of step `triage-plan`'s Pass B established as the Adapter's job, not a script's.
