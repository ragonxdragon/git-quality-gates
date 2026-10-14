"""Shared diff reading for the commit-time content gates.

The gates judge only the lines a change adds, so a file with old text in it can
still be edited. Both gates read a unified diff made with -U0 and walk its
added lines through added_lines().
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from collections.abc import Iterator

from . import config

_HUNK = re.compile(r"\+(\d+)")


def use_utf8_output() -> None:
    """Make stdout and stderr write UTF-8 even on a Windows console code page."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


def is_vendored(path: str) -> bool:
    """True for a path under one of the [paths].exclude prefixes."""
    return any(
        path == prefix.rstrip("/") or path.startswith(prefix) for prefix in config.current().exclude
    )


def added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    """Yield (path, new line number, text) for every added line of a -U0 diff."""
    path: str | None = None
    number = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            if target == "/dev/null":
                path = None
            else:
                path = target.removeprefix("b/")
        elif raw.startswith("@@"):
            found = _HUNK.search(raw)
            number = int(found.group(1)) if found else 0
        elif raw.startswith("+") and path is not None:
            yield path, number, raw[1:]
            number += 1


def git_diff(rev_range: str | None) -> str:
    """The staged diff, or the diff of a revision range when one is given."""
    args = ["git", "diff", "-U0", "--no-color", "--diff-filter=ACM"]
    args += [rev_range] if rev_range else ["--cached"]
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", errors="replace"))
        raise SystemExit(2)
    return result.stdout.decode("utf-8", errors="replace")
