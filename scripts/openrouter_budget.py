#!/usr/bin/env python3
"""Read the OpenRouter key budget without exposing the credential.

The credential is loaded only from the isolated, owner-only Ouroboros profile.
The public result is a strict allowlisted numeric projection of
``GET /api/v1/auth/key``; raw headers, key labels and provider payloads are
never printed or persisted.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import ssl
import stat
import sys
from typing import Any, Callable, Mapping, Sequence
import urllib.error
import urllib.request


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.ouroboros_profile import ProfilePaths  # noqa: E402


SCHEMA = "aga.openrouter-budget/v1"
ENDPOINT = "https://openrouter.ai/api/v1/auth/key"
KEY_RE = re.compile(r"sk-or-v1-[A-Za-z0-9_-]{20,4096}")
MAX_RESPONSE_BYTES = 65_536
DEFAULT_TIMEOUT_SECONDS = 20.0


class BudgetError(RuntimeError):
    """A typed error whose message cannot contain provider data or secrets."""

    def __init__(self, code: str, *, status: str = "failed") -> None:
        if status not in {"failed", "not_configured", "budget_exhausted"}:
            raise ValueError("invalid budget error status")
        self.code = code
        self.status = status
        super().__init__(code)


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward the provider credential through an HTTP redirect."""

    def redirect_request(self, *_arguments: Any, **_kwargs: Any) -> None:
        raise BudgetError("budget_redirect_rejected")


def _open_without_redirects(request: Any, *, timeout: float) -> Any:
    # The python.org macOS builds do not always inherit the Keychain CA bundle.
    # Prefer certifi when it is already available, while retaining the verified
    # system trust store as the dependency-free fallback.  Never disable TLS
    # certificate or hostname verification for a request carrying the key.
    try:
        import certifi
    except ImportError:
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.build_opener(
        _RejectRedirects(),
        urllib.request.HTTPSHandler(context=context),
    ).open(
        request,
        timeout=timeout,
    )


def _strict_json_object(raw: bytes) -> Mapping[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise BudgetError("budget_response_too_large")
    try:
        text = raw.decode("utf-8", errors="strict")

        def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise BudgetError("budget_response_invalid") from exc
    if not isinstance(value, Mapping):
        raise BudgetError("budget_response_invalid")
    return value


def _load_private_key(paths: ProfilePaths) -> str:
    settings = paths.settings_path
    try:
        metadata = settings.lstat()
    except OSError as exc:
        raise BudgetError("openrouter_not_configured", status="not_configured") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise BudgetError("settings_not_private", status="not_configured")
    try:
        raw = settings.read_bytes()
    except OSError as exc:
        raise BudgetError("settings_unavailable", status="not_configured") from exc
    if len(raw) > 1_048_576:
        raise BudgetError("settings_invalid", status="not_configured")
    value = _strict_json_object(raw)
    key = value.get("OPENROUTER_API_KEY")
    if not isinstance(key, str) or KEY_RE.fullmatch(key) is None:
        raise BudgetError("openrouter_not_configured", status="not_configured")
    return key


def _finite_nonnegative(value: Any, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise BudgetError(f"budget_{field}_invalid")
    return float(value)


def read_budget(
    *,
    paths: ProfilePaths | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    minimum_remaining_usd: float = 0.0,
    opener: Callable[..., Any] | None = None,
) -> Mapping[str, Any]:
    """Return a secret-free, validated aggregate budget checkpoint."""

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 60.0
    ):
        raise BudgetError("budget_timeout_invalid")
    minimum = _finite_nonnegative(minimum_remaining_usd, "minimum_remaining")
    selected_paths = paths or ProfilePaths.from_environment()
    key = _load_private_key(selected_paths)
    request = urllib.request.Request(
        ENDPOINT,
        method="GET",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "aga-ouroboros-budget-check/1",
        },
    )
    key = ""  # best-effort release of the local credential reference
    selected_opener = opener or _open_without_redirects
    try:
        with selected_opener(request, timeout=float(timeout_seconds)) as response:
            status = int(getattr(response, "status", 0))
            if status != 200:
                raise BudgetError("budget_api_rejected")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except BudgetError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
        raise BudgetError("budget_api_unavailable") from exc
    payload = _strict_json_object(raw)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise BudgetError("budget_response_invalid")
    usage = _finite_nonnegative(data.get("usage"), "usage")
    limit = _finite_nonnegative(data.get("limit"), "limit")
    remaining_value = data.get("limit_remaining")
    if remaining_value is None:
        remaining_value = max(0.0, limit - usage)
    remaining = _finite_nonnegative(remaining_value, "remaining")
    if remaining > limit + 0.000001 or abs((limit - usage) - remaining) > 0.02:
        raise BudgetError("budget_totals_inconsistent")
    result = {
        "schema": SCHEMA,
        "status": "ready" if remaining >= minimum else "budget_exhausted",
        "usage_usd": round(usage, 8),
        "limit_usd": round(limit, 8),
        "remaining_usd": round(remaining, 8),
        "minimum_remaining_usd": round(minimum, 8),
        "credential_retained": False,
        "raw_provider_payload_retained": False,
    }
    if result["status"] != "ready":
        raise BudgetError("remaining_budget_below_minimum", status="budget_exhausted")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--minimum-remaining-usd", type=float, default=0.0)
    return parser


def _emit(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        _emit(
            read_budget(
                timeout_seconds=arguments.timeout,
                minimum_remaining_usd=arguments.minimum_remaining_usd,
            )
        )
        return 0
    except BudgetError as exc:
        _emit({"schema": SCHEMA, "status": exc.status, "code": exc.code})
        return 2 if exc.status == "not_configured" else 4 if exc.status == "budget_exhausted" else 3
    except Exception:
        _emit({"schema": SCHEMA, "status": "failed", "code": "internal_budget_error"})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
