"""Tests for scripts/schema_enforce.py.

Every path the tool touches is injectable (`--brain`, `--code-root`,
`--files-root`, `--log-file`), so these tests run entirely inside `tmp_path`
git repos and never see the real Vault, the real `Code/` tree, or the real
`~/Library/Logs/`.
"""

import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import schema_enforce as se  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def _git_init(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t" + "@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)


def _git_commit_all(repo: Path, message="fixture"):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", message],
                   cwd=repo, check=True)


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


CONFORMING_TICKET = """---
status: backlog
type: task
priority: medium
component: v2-shippable-core
parent:
assignee:
github:
goal:
created: 2026-07-25
resolved:
---

# A conforming ticket
"""

# What the Base Board plugin actually creates: a status, a kanban_order, and
# nothing else from the ADR-0015 set.
BASE_BOARD_STUB = """---
status: backlog
kanban_order: V3
---

# Stub made by the board
"""


@pytest.fixture
def brain(tmp_path):
    """A clean, committed tmp Brain with one conforming ticket."""
    root = tmp_path / "Vault"
    _git_init(root)
    for slug in ("goals-os", "example-project"):
        (root / "projects" / slug).mkdir(parents=True)
        _write(root / "projects" / slug / f"{slug}.md", f"# {slug}\n")
    (root / "areas" / "work").mkdir(parents=True)
    _write(root / "areas" / "work" / "work.md", "# work\n")
    _write(root / "tasks" / "projects" / "goals-os" / "a-conforming-ticket.md",
           CONFORMING_TICKET)
    _git_commit_all(root)
    return root


@pytest.fixture
def roots(tmp_path):
    """Empty `Code/` and `Files/` roots, so a test opts into what it needs."""
    code = tmp_path / "Code"
    files = tmp_path / "Files"
    (code / "projects").mkdir(parents=True)
    (files / "projects").mkdir(parents=True)
    (files / "areas").mkdir(parents=True)
    return code, files


def _run(brain, roots, tmp_path, apply=False, now=None):
    code, files = roots
    return se.run(brain, code, files, apply=apply,
                  log_file=tmp_path / "logs" / "goals-os-schema-enforce.log",
                  now=now or dt.datetime(2026, 7, 26, 3, 30))


def _kinds(findings, check=None):
    return sorted(f.kind for f in findings if check is None or f.check == check)


# --------------------------------------------------------------------------
# (a) Ticket frontmatter schema
# --------------------------------------------------------------------------

def test_conforming_brain_is_silent(brain, roots, tmp_path):
    assert _run(brain, roots, tmp_path)["findings"] == []


def test_base_board_stub_ticket_gets_its_full_frontmatter(brain, roots, tmp_path):
    ticket = brain / "tasks" / "projects" / "goals-os" / "stub-made-by-the-board.md"
    _write(ticket, BASE_BOARD_STUB)
    _git_commit_all(brain)

    findings = _run(brain, roots, tmp_path)["findings"]
    assert "missing-keys" in _kinds(findings, "a")
    assert ticket.read_text() == BASE_BOARD_STUB, "report mode must not write"

    result = _run(brain, roots, tmp_path, apply=True)
    assert result["applied"]
    values = se.parse_frontmatter(ticket.read_text())
    assert all(key in values for key in se.REQUIRED_KEYS)
    assert values["status"] == "backlog"
    assert values["type"] == "task"


def test_kanban_order_is_never_touched(brain, roots, tmp_path):
    ticket = brain / "tasks" / "projects" / "goals-os" / "stub-made-by-the-board.md"
    _write(ticket, BASE_BOARD_STUB)
    _git_commit_all(brain)

    _run(brain, roots, tmp_path, apply=True)
    assert "kanban_order: V3" in ticket.read_text()
    assert se.parse_frontmatter(ticket.read_text())["kanban_order"] == "V3"


