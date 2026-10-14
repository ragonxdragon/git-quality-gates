"""Configuration: one optional file, .quality-gates.toml, at the repository root.

Every key has a default, so a repository with no file gets working gates. A file
overrides only the keys it names. Unknown tables and keys are an error, so a
misspelled key cannot silently leave a gate on its defaults.
"""

from __future__ import annotations

import copy
import subprocess
import tomllib
from pathlib import Path
from typing import Any

CONFIG_NAME = ".quality-gates.toml"

#: Gates that can be switched off in [gates].disabled and skipped with GQG_SKIP.
GATES = (
    "commit-message",
    "attribution",
    "regression-test",
    "comment",
    "writing",
    "prose",
    "license",
)

DEFAULTS: dict[str, dict[str, Any]] = {
    "gates": {"disabled": []},
    "paths": {
        # Prefixes no content gate reads: vendored code, tool metadata and build output.
        "exclude": [
            "vendor/",
            "third_party/",
            "node_modules/",
            ".git/",
            ".venv/",
            "dist/",
            "build/",
        ],
    },
    "commit_message": {
        "types": [
            "feat",
            "fix",
            "perf",
            "refactor",
            "revert",
            "security",
            "docs",
            "chore",
            "style",
            "test",
            "ci",
            "build",
        ],
        # Case-insensitive regular expressions added to the built-in attribution patterns.
        "extra_attribution_patterns": [],
    },
    "regression_test": {
        "fix_types": ["fix"],
        "guarded_prefixes": ["src/"],
        "test_globs": [
            "test/**",
            "tests/**",
            "**/test_*.py",
            "**/*_test.py",
            "**/*_test.go",
            "**/*.test.*",
            "**/*.spec.*",
            "**/test-*.sh",
        ],
        "min_reason_chars": 20,
    },
    "writing": {
        # Words to reject in addition to the built-in list.
        "extra_vocabulary": [],
    },
    "prose": {
        # Directories whose source comments are spell-checked. Empty means every tracked file.
        "source_roots": [],
        # Term fixes applied to prose, such as {"WiFi" = "Wi-Fi"}.
        "terms": {},
    },
    "license": {
        "vendor_dirs": ["vendor", "third_party"],
        "allowed": ["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib"],
        "banned_prefixes": ["GPL", "AGPL"],
        "lgpl_prefix": "LGPL",
        # {name = {license, reason, evidence = {file, pattern}}} for libraries with no license file.
        "declared": {},
        # [{library, license, reason}] for libraries accepted despite the policy.
        "exceptions": [],
    },
    "changelog": {
        "sync": False,
        "file": "CHANGELOG.md",
        # A commit touching these prefixes gets a note when its type is never recorded.
        "product_paths": ["src/"],
    },
    "hooks": {
        "pre_commit_commands": [],
        "pre_push_commands": [],
    },
}


class ConfigError(ValueError):
    """The configuration file is not valid."""


def repo_root() -> Path:
    """The work tree root, or the working directory outside a repository."""
    found = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    top = found.stdout.strip()
    return Path(top) if found.returncode == 0 and top else Path.cwd()


def merge(overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The defaults with the overrides applied, rejecting unknown tables and keys."""
    merged = copy.deepcopy(DEFAULTS)
    for table, values in overrides.items():
        if table not in DEFAULTS:
            raise ConfigError(f"unknown table [{table}]; known: {', '.join(sorted(DEFAULTS))}")
        if not isinstance(values, dict):
            raise ConfigError(f"[{table}] must be a table")
        for key, value in values.items():
            if key not in DEFAULTS[table]:
                raise ConfigError(
                    f"unknown key {key!r} in [{table}]; known: {', '.join(sorted(DEFAULTS[table]))}"
                )
            expected = type(DEFAULTS[table][key])
            if not isinstance(value, expected):
                raise ConfigError(
                    f"[{table}].{key} must be {expected.__name__}, got {type(value).__name__}"
                )
            merged[table][key] = value
    for name in merged["gates"]["disabled"]:
        if name not in GATES:
            raise ConfigError(f"[gates].disabled names unknown gate {name!r}; known: {GATES}")
    return merged


class Config:
    def __init__(self, values: dict[str, dict[str, Any]], root: Path) -> None:
        self.values = values
        self.root = root

    def get(self, table: str, key: str) -> Any:
        return self.values[table][key]

    def enabled(self, gate: str) -> bool:
        return gate not in self.values["gates"]["disabled"]

    @property
    def exclude(self) -> tuple[str, ...]:
        return tuple(self.values["paths"]["exclude"])


def load(root: Path | None = None) -> Config:
    """Read .quality-gates.toml under root (default: the repository root)."""
    root = root or repo_root()
    path = root / CONFIG_NAME
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    try:
        return Config(merge(data), root)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


_current: Config | None = None


def current() -> Config:
    """The configuration for this process, loaded on first use."""
    global _current
    if _current is None:
        _current = load()
    return _current


def set_current(config: Config | None) -> None:
    """Replace the process configuration; None makes the next current() reload it."""
    global _current
    _current = config


def with_overrides(overrides: dict[str, Any], root: Path | None = None) -> Config:
    """A Config from defaults plus overrides, for tests and embedding."""
    return Config(merge(overrides), root or Path.cwd())
