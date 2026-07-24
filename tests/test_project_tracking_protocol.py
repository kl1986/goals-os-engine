import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PROTOCOL_PATH = REPO_ROOT / "protocols" / "project-tracking.md"


class TestProjectTrackingProtocol(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PROTOCOL_PATH.is_file(), "protocols/project-tracking.md must exist")
        self.content = PROTOCOL_PATH.read_text()

    def test_schema_includes_repos_field(self):
        self.assertIn("repos:", self.content, "Project schema frontmatter must include repos: field")

    def test_documents_code_root_relative_paths(self):
        self.assertIn("code_root", self.content, "Protocol must mention code_root setting")

    def test_documents_absence_fails_closed(self):
        self.assertIn("fail closed", self.content.lower(), "Protocol must document that absent repos: fails closed")

    def test_documents_multi_repo_and_per_ticket_resolution(self):
        self.assertIn("per-Ticket", self.content, "Protocol must document per-Ticket resolution")

    def test_documents_no_ticket_level_repo_field(self):
        self.assertIn("ADR-0022", self.content, "Protocol must cite ADR-0022")


if __name__ == "__main__":
    unittest.main()
