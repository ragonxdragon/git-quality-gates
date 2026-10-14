"""Tests for comment_gate.py.

Run: uv run pytest
"""

from __future__ import annotations

from git_quality_gates import comment_gate


def diff_of(path: str, *lines: str) -> str:
    body = "\n".join("+" + line for line in lines)
    return f"--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}\n"


def rules(path: str, *lines: str) -> list[str]:
    return [rule for _, _, rule, _ in comment_gate.scan(diff_of(path, *lines))]


def test_comment_describing_current_behavior_passes():
    assert rules("src/a.cpp", "// Retries three times, then gives up.") == []
    assert rules("scripts/a.sh", "# Skip the build when nothing changed.") == []


def test_history_words_are_rejected():
    assert rules("src/a.cpp", "// previously this slept for a second") == [
        "narrates earlier behavior"
    ]
    assert rules("src/a.cpp", "// the worker is no longer reset here") == [
        "narrates earlier behavior"
    ]
    assert rules("src/a.cpp", "// it used to return early") == ["narrates earlier behavior"]


def test_used_to_as_a_purpose_is_allowed():
    assert rules("src/a.cpp", "// A buffer used to hold the reply.") == []
    assert rules("src/a.cpp", "// This pin is used to reset the chip.") == []


def test_reference_to_old_code_is_rejected():
    assert rules("src/a.cpp", "// the old implementation polled") == ["refers to the old code"]


def test_replacement_narration_is_rejected():
    assert rules("src/a.cpp", "// this replaces the retry loop") == ["narrates a replacement"]


def test_change_narration_is_rejected():
    assert rules("src/a.cpp", "// we now check the length first") == ["narrates a change"]
    assert rules("src/a.cpp", "// the delay was replaced") == ["narrates a change"]
    assert rules("src/a.cpp", "// now returns the cached value") == ["narrates a change"]


def test_anchor_to_a_change_or_version_is_rejected():
    assert rules("src/a.cpp", "// needed after the refactor") == ["anchored to a change"]
    assert rules("src/a.cpp", "// since 1.4.2 the cache carries this") == ["anchored to a version"]


def test_tracker_reference_is_rejected():
    assert rules("src/a.cpp", "// fixes #42") == ["tracker reference"]


def test_block_comment_lines_are_read():
    assert rules("src/a.h", "/* previously this was a macro */") == ["narrates earlier behavior"]
    assert rules("src/a.h", " * previously this was a macro") == ["narrates earlier behavior"]


def test_trailing_comment_is_read_but_code_is_not():
    assert rules("src/a.cpp", "int x = 1; // formerly 2") == ["narrates earlier behavior"]
    assert rules("src/a.cpp", 'const char *s = "previously";') == []


def test_url_slashes_are_not_a_comment():
    assert rules("src/a.cpp", 'const char *u = "http://example.com/previously";') == []


def test_hash_comments_in_python_and_yaml():
    assert rules("scripts/a.py", "x = 1  # previously it was 2") == ["narrates earlier behavior"]
    assert rules(".github/workflows/a.yml", "  # formerly ran on push") == [
        "narrates earlier behavior"
    ]


def test_shebang_and_c_preprocessor_are_not_comments():
    assert rules("scripts/a.sh", "#!/usr/bin/env previously") == []
    assert rules("src/a.cpp", "#include <previously.h>") == []


def test_markdown_is_not_scanned():
    assert rules("docs/a.md", "Previously this slept.") == []


def test_allow_token_exempts_one_line():
    assert rules("src/a.cpp", "// previously this was a macro  comment-allow") == []


def test_vendored_and_secret_paths_are_skipped():
    assert rules("vendor/pkg/a.h", "// previously this was a macro") == []
    assert rules("node_modules/pkg/a.h", "// previously this was a macro") == []


def test_removed_lines_are_ignored():
    diff = "--- a/a.cpp\n+++ b/a.cpp\n@@ -1 +1 @@\n-// previously this was a macro\n+// a macro\n"
    assert comment_gate.scan(diff) == []


def test_finding_carries_the_line_number():
    diff = "--- a/a.cpp\n+++ b/a.cpp\n@@ -0,0 +4,2 @@\n+// fine\n+// previously this was a macro\n"
    assert [(p, n) for p, n, _, _ in comment_gate.scan(diff)] == [("a.cpp", 5)]


def test_state_words_that_are_not_history_pass():
    assert rules("src/a.cpp", "// The key is no longer needed; wipe it.") == []
    assert rules("src/a.cpp", "// A file previously uploaded by the client.") == []
    assert rules("src/a.cpp", "// Frames may have been dropped by the network.") == []


def test_ip_address_is_not_a_version():
    assert rules("src/a.cpp", "// reads from 10.0.0.2 by default") == []
    assert rules("src/a.cpp", "// since v1.4.2 the cache carries this") == ["anchored to a version"]