def test_out_of_vocabulary_values_are_normalised(brain, roots, tmp_path):
    ticket = brain / "tasks" / "projects" / "goals-os" / "drifted.md"
    _write(ticket, CONFORMING_TICKET
           .replace("status: backlog", "status: In Progress")
           .replace("type: task", "type: Bug")
           .replace("created: 2026-07-25", "created: 25/07/2026"))
    _git_commit_all(brain)

    findings = _run(brain, roots, tmp_path)["findings"]
    assert _kinds(findings, "a") == ["invalid-date-created", "invalid-status", "invalid-type"]

    _run(brain, roots, tmp_path, apply=True)
    values = se.parse_frontmatter(ticket.read_text())
    assert values["status"] == "in-progress"
    assert values["type"] == "bug"
    assert values["created"] == "2026-07-25"


def test_blank_status_defaults_and_unmappable_value_is_reported(brain, roots, tmp_path):
    _write(brain / "tasks" / "projects" / "goals-os" / "blank.md",
           CONFORMING_TICKET.replace("status: backlog", "status:"))
    _write(brain / "tasks" / "projects" / "goals-os" / "nonsense.md",
           CONFORMING_TICKET.replace("status: backlog", "status: banana"))
    _git_commit_all(brain)

    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "a"]
    by_kind = {f.kind: f for f in findings}
    assert by_kind["blank-status"].fixable
    assert not by_kind["invalid-status"].fixable
    assert by_kind["invalid-status"].blocked_reason


def test_blank_resolved_date_is_not_a_finding(brain, roots, tmp_path):
    assert not [f for f in _run(brain, roots, tmp_path)["findings"]
                if f.kind.startswith("invalid-date")]


# --------------------------------------------------------------------------
# (b) Folder/naming traceability
# --------------------------------------------------------------------------

def test_mismatched_case_code_folder_is_flagged_and_reconciled(brain, roots, tmp_path):
    code, _files = roots
    _git_init(code)
    (code / "projects" / "Goals OS").mkdir(parents=True)
    _write(code / "projects" / "Goals OS" / "README.md", "# engine\n")
    _git_commit_all(code)

    # An inbound wikilink that names the drifted folder, so the rename's
    # link rewrite is observable.
    _write(brain / "projects" / "goals-os" / "goals-os.md",
           "# goals-os\n\nCode lives at [[Goals OS|the engine]].\n")
    _git_commit_all(brain)

    findings = _run(brain, roots, tmp_path)["findings"]
    mismatch = [f for f in findings if f.kind == "naming-mismatch"]
    assert [f.path for f in mismatch] == ["Code/projects/Goals OS"]
    assert mismatch[0].fixable
    assert (code / "projects" / "Goals OS").is_dir(), "report mode must not rename"

    result = _run(brain, roots, tmp_path, apply=True)
    assert (code / "projects" / "goals-os").is_dir()
    assert not (code / "projects" / "Goals OS").exists()
    assert "[[goals-os|the engine]]" in (brain / "projects" / "goals-os" / "goals-os.md").read_text()
    assert any("Code/projects/Goals OS" in c for c in result["changes"])


def test_rename_outside_a_git_repo_is_reported_not_applied(brain, roots, tmp_path):
    code, _files = roots  # deliberately NOT a git repo
    (code / "projects" / "Goals OS").mkdir(parents=True)

    result = _run(brain, roots, tmp_path, apply=True)
    assert (code / "projects" / "Goals OS").is_dir(), "must refuse an irreversible rename"
    mismatch = next(f for f in result["findings"] if f.kind == "naming-mismatch")
    assert not mismatch.fixable
    assert "not inside a git repository" in mismatch.blocked_reason


def test_orphan_and_wrong_kind_folders_are_flagged(brain, roots, tmp_path):
    code, files = roots
    (code / "projects" / "nonesuch").mkdir(parents=True)
    (files / "projects" / "work").mkdir(parents=True)  # `work` is an Area

    findings = _run(brain, roots, tmp_path)["findings"]
    by_path = {f.path: f for f in findings if f.check == "b"}
    assert by_path["Code/projects/nonesuch"].kind == "orphan"
    assert by_path["Files/projects/work"].kind == "wrong-kind"


def test_files_root_is_traceability_checked_but_never_case_flagged(brain, roots, tmp_path):
    _code, files = roots
    (files / "areas" / "Work").mkdir(parents=True)

    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "b"]
    assert findings == [], "Files/ mirrors the Areas in Title Case by convention"


