#!/usr/bin/env python3
"""Librarian's Compile and Audit verbs (`protocols/wiki.md`, `protocols/charters/librarian.md`).

Mirrors triage.py's split: this script only does deterministic file I/O
(scanning, writing, index maintenance, heartbeat.bump, Action Log entries).
Concept assignment (Compile) and stale/duplicate judgement (Audit) are
always model-driven (ticket 02/03) — that happens in the invoking Claude
Code session, which then calls this script's `apply_*` functions with the
already-decided structured result.

wiki/ structure (ticket 01): flat `wiki/<concept-slug>.md` articles + one
`wiki/_index.md`. Every scan/list function here only ever looks at files
directly inside `wiki/` (never recurses into subdirectories) and skips a
fixed denylist of non-article files — this matters in the real Vault,
where `wiki/` already holds v1's pre-existing, two-tier-hierarchy Wiki
content (root `_master-index.md`/`_memory.md` + per-concept subfolders,
merged in by a different, earlier work-stream) sitting alongside the new
flat structure this ticket builds. That coexistence is a known, flagged
gap (see the ticket log) — not something this script tries to reconcile.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heartbeat  # noqa: E402
import log_action  # noqa: E402

NON_ARTICLE_FILES = {
    "_index.md", "_master-index.md", "_memory.md", "README.md", "CLAUDE.md",
}

INDEX_ROW_RE = re.compile(r'^\|\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*\|\s*(.*?)\s*\|\s*$')
SOURCE_LINK_RE = re.compile(r'\[\[(archive/inbox/[^\]|]+)\]\]')
WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]*)?\]\]')


def _flat_articles(brain_path: Path) -> list:
    """Every wiki/<slug>.md file, direct children only, excluding non-articles."""
    wiki_dir = brain_path / "wiki"
    if not wiki_dir.is_dir():
        return []
    return sorted(
        p for p in wiki_dir.glob("*.md")
        if p.name not in NON_ARTICLE_FILES
    )


def read_index(brain_path: Path) -> list:
    """Parse wiki/_index.md's table into [{"slug": ..., "summary": ...}, ...]."""
    index_path = brain_path / "wiki" / "_index.md"
    if not index_path.exists():
        return []
    rows = []
    for line in index_path.read_text().splitlines():
        m = INDEX_ROW_RE.match(line.strip())
        if not m:
            continue
        slug, summary = m.group(1).strip(), m.group(2).strip()
        rows.append({"slug": slug, "summary": summary})
    return rows


def list_archived_captures(brain_path: Path) -> list:
    """Every already-triaged, Execute-processed capture under archive/inbox/<source>/.

    Compile reads exclusively from here — never the live inbox/raw/ queue
    (protocols/wiki.md's Compile section).
    """
    archive_dir = brain_path / "archive" / "inbox"
    if not archive_dir.is_dir():
        return []
    captures = []
    for source_dir in sorted(p for p in archive_dir.iterdir() if p.is_dir()):
        source = source_dir.name
        for path in sorted(source_dir.glob("*.md")):
            text = path.read_text()
            id_match = re.search(r'^id:\s*(.+)$', text, re.MULTILINE)
            title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
            body_start = title_match.end() if title_match else 0
            body = text[body_start:].strip()
            captures.append({
                "id": id_match.group(1).strip() if id_match else path.stem,
                "source": source,
                "title": title_match.group(1).strip() if title_match else path.stem,
                "body": body,
                "path": f"archive/inbox/{source}/{path.stem}",
            })
    return captures


def cited_capture_paths(brain_path: Path) -> set:
    """Every archive/inbox/... path already referenced from a flat wiki article's
    Sources section (or anywhere in the article — a Compile write only ever
    puts these links under Sources, so scanning the whole file is equivalent
    and simpler)."""
    cited = set()
    for path in _flat_articles(brain_path):
        cited |= set(SOURCE_LINK_RE.findall(path.read_text()))
    return cited


def new_captures_for_compile(brain_path: Path) -> list:
    """Archived captures not yet cited by any flat wiki article's Sources section —
    the mechanical definition of "new material" a Compile run considers (no
    reliable archive-move timestamp exists to diff against instead; this
    mirrors triage.py's own idempotency-by-presence-in-output convention)."""
    cited = cited_capture_paths(brain_path)
    return [c for c in list_archived_captures(brain_path) if c["path"] not in cited]


