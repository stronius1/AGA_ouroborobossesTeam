# -*- coding: utf-8 -*-
"""Secret-free OpenRouter aggregate budget checkpoint tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.openrouter_budget import (  # noqa: E402
    BudgetError,
    _RejectRedirects,
    read_budget,
)


KEY = "sk-or-v1-" + "x" * 32


class _Response:
    status = 200

    def __init__(self, payload: Any) -> None:
        self._raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_arguments: Any) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self._raw[:limit]


def _paths(tmp_path: Path) -> Any:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"OPENROUTER_API_KEY": KEY}), encoding="utf-8")
    settings.chmod(0o600)
    return SimpleNamespace(settings_path=settings)


def test_budget_projection_contains_only_aggregate_numbers(tmp_path: Path) -> None:
    captured: list[Any] = []

    def opener(request: Any, *, timeout: float) -> _Response:
        captured.append((request, timeout))
        return _Response(
            {
                "data": {
                    "label": "private-key-label-must-not-escape",
                    "usage": 3.5,
                    "limit": 50.0,
                    "limit_remaining": 46.5,
                }
            }
        )

    result = read_budget(paths=_paths(tmp_path), opener=opener)
    assert result == {
        "schema": "aga.openrouter-budget/v1",
        "status": "ready",
        "usage_usd": 3.5,
        "limit_usd": 50.0,
        "remaining_usd": 46.5,
        "minimum_remaining_usd": 0.0,
        "credential_retained": False,
        "raw_provider_payload_retained": False,
    }
    serialized = json.dumps(result)
    assert KEY not in serialized
    assert "private-key-label" not in serialized
    assert captured[0][0].get_header("Authorization") == f"Bearer {KEY}"


def test_budget_refuses_non_private_settings(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.settings_path.chmod(0o644)
    with pytest.raises(BudgetError) as caught:
        read_budget(paths=paths, opener=lambda *_args, **_kwargs: None)
    assert caught.value.code == "settings_not_private"
    assert caught.value.status == "not_configured"


def test_budget_stops_when_remaining_is_below_batch_floor(tmp_path: Path) -> None:
    def opener(_request: Any, *, timeout: float) -> _Response:
        del timeout
        return _Response(
            {"data": {"usage": 49.9, "limit": 50.0, "limit_remaining": 0.1}}
        )

    with pytest.raises(BudgetError) as caught:
        read_budget(
            paths=_paths(tmp_path),
            minimum_remaining_usd=1.0,
            opener=opener,
        )
    assert caught.value.code == "remaining_budget_below_minimum"
    assert caught.value.status == "budget_exhausted"


def test_budget_rejects_inconsistent_provider_totals(tmp_path: Path) -> None:
    def opener(_request: Any, *, timeout: float) -> _Response:
        del timeout
        return _Response(
            {"data": {"usage": 3.0, "limit": 50.0, "limit_remaining": 1.0}}
        )

    with pytest.raises(BudgetError) as caught:
        read_budget(paths=_paths(tmp_path), opener=opener)
    assert caught.value.code == "budget_totals_inconsistent"


def test_budget_rejects_redirect_before_forwarding_authorization() -> None:
    handler = _RejectRedirects()
    with pytest.raises(BudgetError) as caught:
        handler.redirect_request(
            object(),
            object(),
            0,
            "Found",
            {},
            "https://attacker.invalid/collect",
        )
    assert caught.value.code == "budget_redirect_rejected"
