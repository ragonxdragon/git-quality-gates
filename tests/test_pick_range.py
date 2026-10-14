"""Tests for pick_range.py, against a real throwaway repository.

Run: uv run pytest
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from git_quality_gates import pick_range

IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def run(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **IDENTITY},
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        run(path, "init", "-q", "-b", "main")
        run(path, "config", "commit.gpgsign", "false")

    def commit(self, name: str) -> str:
        (self.path / name).write_text(name)
        run(self.path, "add", name)
        run(self.path, "commit", "-q", "-m", name)
        return run(self.path, "rev-parse", "HEAD")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=self.path, capture_output=True, text=True, check=False
        )

    def pick(self, event, pr_base="", pr_head="", before="", sha=""):
        return pick_range.pick_range(event, pr_base, pr_head, before, sha, git=self.git)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def test_pull_request_reads_only_its_own_commits(repo):
    base = repo.commit("a")
    run(repo.path, "checkout", "-q", "-b", "topic")
    head = repo.commit("b")
    run(repo.path, "checkout", "-q", "main")
    moved = repo.commit("c")
    assert repo.pick("pull_request", pr_base=moved, pr_head=head) == (f"{base}..{head}", "")


def test_push_reads_before_to_sha_when_before_is_an_ancestor(repo):
    before = repo.commit("a")
    sha = repo.commit("b")
    assert repo.pick("push", before=before, sha=sha) == (f"{before}..{sha}", "")


def test_force_push_skips_the_range(repo):
    repo.commit("a")
    run(repo.path, "checkout", "-q", "-b", "old")
    old_tip = repo.commit("old")
    run(repo.path, "checkout", "-q", "main")
    sha = repo.commit("new")
    rng, notice = repo.pick("push", before=old_tip, sha=sha)
    assert rng == ""
    assert "not an ancestor" in notice


def test_missing_before_object_skips_the_range(repo):
    sha = repo.commit("a")
    rng, notice = repo.pick("push", before="1" * 40, sha=sha)
    assert rng == ""
    assert "not an ancestor" in notice


def test_all_zeros_before_is_a_new_branch(repo):
    sha = repo.commit("a")
    rng, notice = repo.pick("push", before=pick_range.ZEROS, sha=sha)
    assert rng == ""
    assert "new branch" in notice


def test_manual_run_has_no_range(repo):
    sha = repo.commit("a")
    rng, notice = repo.pick("workflow_dispatch", sha=sha)
    assert rng == ""
    assert notice


def test_cli_prints_the_range(repo):
    before = repo.commit("a")
    sha = repo.commit("b")
    out = subprocess.run(
        [sys.executable, pick_range.__file__, "push", "--before", before, "--sha", sha],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == f"{before}..{sha}"


def test_cli_passes_its_arguments_to_pick_range(capsys):
    from git_quality_gates import cli

    assert cli.main(["pick-range", "workflow_dispatch"]) == 0
    out = capsys.readouterr()
    assert out.out == "\n"
    assert "skipped" in out.err
