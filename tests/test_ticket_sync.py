import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import ticket_sync  # noqa: E402

REAL_BRAIN = Path(
    "/Users/kelvinlee/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault"
)
REAL_TASKS_ROOT = REAL_BRAIN / "tasks"


TICKET_TEXT = """---
status: backlog
type: task
priority:
component: v2-shippable-core
parent:
assignee:
github:
goal:
created:
resolved:
---

# Config & Security Audit

## Description
Body content, untouched by status get/set.
"""


class TestGetTicketStatus(unittest.TestCase):
    def test_reads_status_from_frontmatter(self):
        self.assertEqual(ticket_sync.get_ticket_status(TICKET_TEXT), "backlog")

    def test_returns_none_when_no_status_field(self):
        self.assertIsNone(ticket_sync.get_ticket_status("# No frontmatter here\n"))


class TestSetTicketStatus(unittest.TestCase):
    def test_updates_status_value_only(self):
        new_text = ticket_sync.set_ticket_status(TICKET_TEXT, "done")
        self.assertEqual(ticket_sync.get_ticket_status(new_text), "done")
        # Body content and every other frontmatter field survive untouched.
        self.assertIn("# Config & Security Audit", new_text)
        self.assertIn("Body content, untouched by status get/set.", new_text)
        self.assertIn("component: v2-shippable-core", new_text)


KANBAN_TEXT = """---

kanban-plugin: board

---

## Backlog

- [ ] [[goals-os-3-config-security-audit]] Audit config, json files, and gitignore
- [ ] [[goals-os-6-plugin-development]] Plugin & skill development


## Prioritised



## In Progress



## Done

- [x] [[goals-os-1-daily-note-polish]] Fix Daily Note


## Deprioritized





%% kanban:settings
```
{"kanban-plugin":"board","list-collapse":[false,null]}
```
%%
"""


