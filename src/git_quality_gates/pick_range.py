"""Pick the commit range the CI commit gates read.

    python scripts/checks/pick_range.py EVENT --pr-base SHA --pr-head SHA \
        --before SHA --sha SHA

Prints the range on stdout, or an empty line when the run has no range. The
reason a range was skipped goes to stderr as a GitHub notice.

THE RULES
---------
  - pull_request: the commits the pull request adds, merge-base(base, head)..head.
  - push: before..sha, only when before is an ancestor of sha. A force push, a
    history rewrite and a brand-new branch (an all-zeros before) leave a before
    that is not an ancestor, so the range would reach back through history the
    rules did not exist for. The pull request that carried those commits already
    passed the gates.
  - anything else (a manual run): no range.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable

ZEROS = "0" * 40

Git = Callable[..., "subprocess.CompletedProcess[str]"]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def pick_range(
    event: str,
    pr_base: str,
    pr_head: str,
    before: str,
    sha: str,
    git: Git = _git,
) -> tuple[str, str]:
    """Return (range, notice). An empty range means the range gates are skipped."""
    if event == "pull_request":
        found = git("merge-base", pr_base, pr_head)
        if found.returncode != 0 or not found.stdout.strip():
            return "", "No merge base for the pull request; the range gates are skipped."
        return f"{found.stdout.strip()}..{pr_head}", ""

    if event == "push":
        if not before or before == ZEROS:
            return "", (
                "A new branch has no previous tip; the range gates are skipped. "
                "The pull request for its commits ran them."
            )
        if git("merge-base", "--is-ancestor", before, sha).returncode != 0:
            return "", (
                f"The previous tip {before[:12]} is not an ancestor of {sha[:12]} "
                "(force push or rewritten history); the range gates are skipped. "
                "The pull request for these commits ran them."
            )
        return f"{before}..{sha}", ""

    return "", "No commit range for this run; the range gates are skipped."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("event")
    parser.add_argument("--pr-base", default="")
    parser.add_argument("--pr-head", default="")
    parser.add_argument("--before", default="")
    parser.add_argument("--sha", default="")
    args = parser.parse_args(argv)
    rev_range, notice = pick_range(args.event, args.pr_base, args.pr_head, args.before, args.sha)
    if notice:
        sys.stderr.write(f"::notice::{notice}\n")
    sys.stdout.write(rev_range + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
