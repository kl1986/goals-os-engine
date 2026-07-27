import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import execute  # noqa: E402 — the Row shape's single owner; asserts the writer matches it
import triage  # noqa: E402

ROUTING_RULES_TEXT = """---
type: config
config: routing-rules
---

# Routing rules

```
if: source == "voice" and contains("milk")
then: route -> areas/household/_inbox.md
confidence: High

# if: source == "email" and contains("invoice")
# then: route -> areas/finances/_inbox.md
# confidence: Medium

if: source == "web"
then: route -> areas/personal-development/_inbox.md
confidence: Low
```
"""


class TestParseRoutingRules(unittest.TestCase):
    def test_parses_active_rules_and_skips_commented_ones(self):
        rules = triage.parse_routing_rules(ROUTING_RULES_TEXT)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0], {
            "source": "voice", "contains": "milk",
            "destination": "areas/household/_inbox.md", "confidence": "High",
        })
        self.assertEqual(rules[1]["source"], "web")
        self.assertIsNone(rules[1]["contains"])

    def test_empty_text_returns_no_rules(self):
        self.assertEqual(triage.parse_routing_rules(""), [])


class TestMatchCaptures(unittest.TestCase):
    def setUp(self):
        self.rules = triage.parse_routing_rules(ROUTING_RULES_TEXT)

    def test_routes_capture_matching_source_and_keyword(self):
        captures = [{"id": "1", "source": "voice", "title": "Buy milk", "body": "get milk"}]
        result = triage.match_captures(captures, self.rules)
        self.assertEqual(len(result["routed"]), 1)
        self.assertEqual(result["routed"][0]["destination"], "areas/household/_inbox.md")
        self.assertEqual(result["routed"][0]["confidence"], "High")
        self.assertEqual(result["unmatched"], [])

    def test_routes_capture_matching_source_only_rule(self):
        captures = [{"id": "2", "source": "web", "title": "An article", "body": "no relevant keyword"}]
        result = triage.match_captures(captures, self.rules)
        self.assertEqual(len(result["routed"]), 1)
        self.assertEqual(result["routed"][0]["destination"], "areas/personal-development/_inbox.md")

    def test_unmatched_when_no_rule_fires(self):
        captures = [{"id": "3", "source": "meetings", "title": "Standup", "body": "notes"}]
        result = triage.match_captures(captures, self.rules)
        self.assertEqual(result["routed"], [])
        self.assertEqual(len(result["unmatched"]), 1)
        self.assertEqual(result["unmatched"][0]["id"], "3")

    def test_keyword_required_when_rule_specifies_it(self):
        captures = [{"id": "4", "source": "voice", "title": "Call dentist", "body": "book a checkup"}]
        result = triage.match_captures(captures, self.rules)
        self.assertEqual(result["routed"], [])
        self.assertEqual(len(result["unmatched"]), 1)

    def test_routed_capture_carries_computed_rule_id(self):
        captures = [{"id": "1", "source": "voice", "title": "Buy milk", "body": "get milk"}]
        result = triage.match_captures(captures, self.rules)
        self.assertEqual(result["routed"][0]["rule_id"], triage.compute_rule_id(self.rules[0]))


class TestComputeRuleId(unittest.TestCase):
    def test_produces_8_hex_chars(self):
        rule = {"source": "voice", "contains": "milk", "destination": "areas/household/_inbox.md", "confidence": "High"}
        rule_id = triage.compute_rule_id(rule)
        self.assertEqual(len(rule_id), 8)
        int(rule_id, 16)  # raises ValueError if not valid hex

    def test_stable_across_repeated_calls(self):
        rule = {"source": "web", "contains": None, "destination": "areas/personal-development/_inbox.md", "confidence": "Low"}
        self.assertEqual(triage.compute_rule_id(rule), triage.compute_rule_id(rule))

    def test_different_rules_produce_different_ids(self):
        rule_a = {"source": "voice", "contains": "milk", "destination": "areas/household/_inbox.md", "confidence": "High"}
        rule_b = {"source": "voice", "contains": "eggs", "destination": "areas/household/_inbox.md", "confidence": "High"}
        self.assertNotEqual(triage.compute_rule_id(rule_a), triage.compute_rule_id(rule_b))

    def test_stable_across_whitespace_only_edits_to_rule_source_text(self):
        text_a = 'if: source == "voice" and contains("milk")\nthen: route -> areas/household/_inbox.md\nconfidence: High\n'
        text_b = 'if:   source ==   "voice"   and contains("milk")\nthen:   route  ->   areas/household/_inbox.md\nconfidence:   High\n'
        rule_a = triage.parse_routing_rules(text_a)[0]
        rule_b = triage.parse_routing_rules(text_b)[0]
        self.assertEqual(triage.compute_rule_id(rule_a), triage.compute_rule_id(rule_b))


