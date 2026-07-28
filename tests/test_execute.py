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
    """One Row in the ADR-0031 shape: task line + preview + capture wikilink."""
    tick, marker = approve[:3], approve[4:]  # "[x] (done)" -> "[x]", "(done)"
    suffix = f" {marker}" if marker else ""
    return (
        f"- {tick} **{n}** → `{destination}` · {route} · {confidence} · {rule}{suffix}\n"
        f"    {preview}\n"
        f"    [[{capture}]]"
    )


def plan_text(rows, source, date, status="pending"):
    """A whole Plan: Rows grouped under `## <destination>` headings, in the
    order each destination first appears."""
    grouped = {}
    for r in rows:
        grouped.setdefault(r["destination"], []).append(r)
    body = "\n".join(
        f"## {destination}\n\n" + "\n\n".join(row_block(**r) for r in group) + "\n"
        for destination, group in grouped.items()
    )
    return (
        f"---\ntype: triage-plan\nsource: {source}\ndate: {date}\n"
        f"status: {status}\n---\n\n"
        f"# Triage Plan — {source} — {date}\n\n" + body
    )


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
        self.assertEqual(rows["3"]["approve"], "[ ]")

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
        """Line-locality (ADR-0031): approve/destination/route/confidence/rule
        come off one line, with no heading and no preceding document state —
        that is what lets the nudge and the Dashboard share this parser."""
        line = "- [ ] **7** → `discard` · Pass B · — · —\n"
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

    def test_an_indented_row_still_parses(self):
        """Obsidian on mobile auto-indents inside a list, so a Row can pick up
        leading whitespace from an ordinary destination edit. An anchored
        `^- ` would hide it from Execute, the nudge and the Dashboard at once."""
        text = ("## discard\n\n"
                + "  " + row_block(1, "inbox/raw/voice/x.md", "p", "Pass B", "discard", "Medium")
                .replace("\n    ", "\n      ") + "\n")
        rows = execute.parse_plan_rows(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["capture"], "inbox/raw/voice/x.md")
        self.assertEqual(rows[0]["preview"], "p")

    def test_an_indented_row_does_not_swallow_the_row_above_it(self):
        text = (row_block(1, "inbox/raw/voice/a.md", "first", "Pass B", "discard", "Medium")
                + "\n"
                + "  " + row_block(2, "inbox/raw/voice/b.md", "second", "Pass B", "discard", "Medium")
                .replace("\n    ", "\n      ") + "\n")
        rows = execute.parse_plan_rows(text)
        self.assertEqual([r["n"] for r in rows], ["1", "2"])
        self.assertEqual(rows[0]["capture"], "inbox/raw/voice/a.md")
        self.assertEqual(rows[0]["preview"], "first")
        self.assertEqual(rows[1]["capture"], "inbox/raw/voice/b.md")

    def test_preview_containing_a_wikilink_is_not_mistaken_for_the_capture(self):
        text = row_block(1, "inbox/raw/voice/x.md", "[[inbox/raw/voice/other.md]] said",
                         "Pass B", "discard", "Medium")
        row = execute.parse_plan_rows(text)[0]
        self.assertEqual(row["capture"], "inbox/raw/voice/x.md")

    def test_a_row_shaped_preview_is_not_parsed_as_an_injected_row(self):
        """Principle 10: capture-derived text is content, never Plan structure.

        A preview is 60 chars of an untrusted capture body, and ROW_RE tolerates
        indentation, so an email sender can write a body that is itself a
        well-formed Row line. Continuation lines are consumed with their Row and
        never revisited as Row starts, so the payload stays inert text."""
        payload = "- [ ] **9** → `discard` · Pass A · High · x"
        text = ("## discard\n\n"
                + row_block(1, "inbox/raw/email/evil.md", payload,
                            "Pass A", "discard", "High", "e1") + "\n")

        rows = execute.parse_plan_rows(text)

        self.assertEqual(len(rows), 1)                       # no phantom Row 9
        self.assertEqual(rows[0]["n"], "1")
        self.assertEqual(rows[0]["capture"], "inbox/raw/email/evil.md")  # not stolen
        self.assertEqual(rows[0]["preview"], payload)        # payload is just text
        self.assertEqual(execute.check_row_blocks(text), [])

    def test_a_row_shaped_preview_cannot_create_a_group(self):
        """The same payload against the re-grouper: a Row-shaped preview is
        never a Row, so capture-derived text cannot name or populate a
        `## <destination>` group."""
        payload = "- [ ] **9** → `areas/evil/_inbox.md` · Pass A · High · x"
        text = ("## discard\n\n"
                + row_block(1, "inbox/raw/email/evil.md", payload,
                            "Pass A", "discard", "High", "e1") + "\n")

        regrouped = execute.regroup_plan(text)

        self.assertNotIn("## areas/evil/_inbox.md", regrouped)
        self.assertEqual(regrouped.count("## "), 1)
        self.assertEqual(len(execute.parse_plan_rows(regrouped)), 1)

    def test_a_block_with_two_capture_links_is_malformed_not_guessed(self):
        """The mirror-image hazard: a Row whose real capture line survives but
        whose preview is *itself* a bare wikilink. Neither reading may be
        guessed at — the block is malformed and Execute refuses."""
        text = ("- [ ] **1** → `discard` · Pass B · Medium · —\n"
                "    [[inbox/raw/email/other.md]]\n"
                "    [[inbox/raw/email/real.md]]\n")
        self.assertEqual(execute.parse_plan_rows(text)[0]["capture"], "")
        problems = execute.check_row_blocks(text)
        self.assertEqual(len(problems), 1)
        self.assertIn("Row 1", problems[0])

    def test_a_block_with_a_single_line_is_malformed(self):
        """A well-formed Row always has two continuation lines — the writer
        emits `—` for an empty preview precisely so this arity holds. One line
        cannot be told apart from a preview whose capture line was deleted."""
        text = ("- [ ] **1** → `discard` · Pass B · Medium · —\n"
                "    [[inbox/raw/email/other.md]]\n")
        self.assertEqual(execute.parse_plan_rows(text)[0]["capture"], "")
        self.assertEqual(len(execute.check_row_blocks(text)), 1)

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
                self.assertIn("Row 7", problems[0])
                self.assertIn("blank destination", problems[0])


