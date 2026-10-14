"""Flag British spellings and common writing faults in Markdown prose and source comments.

Why this exists: a document set written in American English drifts without anyone
noticing. A word like "behaviour" reads fine to whoever wrote it, and a spell checker only
flags it after the document has been rendered and sent.

What it checks, in the order the exit code cares about:

  spelling   British forms with an American equivalent. Only forms that a US
             dictionary actually rejects. "catalogue", "grey", "judgement",
             "acknowledgement" and "dialogue" are valid US variants and are NOT flagged.
  term       Project terminology from [prose].terms, such as WiFi to Wi-Fi.
  grammar    Doubled words, "a"/"an" disagreement, and a small set of wordy phrases with
             a shorter equivalent.
  dash       An em or en dash. Not auto-fixed: the right replacement (comma, colon,
             period, parentheses) depends on the sentence.
  history    Code comments only. A comment that narrates what the code used to do, or
             carries a performance-pass tag, instead of stating what it does now.
             History belongs in the commit message.

Deliberately not checked: passive voice. Many checkers flag it, but in technical writing
"responses are bounded by declared length" is usually clearer than naming an actor that
does not matter. Enforcing it would damage the prose to satisfy a style heuristic.

In Markdown, code is never inspected: fenced blocks, inline spans, link targets and HTML
comments are removed before matching, so `ClientSecure` and
`processRemoteConfiguration` survive untouched.

Source files (.c .cpp .h .hpp .py .sh .ps1 .ini under [prose].source_roots, or anywhere
when that list is empty) are checked in their comments and Python docstrings only, never in code or string
literals. Every check above except the grammar ones applies, plus history.

Paths are confined to the working directory and the repository root. --root DIR adds
another tree, which is how a documentation folder outside the repository is checked.

Usage:
    git-quality-gates prose [paths...]      # default: tracked *.md and source files
    git-quality-gates prose --fix [paths]   # rewrite the unambiguous ones
    git-quality-gates prose --root "/srv/docs" --fix "/srv/docs/guide.md"
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

from . import config, gitdiff

# --- British -> American -----------------------------------------------------------
# Only entries a US dictionary rejects. Variants it accepts are omitted on purpose.
SPELLING = {
    "behaviour": "behavior",
    "behaviours": "behaviors",
    "behavioural": "behavioral",
    "colour": "color",
    "colours": "colors",
    "coloured": "colored",
    "colouring": "coloring",
    "honour": "honor",
    "honours": "honors",
    "honoured": "honored",
    "favour": "favor",
    "favours": "favors",
    "favoured": "favored",
    "favourite": "favorite",
    "labour": "labor",
    "neighbour": "neighbor",
    "neighbours": "neighbors",
    "centre": "center",
    "centres": "centers",
    "centred": "centered",
    "metre": "meter",
    "metres": "meters",
    "theatre": "theater",
    "defence": "defense",
    "offence": "offense",
    "practise": "practice",
    "practised": "practiced",
    "analyse": "analyze",
    "analysed": "analyzed",
    "analyses": "analyzes",
    "analysing": "analyzing",
    "paralyse": "paralyze",
    "programme": "program",
    "programmes": "programs",
    "fulfil": "fulfill",
    "fulfils": "fulfills",
    "fulfilment": "fulfillment",
    "enrol": "enroll",
    "enrols": "enrolls",
    "enrolment": "enrollment",
    "instal": "install",
    "skilful": "skillful",
    "wilful": "willful",
    "travelled": "traveled",
    "travelling": "traveling",
    "traveller": "traveler",
    "modelling": "modeling",
    "modelled": "modeled",
    "cancelled": "canceled",
    "cancelling": "canceling",
    "labelled": "labeled",
    "labelling": "labeling",
    "mislabelled": "mislabeled",
    "signalling": "signaling",
    "signalled": "signaled",
    "marvellous": "marvelous",
    "sizeable": "sizable",
    "storey": "storey",
    "whilst": "while",
    "amongst": "among",
    "learnt": "learned",
    "licence": "license",
    "licences": "licenses",
    "ageing": "aging",
    "manoeuvre": "maneuver",
    "sceptical": "skeptical",
}

# -ise / -isation. Generated so a new stem only needs adding in one place.
ISE_STEMS = [
    "normal",
    "serial",
    "random",
    "synchron",
    "desynchron",
    "unsynchron",
    "optim",
    "recogn",
    "author",
    "unauthor",
    "initial",
    "uninitial",
    "organ",
    "special",
    "critic",
    "summar",
    "prior",
    "categor",
    "custom",
    "central",
    "final",
    "capital",
    "material",
    "energ",
    "apolog",
    "minim",
    "maxim",
    "util",
    "visual",
    "standard",
    "modern",
    "general",
    "steril",
    "emphas",
    "legitim",
    "neutral",
    "stabil",
    "regular",
    "modular",
    "character",
    "partition",
    "synthes",
    "hypothes",
]
for _stem in ISE_STEMS:
    for _end in ("e", "ed", "es", "ing", "ation", "ations", "er", "ers", "able"):
        SPELLING[_stem + "is" + _end] = _stem + "iz" + _end

# --- project terminology -----------------------------------------------------------


def terms() -> dict[str, str]:
    """The term fixes from [prose].terms."""
    return dict(config.current().get("prose", "terms"))


# --- wordiness, the subset that has an unambiguous shorter form ----------
WORDY = {
    "in order to": "to",
    "in order for": "for",
    "due to the fact that": "because",
    "in the event that": "if",
    "at this point in time": "now",
    "for the purpose of": "for",
    "in spite of the fact that": "although",
    "a large number of": "many",
    "the majority of": "most",
    "is able to": "can",
    "are able to": "can",
    "has the ability to": "can",
    "in the process of": "",
    "it should be noted that": "",
}

FENCE = re.compile(r"^[ \t]*```.*?^[ \t]*```", re.DOTALL | re.MULTILINE)
INLINE = re.compile(r"`[^`\n]*`")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
LINK_TARGET = re.compile(r"\]\([^)]*\)")
DOUBLED = re.compile(r"\b(\w+)[ \t]+(\1)(?![\w/-])", re.IGNORECASE)
A_AN = re.compile(r"\b(a)\s+([aeiou]\w+)", re.IGNORECASE)
# Words that take "a" despite an initial vowel letter (a one-off, a unique, a user).
A_AN_OK = re.compile(
    r"^(one|once|uniq|unif|unit|univers|usa|use|user|usual|utili|euro|ubiq)",
    re.IGNORECASE,
)
# No article precedes a function word, so "group A across" and "Group A and B" are a
# label plus its neighbor, not a mis-typed article.
# fmt: off
FUNCTION_WORDS = frozenset([
    "and", "or", "of", "to", "at", "in", "on", "is", "are", "as", "across", "after",
    "before", "above", "below", "over", "under", "within", "without", "into",
    "onto", "through", "per", "via", "about", "against", "among", "between",
    "during",
])
# fmt: on
# Initialisms opening with U are read "you-ess-bee", so they take "a", not "an".
U_INITIALISM = re.compile(r"^U[A-Z0-9]+$")


def _mask(text: str) -> str:
    """Blank out code and link targets, preserving offsets so line numbers stay true."""

    def blank(m):
        return re.sub(r"\S", "\x00", m.group(0))

    for pattern in (FENCE, HTML_COMMENT, INLINE, LINK_TARGET):
        text = pattern.sub(blank, text)
    return text


# --- source files: comments and docstrings only ------------------------------------
SOURCE_SUFFIXES = frozenset({".c", ".cpp", ".h", ".hpp", ".py", ".sh", ".ps1", ".ini"})
# This file and its test spell out the faults they look for.
SELF_EXEMPT = frozenset({"prose_check.py", "test_prose_check.py"})

EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)
DASH = re.compile("[" + EN_DASH + EM_DASH + "]")

# A comment states what the code does. These phrases narrate past behavior, which belongs
# in the commit message instead.
HISTORY = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bformerly\b",
        r"\b(?:it|we|they|this|that|which|code|module|service|library) used to\b",
        r"\b(?:the |an? )?old (?:code|version|implementation|behavior|default|procedure)\b",
        r"\bwas (?:changed|replaced|moved|renamed|rewritten|reverted) (?:to|by|with|from|in)\b",
        r"\bhas been (?:changed|replaced|moved|renamed|rewritten) (?:to|by|with|from)\b",
        r"\bnow (?:uses|does|reads|returns|calls|checks|takes|handles)\b",
        r"\b(?:before this (?:change|fix|commit)|after the fix)\b",
    )
]


def _blank_except(text: str, keep: list[tuple[int, int]]) -> str:
    """Return text with every character outside the keep ranges replaced by NUL.

    Newlines survive so line numbers stay true.
    """
    out = [c if c == "\n" else "\x00" for c in text]
    for start, end in keep:
        out[start:end] = text[start:end]
    return "".join(out)


def _c_comment_ranges(text: str) -> list[tuple[int, int]]:
    """Offsets of the comment bodies in C or C++ source, string literals excluded."""
    ranges = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            ranges.append((i + 2, end))
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end
            ranges.append((i + 2, end))
            i = end + 2
        elif c == '"':
            raw_delim = None
            if i > 0 and text[i - 1] == "R":
                paren = text.find("(", i)
                if paren > 0:
                    raw_delim = ")" + text[i + 1 : paren] + '"'
            if raw_delim:
                end = text.find(raw_delim, i)
                i = n if end < 0 else end + len(raw_delim)
            else:
                i += 1
                while i < n and text[i] != '"' and text[i] != "\n":
                    i += 2 if text[i] == "\\" else 1
                i += 1
        elif c == "'" and not (i > 0 and text[i - 1].isalnum()):
            i += 1
            while i < n and text[i] != "'" and text[i] != "\n":
                i += 2 if text[i] == "\\" else 1
            i += 1
        else:
            i += 1
    return ranges


def _py_comment_ranges(text: str) -> list[tuple[int, int]]:
    """Offsets of the comments and docstrings in Python source."""
    starts = [0]
    for line in text.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    ranges = []
    try:
        tree = ast.parse(text)
        doc_rows = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    doc_rows.add(body[0].value.lineno)
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            row, col = tok.start
            if tok.type == tokenize.COMMENT:
                ranges.append((starts[row - 1] + col + 1, starts[row - 1] + col + len(tok.string)))
            elif tok.type == tokenize.STRING and row in doc_rows:
                erow, ecol = tok.end
                ranges.append((starts[row - 1] + col, starts[erow - 1] + ecol))
    except (SyntaxError, tokenize.TokenError, ValueError):
        pass
    return ranges


def _line_comment_ranges(text: str, suffix: str) -> list[tuple[int, int]]:
    """Offsets of # comments in shell and PowerShell, and ; or # comments in an ini file."""
    ranges = []
    pos = 0
    for line in text.split("\n"):
        stripped = line.lstrip()
        if suffix == ".ini":
            if stripped[:1] in (";", "#"):
                start = pos + len(line) - len(stripped) + 1
                ranges.append((start, pos + len(line)))
        elif not stripped.startswith("#!"):
            quote = ""
            for i, c in enumerate(line):
                if quote:
                    if c == quote:
                        quote = ""
                elif c in "\"'":
                    quote = c
                elif c == "#" and (i == 0 or line[i - 1] in " \t"):
                    ranges.append((pos + i + 1, pos + len(line)))
                    break
        pos += len(line) + 1
    return ranges


