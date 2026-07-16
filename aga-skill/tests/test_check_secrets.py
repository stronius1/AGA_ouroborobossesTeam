# -*- coding: utf-8 -*-
"""Regression tests for the project-owned, value-safe secret scanner."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import check_secrets  # noqa: E402


def test_documented_manual_secret_entry_is_not_a_populated_assignment() -> None:
    text = "OPENROUTER_" + "API_KEY: передаётся владельцем по закрытому каналу"

    assert check_secrets.scan_text(Path("runbook.md"), text) == []


def test_python_regex_constant_is_not_a_populated_assignment() -> None:
    text = "SECRET_" + "RE = re.compile(\"synthetic pattern\")"

    assert check_secrets.scan_text(Path("scanner.py"), text) == []


def test_populated_assignment_is_reported_without_returning_its_value() -> None:
    value = "synthetic-runtime-credential-value"
    text = "OPENROUTER_" + "API_KEY=" + value

    findings = check_secrets.scan_text(Path("local.env"), text)

    assert findings == ["possible populated secret assignment"]
    assert value not in " ".join(findings)


def test_token_pattern_is_reported_without_returning_token() -> None:
    value = "sk-" + ("Z" * 30)

    findings = check_secrets.scan_text(Path("capture.json"), value)

    assert findings == ["possible API token"]
    assert value not in " ".join(findings)


def test_quoted_regex_like_secret_value_is_still_reported() -> None:
    text = "SECRET_" + 'RE = "re.compile("'

    assert check_secrets.scan_text(Path("scanner.py"), text) == [
        "possible populated secret assignment"
    ]