class TestParseKanban(unittest.TestCase):
    def test_parses_cards_by_column(self):
        board = ticket_sync.parse_kanban(KANBAN_TEXT)
        backlog_ids = [c["ticket_id"] for c in board["columns"]["Backlog"]]
        self.assertEqual(
            backlog_ids,
            ["goals-os-3-config-security-audit", "goals-os-6-plugin-development"],
        )
        done = board["columns"]["Done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["ticket_id"], "goals-os-1-daily-note-polish")
        self.assertTrue(done[0]["checked"])
        self.assertEqual(done[0]["summary"], "Fix Daily Note")
        self.assertEqual(board["columns"]["Prioritised"], [])

    def test_unchecked_card_has_checked_false(self):
        board = ticket_sync.parse_kanban(KANBAN_TEXT)
        card = board["columns"]["Backlog"][0]
        self.assertFalse(card["checked"])
        self.assertEqual(card["summary"], "Audit config, json files, and gitignore")


class TestRenderKanbanRoundTrip(unittest.TestCase):
    def test_render_after_parse_preserves_every_card(self):
        board = ticket_sync.parse_kanban(KANBAN_TEXT)
        rendered = ticket_sync.render_kanban(board)
        reparsed = ticket_sync.parse_kanban(rendered)
        self.assertEqual(reparsed, board)
        # Plugin settings footer must survive the round trip verbatim.
        self.assertIn('"kanban-plugin":"board"', rendered)


class TestMoveCard(unittest.TestCase):
    def test_moves_card_between_columns_and_flips_checked_state(self):
        board = ticket_sync.parse_kanban(KANBAN_TEXT)
        moved = ticket_sync.move_card(board, "goals-os-3-config-security-audit", "Done")
        self.assertTrue(moved)
        backlog_ids = [c["ticket_id"] for c in board["columns"]["Backlog"]]
        self.assertNotIn("goals-os-3-config-security-audit", backlog_ids)
        done_ids = [c["ticket_id"] for c in board["columns"]["Done"]]
        self.assertIn("goals-os-3-config-security-audit", done_ids)
        moved_card = next(c for c in board["columns"]["Done"] if c["ticket_id"] == "goals-os-3-config-security-audit")
        self.assertTrue(moved_card["checked"])
        self.assertEqual(moved_card["summary"], "Audit config, json files, and gitignore")

    def test_returns_false_when_ticket_not_on_board(self):
        board = ticket_sync.parse_kanban(KANBAN_TEXT)
        moved = ticket_sync.move_card(board, "goals-os-99-nonexistent", "Done")
        self.assertFalse(moved)

    def test_noop_when_already_in_target_column(self):
        board = ticket_sync.parse_kanban(KANBAN_TEXT)
        moved = ticket_sync.move_card(board, "goals-os-1-daily-note-polish", "Done")
        self.assertFalse(moved)


class TestTasksSubpath(unittest.TestCase):
    def test_tasks_root_is_at_the_brain_root_not_under_a_project(self):
        # ADR-0012's "goals-os project root" language was resolved by Kelvin
        # to mean the vault root — tasks/ sits alongside areas/, projects/,
        # config/, not nested under projects/goals-os/.
        self.assertEqual(ticket_sync.TASKS_SUBPATH, ("tasks",))


@unittest.skipUnless(REAL_TASKS_ROOT.is_dir(), "real Brain tasks/ tree not present")
class RealFixtureTestCase(unittest.TestCase):
    """Copies the real, migrated tasks/ tree (15 goals-os tickets +
    kanban.md) into a tmp dir shaped like a Brain, per ticket 16's
    instruction to fixture against real migrated data without mutating it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        dest = self.brain_path / "projects" / "goals-os" / "tasks"
        dest.parent.mkdir(parents=True)
        shutil.copytree(REAL_TASKS_ROOT, dest)
        self.tasks_root = dest

    def tearDown(self):
        self._tmp.cleanup()


class TestFindTicketPath(RealFixtureTestCase):
    def test_finds_a_real_migrated_ticket(self):
        path = ticket_sync.find_ticket_path(self.tasks_root, "goals-os-3-config-security-audit")
        self.assertIsNotNone(path)
        self.assertEqual(path.name, "goals-os-3-config-security-audit.md")

    def test_returns_none_for_unknown_ticket_id(self):
        self.assertIsNone(ticket_sync.find_ticket_path(self.tasks_root, "goals-os-999-nope"))


class TestSyncBoardToTickets(RealFixtureTestCase):
    def test_rewrites_frontmatter_to_match_board_column(self):
        # goals-os-3 sits in Backlog on the real board; force its
        # frontmatter out of sync with that, as if someone hand-edited it.
        ticket_path = ticket_sync.find_ticket_path(self.tasks_root, "goals-os-3-config-security-audit")
        ticket_path.write_text(ticket_sync.set_ticket_status(ticket_path.read_text(), "done"))

        changed = ticket_sync.sync_board_to_tickets(self.tasks_root)

        changed_ids = {c["ticket_id"] for c in changed}
        self.assertIn("goals-os-3-config-security-audit", changed_ids)
        self.assertEqual(ticket_sync.get_ticket_status(ticket_path.read_text()), "backlog")

    def test_ticket_already_matching_its_column_is_left_untouched(self):
        ticket_path = ticket_sync.find_ticket_path(self.tasks_root, "goals-os-1-daily-note-polish")
        before = ticket_path.read_text()

        changed = ticket_sync.sync_board_to_tickets(self.tasks_root)

        changed_ids = {c["ticket_id"] for c in changed}
        self.assertNotIn("goals-os-1-daily-note-polish", changed_ids)
        self.assertEqual(ticket_path.read_text(), before)


class TestSyncTicketsToBoard(RealFixtureTestCase):
    def test_moves_card_to_match_edited_frontmatter_status(self):
        # goals-os-3 sits in Backlog on the real board; edit its frontmatter
        # status directly, as an agent would, and expect the card to move.
        ticket_path = ticket_sync.find_ticket_path(self.tasks_root, "goals-os-3-config-security-audit")
        ticket_path.write_text(ticket_sync.set_ticket_status(ticket_path.read_text(), "prioritised"))

        moved = ticket_sync.sync_tickets_to_board(self.tasks_root)

        moved_ids = {m["ticket_id"] for m in moved}
        self.assertIn("goals-os-3-config-security-audit", moved_ids)

        board = ticket_sync.parse_kanban((self.tasks_root / "kanban.md").read_text())
        backlog_ids = [c["ticket_id"] for c in board["columns"]["Backlog"]]
        prioritised_ids = [c["ticket_id"] for c in board["columns"]["Prioritised"]]
        self.assertNotIn("goals-os-3-config-security-audit", backlog_ids)
        self.assertIn("goals-os-3-config-security-audit", prioritised_ids)

    def test_card_already_in_matching_column_is_left_untouched(self):
        before = (self.tasks_root / "kanban.md").read_text()
        moved = ticket_sync.sync_tickets_to_board(self.tasks_root)
        self.assertEqual(moved, [])
        self.assertEqual((self.tasks_root / "kanban.md").read_text(), before)


if __name__ == "__main__":
    unittest.main()
