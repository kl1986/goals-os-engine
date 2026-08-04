"""PROTOTYPE — throwaway. Mobile editing gestures against a Triage Plan.

THE QUESTION
============
The origin ticket asked whether a Triage Plan Row's checkbox is *tappable* in
Obsidian on iOS. That is one gesture, and it needs a real device. The larger
question, which no test and no device check answers, is whether the task-list
Row shape holds up as a **workflow**: approve a run, notice one is wrong,
correct its destination, execute, come back tomorrow when new captures have
landed. That is a sequence of edits, and the interesting failures live in the
transitions between them, not in any single one.

So this module models the *user's* side, not the engine's. Each function is a
gesture a thumb can perform on a phone — including the clumsy ones Obsidian
makes easy (auto-indent on Enter, saving mid-edit, deleting the wrong line).
The engine's side is already built and tested; what has never been driven
end-to-end is a plausible sequence of human edits against it.

Pure by construction: every gesture is `plan_text -> plan_text`, and `derive()`
reports what the three real consumers (Execute, the pending-work nudge, the
Dashboard) would each see. No I/O lives here — the TUI shell owns the scratch
Brain and calls the real `execute_plan` for the one gesture that needs it.

WHAT TO WATCH FOR
=================
Three known frictions are reachable from this module, deliberately. They are
the point, not bugs in the prototype:

  * `clear_destination` leaves a Row mid-edit with a blank destination. Obsidian
    autosaves. A nightly Execute against that state now refuses the whole Plan
    loudly — feel whether "loud refusal" is the right answer or merely the safe
    one.
  * `edit_heading` is silently ineffective and reverted on the next write. That
    is the accepted cost of ADR-0031's amendment. Feel whether it is tolerable
    or whether bulk re-route by heading needs building.
  * `delete_capture_line` followed by an auto-indented sibling reproduces the
    one open defect on this branch — a Row silently swallowed. Not reachable by
    any code path, only by hand. Feel how likely that hand-edit actually is.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import execute  # noqa: E402
import triage  # noqa: E402


# ---------------------------------------------------------------- observation

def derive(text: str) -> dict:
    """What each of the three real consumers sees, from one Plan's text.

    They are listed separately on purpose: the whole reason Row parsing stayed
    line-local (ADR-0031) is so these three cannot drift. If a gesture ever
    makes them disagree, that is the finding.
    """
    rows = execute.parse_plan_rows(text)
    problems = execute.check_row_blocks(text)
    return {
        "rows": rows,
        "problems": problems,
        # Execute acts only on a bare [x]; [ ] is pending, [x] (done) is spent.
        "execute_would_act_on": [r["n"] for r in rows if r["approve"] == "[x]"],
        # The nudge's split — mirrors triage_pending.row_is_pending.
        "nudge_awaiting_pass_b": [
            r["n"] for r in rows
            if r["approve"].strip().startswith("[ ]")
            and r["destination"].strip().lower() == "unmatched"
        ],
        "nudge_awaiting_execute": [
            r["n"] for r in rows
            if r["approve"].strip().startswith("[ ]")
            and r["destination"].strip().lower() != "unmatched"
        ],
        # The Dashboard's counts — mirrors dashboard._pending_plan_summary.
        "dashboard_ticked": sum(
            1 for r in rows if r["approve"] in ("[x]", "[x] (done)")
        ),
        "dashboard_pending": sum(1 for r in rows if r["approve"] == "[ ]"),
        "groups": re.findall(r"^## (.*)$", text, re.MULTILINE),
    }


# ------------------------------------------------------------------- gestures
# Every one of these is something a thumb does. They return new text and never
# touch disk.

def _map_row_lines(text: str, n: str, fn):
    """Apply `fn` to the task line of Row `n`. Rows are addressed by their
    printed number, which is what the user sees and taps."""
    out = []
    for line in text.splitlines():
        m = execute.ROW_RE.match(line)
        if m and m.group("n") == str(n):
            line = fn(line, m)
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def tap_checkbox(text: str, n) -> str:
    """Tap one checkbox. Toggles [ ] <-> [x]. An already-executed Row
    ((done)/(dispatched)) is left alone — Execute would ignore it anyway."""
    def toggle(line, m):
        if m.group("marker"):
            return line
        tick = m.group("tick")
        start, end = m.span("tick")
        return line[:start] + ("[ ]" if tick == "[x]" else "[x]") + line[end:]
    return _map_row_lines(text, n, toggle)


def tap_run(text: str, heading: str) -> str:
    """Tick every un-executed Row under one `## heading` in one sweep — the
    bulk gesture the whole change exists to enable. Note this walks the
    *document*, which is exactly what a thumb does; the engine never does."""
    out, current, changed = [], None, []
    for line in text.splitlines():
        hm = execute.HEADING_RE.match(line)
        if hm:
            current = hm.group("heading")
        m = execute.ROW_RE.match(line)
        if (m and current is not None
                and current.strip().lower() == heading.strip().lower()
                and not m.group("marker") and m.group("tick") == "[ ]"):
            start, end = m.span("tick")
            line = line[:start] + "[x]" + line[end:]
            changed.append(m.group("n"))
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def retype_destination(text: str, n, destination: str) -> str:
    """Correct a Row's destination in place — one edit, no block-moving. This
    is the gesture the ADR-0031 amendment exists to restore."""
    def rewrite(line, m):
        start, end = m.span("destination")
        return line[:start] + destination + line[end:]
    return _map_row_lines(text, n, rewrite)


def clear_destination(text: str, n) -> str:
    """The mid-edit state: destination cleared, new one not yet typed, and
    Obsidian has autosaved. Reachable on the main correction path."""
    return retype_destination(text, n, "")


def edit_heading(text: str, old: str, new: str) -> str:
    """Rename a `## heading`, as if to bulk re-route everything under it.
    Now silently ineffective — the next write regenerates it from the Rows."""
    return re.sub(
        rf"^## {re.escape(old)}[ \t]*$", f"## {new}", text, flags=re.MULTILINE
    )


def autoindent_row(text: str, n, spaces: int = 2) -> str:
    """Obsidian indents the next line when you press Enter inside a list. A
    Row nudged right used to vanish from all three consumers at once; the
    parser now tolerates it. Confirm that in `derive`."""
    return _map_row_lines(text, n, lambda line, m: " " * spaces + line)


def delete_capture_line(text: str, n) -> str:
    """Fat-finger a swipe-delete on a Row's capture wikilink. With a glued
    sibling below, this reproduces the one open defect on this branch."""
    out, hit, dropped = [], False, False
    for line in text.splitlines():
        m = execute.ROW_RE.match(line)
        if m:
            hit = m.group("n") == str(n)
        elif hit and not dropped and execute.CAPTURE_LINE_RE.match(line.strip()):
            dropped = True
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def unglue(text: str) -> str:
    """Restore the blank line between Row blocks — the thing that makes the
    glued-sibling defect unreachable in practice."""
    return regroup(text)


def new_capture_arrives(text: str, destination: str, preview: str) -> str:
    """Overnight: Triage appends a Row for a capture that landed since. Uses
    the real writer, so numbering and placement are the engine's, not mine."""
    n = triage.next_row_number(text)
    block = triage.build_row_block(
        n, f"inbox/raw/email/{n:04d}-overnight.md", preview,
        "Pass A", destination, "High", "a1b2c3d4",
    )
    return triage.insert_row_block(text, destination, block)


def regroup(text: str) -> str:
    """What every write does now — headings regenerated from each Row's own
    destination. Exposed as its own gesture so the tidy-up is visible rather
    than hidden inside Execute."""
    return execute.regroup_plan(text)


GESTURES = [
    ("t", "tap a checkbox",            "tap_checkbox"),
    ("T", "tap a whole run (heading)", "tap_run"),
    ("d", "retype a destination",      "retype_destination"),
    ("c", "clear a destination",       "clear_destination"),
    ("h", "rename a heading",          "edit_heading"),
    ("i", "auto-indent a Row",         "autoindent_row"),
    ("k", "delete a capture line",     "delete_capture_line"),
    ("n", "overnight: new capture",    "new_capture_arrives"),
    ("g", "regroup (what a write does)", "regroup"),
]
