#!/usr/bin/env python3
"""Commit-message gate: every commit since the last release tag parses as conventional.

    git-quality-gates commit-messages               since the last v* tag
    git-quality-gates commit-messages v1.2.0..HEAD  an explicit range
    git-quality-gates commit-messages --all         the whole history
    git-quality-gates commit-msg FILE               one message file (the commit-msg hook)

The commit-msg hook checks one message as it is written. This gate checks the
range a release covers, because the changelog and the release notes are built
from those subjects and history cannot be relinted once it is pushed.

Each commit must:
  - match type(scope): description, with an optional ! for a breaking change
  - use a type listed in [commit_message].types
  - not end its subject with a period
  - carry no AI-attribution line in its message

Merge commits (subject starting "Merge "), revert and fixup commits git writes
itself, and the root commit are not checked. A shallow clone is refused, since
a range read from one is a range nobody checked.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from . import attribution, bypass, config, regression_test_gate

_SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-zA-Z0-9._/,-]+)\))?!?: (?P<text>\S.*)$")
_GENERATED = ("Merge ", "merge: ", "Revert ", "fixup! ", "squash! ", "amend! ")

_UNIT, _RECORD = "\x1f", "\x1e"


class Commit:
    def __init__(self, sha: str, parents: int, subject: str, body: str) -> None:
        self.sha = sha
        self.parents = parents
        self.subject = subject
        self.body = body


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
        raise SystemExit(2)
    return result.stdout.decode("utf-8", errors="replace")


def is_shallow() -> bool:
    return _git("rev-parse", "--is-shallow-repository").strip() == "true"


def last_tag() -> str | None:
    """The newest release tag reachable from HEAD, or None before the first."""
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
        capture_output=True,
        check=False,
    )
    tag = result.stdout.decode("utf-8", errors="replace").strip()
    return tag if result.returncode == 0 and tag else None


def commits_in(rev_range: str | None) -> list[Commit]:
    args = ["log", f"--format=%H{_UNIT}%P{_UNIT}%s{_UNIT}%b{_RECORD}"]
    if rev_range:
        args.append(rev_range)
    commits = []
    for chunk in _git(*args).split(_RECORD):
        chunk = chunk.strip("\n")
        if chunk:
            sha, parents, subject, body = chunk.split(_UNIT, 3)
            commits.append(Commit(sha, len(parents.split()), subject, body))
    return commits


def findings_for(
    commit: Commit, types: frozenset[str] | None = None, check_attribution: bool = True
) -> list[str]:
    """What is wrong with one commit's message, if anything."""
    if commit.parents == 0 or commit.subject.startswith(_GENERATED):
        return []
    if types is None:
        types = frozenset(config.current().get("commit_message", "types"))
    label = commit.sha[:9]
    out: list[str] = []
    match = _SUBJECT.match(commit.subject)
    if match is None:
        out.append(f"{label} does not parse as type(scope): description: {commit.subject!r}")
    else:
        if match.group("type") not in types:
            out.append(
                f"{label} uses type {match.group('type')!r}; allowed: {', '.join(sorted(types))}"
            )
        if commit.subject.rstrip().endswith("."):
            out.append(f"{label} ends its subject with a period: {commit.subject!r}")
    if check_attribution and attribution.has_attribution(commit.body):
        out.append(f"{label} carries an AI-attribution line")
    return out


#: Types whose commits never reach a changelog.
_UNRECORDED_TYPES = frozenset(("docs", "chore", "style", "test", "ci", "build"))


def check_message_file(message_file: Path) -> int:
    """The commit-msg hook: judge the message git is about to store. Returns an exit code."""
    if not message_file.is_file():
        return 0
    cfg = config.current()
    text = message_file.read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    subject = next((line for line in lines[:1]), "")
    body = "\n".join(lines[1:])
    if not subject.strip() or subject.startswith(_GENERATED):
        return 0

    failed = False
    if cfg.enabled("commit-message") and not bypass.is_skipped("commit-message"):
        check_attribution = cfg.enabled("attribution") and not bypass.is_skipped("attribution")
        findings = findings_for(Commit("-" * 9, 1, subject, body), None, check_attribution)
        for finding in findings:
            sys.stderr.write("[commit-msg] BLOCKED: " + finding[10:] + chr(10))
        failed = bool(findings)
        if any("parse" in finding or "type" in finding for finding in findings):
            sys.stderr.write("[commit-msg] expected: type(scope): description" + chr(10))
    run_regression = cfg.enabled("regression-test") and not bypass.is_skipped("regression-test")
    if run_regression and regression_test_gate.main(["--staged", str(message_file)]) != 0:
        failed = True
    if failed:
        return 1

    # An unrecorded type on a product path is advisory: intent is the author's call.
    if cfg.get("changelog", "sync"):
        found = _SUBJECT.match(subject)
        prefixes = tuple(cfg.get("changelog", "product_paths"))
        if found and found.group("type") in _UNRECORDED_TYPES:
            touched = [p for p in regression_test_gate.staged_paths() if p.startswith(prefixes)]
            if touched:
                sys.stderr.write(
                    f"[commit-msg] NOTE: '{found.group('type')}:' is never recorded in the "
                    f"changelog, but this commit touches {touched[0]}. If the change is "
                    "visible to users, use feat, fix, perf, refactor, revert or security.\n"
                )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("rev_range", nargs="?", help="a revision range such as v1.2.0..HEAD")
    parser.add_argument("--all", action="store_true", help="check the whole history")
    args = parser.parse_args(argv)

    if is_shallow():
        sys.stderr.write(
            "BLOCKED: this is a shallow clone, so the commit range is not the real one. "
            "Check out with fetch-depth 0.\n"
        )
        return 1

    if args.rev_range:
        rev_range, scope = args.rev_range, args.rev_range
    elif args.all:
        rev_range, scope = None, "the whole history"
    else:
        tag = last_tag()
        rev_range = f"{tag}..HEAD" if tag else None
        scope = f"since {tag}" if tag else "the whole history"

    commits = commits_in(rev_range)
    findings = [finding for commit in commits for finding in findings_for(commit)]
    if findings:
        sys.stderr.write("\nBLOCKED: commit messages\n")
        for finding in findings:
            sys.stderr.write(f"  {finding}\n")
        sys.stderr.write(
            "\nFormat: type(scope): description. A breaking change adds ! after the scope.\n"
        )
        return 1
    print(f"[commit-messages] {len(commits)} commits {scope}: every subject parses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