def compile_scan(brain_path: Path, scope: str = None) -> dict:
    """Pure read-only scan — the mechanical half of a Compile pass.

    `scope`: None (incremental default — session decides concept assignment
    for `new_captures`, no concept is forced), a concept slug (force that
    one concept's resynthesis), or "full" (force every indexed concept's
    resynthesis — the exceptional-rebuild gate, ADR-0010; the caller/session
    is responsible for getting an explicit confirmation *before* passing
    scope="full", this function does not gate it itself).
    """
    index = read_index(brain_path)
    new_captures = new_captures_for_compile(brain_path)
    if scope == "full":
        forced_concepts = [row["slug"] for row in index]
    elif scope:
        forced_concepts = [scope]
    else:
        forced_concepts = []
    return {"index": index, "new_captures": new_captures, "forced_concepts": forced_concepts}


def compile_run(brain_path: Path, scope: str = None, now: dt.datetime = None) -> dict:
    """The Routine entry point: scan, then bump Compile's own row in
    config/routine-state.md regardless of outcome — mirroring triage.py's
    run(), "the routine ran and checked" is what Heartbeat needs to know,
    independent of whether there was anything to actually resynthesize.
    """
    now = now or dt.datetime.now()
    result = compile_scan(brain_path, scope=scope)
    heartbeat.bump(brain_path, "Compile", now)
    return result


def _existing_sources(text: str) -> list:
    """Sources lines already present in an article, in file order, deduped by link."""
    lines = []
    seen = set()
    for m in re.finditer(r'^-\s+(\d{4}-\d{2}-\d{2})\s+—\s+\[\[(archive/inbox/[^\]|]+)\]\]\s*$', text, re.MULTILINE):
        date_str, link = m.group(1), m.group(2)
        if link not in seen:
            seen.add(link)
            lines.append((date_str, link))
    return lines


def apply_compile(brain_path: Path, concept_slug: str, concept_title: str, article_body: str,
                   source_refs: list, now: dt.datetime = None, summary: str = None,
                   trigger: str = "Compile (Routine)", confidence: str = "Medium") -> Path:
    """The mechanical write: takes the session's already-decided concept slug,
    title, and fully-resynthesized article body, and performs the file I/O.

    `article_body` fully replaces the article's prior body (Compile resynthesizes
    the whole article each run it fires, ADR-0010) — the `## Sources` section is
    the one part that's additive-only, existing entries preserved, new
    `source_refs` appended (deduped by link, idempotent on rerun).
    """
    now = now or dt.datetime.now()
    wiki_dir = brain_path / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    article_path = wiki_dir / f"{concept_slug}.md"

    existing_sources = []
    if article_path.exists():
        existing_sources = _existing_sources(article_path.read_text())
    existing_links = {link for _, link in existing_sources}
    merged_sources = list(existing_sources)
    for date_str, link in source_refs:
        if link not in existing_links:
            merged_sources.append((date_str, link))
            existing_links.add(link)

    sources_block = "\n".join(f"- {d} — [[{link}]]" for d, link in merged_sources)
    text = (
        "---\n"
        "type: wiki-article\n"
        f"concept: {concept_slug}\n"
        "tags: [wiki]\n"
        "---\n\n"
        f"# {concept_title}\n\n"
        f"{article_body.strip()}\n\n"
        "## Sources\n"
        f"{sources_block}\n"
    )
    article_path.write_text(text)

    _update_index(brain_path, concept_slug, summary or concept_title)

    entry = log_action.build_entry(
        actor="Librarian",
        trigger=trigger,
        action_type="wiki-compile",
        action=f"Resynthesized '{concept_title}' ({concept_slug}) from {len(source_refs)} new source(s).",
        confidence=confidence,
        outcome=f"Wrote wiki/{concept_slug}.md",
        input_link=source_refs[0][1] if source_refs else "—",
    )
    log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)

    return article_path


def _sanitize_cell(text: str) -> str:
    """Keep a table cell on one line and pipe-safe (mirrors triage.py's own
    _sanitize — a model-authored summary/title could contain either)."""
    return text.replace("\n", " ").replace("|", "/").strip()


