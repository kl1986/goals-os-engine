import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import rename_tickets_drop_id_prefix as rename_script  # noqa: E402


def _ticket(brain_path, kind, slug, filename, title, extra_body=""):
    d = brain_path / "tasks" / kind / slug
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    path.write_text(
        f"---\nstatus: prioritised\ntype: task\n---\n\n# {title}\n\n{extra_body}"
    )
    return path


class TestRenameTicketsDropIdPrefix(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_renames_slug_number_filename_to_slugified_title(self):
        _ticket(self.brain_path, "projects", "clear-the-garage",
                "clear-the-garage-1.md", "Install the bike rack")
        manifest, _ = rename_script.rename_tickets(self.brain_path)
        garage_dir = self.brain_path / "tasks" / "projects" / "clear-the-garage"
        self.assertTrue((garage_dir / "install-the-bike-rack.md").exists())
        self.assertFalse((garage_dir / "clear-the-garage-1.md").exists())
        self.assertEqual(manifest, {"clear-the-garage-1": "install-the-bike-rack"})

    def test_already_correctly_named_ticket_is_left_alone(self):
        _ticket(self.brain_path, "projects", "clear-the-garage",
                "install-the-bike-rack.md", "Install the bike rack")
        manifest, _ = rename_script.rename_tickets(self.brain_path)
        self.assertEqual(manifest, {})
        self.assertTrue(
            (self.brain_path / "tasks" / "projects" / "clear-the-garage" / "install-the-bike-rack.md").exists()
        )

    def test_area_ticket_renamed_same_as_project_ticket(self):
        _ticket(self.brain_path, "areas", "health",
                "health-1.md", "Book a dentist appointment")
        manifest, _ = rename_script.rename_tickets(self.brain_path)
        health_dir = self.brain_path / "tasks" / "areas" / "health"
        self.assertTrue((health_dir / "book-a-dentist-appointment.md").exists())
        self.assertEqual(manifest, {"health-1": "book-a-dentist-appointment"})

    def test_collision_within_folder_gets_numeric_suffix(self):
        _ticket(self.brain_path, "projects", "return-on-constraints",
                "return-on-constraints-5-untitled.md", "Untitled ticket")
        _ticket(self.brain_path, "projects", "return-on-constraints",
                "return-on-constraints-6-untitled.md", "Untitled ticket")
        manifest, _ = rename_script.rename_tickets(self.brain_path)
        target_dir = self.brain_path / "tasks" / "projects" / "return-on-constraints"
        self.assertTrue((target_dir / "untitled-ticket.md").exists())
        self.assertTrue((target_dir / "untitled-ticket-2.md").exists())
        self.assertEqual(len(manifest), 2)

    def test_single_blocked_by_reference_rewritten_to_wikilink(self):
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-11-scheduler-adapter-implementation.md",
                "Scheduler adapter implementation")
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-12-rule-learning-activation.md",
                "Rule learning activation",
                extra_body="> Blocked by: goals-os-11\n\nSome body text.\n")

        _, lookup = rename_script.rename_tickets(self.brain_path)
        changed = rename_script.fix_blocked_by_references(self.brain_path, lookup)

        goals_os_dir = self.brain_path / "tasks" / "projects" / "goals-os"
        new_text = (goals_os_dir / "rule-learning-activation.md").read_text()
        self.assertIn("> Blocked by: [[scheduler-adapter-implementation]]", new_text)
        self.assertEqual(len(changed), 1)

    def test_multiple_comma_separated_blocked_by_references_all_rewritten(self):
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-22-trigger-and-scope.md", "Trigger and scope")
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-23-diagram-generation.md", "Diagram generation",
                extra_body="> Blocked by: goals-os-22\n")
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-24-context-packaging.md", "Context packaging",
                extra_body="> Blocked by: goals-os-22\n")
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-25-video-stitching.md", "Video stitching",
                extra_body="> Blocked by: goals-os-23, goals-os-24\n")

        _, lookup = rename_script.rename_tickets(self.brain_path)
        rename_script.fix_blocked_by_references(self.brain_path, lookup)

        goals_os_dir = self.brain_path / "tasks" / "projects" / "goals-os"
        video_text = (goals_os_dir / "video-stitching.md").read_text()
        self.assertIn(
            "> Blocked by: [[diagram-generation]], [[context-packaging]]",
            video_text,
        )

    def test_unrecognized_blocked_by_token_left_untouched(self):
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-15-triage-has-no-automation-path.md",
                "Triage has no automation path",
                extra_body="> Blocked by: goals-os-99\n")  # no ticket goals-os-99 exists
        _, lookup = rename_script.rename_tickets(self.brain_path)
        rename_script.fix_blocked_by_references(self.brain_path, lookup)
        goals_os_dir = self.brain_path / "tasks" / "projects" / "goals-os"
        text = (goals_os_dir / "triage-has-no-automation-path.md").read_text()
        self.assertIn("> Blocked by: goals-os-99", text)

    def test_already_wikilinked_blocked_by_left_untouched(self):
        _ticket(self.brain_path, "projects", "goals-os",
                "already-new-style.md", "Already new style",
                extra_body="> Blocked by: [[some-other-ticket]]\n")
        _, lookup = rename_script.rename_tickets(self.brain_path)
        changed = rename_script.fix_blocked_by_references(self.brain_path, lookup)
        self.assertEqual(changed, [])

    def test_ticket_body_otherwise_unchanged_by_rename(self):
        path = _ticket(self.brain_path, "projects", "clear-the-garage",
                        "clear-the-garage-2.md", "Buy paint",
                        extra_body="Some extra notes.\n")
        original_text = path.read_text()
        rename_script.rename_tickets(self.brain_path)
        new_path = self.brain_path / "tasks" / "projects" / "clear-the-garage" / "buy-paint.md"
        self.assertEqual(new_path.read_text(), original_text)

    def test_second_run_is_a_no_op(self):
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-11-scheduler-adapter-implementation.md",
                "Scheduler adapter implementation")
        _ticket(self.brain_path, "projects", "goals-os",
                "goals-os-12-rule-learning-activation.md",
                "Rule learning activation",
                extra_body="> Blocked by: goals-os-11\n")

        manifest_1, lookup_1 = rename_script.rename_tickets(self.brain_path)
        rename_script.fix_blocked_by_references(self.brain_path, lookup_1)

        manifest_2, lookup_2 = rename_script.rename_tickets(self.brain_path)
        changed_2 = rename_script.fix_blocked_by_references(self.brain_path, lookup_2)

        self.assertEqual(manifest_2, {})
        self.assertEqual(changed_2, [])


if __name__ == "__main__":
    unittest.main()
