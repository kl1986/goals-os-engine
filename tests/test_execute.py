# -*- coding: utf-8 -*-
import copy
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import execute  # noqa: E402


def row_block(n, capture, preview, route, destination, confidence,
              rule="—", approve="[ ]"):
    """One Row in the ADR-0036 shape: task line with inline wikilink."""
    tick, marker = approve[:3], approve[4:]  # "[x] (done)" -> "[x]", "(done)"
    suffix = f" {marker}" if marker else ""
    destinations = [destination] if isinstance(destination, str) else list(destination)
    task_line = f"- {tick} {preview} → {execute.render_destination_list(destinations)} [[{capture}]]{suffix}"
    is_keeper = any(d.strip().lower() in ("unmatched", "?") for d in destinations)
    if not is_keeper:
        return task_line
    lines = [task_line]
    import triage
    for label, val in triage.DEFAULT_KEEPER_OPTIONS:
        if val:
            lines.append(f"    - [ ] {label} · `{val}`")
        else:
            lines.append(f"    - [ ] {label}")
    return "\n".join(lines)


def plan_text(rows, source, date, status="pending"):
    """A whole Plan: Rows grouped under `## <destination>` headings."""
    grouped = {}
    pass_a_rules = []
    for r in rows:
        grouped.setdefault(r["destination"], []).append(r)
        if r.get("route") == "Pass A" and r.get("rule") and r.get("rule") != "—":
            pass_a_rules.append((Path(r["capture"]).name, r["rule"], r.get("confidence", "High")))
    body = "\n".join(
        f"## {destination}\n\n" + "\n\n".join(row_block(**r) for r in group) + "\n"
        for destination, group in grouped.items()
    )
    fm = f"---\ntype: triage-plan\nsource: {source}\ndate: {date}\nstatus: {status}\n"
    if pass_a_rules:
        fm += "rules:\n"
        for fname, r_id, conf in pass_a_rules:
            fm += f"  {fname}:\n    rule: {r_id}\n    confidence: {conf}\n"
    fm += "---\n\n"
    return fm + f"# Triage Plan — {source} — {date}\n\n" + body


def with_row(rows, n, **changes):
    """A copy of `rows` with row `n`'s fields overridden."""
    updated = copy.deepcopy(rows)
    for r in updated:
        if r["n"] == n:
            r.update(changes)
    return updated


PLAN_ROWS = [
    dict(n=1, capture="inbox/raw/voice/2026-07-11-140203-buy-milk.md",
         preview="Remember to buy milk", route="Pass A",
         destination="areas/household/_inbox.md", confidence="High",
         rule="a1b2c3d4", approve="[x]"),
    dict(n=2, capture="inbox/raw/voice/2026-07-11-140500-junk.md",
         preview="not worth keeping", route="Pass B", destination="discard",
         confidence="Medium", approve="[x]"),
    dict(n=3, capture="inbox/raw/voice/2026-07-11-140600-later.md",
         preview="deal with this later", route="Pass B",
         destination="areas/household/_inbox.md", confidence="Medium"),
]
PLAN_TEXT = plan_text(PLAN_ROWS, "voice", "2026-07-11")

# Three groups, five Rows — the shape the mobile-approval prototype used to
# reproduce the heading-rename reorder. Rows 1-3 sit in the first group, so a
# reorder that appends that group at the end is impossible to miss.
THREE_GROUP_ROWS = [
    dict(n=n, capture=f"inbox/raw/voice/2026-07-11-1402{n:02d}-x.md",
         preview=f"capture {n}", route="Pass A", destination=destination,
         confidence="High")
    for n, destination in enumerate(
        ["discard", "discard", "discard", "unmatched",
         "areas/ho-lee-fook/_inbox.md"], start=1)
]


class TestActionTypeFor(unittest.TestCase):
    def test_discard_destination_is_discard_capture(self):
        self.assertEqual(execute.action_type_for("discard"), "discard-capture")
        self.assertEqual(execute.action_type_for("Discard"), "discard-capture")

    def test_path_destination_is_file_capture(self):
        self.assertEqual(execute.action_type_for("areas/household/_inbox.md"), "file-capture")

    def test_agent_destination_is_agent_dispatched(self):
        self.assertEqual(execute.action_type_for("agent: Researcher"), "agent-dispatched")
        self.assertEqual(execute.action_type_for("Agent: Writer "), "agent-dispatched")

    def test_today_destination_is_file_capture_today(self):
        self.assertEqual(execute.action_type_for("today"), "file-capture-today")
        self.assertEqual(execute.action_type_for("Today"), "file-capture-today")
        self.assertEqual(execute.action_type_for("  TODAY  "), "file-capture-today")

    def test_file_heading_destination_is_still_file_capture(self):
        # `file#heading` is a `file-capture` sub-form, not a new action type.
        self.assertEqual(
            execute.action_type_for("people/Example Person.md#🗣️ To Discuss"), "file-capture"
        )


class TestSplitDestination(unittest.TestCase):
    def test_plain_file_has_no_heading(self):
        self.assertEqual(
            execute.split_destination("areas/household/_inbox.md"),
            ("areas/household/_inbox.md", None),
        )

    def test_file_hash_heading_splits_into_both_parts(self):
        self.assertEqual(
            execute.split_destination("people/Example Person.md#🗣️ To Discuss"),
            ("people/Example Person.md", "🗣️ To Discuss"),
        )

    def test_whitespace_around_parts_is_trimmed(self):
        self.assertEqual(
            execute.split_destination("  people/Example Person.md # ⏳ Waiting For  "),
            ("people/Example Person.md", "⏳ Waiting For"),
        )


class TestParsePlanRows(unittest.TestCase):
    def _by_number(self, text):
        return {r["n"]: r for r in execute.parse_plan_rows(text)}

    def test_parses_all_three_rows(self):
        rows = self._by_number(PLAN_TEXT)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows["1"]["approve"], "[x]")
        self.assertEqual(rows["2"]["approve"], "[ ]")
        self.assertEqual(rows["3"]["approve"], "[x]")

    def test_parses_dispatched_and_done_rows(self):
        text = (
            row_block(1, "inbox/raw/voice/x.md", "p", "Pass A", "d", "High",
                      "a1b2c3d4", approve="[x] (dispatched)") + "\n\n"
            + row_block(2, "inbox/raw/voice/y.md", "p", "Pass A", "d", "High",
                        approve="[x] (done)") + "\n"
        )
        rows = execute.parse_plan_rows(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["approve"], "[x] (dispatched)")
        self.assertEqual(rows[1]["approve"], "[x] (done)")

    def test_parses_rule_field(self):
        rows = self._by_number(PLAN_TEXT)
        self.assertEqual(rows["1"]["rule"], "a1b2c3d4")
        self.assertEqual(rows["2"]["rule"], "—")
        self.assertEqual(rows["3"]["rule"], "—")

    def test_recovers_capture_and_preview_from_continuation_lines(self):
        rows = self._by_number(PLAN_TEXT)
        self.assertEqual(rows["1"]["capture"],
                         "inbox/raw/voice/2026-07-11-140203-buy-milk.md")
        self.assertEqual(rows["1"]["preview"], "Remember to buy milk")

    def test_row_line_is_parseable_on_its_own(self):
        """Line-locality (ADR-0036): approve/destination/capture/preview
        come off one line, with no heading and no preceding document state."""
        line = "- [ ] preview → `discard` [[inbox/raw/voice/x.md]]\n"
        rows = execute.parse_plan_rows(line)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["destination"], "discard")
        self.assertEqual(rows[0]["approve"], "[ ]")
        self.assertEqual(rows[0]["route"], "Pass B")

    def test_heading_does_not_feed_the_parse(self):
        """A Row under a contradicting heading still parses as its own
        destination — the Row line wins, and the heading is never read."""
        text = ("## areas/household/_inbox.md\n\n"
                + row_block(1, "inbox/raw/voice/x.md", "p", "Pass B", "discard", "Medium"))
        self.assertEqual(execute.parse_plan_rows(text)[0]["destination"], "discard")

    def test_row_re_anchored_to_column_0(self):
        """ROW_RE is anchored to column 0 (^- ) so indented option lines are not
        mis-parsed as sibling Rows."""
        text = "  - [ ] p → `discard` [[inbox/raw/voice/x.md]]\n"
        problems = execute.check_row_blocks(text)
        self.assertEqual(len(problems), 1)
        self.assertIn("unrecognised or legacy Row line", problems[0])

    def test_preview_containing_a_wikilink_is_not_mistaken_for_the_capture(self):
        text = row_block(1, "inbox/raw/voice/x.md", "\\[\\[inbox/raw/voice/other.md\\]\\] said",
                         "Pass B", "discard", "Medium")
        row = execute.parse_plan_rows(text)[0]
        self.assertEqual(row["capture"], "inbox/raw/voice/x.md")

    def test_a_row_shaped_preview_is_not_parsed_as_an_injected_row(self):
        """Principle 10: capture-derived text is content, never Plan structure."""
        payload = "\\- [ ] **9** → `discard`"
        text = ("## discard\n\n"
                + row_block(1, "inbox/raw/email/evil.md", payload,
                            "Pass A", "discard", "High", "e1") + "\n")

        rows = execute.parse_plan_rows(text)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["n"], "1")
        self.assertEqual(rows[0]["capture"], "inbox/raw/email/evil.md")
        self.assertEqual(execute.check_row_blocks(text), [])

    def test_legacy_three_line_block_is_refused(self):
        """Legacy 3-line blocks are refused upfront by check_row_blocks."""
        text = ("- [ ] **1** → `discard` · Pass B · Medium · —\n"
                "    [[inbox/raw/email/other.md]]\n")
        problems = execute.check_row_blocks(text)
        self.assertEqual(len(problems), 1)
        self.assertIn("unrecognised or legacy Row line", problems[0])

    def test_a_well_formed_block_reports_no_problem(self):
        self.assertEqual(execute.check_row_blocks(PLAN_TEXT), [])

    def test_a_blank_destination_is_reported(self):
        """Reachable from the supported correction gesture: Obsidian autosaves,
        so a nightly Execute can see a Row whose destination has been cleared
        but not yet retyped. Not actionable, so it refuses rather than acts."""
        for destination in ("", " ", "   "):
            with self.subTest(destination=destination):
                text = row_block(7, "inbox/raw/voice/x.md", "p", "Pass B",
                                 destination, "Medium")
                problems = execute.check_row_blocks(text)
                self.assertEqual(len(problems), 1)
                self.assertIn("p", problems[0])
                self.assertIn("blank destination", problems[0])


