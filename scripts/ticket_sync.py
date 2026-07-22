#!/usr/bin/env python3
"""Two-way sync between the global ticket board and per-ticket frontmatter.

Implements ADR-0013: tasks/kanban.md's board columns are the human
drag-and-drop surface, and each ticket file's `status:` YAML frontmatter
field is the machine-readable state. The two are kept consistent by two
one-shot, explicit-direction operations rather than a merge:

- board-to-tickets: a card's column is source of truth; any ticket file
  whose `status:` doesn't match its card's column gets its frontmatter
  rewritten to match (run this after a card is dragged in Obsidian).
- tickets-to-board: a ticket's `status:` field is source of truth; any card
  sitting in the wrong column gets moved to match (run this after an agent
  edits a ticket's frontmatter directly).

There is no persisted "last synced" state, so running both directions in
one pass is not true conflict resolution — it's "board wins, then nothing
is left to move." Pick the direction that matches what actually changed.
"""

import argparse
import re
import sys
from pathlib import Path

TASKS_SUBPATH = ("tasks",)

COLUMNS = ["Backlog", "Prioritised", "In Progress", "Done", "Deprioritized"]

COLUMN_TO_STATUS = {
    "Backlog": "backlog",
    "Prioritised": "prioritised",
    "In Progress": "in-progress",
    "Done": "done",
    "Deprioritized": "deprioritized",
}
STATUS_TO_COLUMN = {v: k for k, v in COLUMN_TO_STATUS.items()}

# Columns whose cards render as ticked checkboxes ("- [x]"); every other
# column renders "- [ ]" regardless of prior state.
CHECKED_COLUMNS = {"Done"}

STATUS_FIELD_RE = re.compile(r'^status:\s*(\S*)\s*$', re.MULTILINE)
CARD_RE = re.compile(r'^- \[( |x)\] \[\[([^\]]+)\]\]\s?(.*)$')
COLUMN_HEADING_RE = re.compile(r'^## (.+?)\s*$')


def get_ticket_status(text: str) -> str | None:
    """Read the `status:` frontmatter field's value, or None if absent."""
    m = STATUS_FIELD_RE.search(text)
    if not m or not m.group(1):
        return None
    return m.group(1)


def set_ticket_status(text: str, new_status: str) -> str:
    """Rewrite the `status:` frontmatter field's value in place. Every other
    line (other frontmatter fields, the body) is left byte-for-byte
    untouched."""
    return STATUS_FIELD_RE.sub(f"status: {new_status}", text, count=1)


def parse_kanban(text: str) -> dict:
    """Parse tasks/kanban.md into {"preamble": str, "columns": {name: [card,
    ...]}, "epilogue": str}. Each card is {"ticket_id", "checked", "summary"}
    — ticket_id is the wikilink target (filename stem), summary is the
    trailing text after the link. Only the five recognized COLUMNS are
    tracked; the `%% kanban:settings ... %%` block (and anything else after
    the last recognized heading's cards) is preserved verbatim as epilogue,
    unparsed, so a round trip never loses the plugin's own state.
    """
    lines = text.split("\n")
    preamble_lines = []
    columns = {name: [] for name in COLUMNS}
    current = None
    epilogue_start = None

    for i, line in enumerate(lines):
        h = COLUMN_HEADING_RE.match(line)
        if h and h.group(1).strip() in COLUMNS:
            current = h.group(1).strip()
            continue
        if line.startswith("%%") and current is not None:
            epilogue_start = i
            break
        if current is None:
            preamble_lines.append(line)
            continue
        m = CARD_RE.match(line)
        if m:
            checked, ticket_id, summary = m.groups()
            columns[current].append({
                "ticket_id": ticket_id,
                "checked": checked == "x",
                "summary": summary.strip(),
            })

    epilogue = "\n".join(lines[epilogue_start:]) if epilogue_start is not None else ""
    return {
        "preamble": "\n".join(preamble_lines),
        "columns": columns,
        "epilogue": epilogue,
    }


def _render_card(card: dict) -> str:
    box = "x" if card["checked"] else " "
    summary = f" {card['summary']}" if card["summary"] else ""
    return f"- [{box}] [[{card['ticket_id']}]]{summary}"


def render_kanban(board: dict) -> str:
    """Inverse of parse_kanban — reconstructs a full kanban.md from the
    structured board. Card order within a column and column order (fixed:
    COLUMNS) are deterministic; the plugin settings epilogue is emitted
    verbatim from whatever parse_kanban captured."""
    parts = [board["preamble"]]
    for name in COLUMNS:
        parts.append(f"## {name}\n")
        cards = board["columns"].get(name, [])
        if cards:
            parts.append("\n".join(_render_card(c) for c in cards))
        parts.append("\n")
    if board.get("epilogue"):
        parts.append(board["epilogue"])
    return "\n".join(parts)


