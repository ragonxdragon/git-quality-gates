"""Tests for commit_message_gate.py.

Run: uv run pytest
"""

from __future__ import annotations

import subprocess

import pytest

from git_quality_gates import commit_message_gate as gate


def commit(subject: str, body: str = "", parents: int = 1) -> gate.Commit:
    return gate.Commit("a" * 40, parents, subject, body)


@pytest.mark.parametrize(
    "subject",
    [
        "feat(sync): add retry",
        "fix: handle an empty reply",
        "fix(build,warnings): clean the build",
        "refactor(comm)!: rename the client",
        "security(tls): pin the root",
        "chore(hooks): add a gate",
    ],
)
def test_conventional_subjects_pass(subject):
    assert gate.findings_for(commit(subject)) == []


@pytest.mark.parametrize(
    "subject",
    [
        "Update the readme",
        "fixed the thing",
        "fix:missing space",
        "Fix: capitalized type",
        "fix(): empty scope",
        "logging/led: not a type",
    ],
)
def test_unparseable_subjects_are_rejected(subject):
    findings = gate.findings_for(commit(subject))
    assert len(findings) == 1
    assert "does not parse" in findings[0]


def test_unknown_type_is_rejected():
    findings = gate.findings_for(commit("logging(led): blink longer"))
    assert len(findings) == 1
    assert "'logging'" in findings[0]


def test_trailing_period_is_rejected():
    findings = gate.findings_for(commit("fix: handle an empty reply."))
    assert len(findings) == 1
    assert "period" in findings[0]


def test_attribution_line_in_the_body_is_rejected():
    body = "- a change\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    findings = gate.findings_for(commit("fix: a change", body))
    assert len(findings) == 1
    assert "attribution" in findings[0]


def test_human_co_author_is_allowed():
    body = "Co-authored-by: Jane Doe <jane@example.com>"
    assert gate.findings_for(commit("fix: a change", body)) == []


def test_root_merge_and_generated_commits_are_not_checked():
    assert gate.findings_for(commit("Initial commit", parents=0)) == []
    assert gate.findings_for(commit("Merge branch 'x' into y", parents=2)) == []
    assert gate.findings_for(commit("merge: bring in the hotfix", parents=2)) == []
    assert gate.findings_for(commit('Revert "feat: a"')) == []
    assert gate.findings_for(commit("fixup! fix: a")) == []


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _commit(repo, name, message):
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message, "--no-verify")


def test_default_range_starts_at_the_last_tag(repo, capsys):
    _commit(repo, "a", "not conventional")
    _git(repo, "tag", "v1.0.0")
    _commit(repo, "b", "fix: handled")
    assert gate.main([]) == 0
    assert "1 commits since v1.0.0" in capsys.readouterr().out


def test_commit_after_the_tag_is_checked(repo, capsys):
    _commit(repo, "a", "chore: start")
    _git(repo, "tag", "v1.0.0")
    _commit(repo, "b", "oops")
    assert gate.main([]) == 1
    assert "oops" in capsys.readouterr().err


def test_explicit_range_and_all(repo):
    _commit(repo, "a", "chore: start")
    _commit(repo, "b", "oops")
    assert gate.main(["HEAD~1..HEAD"]) == 1
    assert gate.main(["--all"]) == 1


def test_no_tag_checks_the_whole_history_but_not_the_root(repo):
    _commit(repo, "a", "oops")
    _commit(repo, "b", "fix: fine")
    assert gate.main([]) == 0
