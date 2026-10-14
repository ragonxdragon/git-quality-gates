"""Deliberate bypass of a gate, with a log line for every use.

    GQG_SKIP=comment,writing git commit ...        skip the named gates
    GQG_SKIP=all GQG_SKIP_REASON="why" git commit  skip every gate

A skipped gate prints a notice on stderr and appends one tab-separated line to
quality-gates-bypass.log inside the git directory: UTC time, user, gate, HEAD,
and the reason from GQG_SKIP_REASON. The log is local to the clone and is never
committed. git commit --no-verify skips the hooks themselves and cannot be
logged, which is why CI runs the same gates over the pushed commits.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

LOG_NAME = "quality-gates-bypass.log"


def requested() -> set[str]:
    return {part.strip() for part in os.environ.get("GQG_SKIP", "").split(",") if part.strip()}


def _git_out(*args: str) -> str:
    found = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return found.stdout.strip() if found.returncode == 0 else ""


def log_path() -> Path | None:
    path = _git_out("rev-parse", "--git-path", LOG_NAME)
    return Path(path) if path else None


def is_skipped(gate: str) -> bool:
    """True when the gate is bypassed. Each call that returns True writes one log line."""
    names = requested()
    if gate not in names and "all" not in names:
        return False
    reason = os.environ.get("GQG_SKIP_REASON", "").replace("\t", " ").replace("\n", " ")
    sys.stderr.write(f"[quality-gates] {gate} skipped by GQG_SKIP (logged in {LOG_NAME})\n")
    path = log_path()
    if path is not None:
        try:
            user = getpass.getuser()
        except (KeyError, OSError):
            user = "unknown"
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        head = _git_out("rev-parse", "--short", "HEAD") or "none"
        line = f"{stamp}\t{user}\t{gate}\t{head}\t{reason}"
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            sys.stderr.write(f"[quality-gates] could not write the bypass log: {exc}\n")
    return True
