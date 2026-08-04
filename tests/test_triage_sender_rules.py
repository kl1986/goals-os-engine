import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import execute  # noqa: E402
import triage_sender_rules as tsr  # noqa: E402


def capture(sender, subject="A subject"):
    return f"---\ntype: raw\n---\n\n**From:** {sender}\n**Subject:** {subject}\n"


class TestSenderRules(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name)
        (self.brain / "inbox" / "raw" / "email").mkdir(parents=True)
        (self.brain / "inbox" / "triage").mkdir(parents=True)
        (self.brain / "config").mkdir()
        (self.brain / "config" / "routing-rules.md").write_text("# Routing rules\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self, senders, destination="unmatched"):
        blocks = []
        for i, sender in enumerate(senders, 1):
            name = f"c{i}.md"
            (self.brain / "inbox" / "raw" / "email" / name).write_text(capture(sender))
            blocks.append(tsr.triage.build_row_block(i, f"inbox/raw/email/{name}", f"preview {i}", destination=destination))
        return "---\nstatus: pending\n---\n\n# Plan\n\n" + "\n\n".join(blocks) + "\n"

    def test_offers_a_checkbox_per_unresolved_sender(self):
        text = self._plan(['A <a@x.com>', 'A <a@x.com>', 'B <b@y.com>'])
        new_text, offered = tsr.write_section(self.brain, text)
        self.assertEqual(offered, 2)
        self.assertIn("Always bin **A** `a@x.com` · 2 today", new_text)
        self.assertIn("Always bin **B** `b@y.com`", new_text)

    def test_the_checkboxes_are_not_rows(self):
        """Execute must be unable to see or act on them."""
        text = self._plan(['A <a@x.com>', 'A <a@x.com>'])
        new_text, _ = tsr.write_section(self.brain, text)
        self.assertEqual(len(execute.parse_plan_rows(new_text)), 2)
        self.assertEqual(execute.check_row_blocks(new_text), [])

    def test_the_section_sorts_last_and_regrouping_is_a_fixed_point(self):
        text = self._plan(['A <a@x.com>', 'A <a@x.com>'], destination="discard")
        new_text, _ = tsr.write_section(self.brain, text)
        self.assertLess(new_text.index("## discard"),
                        new_text.index(f"## {execute.SENDER_RULES_HEADING}"))
        self.assertEqual(execute.regroup_plan(new_text), new_text)

    def test_a_varying_local_part_collapses_to_the_domain(self):
        """A randomised local part would make a rule that never fires again."""
        text = self._plan(['A <no-reply-aaa@m.z.com>', 'A <no-reply-bbb@m.z.com>'])
        new_text, _ = tsr.write_section(self.brain, text)
        self.assertIn("`m.z.com` · 2 today", new_text)
        self.assertNotIn("no-reply-aaa", new_text)

    def test_a_stable_address_keeps_the_tighter_match(self):
        text = self._plan(['A <a@x.com>', 'A <a@x.com>'])
        new_text, _ = tsr.write_section(self.brain, text)
        self.assertIn("`a@x.com`", new_text)

    def test_ticking_proposes_a_diff_and_marks_the_box(self):
        text = self._plan(['A <a@x.com>', 'A <a@x.com>'])
        text, _ = tsr.write_section(self.brain, text)
        text = text.replace("- [ ] ⚡️", "- [x] ⚡️")
        new_text, proposed, skipped = tsr.apply_section(self.brain, text)
        self.assertEqual(proposed, ["A"])
        self.assertIn("(proposed — rule for A (a@x.com))", new_text)
        batch = next((self.brain / "inbox" / "rule-diffs").glob("*.md")).read_text()
        self.assertIn("then: discard", batch)
        self.assertIn("evidence-basis: sender-marked-noise", batch)
        self.assertEqual(batch.count("[[inbox/raw/email/"), 2)

    def test_a_tick_with_a_tally_suffix_is_not_ignored(self):
        """The suffix build_section() writes must not hide the tick — exactly
        the senders worth a rule are the ones that carry it."""
        text = self._plan(['A <a@x.com>', 'A <a@x.com>'])
        text, _ = tsr.write_section(self.brain, text)
        self.assertIn("· 2 today", text)
        text = text.replace("- [ ] ⚡️", "- [x] ⚡️")
        _, proposed, _ = tsr.apply_section(self.brain, text)
        self.assertEqual(proposed, ["A"])

    def test_a_single_sighting_is_not_proposed(self):
        text = self._plan(['A <a@x.com>'])
        text, _ = tsr.write_section(self.brain, text)
        text = text.replace("- [ ] ⚡️", "- [x] ⚡️")
        _, proposed, skipped = tsr.apply_section(self.brain, text)
        self.assertEqual(proposed, [])
        self.assertTrue(skipped)

    def test_an_already_proposed_box_is_not_proposed_twice(self):
        text = self._plan(['A <a@x.com>', 'A <a@x.com>'])
        text, _ = tsr.write_section(self.brain, text)
        text = text.replace("- [ ] ⚡️", "- [x] ⚡️")
        once, _, _ = tsr.apply_section(self.brain, text)
        _, proposed, _ = tsr.apply_section(self.brain, once)
        self.assertEqual(proposed, [])

    def test_a_tick_survives_a_rebuild(self):
        text = self._plan(['A <a@x.com>', 'A <a@x.com>'])
        text, _ = tsr.write_section(self.brain, text)
        text = text.replace("- [ ] ⚡️", "- [x] ⚡️")
        rebuilt, _ = tsr.write_section(self.brain, text)
        self.assertIn("- [x] ⚡️ Always bin **A**", rebuilt)


if __name__ == "__main__":
    unittest.main()