def move_card(board: dict, ticket_id: str, new_column: str) -> bool:
    """Move a card to new_column in place, flipping its checked state to
    match CHECKED_COLUMNS. Returns False (no-op) if the ticket isn't on the
    board at all, or is already in new_column."""
    for name, cards in board["columns"].items():
        for card in cards:
            if card["ticket_id"] == ticket_id:
                if name == new_column:
                    return False
                cards.remove(card)
                card["checked"] = new_column in CHECKED_COLUMNS
                board["columns"][new_column].append(card)
                return True
    return False


def _iter_ticket_files(tasks_root: Path):
    for sub in ("projects", "areas"):
        sub_dir = tasks_root / sub
        if not sub_dir.is_dir():
            continue
        for slug_dir in sorted(sub_dir.iterdir()):
            if slug_dir.is_dir():
                yield from sorted(slug_dir.glob("*.md"))


def find_ticket_path(tasks_root: Path, ticket_id: str) -> Path | None:
    """Locate a ticket file by ID under tasks/projects/*/ or tasks/areas/*/.
    None if no ticket with that filename stem exists."""
    for path in _iter_ticket_files(tasks_root):
        if path.stem == ticket_id:
            return path
    return None


def sync_board_to_tickets(tasks_root: Path) -> list:
    """Board is source of truth. For every card on tasks/kanban.md, rewrite
    its ticket file's `status:` frontmatter to match the card's column if
    it doesn't already. Returns the list of {"ticket_id", "old_status",
    "new_status"} actually rewritten — tickets already in sync aren't
    touched (no needless writes/mtime churn)."""
    kanban_path = tasks_root / "kanban.md"
    board = parse_kanban(kanban_path.read_text())

    changed = []
    for column, cards in board["columns"].items():
        expected_status = COLUMN_TO_STATUS[column]
        for card in cards:
            ticket_path = find_ticket_path(tasks_root, card["ticket_id"])
            if ticket_path is None:
                continue  # card references a ticket file that doesn't exist
            text = ticket_path.read_text()
            current_status = get_ticket_status(text)
            if current_status == expected_status:
                continue
            ticket_path.write_text(set_ticket_status(text, expected_status))
            changed.append({
                "ticket_id": card["ticket_id"],
                "old_status": current_status,
                "new_status": expected_status,
            })
    return changed


def sync_tickets_to_board(tasks_root: Path) -> list:
    """Ticket frontmatter is source of truth. For every ticket file under
    tasks/projects/*/ and tasks/areas/*/, move its card on tasks/kanban.md
    to the column matching its `status:` field if it isn't there already.
    A ticket not yet on the board is left alone (Publish's job, not
    sync's). Returns the list of {"ticket_id", "old_column", "new_column"}
    actually moved; the board file is only rewritten if something moved."""
    kanban_path = tasks_root / "kanban.md"
    board = parse_kanban(kanban_path.read_text())

    card_columns = {
        card["ticket_id"]: column
        for column, cards in board["columns"].items()
        for card in cards
    }

    moved = []
    for ticket_path in _iter_ticket_files(tasks_root):
        ticket_id = ticket_path.stem
        status = get_ticket_status(ticket_path.read_text())
        expected_column = STATUS_TO_COLUMN.get(status)
        if expected_column is None:
            continue  # unknown/missing status - not this script's job to fix
        old_column = card_columns.get(ticket_id)
        if old_column is None:
            continue  # not on the board yet
        if move_card(board, ticket_id, expected_column):
            moved.append({
                "ticket_id": ticket_id,
                "old_column": old_column,
                "new_column": expected_column,
            })

    if moved:
        kanban_path.write_text(render_kanban(board))
    return moved


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    p.add_argument(
        "direction",
        choices=["board-to-tickets", "tickets-to-board"],
        help="Which side is source of truth for this run",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    tasks_root = brain_path.joinpath(*TASKS_SUBPATH)
    if not tasks_root.is_dir():
        sys.exit(f"tasks/ root does not exist: {tasks_root}")

    if args.direction == "board-to-tickets":
        changed = sync_board_to_tickets(tasks_root)
        if not changed:
            print("Nothing to sync — every ticket already matches its board column.")
        for c in changed:
            print(f"{c['ticket_id']}: status {c['old_status']} -> {c['new_status']} (matched board)")
    else:
        moved = sync_tickets_to_board(tasks_root)
        if not moved:
            print("Nothing to sync — every card already matches its ticket's status.")
        for m in moved:
            print(f"{m['ticket_id']}: {m['old_column']} -> {m['new_column']} (matched frontmatter)")


if __name__ == "__main__":
    main()
