"""Offline tests for prose_check.py: the dash check in Markdown and the comment checks in
source files (dashes, British spellings, Wi-Fi, history narration).

Run: uv run pytest
"""

from __future__ import annotations

import pytest

from git_quality_gates import config, prose_check

EM = chr(0x2014)
EN = chr(0x2013)


@pytest.fixture(autouse=True)
def _allow_tmp(tmp_path):
    prose_check.set_allowed_roots([tmp_path])
    yield
    prose_check.set_allowed_roots()


def _kinds(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf8", newline="")
    _raw, findings = prose_check.check(path)
    return [(f[0], f[1]) for f in findings]


def test_markdown_flags_em_and_en_dashes(tmp_path):
    text = f"One {EM} two.\n\nRange 3{EN}5 here.\n"
    assert _kinds(tmp_path, "a.md", text) == [("dash", 1), ("dash", 3)]


def test_markdown_ignores_dashes_in_code(tmp_path):
    text = f"A `x {EM} y` span.\n\n```\nfenced {EM} block\n```\n"
    assert _kinds(tmp_path, "a.md", text) == []


def test_cpp_flags_dash_in_line_and_block_comments(tmp_path):
    text = f"int a; // first {EM} note\n/* second {EN} note */\nint b;\n"
    assert _kinds(tmp_path, "a.cpp", text) == [("dash", 1), ("dash", 2)]


def test_cpp_ignores_dash_in_string_literal(tmp_path):
    text = f'const char *s = "a {EM} b"; // fine\nconst char *t = "// {EM}";\n'
    assert _kinds(tmp_path, "a.cpp", text) == []


def test_cpp_raw_string_and_char_literal_do_not_start_comments(tmp_path):
    text = f'auto s = R"x(// {EM} not a comment)x";\nchar q = \'"\'; // ok\n'
    assert _kinds(tmp_path, "a.cpp", text) == []


def test_python_flags_comment_and_docstring_but_not_strings(tmp_path):
    text = (
        f'"""Module {EM} docstring."""\nx = 1  # trailing {EM} comment\ny = "plain {EM} string"\n'
    )
    assert _kinds(tmp_path, "a.py", text) == [("dash", 1), ("dash", 2)]


def test_shell_and_ini_comments(tmp_path):
    assert _kinds(tmp_path, "a.sh", f"echo '# {EM} no'\n# yes {EM} flagged\n") == [("dash", 2)]
    assert _kinds(tmp_path, "a.ini", f"[env]\n; note {EM} here\nkey = a {EM} b\n") == [("dash", 2)]


def test_history_phrases_are_flagged(tmp_path):
    text = "// It used to poll twice.\n// The old code looped.\n// Formerly a macro.\n"
    assert sorted(_kinds(tmp_path, "a.cpp", text)) == [
        ("history", 1),
        ("history", 2),
        ("history", 3),
    ]


def test_current_behavior_comments_pass(tmp_path):
    text = (
        "// Name used to read settings.\n"
        "// The folder that was removed is returned.\n"
        "// A file previously uploaded by the client.\n"
    )
    assert _kinds(tmp_path, "a.cpp", text) == []


def test_configured_term_is_flagged_but_the_identifier_is_not(tmp_path):
    config.set_current(config.with_overrides({"prose": {"terms": {"WiFi": "Wi-Fi"}}}))
    text = "// WiFi only here\n// calls WiFi.begin() and WiFi::status\n"
    assert _kinds(tmp_path, "a.cpp", text) == [("term", 1)]


def test_spelling_is_checked_in_comments_but_not_identifiers(tmp_path):
    text = "int normalise_device_id(); // normalise the id\n"
    assert _kinds(tmp_path, "a.cpp", text) == [("spelling", 1)]


def test_fix_rewrites_comment_spelling_and_keeps_crlf(tmp_path):
    path = tmp_path / "a.cpp"
    path.write_bytes(b"int normalise_device_id(); // normalise the id\r\nint b;\r\n")
    raw, findings = prose_check.check(path)
    assert prose_check.fix(raw, findings) == (
        "int normalise_device_id(); // normalize the id\r\nint b;\r\n"
    )


def test_prose_check_itself_is_exempt(tmp_path):
    assert _kinds(tmp_path, "prose_check.py", f"# a {EM} b\n") == []
