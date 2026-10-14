"""Tests for license_allowlist_gate.py.

Run: uv run pytest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from git_quality_gates import config
from git_quality_gates import license_allowlist_gate as gate

MIT_TEXT = "The MIT License (MIT)\n\nPermission is hereby granted, free of charge, to any person"
APACHE_TEXT = "Apache License\nVersion 2.0, January 2004"
LGPL_TEXT = "GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007"
GPL_TEXT = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007"
BSD_TEXT = (
    "Redistribution and use in source and binary forms, with or without modification, "
    "are permitted. Neither the name of the author nor the names of contributors"
)

MIN_REASON = gate.MIN_REASON_CHARS

POLICY = {
    "vendor_dirs": ["vendor"],
    "allowed": ["MIT", "Apache-2.0", "BSD-3-Clause"],
    "banned_prefixes": ["GPL", "AGPL"],
    "lgpl_prefix": "LGPL",
    "declared": {
        "single": {
            "license": "MIT",
            "reason": "Single header with the MIT terms in its comment block.",
            "evidence": {"file": "single.h", "pattern": "MIT License"},
        }
    },
    "exceptions": [],
}


def make_lib(root: Path, name: str, license_text: str | None = None, **files: str) -> Path:
    lib = root / "vendor" / name
    lib.mkdir(parents=True)
    if license_text is not None:
        (lib / "LICENSE").write_text(license_text)
    for filename, body in files.items():
        (lib / filename.replace("__", ".")).write_text(body)
    return lib


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (MIT_TEXT, "MIT"),
        (APACHE_TEXT, "Apache-2.0"),
        (LGPL_TEXT, "LGPL-3.0"),
        (GPL_TEXT, "GPL-3.0"),
        (BSD_TEXT, "BSD-3-Clause"),
        ("GNU AFFERO GENERAL PUBLIC LICENSE Version 3", "AGPL-3.0"),
        ("GNU LESSER GENERAL PUBLIC LICENSE Version 2.1, February 1999", "LGPL-2.1"),
        ("something else entirely", None),
    ],
)
def test_sniff_identifies_license_text(text, expected):
    assert gate.sniff(text) == expected


def test_permissive_library_passes(tmp_path):
    make_lib(tmp_path, "good", MIT_TEXT)
    assert gate.check(tmp_path, POLICY) == []


def test_gpl_library_is_banned(tmp_path):
    make_lib(tmp_path, "bad", GPL_TEXT)
    findings = gate.check(tmp_path, POLICY)
    assert findings == ["bad: GPL-3.0 is banned"]


def test_unlisted_license_fails_until_decided(tmp_path):
    make_lib(tmp_path, "odd", "Mozilla Public License Version 2.0")
    assert "not on the allowed list" in gate.check(tmp_path, POLICY)[0]


def test_lgpl_without_exception_fails(tmp_path):
    make_lib(tmp_path, "driver", LGPL_TEXT)
    findings = gate.check(tmp_path, POLICY)
    assert len(findings) == 1
    assert "not allowed outright" in findings[0]


def test_lgpl_with_exception_passes(tmp_path):
    make_lib(tmp_path, "driver", LGPL_TEXT)
    policy = {
        **POLICY,
        "exceptions": [
            {
                "library": "driver",
                "license": "LGPL-3.0",
                "reason": "Vendored driver kept until a permissive one replaces it.",
            }
        ],
    }
    assert gate.check(tmp_path, policy) == []


def test_exception_needs_a_reason(tmp_path):
    make_lib(tmp_path, "driver", LGPL_TEXT)
    policy = {
        **POLICY,
        "exceptions": [{"library": "driver", "license": "LGPL-3.0", "reason": "needed"}],
    }
    assert "needs a reason" in gate.check(tmp_path, policy)[0]


def test_exception_for_a_different_license_fails(tmp_path):
    make_lib(tmp_path, "driver", LGPL_TEXT)
    policy = {
        **POLICY,
        "exceptions": [
            {"library": "driver", "license": "LGPL-2.1", "reason": "x" * MIN_REASON},
        ],
    }
    assert "exception names LGPL-2.1" in gate.check(tmp_path, policy)[0]


def test_stale_exception_fails(tmp_path):
    make_lib(tmp_path, "driver", MIT_TEXT)
    policy = {
        **POLICY,
        "exceptions": [{"library": "driver", "license": "LGPL-3.0", "reason": "x" * MIN_REASON}],
    }
    assert "stale exception" in gate.check(tmp_path, policy)[0]


def test_manifest_and_license_file_must_agree(tmp_path):
    lib = make_lib(tmp_path, "mixed", GPL_TEXT)
    (lib / "library.json").write_text(json.dumps({"license": "MIT"}))
    assert "disagree" in gate.check(tmp_path, POLICY)[0]


def test_spdx_suffix_spellings_agree(tmp_path):
    lib = make_lib(tmp_path, "driver", LGPL_TEXT)
    (lib / "library.json").write_text(json.dumps({"license": "LGPL-3.0-or-later"}))
    policy = {
        **POLICY,
        "exceptions": [{"library": "driver", "license": "LGPL-3.0", "reason": "x" * MIN_REASON}],
    }
    assert gate.check(tmp_path, policy) == []


def test_manifest_license_alone_is_enough(tmp_path):
    lib = make_lib(tmp_path, "json_only")
    (lib / "library.json").write_text(json.dumps({"license": "Apache-2.0"}))
    assert gate.check(tmp_path, POLICY) == []


def test_or_expression_takes_the_allowed_option(tmp_path):
    lib = make_lib(tmp_path, "dual")
    (lib / "library.json").write_text(json.dumps({"license": "MIT OR GPL-2.0"}))
    assert gate.check(tmp_path, POLICY) == []


def test_and_expression_takes_the_worst_option(tmp_path):
    lib = make_lib(tmp_path, "both")
    (lib / "library.json").write_text(json.dumps({"license": "MIT AND GPL-2.0"}))
    assert gate.check(tmp_path, POLICY) == ["both: MIT AND GPL-2.0 is banned"]


def test_nested_license_file_is_read(tmp_path):
    lib = make_lib(tmp_path, "outer", MIT_TEXT)
    nested = lib / "src" / "inner"
    nested.mkdir(parents=True)
    (nested / "LICENSE").write_text(GPL_TEXT)
    assert "disagree" in gate.check(tmp_path, POLICY)[0]


def test_unrecognized_license_text_is_reported(tmp_path):
    make_lib(tmp_path, "weird", "All rights reserved by nobody in particular.")
    findings = gate.check(tmp_path, POLICY)
    assert "license text not recognized" in findings[0]


def test_library_without_any_license_evidence_fails(tmp_path):
    make_lib(tmp_path, "bare", bare__h="int x;")
    assert "no LICENSE file" in gate.check(tmp_path, POLICY)[0]


def test_declared_single_file_library_needs_its_evidence(tmp_path):
    make_lib(tmp_path, "single", single__h="/* MIT License */")
    assert gate.check(tmp_path, POLICY) == []


def test_declared_entry_fails_when_the_header_does_not_back_it(tmp_path):
    make_lib(tmp_path, "single", single__h="/* all rights reserved */")
    assert "pattern not found" in gate.check(tmp_path, POLICY)[0]


def test_main_reads_the_policy_from_the_root_config(tmp_path, capsys):
    (tmp_path / ".quality-gates.toml").write_text(
        "[license]" + chr(10) + 'vendor_dirs = ["vendor"]' + chr(10)
    )
    make_lib(tmp_path, "good", MIT_TEXT)
    assert gate.main(["--root", str(tmp_path)]) == 0
    make_lib(tmp_path, "bad", GPL_TEXT)
    assert gate.main(["--root", str(tmp_path)]) == 1
    assert "bad: GPL-3.0 is banned" in capsys.readouterr().err


def test_package_json_license_is_read(tmp_path):
    lib = make_lib(tmp_path, "js")
    (lib / "package.json").write_text(json.dumps({"license": "GPL-3.0-only"}))
    assert gate.check(tmp_path, POLICY) == ["js: GPL-3.0-only is banned"]


def test_invalid_manifest_is_reported(tmp_path):
    lib = make_lib(tmp_path, "broken", MIT_TEXT)
    (lib / "package.json").write_text("{not json")
    assert "not valid JSON" in gate.check(tmp_path, POLICY)[0]


def test_default_vendor_dirs_are_searched(tmp_path):
    other = tmp_path / "third_party" / "x"
    other.mkdir(parents=True)
    (other / "LICENSE").write_text(GPL_TEXT)
    policy = config.merge({})["license"]
    assert gate.check(tmp_path, policy) == ["x: GPL-3.0 is banned"]
