"""Tests for regression_test_gate.py.

Run: uv run pytest
"""

from __future__ import annotations

import subprocess

import pytest

from git_quality_gates import regression_test_gate as gate

SRC = ["src/main.cpp"]


def test_fix_on_src_without_test_is_rejected():
    assert len(gate.judge("fix(queue): retry on close\n\n- retry", SRC)) == 1


def test_fix_with_a_native_test_passes():
    assert gate.judge("fix(queue): reconnect", [*SRC, "test/test_queue/test_queue.cpp"]) == []


def test_fix_with_a_script_test_passes():
    paths = ["src/a.cpp", "tests/test_parser.py"]
    assert gate.judge("fix: a", paths) == []
    assert gate.judge("fix: a", ["src/a.cpp", "pkg/test_comment.py"]) == []
    assert gate.judge("fix: a", ["src/a.cpp", "scripts/test-hook.sh"]) == []


def test_fix_outside_src_owes_nothing():
    assert gate.judge("fix(ci): quote the path", [".github/workflows/ci.yml"]) == []
    assert gate.judge("fix(docs): a link", ["docs/ARCHITECTURE.md"]) == []
    assert gate.judge("fix(scripts): a flag", ["scripts/build.sh"]) == []


def test_other_types_owe_nothing():
    assert gate.judge("feat(sync): retry", SRC) == []
    assert gate.judge("refactor(comm): rename", SRC) == []
    assert gate.judge("chore: tidy", SRC) == []


def test_scope_and_breaking_marker_still_parse_as_fix():
    assert len(gate.judge("fix!: drop the old route", SRC)) == 1
    assert len(gate.judge("fix(a/b)!: drop the old route", SRC)) == 1


def test_unparseable_subject_is_left_to_the_commit_msg_hook():
    assert gate.judge("fixed the thing", SRC) == []
    assert gate.judge("", SRC) == []


def test_no_test_trailer_with_a_real_reason_passes():
    message = "fix(worker): wait for link\n\nNo-test: the failure only exists on real hardware"
    assert gate.judge(message, SRC) == []


def test_no_test_trailer_with_a_short_reason_is_rejected():
    findings = gate.judge("fix: a\n\nNo-test: hardware", SRC)
    assert len(findings) == 1
    assert "8-character" in findings[0]


def test_empty_no_test_trailer_is_rejected():
    assert len(gate.judge("fix: a\n\nNo-test:", SRC)) == 1


def test_a_test_path_is_recognised_by_location_and_name():
    assert gate.is_test_path("test/test_x/test_x.cpp")
    assert gate.is_test_path("scripts/test_emulator.py")
    assert gate.is_test_path("scripts/test-post.sh")
    assert not gate.is_test_path("src/test_helper.cpp")
    assert not gate.is_test_path("scripts/build.sh")
    assert not gate.is_test_path("docs/test/notes.md")


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "test").mkdir()
    (tmp_path / "src" / "a.cpp").write_text("a\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "chore: start", "--no-verify")
    _git(tmp_path, "tag", "v0.0.1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _commit(repo, message, **files):
    for name, body in files.items():
        path = repo / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, "--no-verify")


def test_range_reports_an_unprotected_fix(repo):
    _commit(repo, "fix(a): bug", src__a_cpp="b\n")
    findings = gate.check_range("v0.0.1..HEAD")
    assert len(findings) == 1
    assert "fix(a): bug" in findings[0]


def test_range_passes_a_fix_with_its_test(repo):
    _commit(repo, "fix(a): bug", src__a_cpp="b\n", test__test_a_cpp="t\n")
    assert gate.check_range("v0.0.1..HEAD") == []


def test_staged_message_is_judged_against_the_index(repo):
    (repo / "src" / "a.cpp").write_text("b\n")
    _git(repo, "add", "src/a.cpp")
    message = repo / "msg.txt"
    message.write_text("fix(a): bug\n\n- change\n# a comment line\n")
    assert len(gate.check_staged(message)) == 1

    (repo / "test" / "test_a.cpp").write_text("t\n")
    _git(repo, "add", "test/test_a.cpp")
    assert gate.check_staged(message) == []


def test_amend_reads_head_when_the_index_is_empty(repo):
    _commit(repo, "fix(a): bug", src__a_cpp="b\n")
    message = repo / "msg.txt"
    message.write_text("fix(a): bug\n")
    assert len(gate.check_staged(message)) == 1
