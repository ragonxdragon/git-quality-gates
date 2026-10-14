"""License allowlist gate: every vendored library is under an accepted license.

    git-quality-gates license [--root DIR]

The policy is the [license] table of .quality-gates.toml:

  - GPL and AGPL are banned (banned_prefixes).
  - LGPL is not allowed outright. Every LGPL library is an exception, named in
    the policy with a reason.
  - Everything else has to be on the allowed list. A license nobody has decided
    about fails until someone does.

Each directory under a vendor_dirs entry is one library. For each the gate reads,
in this order:
  1. every LICENSE or COPYING file at any depth, identified by its text
  2. the "license" field of library.json or package.json
  3. for a single-file library with neither, the "declared" entry in the policy,
     which must be backed by a pattern found in the named source file

A library whose files disagree (library.json says MIT, the LICENSE text says
LGPL) fails. An exception that no longer matches a library, or whose license
changed, also fails, so the exception list can only shrink on purpose.

The gate reads files on this machine and sends nothing anywhere.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import config

MANIFESTS = ("library.json", "package.json")
LICENSE_NAMES = re.compile(r"^(?:LICEN[CS]E|COPYING)(?:[.-].*)?$", re.IGNORECASE)
MIN_REASON_CHARS = 20


def sniff(text: str) -> str | None:
    """Identify a license from the text of its LICENSE file."""
    lowered = text.lower()
    if "gnu affero general public license" in lowered:
        return "AGPL-3.0"
    if "gnu lesser general public license" in lowered:
        return "LGPL-2.1" if "version 2.1" in lowered else "LGPL-3.0"
    if "gnu general public license" in lowered:
        return "GPL-2.0" if "version 2," in lowered or "version 2 " in lowered else "GPL-3.0"
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "mozilla public license" in lowered:
        return "MPL-2.0"
    if "permission is hereby granted, free of charge" in lowered:
        return "MIT"
    if "redistribution and use in source and binary forms" in lowered:
        return "BSD-3-Clause" if "neither the name" in lowered else "BSD-2-Clause"
    if "permission to use, copy, modify, and/or distribute" in lowered:
        return "ISC"
    if "this software is provided 'as-is'" in lowered and "zlib" in lowered:
        return "Zlib"
    return None


def canonical(spdx: str) -> str:
    """Drop the -only, -or-later and trailing + suffixes so two spellings compare equal."""
    return re.sub(r"(?:-only|-or-later|\+)$", "", spdx.strip())


def classify(spdx: str, policy: dict) -> str:
    """allowed, lgpl, banned or unknown for one license identifier."""
    if any(spdx.upper().startswith(prefix) for prefix in policy["banned_prefixes"]):
        return "banned"
    if spdx.upper().startswith(policy["lgpl_prefix"]):
        return "lgpl"
    return "allowed" if spdx in policy["allowed"] else "unknown"


def expression_licenses(expression: str) -> list[str]:
    """The identifiers in a simple SPDX expression such as "MIT OR Apache-2.0"."""
    cleaned = expression.replace("(", " ").replace(")", " ")
    return [part for part in re.split(r"\s+(?:OR|AND)\s+", cleaned.strip()) if part]


def library_licenses(lib: Path, policy: dict) -> tuple[dict[str, str], list[str]]:
    """Licenses found for one library as {source: spdx}, plus problems reading it."""
    found: dict[str, str] = {}
    problems: list[str] = []

    for path in sorted(lib.rglob("*")):
        if path.is_file() and LICENSE_NAMES.match(path.name):
            text = path.read_text(encoding="utf-8", errors="replace")
            spdx = sniff(text)
            relative = path.relative_to(lib).as_posix()
            if spdx is None:
                problems.append(f"{relative}: license text not recognized")
            else:
                found[relative] = spdx

    for name in MANIFESTS:
        manifest = lib / name
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{name}: not valid JSON ({exc.msg})")
            continue
        declared = data.get("license") if isinstance(data, dict) else None
        if isinstance(declared, str) and declared.strip():
            found[name] = declared.strip()
    return found, problems


def declared_entry(name: str, lib: Path, policy: dict) -> tuple[str | None, list[str]]:
    """The policy's declared license for a library with no license file, checked."""
    entry = policy.get("declared", {}).get(name)
    if entry is None:
        return None, []
    problems = []
    if len(entry.get("reason", "")) < MIN_REASON_CHARS:
        problems.append(f"declared entry for {name} needs a reason")
    evidence = entry.get("evidence", {})
    source = lib / evidence.get("file", "")
    if not source.is_file():
        problems.append(f"declared entry for {name}: evidence file {evidence.get('file')} missing")
    elif not re.search(evidence.get("pattern", "(?!)"), source.read_text(errors="replace")):
        problems.append(f"declared entry for {name}: pattern not found in {evidence.get('file')}")
    return entry["license"], problems