def test_a_drifted_project_folder_colliding_with_its_slug_is_not_fixable(brain, roots, tmp_path):
    (brain / "projects" / "Goals OS").mkdir(parents=True)
    _git_commit_all(brain)

    mismatch = next(f for f in _run(brain, roots, tmp_path)["findings"]
                    if f.kind == "naming-mismatch")
    assert not mismatch.fixable
    assert "already exists" in mismatch.blocked_reason


# --------------------------------------------------------------------------
# (c) Cross-note integrity
# --------------------------------------------------------------------------

def test_dangling_wikilink_is_reported(brain, roots, tmp_path):
    _write(brain / "projects" / "goals-os" / "goals-os.md",
           "# goals-os\n\nSee [[No Such Note]].\n")
    _git_commit_all(brain)

    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "c"]
    assert len(findings) == 1
    assert findings[0].kind == "broken-wikilink"
    assert "[[No Such Note]]" in findings[0].detail
    assert not findings[0].fixable


def test_repairable_wikilink_is_repointed(brain, roots, tmp_path):
    _write(brain / "wiki" / "a-conforming-ticket.md", "# ok\n")
    _write(brain / "projects" / "goals-os" / "goals-os.md",
           "# goals-os\n\nSee [[A Conforming Ticket#Why|the ticket]] and "
           "[[A Conforming Ticket]].\n")
    _git_commit_all(brain)

    _run(brain, roots, tmp_path, apply=True)
    text = (brain / "projects" / "goals-os" / "goals-os.md").read_text()
    assert "[[a-conforming-ticket#Why|the ticket]]" in text
    assert "[[a-conforming-ticket]]" in text


def test_link_by_relative_path_with_extension_resolves(brain, roots, tmp_path):
    _write(brain / "Dashboard.md",
           "# Dashboard\n\n[[tasks/projects/goals-os/a-conforming-ticket.md]]\n"
           "[[projects/goals-os/goals-os]]\n")
    _git_commit_all(brain)
    assert [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "c"] == []


def test_wikilinks_inside_fenced_code_blocks_are_ignored(brain, roots, tmp_path):
    _write(brain / "projects" / "goals-os" / "goals-os.md",
           "# goals-os\n\n```\n[[Not A Real Link]]\n```\n")
    _git_commit_all(brain)
    assert [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "c"] == []


def test_ticket_under_a_nonexistent_project_is_flagged(brain, roots, tmp_path):
    _write(brain / "tasks" / "projects" / "ghost-project" / "orphaned.md",
           CONFORMING_TICKET)
    _git_commit_all(brain)

    findings = _run(brain, roots, tmp_path)["findings"]
    orphans = [f for f in findings if f.kind == "ticket-orphan-parent"]
    assert [f.path for f in orphans] == ["tasks/projects/ghost-project/orphaned.md"]
    assert not orphans[0].fixable


# --------------------------------------------------------------------------
# Safety guard, change log, Action Log
# --------------------------------------------------------------------------

def test_dirty_tree_run_aborts(brain, roots, tmp_path):
    _write(brain / "tasks" / "projects" / "goals-os" / "stub.md", BASE_BOARD_STUB)
    # deliberately not committed

    with pytest.raises(RuntimeError, match="dirty"):
        _run(brain, roots, tmp_path, apply=True)

    assert "priority" not in se.parse_frontmatter(
        (brain / "tasks" / "projects" / "goals-os" / "stub.md").read_text())


def test_non_git_brain_refuses_to_apply(tmp_path, roots):
    plain = tmp_path / "PlainBrain"
    (plain / "projects" / "goals-os").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="not a git repository"):
        _run(plain, roots, tmp_path, apply=True)


