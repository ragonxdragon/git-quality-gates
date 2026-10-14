#!/usr/bin/env python3
"""Writing-standard gate: block new dashes, curly quotes, emoji, AI vocabulary and attribution.

    git-quality-gates writing                 staged changes
    git-quality-gates writing --range A..B    a revision range

Only ADDED lines are read, so a file that already carries old text can still be
edited. The gate is deterministic and runs on this machine alone.

Rejected in any text file:
  - em and en dashes
  - curly quotes
  - emoji
  - AI vocabulary (the list in VOCABULARY)
  - AI-attribution lines in Markdown and text files (a Co-Authored-By trailer naming a tool, a
    "Generated with" line)
  - a document that opens with "This document provides"
  - " -- " used as a prose dash in a comment or a Markdown file

Allow one line by ending it with the token humanizer-allow. Vendored trees are
never read. The gate's own source and test build their patterns from escapes
and are skipped by name, because they have to spell the words they ban.
"""

from __future__ import annotations

import argparse
import re
import sys

from . import attribution, config, gitdiff

SELF = ("humanizer_gate.py", "test_humanizer_gate.py")
ALLOW_TOKEN = "humanizer-allow"

#: Built from code points so this file stays free of the characters it rejects.
DASH = re.compile("[" + chr(0x2014) + chr(0x2013) + "]")
CURLY = re.compile("[" + "".join(chr(c) for c in (0x201C, 0x201D, 0x2018, 0x2019)) + "]")
_EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x1F1E6, 0x1F1FF))
EMOJI = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _EMOJI_RANGES) + chr(0xFE0F) + "]"
)

#: Stems with their inflections. Each entry matches on word boundaries.
VOCABULARY = (
    r"comprehensive(?:ly)?",
    r"robust(?:ly|ness)?",
    r"seamless(?:ly)?",
    r"leverag(?:e|es|ed|ing)",
    r"delv(?:e|es|ed|ing)",
    r"crucial(?:ly)?",
    r"pivotal",
    r"streamlin(?:e|es|ed|ing)",
    r"enhanc(?:e|es|ed|ing|ement|ements)",
    r"empower(?:s|ed|ing|ment)?",
    r"utiliz(?:e|es|ed|ing|ation)",
    r"holistic(?:ally)?",
    r"tapestry",
)


def jargon_pattern() -> re.Pattern[str]:
    """The vocabulary matcher: built-in stems plus [writing].extra_vocabulary words."""
    extra = [re.escape(word) for word in config.current().get("writing", "extra_vocabulary")]
    return re.compile(r"\b(?:" + "|".join((*VOCABULARY, *extra)) + r")\b", re.IGNORECASE)


OPENER = re.compile(r"^\s*(?:#+\s*)?this (?:document|page|guide) provides\b", re.IGNORECASE)

#: ' -- ' reads as a dash in prose. CLI flags, SQL comments and rulers are not prose.
PROSE_DOUBLE_HYPHEN = re.compile(r"(?<!-) -- (?!-)")
DOUBLE_HYPHEN_SAFE = re.compile(
    r"-{4,}|<!--|-->|\b(?:git|sh|bash|uv|python|pip|npm|npx|cargo|go|make|cmake|docker)\b"
)

MARKDOWN = (".md", ".markdown")
#: Attribution is read in prose files only. Scripts that implement the attribution
#: filters have to spell the lines they remove.
PROSE_FILES = (*MARKDOWN, ".txt")


def is_comment(path: str, line: str) -> bool:
    if path.endswith(MARKDOWN):
        return True
    stripped = line.lstrip()
    return stripped.startswith(("//", "#", "*", "/*", ";")) or "//" in line


def findings_for(path: str, number: int, text: str) -> list[tuple[str, int, str, str]]:
    """Every rule one added line breaks, as (path, line, rule, fix)."""
    if (
        path.rsplit("/", 1)[-1] in SELF
        or gitdiff.is_vendored(path)
        or text.rstrip().endswith(ALLOW_TOKEN)
    ):
        return []
    out: list[tuple[str, int, str, str]] = []

    def add(rule: str, fix: str) -> None:
        out.append((path, number, rule, fix))

    if DASH.search(text):
        add("em or en dash", "use a comma, period, colon or parentheses")
    if CURLY.search(text):
        add("curly quote", "use a straight quote")
    if EMOJI.search(text):
        add("emoji", "remove it")
    found = jargon_pattern().search(text)
    if found:
        add(f"AI vocabulary '{found.group(0)}'", "say the specific thing in plain words")
    if path.endswith(PROSE_FILES) and attribution.has_attribution(text):
        add("AI attribution", "remove the attribution line")
    if OPENER.search(text):
        add("filler opener", "start with the content")
    if (
        is_comment(path, text)
        and PROSE_DOUBLE_HYPHEN.search(text)
        and not DOUBLE_HYPHEN_SAFE.search(text)
    ):
        add("prose double hyphen", "use a comma, period or colon")
    return out


def scan(diff: str) -> list[tuple[str, int, str, str]]:
    found: list[tuple[str, int, str, str]] = []
    for path, number, text in gitdiff.added_lines(diff):
        found.extend(findings_for(path, number, text))
    return found


def main(argv: list[str]) -> int:
    gitdiff.use_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--range", dest="rev_range", help="a revision range such as A..B")
    args = parser.parse_args(argv)

    found = scan(gitdiff.git_diff(args.rev_range))
    if not found:
        return 0
    sys.stderr.write("\nBLOCKED: writing standard, added lines only\n")
    for path, number, rule, fix in found:
        sys.stderr.write(f"  {path}:{number}  [{rule}]  {fix}\n")
    sys.stderr.write(
        f"\nFix the lines, end one with {ALLOW_TOKEN} to allow it, or bypass once with\n"
        "GQG_SKIP=writing (logged).\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