def headings_of(text):
    return [ln[3:].strip() for ln in text.splitlines() if ln.startswith("## ")]


def row_order(text):
    """Row numbers in the order the document presents them — what the user
    scrolls past on a phone, and what a group reorder disturbs."""
    return [r["n"] for r in execute.parse_plan_rows(text)]


def grouping_of(text):
    """`{heading: [row numbers under it]}` — what the Plan actually says about
    where each Row sits, read back off the rendered document."""
    lines = text.splitlines()
    spans = execute._scan_blocks(text)
    grouped = {}
    current_heading = None
    for i, line in enumerate(lines):
        hm = execute.HEADING_RE.match(line)
        if hm:
            current_heading = hm.group("heading").strip()
            grouped.setdefault(current_heading, [])
            continue
        for start, end, row, _ in spans:
            if start == i:
                if current_heading:
                    grouped.setdefault(current_heading, []).append(row["n"])
                break
    return grouped


class TestRegroupPlan(unittest.TestCase):
    """Headings are regenerated output, never compared (ADR-0031)."""

    def test_a_well_grouped_plan_is_unchanged(self):
        self.assertEqual(execute.regroup_plan(PLAN_TEXT), PLAN_TEXT)

    def test_a_row_under_the_wrong_heading_is_moved_under_its_own_destination(self):
        text = PLAN_TEXT.replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
            "→ `discard` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]"
        )
        self.assertEqual(grouping_of(text)["areas/household/_inbox.md"], ["1", "2"])

        regrouped = execute.regroup_plan(text)

        self.assertEqual(grouping_of(regrouped),
                         {"areas/household/_inbox.md": ["1"], "discard": ["2", "3"]})

    def test_an_emptied_heading_is_dropped(self):
        text = PLAN_TEXT.replace(
            "→ `discard` [[inbox/raw/voice/2026-07-11-140500-junk.md]]",
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140500-junk.md]]"
        )
        self.assertIn("discard", headings_of(text))

        regrouped = execute.regroup_plan(text)

        self.assertEqual(headings_of(regrouped), ["areas/household/_inbox.md"])

    def test_a_needed_heading_that_is_absent_is_created(self):
        text = PLAN_TEXT.replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140600-later.md]]",
            "→ `projects/goals-os/Goals OS.md` [[inbox/raw/voice/2026-07-11-140600-later.md]]"
        )
        self.assertNotIn("projects/goals-os/Goals OS.md", headings_of(text))

        regrouped = execute.regroup_plan(text)
        self.assertIn("projects/goals-os/Goals OS.md", headings_of(regrouped))
        self.assertEqual(grouping_of(regrouped)["projects/goals-os/Goals OS.md"], ["2"])

    def test_rows_with_no_headings_at_all_gain_them(self):
        text = "- [ ] p → `discard` [[inbox/raw/voice/a.md]]\n"
        self.assertEqual(execute.regroup_plan(text),
                         "## discard\n\n" + text)

    def test_is_idempotent(self):
        text = PLAN_TEXT.replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
            "→ `discard` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]")
        once = execute.regroup_plan(text)
        self.assertEqual(execute.regroup_plan(once), once)

    def test_preserves_frontmatter_h1_and_prose(self):
        text = PLAN_TEXT.replace(
            "# Triage Plan — voice — 2026-07-11\n",
            "# Triage Plan — voice — 2026-07-11\n\nA note I typed to myself.\n",
        )
        regrouped = execute.regroup_plan(text)
        self.assertTrue(regrouped.startswith(
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-07-11\n"
            "status: pending\nrules:\n  2026-07-11-140203-buy-milk.md:\n    rule: a1b2c3d4\n    confidence: High\n---\n\n"
            "# Triage Plan — voice — 2026-07-11\n\nA note I typed to myself.\n"
        ))

    def test_preserves_prose_inside_a_section_and_keeps_that_heading_alive(self):
        text = PLAN_TEXT.replace("## discard\n\n", "## discard\n\nWhy these go:\n\n")
        regrouped = execute.regroup_plan(
            text.replace("→ `discard`", "→ `areas/household/_inbox.md`")
        )
        self.assertIn("## discard\n\nWhy these go:\n", regrouped)
        self.assertEqual(grouping_of(regrouped)["discard"], [])

    def test_preserves_numbering_tick_state_and_executed_markers(self):
        text = plan_text(
            with_row(PLAN_ROWS, 2, approve="[x] (done)"), "voice", "2026-07-11",
        ).replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
            "→ `discard` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]"
        )
        regrouped = execute.regroup_plan(text)
        parsed = {r["preview"]: r["approve"] for r in execute.parse_plan_rows(regrouped)}
        self.assertEqual(parsed, {
            "Remember to buy milk": "[x]",
            "not worth keeping": "[x] (done)",
            "deal with this later": "[ ]",
        })

    def test_moves_an_indented_row_block_verbatim(self):
        text = PLAN_TEXT.replace(
            "→ `discard` [[inbox/raw/voice/2026-07-11-140500-junk.md]]",
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140500-junk.md]]",
        )
        regrouped = execute.regroup_plan(text)
        self.assertIn(
            "not worth keeping → `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140500-junk.md]]",
            regrouped,
        )
        self.assertEqual(grouping_of(regrouped)["areas/household/_inbox.md"],
                         ["1", "2", "3"])

    def test_group_order_follows_each_destinations_first_row(self):
        text = PLAN_TEXT.replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140600-later.md]]",
            "→ `today` [[inbox/raw/voice/2026-07-11-140600-later.md]]"
        )
        regrouped = execute.regroup_plan(text)
        self.assertEqual(
            headings_of(regrouped),
            ["areas/household/_inbox.md", "today", "discard"],
        )
        self.assertEqual(row_order(regrouped), ["1", "2", "3"])

    def test_a_new_destination_on_the_last_row_appends_its_group(self):
        text = PLAN_TEXT.replace(
            "→ `discard` [[inbox/raw/voice/2026-07-11-140500-junk.md]]",
            "→ `today` [[inbox/raw/voice/2026-07-11-140500-junk.md]]"
        )
        self.assertEqual(
            headings_of(execute.regroup_plan(text)),
            ["areas/household/_inbox.md", "today"],
        )

    def test_renaming_a_heading_keeps_its_group_in_place(self):
        text = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11")
        self.assertEqual(headings_of(text), ["discard", "unmatched", "areas/ho-lee-fook/_inbox.md"])
        self.assertEqual(row_order(text), ["1", "2", "3", "4", "5"])

        regrouped = execute.regroup_plan(text.replace("## discard\n", "## keep\n"))

        self.assertEqual(headings_of(regrouped),
                         ["unmatched", "areas/ho-lee-fook/_inbox.md", "discard"])
        self.assertEqual(row_order(regrouped), ["1", "2", "3", "4", "5"])
        self.assertEqual(regrouped, execute.regroup_plan(text))

    def test_deleting_a_heading_outright_keeps_its_group_in_place(self):
        text = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11")

        regrouped = execute.regroup_plan(text.replace("## discard\n\n", ""))

        self.assertEqual(headings_of(regrouped),
                         ["unmatched", "areas/ho-lee-fook/_inbox.md", "discard"])
        self.assertEqual(row_order(regrouped), ["1", "2", "3", "4", "5"])

    def test_renaming_the_middle_heading_keeps_every_group_in_place(self):
        text = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11")

        regrouped = execute.regroup_plan(text.replace("## unmatched\n", "## sort later\n"))

        self.assertEqual(headings_of(regrouped),
                         ["unmatched", "areas/ho-lee-fook/_inbox.md", "discard"])

    def test_a_heading_kept_alive_by_prose_holds_its_position(self):
        """A heading with prose but no Rows stays where it was, so prose is
        never orphaned or moved into a neighbouring section."""
        text = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11").replace(
            "## unmatched\n", "## unmatched\n\nStill deciding these.\n")
        emptied = text.replace("→ `unmatched`", "→ `discard`")

        regrouped = execute.regroup_plan(emptied)

        self.assertEqual(headings_of(regrouped),
                         ["unmatched", "areas/ho-lee-fook/_inbox.md", "discard"])
        self.assertIn("## unmatched\n\nStill deciding these.\n", regrouped)
        self.assertEqual(grouping_of(regrouped)["unmatched"], [])
        self.assertEqual(execute.regroup_plan(regrouped), regrouped)

    def test_a_plan_with_neither_rows_nor_headings_is_returned_unchanged(self):
        text = "---\nstatus: pending\n---\n\n# Triage Plan\n"
        self.assertEqual(execute.regroup_plan(text), text)

    def test_a_blank_destination_never_emits_a_heading_and_never_grows(self):
        """`## ` is not a heading `HEADING_RE` reads back, so emitting one
        would be re-read as prose and a fresh `## ` emitted below it — two more
        lines every single run, in a file the user is actively editing."""
        for destination in ("", " "):
            with self.subTest(destination=destination):
                text = PLAN_TEXT.replace(
                    "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
                    f"→ `{destination}` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]")
                sizes = []
                for _ in range(6):
                    text = execute.regroup_plan(text)
                    sizes.append(len(text.splitlines()))

                self.assertEqual(len(set(sizes)), 1, f"file grew: {sizes}")
                self.assertNotIn("## \n", text)
                self.assertNotIn("##  ", text)
                # The Row itself survives, ungrouped, with its tick intact.
                rows = {r["n"]: r for r in execute.parse_plan_rows(text)}
                self.assertEqual(len(rows), 3)
                self.assertEqual(rows["1"]["approve"], "[x]")
                self.assertEqual(rows["1"]["capture"],
                                 "inbox/raw/voice/2026-07-11-140203-buy-milk.md")

    def test_a_blank_destination_row_is_held_above_the_groups(self):
        text = execute.regroup_plan(PLAN_TEXT.replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
            "→ `` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]"))
        self.assertLess(text.index("Remember to buy milk"), text.index("## "))
        self.assertEqual(grouping_of(text),
                         {"areas/household/_inbox.md": ["2"], "discard": ["3"]})

    def test_is_idempotent_across_a_sweep_of_disturbed_plans(self):
        """Idempotence is the hard requirement -- both write paths run this on
        every write -- so it is checked over the whole space of disturbances the
        ordering rule touches, not one case. A second pass must be byte-equal,
        and so must a third."""
        base = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11")
        with_prose = base.replace("## unmatched\n", "## unmatched\n\nDeciding.\n")
        cases = {
            "well-grouped": base,
            "heading renamed": base.replace("## discard\n", "## keep\n"),
            "middle heading renamed": base.replace("## unmatched\n", "## later\n"),
            "last heading renamed": base.replace(
                "## areas/ho-lee-fook/_inbox.md\n", "## hlf\n"),
            "heading deleted": base.replace("## discard\n\n", ""),
            "all headings deleted": "".join(
                ln + "\n" for ln in base.splitlines() if not ln.startswith("## ")),
            "new destination mid-plan": base.replace(
                "capture 2 → `discard`", "capture 2 → `today`"),
            "new destination on last row": base.replace(
                "capture 5 → `areas/ho-lee-fook/_inbox.md`", "capture 5 → `today`"),
            "first row re-routed to an existing group below": base.replace(
                "capture 1 → `discard`", "capture 1 → `areas/ho-lee-fook/_inbox.md`"),
            "prose keeps a heading alive": with_prose.replace(
                "→ `unmatched`", "→ `discard`"),
            "prose heading kept alive and renamed": with_prose.replace(
                "→ `unmatched`", "→ `discard`").replace("## discard\n", "## keep\n"),
            "blank destination": base.replace("capture 3 → `discard`", "capture 3 → ``"),
            "headless prose": base.replace(
                "# Triage Plan — voice — 2026-07-11\n",
                "# Triage Plan — voice — 2026-07-11\n\nA stray note.\n"),
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                once = execute.regroup_plan(text)
                twice = execute.regroup_plan(once)
                self.assertEqual(twice, once)
                self.assertEqual(execute.regroup_plan(twice), once)
                # No Row is ever lost, whatever the disturbance.
                self.assertEqual(sorted(row_order(once)), list("12345"))

    def test_the_sweep_of_disturbed_plans_never_reorders_the_groups(self):
        """Every disturbance that only touches *headings* must leave the Rows
        in exactly the document order the user last saw."""
        base = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11")
        headings = ["## discard\n", "## unmatched\n",
                    "## areas/ho-lee-fook/_inbox.md\n"]
        for heading in headings:
            for disturbance in ("renamed", "deleted"):
                with self.subTest(heading=heading.strip(), disturbance=disturbance):
                    text = base.replace(
                        heading, "## renamed by hand\n" if disturbance == "renamed"
                        else "")
                    self.assertEqual(execute.regroup_plan(text),
                                     execute.regroup_plan(base))

    def test_headless_prose_settles_in_one_pass(self):
        """Prose under no heading is hoisted into the preamble — the only
        position for it that a second pass leaves alone."""
        text = PLAN_TEXT.replace(
            "# Triage Plan — voice — 2026-07-11\n",
            "# Triage Plan — voice — 2026-07-11\n\n"
            "- [ ] p → `discard` [[inbox/raw/voice/z.md]]\n\nA stray note.\n",
        )
        once = execute.regroup_plan(text)
        self.assertIn("A stray note.", once)
        self.assertEqual(execute.regroup_plan(once), once)


class TestExecutePlan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "areas" / "household").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "voice").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        for name in ("2026-07-11-140203-buy-milk.md", "2026-07-11-140500-junk.md", "2026-07-11-140600-later.md"):
            (self.brain_path / "inbox" / "raw" / "voice" / name).write_text("---\nraw: true\n---\nbody\n")
        self.plan_path = self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md"
        self.plan_path.write_text(PLAN_TEXT)
        self.now = dt.datetime(2026, 7, 11, 15, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_files_and_discards_ticked_rows_leaves_unticked_alone(self):
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertEqual(len(result["filed"]), 1)
        self.assertEqual(len(result["discarded"]), 1)
        self.assertEqual(result["errors"], [])

        inbox_note = (self.brain_path / "areas" / "household" / "_inbox.md").read_text()
        self.assertIn("buy-milk", inbox_note)
        self.assertIn("Remember to buy milk", inbox_note)

    def test_moves_processed_raw_files_to_archive_leaves_unticked_raw_in_place(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertFalse((self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140203-buy-milk.md").exists())
        self.assertFalse((self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140500-junk.md").exists())
        self.assertTrue((self.brain_path / "archive" / "inbox" / "voice" / "2026-07-11-140203-buy-milk.md").exists())
        self.assertTrue((self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140600-later.md").exists())

    def test_appends_action_log_entries(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        log_text = (self.brain_path / "log" / "2026-07-11.md").read_text()
        self.assertEqual(log_text.count("### "), 2)
        self.assertIn("file-capture", log_text)
        self.assertIn("discard-capture", log_text)

    def test_pass_a_row_with_rule_gets_rule_aware_trigger(self):
        # Row 1 is Pass A with rule id a1b2c3d4 — trigger records which
        # rule fired, not just that a Routine ran.
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        log_text = (self.brain_path / "log" / "2026-07-11.md").read_text()
        self.assertIn("**trigger:** Execute (Routine) — rule a1b2c3d4", log_text)

    def test_pass_b_row_keeps_bare_trigger(self):
        # Row 2 is Pass B (discard) — no rule fired, trigger stays bare.
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        log_text = (self.brain_path / "log" / "2026-07-11.md").read_text()
        entries = log_text.split("### ")
        discard_entry = next(e for e in entries if "discard-capture" in e)
        self.assertIn("**trigger:** Execute (Routine)\n", discard_entry)
        self.assertNotIn("rule a1b2c3d4", discard_entry)

    def test_pass_a_row_without_a_rule_id_keeps_bare_trigger(self):
        # Defensive case: a Pass A row whose rule cell is "—" (e.g. a
        # hand-edited plan) must not produce a malformed trigger.
        self.plan_path.write_text(
            plan_text(with_row(PLAN_ROWS, 1, rule="—"), "voice", "2026-07-11")
        )
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        log_text = (self.brain_path / "log" / "2026-07-11.md").read_text()
        entries = log_text.split("### ")
        file_entry = next(e for e in entries if "file-capture" in e and "discard" not in e)
        self.assertIn("**trigger:** Execute (Routine)\n", file_entry)

    def test_plan_not_archived_while_a_row_remains_unticked(self):
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertFalse(result["plan_executed"])
        self.assertTrue(self.plan_path.exists())
        text = self.plan_path.read_text()
        self.assertIn("status: pending", text)
        self.assertIn(" (done)", text)
        self.assertIn("- [ ] deal with this later", text)  # row 3 still untouched

    def test_marker_is_a_suffix_on_the_task_line_not_a_rewritten_cell(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        text = self.plan_path.read_text()
        self.assertIn(
            "- [x] Remember to buy milk → `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] (done)",
            text,
        )

    def test_rerun_does_not_re_execute_a_done_row(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        inbox_before = (self.brain_path / "areas" / "household" / "_inbox.md").read_text()

        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(result["filed"], [])
        self.assertEqual(result["discarded"], [])
        self.assertEqual(
            (self.brain_path / "areas" / "household" / "_inbox.md").read_text(),
            inbox_before,
        )
        self.assertEqual(self.plan_path.read_text().count("(done)"), 2)

    def test_indented_task_line_is_refused(self):
        # ROW_RE is anchored to column 0 (ADR-0036). An indented task line is
        # refused by check_row_blocks.
        text = PLAN_TEXT.replace(
            "- [x] not worth keeping →", "  - [x] not worth keeping →",
        )
        self.plan_path.write_text(text)

        with self.assertRaises(execute.ExecuteError):
            execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

    def test_in_place_destination_edit_executes_to_the_edited_destination(self):
        # Re-routing is one edit: change the destination on the Row line. Row 1
        # was a file-capture, is now a discard, and still sits under the old
        # heading — which is presentation, so it changes nothing.
        self.plan_path.write_text(PLAN_TEXT.replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
            "→ `discard` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
        ))

        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["filed"], [])
        self.assertEqual(len(result["discarded"]), 2)
        self.assertFalse((self.brain_path / "areas" / "household" / "_inbox.md").exists())
        self.assertTrue(
            (self.brain_path / "archive" / "inbox" / "voice"
             / "2026-07-11-140203-buy-milk.md").exists()
        )

    def test_the_plan_comes_back_regrouped_after_an_in_place_edit(self):
        self.plan_path.write_text(PLAN_TEXT.replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
            "→ `discard` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
        ))

        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        text = self.plan_path.read_text()
        self.assertEqual(grouping_of(text),
                         {"areas/household/_inbox.md": ["1"], "discard": ["2", "3"]})
        self.assertIn("- [x] Remember to buy milk → `discard` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] (done)", text)

    def test_a_row_moved_under_a_wrong_heading_still_executes_to_its_own_destination(self):
        # The mirror case: the Row line is untouched, the *heading* is what a
        # user hand-moved it under. The heading is never read, so the Row files
        # to its own destination — and is moved back on the way out.
        rows = "\n\n".join(row_block(**r) for r in PLAN_ROWS)
        self.plan_path.write_text(
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-07-11\n"
            "status: pending\n---\n\n# Triage Plan — voice — 2026-07-11\n\n"
            "## discard\n\n" + rows + "\n"
        )

        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["filed"], ["inbox/raw/voice/2026-07-11-140203-buy-milk.md"])
        self.assertEqual(result["discarded"], ["inbox/raw/voice/2026-07-11-140500-junk.md"])
        self.assertIn("buy-milk",
                      (self.brain_path / "areas" / "household" / "_inbox.md").read_text())
        self.assertEqual(grouping_of(self.plan_path.read_text()),
                         {"areas/household/_inbox.md": ["1", "2"], "discard": ["3"]})

    def test_regrouping_on_execute_is_idempotent(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        once = self.plan_path.read_text()
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertEqual(self.plan_path.read_text(), once)

    def test_ticked_blank_destination_refuses_instead_of_crashing_mid_run(self):
        """Row 1 is ticked and valid; Row 2 is ticked with a cleared
        destination. `_file_capture` used to resolve that to the Brain root and
        raise an uncaught IsADirectoryError *after* Row 1 was filed, archived
        and logged but *before* the Plan was rewritten — leaving the Plan
        disagreeing with the Action Log about what had happened."""
        text = PLAN_TEXT.replace("→ `discard` [[inbox/raw/voice/2026-07-11-140500-junk.md]]", "→ `` [[inbox/raw/voice/2026-07-11-140500-junk.md]]")
        self.plan_path.write_text(text)

        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertIn("not worth keeping", str(ctx.exception))
        self.assertIn("blank destination", str(ctx.exception))
        self.assertFalse((self.brain_path / "areas" / "household" / "_inbox.md").exists())
        self.assertFalse((self.brain_path / "archive").exists())
        self.assertFalse((self.brain_path / "log").exists())
        self.assertEqual(self.plan_path.read_text(), text)

    def test_repeated_runs_never_grow_a_plan_holding_a_blank_destination(self):
        # Unticked, so nothing executes and nothing refuses on the rows that
        # matter — but execute_plan re-groups on every run regardless.
        self.plan_path.write_text(
            PLAN_TEXT.replace("→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140600-later.md]]",
                              "→ `` [[inbox/raw/voice/2026-07-11-140600-later.md]]")
                     .replace("- [x] ", "- [ ] ")
        )
        sizes = []
        for _ in range(3):
            with self.assertRaises(execute.ExecuteError):
                execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
            sizes.append(len(self.plan_path.read_text().splitlines()))
        self.assertEqual(len(set(sizes)), 1, f"file grew: {sizes}")

    def test_malformed_row_block_still_refuses_the_whole_plan(self):
        # The other refusal class is unchanged: a Row whose capture cannot be
        # read unambiguously stops everything, including the clean ticked rows.
        text = PLAN_TEXT.replace(
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]",
            "→ `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] [[inbox/raw/voice/decoy.md]]",
        )
        self.plan_path.write_text(text)

        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertIn("Remember to buy milk", str(ctx.exception))
        self.assertFalse((self.brain_path / "areas" / "household" / "_inbox.md").exists())
        self.assertFalse((self.brain_path / "archive").exists())
        self.assertFalse((self.brain_path / "log").exists())
        self.assertEqual(self.plan_path.read_text(), text)

    def test_second_run_after_ticking_last_row_archives_plan(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        text = self.plan_path.read_text().replace(
            "- [ ] deal with this later", "- [x] deal with this later",
        )
        self.plan_path.write_text(text)

        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertTrue(result["plan_executed"])
        self.assertFalse(self.plan_path.exists())
        archived_text = result["archived_to"].read_text()
        self.assertIn("status: executed", archived_text)

    def test_missing_raw_capture_reports_error_not_crash(self):
        (self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140203-buy-milk.md").unlink()
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("not found", result["errors"][0])

    def test_unmatched_destination_on_ticked_row_reports_error(self):
        rows = with_row(PLAN_ROWS, 1, route="Pass B", destination="unmatched",
                        confidence="—", rule="—", approve="[x]")
        self.plan_path.write_text(plan_text(rows, "voice", "2026-07-11"))
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("unmatched", result["errors"][0])

    def test_bumps_execute_last_run_when_routine_state_exists(self):
        (self.brain_path / "config").mkdir()
        routine_state = self.brain_path / "config" / "routine-state.md"
        routine_state.write_text("| Routine | Last run |\n|---|---|\n| Execute | never |\n")

        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertIn("| Execute | 2026-07-11 15:00 |", routine_state.read_text())

    def test_agent_dispatched_leaves_raw_capture_and_returns_log_id(self):
        self.plan_path.write_text(plan_text(
            with_row(PLAN_ROWS, 1, destination="agent: Reviewer"),
            "voice", "2026-07-11",
        ))
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        
        self.assertEqual(len(result["agent_dispatched"]), 1)
        dispatched_row = result["agent_dispatched"][0]
        self.assertIn("log_id", dispatched_row)
        
        # Raw capture should NOT be moved to archive
        self.assertTrue((self.brain_path / "inbox" / "raw" / "voice" / "2026-07-11-140203-buy-milk.md").exists())
        self.assertFalse((self.brain_path / "archive" / "inbox" / "voice" / "2026-07-11-140203-buy-milk.md").exists())
        
        # Plan should be updated with a trailing (dispatched) marker
        text = self.plan_path.read_text()
        self.assertIn("- [x] Remember to buy milk → `agent: Reviewer` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]] (dispatched)", text)


TODAY_PLAN_ROWS = [
    dict(n=1, capture="inbox/raw/voice/2026-07-13-090000-call-plumber.md",
         preview="Call the plumber", route="Pass A", destination="today",
         confidence="High", rule="e5f6a7b8", approve="[x]"),
    dict(n=2, capture="inbox/raw/voice/2026-07-13-091000-later.md",
         preview="deal with this later", route="Pass B",
         destination="areas/household/_inbox.md", confidence="Medium"),
]
TODAY_PLAN_TEXT = plan_text(TODAY_PLAN_ROWS, "voice", "2026-07-13")


class TestFileCaptureToday(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "inbox" / "raw" / "voice").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        for name in ("2026-07-13-090000-call-plumber.md", "2026-07-13-091000-later.md"):
            (self.brain_path / "inbox" / "raw" / "voice" / name).write_text("---\nraw: true\n---\nbody\n")
        self.plan_path = self.brain_path / "inbox" / "triage" / "2026-07-13-voice.md"
        self.plan_path.write_text(TODAY_PLAN_TEXT)
        self.now = dt.datetime(2026, 7, 13, 15, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_daily_note(self, today_tasks_body="- [ ]"):
        (self.brain_path / "2026-07-13.md").write_text(
            "---\ntype: daily-note\ndate: 2026-07-13\ntags:\n  - daily-note\n---\n\n"
            "# Monday, 13 July 2026\n\n"
            f"## Today's tasks\n{today_tasks_body}\n\n"
            "## Project next actions\n\n"
            "## Waiting for\n\n"
            "## Notes\n"
        )

    def test_happy_path_inserts_as_last_line_of_todays_tasks_before_next_heading(self):
        self._write_daily_note("- [ ] Existing manual task")
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["filed"]), 1)

        note_text = (self.brain_path / "2026-07-13.md").read_text()
        section = note_text.split("## Today's tasks\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, [
            "- [ ] Existing manual task",
            "- [ ] Call the plumber — [[inbox/raw/voice/2026-07-13-090000-call-plumber.md]]",
        ])
        # It landed before the next heading, not appended blindly at EOF.
        self.assertTrue(note_text.rstrip().endswith("## Notes"))

    def test_happy_path_archives_capture_and_marks_row_done(self):
        self._write_daily_note()
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertFalse(
            (self.brain_path / "inbox" / "raw" / "voice" / "2026-07-13-090000-call-plumber.md").exists()
        )
        self.assertTrue(
            (self.brain_path / "archive" / "inbox" / "voice" / "2026-07-13-090000-call-plumber.md").exists()
        )
        text = self.plan_path.read_text()
        self.assertIn(" (done)", text)

        log_text = (self.brain_path / "log" / "2026-07-13.md").read_text()
        self.assertIn("file-capture-today", log_text)
        self.assertIn("Filed to today's daily note", log_text)
        self.assertIn("**trigger:** Execute (Routine) — rule e5f6a7b8", log_text)

    def test_missing_todays_note_reports_error_leaves_row_and_capture_untouched(self):
        # No daily note written for today at all.
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("does not exist", result["errors"][0])
        self.assertEqual(result["filed"], [])

        # Row left untouched (still [x], not [x] (done)) and capture not moved.
        text = self.plan_path.read_text()
        self.assertIn("- [x] Call the plumber → `today` [[inbox/raw/voice/2026-07-13-090000-call-plumber.md]]", text)
        self.assertTrue(
            (self.brain_path / "inbox" / "raw" / "voice" / "2026-07-13-090000-call-plumber.md").exists()
        )
        self.assertFalse(
            (self.brain_path / "archive" / "inbox" / "voice" / "2026-07-13-090000-call-plumber.md").exists()
        )

    def test_missing_todays_note_does_not_block_other_rows(self):
        # Tick the second row too, and give it a real destination — it
        # should still get filed even though row 1 errors out.
        self.plan_path.write_text(plan_text(
            with_row(TODAY_PLAN_ROWS, 2, approve="[x]"), "voice", "2026-07-13",
        ))
        (self.brain_path / "areas" / "household").mkdir(parents=True)

        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(result["filed"]), 1)
        self.assertIn(
            "[[inbox/raw/voice/2026-07-13-091000-later.md]]",
            (self.brain_path / "areas" / "household" / "_inbox.md").read_text(),
        )


PERSON_PLAN_TEXT = plan_text([
    dict(n=1, capture="inbox/raw/text/2026-07-16-090000-ask-example-person.md",
         preview="Ask Example Person about the mortgage", route="Pass B",
         destination="people/Example Person.md#🗣️ To Discuss",
         confidence="Medium", approve="[x]"),
    dict(n=2, capture="inbox/raw/text/2026-07-16-091000-waiting-example-person.md",
         preview="Waiting on Example Person for the invoice", route="Pass B",
         destination="people/Example Person.md#⏳ Waiting For", confidence="Medium"),
], "text", "2026-07-16")


class TestFileCaptureHeading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "people").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "text").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        for name in ("2026-07-16-090000-ask-example-person.md", "2026-07-16-091000-waiting-example-person.md"):
            (self.brain_path / "inbox" / "raw" / "text" / name).write_text("---\nraw: true\n---\nbody\n")
        self.plan_path = self.brain_path / "inbox" / "triage" / "2026-07-16-text.md"
        self.plan_path.write_text(PERSON_PLAN_TEXT)
        self.now = dt.datetime(2026, 7, 16, 15, 0)
        self.hub_path = self.brain_path / "people" / "Example Person.md"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_hub(self, to_discuss_body="<!-- Open agenda items -->"):
        self.hub_path.write_text(
            "---\ntype: person\nname: Example Person\n---\n\n"
            "# Example Person\n> Wife\n\n"
            f"## 🗣️ To Discuss\n{to_discuss_body}\n\n"
            "## ⏳ Waiting For\n<!-- Things delegated -->\n\n"
            "## 🧠 Context\n<!-- Durable facts -->\n\n"
            "## 🗓️ Log\n- 2026-01-01 — created\n"
        )

    def test_happy_path_inserts_before_next_heading_not_eof(self):
        self._write_hub("- Existing agenda item")
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["filed"]), 1)

        hub_text = self.hub_path.read_text()
        section = hub_text.split("## 🗣️ To Discuss\n", 1)[1].split("\n## ", 1)[0]
        lines = [ln for ln in section.splitlines() if ln.strip()]
        self.assertEqual(lines, [
            "- Existing agenda item",
            "- 2026-07-16 — [[inbox/raw/text/2026-07-16-090000-ask-example-person.md]] — Ask Example Person about the mortgage",
        ])
        # It landed before the next heading, not appended at EOF.
        self.assertIn("## ⏳ Waiting For", hub_text.split("2026-07-16 —", 1)[1])

    def test_archives_capture_and_marks_row_done(self):
        self._write_hub()
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertFalse(
            (self.brain_path / "inbox" / "raw" / "text" / "2026-07-16-090000-ask-example-person.md").exists()
        )
        self.assertTrue(
            (self.brain_path / "archive" / "inbox" / "text" / "2026-07-16-090000-ask-example-person.md").exists()
        )
        text = self.plan_path.read_text()
        self.assertIn(" (done)", text)

    def test_missing_heading_reports_error_leaves_row_untouched(self):
        # Hub exists but has no "To Discuss" heading at all.
        self.hub_path.write_text("---\ntype: person\nname: Example Person\n---\n\n# Example Person\n\n## 🧠 Context\nsome facts\n")
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("To Discuss", result["errors"][0])
        self.assertEqual(result["filed"], [])
        self.assertTrue(
            (self.brain_path / "inbox" / "raw" / "text" / "2026-07-16-090000-ask-example-person.md").exists()
        )

    def test_missing_file_reports_error_never_creates_hub(self):
        # No Example Person.md at all — a file#heading destination never creates it.
        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("does not exist", result["errors"][0])
        self.assertFalse(self.hub_path.exists())
        self.assertTrue(
            (self.brain_path / "inbox" / "raw" / "text" / "2026-07-16-090000-ask-example-person.md").exists()
        )


class TestRefusalHasNoSideEffects(unittest.TestCase):
    """A refusal must happen before *anything* — no destination write, no
    capture archived, no Action Log entry, no per-source hook, no heartbeat
    bump, no rewrite of the Plan itself. A half-executed Plan whose remaining
    Rows are ambiguous is strictly worse than an untouched one, so the checks
    run against the raw text before the execute loop is entered at all.

    Asserted by diffing the whole Brain tree byte-for-byte, rather than by
    listing the side effects one at a time and hoping the list is complete."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name) / "brain"
        (self.brain_path / "areas" / "household").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "fakesource").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        (self.brain_path / "config").mkdir()
        # A routine-state row, so a heartbeat bump would show up in the diff.
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Execute | never |\n"
        )
        for name in ("good.md", "other.md", "real.md"):
            (self.brain_path / "inbox" / "raw" / "fakesource" / name).write_text(
                "---\nraw: true\n---\nbody\n"
            )
        # A hook that would leave a file behind if it ever ran.
        self.library_path = Path(self._tmp.name) / "library"
        hook_dir = self.library_path / "plugins" / "claude-code" / "skills" / "fakesource"
        hook_dir.mkdir(parents=True)
        self.hook_marker = self.brain_path / "hook-fired.txt"
        (hook_dir / "execute_hook.py").write_text(
            f"open({str(self.hook_marker)!r}, 'a').write('fired\\n')\n"
        )
        self.plan_path = self.brain_path / "inbox" / "triage" / "2026-07-21-fakesource.md"
        self.now = dt.datetime(2026, 7, 21, 15, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _snapshot(self):
        return {
            str(p.relative_to(self.brain_path)): p.read_bytes()
            for p in sorted(self.brain_path.rglob("*")) if p.is_file()
        }

    def _write_plan(self, body):
        self.plan_path.write_text(
            "---\ntype: triage-plan\nsource: fakesource\ndate: 2026-07-21\n"
            "status: pending\n---\n\n"
            "# Triage Plan — fakesource — 2026-07-21\n\n" + body
        )

    def _assert_refused_untouched(self, expected_in_message):
        before = self._snapshot()

        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(
                self.brain_path, self.plan_path, now=self.now,
                library_path=self.library_path,
            )

        self.assertIn(expected_in_message, str(ctx.exception))
        self.assertEqual(self._snapshot(), before)   # nothing written or removed
        self.assertFalse(self.hook_marker.exists())  # no hook fired
        self.assertIn("| Execute | never |",         # no heartbeat bump
                      (self.brain_path / "config" / "routine-state.md").read_text())

    def test_malformed_block_refuses_before_any_side_effect(self):
        # Row 1 is ticked, valid, and would file if the run got that far.
        # Row 2 is ticked and its block carries two capture links.
        self._write_plan(
            "## areas/household/_inbox.md\n\n"
            + row_block(1, "inbox/raw/fakesource/good.md", "a filed item",
                        "Pass B", "areas/household/_inbox.md", "Medium",
                        approve="[x]") + "\n\n"
            "## discard\n\n"
            "- [x] malformed item → `discard` [[inbox/raw/fakesource/other.md]] [[inbox/raw/fakesource/real.md]]\n"
        )
        self._assert_refused_untouched("malformed item")
        # Specifically: the *valid* ticked row did not slip through.
        self.assertFalse((self.brain_path / "areas" / "household" / "_inbox.md").exists())

    def test_a_mis_grouped_row_is_not_a_refusal_at_all(self):
        """The heading is regenerated output, never compared (ADR-0031), so a
        Row under a heading it does not match runs like any other Row and the
        hook fires for it — this is the class of refusal that was removed."""
        self._write_plan(
            "## areas/household/_inbox.md\n\n"
            + row_block(1, "inbox/raw/fakesource/good.md", "a filed item",
                        "Pass B", "areas/household/_inbox.md", "Medium",
                        approve="[x]") + "\n\n"
            + row_block(2, "inbox/raw/fakesource/real.md", "mis-grouped",
                        "Pass B", "discard", "Medium", approve="[x]") + "\n"
        )

        result = execute.execute_plan(
            self.brain_path, self.plan_path, now=self.now,
            library_path=self.library_path,
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["filed"], ["inbox/raw/fakesource/good.md"])
        self.assertEqual(result["discarded"], ["inbox/raw/fakesource/real.md"])
        # Every Row executed, so the Plan archived — regrouped on the way out.
        self.assertEqual(grouping_of(result["archived_to"].read_text()),
                         {"areas/household/_inbox.md": ["1"], "discard": ["2"]})

    def test_a_clean_plan_in_the_same_fixture_does_execute(self):
        """Guards the test itself: the fixture must be capable of executing,
        so the assertions above are proving the refusal and not a broken setup."""
        self._write_plan(
            "## areas/household/_inbox.md\n\n"
            + row_block(1, "inbox/raw/fakesource/good.md", "a filed item",
                        "Pass B", "areas/household/_inbox.md", "Medium",
                        approve="[x]") + "\n"
        )
        result = execute.execute_plan(
            self.brain_path, self.plan_path, now=self.now,
            library_path=self.library_path,
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["filed"]), 1)
        self.assertTrue((self.brain_path / "areas" / "household" / "_inbox.md").exists())
        self.assertTrue(self.hook_marker.exists())
        self.assertIn("| Execute | 2026-07-21 15:00 |",
                      (self.brain_path / "config" / "routine-state.md").read_text())


class TestResolveLibraryPath(unittest.TestCase):
    def setUp(self):
        self._prev = __import__("os").environ.pop("GOALS_OS_LIBRARY_PATH", None)

    def tearDown(self):
        if self._prev is not None:
            __import__("os").environ["GOALS_OS_LIBRARY_PATH"] = self._prev

    def test_default_is_sibling_of_this_engines_own_repo_root(self):
        # execute.py lives at <engine-repo-root>/scripts/execute.py; the
        # documented Code/projects/Goals OS/{goals-os-engine,goals-os-library}
        # topology puts goals-os-library one level ABOVE engine-repo-root,
        # as a sibling of it.
        resolved = execute.resolve_library_path(None)
        engine_repo_root = Path(execute.__file__).resolve().parent.parent
        self.assertEqual(resolved, engine_repo_root.parent / "goals-os-library")

    def test_explicit_arg_overrides_default(self):
        resolved = execute.resolve_library_path("/tmp/somewhere")
        self.assertEqual(resolved, Path("/tmp/somewhere").resolve())

    def test_env_var_used_when_no_explicit_arg(self):
        __import__("os").environ["GOALS_OS_LIBRARY_PATH"] = "/tmp/env-library"
        resolved = execute.resolve_library_path(None)
        self.assertEqual(resolved, Path("/tmp/env-library").resolve())
        del __import__("os").environ["GOALS_OS_LIBRARY_PATH"]


HOOK_PLAN_TEXT = plan_text([
    dict(n=1, capture="inbox/raw/fakesource/2026-07-21-090000-filed.md",
         preview="A filed item", route="Pass B",
         destination="areas/household/_inbox.md", confidence="Medium", approve="[x]"),
    dict(n=2, capture="inbox/raw/fakesource/2026-07-21-091000-discarded.md",
         preview="not worth keeping", route="Pass B", destination="discard",
         confidence="Medium", approve="[x]"),
], "fakesource", "2026-07-21")


class TestSourceExecuteHook(unittest.TestCase):
    """Ticket 14 (revised): Execute — not fetch.py — is now the only place
    a source-specific side effect (e.g. Gmail archiving) can fire, and only
    for a source whose plugin folder defines execute_hook.py. Verifies the
    hook receives the archived capture's final path and the right
    filed/discarded outcome, using a fake hook script (no real plugin, no
    network) so this test has zero goals-os-library/Gmail dependency."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name) / "brain"
        (self.brain_path / "areas" / "household").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "fakesource").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        for name in ("2026-07-21-090000-filed.md", "2026-07-21-091000-discarded.md"):
            (self.brain_path / "inbox" / "raw" / "fakesource" / name).write_text(
                "---\nraw: true\n---\nbody\n"
            )
        self.plan_path = self.brain_path / "inbox" / "triage" / "2026-07-21-fakesource.md"
        self.plan_path.write_text(HOOK_PLAN_TEXT)
        self.now = dt.datetime(2026, 7, 21, 15, 0)

        # Fake library checkout with a fakesource/execute_hook.py that just
        # records its argv to a file — enough to assert on without any real
        # plugin or network dependency.
        self.library_path = Path(self._tmp.name) / "library"
        hook_dir = self.library_path / "plugins" / "claude-code" / "skills" / "fakesource"
        hook_dir.mkdir(parents=True)
        self.calls_file = Path(self._tmp.name) / "hook_calls.txt"
        (hook_dir / "execute_hook.py").write_text(
            "import sys\n"
            f"with open({str(self.calls_file)!r}, 'a') as f:\n"
            "    f.write('|'.join(sys.argv[1:]) + chr(10))\n"
        )
        self.config_dir = self.brain_path / "config"

    def tearDown(self):
        self._tmp.cleanup()

    def _read_calls(self):
        if not self.calls_file.exists():
            return []
        return [line for line in self.calls_file.read_text().splitlines() if line]

    def test_hook_called_once_per_ticked_row_with_correct_outcome(self):
        execute.execute_plan(
            self.brain_path, self.plan_path, now=self.now,
            config_dir=self.config_dir, library_path=self.library_path,
        )
        calls = self._read_calls()
        self.assertEqual(len(calls), 2)
        self.assertTrue(any("--outcome|filed" in c for c in calls))
        self.assertTrue(any("--outcome|discarded" in c for c in calls))

    def test_hook_receives_the_archived_not_original_capture_path(self):
        execute.execute_plan(
            self.brain_path, self.plan_path, now=self.now,
            config_dir=self.config_dir, library_path=self.library_path,
        )
        calls = self._read_calls()
        archived_dir = str(self.brain_path / "archive" / "inbox" / "fakesource")
        self.assertTrue(all(archived_dir in c for c in calls))
        raw_dir = str(self.brain_path / "inbox" / "raw" / "fakesource")
        self.assertTrue(all(raw_dir not in c for c in calls))

    def test_hook_receives_the_given_config_dir(self):
        execute.execute_plan(
            self.brain_path, self.plan_path, now=self.now,
            config_dir=self.config_dir, library_path=self.library_path,
        )
        calls = self._read_calls()
        self.assertTrue(all(f"--config-dir|{self.config_dir}" in c for c in calls))

    def test_no_hook_for_a_source_without_execute_hook_py_is_a_silent_noop(self):
        # voice has no execute_hook.py anywhere — must not error or block.
        text = HOOK_PLAN_TEXT.replace("fakesource", "voice")
        (self.brain_path / "inbox" / "raw" / "voice").mkdir(parents=True)
        for name in ("2026-07-21-090000-filed.md", "2026-07-21-091000-discarded.md"):
            (self.brain_path / "inbox" / "raw" / "voice" / name).write_text("---\nraw: true\n---\nbody\n")
        voice_plan = self.brain_path / "inbox" / "triage" / "2026-07-21-voice.md"
        voice_plan.write_text(text)

        result = execute.execute_plan(
            self.brain_path, voice_plan, now=self.now,
            config_dir=self.config_dir, library_path=self.library_path,
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["filed"]), 1)
        self.assertEqual(len(result["discarded"]), 1)

    def test_default_config_dir_is_brain_config_when_not_given(self):
        execute.execute_plan(
            self.brain_path, self.plan_path, now=self.now,
            library_path=self.library_path,
        )
        calls = self._read_calls()
        expected = str(self.brain_path / "config")
        self.assertTrue(all(f"--config-dir|{expected}" in c for c in calls))


