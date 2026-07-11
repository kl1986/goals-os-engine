# Claude Code Adapter

The reference Adapter (ADR-0002): the thin mapping layer binding the Engine's Protocols onto Claude Code's native skill format. Claude Code is the proof that the Protocol/Adapter split works — other Runtimes (Codex CLI, Gemini CLI) get their own Adapter here later, each implementing the same underlying `../../scripts/` against their own skill/agent/hook format.

**Contract:** an Adapter never contains logic — Protocols define what happens, `scripts/` do anything that needs hard code (deterministic, testable, callable from any Runtime), and the Adapter is just the binding that lets a Runtime discover and invoke that logic in its own idiom. If a skill file here starts accumulating actual decision logic, that logic belongs in the Protocol doc or a script instead.

## Skills implemented

| Skill | Protocol | What it does |
|---|---|---|
| [`skills/log-action/`](./skills/log-action/) | [`action-log-schema.md`](../../protocols/action-log-schema.md) | Appends a schema-valid Action Log entry to a Brain's `log/` folder. |
| [`skills/onboard/`](./skills/onboard/) | [`onboarding.md`](../../protocols/onboarding.md) | Interviews the user for one Area, then idempotently materialises `config/` and that Area in a cloned Brain. |
| [`skills/heartbeat/`](./skills/heartbeat/) | [`routines.md`](../../protocols/routines.md) | Reports overdue Routines against the manifest and a Brain's `config/routine-state.md`. Nudge-only. |
| [`skills/capture/`](./skills/capture/) | [`capture.md`](../../protocols/capture.md) | Stamps a manual/text capture into `inbox/raw/<source>/`. |

## Installing into a Brain

A Brain "installs" this Adapter by making its `skills/` discoverable to Claude Code (e.g. as a plugin, or symlinked/copied into the Brain's own `.claude/skills/`). Packaging this as a proper installable plugin is a later ticket — for now, point Claude Code at this folder directly.

## Verifying end-to-end (ticket 04 proof)

```bash
git clone https://github.com/kl1986/goals-os-brain-template.git /tmp/test-brain

python3 scripts/log_action.py \
  --brain /tmp/test-brain \
  --actor "EA" \
  --trigger "Triage (Routine)" \
  --action-type "file-email" \
  --action "Example action" \
  --confidence "High" \
  --outcome "Filed to areas/example/_inbox/"

cat /tmp/test-brain/log/$(date +%F).md   # schema-valid entry, plain markdown
cd /tmp/test-brain && git status --short  # untracked/modified log file — plain, git-diffable
```

Run against a fresh clone of the public `goals-os-brain-template` on 11/07/2026: two entries appended correctly (in order, no overwrite), each matching the 8-field schema in `action-log-schema.md`, and visible as a normal `git diff` on `log/`.