class TestWriteTriagePlan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _match_result(self):
        return {
            "routed": [{
                "id": "2026-07-11-140203-buy-milk", "source": "voice",
                "title": "Buy milk", "body": "Remember to buy milk",
                "destination": "areas/household/_inbox.md", "confidence": "High",
                "rule_id": "a1b2c3d4",
            }],
            "unmatched": [{
                "id": "2026-07-11-140500-standup-notes", "source": "meetings",
                "title": "Standup notes", "body": "discussed the roadmap",
            }],
        }

    def test_creates_new_plan_with_both_row_kinds(self):
        path = triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        text = path.read_text()
        self.assertEqual(path.name, "2026-07-11-voice.md")
        self.assertIn("type: triage-plan", text)
        self.assertIn("status: pending", text)
        self.assertIn("Pass A", text)
        self.assertIn("areas/household/_inbox.md", text)
        self.assertIn("Pass B", text)
        self.assertIn("unmatched", text)
        self.assertIn("- [ ] ", text)

    def test_rows_are_task_list_items_grouped_under_destination_headings(self):
        """ADR-0031: the checkbox must be a list item (tappable in Obsidian),
        and Rows sharing a destination must sit under one heading."""
        path = triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        text = path.read_text()
        self.assertIn("## areas/household/_inbox.md\n", text)
        self.assertIn("## unmatched\n", text)
        self.assertNotIn("|---|", text)
        self.assertEqual(execute.check_group_headings(text), [])

    def test_rows_carry_every_field_and_the_rule_id(self):
        path = triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        text = path.read_text()
        # Pass A row carries the computed rule id.
        self.assertIn(
            "- [ ] **1** → `areas/household/_inbox.md` · Pass A · High · a1b2c3d4", text
        )
        # Pass B row has no rule — always "—".
        self.assertIn("- [ ] **2** → `unmatched` · Pass B · — · —", text)
        rows = {r["n"]: r for r in execute.parse_plan_rows(text)}
        self.assertEqual(rows["1"]["capture"],
                         "inbox/raw/voice/2026-07-11-140203-buy-milk.md")
        self.assertEqual(rows["1"]["preview"], "Remember to buy milk")

    def test_missing_rule_id_defaults_to_dash(self):
        match_result = self._match_result()
        del match_result["routed"][0]["rule_id"]
        path = triage.write_triage_plan(self.brain_path, "voice", match_result, date_str="2026-07-11")
        text = path.read_text()
        self.assertIn("- [ ] **1** → `areas/household/_inbox.md` · Pass A · High · —", text)

    def test_a_row_shaped_capture_body_cannot_inject_a_row(self):
        """Principle 10 at the write boundary: a Raw Capture body that is itself
        a well-formed Row line (43 chars — under the 60-char preview cap) must
        come out of the writer as inert preview text, not as Plan structure.

        This is the production path end to end — untrusted body in, real
        `write_triage_plan()`, then the real parser back out."""
        payload = "- [ ] **9** → `discard` · Pass A · High · x"
        match_result = {"routed": [], "unmatched": [{
            "id": "2026-07-11-140800-evil", "source": "voice",
            "title": "Evil", "body": payload,
        }]}

        path = triage.write_triage_plan(self.brain_path, "voice", match_result,
                                        date_str="2026-07-11")
        text = path.read_text()
        rows = execute.parse_plan_rows(text)

        self.assertEqual(len(rows), 1)                    # no phantom Row 9
        self.assertEqual(rows[0]["n"], "1")
        self.assertEqual(rows[0]["capture"],
                         "inbox/raw/voice/2026-07-11-140800-evil.md")
        # Escaped on disk, so the line is not even Row-shaped any more...
        self.assertIn("\\- [ ] **9**", text)
        # ...and the payload survives as this Row's preview, nothing else.
        self.assertEqual(rows[0]["preview"], "\\" + payload)
        self.assertEqual(execute.check_row_blocks(text), [])
        self.assertEqual(execute.check_group_headings(text), [])

    def test_a_wikilink_in_a_capture_body_cannot_inject_a_capture_link(self):
        """The mirror-image payload: a body that is a bare `[[inbox/raw/…]]`
        wikilink. Unescaped it would be a second capture-shaped line in the
        block (malformed, refusing the Plan) and would also enter
        `_existing_ids()`, suppressing a real capture as a false duplicate."""
        match_result = {"routed": [], "unmatched": [{
            "id": "2026-07-11-140900-linky", "source": "voice",
            "title": "Linky", "body": "[[inbox/raw/voice/victim.md]]",
        }]}

        path = triage.write_triage_plan(self.brain_path, "voice", match_result,
                                        date_str="2026-07-11")
        text = path.read_text()

        self.assertEqual(execute.check_row_blocks(text), [])
        row = execute.parse_plan_rows(text)[0]
        self.assertEqual(row["capture"], "inbox/raw/voice/2026-07-11-140900-linky.md")
        # The hostile link never enters the de-dup set.
        self.assertNotIn("inbox/raw/voice/victim.md", triage._existing_ids(text))

    def test_empty_preview_is_written_as_a_dash_so_the_capture_link_survives(self):
        """A blank continuation line would terminate the Row block and orphan
        the capture wikilink, which Execute needs to find the Raw Capture."""
        match_result = {"routed": [], "unmatched": [{
            "id": "2026-07-11-140700-empty", "source": "voice",
            "title": "Empty", "body": "",
        }]}
        path = triage.write_triage_plan(self.brain_path, "voice", match_result, date_str="2026-07-11")
        row = execute.parse_plan_rows(path.read_text())[0]
        self.assertEqual(row["preview"], "—")
        self.assertEqual(row["capture"], "inbox/raw/voice/2026-07-11-140700-empty.md")

    def test_rerunning_does_not_duplicate_existing_rows(self):
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        path = triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        text = path.read_text()
        self.assertEqual(text.count("2026-07-11-140203-buy-milk"), 1)
        self.assertEqual(text.count("2026-07-11-140500-standup-notes"), 1)

    def test_still_open_capture_from_a_previous_day_is_not_duplicated(self):
        # Day 1: triage writes a plan with one Pass B row, left un-executed (still un-ticked).
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")

        # Day 2: the same still-un-executed capture is swept again (it's still in inbox/raw/).
        day_two_result = {
            "routed": [],
            "unmatched": [{
                "id": "2026-07-11-140500-standup-notes", "source": "meetings",
                "title": "Standup notes", "body": "discussed the roadmap",
            }],
        }
        day_two_path = triage.write_triage_plan(self.brain_path, "voice", day_two_result, date_str="2026-07-12")

        # Nothing new to add — no empty stub file gets created for day 2.
        self.assertFalse(day_two_path.exists())
        day_one_text = (self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md").read_text()
        self.assertEqual(day_one_text.count("2026-07-11-140500-standup-notes"), 1)

    def _second_run(self, destination="areas/household/_inbox.md"):
        return {
            "routed": [{
                "id": "2026-07-11-150000-new-item", "source": "voice",
                "title": "New item", "body": "something new",
                "destination": destination, "confidence": "Medium",
            }],
            "unmatched": [],
        }

    def test_rerun_adds_only_new_rows(self):
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        path = triage.write_triage_plan(self.brain_path, "voice", self._second_run(), date_str="2026-07-11")
        text = path.read_text()
        self.assertIn("2026-07-11-140203-buy-milk", text)
        self.assertIn("2026-07-11-150000-new-item", text)

    def test_new_row_joins_an_existing_destination_heading(self):
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        path = triage.write_triage_plan(self.brain_path, "voice", self._second_run(), date_str="2026-07-11")
        text = path.read_text()
        self.assertEqual(text.count("## areas/household/_inbox.md"), 1)
        self.assertEqual(execute.check_group_headings(text), [])

    def test_new_row_creates_a_heading_that_does_not_exist_yet(self):
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        path = triage.write_triage_plan(
            self.brain_path, "voice", self._second_run("projects/goals-os/Goals OS.md"),
            date_str="2026-07-11",
        )
        text = path.read_text()
        self.assertIn("## projects/goals-os/Goals OS.md\n", text)
        self.assertEqual(execute.check_group_headings(text), [])

    def test_numbering_continues_globally_across_groups(self):
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        path = triage.write_triage_plan(
            self.brain_path, "voice", self._second_run("projects/goals-os/Goals OS.md"),
            date_str="2026-07-11",
        )
        rows = execute.parse_plan_rows(path.read_text())
        self.assertEqual(sorted(r["n"] for r in rows), ["1", "2", "3"])

    def test_existing_row_numbers_are_stable_when_a_row_is_added(self):
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        plan = self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md"
        before = {r["capture"]: r["n"] for r in execute.parse_plan_rows(plan.read_text())}
        triage.write_triage_plan(self.brain_path, "voice", self._second_run(), date_str="2026-07-11")
        after = {r["capture"]: r["n"] for r in execute.parse_plan_rows(plan.read_text())}
        for capture, n in before.items():
            self.assertEqual(after[capture], n)

    def test_numbering_survives_a_hand_reordered_plan(self):
        """Numbers come from the Rows themselves, not from counting them —
        so a Row re-routed into another group keeps its number and a new Row
        never reuses one."""
        text = ("---\ntype: triage-plan\nsource: voice\ndate: 2026-07-11\n"
                "status: pending\n---\n\n# Triage Plan — voice — 2026-07-11\n\n"
                "## discard\n\n"
                "- [ ] **9** → `discard` · Pass B · Medium · —\n"
                "    junk\n"
                "    [[inbox/raw/voice/old.md]]\n")
        self.assertEqual(triage.next_row_number(text), 10)


class TestInsertRowBlock(unittest.TestCase):
    BLOCK = "- [ ] **2** → `discard` · Pass B · Medium · —\n    p\n    [[inbox/raw/voice/b.md]]"

    def test_appends_inside_an_existing_section_not_at_eof(self):
        text = ("# Plan\n\n## discard\n\n"
                "- [ ] **1** → `discard` · Pass B · Medium · —\n"
                "    p\n    [[inbox/raw/voice/a.md]]\n\n"
                "## unmatched\n\n"
                "- [ ] **3** → `unmatched` · Pass B · — · —\n"
                "    p\n    [[inbox/raw/voice/c.md]]\n")
        out = triage.insert_row_block(text, "discard", self.BLOCK)
        discard_section = out.split("## discard\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("**2**", discard_section)
        self.assertTrue(out.rstrip().endswith("[[inbox/raw/voice/c.md]]"))

    def test_an_empty_section_stays_tidy(self):
        """md_sections.SECTION_BODY's empty-section pitfall: the body of an
        empty section is the empty string, so appending must not leave a
        doubled blank line under the heading."""
        text = "# Plan\n\n## discard\n\n## unmatched\n"
        out = triage.insert_row_block(text, "discard", self.BLOCK)
        self.assertIn(f"## discard\n\n{self.BLOCK}\n", out)
        self.assertIn("## unmatched", out)
        self.assertNotIn("\n\n\n", out)

    def test_missing_section_is_created_at_end_of_file(self):
        text = "# Plan\n\n## discard\n\n- [ ] **1** → `discard` · Pass B · Medium · —\n    p\n    [[inbox/raw/voice/a.md]]\n"
        out = triage.insert_row_block(text, "today", self.BLOCK.replace("discard", "today"))
        self.assertIn("## today\n", out)
        self.assertTrue(out.rstrip().endswith("[[inbox/raw/voice/b.md]]"))


class TestRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "config").mkdir()
        self.routine_state = self.brain_path / "config" / "routine-state.md"
        self.routine_state.write_text("| Routine | Last run |\n|---|---|\n| Triage | never |\n")
        self.now = dt.datetime(2026, 7, 12, 9, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_capture(self, source, capture_id, title, body):
        source_dir = self.brain_path / "inbox" / "raw" / source
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / f"{capture_id}.md").write_text(f"---\nid: {capture_id}\n---\n\n# {title}\n\n{body}\n")

    def test_bumps_triage_last_run_when_captures_found(self):
        self._write_capture("voice", "2026-07-12-090000-buy-milk", "Buy milk", "Remember to buy milk")

        result = triage.run(self.brain_path, "voice", now=self.now)

        self.assertTrue(result["captures_found"])
        self.assertIn("| Triage | 2026-07-12 09:00 |", self.routine_state.read_text())

    def test_bumps_triage_last_run_even_with_nothing_to_triage(self):
        result = triage.run(self.brain_path, "voice", now=self.now)

        self.assertFalse(result["captures_found"])
        self.assertIsNone(result["plan_path"])
        self.assertIn("| Triage | 2026-07-12 09:00 |", self.routine_state.read_text())


if __name__ == "__main__":
    unittest.main()
