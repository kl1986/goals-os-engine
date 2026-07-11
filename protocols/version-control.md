# Protocol: Version control (v0)

A daily Routine that commits and pushes the Brain's changes with a generated (non-LLM) checkpoint message, and tags a revertable/cherry-pickable point — PRD §8's "commit, push, off-site backup; checkpoints for revert/cherry-pick," implemented using only the Brain's existing private git remote (ADR-0003).

## Off-site backup

"Off-site backup" means `git push` to the private remote the Brain was cloned from. No secondary target (S3 mirror, rclone, etc.) is built — explicitly out of scope. If the Brain doesn't have a remote configured, `git push` fails and the routine reports that plainly; it does not silently no-op or invent a fallback.

## What it does

1. `git status --porcelain` — if the tree is clean, **no-op**: no commit, no tag, nothing written. This is the routine's idle state on most invocations.
2. Otherwise: bump `config/routine-state.md`'s `Version control` row to the current timestamp *before* staging, so the checkpoint commit records its own run.
3. `git add -A`, then commit with a generated message — `Brain checkpoint {date} — {n} file(s) changed`, where `n` comes from the porcelain count. Never an LLM summary; deterministic and reproducible.
4. `git push`.
5. `git tag brain-{YYYY-MM-DD-HHMM}`, then push the tag too (if the branch push succeeded) — this is the "checkpoint for revert/cherry-pick": `git checkout brain-2026-07-11-2215` or `git cherry-pick` against it later, same as any git tag.

## Adapter binding

See [`adapters/claude-code/skills/version-control/`](../adapters/claude-code/skills/version-control/).

## Non-goals (v0)

- No automatic unattended scheduling — this Routine fires via the Heartbeat nudge (a manual skill invocation) or direct invocation only. A real scheduler binding is a later Adapter-layer addition (ADR-0007 layer 2).
- No secondary off-site backup target beyond the Brain's existing private git remote.
- No LLM-generated commit messages — the message is derived mechanically from `git status --porcelain`.
