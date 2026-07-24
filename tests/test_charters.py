import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARTERS_DIR = os.path.join(REPO_ROOT, "protocols", "charters")
CHARTER_SCHEMA_PATH = os.path.join(REPO_ROOT, "protocols", "charter-schema.md")

def parse_simple_frontmatter(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    fm_lines = parts[1].strip().split("\n")
    data = {}
    for line in fm_lines:
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data

class TestCharterSchema(unittest.TestCase):
    def test_charter_schema_version_is_v1(self):
        with open(CHARTER_SCHEMA_PATH, "r", encoding="utf-8") as f:
            first_line = f.readline()
        self.assertIn("(v1)", first_line, "protocols/charter-schema.md should be bumped to v1")

    def test_all_charters_have_valid_frontmatter_and_owner(self):
        charter_files = []
        for root, _, files in os.walk(CHARTERS_DIR):
            for file in files:
                if file.endswith(".md"):
                    charter_files.append(os.path.join(root, file))

        self.assertGreater(len(charter_files), 0, "No charter files found in protocols/charters/")

        for filepath in charter_files:
            rel_path = os.path.relpath(filepath, REPO_ROOT)
            fm = parse_simple_frontmatter(filepath)
            self.assertEqual(fm.get("type"), "charter", f"{rel_path} missing 'type: charter'")
            self.assertIn(fm.get("charter-kind"), {"system", "area", "capability"}, f"{rel_path} has invalid 'charter-kind'")
            if "owner" in fm:
                self.assertIn(fm["owner"], {"engine", "plugin"}, f"{rel_path} has invalid 'owner' (must be 'engine' or 'plugin')")
            owner = fm.get("owner", "engine")
            self.assertIn(owner, {"engine", "plugin"}, f"{rel_path} effective owner must be 'engine' or 'plugin'")
            self.assertIn(fm.get("scope"), {"generic", "instance"}, f"{rel_path} has invalid 'scope'")

if __name__ == "__main__":
    unittest.main()