class TestSourceExecuteHookDestination(unittest.TestCase):
    """`--destination` passes the Triage row's own destination cell through to
    the hook, so a hook never has to re-derive the answer the user already gave
    by ticking the row (protocols/execute.md v1.3). The flag is present for
    every outcome kind that runs a hook — `file-capture`, `file-capture-today`
    and `discard-capture` — specifically so a hook can read it unconditionally
    rather than branching on its absence. Execute gains no source-specific
    knowledge from this: it forwards a string it already parsed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name) / "brain"
        (self.brain_path / "areas" / "household").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "fakesource").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        self.now = dt.datetime(2026, 7, 21, 15, 0)
        # file-capture-today never creates the daily note, so it must exist.
        (self.brain_path / "2026-07-21.md").write_text(
            "# 2026-07-21\n\n## Today's tasks\n\n## Notes\n"
        )

        self.library_path = Path(self._tmp.name) / "library"
        hook_dir = self.library_path / "plugins" / "claude-code" / "skills" / "fakesource"
        hook_dir.mkdir(parents=True)
        self.calls_file = Path(self._tmp.name) / "hook_calls.txt"
        self.hook_path = hook_dir / "execute_hook.py"
        self._write_hook(exit_code=0)
        self.config_dir = self.brain_path / "config"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_hook(self, exit_code):
        self.hook_path.write_text(
            "import sys\n"
            f"with open({str(self.calls_file)!r}, 'a') as f:\n"
            "    f.write('|'.join(sys.argv[1:]) + chr(10))\n"
            f"sys.exit({exit_code})\n"
        )

    def _run_plan(self, rows):
        """Execute a plan whose ticked rows are `(capture-stem, destination)`."""
        plan_rows = []
        for n, (stem, destination) in enumerate(rows, start=1):
            (self.brain_path / "inbox" / "raw" / "fakesource" / f"{stem}.md").write_text(
                "---\nraw: true\n---\nbody\n"
            )
            plan_rows.append(dict(
                n=n, capture=f"inbox/raw/fakesource/{stem}.md", preview=f"preview {n}",
                route="Pass B", destination=destination, confidence="Medium",
                approve="[x]",
            ))
        plan_path = self.brain_path / "inbox" / "triage" / "2026-07-21-fakesource.md"
        plan_path.write_text(plan_text(plan_rows, "fakesource", "2026-07-21"))
        return execute.execute_plan(
            self.brain_path, plan_path, now=self.now,
            config_dir=self.config_dir, library_path=self.library_path,
        )

    def _read_calls(self):
        if not self.calls_file.exists():
            return []
        return [line for line in self.calls_file.read_text().splitlines() if line]

    def test_file_capture_row_passes_its_own_destination(self):
        self._run_plan([("filed", "areas/household/_inbox.md")])
        self.assertIn("--destination|areas/household/_inbox.md", self._read_calls()[0])

    def test_file_capture_destination_keeps_its_heading_fragment(self):
        # A `file#heading` destination (execute.md v1.1) is forwarded whole —
        # the hook gets the same string the user ticked, not a truncated path.
        (self.brain_path / "people").mkdir()
        (self.brain_path / "people" / "Example Person.md").write_text(
            "# Example Person\n\n## To Discuss\n\n## Log\n"
        )
        self._run_plan([("filed", "people/Example Person.md#To Discuss")])
        self.assertIn("--destination|people/Example Person.md#To Discuss", self._read_calls()[0])

    def test_file_capture_today_row_passes_its_own_destination(self):
        self._run_plan([("todayrow", "today")])
        self.assertIn("--destination|today", self._read_calls()[0])

    def test_discard_row_passes_the_literal_discard(self):
        self._run_plan([("dropped", "discard")])
        self.assertIn("--destination|discard", self._read_calls()[0])

    def test_discard_row_normalises_case_to_the_literal_discard(self):
        # `action_type_for()` matches case-insensitively, so a `Discard` cell is
        # still a discard row; the hook must see the canonical literal either way.
        self._run_plan([("dropped", "Discard")])
        self.assertIn("--destination|discard", self._read_calls()[0])

    def test_every_hook_invocation_carries_the_flag(self):
        # A hook may read --destination unconditionally; it is never absent.
        self._run_plan([
            ("filed", "areas/household/_inbox.md"),
            ("todayrow", "today"),
            ("dropped", "discard"),
        ])
        calls = self._read_calls()
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("--destination|" in c for c in calls))

    def test_destination_is_passed_alongside_the_three_existing_flags(self):
        self._run_plan([("filed", "areas/household/_inbox.md")])
        call = self._read_calls()[0]
        for flag in ("--config-dir|", "--raw-capture|", "--outcome|", "--destination|"):
            self.assertIn(flag, call)

    def test_nonzero_hook_exit_still_never_blocks_or_fails_the_row(self):
        # The check=False guarantee must not regress now that the hook takes an
        # extra flag: a hook that rejects its arguments and exits non-zero must
        # not turn into an Execute error or an unfiled row.
        self._write_hook(exit_code=2)
        result = self._run_plan([
            ("filed", "areas/household/_inbox.md"),
            ("dropped", "discard"),
        ])
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["filed"]), 1)
        self.assertEqual(len(result["discarded"]), 1)


class TestMultiDestinationRows(unittest.TestCase):
    """ADR-0033: one Row may name several destinations, and the
    route/confidence/rule triple is wrapped in an Obsidian comment."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        for d in ("areas/household", "areas/finances", "projects/bills",
                  "inbox/raw/voice", "inbox/triage"):
            (self.brain_path / d).mkdir(parents=True)
        (self.brain_path / "inbox/raw/voice/2026-07-11-140203-buy-milk.md").write_text("x")
        self.now = dt.datetime(2026, 7, 11, 15, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self, destinations, approve="[x]"):
        block = f"- {approve} Remember to buy milk → {destinations} [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]"
        path = self.brain_path / "inbox/triage/2026-07-11-voice.md"
        path.write_text("---\nstatus: pending\n---\n\n# Plan\n\n" + block + "\n")
        return path

    def test_parses_a_list_and_keeps_destination_as_the_first(self):
        rows = execute.parse_plan_rows(
            self._plan("`areas/finances/_inbox.md`, `projects/bills/notes.md`").read_text())
        self.assertEqual(rows[0]["destinations"],
                         ["areas/finances/_inbox.md", "projects/bills/notes.md"])
        # Existing single-valued consumers keep working unchanged.
        self.assertEqual(rows[0]["destination"], "areas/finances/_inbox.md")

    def test_files_one_capture_to_every_destination_archiving_once(self):
        plan = self._plan("`areas/finances/_inbox.md`, `projects/bills/notes.md`")
        result = execute.execute_plan(self.brain_path, plan, now=self.now)
        self.assertEqual(result["errors"], [])
        # One capture filed, not two — the Row is one action with two writes.
        self.assertEqual(len(result["filed"]), 1)
        for dest in ("areas/finances/_inbox.md", "projects/bills/notes.md"):
            self.assertIn("buy-milk", (self.brain_path / dest).read_text())
        self.assertTrue((self.brain_path / "archive/inbox/voice/2026-07-11-140203-buy-milk.md").exists())

    def test_one_action_log_entry_naming_every_destination(self):
        plan = self._plan("`areas/finances/_inbox.md`, `projects/bills/notes.md`")
        execute.execute_plan(self.brain_path, plan, now=self.now)
        log = (self.brain_path / "log" / "2026-07-11.md").read_text()
        self.assertEqual(log.count("- **action:**"), 1)
        self.assertIn("areas/finances/_inbox.md", log)
        self.assertIn("projects/bills/notes.md", log)

    def test_discard_combined_with_a_real_destination_refuses_the_plan(self):
        plan = self._plan("`areas/finances/_inbox.md`, `discard`")
        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(self.brain_path, plan, now=self.now)
        self.assertIn("cannot be combined", str(ctx.exception))
        # Refusal is before any side effect: nothing filed, capture untouched.
        self.assertFalse((self.brain_path / "areas/finances/_inbox.md").exists())
        self.assertTrue((self.brain_path / "inbox/raw/voice/2026-07-11-140203-buy-milk.md").exists())

    def test_a_repeated_destination_refuses_the_plan(self):
        plan = self._plan("`areas/finances/_inbox.md`, `areas/finances/_inbox.md`")
        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(self.brain_path, plan, now=self.now)
        self.assertIn("listed twice", str(ctx.exception))

    def test_a_blank_entry_in_the_list_refuses_rather_than_filing_the_rest(self):
        plan = self._plan("`areas/finances/_inbox.md`, ``")
        self.assertTrue(any("blank destination" in e
                            for e in execute.check_row_blocks(plan.read_text())))

    def test_one_line_multi_destination_rows_parse(self):
        line = "- [x] Remember to buy milk → `areas/household/_inbox.md` [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]"
        text = ("---\nstatus: pending\n---\n\n# Plan\n\n" + line + "\n")
        rows = execute.parse_plan_rows(text)
        self.assertEqual(rows[0]["destinations"], ["areas/household/_inbox.md"])
        self.assertEqual(rows[0]["approve"], "[x]")

    def test_regrouping_a_multi_destination_row_is_a_fixed_point(self):
        plan = self._plan("`areas/finances/_inbox.md`, `projects/bills/notes.md`", approve="[ ]")
        once = execute.regroup_plan(plan.read_text())
        self.assertEqual(once, execute.regroup_plan(once))
        self.assertIn("## areas/finances/_inbox.md", once)


