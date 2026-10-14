"""Command line entry point: git-quality-gates <command>.

Gate commands run one gate and are what CI calls. Hook commands (pre-commit,
commit-msg, prepare-commit-msg, pre-push) are what the installed git hooks call.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from importlib import resources
from pathlib import Path

from . import (
    attribution,
    bypass,
    comment_gate,
    commit_message_gate,
    config,
    gitdiff,
    humanizer_gate,
    license_allowlist_gate,
    pick_range,
    prose_check,
    regression_test_gate,
)

Main = Callable[[list[str]], int]

#: command name -> (gate name for [gates].disabled and GQG_SKIP, entry point)
GATE_COMMANDS: dict[str, tuple[str, Main]] = {
    "comment": ("comment", comment_gate.main),
    "writing": ("writing", humanizer_gate.main),
    "regression": ("regression-test", regression_test_gate.main),
    "commit-messages": ("commit-message", commit_message_gate.main),
    "license": ("license", license_allowlist_gate.main),
    "prose": ("prose", lambda argv: prose_check.main(argv)),
}

USAGE = """usage: git-quality-gates <command> [options]

gate commands (what CI runs):
  comment [--range A..B]          comments that narrate history
  writing [--range A..B]          dashes, curly quotes, emoji, filler vocabulary
  prose [--fix] [paths]           British spellings, wordy phrases, doubled words
  license [--root DIR]            vendored libraries against the license allowlist
  regression --staged FILE | --range A..B
                                  a fix commit touches a test
  commit-messages [RANGE | --all] every subject parses as a Conventional Commit
  pick-range EVENT ...            choose the commit range for a CI run

setup:
  init                            write a commented .quality-gates.toml
  install [--force|--uninstall]   install the git hooks
  config KEY                      print one setting, such as changelog.sync
  changelog [--file F] [--subject S]
                                  add a bullet to the changelog [Unreleased] section

hook commands (called by the installed hooks):
  pre-commit | commit-msg FILE | prepare-commit-msg FILE | pre-push
"""


def run_gate(command: str, argv: list[str]) -> int:
    """Run one gate command unless it is disabled in the config or bypassed."""
    gate, entry = GATE_COMMANDS[command]
    if not config.current().enabled(gate):
        return 0
    if bypass.is_skipped(gate):
        return 0
    return entry(argv)


def _staged_files() -> list[str]:
    found = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.splitlines()


def _run_commands(commands: list[str], label: str, root: Path) -> int:
    failed = 0
    for command in commands:
        argv = shlex.split(command)
        if not argv:
            continue
        found = subprocess.run(argv, cwd=root, check=False)
        if found.returncode != 0:
            sys.stderr.write(f"[{label}] BLOCKED: `{command}` exited {found.returncode}\n")
            failed = 1
    return failed


def pre_commit() -> int:
    cfg = config.current()
    failed = 0
    for command in ("writing", "comment"):
        failed |= run_gate(command, [])

    staged = _staged_files()
    prefixes = tuple(f"{vendor.strip('/')}/" for vendor in cfg.get("license", "vendor_dirs"))
    if any(path.startswith(prefixes) or path == config.CONFIG_NAME for path in staged):
        failed |= run_gate("license", [])

    prose = [path for path in staged if prose_check.is_checked(path)]
    if prose:
        failed |= run_gate("prose", prose)

    if not bypass.is_skipped("pre-commit-commands"):
        failed |= _run_commands(cfg.get("hooks", "pre_commit_commands"), "pre-commit", cfg.root)
    if failed:
        sys.stderr.write(
            "\n[quality-gates] commit blocked. Fix the lines above, or bypass one gate with "
            "GQG_SKIP=<gate> (logged).\n"
        )
        return 1
    return 0


def pre_push() -> int:
    cfg = config.current()
    if bypass.is_skipped("pre-push"):
        return 0
    if _run_commands(cfg.get("hooks", "pre_push_commands"), "pre-push", cfg.root):
        sys.stderr.write(
            "\n[quality-gates] push blocked. Bypass with GQG_SKIP=pre-push (logged).\n"
        )
        return 1
    return 0


def prepare_commit_msg(message_file: Path) -> int:
    if not message_file.is_file():
        return 0
    if not config.current().enabled("attribution") or bypass.is_skipped("attribution"):
        return 0
    text = message_file.read_text(encoding="utf-8", errors="replace")
    stripped = attribution.strip(text)
    if stripped != text:
        message_file.write_text(stripped, encoding="utf-8", newline="")
    return 0


def _message_file(raw: str) -> Path | None:
    """The commit message file, confined to the work tree and the git directories.

    Git passes .git/COMMIT_EDITMSG. Anything that resolves elsewhere is refused, so the
    hook commands cannot be pointed at an arbitrary file.
    """
    resolved = Path(os.path.realpath(raw))
    roots = [config.repo_root()]
    for flag in ("--absolute-git-dir", "--git-common-dir"):
        found = subprocess.run(
            ["git", "rev-parse", flag], capture_output=True, text=True, check=False
        )
        if found.returncode == 0 and found.stdout.strip():
            roots.append(Path(os.path.realpath(found.stdout.strip())))
    if any(resolved.is_relative_to(Path(os.path.realpath(root))) for root in roots):
        return resolved
    sys.stderr.write(f"refused: {raw} is outside the work tree and the git directory\n")
    return None


def _data(name: str) -> Path:
    return Path(str(resources.files("git_quality_gates").joinpath("data", name)))


def init() -> int:
    target = config.repo_root() / config.CONFIG_NAME
    if target.exists():
        sys.stderr.write(f"{target} already exists; not overwriting it.\n")
        return 1
    shutil.copyfile(_data("quality-gates.example.toml"), target)
    print(f"wrote {target}")
    return 0


def install(argv: list[str]) -> int:
    return subprocess.run(["sh", str(_data("install-hooks.sh")), *argv], check=False).returncode


def changelog(argv: list[str]) -> int:
    cfg = config.current()
    args = list(argv)
    if "--file" not in args:
        args = ["--file", str(cfg.root / cfg.get("changelog", "file")), *args]
    return subprocess.run(["sh", str(_data("changelog-sync.sh")), *args], check=False).returncode


def show_config(key: str) -> int:
    table, _, name = key.partition(".")
    try:
        value = config.current().get(table, name)
    except KeyError:
        sys.stderr.write(f"unknown setting {key!r}\n")
        return 2
    if isinstance(value, bool):
        print("true" if value else "false")
    elif isinstance(value, list):
        print("\n".join(str(item) for item in value))
    else:
        print(value)
    return 0


def main(argv: list[str] | None = None) -> int:
    gitdiff.use_utf8_output()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    command, rest = args[0], args[1:]
    try:
        if command in GATE_COMMANDS:
            return run_gate(command, rest)
        if command == "pick-range":
            return pick_range.main(rest)
        if command == "init":
            return init()
        if command == "install":
            return install(rest)
        if command == "changelog":
            return changelog(rest)
        if command == "config" and len(rest) == 1:
            return show_config(rest[0])
        if command == "pre-commit":
            return pre_commit()
        if command == "pre-push":
            return pre_push()
        if command in ("commit-msg", "prepare-commit-msg") and rest:
            target = _message_file(rest[0])
            if target is None:
                return 2
            if command == "commit-msg":
                return commit_message_gate.check_message_file(target)
            return prepare_commit_msg(target)
    except config.ConfigError as exc:
        sys.stderr.write(f"configuration error: {exc}\n")
        return 2
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
