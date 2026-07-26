#!/usr/bin/env python3
"""Report likely personal data in a publishable Goals OS repository.

The generic tier is safe to publish because its rules name data *shapes*, not
people.  An optional private Brain config adds identity terms and allowlist
entries.  Identity values are deliberately never included in the report.
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


GENERIC_PATTERNS = {
    "email-address": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "absolute-home-path": re.compile(
        r"(?i)(?:/Users/[^/\s]+|/home/[^/\s]+|[A-Z]:\\\\Users\\[^\\\s]+)"
    ),
    "api-key-shape": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b"
    ),
    "phone-number": re.compile(
        r"(?x)(?<!\w)(?:\+44\s?7\d{3}|07\d{3})(?:[\s-]?\d{3}){2}(?!\w)"
    ),
    "uk-postcode": re.compile(
        r"(?i)\b(?:[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b"
    ),
    "icloud-mobile-documents-path": re.compile(r"Library/Mobile\ Documents/iCloud~"),
}


@dataclass(frozen=True)
class Finding:
    category: str
    relative_path: str
    line: int


def is_private_brain(root: Path) -> bool:
    """Recognise a private Brain by its required per-Brain code-root config.

    This check is deliberately structural: a private Brain is rejected before
    traversing any content rather than omitted by a pattern that could drift.
    """
    return (root / "config" / "code-root.md").is_file()


def parse_identity_config(brain: Path) -> tuple[list[str], set[tuple[str, str]]]:
    """Read the private markdown config without requiring a YAML dependency."""
    config = brain / "config" / "personal-data-check.md"
    if not config.is_file():
        raise ValueError(f"identity config not found: {config}")

    section = None
    terms = []
    allowlist = set()
    for raw_line in config.read_text(encoding="utf-8").splitlines():
        heading = raw_line.strip().lower()
        if heading == "## identity terms":
            section = "terms"
            continue
        if heading == "## allowlist":
            section = "allowlist"
            continue
        if not raw_line.startswith("- "):
            continue
        value = raw_line[2:].strip().strip("`")
        if section == "terms" and value:
            terms.append(value)
        elif section == "allowlist" and " :: " in value:
            path, term = value.split(" :: ", 1)
            allowlist.add((path.strip(), term.strip()))
    return terms, allowlist


def tracked_files(root: Path) -> list[Path]:
    """Return only versioned files, never ignored local state or Git history."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [root / item for item in result.stdout.decode().split("\0") if item]


def scan_paths(
    root: Path,
    paths: list[Path],
    identity_terms: list[str] | None = None,
    allowlist: set[tuple[str, str]] | None = None,
) -> list[Finding]:
    """Scan supplied text files and return safe, value-free findings."""
    identity_terms = identity_terms or []
    allowlist = allowlist or set()
    identity_patterns = [re.compile(re.escape(term), re.IGNORECASE) for term in identity_terms]
    findings = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative_path = path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for category, pattern in GENERIC_PATTERNS.items():
                if pattern.search(line):
                    findings.append(Finding(category, relative_path, line_number))
            for term, pattern in zip(identity_terms, identity_patterns):
                if pattern.search(line) and (relative_path, term) not in allowlist:
                    findings.append(Finding("identity-term", relative_path, line_number))
    return findings


def format_report(findings: list[Finding]) -> str:
    if not findings:
        return "personal-data-check: 0 findings"
    lines = [f"personal-data-check: {len(findings)} finding(s)"]
    lines.extend(f"  {f.relative_path}:{f.line}: {f.category}" for f in findings)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="publishable repository to scan")
    parser.add_argument(
        "--brain", default=os.environ.get("GOALS_OS_BRAIN_PATH"),
        help="private Brain containing config/personal-data-check.md",
    )
    parser.add_argument(
        "--report-only", action="store_true",
        help="always exit zero after reporting; required while cleanup is underway",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    if is_private_brain(root):
        print("personal-data-check: refusing to scan a private Brain", file=sys.stderr)
        return 2

    identity_terms = []
    allowlist = set()
    identity_available = False
    if args.brain:
        try:
            identity_terms, allowlist = parse_identity_config(Path(args.brain).expanduser())
            identity_available = True
        except ValueError as error:
            print(f"personal-data-check: identity tier unavailable ({error})", file=sys.stderr)
    else:
        print(
            "personal-data-check: identity tier unavailable (no --brain or GOALS_OS_BRAIN_PATH)",
            file=sys.stderr,
        )

    try:
        findings = scan_paths(root, tracked_files(root), identity_terms, allowlist)
    except subprocess.CalledProcessError as error:
        print(f"personal-data-check: cannot list tracked files: {error}", file=sys.stderr)
        return 2
    print(format_report(findings))
    if args.report_only:
        return 0
    if not identity_available:
        return 2
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