def _update_index(brain_path: Path, slug: str, summary: str):
    """Add a new row for `slug` to wiki/_index.md if it isn't already listed.
    Never touches an existing row's summary (Audit's relist-orphan verb, not
    Compile, owns dangling/unindexed-entry repair)."""
    index_path = brain_path / "wiki" / "_index.md"
    existing_slugs = {row["slug"] for row in read_index(brain_path)}
    if slug in existing_slugs:
        return
    summary = _sanitize_cell(summary)

    if not index_path.exists():
        index_path.write_text(
            "---\ntype: wiki-index\n---\n\n# Wiki — Index\n\n"
            "Machine-maintained by the Librarian's Compile/Audit verbs "
            "(`protocols/wiki.md`). Cheap-first read pattern: check this "
            "index, then open the article you need directly.\n\n"
            "| Article | Summary |\n|---|---|\n"
            f"| [[{slug}]] | {summary} |\n"
        )
        return

    text = index_path.read_text()
    new_row = f"| [[{slug}]] | {summary} |"
    if not text.endswith("\n"):
        text += "\n"
    index_path.write_text(text + new_row + "\n")


def _link_resolves(brain_path: Path, link: str) -> bool:
    """Resolve a [[wikilink]] target to a file on disk (filename-stem
    resolution, matching the vault-wide convention — root CLAUDE.md's
    "Internal links use [[wikilink]] format — resolution is by filename")."""
    if link.startswith("archive/inbox/"):
        return (brain_path / f"{link}.md").exists()
    if "/" not in link:
        return (brain_path / "wiki" / f"{link}.md").exists()
    rel = link if link.endswith(".md") else f"{link}.md"
    return (brain_path / rel).exists()


def find_dead_links(brain_path: Path) -> list:
    """Mechanical check #1: every [[wikilink]] in a flat wiki article whose
    target doesn't resolve to a file on disk. Zero LLM calls (ticket 03)."""
    findings = []
    for path in _flat_articles(brain_path):
        slug = path.stem
        for link in WIKILINK_RE.findall(path.read_text()):
            if not _link_resolves(brain_path, link):
                findings.append({"article": slug, "link": link})
    return findings


def find_orphans(brain_path: Path) -> dict:
    """Mechanical check #2: a flat wiki/*.md article not listed in
    wiki/_index.md ("unindexed_articles"), or an _index.md row pointing at a
    slug with no corresponding file on disk ("dangling_index_entries")."""
    article_slugs = {path.stem for path in _flat_articles(brain_path)}
    indexed_slugs = {row["slug"] for row in read_index(brain_path)}
    return {
        "unindexed_articles": sorted(article_slugs - indexed_slugs),
        "dangling_index_entries": sorted(indexed_slugs - article_slugs),
    }


def audit_scan_mechanical(brain_path: Path) -> dict:
    """Both mechanical Audit checks in one pass — dead links and orphans.
    Pure read, zero LLM calls, no writes. The semantic checks (stale,
    duplicate) require a model's judgement and are not this script's job
    (ticket 03) — the invoking session runs those over `find_dead_links`'s
    sibling data (the articles themselves) and produces its own findings."""
    return {
        "dead_links": find_dead_links(brain_path),
        "orphans": find_orphans(brain_path),
    }


def _remove_index_row(brain_path: Path, slug: str):
    index_path = brain_path / "wiki" / "_index.md"
    if not index_path.exists():
        return
    text = index_path.read_text()
    kept = []
    for line in text.splitlines():
        m = INDEX_ROW_RE.match(line.strip())
        if m and m.group(1).strip() == slug:
            continue
        kept.append(line)
    index_path.write_text("\n".join(kept) + ("\n" if text.endswith("\n") else ""))


def apply_fix_dead_link(brain_path: Path, article_slug: str, old_link: str, new_link: str = None,
                         now: dt.datetime = None, trigger: str = "Audit", confidence: str = "Medium") -> Path:
    """Repairs a broken wikilink (new_link given) or strips the line containing
    it entirely (new_link=None) in wiki/<article_slug>.md."""
    now = now or dt.datetime.now()
    article_path = brain_path / "wiki" / f"{article_slug}.md"
    text = article_path.read_text()
    old_ref = f"[[{old_link}]]"

    if new_link:
        new_text = text.replace(old_ref, f"[[{new_link}]]")
        outcome = f"Repaired link to [[{new_link}]]"
    else:
        lines = [ln for ln in text.splitlines() if old_ref not in ln]
        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        outcome = "Removed broken link"
    article_path.write_text(new_text)

    entry = log_action.build_entry(
        actor="Librarian", trigger=trigger, action_type="wiki-audit-fix-dead-link",
        action=f"Fixed dead link in wiki/{article_slug}.md: {old_link} -> {new_link or '(removed)'}.",
        confidence=confidence, outcome=outcome, input_link=f"wiki/{article_slug}.md",
    )
    log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)
    return article_path


