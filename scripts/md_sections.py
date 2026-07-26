#!/usr/bin/env python3
"""Shared markdown section-scanning patterns.

A leaf module by design: it imports nothing from `scripts/`, so `daily_note`,
`dashboard`, `execute` and the migrations can all import it without the
circularity the existing graph (daily_note → dashboard → execute) would
otherwise create.
"""


# `[ \t]*\n` after the heading, never `\s*\n`. `\s` matches newlines, so on an
# *empty* section `\s*` swallowed the blank line and the match then began at the
# NEXT heading — making the "body" of the empty section every section that
# followed it, to EOF.
#
# What that cost, per call site: `_replace_section` silently deleted them (a
# daily note with no open Waiting For items lost `## Notes` and everything after
# it on the next same-day regeneration); `_append_new_lines_to_section` appended
# new rows under the wrong heading; `execute._insert_before_next_heading`
# appended a `file-capture` into the *next* section of a curated note.
#
# Matching only the heading line's own terminator keeps an empty section empty.
#
# `{}` is the heading text, `re.escape`d by the caller unless it is deliberately
# a pattern (dashboard's `.*Waiting For`). Use with re.MULTILINE | re.DOTALL;
# group 1 is the section body.
#
# Line endings: `[ \t]*` deliberately does NOT tolerate a CR, so a CRLF-authored
# file's heading will not match at all. That is the chosen failure mode — a
# heading that doesn't match is a visible no-op, whereas widening this to admit
# `\r` reintroduces the class of ambiguity that caused the bug. Every writer in
# this Engine emits LF; if a path is ever added that reads DOS-authored files,
# normalise line endings at the read boundary rather than loosening this pattern.
SECTION_BODY = r"^## {}[ \t]*\n(.*?)(?=\n## |\Z)"
