"""Regression-test gate: a fix that changes guarded source ships with a test.

    git-quality-gates regression --staged .git/COMMIT_EDITMSG
    git-quality-gates regression --range v1.2.0..HEAD

THE RULE
--------
A commit of type fix that touches a guarded path also touches a test, or carries
a No-test trailer that says why no test could fail:

    No-test: the failure only occurs against the live vendor service

A fix without a test holds until somebody refactors past it. The test is what
remembers which behavior was paid for.

WHAT COUNTS AS A TEST
---------------------
Any path matching one of the [regression_test].test_globs patterns. The defaults
cover test/ and tests/ trees, test_*.py, *_test.py, *_test.go, *.test.* and
*.spec.* files, and test-*.sh scripts.

WHAT THE GATE CANNOT CHECK
--------------------------
Whether the test fails against the unfixed code. A person confirms that in
review: write the test, watch it fail, then fix.

THE EXEMPTION
-------------
The reason in a No-test trailer has to be at least [regression_test].min_reason_chars
characters. Behavior that only exists on hardware or against a live service, a
build-flag change and a log-text fix are the usual honest ones. The trailer keeps
the reason in the log next to the commit it excuses, where review reads it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from . import config, gitdiff

#: Conventional Commits subject: type, optional scope, optional breaking marker.
_SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?: (?P<text>.+)$")
_EXEMPTION = re.compile(r"^No-test:[ \t]*(?P<reason>\S.*)$", re.MULTILINE)


def glob_regex(pattern: str) -> re.Pattern[str]:
    """A path glob as a regex: ** crosses directories, * and ? stay inside one."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def is_test_path(path: str) -> bool:
    globs = config.current().get("regression_test", "test_globs")
    return any(glob_regex(pattern).match(path) for pattern in globs)


def subject_of(message: str) -> str:
    for line in message.splitlines():
        if line.strip():
            return line.strip()
    return ""


def judge(message: str, paths: list[str]) -> list[str]:
    """Findings for one commit. An empty list means it satisfies the rule."""
    settings = config.current()
    match = _SUBJECT.match(subject_of(message))
    if match is None or match.group("type") not in settings.get("regression_test", "fix_types"):
        return []
    guarded = tuple(settings.get("regression_test", "guarded_prefixes"))
    guarded_paths = [p for p in paths if p.startswith(guarded) and not gitdiff.is_vendored(p)]
    if not guarded_paths:
        return []
    if any(is_test_path(path) for path in paths):
        return []

    minimum = settings.get("regression_test", "min_reason_chars")
    exemption = _EXEMPTION.search(message)
    if exemption is None:
        return [
            f"is a fix that changes {guarded_paths[0]} and touches no test. Add the test that "
            "fails against the unfixed code, or add a trailer: No-test: <why no test could fail>"
        ]
    reason = exemption.group("reason").strip()
    if len(reason) < minimum:
        return [
            f"carries a No-test trailer with a {len(reason)}-character reason. "
            f"Say why no test could fail, in at least {minimum} characters"
        ]
    return []


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
        raise SystemExit(2)
    return result.stdout.decode("utf-8", errors="replace")


def staged_paths() -> list[str]:
    """The paths in the index. On an amend the index is empty, so read HEAD instead."""
    paths = _git("diff", "--cached", "--name-only").splitlines()
    if paths:
        return paths
    head = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "HEAD"], capture_output=True, check=False
    )
    if head.returncode != 0:
        return []
    return _git("show", "--name-only", "--format=", "HEAD").splitlines()


def check_staged(message_file: Path) -> list[str]:
    if not message_file.is_file():
        raise SystemExit(f"no commit message at {message_file}")
    text = message_file.read_text(encoding="utf-8", errors="replace")
    message = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return [f"this commit {finding}" for finding in judge(message, staged_paths())]


def check_range(rev_range: str) -> list[str]:
    findings: list[str] = []
    for revision in _git("rev-list", "--no-merges", rev_range).split():
        message = _git("log", "-1", "--format=%B", revision)
        paths = _git(
            "diff-tree", "--root", "-r", "--no-commit-id", "--name-only", revision
        ).splitlines()
        subject = subject_of(message)
        findings.extend(
            f"{revision[:9]} {subject[:60]!r} {finding}" for finding in judge(message, paths)
        )
    return findings


def main(argv: list[str]) -> int:
    gitdiff.use_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", type=Path, metavar="MSGFILE", help="the commit being written")
    group.add_argument("--range", dest="rev_range", help="a revision range such as v1.2.0..HEAD")
    args = parser.parse_args(argv)

    findings = check_staged(args.staged) if args.staged else check_range(args.rev_range)
    if findings:
        sys.stderr.write("\nBLOCKED: a fix ships with its test\n")
        for finding in findings:
            sys.stderr.write(f"  {finding}\n")
        sys.stderr.write("\nBypass once with GQG_SKIP=regression-test (logged).\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
