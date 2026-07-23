from pathlib import Path
import re

REPO_ROOT = Path(__file__).parent.parent
REVIEWER_CHARTER_PATH = REPO_ROOT / "protocols" / "charters" / "capability" / "reviewer.md"


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


def test_reviewer_charter_frontmatter_and_headings():
    assert REVIEWER_CHARTER_PATH.exists()
    fm, body = parse_frontmatter_and_body(REVIEWER_CHARTER_PATH)

    assert fm.get("type") == "charter"
    assert fm.get("charter-kind") == "capability"
    assert fm.get("scope") == "generic"
    assert fm.get("agent") == "Reviewer"
    assert fm.get("directs") == "none"
    assert fm.get("commissioned-by") == "both"
    assert fm.get("tool-scope") == "see body"
    assert fm.get("memory") == "none"

    assert "# Reviewer" in body
    assert "## Role & purpose" in body
    assert "## Boundaries" in body
    assert "## Session behaviour" in body
    assert "## Tool scope" in body


def test_reviewer_charter_no_execution_capabilities_removed():
    _, body = parse_frontmatter_and_body(REVIEWER_CHARTER_PATH)
    assert "No execution capabilities" not in body, (
        "'No execution capabilities' must be removed from Reviewer charter"
    )


def test_reviewer_charter_execution_rights_and_boundaries():
    _, body = parse_frontmatter_and_body(REVIEWER_CHARTER_PATH)

    # May run target repo's declared test, lint, build commands inside worktree
    assert "declared" in body.lower()
    assert "test" in body.lower()
    assert "lint" in body.lower()
    assert "build" in body.lower()
    assert "worktree" in body.lower()

    # Arbitrary shell forbidden
    assert "arbitrary shell" in body.lower()
    assert ("exploit" in body.lower() or "hostile" in body.lower())

    # Critiques, never enacts fix & no write access
    assert "critiques, never enacts" in body.lower()
    assert "no write access" in body.lower()


def test_reviewer_charter_declaration_source_and_fallback():
    _, body = parse_frontmatter_and_body(REVIEWER_CHARTER_PATH)

    # Where declared comes from
    assert ("readme" in body.lower() or "context.md" in body.lower() or "manifest" in body.lower())

    # Fallback when repo declares nothing
    assert ("declares nothing" in body.lower() or "declares no" in body.lower() or "no test" in body.lower())
    assert ("diff" in body.lower() or "fails closed" in body.lower() or "read-only" in body.lower())


def test_reviewer_charter_runs_suite_itself_rationale():
    _, body = parse_frontmatter_and_body(REVIEWER_CHARTER_PATH)

    # Runs suite itself rather than trusting Coder's report
    assert "coder" in body.lower()
    assert ("trust" in body.lower() or "report" in body.lower())
    assert "weakened" in body.lower() or "unnoticed" in body.lower()