def test_apply_lays_down_a_revertible_pre_fix_commit(brain, roots, tmp_path):
    before = subprocess.run(["git", "-C", str(brain), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    _write(brain / "tasks" / "projects" / "goals-os" / "stub.md", BASE_BOARD_STUB)
    _git_commit_all(brain)

    result = _run(brain, roots, tmp_path, apply=True)
    assert result["marker"]

    subprocess.run(["git", "-C", str(brain), "reset", "--hard", result["marker"]],
                   check=True, capture_output=True)
    assert (brain / "tasks" / "projects" / "goals-os" / "stub.md").read_text() == BASE_BOARD_STUB
    assert before != result["marker"]


def test_report_mode_is_the_default_and_writes_nothing(brain, roots, tmp_path):
    _write(brain / "tasks" / "projects" / "goals-os" / "stub.md", BASE_BOARD_STUB)
    _git_commit_all(brain)

    result = _run(brain, roots, tmp_path)
    assert result["applied"] is False
    assert result["changes"] == []
    assert not (tmp_path / "logs").exists()
    assert not (brain / "log").exists()
    status = subprocess.run(["git", "-C", str(brain), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert status.strip() == ""


def test_apply_writes_change_log_and_action_log(brain, roots, tmp_path):
    _write(brain / "tasks" / "projects" / "goals-os" / "stub.md", BASE_BOARD_STUB)
    _git_commit_all(brain)

    _run(brain, roots, tmp_path, apply=True)

    change_log = (tmp_path / "logs" / "goals-os-schema-enforce.log").read_text()
    assert "schema enforce (apply)" in change_log
    assert "tasks/projects/goals-os/stub.md" in change_log

    action_log = (brain / "log" / "2026-07-26.md").read_text()
    assert "**action type:** ticket-normalize" in action_log
    assert "**actor:** EA" in action_log


def test_apply_is_idempotent(brain, roots, tmp_path):
    _write(brain / "tasks" / "projects" / "goals-os" / "stub.md", BASE_BOARD_STUB)
    _git_commit_all(brain)

    _run(brain, roots, tmp_path, apply=True)
    _git_commit_all(brain)
    second = _run(brain, roots, tmp_path)
    assert [f for f in second["findings"] if f.check == "a"] == []


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_cli_defaults_to_report_mode(brain, roots, tmp_path, capsys):
    code, files = roots
    _write(brain / "tasks" / "projects" / "goals-os" / "stub.md", BASE_BOARD_STUB)

    se.main(["--brain", str(brain), "--code-root", str(code),
             "--files-root", str(files), "--log-file", str(tmp_path / "x.log")])
    out = capsys.readouterr().out
    assert "Report mode (default)" in out
    assert not (tmp_path / "x.log").exists()


def test_cli_rejects_apply_with_dry_run(brain, roots, tmp_path):
    with pytest.raises(SystemExit):
        se.main(["--brain", str(brain), "--apply", "--dry-run"])


# --------------------------------------------------------------------------
# Regressions — the seven defects found in review of the first pass
# --------------------------------------------------------------------------

def test_rename_never_repoints_an_already_valid_bare_link(brain, roots, tmp_path):
    """(1) A directory name and a wikilink target are different namespaces."""
    code, _files = roots
    _git_init(code)
    (code / "projects" / "Goals OS").mkdir(parents=True)
    _git_commit_all(code)

    _write(brain / "wiki" / "Goals OS.md", "# Goals OS\n\nThe real note.\n")
    _write(brain / "Dashboard.md", "# Dashboard\n\nSee [[Goals OS]].\n")
    _git_commit_all(brain)

    _run(brain, roots, tmp_path, apply=True)

    assert (code / "projects" / "goals-os").is_dir()
    assert "[[Goals OS]]" in (brain / "Dashboard.md").read_text(), \
        "a link that already resolves must survive an unrelated folder rename"
    assert (brain / "wiki" / "Goals OS.md").is_file()
    # And the corruption must not be invisible: a re-scan is still silent.
    _git_commit_all(brain)
    assert [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "c"] == []


def test_rename_repoints_the_path_form_links_it_actually_breaks(brain, roots, tmp_path):
    """(1) Path-form links are the ones a directory rename really breaks."""
    _write(brain / "tasks" / "projects" / "Example Project" / "t.md", CONFORMING_TICKET)
    _write(brain / "Dashboard.md",
           "# Dashboard\n\n[[tasks/projects/Example Project/t|the ticket]]\n")
    _git_commit_all(brain)

    _run(brain, roots, tmp_path, apply=True)
    assert "[[tasks/projects/example-project/t|the ticket]]" in (brain / "Dashboard.md").read_text()


def test_fix_pass_honours_fences_inline_code_and_frontmatter(brain, roots, tmp_path):
    """(2) Repair must touch exactly what detection looked at."""
    note = brain / "projects" / "goals-os" / "goals-os.md"
    _write(note,
           "---\n"
           "link: \"[[A Conforming Ticket]]\"\n"
           "---\n"
           "# goals-os\n\n"
           "Prose [[A Conforming Ticket]] here.\n"
           "Inline `[[A Conforming Ticket]]` code.\n"
           "```\n[[A Conforming Ticket]]\n```\n")
    _git_commit_all(brain)

    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "c"]
    assert len(findings) == 1, "one live prose occurrence, nothing else"

    _run(brain, roots, tmp_path, apply=True)
    text = note.read_text()
    assert "Prose [[a-conforming-ticket]] here." in text
    assert "link: \"[[A Conforming Ticket]]\"" in text
    assert "Inline `[[A Conforming Ticket]]` code." in text
    assert "```\n[[A Conforming Ticket]]\n```" in text


def test_archive_is_immune_to_every_write(brain, roots, tmp_path):
    """(2) `archive/` is the immutable record of what was filed."""
    archived = brain / "archive" / "inbox" / "email" / "2026-07-25-a-capture.md"
    original = "# capture\n\nMentions [[A Conforming Ticket]].\n"
    _write(archived, original)
    _git_commit_all(brain)

    result = _run(brain, roots, tmp_path, apply=True)
    finding = next(f for f in result["findings"] if f.check == "c")
    assert not finding.fixable
    assert "immutable" in finding.blocked_reason
    assert archived.read_text() == original


def test_two_in_brain_renames_both_land_in_one_run(brain, roots, tmp_path):
    """(3) Rename #1 dirties the tree; it must not veto rename #2."""
    _write(brain / "tasks" / "projects" / "Example Project" / "t.md", CONFORMING_TICKET)
    _write(brain / "tasks" / "areas" / "Work Area" / "t.md", CONFORMING_TICKET)
    (brain / "areas" / "work-area").mkdir(parents=True)
    _write(brain / "areas" / "work-area" / "work-area.md", "# work-area\n")
    _git_commit_all(brain)

    _run(brain, roots, tmp_path, apply=True)
    assert (brain / "tasks" / "projects" / "example-project").is_dir()
    assert (brain / "tasks" / "areas" / "work-area").is_dir()
    assert not (brain / "tasks" / "projects" / "Example Project").exists()


def test_pure_case_only_rename_is_fixable(brain, roots, tmp_path):
    """(4) `Path.exists()` is not a collision test on a case-insensitive FS."""
    _write(brain / "tasks" / "areas" / "Work" / "t.md", CONFORMING_TICKET)
    _git_commit_all(brain)

    mismatch = next(f for f in _run(brain, roots, tmp_path)["findings"]
                    if f.kind == "naming-mismatch")
    assert mismatch.fixable, mismatch.blocked_reason

    _run(brain, roots, tmp_path, apply=True)
    names = [p.name for p in (brain / "tasks" / "areas").iterdir()]
    assert names == ["work"]


def test_findings_are_rederived_after_a_rename(brain, roots, tmp_path):
    """(5) A rename invalidates the paths every (a)/(c) finding carries."""
    stub = brain / "tasks" / "projects" / "Example Project" / "stub.md"
    _write(stub, BASE_BOARD_STUB)
    _git_commit_all(brain)

    before = _run(brain, roots, tmp_path)["findings"]
    assert "ticket-orphan-parent" in _kinds(before, "c")

    result = _run(brain, roots, tmp_path, apply=True)
    moved = brain / "tasks" / "projects" / "example-project" / "stub.md"
    assert moved.is_file() and not stub.exists()
    values = se.parse_frontmatter(moved.read_text())
    assert all(key in values for key in se.REQUIRED_KEYS), \
        "the ticket under the renamed folder must still be repaired"
    assert not [f for f in result["findings"] if f.blocked_reason
                and f.blocked_reason.startswith("failed:")]
    assert "ticket-orphan-parent" not in _kinds(result["findings"], "c"), \
        "no false positive for a path this run just fixed"


def test_two_consecutive_apply_runs_succeed(brain, roots, tmp_path):
    """(6) The tool must commit its own output, not choke on it."""
    _write(brain / "tasks" / "projects" / "goals-os" / "stub.md", BASE_BOARD_STUB)
    _git_commit_all(brain)

    first = _run(brain, roots, tmp_path, apply=True)
    assert first["applied"]
    status = subprocess.run(["git", "-C", str(brain), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert status.strip() == "", "run 1 must leave the tree clean"

    second = _run(brain, roots, tmp_path, apply=True)  # must not raise
    assert second["changes"] == []


def test_apply_with_nothing_fixable_writes_nothing(brain, roots, tmp_path):
    """(6) A nightly `--apply` on a conforming Brain is a true no-op."""
    head = subprocess.run(["git", "-C", str(brain), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    result = _run(brain, roots, tmp_path, apply=True)
    assert result["marker"] is None
    assert not (tmp_path / "logs").exists()
    assert not (brain / "log").exists()
    after = subprocess.run(["git", "-C", str(brain), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout.strip()
    assert after == head, "no empty marker commit when there is nothing to fix"


BLOCK_SEQUENCE_TICKET = CONFORMING_TICKET.replace(
    "status: backlog", "status:\n  - backlog")


def test_block_sequence_frontmatter_value_is_never_rewritten(brain, roots, tmp_path):
    """(7) A line-based rewrite of a YAML block value produces invalid YAML."""
    ticket = brain / "tasks" / "projects" / "goals-os" / "blocky.md"
    _write(ticket, BLOCK_SEQUENCE_TICKET)
    _git_commit_all(brain)

    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "a"]
    assert _kinds(findings) == ["multiline-status"]
    assert not findings[0].fixable

    _run(brain, roots, tmp_path, apply=True)
    assert ticket.read_text() == BLOCK_SEQUENCE_TICKET


def test_set_frontmatter_value_refuses_a_block_value():
    """(7) The primitive itself refuses, whatever the caller believes."""
    assert se.set_frontmatter_value(BLOCK_SEQUENCE_TICKET, "status", "backlog") \
        == BLOCK_SEQUENCE_TICKET
    assert se.block_keys(BLOCK_SEQUENCE_TICKET) == {"status"}


def test_slug_map_folds_a_drifted_directory_onto_its_canonical_slug(brain):
    (brain / "projects" / "Goals OS").mkdir()
    slug_map = se.build_slug_map(brain)
    assert slug_map["goals-os"] == "project"
    assert slug_map["work"] == "area"
    assert "Goals OS" not in slug_map


# --------------------------------------------------------------------------
# (d) CLAUDE.md caveat expiry
# --------------------------------------------------------------------------

DONE_TICKET = """---
status: done
type: task
priority:
component: v2-shippable-core
parent:
assignee:
github:
goal:
created: 2026-07-20
resolved: 2026-07-25
---

# A finished ticket
"""


def _caveat_brain(brain, body: str, ticket: str = None):
    """`brain` plus a project CLAUDE.md carrying `body`, and optionally a
    second ticket written verbatim from `ticket`."""
    _write(brain / "projects" / "goals-os" / "CLAUDE.md", body)
    if ticket is not None:
        _write(brain / "tasks" / "projects" / "goals-os" / "a-finished-ticket.md",
               ticket)
    return brain


def test_a_brain_with_no_caveats_raises_nothing(brain, roots, tmp_path):
    _caveat_brain(brain, "# Project context\n\nNothing conditional here.\n")
    assert _kinds(_run(brain, roots, tmp_path)["findings"], "d") == []


def test_a_caveat_naming_an_open_ticket_is_silent(brain, roots, tmp_path):
    _caveat_brain(
        brain,
        "**Caveat** — don't write that value until [[a-conforming-ticket]] lands.\n",
    )
    assert _kinds(_run(brain, roots, tmp_path)["findings"], "d") == []


def test_a_caveat_whose_ticket_is_done_is_flagged_stale(brain, roots, tmp_path):
    _caveat_brain(
        brain,
        "**Caveat** — don't write that value until [[a-finished-ticket]] lands.\n",
        ticket=DONE_TICKET,
    )
    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "d"]
    assert [f.kind for f in findings] == ["caveat-expired"]
    assert "a-finished-ticket" in findings[0].detail


def test_an_expired_caveat_is_never_auto_repaired(brain, roots, tmp_path):
    """Deleting a caveat means rewriting prose around it — always a human's
    call, so `--apply` must leave the file byte-identical."""
    body = "**Caveat** — don't write that value until [[a-finished-ticket]] lands.\n"
    _caveat_brain(brain, body, ticket=DONE_TICKET)
    _git_commit_all(brain, "add caveat")
    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "d"]
    assert not findings[0].fixable
    _run(brain, roots, tmp_path, apply=True)
    assert (brain / "projects" / "goals-os" / "CLAUDE.md").read_text() == body


def test_a_caveat_naming_no_ticket_is_flagged_unlinked(brain, roots, tmp_path):
    _caveat_brain(brain, "**Caveat** — don't write that value yet.\n")
    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "d"]
    assert [f.kind for f in findings] == ["caveat-unlinked"]


def test_a_caveat_naming_a_non_ticket_note_is_flagged(brain, roots, tmp_path):
    """A caveat must clear on a *ticket*'s status. A link to a Project note
    resolves fine as a wikilink, so check (c) stays quiet — but it can never
    go `done`, so the caveat would never expire."""
    _caveat_brain(brain, "**Caveat** — blocked until [[goals-os]] is sorted.\n")
    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "d"]
    assert [f.kind for f in findings] == ["caveat-unresolved-ticket"]


def test_caveat_scanning_ignores_non_claude_md_files(brain, roots, tmp_path):
    """The convention is scoped to always-loaded context. The same words in an
    ordinary note are prose, not a standing instruction to an agent."""
    _write(brain / "projects" / "goals-os" / "notes.md",
           "**Caveat** — don't write that value yet.\n")
    assert _kinds(_run(brain, roots, tmp_path)["findings"], "d") == []


def test_a_caveat_inside_a_fenced_block_is_ignored(brain, roots, tmp_path):
    """Documenting the convention must not trip it."""
    _caveat_brain(
        brain,
        "How to write one:\n\n```\n**Caveat** — don't do X until [[some-ticket]] lands.\n```\n",
    )
    assert _kinds(_run(brain, roots, tmp_path)["findings"], "d") == []


def test_several_caveats_are_reported_independently(brain, roots, tmp_path):
    _caveat_brain(
        brain,
        "**Caveat** — wait for [[a-finished-ticket]].\n\n"
        "**Caveat** — wait for [[a-conforming-ticket]].\n\n"
        "**Caveat** — wait for something.\n",
        ticket=DONE_TICKET,
    )
    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "d"]
    assert sorted(f.kind for f in findings) == ["caveat-expired", "caveat-unlinked"]
    assert all(":" in f.path for f in findings)


def test_caveats_are_found_in_every_claude_md_in_the_brain(brain, roots, tmp_path):
    _write(brain / "CLAUDE.md", "**Caveat** — wait for [[a-finished-ticket]].\n")
    _write(brain / "wiki" / "CLAUDE.md",
           "**Caveat** — wait for [[a-finished-ticket]].\n")
    _write(brain / "tasks" / "projects" / "goals-os" / "a-finished-ticket.md",
           DONE_TICKET)
    findings = [f for f in _run(brain, roots, tmp_path)["findings"] if f.check == "d"]
    assert len(findings) == 2
    assert sorted(f.path.split(":")[0] for f in findings) == ["CLAUDE.md", "wiki/CLAUDE.md"]


def test_the_report_names_the_caveat_check(brain, roots, tmp_path):
    _caveat_brain(brain, "**Caveat** — don't write that value yet.\n")
    report = se.format_report(_run(brain, roots, tmp_path)["findings"], False)
    assert "(d) CLAUDE.md caveat expiry" in report
