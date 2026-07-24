from pathlib import Path
import re

REPO_ROOT = Path(__file__).parent.parent
CODER_CHARTER_PATH = REPO_ROOT / "protocols" / "charters" / "capability" / "coder.md"


def parse_frontmatter_and_body(file_path: Path):
    content = file_path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    assert match is not None, "File does not contain YAML frontmatter delimited by ---"
    frontmatter_str, body_str = match.groups()
    fm = {}
    for line in frontmatter_str.strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()
    return fm, body_str


def test_coder_charter_frontmatter_and_headings():
    assert CODER_CHARTER_PATH.exists()
    fm, body = parse_frontmatter_and_body(CODER_CHARTER_PATH)

    assert fm.get("type") == "charter"
    assert fm.get("charter-kind") == "capability"
    assert fm.get("scope") == "generic"
    assert fm.get("agent") == "Coder"
    assert fm.get("directs") == "none"
    assert fm.get("commissioned-by") == "both"
    assert fm.get("tool-scope") == "see body"
    assert fm.get("memory") == "none"
    assert "owner" not in fm, "Absent owner field defaults to engine per charter schema"

    assert "# Coder" in body
    assert "## Role & purpose" in body
    assert "## Boundaries" in body
    assert "## Session behaviour" in body
    assert "## Tool scope" in body


def test_coder_charter_code_root_scope_widening():
    _, body = parse_frontmatter_and_body(CODER_CHARTER_PATH)
    body_lower = body.lower()

    # Scope widens to repos declared under code_root (ADR-0022)
    assert "code_root" in body_lower, "Charter must reference code_root (ADR-0022)"
    assert "adr-0022" in body_lower, "Charter must reference ADR-0022 for code_root scope"


def test_coder_charter_explicit_per_commission_brain_write_exception():
    _, body = parse_frontmatter_and_body(CODER_CHARTER_PATH)
    body_lower = body.lower()

    # Ordinary commission must never touch areas/ or config/
    assert "areas/" in body and "config/" in body, "Charter must explicitly name areas/ and config/"
    assert "per-commission" in body_lower or "scoped exception" in body_lower, (
        "Brain-write exception must be explicit and per-commission"
    )
    # Standing exception must be gone
    assert "unless explicitly tasked to do so by a system agent upgrading the engine" not in body_lower, (
        "Standing Brain-edit exception must be replaced with per-commission exception"
    )


def test_coder_charter_commits_doesnt_push_sharpening():
    _, body = parse_frontmatter_and_body(CODER_CHARTER_PATH)
    body_lower = body.lower()

    # Sharpened boundary per ADR-0023: commits, doesn't push
    assert "commits, doesn't push" in body_lower or ("commit" in body_lower and "push" in body_lower), (
        "Boundary must sharpen into 'commits, doesn't push' (ADR-0023)"
    )
    assert "adr-0023" in body_lower, "Charter must reference ADR-0023"


def test_coder_charter_authoritative_contract_and_escalation():
    _, body = parse_frontmatter_and_body(CODER_CHARTER_PATH)
    body_lower = body.lower()

    # Ticket contract is authoritative; conflict with real repo state escalates
    assert "authoritative" in body_lower, "Ticket contract must be declared authoritative"
    assert "escalat" in body_lower or "blocked" in body_lower, (
        "Conflict with real repo state must be escalated rather than silently resolved"
    )