def _comment_mask(text: str, suffix: str) -> str:
    """Blank out everything but the comments, preserving offsets and line numbers."""
    if suffix == ".py":
        ranges = _py_comment_ranges(text)
    elif suffix in (".sh", ".ps1", ".ini"):
        ranges = _line_comment_ranges(text, suffix)
    else:
        ranges = _c_comment_ranges(text)
    return _blank_except(text, ranges)


_ALLOWED_ROOTS: list[Path] = []


def set_allowed_roots(extra=()) -> list[Path]:
    """Fix the directories --fix is permitted to write inside.

    The working directory and the repository root by default, plus whatever --root
    names. Documentation can live in more than one tree, so a fixed single root would
    not do, but an unbounded one means a typo or a pasted path can rewrite a file nobody
    meant to touch.
    """
    global _ALLOWED_ROOTS
    roots = [Path.cwd()]
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if top:
            roots.append(Path(top))
    except Exception:
        pass
    roots.extend(Path(e) for e in extra)
    # Run from the repository root and cwd is the repo root, so deduplicate before the
    # list is quoted back at anyone.
    seen = {}
    for root in roots:
        seen.setdefault(os.path.realpath(root), None)
    _ALLOWED_ROOTS = [Path(r) for r in seen]
    return _ALLOWED_ROOTS


