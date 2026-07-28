# Goals OS user guide

Goals OS separates the reusable **Engine** from your private **Brain**. The
Engine supplies protocols, schemas, scripts, and Runtime adapters; the Brain
holds your captures, plans, knowledge, configuration, and Action Log. This
guide describes the daily workflow in a Brain after it has been created from
the Brain Template and [onboarded](../protocols/onboarding.md).

The important boundary is simple: a capture is immutable evidence; a plan is
your approval surface; the Wiki is a rebuildable synthesis. The Engine does
not contain, or ship with, any personal data.

## Daily lifecycle

```text
Capture -> Raw Capture -> Triage Plan -> your tick -> Execute -> archive -> Compile -> Wiki
                         (inbox/triage/)                    (archive/inbox/)  (wiki/)
```

### 1. Capture

A capture is stamped into `inbox/raw/<source>/` as a Markdown **Raw Capture**.
It has a stable ID and frontmatter recording its source; it is never edited or
deleted. The only later change is a move to `archive/inbox/<source>/` after a
successful Execute step. If something was captured incorrectly, capture a new
correction rather than altering the original. See the full
[Capture protocol](../protocols/capture.md).

For a direct manual capture, use the Runtime's Capture binding (the Claude
Code reference binding is [documented here](../adapters/claude-code/skills/capture/SKILL.md)).
Adapters and source plugins can also create the same Raw Capture format. The
source value carries routing intent, so it is configured by the Brain rather
than restricted to a fixed Engine list.

### 2. Triage

Triage turns unprocessed Raw Captures from one source into a reviewable plan
at `inbox/triage/<date>-<source>.md`. It does **not** file, discard, or alter
a capture. This is the safety boundary for untrusted incoming content.

Triage has two passes:

1. **Pass A** applies the deterministic rules in `config/routing-rules.md`.
2. **Pass B** asks the Runtime to classify only the unmatched rows. It can
   propose a destination, but cannot approve it.

Every plan row needs your explicit `[x]` tick before it can be executed,
regardless of its confidence. Rows are task-list items grouped under a
`## <destination>` heading, so ticking one is a tap on its checkbox in
Obsidian and a run of rows sharing a destination can be approved together.
Correcting a row is one edit: change the destination on the row line itself.
The heading is regenerated from the rows beneath it, so a corrected row sits
under the right one again after the next run — you never move it by hand.
Review or correct the proposed destination in the plan, then tick only the
rows you want processed. A literal `discard` destination is a deliberate,
reviewable decision to retain only the archived source record. Details and
the plan format are in the [Triage protocol](../protocols/triage.md).

### 3. Execute

Execute reads only ticked rows. For the standard internal actions, it files a
dated link to the existing destination or discards the item, moves the Raw
Capture to `archive/inbox/<source>/`, marks the row done with a trailing
`(done)`, and appends a schema-valid entry to `log/YYYY-MM-DD.md`. Unticked
and failed rows remain open; re-running Execute does not repeat completed
rows. It also regroups the plan under its destination headings on the way
out. If a row can't be read as an actionable row — its capture wikilink
missing or duplicated, or its destination left blank mid-edit — Execute
refuses the whole plan and acts on nothing until you fix it.

The standard destinations are an existing Area or Project inbox, a
section-targeted Person Hub, `today` for the daily note, or `discard`.
Source-specific plugins may run a post-action hook only after this
human-approved, archived outcome. See the [Execute protocol](../protocols/execute.md)
and the [Action Log schema](../protocols/action-log-schema.md).

### 4. Knowledge synthesis (Compile)

The Librarian's **Compile** routine reads only `archive/inbox/<source>/` plus
validated feedback. It never reads the live Raw queue, so a new capture
cannot affect the Wiki before it has passed through your Triage and Execute
approval path.

Compile incrementally resynthesises the affected flat Wiki articles in
`wiki/` and maintains `wiki/_index.md` plus dated source links. Because the
Wiki is derived from archived Raw Captures and feedback, it can be rebuilt;
do not treat Wiki articles as the place to preserve a private manual edit.
Run a full rebuild only after the explicit confirmation required by the
[Wiki protocol](../protocols/wiki.md).

