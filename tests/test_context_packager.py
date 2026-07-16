import os
import shutil
import tempfile
import unittest
from pathlib import Path


from scripts.context_packager import get_category, bundle_context

class TestContextPackager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.test_dir, 'scratch')
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
        
    def test_get_category(self):
        self.assertEqual(get_category(Path('adrs/001-init.md')), '_adrs_context.md')
        self.assertEqual(get_category(Path('docs/ticket-123.md')), '_tickets_context.md')
        self.assertEqual(get_category(Path('src/main.py')), '_code_context.md')
        self.assertEqual(get_category(Path('issues/bug.txt')), '_tickets_context.md')
        
    def test_bundle_context(self):
        # Create some dummy files
        adr_file = Path(self.test_dir) / "001-adr.md"
        adr_file.write_text("ADR Content")
        
        ticket_file = Path(self.test_dir) / "ticket-1.md"
        ticket_file.write_text("Ticket Content")
        
        code_file = Path(self.test_dir) / "app.py"
        code_file.write_text("print('hello')")
        
        unreadable_file = Path(self.test_dir) / "unreadable.md"
        unreadable_file.write_text("unreadable")
        os.chmod(unreadable_file, 0o000)  # Make unreadable
        
        patterns = [
            str(Path(self.test_dir) / "*.md"),
            str(Path(self.test_dir) / "*.py")
        ]
        
        bundle_context(patterns, self.output_dir)
        
        # Clean up permissions so rmtree can delete it in tearDown
        os.chmod(unreadable_file, 0o644)

        # Verify outputs
        out_path = Path(self.output_dir)
        self.assertTrue((out_path / "_adrs_context.md").exists())
        self.assertTrue((out_path / "_tickets_context.md").exists())
        self.assertTrue((out_path / "_code_context.md").exists())
        
        adr_out = (out_path / "_adrs_context.md").read_text()
        self.assertIn("ADR Content", adr_out)
        self.assertIn("001-adr.md", adr_out)
        
        ticket_out = (out_path / "_tickets_context.md").read_text()
        self.assertIn("Ticket Content", ticket_out)
        
        code_out = (out_path / "_code_context.md").read_text()
        self.assertIn("print('hello')", code_out)

    def test_empty_files(self):
        bundle_context([str(Path(self.test_dir) / "nonexistent*.txt")], self.output_dir)
        out_path = Path(self.output_dir)
        self.assertFalse(out_path.exists() and any(out_path.iterdir()))

if __name__ == '__main__':
    unittest.main()
