#!/usr/bin/env python3
"""Materialise config/ and one Area in a Brain — the deterministic half of onboarding.

Implements protocols/onboarding.md (v0). The interview itself (asking the
user which areas they want, agent names/tone) is the Adapter's job; this
script only writes files, and never overwrites one that already exists —
safe to re-run any number of times, including once per additional area.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import log_action  # noqa: E402  (dogfoods the Action Log Protocol, ticket 03)

MODEL_ROUTING = """---
type: config
config: model-routing
---

# Model routing

Default model for Capability agent tasks (PRD §4.2 — model choices are
declared per-task here, never baked into a Protocol).

| Task type | Model |
|---|---|
| default | claude-sonnet-5 |
| reasoning-heavy | claude-opus-4-8 |

Edit this table to change routing. No Engine logic reads these names
directly — each Adapter interprets this file in its own idiom.
"""

AUTONOMY_POLICY = """---
type: config
config: autonomy-policy
---

# Autonomy policy

Brain-level graduation defaults (ADR-0006). Per-action-type overrides can
be added to this file as the system matures.

| Setting | Default | Meaning |
|---|---|---|
| review-window-days | {review_window_days} | Internal & reversible action types: an unreviewed entry older than this counts as approved. |
| graduation-min-sessions | {graduation_min_sessions} | Minimum distinct days/sessions of validated feedback an action type needs before graduating (temporal-spread requirement, ADR-0006 amendment). |

Outward-facing / hard-to-reverse action types never graduate on silence —
explicit validation only, regardless of these defaults.
"""

ROUTINE_STATE = """---
type: config
config: routine-state
---

# Routine state

Last-run timestamp per Routine (Engine manifest, ADR-0007, PRD §8). The
heartbeat due-check reads this at session start. `never` means the
Routine hasn't run yet in this Brain — machine-updated on completion,
don't hand-edit the "Last run" column.

| Routine | Cadence | Last run |
|---|---|---|
| Capture sweep | continuous/hourly | never |
| Triage | on new raw / daily | never |
| Execute | on approval | never |
| Dashboard | morning | never |
| Planning session | weekly / on demand | never |
| Weekly Review | weekly | never |
| Coaching session | monthly | never |
| Goal review | quarterly / on demand | never |
| Upgrade review | fortnightly | never |
| Architecture review | quarterly | never |
| Version control | daily | never |
| Metrics pulse | weekly | never |
"""

AREA_NOTE = """---
type: area
agent: {area_agent}
tags: [area]
---

# {area_name}

## Standard
What "good enough" looks like in this area — fill in with {area_agent}
during your first planning session.

## Current goals
-

## Related
-
"""

AREA_MEMORY = """# {area_agent} — memory

Continuity notes {area_agent} reads before each session. Empty until the
first planning session.

## Session log
"""


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "area"


def ensure_file(path: Path, content: str) -> bool:
    """Write content only if the file doesn't exist. Returns True if created."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def onboard(brain_path: Path, area_name: str, area_agent: str, area_slug: str,
            review_window_days: int, graduation_min_sessions: int) -> dict:
    created, skipped = [], []

    def track(rel_path: str, content: str):
        target = brain_path / rel_path
        if ensure_file(target, content):
            created.append(rel_path)
        else:
            skipped.append(rel_path)

    track("config/model-routing.md", MODEL_ROUTING)
    track("config/autonomy-policy.md", AUTONOMY_POLICY.format(
        review_window_days=review_window_days,
        graduation_min_sessions=graduation_min_sessions,
    ))
    track("config/routine-state.md", ROUTINE_STATE)
    track(f"areas/{area_slug}/{area_name}.md", AREA_NOTE.format(
        area_name=area_name, area_agent=area_agent,
    ))
    track(f"areas/{area_slug}/_memory.md", AREA_MEMORY.format(area_agent=area_agent))

    return {"created": created, "skipped": skipped}


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--area-name", required=True, help='e.g. "Work"')
    p.add_argument("--area-agent", default=None, help="Defaults to --area-name if omitted")
    p.add_argument("--area-slug", default=None, help="Defaults to a slugified --area-name")
    p.add_argument("--review-window-days", type=int, default=3)
    p.add_argument("--graduation-min-sessions", type=int, default=5)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    area_agent = args.area_agent or args.area_name
    area_slug = args.area_slug or slugify(args.area_name)

    result = onboard(
        brain_path, args.area_name, area_agent, area_slug,
        args.review_window_days, args.graduation_min_sessions,
    )

    print(f"Created: {result['created'] or '(none)'}")
    print(f"Skipped (already existed): {result['skipped'] or '(none)'}")

    summary = (
        f"Onboarding run for area '{args.area_name}'. "
        f"Created {len(result['created'])} file(s), "
        f"skipped {len(result['skipped'])} already present."
    )
    entry = log_action.build_entry(
        actor="Onboarding Protocol",
        trigger="onboarding run",
        action_type="onboarding",
        action=summary,
        confidence="High",
        outcome=f"created={result['created']}; skipped={result['skipped']}",
        input_link="protocols/onboarding.md",
    )
    date_str = dt.datetime.now().strftime("%Y-%m-%d")
    log_action.append_entry(brain_path, date_str, entry)
    print("Onboarding run logged to the Action Log.")


if __name__ == "__main__":
    main()
