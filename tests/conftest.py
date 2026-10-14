"""Shared fixtures: default configuration, no inherited bypass, and a throwaway git repository."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from git_quality_gates import config


@pytest.fixture(autouse=True)
def _default_config(monkeypatch):
    for name in ("GQG_SKIP", "GQG_SKIP_REASON", "GQG_CMD", "NO_CHANGELOG_SYNC"):
        monkeypatch.delenv(name, raising=False)
    config.set_current(config.with_overrides({}))
    yield
    config.set_current(None)


IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(repo: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, **IDENTITY},
        capture_output=True,
        text=True,
        check=check,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    """An empty repository with the working directory moved into it."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    monkeypatch.chdir(tmp_path)
    config.set_current(config.with_overrides({}, tmp_path))
    return tmp_path


#: How the shell hooks reach the gates under test.
GQG_COMMAND = f"{sys.executable} -m git_quality_gates"
