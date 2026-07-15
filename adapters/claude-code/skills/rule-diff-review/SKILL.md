---
name: rule-diff-review
description: Review pending rule-diff batch files — surface open diffs for a decision, then apply whichever Approve/Reject boxes Kelvin has ticked (append the rule block for an approval, log-only for a rejection), archiving the batch once every diff in it is decided. Never ticks a checkbox itself. Use when the user wants to review rule-diff proposals or has ticked Approve/Reject on one.
allowed-tools:
  - Bash
  - Read
triggers:
  - review rule diffs
  - /rule-diff-review
---

# rule-diff-review

The Claude Code binding for `protocols/rule-diff-review.md`. All the logic — parsing diff sections, appending an approved rule block additive-only, logging Action Log entries, archiving a fully-resolved batch file — lives in `scripts/rule_diff_review.py`. This skill only surfaces open batch files, calls the script once Kelvin has ticked a decision, and relays the result. It never ticks `Approve` or `Reject` itself — same discipline as Triage Plan approval.

## What to do

1. **Surfacing (no ticks yet).** If asked to review or show pending rule diffs, sweep `inbox/rule-diffs/*.md` for files with `status: pending` (or check `Dashboard.md`'s `## Pending review` section, which already lists them). Read each open batch file and present every diff's rule block, **Why**, and **Evidence** links so Kelvin can decide — do not run the script yet if nothing has been ticked.
2. **Applying decisions.** Once Kelvin has ticked `Approve` or `Reject` on one or more diffs in a batch file (himself, or per his explicit instruction this session), run:

```bash
python3 <path-to-goals-os-engine>/scripts/rule_diff_review.py --brain "<path-to-brain>" --batch "<path-to-batch-file-or-relative-to-brain>"
```

If no specific file was named and multiple batch files have ticked-but-unprocessed boxes, run it once per file.

3. **Report back:** how many diffs were applied, how many rejected, and relay any errors verbatim (a malformed diff — missing rule block, missing rationale, fewer than two evidence links — or both boxes ticked at once; none of these crash the run, but they need Kelvin's attention to fix the batch file by hand). If the batch was fully resolved, tell Kelvin it's been archived to `archive/rule-diffs/`; if diffs remain undecided, tell him it's still open in `inbox/rule-diffs/`.
4. **Idempotent by design** — re-running against a batch file where every ticked diff has already been processed (marked `(applied)`/`(logged)`) reports zero applied/rejected and makes no further changes. Safe to re-invoke without checking state first.

## Contract this Adapter fulfils (ADR-0002)

The Protocol defines the file format, the de-dup key ticket 07's proposal-writer must use, and the Approve/Reject lifecycle; `scripts/rule_diff_review.py` is the portable, runtime-agnostic implementation; this file is only the Claude Code binding. This skill never invents a third decision state, never edits a rule-set file directly (only the script does, via additive-only append), and never ticks a box on Kelvin's behalf.