def judge_expression(expression: str, policy: dict) -> str:
    """allowed, lgpl, banned or unknown for an expression. OR picks the best, AND the worst."""
    kinds = [classify(part, policy) for part in expression_licenses(expression)]
    if not kinds:
        return "unknown"
    if " OR " in expression.upper():
        for kind in ("allowed", "lgpl", "unknown"):
            if kind in kinds:
                return kind
        return "banned"
    for kind in ("banned", "unknown", "lgpl"):
        if kind in kinds:
            return kind
    return "allowed"


def libraries_in(root: Path, policy: dict) -> list[Path]:
    """Every library directory directly under a vendor_dirs entry."""
    found: list[Path] = []
    for vendor in policy.get("vendor_dirs", []):
        base = root / vendor
        if base.is_dir():
            found.extend(sorted(p for p in base.iterdir() if p.is_dir()))
    return found


def check(root: Path, policy: dict) -> list[str]:
    findings: list[str] = []
    libraries = libraries_in(root, policy)
    exceptions = {e["library"]: e for e in policy.get("exceptions", [])}
    used: set[str] = set()

    for lib in libraries:
        name = lib.name
        found, problems = library_licenses(lib, policy)
        findings.extend(f"{name}: {problem}" for problem in problems)

        if not found:
            spdx, declared_problems = declared_entry(name, lib, policy)
            findings.extend(declared_problems)
            if spdx is None:
                findings.append(
                    f"{name}: no LICENSE file, no manifest license and no declared entry "
                    "in the [license] policy"
                )
                continue
            found = {"policy declared": spdx}

        if len({canonical(v) for v in found.values()}) > 1:
            detail = ", ".join(f"{src}={spdx}" for src, spdx in found.items())
            findings.append(f"{name}: license sources disagree ({detail})")
            continue

        spdx = next(iter(found.values()))
        kind = judge_expression(spdx, policy)
        if kind == "banned":
            findings.append(f"{name}: {spdx} is banned")
        elif kind == "unknown":
            findings.append(f"{name}: {spdx} is not on the allowed list; decide it in the policy")
        elif kind == "lgpl":
            exception = exceptions.get(name)
            if exception is None:
                findings.append(
                    f"{name}: {spdx} is not allowed outright; "
                    "list an exception with a reason or replace it"
                )
            elif canonical(exception.get("license", "")) != canonical(spdx):
                findings.append(
                    f"{name}: exception names {exception.get('license')} but the library is {spdx}"
                )
            elif len(exception.get("reason", "")) < MIN_REASON_CHARS:
                findings.append(
                    f"{name}: exception needs a reason of {MIN_REASON_CHARS}+ characters"
                )
            else:
                used.add(name)

    for name in sorted(set(exceptions) - used):
        findings.append(
            f"{name}: stale exception in the [license] policy (library gone or no longer LGPL)"
        )
    return findings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--root", type=Path, default=None, help="repository root")
    args = parser.parse_args(argv)

    root = args.root or config.repo_root()
    policy = config.load(root).values["license"]
    findings = check(root, policy)
    if findings:
        sys.stderr.write("\nBLOCKED: license allowlist\n")
        for finding in findings:
            sys.stderr.write(f"  {finding}\n")
        sys.stderr.write(
            "\nThe policy is the [license] table of .quality-gates.toml. "
            "Bypass once with GQG_SKIP=license (logged).\n"
        )
        return 1
    count = len(libraries_in(root, policy))
    print(f"[license] {count} vendored libraries checked against the allowlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
