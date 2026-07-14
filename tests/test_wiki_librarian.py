import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import wiki_librarian  # noqa: E402

NOW = dt.datetime(2026, 7, 14, 9, 30)


def _write_archived_capture(brain_path, source, filename, date_str, body="Some body text."):
    d = brain_path / "archive" / "inbox" / source
    d.mkdir(parents=True, exist_ok=True)
    stem = filename[:-3] if filename.endswith(".md") else filename
    (d / filename).write_text(
        f"---\ntype: raw\ndate: {date_str}\nsource: {source}\nid: {stem}\nraw: true\n---\n\n"
        f"# {stem}\n\n{body}\n"
    )
    return f"archive/inbox/{source}/{stem}"


class TestReadIndex(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_index_returns_empty_list(self):
        self.assertEqual(wiki_librarian.read_index(self.brain_path), [])

    def test_parses_rows(self):
        wiki_dir = self.brain_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "_index.md").write_text(
            "---\ntype: wiki-index\n---\n\n# Wiki — Index\n\n"
            "| Article | Summary |\n|---|---|\n"
            "| [[hyrox-training]] | Hyrox training notes |\n"
            "| [[curry-paste-recipes]] | Curry paste recipes |\n"
        )
        rows = wiki_librarian.read_index(self.brain_path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {"slug": "hyrox-training", "summary": "Hyrox training notes"})
        self.assertEqual(rows[1], {"slug": "curry-paste-recipes", "summary": "Curry paste recipes"})