def resolve_target(path: Path) -> Path:
    """Normalize a caller-supplied path and confine it to the allowed roots.

    Resolving once up front also means the reader and the writer cannot end up on
    different files: a relative path, a symlink or a ../ chain is settled before either
    open() runs, and a directory or a device node is rejected rather than read.
    """
    roots = _ALLOWED_ROOTS or set_allowed_roots()
    resolved = Path(os.path.realpath(path))
    if not any(resolved.is_relative_to(root) for root in roots):
        raise ValueError(
            f"{path} resolves outside the allowed roots "
            f"({', '.join(r.as_posix() for r in roots)}); pass --root to widen them"
        )
    if not resolved.is_file():
        raise ValueError(f"not a regular file: {path}")
    return resolved


def check(path: Path):
    target = resolve_target(path)
    with open(target, encoding="utf8", errors="replace", newline="") as fh:
        raw = fh.read()
    suffix = target.suffix.lower()
    if suffix in SOURCE_SUFFIXES:
        if target.name in SELF_EXEMPT:
            return raw, []
        return raw, _scan(_comment_mask(raw, suffix), source=True)
    return raw, _scan(_mask(raw), source=False)


def _scan(masked: str, source: bool):
    """Run the checks over text whose code is already blanked out.

    Markdown gets spelling, terminology, dashes and the grammar checks. Source files get
    spelling, terminology, dashes and history, over their comments alone.
    """
    findings = []

    def add(kind, line, found, suggest, note="", span=None):
        findings.append((kind, line, found, suggest, note, span))

    def line_of(pos):
        return masked.count("\n", 0, pos) + 1

    for word, better in SPELLING.items():
        for m in re.finditer(rf"\b{re.escape(word)}\b", masked, re.IGNORECASE):
            add("spelling", line_of(m.start()), m.group(0), better, span=m.span())
    for word, better in terms().items():
        # Word boundaries only. A hyphen guard would also skip prose compounds such as
        # "guest-WiFi"; identifiers are already out of reach because code is masked and
        # anything like wifi_init or isWiFiConnected has a word character alongside.
        for m in re.finditer(rf"(?<!\w){re.escape(word)}(?!\w)", masked):
            # In source comments a term followed by . ( or :: names an identifier.
            after = masked[m.end() : m.end() + 2]
            if source and (after[:1] in (".", "(") or after == "::"):
                continue
            add("term", line_of(m.start()), m.group(0), better, span=m.span())
    for m in DASH.finditer(masked):
        name = "em dash" if m.group(0) == EM_DASH else "en dash"
        add("dash", line_of(m.start()), name, "comma, colon, period or parentheses")
    if source:
        for pattern in HISTORY:
            for m in pattern.finditer(masked):
                add("history", line_of(m.start()), m.group(0), "state what the code does now")
        return findings
    for phrase, better in WORDY.items():
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", masked, re.IGNORECASE):
            add("grammar", line_of(m.start()), m.group(0), better or "(delete)", "wordy")
    for m in DOUBLED.finditer(masked):
        # "had had" and "that that" are legitimate; everything else doubled is a typo.
        if m.group(1).lower() in ("had", "that"):
            continue
        # A run of equal numbers is a table column, not a stutter: "| 0 | 0 | 0 |".
        if m.group(1).isdigit():
            continue
        # A repeated single capital is an initial or an abbreviated title, as in the
        # journal "A A Case Rep."
        if len(m.group(1)) == 1 and m.group(1).isupper():
            continue
        # "the IT it serves": an all-caps token beside its lowercase homograph is two
        # different words, one of them an acronym or identifier.
        if m.group(1) != m.group(2) and (m.group(1).isupper() or m.group(2).isupper()):
            continue
        add("grammar", line_of(m.start()), m.group(0), m.group(1), "doubled word")
    for m in A_AN.finditer(masked):
        if A_AN_OK.match(m.group(2)) or U_INITIALISM.match(m.group(2)):
            continue
        if m.group(2).lower() in FUNCTION_WORDS:
            continue
        # A capital "A" mid-sentence or after a hyphen is a label, not an article:
        # grades ("graded A as retrieved"), Group A, the "-A engine" part designator.
        if m.group(1) == "A":
            before = masked[: m.start()].rstrip()
            if before and (before[-1].isalnum() or before[-1] == "-"):
                continue
        add("grammar", line_of(m.start()), m.group(0), "an " + m.group(2), "a/an")
    return findings


