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

    def test_strict_mode_fails_when_identity_tier_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(personal_data_check, "tracked_files", return_value=[]):
                exit_code = personal_data_check.main(["--root", temporary])

        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
