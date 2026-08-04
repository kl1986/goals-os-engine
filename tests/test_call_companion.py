import datetime as dt
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import call_companion  # noqa: E402
import frontmatter  # noqa: E402


def mock_provider(candidates):
    proposals = []
    for c in candidates:
        proposals.append({
            "path": c["path"],
            "call_suitable": True,
            "estimate_minutes": 30,
            "rationale": f"Suitable for audio call: {c['title']}"
        })
    return proposals


class TestCallCompanion(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_path = Path(self._tmp.name)
        (self.brain_path / "tasks" / "projects" / "p1").mkdir(parents=True)
        (self.brain_path / "tasks" / "areas" / "a1").mkdir(parents=True)
        self.now = dt.datetime(2026, 8, 4, 14, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def _create_ticket(self, rel_path: str, status="backlog", priority="medium", call_suitable=None, estimate_minutes=None):
        file_path = self.brain_path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fm_lines = [
            "---",
            f"status: {status}",
            "type: task",
        ]
        if priority is not None:
            fm_lines.append(f"priority: {priority}")
        if call_suitable is not None:
            fm_lines.append(f"call_suitable: {call_suitable}")
        if estimate_minutes is not None:
            fm_lines.append(f"estimate_minutes: {estimate_minutes}")
        fm_lines.extend([
            "---",
            "",
            f"# {file_path.stem}",
            "",
            "Some task description.",
        ])
        content = "\n".join(fm_lines) + "\n"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def test_f13_no_banned_imports(self):
        """F13: Assert execute, triage, dashboard are absent from sys.modules when call_companion is imported in a clean interpreter."""
        cmd = [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; sys.path.insert(0, str(Path('scripts').resolve())); "
            "import call_companion; "
            "assert 'execute' not in sys.modules, 'execute in sys.modules'; "
            "assert 'triage' not in sys.modules, 'triage in sys.modules'; "
            "assert 'dashboard' not in sys.modules, 'dashboard in sys.modules'"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))
        self.assertEqual(res.returncode, 0, f"Clean import failed: {res.stderr}")

    def test_f14_u2028_in_frontmatter_value_preserved(self):
        """F14: U+2028 inside frontmatter values must not split key-value into two frontmatter lines."""
        text = "---\nstatus: backlog\ntitle: \"Fix bug\u2028part 2\"\ntype: task\n---\n\n# Body\n"
        updated = frontmatter._update_frontmatter(text, {"call_suitable": "true"})
        self.assertIn("title: \"Fix bug\u2028part 2\"", updated)
        fm_dict = frontmatter.parse_frontmatter_dict(updated)
        self.assertEqual(fm_dict["title"], "Fix bug\u2028part 2")

    def test_twenty_bound(self):
        for i in range(25):
            self._create_ticket(f"tasks/projects/p1/ticket-{i:02d}.md", priority="medium")

        candidates = call_companion.gather_candidates(self.brain_path, limit=20)
        self.assertEqual(len(candidates), 20)

    def test_priority_ordering(self):
        self._create_ticket("tasks/projects/p1/ticket-low.md", priority="low")
        self._create_ticket("tasks/projects/p1/ticket-high.md", priority="high")
        self._create_ticket("tasks/projects/p1/ticket-none.md", priority=None)
        self._create_ticket("tasks/projects/p1/ticket-medium.md", priority="medium")
        self._create_ticket("tasks/projects/p1/ticket-high-b.md", priority="high")

        candidates = call_companion.gather_candidates(self.brain_path, limit=20)
        paths = [c["path"] for c in candidates]

        expected = [
            "tasks/projects/p1/ticket-high-b.md",
            "tasks/projects/p1/ticket-high.md",
            "tasks/projects/p1/ticket-medium.md",
            "tasks/projects/p1/ticket-low.md",
            "tasks/projects/p1/ticket-none.md",
        ]
        self.assertEqual(paths, expected)

    def test_unclassified_only_selection(self):
        self._create_ticket("tasks/projects/p1/unclassified-1.md", status="backlog", call_suitable=None)
        self._create_ticket("tasks/projects/p1/unclassified-2.md", status="prioritised", call_suitable="")
        self._create_ticket("tasks/projects/p1/classified-false.md", status="backlog", call_suitable="false")
        self._create_ticket("tasks/projects/p1/classified-true.md", status="backlog", call_suitable="true")
        self._create_ticket("tasks/projects/p1/done-ticket.md", status="done", call_suitable=None)
        self._create_ticket("tasks/projects/p1/deprioritized-ticket.md", status="deprioritized", call_suitable=None)

        candidates = call_companion.gather_candidates(self.brain_path, limit=20)
        paths = [c["path"] for c in candidates]

        self.assertEqual(sorted(paths), [
            "tasks/projects/p1/unclassified-1.md",
            "tasks/projects/p1/unclassified-2.md",
        ])

    def test_propose_writes_nothing(self):
        t1 = self._create_ticket("tasks/projects/p1/t1.md")
        t2 = self._create_ticket("tasks/projects/p1/t2.md")

        candidates = call_companion.gather_candidates(self.brain_path)
        content_before = {
            t1: t1.read_bytes(),
            t2: t2.read_bytes()
        }

        proposals = call_companion.propose(candidates, mock_provider)
        self.assertEqual(len(proposals), 2)

        self.assertEqual(t1.read_bytes(), content_before[t1])
        self.assertEqual(t2.read_bytes(), content_before[t2])

    def test_apply_confirmed_writes_only_confirmed_tickets(self):
        t1 = self._create_ticket("tasks/projects/p1/t1.md")
        t2 = self._create_ticket("tasks/projects/p1/t2.md")

        candidates = call_companion.gather_candidates(self.brain_path)
        proposals = call_companion.propose(candidates, mock_provider)

        # Confirm only t1
        confirmed = [dict(p, confirmed=True) for p in proposals if p["path"] == "tasks/projects/p1/t1.md"]
        res = call_companion.apply_confirmed(self.brain_path, confirmed, now=self.now)
        self.assertEqual(len(res["applied"]), 1)

        t1_text = t1.read_text()
        t2_text = t2.read_text()

        self.assertIn("call_suitable: true", t1_text)
        self.assertIn("estimate_minutes: 30", t1_text)
        self.assertNotIn("call_suitable", t2_text)
        self.assertNotIn("estimate_minutes", t2_text)

    def test_rejected_and_omitted_tickets_are_byte_identical(self):
        t1 = self._create_ticket("tasks/projects/p1/t1.md")
        t2 = self._create_ticket("tasks/projects/p1/t2.md")
        t3 = self._create_ticket("tasks/projects/p1/t3.md")

        bytes_t2_before = t2.read_bytes()
        bytes_t3_before = t3.read_bytes()

        candidates = call_companion.gather_candidates(self.brain_path)
        proposals = call_companion.propose(candidates, mock_provider)

        confirmed = [dict(p, confirmed=True) for p in proposals if p["path"] == "tasks/projects/p1/t1.md"]
        call_companion.apply_confirmed(self.brain_path, confirmed, now=self.now)

        self.assertEqual(t2.read_bytes(), bytes_t2_before)
        self.assertEqual(t3.read_bytes(), bytes_t3_before)

    def test_only_permitted_keys_change_and_formatting_preserved(self):
        ticket_file = self.brain_path / "tasks/projects/p1/custom.md"
        raw_content = (
            "---\n"
            "status: backlog\n"
            "type: task\n"
            "priority: high\n"
            "custom_key: custom_val\n"
            "---\n\n"
            "# Custom Ticket\n\n"
            "Body text.\n"
        )
        ticket_file.write_text(raw_content, encoding="utf-8")

        candidates = call_companion.gather_candidates(self.brain_path)
        proposals = call_companion.propose(candidates, mock_provider)

        confirmed = [dict(p, confirmed=True) for p in proposals]
        call_companion.apply_confirmed(self.brain_path, confirmed, now=self.now)

        text_after = ticket_file.read_text()
        fm_dict = call_companion.parse_frontmatter_dict(text_after)

        expected_keys = {"status", "type", "priority", "custom_key", "call_suitable", "estimate_minutes"}
        self.assertEqual(set(fm_dict.keys()), expected_keys)
        self.assertEqual(fm_dict["call_suitable"], "true")
        self.assertEqual(fm_dict["estimate_minutes"], "30")

        # Ensure prohibited keys were NOT injected
        self.assertNotIn("planning_lane", fm_dict)
        self.assertNotIn("planned_for", fm_dict)
        self.assertNotIn("critical", fm_dict)
        self.assertTrue(text_after.endswith("# Custom Ticket\n\nBody text.\n"))

    def test_action_log_entry_created(self):
        self._create_ticket("tasks/projects/p1/t1.md")
        candidates = call_companion.gather_candidates(self.brain_path)
        proposals = call_companion.propose(candidates, mock_provider)

        confirmed = [dict(p, confirmed=True) for p in proposals]
        call_companion.apply_confirmed(self.brain_path, confirmed, now=self.now)

        log_file = self.brain_path / "log" / "2026-08-04.md"
        self.assertTrue(log_file.exists())

        log_text = log_file.read_text()
        self.assertIn("### 14:00 — ticket-planning-update", log_text)
        self.assertIn("- **actor:** EA", log_text)
        self.assertIn("- **trigger:** Call Companion curation", log_text)
        self.assertIn("- **input link:** tasks/projects/p1/t1.md", log_text)
        self.assertIn("- **action type:** ticket-planning-update", log_text)

    def test_confirmation_gate_requires_explicit_marker(self):
        self._create_ticket("tasks/projects/p1/t1.md")
        candidates = call_companion.gather_candidates(self.brain_path)
        proposals = call_companion.propose(candidates, mock_provider)
        # Passing raw propose() output without confirmed: True must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            call_companion.apply_confirmed(self.brain_path, proposals, now=self.now)
        self.assertIn("tasks/projects/p1/t1.md", str(ctx.exception))

    def test_path_traversal_and_absolute_paths_rejected(self):
        self._create_ticket("tasks/projects/p1/t1.md")
        traversal_item = [{"path": "../outside.md", "call_suitable": True, "estimate_minutes": 30, "confirmed": True}]
        with self.assertRaises(ValueError) as ctx:
            call_companion.apply_confirmed(self.brain_path, traversal_item, now=self.now)
        self.assertIn("../outside.md", str(ctx.exception))

        abs_item = [{"path": "/etc/passwd", "call_suitable": True, "estimate_minutes": 30, "confirmed": True}]
        with self.assertRaises(ValueError) as ctx:
            call_companion.apply_confirmed(self.brain_path, abs_item, now=self.now)
        self.assertIn("/etc/passwd", str(ctx.exception))

    def test_non_candidate_path_rejected(self):
        self._create_ticket("tasks/projects/p1/t1.md")
        # File outside tasks directory or not a gathered candidate
        config_file = self.brain_path / "config" / "CLAUDE.md"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("config", encoding="utf-8")

        non_candidate = [{"path": "config/CLAUDE.md", "call_suitable": True, "estimate_minutes": 30, "confirmed": True}]
        with self.assertRaises(ValueError) as ctx:
            call_companion.apply_confirmed(self.brain_path, non_candidate, now=self.now)
        self.assertIn("config/CLAUDE.md", str(ctx.exception))

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            call_companion.gather_candidates(self.brain_path, limit=-1)

        with self.assertRaises(ValueError):
            call_companion.gather_candidates(self.brain_path, limit=0)

    def test_malformed_provider_values_rejected(self):
        self._create_ticket("tasks/projects/p1/t1.md")
        candidates = call_companion.gather_candidates(self.brain_path)

        def bad_cs_provider(cands):
            return [{"path": cands[0]["path"], "call_suitable": "maybe", "estimate_minutes": 30}]

        with self.assertRaises(ValueError):
            call_companion.propose(candidates, bad_cs_provider)

        def bad_est_provider(cands):
            return [{"path": cands[0]["path"], "call_suitable": True, "estimate_minutes": 0}]

        with self.assertRaises(ValueError):
            call_companion.propose(candidates, bad_est_provider)

        def float_est_provider(cands):
            return [{"path": cands[0]["path"], "call_suitable": True, "estimate_minutes": 30.9}]

        with self.assertRaises(ValueError):
            call_companion.propose(candidates, float_est_provider)

        def leading_zero_est_provider(cands):
            return [{"path": cands[0]["path"], "call_suitable": True, "estimate_minutes": "0030"}]

        with self.assertRaises(ValueError):
            call_companion.propose(candidates, leading_zero_est_provider)

        def negative_est_provider(cands):
            return [{"path": cands[0]["path"], "call_suitable": True, "estimate_minutes": -15}]

        with self.assertRaises(ValueError):
            call_companion.propose(candidates, negative_est_provider)

    def test_f4_estimate_minutes_strict_validation(self):
        """F4: reject any value for estimate_minutes that is not an exact positive integer."""
        invalid_values = [30.9, 1.4, 30.0, "0030", "30.9", "1.4", 0, -5, True, False, "abc", "", None, [30]]
        for val in invalid_values:
            with self.subTest(val=val):
                with self.assertRaises(ValueError):
                    call_companion.validate_estimate_minutes(val)

        valid_values = [(30, "30"), (1, "1"), ("30", "30"), ("1", "1")]
        for val, expected in valid_values:
            with self.subTest(val=val):
                self.assertEqual(call_companion.validate_estimate_minutes(val), expected)

    def test_f12_malformed_frontmatter_not_gathered(self):
        """F12: Malformed frontmatter files are skipped during gather_candidates."""
        tf = self.brain_path / "tasks" / "projects" / "p1" / "malformed.md"
        malformed_content = "---\nstatus: backlog\n---# Malformed\n"
        tf.write_text(malformed_content, encoding="utf-8")

        candidates = call_companion.gather_candidates(self.brain_path)
        self.assertEqual(candidates, [])

    def test_f15_apply_confirmed_atomic(self):
        """F15: If any proposal in confirmed fails validation, NO files are written (atomic)."""
        t1 = self._create_ticket("tasks/projects/p1/t1.md")
        t2 = self._create_ticket("tasks/projects/p1/t2.md")
        t1_bytes_before = t1.read_bytes()

        confirmed = [
            {"path": "tasks/projects/p1/t1.md", "call_suitable": True, "estimate_minutes": 30, "confirmed": True},
            {"path": "tasks/projects/p1/t2.md", "call_suitable": True, "estimate_minutes": -5, "confirmed": True},  # Hostile/invalid
        ]

        with self.assertRaises(ValueError):
            call_companion.apply_confirmed(self.brain_path, confirmed, now=self.now)

        # Assert t1 was NOT modified
        self.assertEqual(t1.read_bytes(), t1_bytes_before)
        log_file = self.brain_path / "log" / "2026-08-04.md"
        self.assertFalse(log_file.exists())

    def test_f16_propose_provider_path_and_count_validation(self):
        """F16: propose checks provider-returned paths correspond to candidates and count does not exceed candidates."""
        t1 = self._create_ticket("tasks/projects/p1/t1.md")
        candidates = call_companion.gather_candidates(self.brain_path)

        def invalid_path_provider(cands):
            return [{"path": "tasks/projects/p1/nonexistent.md", "call_suitable": True, "estimate_minutes": 30}]

        with self.assertRaises(ValueError):
            call_companion.propose(candidates, invalid_path_provider)

        def duplicate_path_provider(cands):
            return [
                {"path": cands[0]["path"], "call_suitable": True, "estimate_minutes": 30},
                {"path": cands[0]["path"], "call_suitable": False, "estimate_minutes": 15},
            ]

        with self.assertRaises(ValueError):
            call_companion.propose(candidates, duplicate_path_provider)

    def test_provider_called_once_no_arity_sniffing(self):
        self._create_ticket("tasks/projects/p1/t1.md")
        self._create_ticket("tasks/projects/p1/t2.md")
        candidates = call_companion.gather_candidates(self.brain_path)

        call_count = 0
        def counting_provider(cands):
            nonlocal call_count
            call_count += 1
            return [
                {"path": c["path"], "call_suitable": True, "estimate_minutes": 30}
                for c in cands
            ]

        call_companion.propose(candidates, counting_provider)
        self.assertEqual(call_count, 1)

        def non_list_provider(cands):
            return {"path": cands[0]["path"], "call_suitable": True, "estimate_minutes": 30}

        with self.assertRaises(TypeError):
            call_companion.propose(candidates, non_list_provider)

    def test_crlf_line_endings_preserved(self):
        tf = self.brain_path / "tasks" / "projects" / "p1" / "crlf.md"
        crlf_content = "---\r\nstatus: backlog\r\ntype: task\r\n---\r\n\r\n# CRLF Ticket\r\n\r\nBody text.\r\n"
        tf.write_bytes(crlf_content.encode("utf-8"))

        candidates = call_companion.gather_candidates(self.brain_path)
        proposals = call_companion.propose(candidates, mock_provider)
        confirmed = [dict(p, confirmed=True) for p in proposals if p["path"] == "tasks/projects/p1/crlf.md"]
        call_companion.apply_confirmed(self.brain_path, confirmed, now=self.now)

        raw_bytes = tf.read_bytes()
        self.assertIn(b"\r\n", raw_bytes)
        self.assertEqual(raw_bytes.count(b"\r\n"), raw_bytes.count(b"\n"))

    def test_tasks_areas_candidate_gathered_and_updated(self):
        tf = self._create_ticket("tasks/areas/a1/area-ticket.md")
        candidates = call_companion.gather_candidates(self.brain_path)
        paths = [c["path"] for c in candidates]
        self.assertIn("tasks/areas/a1/area-ticket.md", paths)

        proposals = call_companion.propose(candidates, mock_provider)
        confirmed = [dict(p, confirmed=True) for p in proposals if p["path"] == "tasks/areas/a1/area-ticket.md"]
        call_companion.apply_confirmed(self.brain_path, confirmed, now=self.now)

        text_after = tf.read_text()
        self.assertIn("call_suitable: true", text_after)

    def test_list_valued_frontmatter_preserved(self):
        tf = self.brain_path / "tasks" / "projects" / "p1" / "tags.md"
        content = (
            "---\n"
            "status: backlog\n"
            "type: task\n"
            "tags:\n"
            "  - urgent\n"
            "  - review\n"
            "---\n\n"
            "# Tags Ticket\n"
        )
        tf.write_text(content, encoding="utf-8")

        candidates = call_companion.gather_candidates(self.brain_path)
        proposals = call_companion.propose(candidates, mock_provider)
        confirmed = [dict(p, confirmed=True) for p in proposals if p["path"] == "tasks/projects/p1/tags.md"]
        call_companion.apply_confirmed(self.brain_path, confirmed, now=self.now)

        text_after = tf.read_text()
        self.assertIn("tags:\n  - urgent\n  - review\n", text_after)
        self.assertIn("call_suitable: true", text_after)

    def test_path_with_newline_rejected(self):
        bad_item = [{"path": "tasks/projects/p1/t1.md\n### Injection", "call_suitable": True, "estimate_minutes": 30, "confirmed": True}]
        with self.assertRaises(ValueError) as ctx:
            call_companion.apply_confirmed(self.brain_path, bad_item, now=self.now)
        self.assertIn("t1.md", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