def apply_relist_orphan(brain_path: Path, action: str, slug: str, summary: str = None,
                         now: dt.datetime = None, trigger: str = "Audit", confidence: str = "Medium") -> Path:
    """action="add": lists an unindexed article in wiki/_index.md.
    action="remove": deletes a dangling index row pointing at no file."""
    now = now or dt.datetime.now()
    index_path = brain_path / "wiki" / "_index.md"

    if action == "add":
        _update_index(brain_path, slug, summary or slug)
        outcome = f"Added [[{slug}]] to wiki/_index.md"
        action_desc = f"Relisted unindexed article '{slug}' in wiki/_index.md."
    elif action == "remove":
        _remove_index_row(brain_path, slug)
        outcome = f"Removed dangling index entry for '{slug}'"
        action_desc = f"Removed wiki/_index.md entry pointing at missing article '{slug}'."
    else:
        raise ValueError(f'Unknown action: {action!r} (expected "add" or "remove")')

    entry = log_action.build_entry(
        actor="Librarian", trigger=trigger, action_type="wiki-audit-relist-orphan",
        action=action_desc, confidence=confidence, outcome=outcome, input_link="wiki/_index.md",
    )
    log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)
    return index_path


def apply_delete_stale(brain_path: Path, slug: str, now: dt.datetime = None,
                        trigger: str = "Audit", confidence: str = "Medium") -> dict:
    """Deletes a superseded article. Plain git-delete, no archive/wiki/ folder
    (ticket 03) — git history plus the resynthesis guarantee are the safety net."""
    now = now or dt.datetime.now()
    article_path = brain_path / "wiki" / f"{slug}.md"
    if article_path.exists():
        article_path.unlink()
    _remove_index_row(brain_path, slug)

    entry = log_action.build_entry(
        actor="Librarian", trigger=trigger, action_type="wiki-audit-delete-stale",
        action=f"Deleted stale article '{slug}' (plain delete, no archive/wiki/ folder).",
        confidence=confidence, outcome=f"Deleted wiki/{slug}.md and its index row",
        input_link=f"wiki/{slug}.md",
    )
    log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)
    return {"deleted": slug}


