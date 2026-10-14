"""AI-attribution lines in commit messages: detect them, or strip them.

One definition serves the commit-message gate, the writing gate and the
prepare-commit-msg hook, so the three agree on what counts as attribution.
"""

from __future__ import annotations

import re

from . import config

#: Tool names that mark a Co-authored-by trailer or a "Generated with" line as attribution.
_TOOLS = r"claude|anthropic|copilot|gpt|chatgpt|cursor|gemini|codex"

_ROBOT = chr(0x1F916)

_BUILTIN = (
    rf"^co-authored-by:.*(?:{_TOOLS})",
    rf"^.*generated (?:with|by) .*(?:{_TOOLS})",
)


def patterns(robot: bool = False) -> re.Pattern[str]:
    """The attribution matcher: built-ins plus [commit_message].extra_attribution_patterns.

    A line carrying the robot emoji is attribution to strip, but not one to block on: the
    writing gate already rejects emoji.
    """
    extra = config.current().get("commit_message", "extra_attribution_patterns")
    joined = "|".join(f"(?:{p})" for p in (*_BUILTIN, *extra, *([_ROBOT] if robot else [])))
    return re.compile(joined, re.IGNORECASE | re.MULTILINE)


def has_attribution(text: str) -> bool:
    return patterns().search(text) is not None


def strip(text: str) -> str:
    """The message without attribution lines, trailing blank lines dropped."""
    matcher = patterns(robot=True)
    kept = [line for line in text.splitlines() if not matcher.search(line)]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept) + ("\n" if kept else "")