def fix(raw: str, findings) -> str:
    """Apply the unambiguous corrections, spelling and terminology, at their own offsets.

    Splicing by span is what keeps code safe. Re-running the pattern over the raw text
    would reach the occurrences the scan deliberately masked, and rewrite Client.onEvent
    inside a code span into something that does not exist.
    """
    edits = [f for f in findings if f[0] in ("spelling", "term") and f[5]]
    for _kind, _line, found, better, _note, (start, end) in sorted(edits, key=lambda f: -f[5][0]):
        if found.isupper():
            better = better.upper()
        elif found[:1].isupper():
            better = better[:1].upper() + better[1:]
        raw = raw[:start] + better + raw[end:]
    return raw


def is_checked(path: str) -> bool:
    """True for a Markdown file, or a source file under [prose].source_roots, not vendored."""
    if gitdiff.is_vendored(path):
        return False
    suffix = Path(path).suffix.lower()
    if suffix == ".md":
        return True
    roots = tuple(config.current().get("prose", "source_roots"))
    return suffix in SOURCE_SUFFIXES and (not roots or path.startswith(roots))


def tracked_files():
    """Tracked Markdown, plus the source files whose comments are checked."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except Exception:
        return []
    return [Path(p) for p in out if is_checked(p)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--fix", action="store_true", help="rewrite spelling and terminology")
    ap.add_argument(
        "--root",
        action="append",
        default=[],
        metavar="DIR",
        help="allow paths under DIR as well as the working directory and repo root",
    )
    args = ap.parse_args(argv)

    set_allowed_roots(args.root)
    paths = args.paths or tracked_files()
    if not paths:
        print("no files to check")
        return 0

    total = 0
    fixed = 0
    for path in paths:
        if not path.is_file():
            continue
        try:
            raw, findings = check(path)
        except ValueError as exc:
            print(f"refused: {exc}")
            total += 1
            continue
        if not findings:
            continue
        if args.fix:
            new = fix(raw, findings)
            if new != raw:
                with open(resolve_target(path), "w", encoding="utf8", newline="") as fh:
                    fh.write(new)
                n = sum(1 for f in findings if f[5])
                fixed += n
                print(f"fixed {path.as_posix():<52} {n}")
            # Only spelling and terminology carry a span; the rest need a human.
            findings = [f for f in findings if not f[5]]
        if not findings:
            continue
        total += len(findings)
        print(f"\n{path.as_posix()}")
        for kind, line, found, suggest, note, _ in sorted(findings, key=lambda f: f[1])[:40]:
            tail = f"  ({note})" if note else ""
            print(f"  {kind:<8} line {line:<5} {found:<28} -> {suggest}{tail}")

    if args.fix:
        print(f"\n{fixed} corrections applied. {total} judgment calls left.")
        return 0
    if total:
        print(f"\n{total} issue(s). Run --fix to apply the spelling and terminology ones.")
        return 1
    print("prose check clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
