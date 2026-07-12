#!/usr/bin/env python3
"""Commission Capability Agent script.

Implements the Action Log logging requirement of protocols/commissioning.md.
Called by the Adapter binding (e.g., the Claude Code `commission` skill)
after a capability agent has completed its task, to record the event in
the Brain's Action Log under the commissioning agent's name.
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import log_action  # noqa: E402


def run(brain_path: Path, commissioning_agent: str, capability_role: str,
        task_summary: str, outcome: str, confidence: str = "High",
        now: dt.datetime = None) -> Path:
    """Log one commission event to the Action Log."""
    now = now or dt.datetime.now()

    actor_str = f"{capability_role} (via {commissioning_agent})"

    entry = log_action.build_entry(
        actor=actor_str,
        trigger="Commissioned Capability Agent",
        action_type="commission-capability",
        action=f"Commissioned {capability_role}: {task_summary}",
        confidence=confidence,
        outcome=outcome,
        time_str=now.strftime("%H:%M"),
    )
    log_path = log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)
    return log_path


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument("--commissioning-agent", required=True, help='The agent initiating the commission, e.g. "EA" or "Will"')
    p.add_argument("--capability-role", required=True, help='The capability role, e.g. "Researcher"')
    p.add_argument("--task-summary", required=True, help="Short summary of what the capability agent was asked to do")
    p.add_argument("--outcome", required=True, help="Short outcome of the commission, e.g. 'Found 3 relevant sources.'")
    p.add_argument("--confidence", required=True, choices=log_action.CONFIDENCE_LEVELS,
                    help="The commissioning agent's confidence in the result")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    log_path = run(
        brain_path, args.commissioning_agent, args.capability_role,
        args.task_summary, args.outcome, confidence=args.confidence,
    )
    print(f"Commission event logged to: {log_path}")


if __name__ == "__main__":
    main()