def headings_of(text):
    return [ln[3:].strip() for ln in text.splitlines() if ln.startswith("## ")]


def row_order(text):
    """Row numbers in the order the document presents them — what the user
    scrolls past on a phone, and what a group reorder disturbs."""
    return [m.group("n") for m in
            (execute.ROW_RE.match(ln) for ln in text.splitlines()) if m]


def grouping_of(text):
    """`{heading: [row numbers under it]}` — what the Plan actually says about
    where each Row sits, read back off the rendered document."""
    grouped, heading = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            grouped.setdefault(heading, [])
        else:
            match = execute.ROW_RE.match(line)
            if match and heading is not None:
                grouped[heading].append(match.group("n"))
    return grouped


class TestRegroupPlan(unittest.TestCase):
    """Headings are regenerated output, never compared (ADR-0031)."""

    def test_a_well_grouped_plan_is_unchanged(self):
        self.assertEqual(execute.regroup_plan(PLAN_TEXT), PLAN_TEXT)

    def test_a_row_under_the_wrong_heading_is_moved_under_its_own_destination(self):
        text = PLAN_TEXT.replace(
            "- [x] **1** → `areas/household/_inbox.md`", "- [x] **1** → `discard`")
        # The in-place edit alone leaves Row 1 sitting under the old heading...
        self.assertEqual(grouping_of(text)["areas/household/_inbox.md"], ["1", "3"])

        regrouped = execute.regroup_plan(text)

        self.assertEqual(grouping_of(regrouped),
                         {"areas/household/_inbox.md": ["3"], "discard": ["1", "2"]})

    def test_an_emptied_heading_is_dropped(self):
        # Row 2 was the only Row under `## discard`; re-routing it in place
        # leaves that heading with nothing under it.
        text = PLAN_TEXT.replace(
            "- [x] **2** → `discard`", "- [x] **2** → `areas/household/_inbox.md`")
        self.assertIn("discard", headings_of(text))

        regrouped = execute.regroup_plan(text)

        self.assertEqual(headings_of(regrouped), ["areas/household/_inbox.md"])

    def test_a_needed_heading_that_is_absent_is_created(self):
        text = PLAN_TEXT.replace(
            "- [ ] **3** → `areas/household/_inbox.md`",
            "- [ ] **3** → `projects/goals-os/Goals OS.md`")
        self.assertNotIn("projects/goals-os/Goals OS.md", headings_of(text))

        regrouped = execute.regroup_plan(text)
        self.assertIn("projects/goals-os/Goals OS.md", headings_of(regrouped))
        self.assertEqual(grouping_of(regrouped)["projects/goals-os/Goals OS.md"], ["3"])

    def test_rows_with_no_headings_at_all_gain_them(self):
        text = ("- [ ] **1** → `discard` · Pass B · — · —\n"
                "    p\n    [[inbox/raw/voice/a.md]]\n")
        self.assertEqual(execute.regroup_plan(text),
                         "## discard\n\n" + text)

    def test_is_idempotent(self):
        text = PLAN_TEXT.replace(
            "- [x] **1** → `areas/household/_inbox.md`", "- [x] **1** → `discard`")
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
            "status: pending\n---\n\n# Triage Plan — voice — 2026-07-11\n\n"
            "A note I typed to myself.\n"
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
        ).replace("- [x] **1** → `areas/household/_inbox.md`", "- [x] **1** → `discard`")
        regrouped = execute.regroup_plan(text)
        parsed = {r["n"]: r["approve"] for r in execute.parse_plan_rows(regrouped)}
        self.assertEqual(parsed, {"1": "[x]", "2": "[x] (done)", "3": "[ ]"})
        self.assertEqual(
            sorted(r["n"] for r in execute.parse_plan_rows(regrouped)), ["1", "2", "3"]
        )

    def test_moves_an_indented_row_block_verbatim(self):
        text = PLAN_TEXT.replace(
            "- [x] **2** → `discard`", "  - [x] **2** → `areas/household/_inbox.md`",
        ).replace("\n    not worth keeping\n    [[", "\n      not worth keeping\n      [[")
        regrouped = execute.regroup_plan(text)
        self.assertIn(
            "  - [x] **2** → `areas/household/_inbox.md` · Pass B · Medium · —\n"
            "      not worth keeping\n"
            "      [[inbox/raw/voice/2026-07-11-140500-junk.md]]",
            regrouped,
        )
        # Document order within the group: Rows 1 and 3 were already there,
        # Row 2 arrives from the group below them.
        self.assertEqual(grouping_of(regrouped)["areas/household/_inbox.md"],
                         ["1", "3", "2"])

    def test_group_order_follows_each_destinations_first_row(self):
        """Groups sort by the document position of their first Row, never by a
        heading's. Re-routing Row 3 — which sits between Rows 1 and 2 in the
        document — opens its new group exactly where that Row already is, so no
        Row moves at all."""
        text = PLAN_TEXT.replace(
            "- [ ] **3** → `areas/household/_inbox.md`", "- [ ] **3** → `today`")
        regrouped = execute.regroup_plan(text)
        self.assertEqual(
            headings_of(regrouped),
            ["areas/household/_inbox.md", "today", "discard"],
        )
        self.assertEqual(row_order(regrouped), ["1", "3", "2"])

    def test_a_new_destination_on_the_last_row_appends_its_group(self):
        text = PLAN_TEXT.replace("- [x] **2** → `discard`", "- [x] **2** → `today`")
        self.assertEqual(
            headings_of(execute.regroup_plan(text)),
            ["areas/household/_inbox.md", "today"],
        )

    def test_renaming_a_heading_keeps_its_group_in_place(self):
        """The defect this rule exists to fix. `## discard` renamed by hand no
        longer holds any Row (the Rows still say `discard`), so the old
        heading-anchored rule dropped it, found `discard` heading-less, and
        appended the whole group at the end — a silent reorder mid-approval.
        The rename is still reverted; the group must not move."""
        text = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11")
        self.assertEqual(headings_of(text), ["discard", "unmatched", "areas/ho-lee-fook/_inbox.md"])
        self.assertEqual(row_order(text), ["1", "2", "3", "4", "5"])

        regrouped = execute.regroup_plan(text.replace("## discard\n", "## keep\n"))

        self.assertEqual(headings_of(regrouped),
                         ["discard", "unmatched", "areas/ho-lee-fook/_inbox.md"])
        self.assertEqual(row_order(regrouped), ["1", "2", "3", "4", "5"])
        self.assertEqual(regrouped, execute.regroup_plan(text))  # rename reverted

    def test_deleting_a_heading_outright_keeps_its_group_in_place(self):
        text = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11")

        regrouped = execute.regroup_plan(text.replace("## discard\n\n", ""))

        self.assertEqual(headings_of(regrouped),
                         ["discard", "unmatched", "areas/ho-lee-fook/_inbox.md"])
        self.assertEqual(row_order(regrouped), ["1", "2", "3", "4", "5"])

    def test_renaming_the_middle_heading_keeps_every_group_in_place(self):
        text = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11")

        regrouped = execute.regroup_plan(text.replace("## unmatched\n", "## sort later\n"))

        self.assertEqual(headings_of(regrouped),
                         ["discard", "unmatched", "areas/ho-lee-fook/_inbox.md"])
        self.assertEqual(row_order(regrouped), ["1", "2", "3", "4", "5"])

    def test_a_prose_kept_alive_heading_sorts_by_its_own_position(self):
        """It has no first Row to sort by, so it holds the one position it does
        have — its own — and carries its prose with it, between the groups it
        was written between."""
        text = plan_text(THREE_GROUP_ROWS, "voice", "2026-07-11").replace(
            "## unmatched\n", "## unmatched\n\nStill deciding these.\n")
        emptied = text.replace("→ `unmatched`", "→ `discard`")

        regrouped = execute.regroup_plan(emptied)

        self.assertEqual(headings_of(regrouped),
                         ["discard", "unmatched", "areas/ho-lee-fook/_inbox.md"])
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
                    "- [x] **1** → `areas/household/_inbox.md`",
                    f"- [x] **1** → `{destination}`")
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
            "- [x] **1** → `areas/household/_inbox.md`", "- [x] **1** → ``"))
        self.assertLess(text.index("**1**"), text.index("## "))
        self.assertEqual(grouping_of(text),
                         {"areas/household/_inbox.md": ["3"], "discard": ["2"]})

    def test_is_idempotent_across_a_sweep_of_disturbed_plans(self):
        """Idempotence is the hard requirement — both write paths run this on
        every write — so it is checked over the whole space of disturbances the
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
                "**2** → `discard`", "**2** → `today`"),
            "new destination on last row": base.replace(
                "**5** → `areas/ho-lee-fook/_inbox.md`", "**5** → `today`"),
            "first row re-routed to an existing group below": base.replace(
                "**1** → `discard`", "**1** → `areas/ho-lee-fook/_inbox.md`"),
            "prose keeps a heading alive": with_prose.replace(
                "→ `unmatched`", "→ `discard`"),
            "prose heading kept alive and renamed": with_prose.replace(
                "→ `unmatched`", "→ `discard`").replace("## discard\n", "## keep\n"),
            "blank destination": base.replace("**3** → `discard`", "**3** → ``"),
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
            "- [ ] **9** → `discard` · Pass B · — · —\n    p\n"
            "    [[inbox/raw/voice/z.md]]\n\nA stray note.\n",
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
        self.assertIn("- [ ] **3**", text)  # row 3 still untouched

    def test_marker_is_a_suffix_on_the_task_line_not_a_rewritten_cell(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        text = self.plan_path.read_text()
        self.assertIn(
            "- [x] **1** → `areas/household/_inbox.md` · Pass A · High · a1b2c3d4 (done)",
            text,
        )
        # The Row's own continuation lines are untouched by the stamp.
        self.assertIn("    [[inbox/raw/voice/2026-07-11-140203-buy-milk.md]]", text)

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

    def test_executes_an_indented_row_and_stamps_it_in_place(self):
        # Row 2 (the ticked discard) picks up a leading indent, as a mobile
        # edit would leave it. It must still execute, and the stamp must land
        # on that line without disturbing its indent.
        text = PLAN_TEXT.replace(
            "- [x] **2** →", "  - [x] **2** →",
        ).replace("\n    not worth keeping\n    [[", "\n      not worth keeping\n      [[")
        self.plan_path.write_text(text)

        result = execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["discarded"], ["inbox/raw/voice/2026-07-11-140500-junk.md"])
        self.assertIn("  - [x] **2** → `discard` · Pass B · Medium · — (done)",
                      self.plan_path.read_text())

    def test_in_place_destination_edit_executes_to_the_edited_destination(self):
        # Re-routing is one edit: change the destination on the Row line. Row 1
        # was a file-capture, is now a discard, and still sits under the old
        # heading — which is presentation, so it changes nothing.
        self.plan_path.write_text(PLAN_TEXT.replace(
            "- [x] **1** → `areas/household/_inbox.md`",
            "- [x] **1** → `discard`",
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
            "- [x] **1** → `areas/household/_inbox.md`",
            "- [x] **1** → `discard`",
        ))

        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        text = self.plan_path.read_text()
        self.assertEqual(grouping_of(text),
                         {"areas/household/_inbox.md": ["3"], "discard": ["1", "2"]})
        self.assertIn("- [x] **1** → `discard` · Pass A · High · a1b2c3d4 (done)", text)

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
                         {"discard": ["2"], "areas/household/_inbox.md": ["1", "3"]})

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
        text = PLAN_TEXT.replace("- [x] **2** → `discard`", "- [x] **2** → ``")
        self.plan_path.write_text(text)

        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertIn("Row 2", str(ctx.exception))
        self.assertIn("blank destination", str(ctx.exception))
        self.assertFalse((self.brain_path / "areas" / "household" / "_inbox.md").exists())
        self.assertFalse((self.brain_path / "archive").exists())
        self.assertFalse((self.brain_path / "log").exists())
        self.assertEqual(self.plan_path.read_text(), text)

    def test_repeated_runs_never_grow_a_plan_holding_a_blank_destination(self):
        # Unticked, so nothing executes and nothing refuses on the rows that
        # matter — but execute_plan re-groups on every run regardless.
        self.plan_path.write_text(
            PLAN_TEXT.replace("- [ ] **3** → `areas/household/_inbox.md`",
                              "- [ ] **3** → ``")
                     .replace("- [x] **", "- [ ] **")
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
            "    Remember to buy milk\n", "    [[inbox/raw/voice/decoy.md]]\n",
        )
        self.plan_path.write_text(text)

        with self.assertRaises(execute.ExecuteError) as ctx:
            execute.execute_plan(self.brain_path, self.plan_path, now=self.now)

        self.assertIn("Row 1", str(ctx.exception))
        self.assertFalse((self.brain_path / "areas" / "household" / "_inbox.md").exists())
        self.assertFalse((self.brain_path / "archive").exists())
        self.assertFalse((self.brain_path / "log").exists())
        self.assertEqual(self.plan_path.read_text(), text)

    def test_second_run_after_ticking_last_row_archives_plan(self):
        execute.execute_plan(self.brain_path, self.plan_path, now=self.now)
        text = self.plan_path.read_text().replace(
            "- [ ] **3**", "- [x] **3**",
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
        self.assertIn("- [x] **1** → `agent: Reviewer` · Pass A · High · a1b2c3d4 (dispatched)", text)


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
        self.assertIn("- [x] **1** → `today` · Pass A · High · e5f6a7b8\n", text)
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
            "- [x] **2** → `discard` · Pass B · Medium · —\n"
            "    [[inbox/raw/fakesource/other.md]]\n"
            "    [[inbox/raw/fakesource/real.md]]\n"
        )
        self._assert_refused_untouched("Row 2")
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


if __name__ == "__main__":
    unittest.main()
