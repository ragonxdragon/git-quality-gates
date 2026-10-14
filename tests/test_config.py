"""Tests for config.py and bypass.py."""

from __future__ import annotations

import pytest
from conftest import git

from git_quality_gates import bypass, config


def test_defaults_load_without_a_file(tmp_path):
    loaded = config.load(tmp_path)
    assert "feat" in loaded.get("commit_message", "types")
    assert loaded.enabled("comment")


def test_file_overrides_only_the_keys_it_names(tmp_path):
    (tmp_path / config.CONFIG_NAME).write_text('[commit_message]\ntypes = ["feat", "fix"]\n')
    loaded = config.load(tmp_path)
    assert loaded.get("commit_message", "types") == ["feat", "fix"]
    assert loaded.get("regression_test", "guarded_prefixes") == ["src/"]


def test_unknown_table_and_key_are_errors(tmp_path):
    (tmp_path / config.CONFIG_NAME).write_text("[nothing]\nx = 1\n")
    with pytest.raises(config.ConfigError, match="unknown table"):
        config.load(tmp_path)
    (tmp_path / config.CONFIG_NAME).write_text("[license]\nvendor_dir = []\n")
    with pytest.raises(config.ConfigError, match="unknown key 'vendor_dir'"):
        config.load(tmp_path)


def test_wrong_type_is_an_error(tmp_path):
    (tmp_path / config.CONFIG_NAME).write_text('[changelog]\nsync = "yes"\n')
    with pytest.raises(config.ConfigError, match="must be bool"):
        config.load(tmp_path)


def test_unknown_gate_name_is_an_error(tmp_path):
    (tmp_path / config.CONFIG_NAME).write_text('[gates]\ndisabled = ["lint"]\n')
    with pytest.raises(config.ConfigError, match="unknown gate"):
        config.load(tmp_path)


def test_malformed_toml_names_the_file(tmp_path):
    (tmp_path / config.CONFIG_NAME).write_text("[gates\n")
    with pytest.raises(config.ConfigError, match=config.CONFIG_NAME):
        config.load(tmp_path)


def test_bypass_is_off_by_default(repo):
    assert bypass.is_skipped("comment") is False
    assert bypass.log_path() is not None
    assert not bypass.log_path().exists()


def test_bypass_names_one_gate_and_logs_it(repo, monkeypatch, capsys):
    monkeypatch.setenv("GQG_SKIP", "comment, writing")
    monkeypatch.setenv("GQG_SKIP_REASON", "generated\tfile")
    assert bypass.is_skipped("comment") is True
    assert bypass.is_skipped("license") is False
    assert "comment skipped" in capsys.readouterr().err
    fields = bypass.log_path().read_text().splitlines()[0].split("\t")
    assert fields[2] == "comment"
    assert fields[3] == "none"
    assert fields[4] == "generated file"


def test_bypass_all_covers_every_gate(repo, monkeypatch):
    monkeypatch.setenv("GQG_SKIP", "all")
    assert bypass.is_skipped("license") is True
    assert bypass.is_skipped("pre-push") is True
    assert len(bypass.log_path().read_text().splitlines()) == 2


def test_bypass_log_records_head(repo, monkeypatch):
    (repo / "a").write_text("a")
    git(repo, "add", "a")
    git(repo, "commit", "-q", "-m", "chore: a")
    monkeypatch.setenv("GQG_SKIP", "writing")
    bypass.is_skipped("writing")
    head = git(repo, "rev-parse", "--short", "HEAD")
    assert bypass.log_path().read_text().split("\t")[3] == head