class TestListArchivedCaptures(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_archive_dir_returns_empty(self):
        self.assertEqual(wiki_librarian.list_archived_captures(self.brain_path), [])

    def test_reads_across_every_source_subfolder(self):
        _write_archived_capture(self.brain_path, "voice", "2026-07-11-a.md", "2026-07-11", "Voice body")
        _write_archived_capture(self.brain_path, "text", "2026-07-12-b.md", "2026-07-12", "Text body")
        captures = wiki_librarian.list_archived_captures(self.brain_path)
        self.assertEqual(len(captures), 2)
        sources = sorted(c["source"] for c in captures)
        self.assertEqual(sources, ["text", "voice"])
        for c in captures:
            self.assertIn("path", c)
            self.assertTrue(c["path"].startswith("archive/inbox/"))


class TestCitedCapturePaths(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        self.wiki_dir = self.brain_path / "wiki"
        self.wiki_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_collects_source_links_from_flat_articles(self):
        (self.wiki_dir / "hyrox-training.md").write_text(
            "---\ntype: wiki-article\nconcept: hyrox-training\ntags: [wiki]\n---\n\n"
            "# Hyrox training\n\nSome synthesized content.\n\n"
            "## Sources\n- 2026-07-11 — [[archive/inbox/voice/2026-07-11-a]]\n"
        )
        cited = wiki_librarian.cited_capture_paths(self.brain_path)
        self.assertEqual(cited, {"archive/inbox/voice/2026-07-11-a"})

    def test_ignores_non_article_root_files(self):
        # Simulates the real Vault: pre-existing v1-migrated content sitting
        # alongside the new flat structure (_master-index.md, _memory.md,
        # README.md) must never be scanned as if it were a flat article.
        (self.wiki_dir / "_master-index.md").write_text(
            "Some v1 content referencing [[archive/inbox/voice/should-not-count]]\n"
        )
        (self.wiki_dir / "_memory.md").write_text("notes\n")
        (self.wiki_dir / "README.md").write_text("readme\n")
        (self.wiki_dir / "_index.md").write_text("| Article | Summary |\n|---|---|\n")
        cited = wiki_librarian.cited_capture_paths(self.brain_path)
        self.assertEqual(cited, set())

    def test_ignores_subdirectories(self):
        v1_concept_dir = self.wiki_dir / "some-v1-concept"
        v1_concept_dir.mkdir()
        (v1_concept_dir / "_index.md").write_text("stuff\n")
        (v1_concept_dir / "Some Article.md").write_text(
            "[[archive/inbox/voice/should-not-count]]\n"
        )
        cited = wiki_librarian.cited_capture_paths(self.brain_path)
        self.assertEqual(cited, set())


class TestNewCapturesForCompile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_all_captures_new_when_nothing_cited_yet(self):
        _write_archived_capture(self.brain_path, "voice", "2026-07-11-a.md", "2026-07-11")
        new = wiki_librarian.new_captures_for_compile(self.brain_path)
        self.assertEqual(len(new), 1)

    def test_excludes_already_cited_captures(self):
        path = _write_archived_capture(self.brain_path, "voice", "2026-07-11-a.md", "2026-07-11")
        (self.brain_path / "wiki" / "hyrox-training.md").write_text(
            f"## Sources\n- 2026-07-11 — [[{path}]]\n"
        )
        new = wiki_librarian.new_captures_for_compile(self.brain_path)
        self.assertEqual(new, [])


class TestCompileScan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_scope_forces_nothing(self):
        result = wiki_librarian.compile_scan(self.brain_path)
        self.assertEqual(result["forced_concepts"], [])

    def test_single_concept_scope_forces_that_concept(self):
        result = wiki_librarian.compile_scan(self.brain_path, scope="hyrox-training")
        self.assertEqual(result["forced_concepts"], ["hyrox-training"])

    def test_full_scope_forces_every_indexed_concept(self):
        (self.brain_path / "wiki" / "_index.md").write_text(
            "| Article | Summary |\n|---|---|\n"
            "| [[hyrox-training]] | x |\n| [[curry-paste-recipes]] | y |\n"
        )
        result = wiki_librarian.compile_scan(self.brain_path, scope="full")
        self.assertEqual(sorted(result["forced_concepts"]), ["curry-paste-recipes", "hyrox-training"])

    def test_includes_new_captures_and_index(self):
        _write_archived_capture(self.brain_path, "voice", "2026-07-11-a.md", "2026-07-11")
        result = wiki_librarian.compile_scan(self.brain_path)
        self.assertEqual(len(result["new_captures"]), 1)
        self.assertEqual(result["index"], [])


class TestCompileRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()
        (self.brain_path / "config").mkdir()
        (self.brain_path / "config" / "routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Compile | never |\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_bumps_heartbeat_regardless_of_outcome(self):
        wiki_librarian.compile_run(self.brain_path, now=NOW)
        state_text = (self.brain_path / "config" / "routine-state.md").read_text()
        self.assertIn("| Compile | 2026-07-14 09:30 |", state_text)


class TestApplyCompile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_new_article_and_index_row(self):
        path = wiki_librarian.apply_compile(
            self.brain_path,
            concept_slug="hyrox-training",
            concept_title="Hyrox Training",
            article_body="Synthesized content about Hyrox training.",
            source_refs=[("2026-07-11", "archive/inbox/voice/2026-07-11-a")],
            now=NOW,
        )
        self.assertEqual(path, self.brain_path / "wiki" / "hyrox-training.md")
        text = path.read_text()
        self.assertIn("type: wiki-article", text)
        self.assertIn("# Hyrox Training", text)
        self.assertIn("Synthesized content about Hyrox training.", text)
        self.assertIn("## Sources\n- 2026-07-11 — [[archive/inbox/voice/2026-07-11-a]]", text)

        index_text = (self.brain_path / "wiki" / "_index.md").read_text()
        self.assertIn("[[hyrox-training]]", index_text)
        self.assertIn("Hyrox Training", index_text)

    def test_resynthesis_replaces_body_but_preserves_and_extends_sources(self):
        wiki_librarian.apply_compile(
            self.brain_path, "hyrox-training", "Hyrox Training", "Original body.",
            [("2026-07-11", "archive/inbox/voice/2026-07-11-a")], now=NOW,
        )
        wiki_librarian.apply_compile(
            self.brain_path, "hyrox-training", "Hyrox Training", "Fully resynthesized new body.",
            [("2026-07-12", "archive/inbox/voice/2026-07-12-b")], now=NOW,
        )
        text = (self.brain_path / "wiki" / "hyrox-training.md").read_text()
        self.assertNotIn("Original body.", text)
        self.assertIn("Fully resynthesized new body.", text)
        self.assertIn("- 2026-07-11 — [[archive/inbox/voice/2026-07-11-a]]", text)
        self.assertIn("- 2026-07-12 — [[archive/inbox/voice/2026-07-12-b]]", text)

    def test_does_not_duplicate_index_row_on_rerun(self):
        wiki_librarian.apply_compile(
            self.brain_path, "hyrox-training", "Hyrox Training", "Body one.", [], now=NOW,
        )
        wiki_librarian.apply_compile(
            self.brain_path, "hyrox-training", "Hyrox Training", "Body two.", [], now=NOW,
        )
        index_text = (self.brain_path / "wiki" / "_index.md").read_text()
        self.assertEqual(index_text.count("[[hyrox-training]]"), 1)

    def test_does_not_duplicate_source_ref_already_present(self):
        wiki_librarian.apply_compile(
            self.brain_path, "hyrox-training", "Hyrox Training", "Body.",
            [("2026-07-11", "archive/inbox/voice/2026-07-11-a")], now=NOW,
        )
        wiki_librarian.apply_compile(
            self.brain_path, "hyrox-training", "Hyrox Training", "Body two.",
            [("2026-07-11", "archive/inbox/voice/2026-07-11-a")], now=NOW,
        )
        text = (self.brain_path / "wiki" / "hyrox-training.md").read_text()
        self.assertEqual(text.count("archive/inbox/voice/2026-07-11-a"), 1)

    def test_logs_action_log_entry(self):
        wiki_librarian.apply_compile(
            self.brain_path, "hyrox-training", "Hyrox Training", "Body.",
            [("2026-07-11", "archive/inbox/voice/2026-07-11-a")], now=NOW,
        )
        log_text = (self.brain_path / "log" / "2026-07-14.md").read_text()
        self.assertIn("wiki-compile", log_text)
        self.assertIn("Librarian", log_text)

    def test_pipe_in_summary_does_not_break_index_table(self):
        wiki_librarian.apply_compile(
            self.brain_path, "hyrox-training", "Hyrox Training", "Body.", [],
            now=NOW, summary="Training | recovery | conditioning",
        )
        index_text = (self.brain_path / "wiki" / "_index.md").read_text()
        rows = wiki_librarian.read_index(self.brain_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["slug"], "hyrox-training")
        self.assertNotIn("\n", rows[0]["summary"])


class TestFindDeadLinks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_articles_no_findings(self):
        self.assertEqual(wiki_librarian.find_dead_links(self.brain_path), [])

    def test_live_source_link_is_not_flagged(self):
        _write_archived_capture(self.brain_path, "voice", "2026-07-11-a.md", "2026-07-11")
        (self.brain_path / "wiki" / "hyrox-training.md").write_text(
            "# Hyrox training\n\nbody\n\n## Sources\n"
            "- 2026-07-11 — [[archive/inbox/voice/2026-07-11-a]]\n"
        )
        self.assertEqual(wiki_librarian.find_dead_links(self.brain_path), [])

    def test_dead_source_link_is_flagged(self):
        (self.brain_path / "wiki" / "hyrox-training.md").write_text(
            "# Hyrox training\n\nbody\n\n## Sources\n"
            "- 2026-07-11 — [[archive/inbox/voice/does-not-exist]]\n"
        )
        findings = wiki_librarian.find_dead_links(self.brain_path)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["article"], "hyrox-training")
        self.assertEqual(findings[0]["link"], "archive/inbox/voice/does-not-exist")

    def test_live_cross_article_link_is_not_flagged(self):
        (self.brain_path / "wiki" / "curry-paste-recipes.md").write_text("# Curry paste recipes\n\nbody\n")
        (self.brain_path / "wiki" / "hyrox-training.md").write_text(
            "# Hyrox training\n\nSee also [[curry-paste-recipes]].\n"
        )
        self.assertEqual(wiki_librarian.find_dead_links(self.brain_path), [])

    def test_dead_cross_article_link_is_flagged(self):
        (self.brain_path / "wiki" / "hyrox-training.md").write_text(
            "# Hyrox training\n\nSee also [[no-such-concept]].\n"
        )
        findings = wiki_librarian.find_dead_links(self.brain_path)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["link"], "no-such-concept")


class TestFindOrphans(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_findings_when_consistent(self):
        (self.brain_path / "wiki" / "hyrox-training.md").write_text("# Hyrox training\n")
        (self.brain_path / "wiki" / "_index.md").write_text(
            "| Article | Summary |\n|---|---|\n| [[hyrox-training]] | x |\n"
        )
        result = wiki_librarian.find_orphans(self.brain_path)
        self.assertEqual(result, {"unindexed_articles": [], "dangling_index_entries": []})

    def test_unindexed_article_flagged(self):
        (self.brain_path / "wiki" / "hyrox-training.md").write_text("# Hyrox training\n")
        (self.brain_path / "wiki" / "_index.md").write_text("| Article | Summary |\n|---|---|\n")
        result = wiki_librarian.find_orphans(self.brain_path)
        self.assertEqual(result["unindexed_articles"], ["hyrox-training"])
        self.assertEqual(result["dangling_index_entries"], [])

    def test_dangling_index_entry_flagged(self):
        (self.brain_path / "wiki" / "_index.md").write_text(
            "| Article | Summary |\n|---|---|\n| [[ghost-concept]] | x |\n"
        )
        result = wiki_librarian.find_orphans(self.brain_path)
        self.assertEqual(result["dangling_index_entries"], ["ghost-concept"])
        self.assertEqual(result["unindexed_articles"], [])

    def test_non_article_files_never_flagged_as_unindexed(self):
        (self.brain_path / "wiki" / "_master-index.md").write_text("v1 content\n")
        (self.brain_path / "wiki" / "_memory.md").write_text("v1 content\n")
        (self.brain_path / "wiki" / "README.md").write_text("readme\n")
        (self.brain_path / "wiki" / "_index.md").write_text("| Article | Summary |\n|---|---|\n")
        result = wiki_librarian.find_orphans(self.brain_path)
        self.assertEqual(result["unindexed_articles"], [])

    def test_subdirectory_content_never_flagged(self):
        v1_dir = self.brain_path / "wiki" / "some-v1-concept"
        v1_dir.mkdir()
        (v1_dir / "Some Article.md").write_text("content\n")
        (self.brain_path / "wiki" / "_index.md").write_text("| Article | Summary |\n|---|---|\n")
        result = wiki_librarian.find_orphans(self.brain_path)
        self.assertEqual(result["unindexed_articles"], [])


class TestAuditScanMechanical(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_combines_dead_links_and_orphans_zero_llm_calls(self):
        (self.brain_path / "wiki" / "hyrox-training.md").write_text(
            "# Hyrox training\n\n[[no-such-concept]]\n"
        )
        (self.brain_path / "wiki" / "_index.md").write_text(
            "| Article | Summary |\n|---|---|\n| [[ghost-concept]] | x |\n"
        )
        result = wiki_librarian.audit_scan_mechanical(self.brain_path)
        self.assertEqual(len(result["dead_links"]), 1)
        self.assertEqual(result["orphans"]["unindexed_articles"], ["hyrox-training"])
        self.assertEqual(result["orphans"]["dangling_index_entries"], ["ghost-concept"])


class TestApplyFixDeadLink(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()
        (self.brain_path / "wiki" / "hyrox-training.md").write_text(
            "# Hyrox training\n\nSee [[no-such-concept]] and the rest.\n\n"
            "## Sources\n- 2026-07-11 — [[archive/inbox/voice/does-not-exist]]\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_repairs_link_when_replacement_given(self):
        wiki_librarian.apply_fix_dead_link(
            self.brain_path, "hyrox-training", "no-such-concept", "curry-paste-recipes", now=NOW,
        )
        text = (self.brain_path / "wiki" / "hyrox-training.md").read_text()
        self.assertNotIn("[[no-such-concept]]", text)
        self.assertIn("[[curry-paste-recipes]]", text)

    def test_removes_link_when_no_replacement(self):
        wiki_librarian.apply_fix_dead_link(
            self.brain_path, "hyrox-training", "archive/inbox/voice/does-not-exist", None, now=NOW,
        )
        text = (self.brain_path / "wiki" / "hyrox-training.md").read_text()
        self.assertNotIn("does-not-exist", text)

    def test_logs_action_log_entry(self):
        wiki_librarian.apply_fix_dead_link(
            self.brain_path, "hyrox-training", "no-such-concept", "curry-paste-recipes", now=NOW,
        )
        log_text = (self.brain_path / "log" / "2026-07-14.md").read_text()
        self.assertIn("wiki-audit-fix-dead-link", log_text)


class TestApplyRelistOrphan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_adds_unindexed_article_to_index(self):
        (self.brain_path / "wiki" / "hyrox-training.md").write_text("# Hyrox training\n")
        (self.brain_path / "wiki" / "_index.md").write_text("| Article | Summary |\n|---|---|\n")
        wiki_librarian.apply_relist_orphan(
            self.brain_path, action="add", slug="hyrox-training", summary="Hyrox training notes", now=NOW,
        )
        text = (self.brain_path / "wiki" / "_index.md").read_text()
        self.assertIn("[[hyrox-training]]", text)

    def test_removes_dangling_index_entry(self):
        (self.brain_path / "wiki" / "_index.md").write_text(
            "| Article | Summary |\n|---|---|\n| [[ghost-concept]] | x |\n| [[hyrox-training]] | y |\n"
        )
        (self.brain_path / "wiki" / "hyrox-training.md").write_text("# Hyrox training\n")
        wiki_librarian.apply_relist_orphan(self.brain_path, action="remove", slug="ghost-concept", now=NOW)
        text = (self.brain_path / "wiki" / "_index.md").read_text()
        self.assertNotIn("ghost-concept", text)
        self.assertIn("hyrox-training", text)

    def test_logs_action_log_entry(self):
        (self.brain_path / "wiki" / "_index.md").write_text(
            "| Article | Summary |\n|---|---|\n| [[ghost-concept]] | x |\n"
        )
        wiki_librarian.apply_relist_orphan(self.brain_path, action="remove", slug="ghost-concept", now=NOW)
        log_text = (self.brain_path / "log" / "2026-07-14.md").read_text()
        self.assertIn("wiki-audit-relist-orphan", log_text)


class TestApplyDeleteStale(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()
        (self.brain_path / "wiki" / "hyrox-training.md").write_text("# Hyrox training\n")
        (self.brain_path / "wiki" / "_index.md").write_text(
            "| Article | Summary |\n|---|---|\n"
            "| [[hyrox-training]] | x |\n| [[curry-paste-recipes]] | y |\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_deletes_article_file_and_index_row(self):
        wiki_librarian.apply_delete_stale(self.brain_path, "hyrox-training", now=NOW)
        self.assertFalse((self.brain_path / "wiki" / "hyrox-training.md").exists())
        index_text = (self.brain_path / "wiki" / "_index.md").read_text()
        self.assertNotIn("hyrox-training", index_text)
        self.assertIn("curry-paste-recipes", index_text)

    def test_no_archive_folder_created(self):
        wiki_librarian.apply_delete_stale(self.brain_path, "hyrox-training", now=NOW)
        self.assertFalse((self.brain_path / "archive" / "wiki").exists())

    def test_logs_action_log_entry(self):
        wiki_librarian.apply_delete_stale(self.brain_path, "hyrox-training", now=NOW)
        log_text = (self.brain_path / "log" / "2026-07-14.md").read_text()
        self.assertIn("wiki-audit-delete-stale", log_text)


class TestApplyMergeDuplicate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "wiki").mkdir()
        (self.brain_path / "wiki" / "hyrox-training.md").write_text(
            "---\ntype: wiki-article\nconcept: hyrox-training\ntags: [wiki]\n---\n\n"
            "# Hyrox training\n\nOriginal content.\n\n"
            "## Sources\n- 2026-07-11 — [[archive/inbox/voice/2026-07-11-a]]\n"
        )
        (self.brain_path / "wiki" / "hyrox-workouts.md").write_text(
            "---\ntype: wiki-article\nconcept: hyrox-workouts\ntags: [wiki]\n---\n\n"
            "# Hyrox workouts\n\nDuplicate content.\n\n"
            "## Sources\n- 2026-07-12 — [[archive/inbox/voice/2026-07-12-b]]\n"
        )
        (self.brain_path / "wiki" / "_index.md").write_text(
            "| Article | Summary |\n|---|---|\n"
            "| [[hyrox-training]] | x |\n| [[hyrox-workouts]] | y |\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_merges_into_keep_slug_and_deletes_merge_slug(self):
        wiki_librarian.apply_merge_duplicate(
            self.brain_path, keep_slug="hyrox-training", merge_slug="hyrox-workouts",
            merged_body="Fully merged content covering both.", now=NOW,
        )
        self.assertFalse((self.brain_path / "wiki" / "hyrox-workouts.md").exists())
        keep_text = (self.brain_path / "wiki" / "hyrox-training.md").read_text()
        self.assertIn("Fully merged content covering both.", keep_text)
        self.assertIn("archive/inbox/voice/2026-07-11-a", keep_text)
        self.assertIn("archive/inbox/voice/2026-07-12-b", keep_text)

    def test_removes_merge_slug_from_index_keeps_keep_slug(self):
        wiki_librarian.apply_merge_duplicate(
            self.brain_path, keep_slug="hyrox-training", merge_slug="hyrox-workouts",
            merged_body="Merged.", now=NOW,
        )
        index_text = (self.brain_path / "wiki" / "_index.md").read_text()
        self.assertNotIn("hyrox-workouts", index_text)
        self.assertIn("hyrox-training", index_text)

    def test_logs_action_log_entry_as_hard_to_reverse(self):
        wiki_librarian.apply_merge_duplicate(
            self.brain_path, keep_slug="hyrox-training", merge_slug="hyrox-workouts",
            merged_body="Merged.", now=NOW,
        )
        log_text = (self.brain_path / "log" / "2026-07-14.md").read_text()
        self.assertIn("wiki-audit-merge-duplicate", log_text)


if __name__ == "__main__":
    unittest.main()
