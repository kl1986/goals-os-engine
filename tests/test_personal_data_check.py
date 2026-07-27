import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import personal_data_check  # noqa: E402


class TestPersonalDataCheck(unittest.TestCase):
    def test_generic_findings_identify_category_file_and_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "note.md").write_text("Contact person" + "@example.test\n")

            findings = personal_data_check.scan_paths(root, [root / "note.md"])

        self.assertEqual([(f.category, f.relative_path, f.line) for f in findings], [
            ("email-address", "note.md", 1),
        ])

    def test_absolute_home_path_finds_a_real_path_but_not_its_own_rule(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            note = root / "note.md"
            note.write_text("Local checkout: /" + "Users/example/project\\n")

            findings = personal_data_check.scan_paths(root, [note])

        self.assertEqual([(f.category, f.relative_path, f.line) for f in findings], [
            ("absolute-home-path", "note.md", 1),
        ])

        checker = Path(personal_data_check.__file__).resolve()
        checker_root = checker.parent.parent
        checker_findings = personal_data_check.scan_paths(checker_root, [checker])
        self.assertNotIn(
            "absolute-home-path", [finding.category for finding in checker_findings]
        )

    def test_identity_findings_never_include_the_matched_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "note.md"
            path.write_text("Private Identity\n")

            findings = personal_data_check.scan_paths(root, [path], ["Private Identity"])
            report = personal_data_check.format_report(findings)

        self.assertIn("identity-term", report)
        self.assertNotIn("Private Identity", report)

    def test_allowlist_is_scoped_to_path_and_identity_term(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / "LICENSE"
            blocked = root / "note.md"
            allowed.write_text("Private Identity\n")
            blocked.write_text("Private Identity\n")

            findings = personal_data_check.scan_paths(
                root,
                [allowed, blocked],
                ["Private Identity"],
                {("LICENSE", "Private Identity")},
            )

        self.assertEqual([(f.relative_path, f.category) for f in findings], [
            ("note.md", "identity-term"),
        ])

    def test_private_brain_is_rejected_structurally(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "config" / "code-root.md").write_text("private configuration\n")

            self.assertTrue(personal_data_check.is_private_brain(root))

    def test_strict_mode_passes_a_clean_generic_scan_without_a_private_brain(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(personal_data_check, "tracked_files", return_value=[]):
                exit_code = personal_data_check.main(["--root", temporary])

        self.assertEqual(exit_code, 0)

    def test_strict_mode_fails_for_an_unavailable_requested_identity_tier(self):
        with tempfile.TemporaryDirectory() as temporary:
            exit_code = personal_data_check.main(["--root", temporary, "--brain", temporary])

        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