def apply_merge_duplicate(brain_path: Path, keep_slug: str, merge_slug: str, merged_body: str,
                           now: dt.datetime = None, trigger: str = "Audit", confidence: str = "Medium") -> Path:
    """Merges merge_slug's content into keep_slug (merged_body is the
    session-authored merged article text) and deletes merge_slug. Tagged
    outward-facing/hard-to-reverse in config/action-types.md despite the
    resynthesis guarantee — merging discards a separate identity, a real
    loss even though no underlying capture is destroyed (ticket 03)."""
    now = now or dt.datetime.now()
    wiki_dir = brain_path / "wiki"
    keep_path = wiki_dir / f"{keep_slug}.md"
    merge_path = wiki_dir / f"{merge_slug}.md"

    keep_sources = _existing_sources(keep_path.read_text()) if keep_path.exists() else []
    merge_sources = _existing_sources(merge_path.read_text()) if merge_path.exists() else []
    seen, combined = set(), []
    for date_str, link in keep_sources + merge_sources:
        if link not in seen:
            seen.add(link)
            combined.append((date_str, link))

    title = keep_slug
    if keep_path.exists():
        m = re.search(r'^#\s+(.+)$', keep_path.read_text(), re.MULTILINE)
        if m:
            title = m.group(1).strip()

    sources_block = "\n".join(f"- {d} — [[{link}]]" for d, link in combined)
    text = (
        "---\n"
        "type: wiki-article\n"
        f"concept: {keep_slug}\n"
        "tags: [wiki]\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{merged_body.strip()}\n\n"
        "## Sources\n"
        f"{sources_block}\n"
    )
    keep_path.write_text(text)

    if merge_path.exists():
        merge_path.unlink()
    _remove_index_row(brain_path, merge_slug)

    entry = log_action.build_entry(
        actor="Librarian", trigger=trigger, action_type="wiki-audit-merge-duplicate",
        action=f"Merged '{merge_slug}' into '{keep_slug}' — Audit judged them the same concept.",
        confidence=confidence,
        outcome=f"wiki/{merge_slug}.md deleted; content merged into wiki/{keep_slug}.md",
        input_link=f"wiki/{merge_slug}.md",
    )
    log_action.append_entry(brain_path, now.strftime("%Y-%m-%d"), entry)
    return keep_path


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", required=True, help="Path to the Brain")
    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("compile-scan", help="Read-only Compile scan; bumps Compile's routine-state row.")
    scan.add_argument("--scope", default=None, help='A concept slug to force, or "full" for every concept.')

    apply_c = sub.add_parser("compile-apply", help="Mechanical write for one already-decided concept's resynthesis.")
    apply_c.add_argument("--concept-slug", required=True)
    apply_c.add_argument("--concept-title", required=True)
    apply_c.add_argument("--body-file", required=True, help="Path to a file containing the resynthesized article body.")
    apply_c.add_argument("--sources-json", default="[]", help='JSON list of [date, archive-path] pairs, e.g. [["2026-07-11","archive/inbox/voice/x"]]')
    apply_c.add_argument("--summary", default=None)
    apply_c.add_argument("--confidence", default="Medium", choices=("High", "Medium", "Low"))

    sub.add_parser("audit-scan-mechanical", help="Read-only dead-link + orphan scan. Zero LLM calls, no writes.")

    fix = sub.add_parser("audit-apply-fix-dead-link")
    fix.add_argument("--article-slug", required=True)
    fix.add_argument("--old-link", required=True)
    fix.add_argument("--new-link", default=None, help="Omit to remove the broken link's line entirely.")

    relist = sub.add_parser("audit-apply-relist-orphan")
    relist.add_argument("--action", required=True, choices=("add", "remove"))
    relist.add_argument("--slug", required=True)
    relist.add_argument("--summary", default=None)

    delete = sub.add_parser("audit-apply-delete-stale")
    delete.add_argument("--slug", required=True)

    merge = sub.add_parser("audit-apply-merge-duplicate")
    merge.add_argument("--keep-slug", required=True)
    merge.add_argument("--merge-slug", required=True)
    merge.add_argument("--body-file", required=True, help="Path to a file containing the merged article body.")

    return p.parse_args(argv)


def main(argv=None):
    import json

    args = parse_args(argv)
    brain_path = Path(args.brain).expanduser().resolve()
    if not brain_path.is_dir():
        sys.exit(f"Brain path does not exist: {brain_path}")

    if args.command == "compile-scan":
        result = compile_run(brain_path, scope=args.scope)
        print(f"New captures: {len(result['new_captures'])}")
        print(f"Indexed concepts: {len(result['index'])}")
        if result["forced_concepts"]:
            print(f"Forced concepts: {', '.join(result['forced_concepts'])}")
        print(json.dumps(result, indent=2))

    elif args.command == "compile-apply":
        body = Path(args.body_file).read_text()
        source_refs = [tuple(pair) for pair in json.loads(args.sources_json)]
        path = apply_compile(
            brain_path, args.concept_slug, args.concept_title, body, source_refs,
            summary=args.summary, confidence=args.confidence,
        )
        print(f"Wrote {path}")

    elif args.command == "audit-scan-mechanical":
        result = audit_scan_mechanical(brain_path)
        print(f"Dead links: {len(result['dead_links'])}")
        print(f"Unindexed articles: {len(result['orphans']['unindexed_articles'])}")
        print(f"Dangling index entries: {len(result['orphans']['dangling_index_entries'])}")
        print(json.dumps(result, indent=2))

    elif args.command == "audit-apply-fix-dead-link":
        path = apply_fix_dead_link(brain_path, args.article_slug, args.old_link, args.new_link)
        print(f"Fixed {path}")

    elif args.command == "audit-apply-relist-orphan":
        path = apply_relist_orphan(brain_path, args.action, args.slug, summary=args.summary)
        print(f"Updated {path}")

    elif args.command == "audit-apply-delete-stale":
        result = apply_delete_stale(brain_path, args.slug)
        print(f"Deleted {result['deleted']}")

    elif args.command == "audit-apply-merge-duplicate":
        body = Path(args.body_file).read_text()
        path = apply_merge_duplicate(brain_path, args.keep_slug, args.merge_slug, body)
        print(f"Merged into {path}")


if __name__ == "__main__":
    main()
