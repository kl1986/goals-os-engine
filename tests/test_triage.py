import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import triage  # noqa: E402

ROUTING_RULES_TEXT = """---
type: config
config: routing-rules
---

# Routing rules

```
if: source == "voice" and contains("milk")
then: route -> areas/home/_inbox.md
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
            "destination": "areas/home/_inbox.md", "confidence": "High",
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
        self.assertEqual(result["routed"][0]["destination"], "areas/home/_inbox.md")
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
                "destination": "areas/home/_inbox.md", "confidence": "High",
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
        self.assertIn("areas/home/_inbox.md", text)
        self.assertIn("Pass B", text)
        self.assertIn("unmatched", text)
        self.assertIn("[ ]", text)

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

    def test_rerun_adds_only_new_rows(self):
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        second = {
            "routed": [{
                "id": "2026-07-11-150000-new-item", "source": "voice",
                "title": "New item", "body": "something new",
                "destination": "areas/home/_inbox.md", "confidence": "Medium",
            }],
            "unmatched": [],
        }
        path = triage.write_triage_plan(self.brain_path, "voice", second, date_str="2026-07-11")
        text = path.read_text()
        self.assertIn("2026-07-11-140203-buy-milk", text)
        self.assertIn("2026-07-11-150000-new-item", text)


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
