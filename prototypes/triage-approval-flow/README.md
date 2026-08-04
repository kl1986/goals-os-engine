# PROTOTYPE — Triage approval flow end-to-end

**Throwaway.** Lives on branch `prototype/triage-approval-flow`, cut from
`build/triage-plan-approval-is-not-tappable-in-obsidian-mobile`. Not for main.

```
./venv/bin/python prototypes/triage-approval-flow/run.py
```

## The question

[[triage-plan-approval-is-not-tappable-in-obsidian-mobile]] asked whether a
Row's checkbox is *tappable* in Obsidian on iOS. That is one gesture and it
needs a real device. The larger question, which no test and no device check
answers, is whether the task-list Row shape holds up as a **workflow** —
approve a run, notice one is wrong, correct its destination, execute, come back
tomorrow when new captures have landed. The interesting failures live in the
transitions between gestures, not in any single one.

Deliberately **not** a UI prototype: the real renderer is Obsidian, so a web
mock would report on the mock, not on Obsidian. What is prototypable is the
sequence of edits and what the engine does in response.

## Shape

- `gestures.py` — pure, portable. Each function is `plan_text -> plan_text` and
  models something a thumb does, including the clumsy things Obsidian makes
  easy (auto-indent on Enter, autosaving mid-edit, deleting the wrong line).
  `derive()` reports what all three real consumers — Execute, the pending-work
  nudge, the Dashboard — would each see, so any drift between them is visible.
- `run.py` — throwaway TUI. Owns the one impure thing: a scratch Brain in a
  temp dir, so `x` runs the **real** `execute_plan` against real files. Wiped
  on quit. Never touches the live Vault.

## Findings

Driven through the three friction paths the build left open.

**1. The mid-edit blank destination is handled well.** `c 5` → `t 5` → `x`
refuses the whole Plan, names row 5, and files nothing. The gesture that gets
you there — clearing a destination before typing the new one, with Obsidian
autosaving underneath you — is on the main correction path, so this mattered.
Loud and safe, and the message tells you what a destination may be.

**2. Renaming a heading is worse than the ADR admits — it reorders your Plan.**
ADR-0031 records that a hand-edit to a heading is "silently ineffective and
reverted on the next write". True, but incomplete. The renamed heading holds no
Rows, so it is dropped; the Rows' real destination is then treated as a *new*
group and appended at the end:

```
before:                   discard, unmatched, areas/ho-lee-fook/_inbox.md
after renaming 'discard': keep,    unmatched, areas/ho-lee-fook/_inbox.md
after the next write:     unmatched, areas/ho-lee-fook/_inbox.md, discard
row order 1,2,3,4,5  ->  4,5,1,2,3
```

Three Rows at the top of the Plan jump below the other two. On a phone,
mid-approval, that is disorienting in a way "your edit was ignored" is not.
Worth either fixing (preserve a renamed group's position) or stating honestly
in the ADR.

**3. The known glued-sibling defect is not reachable through the real flow.**
`k 1` → `i 2` — delete a capture line, then auto-indent the Row below —
produces a **loud refusal**, not the silent swallow, because the writer always
leaves a blank line between Row blocks and the flow never removes it. This
supports leaving that defect filed rather than fixed: you have to glue the Rows
by hand, on purpose, in addition to deleting the capture line.

## Status — answered

All three findings settled. **Finding 2 was fixed** on the implementation
branch as `97ab1c5`: group order now comes from the document position of each
destination's first Row rather than from a matching heading, so renaming or
deleting a heading leaves the group's position and its Rows' order untouched.
Verified back through this prototype — `edit_heading` then `regroup` now
returns the Plan byte-identical, row order `1,2,3,4,5` preserved.

This is the prototype's own justification: the defect was reachable in two
gestures and invisible to 578 passing tests, because it lived in a *sequence*
of edits rather than in any single transformation.

**The device check is still the one thing this cannot substitute for** — see
`projects/goals-os/scratch/Checkbox tap test (Obsidian iOS).md` in the Brain.
