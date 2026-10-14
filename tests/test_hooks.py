"""Tests for the CLI and for the shell hooks, driven the way git drives them.

The shell tests need a POSIX sh and are skipped where there is none.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import GQG_COMMAND, IDENTITY, git

from git_quality_gates import attribution, cli, commit_message_gate, config

DATA = Path(cli.__file__).parent / "data"
needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh")


def sh_env(**extra: str) -> dict[str, str]:
    return {**os.environ, **IDENTITY, "GQG_CMD": GQG_COMMAND, **extra}


def run_sh(repo: Path, script: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(script), *args],
        cwd=repo,
        env=sh_env(**env),
        capture_output=True,
        text=True,
        check=False,
    )


# --- commit-msg ------------------------------------------------------------------------


def message(repo: Path, text: str) -> Path:
    path = repo / "m.txt"
    path.write_text(text)
    return path


def stage(repo: Path, **files: str) -> None:
    for name, body in files.items():
        target = repo / name.replace("__", "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        git(repo, "add", str(target.relative_to(repo)))


def test_conventional_message_passes(repo):
    assert commit_message_gate.check_message_file(message(repo, "feat(a): add a\n\n- add a\n")) == 0


def test_non_conventional_subject_blocks(repo, capsys):
    assert commit_message_gate.check_message_file(message(repo, "fixed the thing\n")) == 1
    assert "does not parse" in capsys.readouterr().err


def test_attribution_trailer_blocks(repo):
    text = "feat(a): x\n\n- x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
    assert commit_message_gate.check_message_file(message(repo, text)) == 1


def test_comment_lines_are_not_part_of_the_message(repo):
    text = "feat(a): x\n\n# Co-Authored-By: Claude <noreply@anthropic.com>\n"
    assert commit_message_gate.check_message_file(message(repo, text)) == 0


def test_generated_and_empty_subjects_are_left_alone(repo):
    assert commit_message_gate.check_message_file(message(repo, "Merge branch 'x'\n")) == 0
    assert commit_message_gate.check_message_file(message(repo, "# only a comment\n")) == 0


def test_fix_on_guarded_source_needs_a_test(repo):
    stage(repo, src__c_py="c\n")
    path = message(repo, "fix(c): handle an empty reply\n\n- return early\n")
    assert commit_message_gate.check_message_file(path) == 1

    path = message(
        repo, "fix(c): handle an empty reply\n\nNo-test: only reachable on the live server\n"
    )
    assert commit_message_gate.check_message_file(path) == 0


def test_fix_with_a_staged_test_passes(repo):
    stage(repo, src__c_py="c\n", tests__test_c_py="t\n")
    assert commit_message_gate.check_message_file(message(repo, "fix(c): handle empty\n")) == 0


def test_amend_reads_head_when_nothing_is_staged(repo):
    stage(repo, src__c_py="c\n")
    git(repo, "commit", "-q", "-m", "chore: seed", "--no-verify")
    path = message(repo, "fix(c): handle an empty reply\n\n- return early\n")
    assert commit_message_gate.check_message_file(path) == 1


def test_bypass_skips_the_gate_and_logs(repo, monkeypatch):
    monkeypatch.setenv("GQG_SKIP", "commit-message")
    monkeypatch.setenv("GQG_SKIP_REASON", "imported history")
    assert commit_message_gate.check_message_file(message(repo, "fixed the thing\n")) == 0
    assert "commit-message" in (repo / ".git" / "quality-gates-bypass.log").read_text()


def test_disabled_gate_is_not_run(repo):
    config.set_current(config.with_overrides({"gates": {"disabled": ["commit-message"]}}, repo))
    assert commit_message_gate.check_message_file(message(repo, "fixed the thing\n")) == 0


def test_changelog_note_for_an_unrecorded_type_on_product_paths(repo, capsys):
    config.set_current(config.with_overrides({"changelog": {"sync": True}}, repo))
    stage(repo, src__a_py="a\n")
    assert commit_message_gate.check_message_file(message(repo, "ci(a): add a\n")) == 0
    assert "never recorded" in capsys.readouterr().err


def test_configured_types_replace_the_defaults(repo):
    config.set_current(config.with_overrides({"commit_message": {"types": ["feat"]}}, repo))
    assert commit_message_gate.check_message_file(message(repo, "fix: a\n")) == 1


# --- prepare-commit-msg ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("fix: a\n\n- retry after 5 s\n", "fix: a\n\n- retry after 5 s\n"),
        (
            "feat: a\n\n- b\n\nCo-Authored-By: Claude Sonnet <noreply@anthropic.com>\n",
            "feat: a\n\n- b\n",
        ),
        ("fix: a\n\nco-authored-by: claude <x@y.z>\n", "fix: a\n"),
        (
            "fix: a\n\nCo-authored-by: Jane Doe <jane@example.com>\n",
            "fix: a\n\nCo-authored-by: Jane Doe <jane@example.com>\n",
        ),
        ("docs: a\n\nGenerated with Claude Code\n", "docs: a\n"),
        ("docs: a\n\n" + chr(0x1F916) + " built by a tool\n", "docs: a\n"),
        (
            "fix: a\n\n# git comment\nCo-Authored-By: Claude <n@a.com>\n",
            "fix: a\n\n# git comment\n",
        ),
        ("Co-Authored-By: Claude <noreply@anthropic.com>\n", ""),
    ],
)
def test_attribution_is_stripped(text, want):
    assert attribution.strip(text) == want


def test_extra_attribution_pattern_is_honored():
    config.set_current(
        config.with_overrides(
            {"commit_message": {"extra_attribution_patterns": ["^drafted by bot"]}}
        )
    )
    assert attribution.has_attribution("fix: a\n\nDrafted by bot v2\n")


def test_prepare_commit_msg_rewrites_the_file(repo):
    path = message(repo, "feat: a\n\n- b\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n")
    assert cli.main(["prepare-commit-msg", str(path)]) == 0
    assert path.read_text() == "feat: a\n\n- b\n"
    assert cli.main(["prepare-commit-msg", str(repo / "missing")]) == 0


@needs_sh
def test_prepare_commit_msg_hook(repo):
    path = message(repo, "feat: a\n\nGenerated with Claude Code\n")
    result = run_sh(repo, DATA / "hooks" / "prepare-commit-msg", str(path))
    assert result.returncode == 0
    assert path.read_text() == "feat: a\n"


# --- installer and hooks end to end ---------------------------------------------------


@needs_sh
def test_installer_installs_and_uninstalls(repo):
    installer = DATA / "install-hooks.sh"
    result = run_sh(repo, installer)
    assert result.returncode == 0, result.stderr
    hooks = repo / ".git" / "hooks"
    for name in ("pre-commit", "commit-msg", "prepare-commit-msg", "pre-push", "post-commit"):
        assert "managed by git-quality-gates" in (hooks / name).read_text()
    assert run_sh(repo, installer, "--uninstall").returncode == 0
    assert not (hooks / "commit-msg").exists()


@needs_sh
def test_installer_keeps_a_foreign_hook_unless_forced(repo):
    hook = repo / ".git" / "hooks" / "commit-msg"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n")
    installer = DATA / "install-hooks.sh"
    result = run_sh(repo, installer)
    assert "skipped commit-msg" in result.stderr
    assert "echo mine" in hook.read_text()
    run_sh(repo, installer, "--force")
    assert "managed by git-quality-gates" in hook.read_text()
    assert "echo mine" in (hook.parent / "commit-msg.orig").read_text()
    run_sh(repo, installer, "--uninstall")
    assert "echo mine" in hook.read_text()


@needs_sh
def test_installed_hooks_gate_a_real_commit(repo):
    run_sh(repo, DATA / "install-hooks.sh")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")

    bad = subprocess.run(
        ["git", "commit", "-m", "added a file"],
        cwd=repo,
        env=sh_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode != 0
    assert "does not parse" in bad.stderr

    good = subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "feat: add a file\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
        ],
        cwd=repo,
        env=sh_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert good.returncode == 0, good.stderr
    assert "Claude" not in git(repo, "log", "-1", "--format=%B")


@needs_sh
def test_pre_commit_blocks_a_dash_and_the_bypass_is_logged(repo):
    run_sh(repo, DATA / "install-hooks.sh")
    (repo / "notes.md").write_text(f"One {chr(0x2014)} two.\n", encoding="utf-8")
    git(repo, "add", "notes.md")
    blocked = subprocess.run(
        ["git", "commit", "-m", "docs: add notes"],
        cwd=repo,
        env=sh_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode != 0
    assert "em or en dash" in blocked.stderr

    allowed = subprocess.run(
        ["git", "commit", "-m", "docs: add notes"],
        cwd=repo,
        env=sh_env(GQG_SKIP="writing,prose", GQG_SKIP_REASON="quoted source text"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert allowed.returncode == 0, allowed.stderr
    log = (repo / ".git" / "quality-gates-bypass.log").read_text()
    assert "\twriting\t" in log
    assert "quoted source text" in log


@needs_sh
def test_hook_without_the_tool_installed_warns_and_allows(repo, monkeypatch):
    env = {k: v for k, v in sh_env().items() if k != "GQG_CMD"}
    env["PATH"] = (
        str(Path(shutil.which("sh")).parent) + os.pathsep + str(Path(shutil.which("git")).parent)
    )
    result = subprocess.run(
        ["sh", str(DATA / "hooks" / "commit-msg"), "m.txt"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "not installed" in result.stderr


@needs_sh
def test_pre_push_runs_configured_commands(repo):
    python = sys.executable.replace(chr(92), "/")
    cmd = f"{python} -c 'raise SystemExit(3)'"
    (repo / ".quality-gates.toml").write_text(f'[hooks]\npre_push_commands = ["{cmd}"]\n')
    config.set_current(config.load(repo))
    result = run_sh(repo, DATA / "hooks" / "pre-push")
    assert result.returncode == 1
    assert "exited 3" in result.stderr
    assert run_sh(repo, DATA / "hooks" / "pre-push", GQG_SKIP="pre-push").returncode == 0


# --- post-commit and the changelog script ---------------------------------------------

CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n### Fixed\n\n### Changed\n"


def changelog_repo(repo: Path) -> None:
    (repo / ".quality-gates.toml").write_text("[changelog]\nsync = true\n")
    (repo / "CHANGELOG.md").write_text(CHANGELOG)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: seed", "--no-verify")


@needs_sh
def test_changelog_script_selftest():
    result = subprocess.run(
        ["sh", str(DATA / "changelog-sync.sh"), "--selftest"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "OK" in result.stdout


@needs_sh
def test_post_commit_keeps_a_pathspec_scope_and_folds_the_entry(repo):
    changelog_repo(repo)
    (repo / "src").mkdir()
    (repo / "src" / "one.c").write_text("1")
    (repo / "src" / "two.c").write_text("2")
    git(repo, "add", "src/one.c", "src/two.c")
    git(repo, "commit", "-q", "--no-verify", "-m", "fix(one): only one", "--", "src/one.c")
    result = run_sh(repo, DATA / "hooks" / "post-commit")
    assert result.returncode == 0, result.stderr
    in_commit = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert "src/two.c" not in in_commit
    assert "CHANGELOG.md" in in_commit
    assert "- only one" in (repo / "CHANGELOG.md").read_text().splitlines()
    assert "src/two.c" in git(repo, "diff", "--cached", "--name-only")


@needs_sh
def test_post_commit_leaves_unrecorded_types_alone_and_says_so(repo):
    changelog_repo(repo)
    (repo / "three.md").write_text("3")
    git(repo, "add", "three.md")
    git(repo, "commit", "-q", "--no-verify", "-m", "docs(three): add three")
    before = git(repo, "rev-parse", "HEAD")
    result = run_sh(repo, DATA / "hooks" / "post-commit")
    assert git(repo, "rev-parse", "HEAD") == before
    assert "is not recorded" in result.stdout


@needs_sh
def test_post_commit_opt_out_and_default_off(repo):
    changelog_repo(repo)
    (repo / "four.c").write_text("4")
    git(repo, "add", "four.c")
    git(repo, "commit", "-q", "--no-verify", "-m", "fix(four): add four")
    before = git(repo, "rev-parse", "HEAD")
    run_sh(repo, DATA / "hooks" / "post-commit", NO_CHANGELOG_SYNC="1")
    assert git(repo, "rev-parse", "HEAD") == before

    (repo / ".quality-gates.toml").write_text("[changelog]\nsync = false\n")
    run_sh(repo, DATA / "hooks" / "post-commit")
    assert git(repo, "rev-parse", "HEAD") == before


# --- CLI -------------------------------------------------------------------------------


def test_init_writes_a_config_that_loads_and_refuses_to_overwrite(repo, capsys):
    assert cli.main(["init"]) == 0
    written = repo / config.CONFIG_NAME
    assert config.load(repo).get("regression_test", "min_reason_chars") == 20
    assert written.read_text().startswith("# .quality-gates.toml")
    assert cli.main(["init"]) == 1


def test_config_command_prints_values(repo, capsys):
    assert cli.main(["config", "changelog.sync"]) == 0
    assert capsys.readouterr().out.strip() == "false"
    assert cli.main(["config", "changelog.file"]) == 0
    assert capsys.readouterr().out.strip() == "CHANGELOG.md"
    assert cli.main(["config", "nothing.here"]) == 2


def test_unknown_command_prints_usage(capsys):
    assert cli.main(["frobnicate"]) == 2
    assert "usage:" in capsys.readouterr().err
    assert cli.main([]) == 0


def test_disabled_and_bypassed_gate_commands_return_zero(repo, monkeypatch):
    stage(repo, **{"a.md": f"x {chr(0x2014)} y\n"})
    assert cli.main(["writing"]) == 1
    monkeypatch.setenv("GQG_SKIP", "writing")
    assert cli.main(["writing"]) == 0
    monkeypatch.delenv("GQG_SKIP")
    config.set_current(config.with_overrides({"gates": {"disabled": ["writing"]}}, repo))
    assert cli.main(["writing"]) == 0


def test_bad_config_is_reported(repo, capsys, monkeypatch):
    (repo / config.CONFIG_NAME).write_text("[nope]\n")
    config.set_current(None)
    assert cli.main(["comment"]) == 2
    assert "configuration error" in capsys.readouterr().err


def test_pre_commit_runs_every_gate(repo, capsys):
    stage(repo, **{"a.md": f"x {chr(0x2014)} y behaviour\n"})
    assert cli.main(["pre-commit"]) == 1
    err = capsys.readouterr()
    assert "em or en dash" in err.err
    assert "behaviour" in err.out


def test_pre_commit_checks_license_when_the_vendor_tree_changes(repo, capsys):
    stage(repo, vendor__bad__LICENSE="GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n")
    assert cli.main(["pre-commit"]) == 1
    assert "GPL-3.0 is banned" in capsys.readouterr().err


def test_message_file_outside_the_repository_is_refused(repo, tmp_path_factory, capsys):
    outside = tmp_path_factory.mktemp("elsewhere") / "m.txt"
    outside.write_text("fixed it\n")
    assert cli.main(["commit-msg", str(outside)]) == 2
    assert "refused" in capsys.readouterr().err
    assert cli.main(["prepare-commit-msg", str(outside)]) == 2
