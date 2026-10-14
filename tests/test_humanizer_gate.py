"""Tests for humanizer_gate.py.

Run: uv run pytest
"""

from __future__ import annotations

from git_quality_gates import humanizer_gate

EM = chr(0x2014)
EN = chr(0x2013)
CURLY_OPEN = chr(0x201C)
APOSTROPHE = chr(0x2019)
ROBOT = chr(0x1F916)
LEVER = "lever" + "age"
ROBUST = "rob" + "ust"


def diff_of(path: str, *lines: str) -> str:
    body = "\n".join("+" + line for line in lines)
    return f"--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}\n"


def rules(path: str, *lines: str) -> list[str]:
    return [rule for _, _, rule, _ in humanizer_gate.scan(diff_of(path, *lines))]


def test_clean_line_passes():
    assert rules("src/a.cpp", "// retry after five seconds") == []


def test_em_dash_is_rejected():
    assert rules("README.md", f"The worker {EM} not the queue {EM} resets.") == ["em or en dash"]


def test_en_dash_is_rejected():
    assert rules("src/a.cpp", f"// range 1{EN}5") == ["em or en dash"]


def test_curly_quotes_are_rejected():
    assert rules("docs/a.md", f"{CURLY_OPEN}quoted{APOSTROPHE}") == ["curly quote"]


def test_emoji_is_rejected_in_any_file():
    assert rules("docs/a.md", f"done {ROBOT}") == ["emoji"]
    assert rules("src/a.cpp", f"// done {ROBOT}") == ["emoji"]


def test_ai_vocabulary_is_rejected_with_inflections():
    assert rules("src/a.cpp", f"// {LEVER} the cache") == [f"AI vocabulary '{LEVER}'"]
    assert rules("docs/a.md", f"A {ROBUST} design.") == [f"AI vocabulary '{ROBUST}'"]
    assert rules("docs/a.md", "We utilized it.") == ["AI vocabulary 'utilized'"]


def test_vocabulary_matches_whole_words_only():
    assert rules("src/a.cpp", "// the unenhanced path and a crucially_named_var") == []


def test_attribution_line_is_rejected():
    assert rules("docs/a.md", "Co-Authored-By: Claude <noreply@anthropic.com>") == [
        "AI attribution"
    ]
    assert rules("docs/a.md", "Generated with Claude Code") == ["AI attribution"]


def test_human_co_author_is_allowed():
    assert rules("docs/a.md", "Co-authored-by: Jane Doe <jane@example.com>") == []


def test_filler_opener_is_rejected():
    assert rules("docs/a.md", "This document provides an overview.") == ["filler opener"]


def test_prose_double_hyphen_in_comment_is_rejected():
    assert rules("src/a.cpp", "// the worker -- not the queue -- resets") == ["prose double hyphen"]


def test_double_hyphen_in_commands_and_rulers_is_allowed():
    assert rules("docs/a.md", "run git log -- src/ to see it") == []
    assert rules("docs/a.md", "| a | ---- |") == []
    assert rules("src/a.cpp", "int x = 1; // --") == []


def test_double_hyphen_in_code_is_not_prose():
    assert rules("src/a.cpp", "int x = a -- b;") == []


def test_allow_token_exempts_one_line():
    assert rules("src/a.cpp", f"// {LEVER} the cache  humanizer-allow") == []


def test_vendored_and_secret_paths_are_skipped():
    assert rules("vendor/pkg/a.h", f"// a {EM} b") == []
    assert rules("node_modules/pkg/a.h", f"// a {EM} b") == []


def test_gate_files_are_skipped_by_name():
    assert rules("tools/humanizer_gate.py", f"# a {EM} b") == []


def test_removed_lines_and_context_are_ignored():
    diff = f"--- a/a.md\n+++ b/a.md\n@@ -1,2 +1,1 @@\n-old {EM} text\n kept {EM} text\n+fine\n"
    assert humanizer_gate.scan(diff) == []


def test_line_numbers_follow_the_hunk_header():
    diff = "--- a/a.md\n+++ b/a.md\n@@ -0,0 +7,2 @@\n+fine\n+" + f"bad {EM} line" + "\n"
    assert [(p, n) for p, n, _, _ in humanizer_gate.scan(diff)] == [("a.md", 8)]


def test_deleted_file_is_ignored():
    diff = "--- a/a.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-gone\n"
    assert humanizer_gate.scan(diff) == []


def test_attribution_is_read_in_prose_files_only():
    line = "Co-Authored-By: Claude <noreply@anthropic.com>"
    assert rules("notes.txt", line) == ["AI attribution"]
    assert rules("scripts/hooks/prepare-commit-msg", f"# removes {line}") == []
    assert rules("scripts/a.py", f"# removes {line}") == []
