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
        self.assertIn("rules:", text)
        self.assertIn("areas/household/_inbox.md", text)
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

    def test_rows_carry_every_field_and_the_rule_id(self):
        path = triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        text = path.read_text()
        self.assertIn(
            "- [ ] Remember to buy milk → `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]", text
        )
        self.assertIn("rules:", text)
        self.assertIn("rule: a1b2c3d4", text)
        rows = {r["n"]: r for r in execute.parse_plan_rows(text)}
        self.assertEqual(rows["1"]["capture"],
                         "inbox/raw/voice/2026-07-11-140203-buy-milk.md")
        self.assertEqual(rows["1"]["preview"], "Remember to buy milk")

    def test_missing_rule_id_defaults_to_dash(self):
        match_result = self._match_result()
        del match_result["routed"][0]["rule_id"]
        path = triage.write_triage_plan(self.brain_path, "voice", match_result, date_str="2026-07-11")
        text = path.read_text()
        self.assertIn("rule: —", text)

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
        self.assertEqual(rows[0]["preview"], "\\" + payload.replace("→", "->"))
        self.assertEqual(execute.check_row_blocks(text), [])

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
        self.assertEqual(text.count("[[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]"), 1)
        self.assertEqual(text.count("[[inbox/raw/meetings/2026-07-11-140500-standup-notes.md]]"), 1)

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

    def test_new_row_creates_a_heading_that_does_not_exist_yet(self):
        triage.write_triage_plan(self.brain_path, "voice", self._match_result(), date_str="2026-07-11")
        path = triage.write_triage_plan(
            self.brain_path, "voice", self._second_run("projects/goals-os/Goals OS.md"),
            date_str="2026-07-11",
        )
        text = path.read_text()
        self.assertIn("## projects/goals-os/Goals OS.md\n", text)

    def test_a_hand_rerouted_row_converges_on_the_next_write(self):
        """Pass B re-routing is a single in-place edit of the Row line
        (ADR-0031). The heading is never compared, so the misplaced Row is not
        an error — the next write regroups it rather than leaving the Plan to
        accumulate Rows under stale headings."""
        path = triage.write_triage_plan(self.brain_path, "voice", self._match_result(),
                                        date_str="2026-07-11")
        path.write_text(path.read_text().replace(
            "→ `unmatched`", "→ `areas/household/_inbox.md`"))

        triage.write_triage_plan(self.brain_path, "voice", self._second_run(),
                                 date_str="2026-07-11")

        text = path.read_text()
        self.assertNotIn("## unmatched", text)
        rows_under_household = text.split("## areas/household/_inbox.md\n", 1)[1]
        self.assertEqual(len(execute.parse_plan_rows(rows_under_household)), 3)
        self.assertEqual(execute.regroup_plan(text), text)

    def test_a_blank_destination_row_does_not_grow_the_plan_on_each_write(self):
        """Triage's write path re-groups but never refuses, so `regroup_plan`
        has to be safe on its own here: a Row whose destination a mid-edit save
        left blank must not accumulate `## ` lines every time a new capture
        arrives."""
        path = triage.write_triage_plan(self.brain_path, "voice", self._match_result(),
                                        date_str="2026-07-11")
        path.write_text(path.read_text().replace("→ `unmatched`", "→ ``"))

        sizes = []
        for i in range(3):
            triage.write_triage_plan(self.brain_path, "voice", {
                "routed": [], "unmatched": [{
                    "id": f"2026-07-11-16000{i}-later", "source": "voice",
                    "title": f"Later {i}", "body": "something else",
                }],
            }, date_str="2026-07-11")
            text = path.read_text()
            sizes.append(len(text.splitlines()) - 6 * (i + 1))  # minus each new Row

        self.assertEqual(len(set(sizes)), 1, f"plan grew beyond its Rows: {sizes}")
        self.assertNotIn("## \n", path.read_text())

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
        # First row's position is unchanged under document-order derivation
        self.assertEqual(after["inbox/raw/voice/2026-07-11-140203-buy-milk.md"], before["inbox/raw/voice/2026-07-11-140203-buy-milk.md"])

    def test_numbering_survives_a_hand_reordered_plan(self):
        text = ("---\ntype: triage-plan\nsource: voice\ndate: 2026-07-11\n"
                "status: pending\n---\n\n# Triage Plan — voice — 2026-07-11\n\n"
                "## discard\n\n"
                "- [ ] junk → `discard` [[inbox/raw/voice/old.md]]\n")
        self.assertEqual(triage.next_row_number(text), 2)


