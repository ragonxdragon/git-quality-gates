"""Comment gate: a comment describes what the code does now, not its past.

    git-quality-gates comment                 staged changes
    git-quality-gates comment --range A..B    a revision range

History belongs in the commit message. A comment that narrates a change ("this
replaces the old retry loop", "we now check the length") is true on the day it
is written and wrong on every day after, and it tells the next reader about code
they cannot see.

The gate reads only the comments on ADDED lines and matches them against the
patterns in RULES. It is regular expressions and nothing else: it runs on this
machine, sends no code anywhere, and gives the same answer every time.

What it cannot see: a comment that restates the code, or one that is simply
unclear. Review owns those.

Covered: // and block comments in C-family, Java, Go, Rust, JavaScript, TypeScript and similar
files, and # comments in Python, shell, Ruby, YAML, PowerShell, TOML and INI. Markdown is prose and belongs to the
humanizer gate. Allow one line by ending it with the token comment-allow.
"""

from __future__ import annotations

import argparse
import re
import sys

from . import gitdiff

#: The gate's own source and test spell out the phrases they reject.
SELF = ("comment_gate.py", "test_comment_gate.py")
ALLOW_TOKEN = "comment-allow"

C_LIKE = (
    ".c", ".cc", ".cpp", ".h", ".hpp", ".ino", ".java", ".kt", ".go", ".rs", ".js", ".mjs",
    ".ts", ".tsx", ".jsx", ".cs", ".swift", ".scala", ".php",
)  # fmt: skip
HASH_LIKE = (".py", ".sh", ".rb", ".yml", ".yaml", ".ps1", ".toml", ".ini", ".tf")

#: A release number, not an IP address or a longer dotted run.
_VERSION = r"(?<![\d.])v?\d{1,2}\.\d+(?:\.\d+)?(?![.\d])"

#: (name, pattern). Each pattern is matched against the comment text only.
RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("narrates earlier behavior", r"\b(?:formerly|originally|at one point)\b"),
        ("narrates earlier behavior", r"\b(?:it|this|we|they|that|which)\s+used to\b"),
        (
            "narrates earlier behavior",
            r"\bpreviously,? (?:this|we|it|was|were|did|had|used|the \w+ (?:was|did|used))\b",
        ),
        (
            "narrates earlier behavior",
            r"\bno longer (?:uses?|calls?|does|checks?|resets?|sends?|reads?|writes?|returns?"
            r"|waits?|retries|blocks?|handles?|needs to)\b",
        ),
        (
            "refers to the old code",
            r"\b(?:the )?(?:old|previous|former|legacy) "
            r"(?:behaviou?r|code|version|implementation|approach|logic|value|name|path)\b",
        ),
        ("narrates a replacement", r"\b(?:this|it) (?:replaces|replaced|supersedes|superseded)\b"),
        (
            "narrates a change",
            r"\bwe (?:now|changed|removed|added|moved|renamed|switched|dropped|fixed)\b",
        ),
        (
            "narrates a change",
            r"\b(?:was|were) (?:changed|renamed|replaced|switched|reverted|fixed)\b(?! by\b)",
        ),
        ("narrates a change", r"\bnow (?:uses|returns|does|calls|checks|handles|sends|reads)\b"),
        (
            "anchored to a change",
            r"\b(?:after|since|before|following) (?:the )?(?:fix|change|refactor|migration|rewrite|port)\b",
        ),
        (
            "anchored to a version",
            rf"\b(?:since|as of|until|prior to|before|after|from) {_VERSION}",
        ),
        ("tracker reference", r"\b(?:fix(?:es|ed)?|closes|resolves) #\d+"),
    )
)


def comment_text(path: str, line: str) -> str | None:
    """The comment part of a source line, or None when the line has no comment."""
    if path.endswith(C_LIKE):
        stripped = line.strip()
        if stripped.startswith(("/*", "*")):
            return stripped.lstrip("/*").strip()
        found = re.search(r"(?<!:)//(.*)$", line)
        return found.group(1) if found else None
    if path.endswith(HASH_LIKE):
        stripped = line.strip()
        if stripped.startswith("#!"):
            return None
        found = re.search(r"(?:^|\s)#(.*)$", line)
        if found:
            return found.group(1)
        if path.endswith(".ini") and stripped.startswith(";"):
            return stripped[1:]
    return None


def findings_for(path: str, number: int, text: str) -> list[tuple[str, int, str, str]]:
    if (
        path.rsplit("/", 1)[-1] in SELF
        or gitdiff.is_vendored(path)
        or text.rstrip().endswith(ALLOW_TOKEN)
    ):
        return []
    comment = comment_text(path, text)
    if not comment:
        return []
    out: list[tuple[str, int, str, str]] = []
    seen: set[str] = set()
    for name, pattern in RULES:
        found = pattern.search(comment)
        if found and name not in seen:
            seen.add(name)
            out.append((path, number, name, f"'{found.group(0)}'"))
    return out


def scan(diff: str) -> list[tuple[str, int, str, str]]:
    found: list[tuple[str, int, str, str]] = []
    for path, number, text in gitdiff.added_lines(diff):
        found.extend(findings_for(path, number, text))
    return found


def main(argv: list[str]) -> int:
    gitdiff.use_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--range", dest="rev_range", help="a revision range such as A..B")
    args = parser.parse_args(argv)

    found = scan(gitdiff.git_diff(args.rev_range))
    if not found:
        return 0
    sys.stderr.write("\nBLOCKED: comments that narrate history, added lines only\n")
    for path, number, rule, matched in found:
        sys.stderr.write(f"  {path}:{number}  [{rule}]  {matched}\n")
    sys.stderr.write(
        "\nDescribe what the code does now and put the history in the commit message.\n"
        f"End a line with {ALLOW_TOKEN} to allow it, or bypass once with GQG_SKIP=comment (logged).\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