## The six reference-Brain drop zones

The six documented drop zones are deliberately split between three
Capture-sweep folders inside the Brain and three specialist file queues next
to it. A drop zone is an ingress location, not an Engine-wide source enum.

| Drop zone | Normal destination | What happens next |
|---|---|---|
| `inbox/_dropzone/meetings/` | `inbox/raw/meetings/` | Capture sweep stamps each file as a Raw Capture, then Triage creates a plan under `inbox/triage/`. |
| `inbox/_dropzone/text/voice/` | `inbox/raw/text/` with `input-modality: voice` | Capture sweep stamps each file as a Raw Capture, then the normal Triage → Execute route applies. |
| `inbox/_dropzone/text/typed/` | `inbox/raw/text/` | Capture sweep stamps each file as a Raw Capture, then the normal Triage → Execute route applies. |
| `Files/dropzone/Expenses/` | Specialist expenses capability | This is a file-processing queue, not an automatic Triage source. |
| `Files/dropzone/Homework/` | Specialist homework capability | This is a file-processing queue, not an automatic Triage source. |
| `Files/dropzone/Recipes/` | Specialist recipe capability | This is a file-processing queue, not an automatic Triage source. |

The `Files/dropzone/` queues sit beside the Brain under `Files/`. The
Dashboard shows their outstanding item counts as a nudge; it does not process
them. Email and YouTube are **source plugins**, not drop zones: they stamp
their own Raw Captures into `inbox/raw/email/` and `inbox/raw/youtube/`, then
use the same Triage → Execute path as every other capture source. Other
Runtime adapters or Library plugins can add sources, but they should stamp the
Engine's Raw Capture contract before relying on the standard pipeline.

## Starting a session: Heartbeat and due routines

Start a session with **Heartbeat**. It is a reporter, not a scheduler or
dispatcher: it compares three sources and tells you which implemented
Routines are due.

| Source | Owns |
|---|---|
| Engine [`protocols/routines.md`](../protocols/routines.md) | What a Routine is, its Protocol, owner, risk tier, and implementation status. |
| Brain `config/schedules.md` | When a Routine runs. This is the only timing source. |
| Brain `config/routine-state.md` | When a Routine last ran. |

Only an implemented Routine with an enabled `fixed-interval` Schedule can be
overdue. `poll` schedules are event-triggered and are intentionally excluded
from the due-check. Heartbeat never runs an overdue Routine by itself: choose
which reported work to invoke. The reference Claude Code adapter can be run
with:

```bash
python3 <path-to-goals-os-engine>/scripts/heartbeat.py --brain <path-to-brain>
```

The Brain Template provides a starter schedule, including daily due-checks
for the daily note, Compile, Triage, Dashboard, and other implemented
Routines. A Schedule can also render a launchd Job through the Scheduler
Adapter, but that job is only a trigger; it does not create an unattended
agent session. Read [Schedules](../protocols/schedules.md) before changing
timing, and use `sync_schedules.py --dry-run` before applying a scheduler
change.

## What belongs where

| Layer | Location | Purpose |
|---|---|---|
| Raw | `inbox/raw/`, then `archive/inbox/` | Immutable captured evidence. |
| Approval | `inbox/triage/` | Mutable, human-ticked proposed routes. |
| Curated | `areas/`, `projects/`, `people/`, configuration | Human-authored decisions, goals, and working context. |
| Knowledge | `wiki/` | Rebuildable concept synthesis with source links. |
| Audit trail | `log/YYYY-MM-DD.md` | Append-only record of agent actions and later feedback. |

This separation is why the Engine can be upgraded without overwriting your
Brain, and why a workflow can be inspected or rebuilt from its source
material. For terminology and the full set of boundaries, see
[CONTEXT.md](../CONTEXT.md).

## Where to go next

- Use the [Claude Code adapter](../adapters/claude-code/README.md) for the
  reference Runtime commands and skill bindings.
- Read the [protocols directory](../protocols/) when changing workflow
  behaviour; Protocols define behaviour, while Adapters only bind it to a
  Runtime.
- Read the [ADRs](./adr/) before making architecture-level changes.