if __name__ == "__main__":
    unittest.main()


class TestPlanCompletionRequiresActionNotJustATick(unittest.TestCase):
    """A Plan is finished when every Row has been *acted on*, not when no Row
    is left unticked. Those differ exactly when a ticked Row errors — and
    ticking a Plan of still-`unmatched` Rows is the natural thing to do on a
    Plan whose Pass B has not been resolved."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "areas" / "household").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "voice").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        for name in ("a.md", "b.md"):
            (self.brain_path / "inbox" / "raw" / "voice" / name).write_text("x")
        self.now = dt.datetime(2026, 7, 11, 15, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self, *destinations):
        rows = [
            dict(n=i, capture=f"inbox/raw/voice/{name}", preview=f"p{i}",
                 route="Pass B", destination=d, confidence="—", approve="[x]")
            for i, (d, name) in enumerate(zip(destinations, ("a.md", "b.md")), 1)
        ]
        path = self.brain_path / "inbox" / "triage" / "2026-07-11-voice.md"
        path.write_text(plan_text(rows, "voice", "2026-07-11"))
        return path

    def test_a_plan_of_ticked_unmatched_rows_is_not_archived(self):
        plan = self._plan("unmatched", "unmatched")
        result = execute.execute_plan(self.brain_path, plan, now=self.now)
        self.assertEqual(len(result["errors"]), 2)
        self.assertFalse(result["plan_executed"])
        self.assertTrue(plan.exists())
        self.assertIn("status: pending", plan.read_text())
        # The captures are still there to be triaged once Pass B is resolved.
        self.assertTrue((self.brain_path / "inbox" / "raw" / "voice" / "a.md").exists())

    def test_a_plan_mixing_one_good_row_and_one_errored_row_is_not_archived(self):
        plan = self._plan("areas/household/_inbox.md", "unmatched")
        result = execute.execute_plan(self.brain_path, plan, now=self.now)
        self.assertEqual(len(result["filed"]), 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertFalse(result["plan_executed"])
        self.assertTrue(plan.exists())

    def test_a_plan_whose_rows_all_acted_is_still_archived(self):
        plan = self._plan("areas/household/_inbox.md", "discard")
        result = execute.execute_plan(self.brain_path, plan, now=self.now)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["plan_executed"])
        self.assertFalse(plan.exists())


class TestReleaseBlockerFixes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "areas" / "household").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "voice").mkdir(parents=True)
        (self.brain_path / "inbox" / "triage").mkdir(parents=True)
        (self.brain_path / "inbox" / "raw" / "voice" / "a.md").write_text("x")
        self.now = dt.datetime(2026, 8, 2, 10, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_legacy_markdown_table_plan_refuses_execution_and_archival(self):
        table_plan_text = (
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan — voice — 2026-08-02\n\n"
            "| # | capture | preview | route | destination | confidence | rule | approve |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| 1 | [[inbox/raw/voice/a.md]] | buy milk | Pass B | unmatched | High | — | [x] |\n"
        )
        plan_path = self.brain_path / "inbox" / "triage" / "2026-08-02-voice.md"
        plan_path.write_text(table_plan_text, encoding="utf-8")

        self.assertTrue(execute.requires_migration(table_plan_text))
        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(self.brain_path, plan_path, now=self.now)
        self.assertIn("requires migration", str(ctx.exception))
        self.assertTrue(plan_path.exists())
        self.assertTrue((self.brain_path / "inbox" / "raw" / "voice" / "a.md").exists())

    def test_legacy_3_line_format_plan_refuses_execution(self):
        three_line_text = (
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan — voice — 2026-08-02\n\n"
            "## unmatched\n\n"
            "- [x] **1** → `unmatched` %%· Pass B · — · —%%\n"
            "    buy milk\n"
            "    [[inbox/raw/voice/a.md]]\n"
        )
        plan_path = self.brain_path / "inbox" / "triage" / "2026-08-02-voice.md"
        plan_path.write_text(three_line_text, encoding="utf-8")

        self.assertTrue(execute.requires_migration(three_line_text))
        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(self.brain_path, plan_path, now=self.now)
        self.assertIn("requires migration", str(ctx.exception))
        self.assertTrue(plan_path.exists())

    def test_invalid_keeper_option_label_refuses(self):
        plan_text = (
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan\n\n"
            "## unmatched\n\n"
            "- [ ] buy milk → `unmatched` [[inbox/raw/voice/a.md]]\n"
            "    - [ ] Custom option · `areas/household/_inbox.md`\n"
        )
        errors = execute.check_row_blocks(plan_text)
        self.assertTrue(any("invalid keeper option label 'Custom option'" in e for e in errors))

    def test_area_option_without_valid_path_refuses(self):
        plan_text = (
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan\n\n"
            "## unmatched\n\n"
            "- [ ] buy milk → `unmatched` [[inbox/raw/voice/a.md]]\n"
            "    - [ ] Area\n"
        )
        errors = execute.check_row_blocks(plan_text)
        self.assertTrue(any("option 'Area' requires a valid destination path" in e for e in errors))

    def test_duplicate_destinations_from_multiple_ticked_options_refuse_before_dedup(self):
        plan_text = (
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan\n\n"
            "## unmatched\n\n"
            "- [x] buy milk → `unmatched` [[inbox/raw/voice/a.md]]\n"
            "    - [x] Area · `areas/household/_inbox.md`\n"
            "    - [x] Project · `areas/household/_inbox.md`\n"
        )
        errors = execute.check_row_blocks(plan_text)
        self.assertTrue(any("same destination is listed twice" in e for e in errors))

    def test_duplicate_destinations_from_ticked_options_on_question_mark_keeper_refuses(self):
        plan_text = (
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan\n\n"
            "## ?\n\n"
            "- [x] buy milk → `?` [[inbox/raw/voice/a.md]]\n"
            "    - [x] Area · `areas/household/_inbox.md`\n"
            "    - [x] Project · `areas/household/_inbox.md`\n"
        )
        errors = execute.check_row_blocks(plan_text)
        self.assertTrue(any("same destination is listed twice" in e for e in errors))
        self.assertFalse(any("options are only permitted on keeper Rows" in e for e in errors))

    def test_options_on_discard_rows_refuse(self):
        plan_text = (
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan\n\n"
            "## discard\n\n"
            "- [ ] junk capture → `discard` [[inbox/raw/voice/a.md]]\n"
            "    - [ ] Bin it instead\n"
        )
        errors = execute.check_row_blocks(plan_text)
        self.assertTrue(any("options are only permitted on keeper Rows" in e for e in errors))

    def test_options_on_routed_rows_refuse(self):
        plan_text = (
            "---\ntype: triage-plan\nsource: voice\ndate: 2026-08-02\nstatus: pending\n---\n\n"
            "# Triage Plan\n\n"
            "## areas/household/_inbox.md\n\n"
            "- [ ] buy milk → `areas/household/_inbox.md` [[inbox/raw/voice/a.md]]\n"
            "    - [ ] Act on this\n"
        )
        errors = execute.check_row_blocks(plan_text)
        self.assertTrue(any("options are only permitted on keeper Rows" in e for e in errors))