class TestInsertRowBlock(unittest.TestCase):
    BLOCK = "- [ ] p → `discard` [[inbox/raw/voice/b.md]]"

    def test_appends_inside_an_existing_section_not_at_eof(self):
        text = ("# Plan\n\n## discard\n\n"
                "- [ ] p → `discard` [[inbox/raw/voice/a.md]]\n\n"
                "## unmatched\n\n"
                "- [ ] p → `unmatched` [[inbox/raw/voice/c.md]]\n")
        out = triage.insert_row_block(text, "discard", self.BLOCK)
        discard_section = out.split("## discard\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("inbox/raw/voice/b.md", discard_section)
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


class TestDiscardRules(unittest.TestCase):
    """ADR-0034: a routing rule may say a capture is noise, not just where it
    goes — the judgement that was 25 of 32 Rows on the 23/07 email Plan."""

    def test_then_discard_parses_to_the_discard_destination(self):
        rules = triage.parse_routing_rules(
            'if: source == "email" and contains("jobalerts-noreply@linkedin.com")\n'
            "then: discard\n"
            "confidence: High\n"
        )
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["destination"], "discard")
        self.assertEqual(rules[0]["contains"], "jobalerts-noreply@linkedin.com")

    def test_the_two_ways_of_writing_a_discard_rule_share_one_id(self):
        """`then: discard` and `then: route -> discard` are one rule written
        two ways — same parsed destination, same Execute behaviour — so the id
        that answers "which rule fired" must be the same for both."""
        base = 'if: source == "email" and contains("x")\n'
        discard = triage.parse_routing_rules(base + "then: discard\n")[0]
        routed = triage.parse_routing_rules(base + "then: route -> discard\n")[0]
        self.assertEqual(triage.compute_rule_id(discard),
                         triage.compute_rule_id(routed))

    def test_a_discard_rule_and_a_routing_rule_differ(self):
        base = 'if: source == "email" and contains("x")\n'
        discard = triage.parse_routing_rules(base + "then: discard\n")[0]
        routed = triage.parse_routing_rules(base + "then: route -> areas/home/_inbox.md\n")[0]
        self.assertNotEqual(triage.compute_rule_id(discard),
                            triage.compute_rule_id(routed))

    def test_a_matched_discard_rule_routes_the_capture_at_pass_a(self):
        rules = triage.parse_routing_rules(
            'if: source == "email" and contains("linkedin")\nthen: discard\nconfidence: High\n')
        result = triage.match_captures(
            [{"source": "email", "title": "t", "body": "from linkedin jobs",
              "path": "inbox/raw/email/a.md"}], rules)
        self.assertEqual(len(result["routed"]), 1)
        self.assertEqual(result["routed"][0]["destination"], "discard")
        self.assertEqual(result["unmatched"], [])

    def test_execute_reads_a_pass_a_discard_exactly_as_a_pass_b_one(self):
        self.assertEqual(execute.action_type_for("discard"), "discard-capture")


class TestDiscardGroupIsPinnedLast(unittest.TestCase):
    def test_the_noise_group_sorts_below_every_other_group(self):
        rows = [
            "- [ ] p1 → `discard` [[inbox/raw/email/1.md]]",
            "- [ ] p2 → `areas/home/_inbox.md` [[inbox/raw/email/2.md]]",
        ]
        text = "---\nstatus: pending\n---\n\n# Plan\n\n" + "\n\n".join(rows) + "\n"
        regrouped = execute.regroup_plan(text)
        self.assertLess(regrouped.index("## areas/home/_inbox.md"),
                        regrouped.index("## discard"))
        # Still a fixed point — the pin is a property of the destination, not
        # of the document, so a second pass sorts it last again.
        self.assertEqual(execute.regroup_plan(regrouped), regrouped)


class TestEmailPreview(unittest.TestCase):
    """An email body opens with From/Subject headers, so the generic
    first-N-characters preview spent its whole budget on the From line and
    truncated before the subject — invisible on every email Row."""

    BODY = ('# Ten factors\n\n**From:** "ICAS | CA Weekly" <Update@update.icas.com>\n'
            "**Subject:** Ten factors shaping the UK economy\n"
            "**Date:** 2026-07-28\n")

    def test_composes_sender_and_subject_and_drops_the_address(self):
        # `_sanitize()` still maps a pipe to a slash, so the sender's own `|`
        # comes through as `/` — it goes through the same escaping as any
        # other preview text rather than being trusted for being a header.
        self.assertEqual(triage.preview_for(self.BODY, "email"),
                         "**ICAS / CA Weekly** — Ten factors shaping the UK economy")

    def test_the_subject_survives_where_it_used_to_be_truncated_away(self):
        old = triage._preview(self.BODY)
        self.assertNotIn("Ten factors shaping the UK economy", old)
        self.assertIn("Ten factors shaping the UK economy",
                      triage.preview_for(self.BODY, "email"))

    def test_falls_back_to_the_generic_preview_without_a_subject(self):
        self.assertIsNone(triage.structured_preview("no headers here", "email"))
        self.assertEqual(triage.preview_for("no headers here", "email"),
                         triage._preview("no headers here"))

    def test_no_structured_derivation_for_other_sources(self):
        self.assertIsNone(triage.structured_preview(self.BODY, "text"))

    def test_a_long_sender_cannot_crowd_out_the_subject(self):
        body = ("**From:** " + "N" * 200 + " <a@b.c>\n**Subject:** The subject\n")
        out = triage.preview_for(body, "email")
        self.assertIn("The subject", out)
        self.assertLessEqual(len(out), triage.EMAIL_PREVIEW_LEN)

    def test_a_row_shaped_subject_is_still_inert(self):
        """Principle 10: a Subject header is attacker-controlled exactly as a
        body is, so it goes through the same escaping."""
        body = "**Subject:** - [ ] **9** → `discard` · Pass A · High · x\n"
        out = triage.preview_for(body, "email")
        self.assertFalse(execute.ROW_RE.match(out.strip()))

    def test_a_wikilink_in_a_subject_cannot_inject_a_capture_link(self):
        body = "**Subject:** [[inbox/raw/email/evil.md]]\n"
        out = triage.preview_for(body, "email")
        self.assertNotIn("[[inbox/raw/", out)

    def test_an_arrow_in_a_subject_is_sanitized(self):
        body = "**Subject:** Update → Action required\n"
        out = triage.preview_for(body, "email")
        self.assertNotIn("→", out)
        self.assertIn("->", out)
