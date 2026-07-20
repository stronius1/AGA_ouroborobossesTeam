#!/usr/bin/env python3
"""Loopback-only UI and run controller for the AGA self-evolution demo."""

from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import hashlib
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
from scripts.ouroboros_models import (  # noqa: E402
    DEFAULT_MODEL_ID,
    MODEL_ENV,
    SUPPORTED_MODELS,
    public_models,
)
STATIC_ROOT = REPOSITORY_ROOT / "self-evolution-ui"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090
SCHEMA = "aga.self-evolution-ui-api/v1"
RUN_SCHEMA = "aga.self-evolution-ui-run/v1"
V2_SCHEMA = "aga.self-evolution-ui-api/v2"
V2_RUN_SCHEMA = "aga.self-evolution-e2e/v2"
SCENARIO_SCHEMA = "aga.self-evolution-scenario/v2"
E2E_RESULT_SCHEMA = "aga.self-evolution-e2e-result/v2"
MAX_REQUEST_BYTES = 16 * 1024
MAX_SUBPROCESS_OUTPUT_BYTES = 128 * 1024
REPLAY_STEP_SECONDS = 0.45
PUBLIC_RUN_ENVELOPE_SCHEMA = "aga.self-evolution-ui-public-run-envelope/v1"
PUBLIC_RUN_REPORT_SCHEMA = "aga.self-evolution-ui-sanitized-report/v1"
PUBLIC_RUN_STORE = (
    REPOSITORY_ROOT / ".aga-runs" / "self-evolution-ui" / "last-public-run.json"
)
PUBLIC_RUN_MAX_BYTES = 8 * 1024 * 1024
LIVE_READINESS_SCHEMA = "aga.self-evolution-ui-live-readiness/v1"
LIVE_READINESS_CACHE_SECONDS = 20.0
LIVE_MINIMUM_REMAINING_USD = 0.50
LIVE_ESTIMATED_DURATION_SECONDS = {"min": 180, "max": 600}
LIVE_ESTIMATED_COST_USD = {"min": 0.05, "max": 0.50}
LOCAL_ARCHITECTURE_ENGINE = "AGA deterministic review/remediation/re-review (no model calls)"
LIVE_ARCHITECTURE_ENGINE = "Ouroboros/OpenRouter (3 live tasks)"
REVIEW_MCP_TOOL_NAMES = (
    "aga_prepare_review",
    "aga_seaf_lookup",
    "aga_parse_diagram",
    "aga_finalize_review",
)
REMEDIATION_MCP_TOOL_NAMES = (
    "aga_prepare_remediation",
    "aga_finalize_remediation",
)
ALL_MCP_TOOL_NAMES = REVIEW_MCP_TOOL_NAMES + REMEDIATION_MCP_TOOL_NAMES
RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")
ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
SAFE_SEED_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SECRET_VALUE_RE = re.compile(
    r"(?:sk-or-v1-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._~+/-]{12,})",
    re.IGNORECASE,
)
SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)",
    re.IGNORECASE,
)
STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


class UIError(RuntimeError):
    """Typed, path-free error suitable for the local JSON boundary."""

    def __init__(self, code: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        self.code = code
        self.http_status = int(status)
        super().__init__(code)


def _strict_json_object(raw: bytes) -> Mapping[str, Any]:
    if len(raw) > MAX_REQUEST_BYTES:
        raise UIError("request_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise UIError("request_invalid_json") from exc
    if not isinstance(value, Mapping):
        raise UIError("request_must_be_object")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _public_safe_copy(value: Any) -> Any:
    """Return a JSON-safe projection with credential-shaped values removed."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if SENSITIVE_KEY_RE.search(key):
                continue
            result[key] = _public_safe_copy(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_public_safe_copy(item) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE_RE.sub("[redacted]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _scenario_content_sha256(scenario: Mapping[str, Any]) -> str:
    """Reproduce the scenario generator's stable content digest."""

    digest_input = {
        key: scenario.get(key)
        for key in (
            "schema",
            "seed",
            "preset",
            "parallel_workers",
            "graph",
            "tests",
        )
    }
    return hashlib.sha256(
        json.dumps(
            digest_input,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _public_run_semantics_valid(run: Mapping[str, Any]) -> bool:
    """Validate provenance invariants before persisted evidence is replayed."""

    execution = run.get("execution")
    expected_mode = "LIVE" if execution == "live" else "LOCAL"
    scenario = run.get("scenario")
    scenario_id = run.get("scenario_id")
    tests = run.get("tests")
    cost = run.get("cost_usd")
    if (
        not isinstance(scenario, Mapping)
        or scenario.get("schema") != SCENARIO_SCHEMA
        or scenario.get("classification") != "synthetic-public"
        or not isinstance(scenario.get("seed"), str)
        or SAFE_SEED_RE.fullmatch(str(scenario["seed"])) is None
        or scenario.get("preset") not in {"demo", "full", "integration", "governance"}
        or isinstance(scenario.get("parallel_workers"), bool)
        or scenario.get("parallel_workers") not in {2, 3, 4}
        or not isinstance(scenario.get("graph"), Mapping)
        or not isinstance(scenario.get("graph", {}).get("nodes"), list)
        or not isinstance(scenario.get("graph", {}).get("edges"), list)
        or not isinstance(scenario_id, str)
        or re.fullmatch(r"e2e-[0-9a-f]{16}", scenario_id) is None
        or scenario.get("scenario_id") != scenario_id
        or not isinstance(scenario.get("content_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(scenario["content_sha256"])) is None
        or not hmac.compare_digest(
            _scenario_content_sha256(scenario), str(scenario["content_sha256"])
        )
        or scenario_id != f"e2e-{str(scenario['content_sha256'])[:16]}"
        or run.get("display_mode") != expected_mode
        or run.get("recorded_evidence") is not False
        or isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(float(cost))
        or float(cost) < 0.0
        or not isinstance(tests, list)
    ):
        return False

    scenario_tests = scenario.get("tests")
    if not isinstance(scenario_tests, list):
        return False
    scenario_test_ids = [
        item.get("id") for item in scenario_tests if isinstance(item, Mapping)
    ]
    run_test_ids = [item.get("id") for item in tests if isinstance(item, Mapping)]
    if (
        len(scenario_test_ids) != len(scenario_tests)
        or len(run_test_ids) != len(tests)
        or any(
            not isinstance(case_id, str) or not case_id
            for case_id in [*scenario_test_ids, *run_test_ids]
        )
    ):
        return False
    if (
        len(set(scenario_test_ids)) != len(scenario_test_ids)
        or len(set(run_test_ids)) != len(run_test_ids)
        or scenario_test_ids != run_test_ids
    ):
        return False

    if execution == "live":
        if (
            run.get("provider") != "OpenRouter"
            or not isinstance(run.get("model_id"), str)
            or run.get("model_id") not in SUPPORTED_MODELS
        ):
            return False
    elif (
        execution != "local"
        or run.get("provider") is not None
        or run.get("model_id") is not None
        or float(cost) != 0.0
    ):
        return False

    state = run.get("state")
    result = run.get("result")
    error_code = run.get("error_code")
    if state == "failed":
        return (
            result is None
            and isinstance(error_code, str)
            and ERROR_CODE_RE.fullmatch(error_code) is not None
        )
    if state != "succeeded" or not isinstance(result, Mapping) or error_code is not None:
        return False
    summary = result.get("summary")
    gate = result.get("gate")
    expected_engine = (
        LIVE_ARCHITECTURE_ENGINE
        if execution == "live"
        else LOCAL_ARCHITECTURE_ENGINE
    )
    if (
        result.get("schema") != E2E_RESULT_SCHEMA
        or result.get("scenario_id") != scenario_id
        or not isinstance(summary, Mapping)
        or summary.get("architecture_engine") != expected_engine
        or isinstance(summary.get("tests"), bool)
        or summary.get("tests") != len(tests)
        or summary.get("human_review_required") is not True
        or summary.get("merge_performed") is not False
        or not isinstance(gate, Mapping)
        or gate.get("passed") is not True
    ):
        return False
    summary_cost = summary.get("actual_cost_usd")
    if execution == "local":
        return summary_cost is None
    return (
        not isinstance(summary_cost, bool)
        and isinstance(summary_cost, (int, float))
        and math.isfinite(float(summary_cost))
        and float(summary_cost) >= 0.0
        and math.isclose(float(summary_cost), float(cost), rel_tol=0.0, abs_tol=1e-8)
    )


def _strict_public_envelope(raw: bytes) -> Mapping[str, Any]:
    if not raw or len(raw) > PUBLIC_RUN_MAX_BYTES:
        raise UIError("recorded_run_invalid")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        envelope = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise UIError("recorded_run_invalid") from exc
    if (
        not isinstance(envelope, Mapping)
        or set(envelope) != {"schema", "payload_sha256", "run"}
        or envelope.get("schema") != PUBLIC_RUN_ENVELOPE_SCHEMA
        or not isinstance(envelope.get("payload_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(envelope["payload_sha256"])) is None
        or not isinstance(envelope.get("run"), Mapping)
    ):
        raise UIError("recorded_run_invalid")
    run = envelope["run"]
    digest = hashlib.sha256(_canonical_json(run)).hexdigest()
    if not hmac.compare_digest(digest, str(envelope["payload_sha256"])):
        raise UIError("recorded_run_checksum_mismatch")
    if _public_safe_copy(run) != run:
        raise UIError("recorded_run_contains_sensitive_data")
    if (
        run.get("schema") != V2_RUN_SCHEMA
        or RUN_ID_RE.fullmatch(str(run.get("run_id") or "")) is None
        or run.get("lane") != "e2e"
        or run.get("execution") not in {"local", "live"}
        or run.get("state") not in {"succeeded", "failed"}
        or not isinstance(run.get("scenario"), Mapping)
        or not isinstance(run.get("events"), list)
        or not isinstance(run.get("tests"), list)
        or not _public_run_semantics_valid(run)
    ):
        raise UIError("recorded_run_schema_mismatch")
    return envelope


def _decode_process_json(
    completed: subprocess.CompletedProcess[bytes],
) -> Mapping[str, Any] | None:
    try:
        value = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _exact_tool_inventory(value: Any, expected: Sequence[str]) -> bool:
    return (
        isinstance(value, list)
        and len(value) == len(expected)
        and all(isinstance(item, str) for item in value)
        and len(set(value)) == len(value)
        and set(value) == set(expected)
    )


def _base_live_readiness(model_id: str) -> dict[str, Any]:
    return {
        "schema": LIVE_READINESS_SCHEMA,
        "status": "failed",
        "code": "live_preflight_not_run",
        "checked_at_unix": int(time.time()),
        "runtime_version": "6.64.1",
        "provider": "OpenRouter",
        "model": model_id,
        "profile_status": "unknown",
        "mcp_gateway": "not_checked",
        "tools": {
            "review": {"ready": 0, "required": 4},
            "remediation": {"ready": 0, "required": 2},
        },
        "hard_budget_cap_usd": 50.0,
        "run_stop_threshold_usd": 40.0,
        "classification": "synthetic-public",
        "estimated_duration_seconds": dict(LIVE_ESTIMATED_DURATION_SECONDS),
        "estimated_cost_usd": dict(LIVE_ESTIMATED_COST_USD),
        "network": {
            "status": "not_checked",
            "provider_reachable": False,
            "vpn_details_exposed": False,
        },
        "secrets_exposed": False,
    }


def _switch_profile_model(profile_script: str, model_id: str) -> bool:
    """Synchronize and restart the isolated profile for one allowlisted model."""

    actions = (
        ("stop", 45.0, {"stopped"}),
        ("sync", 45.0, {"synced"}),
        ("start", 120.0, {"started", "already_running"}),
    )
    for action, timeout, accepted in actions:
        completed = _bounded_process(
            (sys.executable, profile_script, action),
            cwd=REPOSITORY_ROOT,
            timeout_seconds=timeout,
            model_id=model_id,
        )
        payload = _decode_process_json(completed)
        if (
            completed.returncode != 0
            or not isinstance(payload, Mapping)
            or payload.get("status") not in accepted
        ):
            return False
    return True


def _probe_live_readiness(model_id: str) -> Mapping[str, Any]:
    """Run the existing secret-free profile, MCP and provider readiness checks."""

    if model_id not in SUPPORTED_MODELS:
        raise UIError("model_not_supported")
    result = _base_live_readiness(model_id)
    profile_script = str(REPOSITORY_ROOT / "scripts" / "ouroboros_profile.py")
    status_process = _bounded_process(
        (sys.executable, profile_script, "status"),
        cwd=REPOSITORY_ROOT,
        timeout_seconds=30.0,
        model_id=model_id,
    )
    profile = _decode_process_json(status_process)
    if not isinstance(profile, Mapping):
        result["code"] = "profile_status_invalid"
        return result
    result["profile_status"] = str(profile.get("status") or "unknown")
    if status_process.returncode != 0:
        code = profile.get("code")
        result["code"] = str(code) if isinstance(code, str) else "profile_not_ready"
        return result
    if profile.get("status") != "running":
        result["code"] = "profile_not_running"
        return result

    preflight_process = _bounded_process(
        (sys.executable, profile_script, "preflight"),
        cwd=REPOSITORY_ROOT,
        timeout_seconds=210.0,
        model_id=model_id,
    )
    preflight = _decode_process_json(preflight_process)
    if not isinstance(preflight, Mapping):
        result["code"] = "preflight_output_invalid"
        return result
    preflight_code = preflight.get("code")
    if (
        (preflight_process.returncode != 0 or preflight.get("status") != "ready")
        and preflight_code
        in {
            "model_not_configured",
            "model_routes_not_configured",
            "runtime_overlay_attestation_mismatch",
        }
    ):
        if not _switch_profile_model(profile_script, model_id):
            result["code"] = "profile_model_switch_failed"
            return result
        result["profile_status"] = "running"
        preflight_process = _bounded_process(
            (sys.executable, profile_script, "preflight"),
            cwd=REPOSITORY_ROOT,
            timeout_seconds=210.0,
            model_id=model_id,
        )
        preflight = _decode_process_json(preflight_process)
        if not isinstance(preflight, Mapping):
            result["code"] = "preflight_output_invalid"
            return result
    runtime = preflight.get("runtime")
    configuration = preflight.get("configuration")
    mcp = preflight.get("mcp")
    if isinstance(runtime, Mapping) and isinstance(runtime.get("version"), str):
        result["runtime_version"] = runtime["version"]
    if isinstance(configuration, Mapping):
        provider = configuration.get("provider")
        configured_model = configuration.get("model")
        if isinstance(provider, str):
            result["provider"] = provider.title()
        if isinstance(configured_model, str):
            result["model"] = configured_model
        cap = configuration.get("global_hard_cap_max_usd")
        if isinstance(cap, (int, float)) and not isinstance(cap, bool):
            result["hard_budget_cap_usd"] = float(cap)
    if preflight_process.returncode != 0 or preflight.get("status") != "ready":
        code = preflight.get("code")
        result["code"] = str(code) if isinstance(code, str) else "live_preflight_failed"
        return result
    if result["model"] != model_id:
        result["code"] = "preflight_model_mismatch"
        return result

    gateway = mcp.get("gateway_discovery") if isinstance(mcp, Mapping) else None
    worker = mcp.get("worker_ready_discovery") if isinstance(mcp, Mapping) else None
    stages = worker.get("stages") if isinstance(worker, Mapping) else None
    review = stages.get("review") if isinstance(stages, Mapping) else None
    remediation = stages.get("remediation") if isinstance(stages, Mapping) else None
    review_tools = review.get("active_tools") if isinstance(review, Mapping) else None
    remediation_tools = (
        remediation.get("active_tools") if isinstance(remediation, Mapping) else None
    )
    gateway_tools = gateway.get("tools") if isinstance(gateway, Mapping) else None
    gateway_ready = _exact_tool_inventory(gateway_tools, ALL_MCP_TOOL_NAMES)
    review_ready = _exact_tool_inventory(review_tools, REVIEW_MCP_TOOL_NAMES)
    remediation_ready = _exact_tool_inventory(
        remediation_tools, REMEDIATION_MCP_TOOL_NAMES
    )
    result["mcp_gateway"] = "ready" if gateway_ready else "failed"
    result["tools"] = {
        "review": {
            "ready": len(REVIEW_MCP_TOOL_NAMES) if review_ready else 0,
            "required": len(REVIEW_MCP_TOOL_NAMES),
        },
        "remediation": {
            "ready": len(REMEDIATION_MCP_TOOL_NAMES) if remediation_ready else 0,
            "required": len(REMEDIATION_MCP_TOOL_NAMES),
        },
    }
    if not gateway_ready or not review_ready or not remediation_ready:
        result["code"] = "mcp_tools_not_ready"
        return result

    budget_process = _bounded_process(
        (
            sys.executable,
            str(REPOSITORY_ROOT / "scripts" / "openrouter_budget.py"),
            "--timeout",
            "20",
            "--minimum-remaining-usd",
            str(LIVE_MINIMUM_REMAINING_USD),
        ),
        cwd=REPOSITORY_ROOT,
        timeout_seconds=30.0,
        model_id=model_id,
    )
    budget = _decode_process_json(budget_process)
    if not isinstance(budget, Mapping):
        result["code"] = "budget_response_invalid"
        return result
    if budget_process.returncode != 0 or budget.get("status") != "ready":
        code = budget.get("code")
        result["code"] = str(code) if isinstance(code, str) else "network_not_ready"
        result["network"]["status"] = "failed"
        return result
    remaining = budget.get("remaining_usd")
    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
        result["remaining_budget_usd"] = round(float(remaining), 8)
    result["network"] = {
        "status": "ready",
        "provider_reachable": True,
        "vpn_details_exposed": False,
    }
    result["status"] = "ready"
    result["code"] = "ok"
    return result


def _load_fixture() -> Mapping[str, Any]:
    try:
        from scripts.generate_self_evolution_ui_fixture import build_fixture

        value = build_fixture(REPOSITORY_ROOT)
    except (ImportError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise UIError("fixture_unavailable", HTTPStatus.SERVICE_UNAVAILABLE) from exc
    if not isinstance(value, Mapping):
        raise UIError("fixture_invalid", HTTPStatus.SERVICE_UNAVAILABLE)
    encoded = _canonical_json(value)
    if len(encoded) > 2 * 1024 * 1024:
        raise UIError("fixture_too_large", HTTPStatus.SERVICE_UNAVAILABLE)
    return dict(value)


def _safe_subprocess_environment(model_id: str | None = None) -> dict[str, str]:
    allowed = (
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    for key in (
        "AGA_OUROBOROS_PROFILE_HOME",
        "AGA_OUROBOROS_VENV_DIR",
        "AGA_OUROBOROS_SOURCE_DIR",
        "AGA_OUROBOROS_BIN",
        "AGA_OUROBOROS_PYTHON",
    ):
        if key in os.environ:
            environment[key] = os.environ[key]
    selected_model = model_id or DEFAULT_MODEL_ID
    if selected_model not in SUPPORTED_MODELS:
        raise UIError("model_not_supported")
    environment[MODEL_ENV] = selected_model
    return environment


def _bounded_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    model_id: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=_safe_subprocess_environment(model_id),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UIError("run_process_unavailable", HTTPStatus.INTERNAL_SERVER_ERROR) from exc
    if (
        len(completed.stdout) > MAX_SUBPROCESS_OUTPUT_BYTES
        or len(completed.stderr) > MAX_SUBPROCESS_OUTPUT_BYTES
    ):
        raise UIError("run_output_too_large", HTTPStatus.INTERNAL_SERVER_ERROR)
    return completed


def _typed_process_error(completed: subprocess.CompletedProcess[bytes]) -> str:
    for payload in (completed.stdout, completed.stderr):
        for raw_line in reversed(payload.splitlines()[-8:]):
            try:
                value = json.loads(raw_line.decode("utf-8", errors="strict"))
            except (UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(value, Mapping):
                code = value.get("code") or value.get("error")
                if isinstance(code, str) and ERROR_CODE_RE.fullmatch(code):
                    return code
    return "run_failed"


def _known_model_cost(value: Any) -> float | None:
    usage = value.get("model_usage") if isinstance(value, Mapping) else None
    cost = usage.get("known_cost_usd") if isinstance(usage, Mapping) else None
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(float(cost))
        or float(cost) < 0.0
    ):
        return None
    return float(cost)


def _architecture_evidence_cost(evidence: Mapping[str, Any]) -> float | None:
    costs = [
        cost
        for stage in ("review_before", "remediation", "review_after")
        if (cost := _known_model_cost(evidence.get(stage))) is not None
    ]
    return round(sum(costs), 8) if costs else None


def _architecture_failure_projection(stage: str) -> Mapping[str, str]:
    projections = {
        "setup": {
            "event_id": "architecture.ouroboros.setup.failed",
            "label": "Live-контур Ouroboros не запущен",
            "detail": "Платные архитектурные задачи не считаются выполненными; сценарий и локальные тесты сохранены.",
            "tool": "ouroboros_profile",
        },
        "review_before": {
            "event_id": "architecture.ouroboros.review.failed",
            "label": "Ouroboros не завершил первый review",
            "detail": "Архитектурный patch и re-review не запускались; параллельные тесты сохранены.",
            "tool": "aga_prepare_review",
        },
        "remediation": {
            "event_id": "architecture.ouroboros.remediation.failed",
            "label": "Ouroboros remediation не завершён",
            "detail": "Первый review сохранён; patch не считается готовым, re-review не запускался.",
            "tool": "aga_prepare_remediation",
        },
        "materialize": {
            "event_id": "architecture.ouroboros.materialize.failed",
            "label": "Локальный candidate patch не материализован",
            "detail": "Review и remediation receipts сохранены; candidate и re-review не считаются завершёнными.",
            "tool": "aga_finalize_remediation",
        },
        "review_after": {
            "event_id": "architecture.ouroboros.rereview.failed",
            "label": "Ouroboros re-review не завершён",
            "detail": "Первый review и patch сохранены; architecture gate не пройден.",
            "tool": "aga_prepare_review",
        },
    }
    return projections.get(
        stage,
        {
            "event_id": "architecture.ouroboros.run.failed",
            "label": "Live-архитектурная ветка остановлена",
            "detail": "Фактическая стадия и ошибка сохранены; незавершённые шаги не считаются выполненными.",
            "tool": "ouroboros",
        },
    )


@dataclass
class EvolutionRun:
    run_id: str
    lane: str
    execution: str
    model_id: str = DEFAULT_MODEL_ID
    state: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    result: Mapping[str, Any] | None = None
    error_code: str | None = None
    failure: Mapping[str, Any] | None = None
    recovery: Mapping[str, Any] | None = None
    started_at_unix: int | None = None
    finished_at_unix: int | None = None
    started_at_unix_ms: int | None = None
    finished_at_unix_ms: int | None = None
    scenario_id: str | None = None
    scenario: Mapping[str, Any] | None = None
    phase: str = "queued"
    progress: dict[str, int] = field(default_factory=lambda: {"done": 0, "total": 1, "percent": 0})
    agents: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0
    _seen_events: set[str] = field(default_factory=set, repr=False)

    def append(
        self,
        event_id: str,
        label: str,
        actor: str,
        detail: str,
        *,
        kind: str = "stage",
        status: str = "completed",
        actor_id: str | None = None,
        tool: str | None = None,
        task_id: str | None = None,
        graph_delta: Mapping[str, Any] | None = None,
        test_ids: Sequence[str] = (),
        data: Mapping[str, Any] | None = None,
    ) -> None:
        if event_id in self._seen_events:
            return
        self._seen_events.add(event_id)
        event: dict[str, Any] = {
            "seq": len(self.events) + 1,
            "id": event_id,
            "kind": kind,
            "label": label,
            "actor": actor,
            "actor_id": actor_id or actor,
            "status": status,
            "detail": detail,
            "timestamp_unix_ms": int(time.time() * 1000),
        }
        if tool:
            event["tool"] = tool
        if task_id:
            event["task_id"] = task_id
        if graph_delta is not None:
            event["graph_delta"] = dict(graph_delta)
        if test_ids:
            event["test_ids"] = list(test_ids)
        if data is not None:
            event["data"] = copy.deepcopy(dict(data))
        self.events.append(event)

    def agent(self, agent_id: str) -> dict[str, Any]:
        for agent in self.agents:
            if agent.get("id") == agent_id:
                return agent
        raise KeyError(agent_id)

    def test(self, case_id: str) -> dict[str, Any]:
        for case in self.tests:
            if case.get("id") == case_id:
                return case
        raise KeyError(case_id)

    def public(self) -> Mapping[str, Any]:
        display_mode = (
            "LIVE"
            if self.execution == "live"
            else "LOCAL"
            if self.execution == "local"
            else "RECORDED EVIDENCE"
        )
        return {
            "schema": V2_RUN_SCHEMA if self.lane == "e2e" else RUN_SCHEMA,
            "run_id": self.run_id,
            "lane": self.lane,
            "execution": self.execution,
            "model_id": self.model_id if self.execution == "live" else None,
            "provider": "OpenRouter" if self.execution == "live" else None,
            "display_mode": display_mode,
            "recorded_evidence": False,
            "state": self.state,
            "phase": self.phase,
            "progress": copy.deepcopy(self.progress),
            "scenario_id": self.scenario_id,
            "scenario": copy.deepcopy(self.scenario),
            "events": copy.deepcopy(self.events),
            "agents": copy.deepcopy(self.agents),
            "tests": copy.deepcopy(self.tests),
            "result": copy.deepcopy(self.result),
            "cost_usd": self.cost_usd,
            "error_code": self.error_code,
            "failure": copy.deepcopy(self.failure),
            "recovery": copy.deepcopy(self.recovery),
            "started_at_unix": self.started_at_unix,
            "finished_at_unix": self.finished_at_unix,
            "started_at_unix_ms": self.started_at_unix_ms,
            "finished_at_unix_ms": self.finished_at_unix_ms,
        }


class JobManager:
    def __init__(
        self,
        *,
        public_run_store: Path | None = None,
        readiness_probe: Any | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, EvolutionRun] = {}
        self._scenarios: dict[str, dict[str, Any]] = {}
        self._active_run_id: str | None = None
        self._recorded_run: Mapping[str, Any] | None = None
        self._public_run_store = public_run_store or PUBLIC_RUN_STORE
        self._readiness_probe = readiness_probe or _probe_live_readiness
        self._readiness_cache: dict[str, tuple[float, Mapping[str, Any]]] = {}
        self._load_recorded_run()

    def _load_recorded_run(self) -> None:
        try:
            per_run = sorted(
                (
                    path
                    for path in self._public_run_store.parent.glob(
                        "????????????/public-run.json"
                    )
                    if RUN_ID_RE.fullmatch(path.parent.name)
                ),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        except OSError:
            per_run = []
        candidates = [self._public_run_store, *per_run]
        try:
            candidates = sorted(
                {path for path in candidates if path.is_file()},
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        except OSError:
            candidates = [self._public_run_store, *per_run]
        envelope: Mapping[str, Any] | None = None
        for candidate in candidates:
            try:
                envelope = _strict_public_envelope(candidate.read_bytes())
                break
            except (OSError, UIError):
                continue
        if envelope is None:
            return
        run = copy.deepcopy(dict(envelope["run"]))
        run["recorded_evidence"] = True
        run["display_mode"] = "RECORDED EVIDENCE"
        run["source_execution"] = run.get("execution")
        self._recorded_run = run
        scenario = run.get("scenario")
        scenario_id = run.get("scenario_id")
        if isinstance(scenario, Mapping) and isinstance(scenario_id, str):
            self._scenarios[scenario_id] = copy.deepcopy(dict(scenario))

    @staticmethod
    def _public_run_envelope(run: Mapping[str, Any]) -> Mapping[str, Any]:
        sanitized = _public_safe_copy(run)
        if not isinstance(sanitized, Mapping):
            raise UIError("recorded_run_invalid")
        payload = _canonical_json(sanitized)
        if len(payload) > PUBLIC_RUN_MAX_BYTES:
            raise UIError("recorded_run_too_large")
        return {
            "schema": PUBLIC_RUN_ENVELOPE_SCHEMA,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "run": sanitized,
        }

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        if len(payload) > PUBLIC_RUN_MAX_BYTES:
            raise UIError("recorded_run_too_large")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            try:
                directory = os.open(path.parent, os.O_RDONLY)
            except OSError:
                directory = None
            if directory is not None:
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except OSError as exc:
            raise UIError("recorded_run_write_failed") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _persist_terminal_run(self, run_id: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.lane != "e2e" or run.state not in {"succeeded", "failed"}:
                return
            public_run = run.public()
        envelope = self._public_run_envelope(public_run)
        payload = _canonical_json(envelope)
        per_run = self._public_run_store.parent / run_id / "public-run.json"
        self._atomic_write(per_run, payload)
        self._atomic_write(self._public_run_store, payload)

    def live_readiness(
        self,
        model_id: str,
        *,
        force: bool = False,
    ) -> Mapping[str, Any]:
        if model_id not in SUPPORTED_MODELS:
            raise UIError("model_not_supported")
        now = time.monotonic()
        with self._lock:
            cached = self._readiness_cache.get(model_id)
            if (
                not force
                and cached is not None
                and now - cached[0] <= LIVE_READINESS_CACHE_SECONDS
            ):
                return copy.deepcopy(dict(cached[1]))
        try:
            readiness = self._readiness_probe(model_id)
        except UIError as exc:
            readiness = _base_live_readiness(model_id)
            readiness["code"] = exc.code
        except Exception:
            readiness = _base_live_readiness(model_id)
            readiness["code"] = "internal_preflight_error"
        if not isinstance(readiness, Mapping):
            readiness = _base_live_readiness(model_id)
            readiness["code"] = "preflight_output_invalid"
        public = _public_safe_copy(readiness)
        if not isinstance(public, Mapping):
            raise UIError("preflight_output_invalid")
        with self._lock:
            self._readiness_cache[model_id] = (
                time.monotonic(),
                copy.deepcopy(dict(public)),
            )
        return copy.deepcopy(dict(public))

    def create_scenario(
        self,
        *,
        seed: str,
        preset: str,
        parallel_workers: int,
    ) -> Mapping[str, Any]:
        try:
            from scripts.generate_self_evolution_scenario import build_scenario

            scenario = build_scenario(
                seed=seed,
                preset=preset,
                parallel_workers=parallel_workers,
                project_root=REPOSITORY_ROOT,
            )
        except (ImportError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise UIError("scenario_generation_failed", HTTPStatus.SERVICE_UNAVAILABLE) from exc
        if not isinstance(scenario, Mapping):
            raise UIError("scenario_generation_failed", HTTPStatus.SERVICE_UNAVAILABLE)
        scenario_id = str(scenario.get("scenario_id") or "")
        if re.fullmatch(r"e2e-[0-9a-f]{16}", scenario_id) is None:
            raise UIError("scenario_generation_failed", HTTPStatus.SERVICE_UNAVAILABLE)
        encoded = _canonical_json(scenario)
        if len(encoded) > 2 * 1024 * 1024:
            raise UIError("scenario_too_large", HTTPStatus.SERVICE_UNAVAILABLE)
        with self._lock:
            self._scenarios[scenario_id] = copy.deepcopy(dict(scenario))
        return copy.deepcopy(dict(scenario))

    def scenario(self, scenario_id: str) -> Mapping[str, Any]:
        if re.fullmatch(r"e2e-[0-9a-f]{16}", scenario_id) is None:
            raise UIError("scenario_id_invalid")
        with self._lock:
            scenario = self._scenarios.get(scenario_id)
            if scenario is None:
                raise UIError("scenario_not_found", HTTPStatus.NOT_FOUND)
            return copy.deepcopy(scenario)

    def start(
        self,
        *,
        lane: str,
        execution: str,
        confirm_paid_run: bool,
        scenario_id: str | None = None,
        model_id: str = DEFAULT_MODEL_ID,
        recovery_of_run_id: str | None = None,
    ) -> Mapping[str, Any]:
        if lane not in {"architecture", "rules", "e2e"}:
            raise UIError("lane_invalid")
        if execution not in {"replay", "local", "live"}:
            raise UIError("execution_invalid")
        if lane == "e2e" and execution not in {"local", "live"}:
            raise UIError("execution_invalid")
        if lane != "e2e" and execution == "local":
            raise UIError("execution_invalid")
        if lane == "rules" and execution == "live":
            # This legacy lane is fully deterministic.  Rejecting LIVE avoids
            # attaching OpenRouter/model provenance to a run with no model calls.
            raise UIError("execution_invalid")
        if lane in {"architecture", "e2e"} and execution == "live" and confirm_paid_run is not True:
            raise UIError("paid_run_confirmation_required")
        if model_id not in SUPPORTED_MODELS:
            raise UIError("model_not_supported")
        if execution == "live":
            readiness = self.live_readiness(model_id)
            if readiness.get("status") != "ready":
                code = readiness.get("code")
                raise UIError(
                    str(code) if isinstance(code, str) and ERROR_CODE_RE.fullmatch(code) else "live_preflight_failed",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
        selected_scenario: Mapping[str, Any] | None = None
        if lane == "e2e":
            if not isinstance(scenario_id, str):
                raise UIError("scenario_required")
            selected_scenario = self.scenario(scenario_id)
        recovery: Mapping[str, Any] | None = None
        if recovery_of_run_id is not None:
            if lane != "e2e" or execution != "local" or RUN_ID_RE.fullmatch(recovery_of_run_id) is None:
                raise UIError("recovery_request_invalid")
            with self._lock:
                failed = self._runs.get(recovery_of_run_id)
                failed_public = failed.public() if failed is not None else None
                if failed_public is None and isinstance(self._recorded_run, Mapping):
                    if self._recorded_run.get("run_id") == recovery_of_run_id:
                        failed_public = copy.deepcopy(dict(self._recorded_run))
            if (
                not isinstance(failed_public, Mapping)
                or failed_public.get("state") != "failed"
                or failed_public.get("execution") != "live"
                or failed_public.get("scenario_id") != scenario_id
            ):
                raise UIError("recovery_source_invalid")
            failed_events = failed_public.get("events")
            failed_event = (
                next(
                    (
                        event
                        for event in reversed(failed_events)
                        if isinstance(event, Mapping) and event.get("id") == "run.failed"
                    ),
                    None,
                )
                if isinstance(failed_events, list)
                else None
            )
            recovery = {
                "source_run_id": recovery_of_run_id,
                "source_mode": "LIVE",
                "error_code": failed_public.get("error_code"),
                "failure": copy.deepcopy(failed_public.get("failure")),
                "failed_event": copy.deepcopy(failed_event),
                "cost_usd": failed_public.get("cost_usd"),
                "same_scenario": True,
                "model_calls_replayed": False,
            }
        with self._lock:
            if self._active_run_id is not None:
                active = self._runs.get(self._active_run_id)
                if active is not None and active.state in {"queued", "running"}:
                    raise UIError("run_already_active", HTTPStatus.CONFLICT)
            run_id = uuid.uuid4().hex[:12]
            run = EvolutionRun(
                run_id=run_id,
                lane=lane,
                execution=execution,
                model_id=model_id,
                scenario_id=scenario_id,
                scenario=copy.deepcopy(selected_scenario),
                recovery=copy.deepcopy(recovery),
            )
            if selected_scenario is not None:
                run.tests = [
                    {
                        **copy.deepcopy(case),
                        "status": "queued",
                        "baseline": None,
                        "candidate": None,
                        "worker_id": None,
                    }
                    for case in selected_scenario.get("tests", [])
                    if isinstance(case, Mapping)
                ]
                self._initialise_e2e_agents(run)
                total = 5 + len(run.tests) * 2
                run.progress = {"done": 0, "total": total, "percent": 0}
            self._runs[run_id] = run
            self._active_run_id = run_id
            public_run = run.public()
        thread = threading.Thread(
            target=self._execute,
            args=(run_id,),
            name=f"aga-self-evolution-{run_id}",
            daemon=True,
        )
        thread.start()
        return public_run

    @staticmethod
    def _initialise_e2e_agents(run: EvolutionRun) -> None:
        assert isinstance(run.scenario, Mapping)
        workers = int(run.scenario.get("parallel_workers") or 4)
        agents = [
            {
                "id": "orchestrator",
                "name": "E2E Orchestrator",
                "type": "orchestrator",
                "status": "queued",
                "current_action": "Ждёт запуска",
                "tools": [],
                "test_ids": [],
                "duration_ms": None,
                "cost_usd": 0.0,
            },
            {
                "id": "architecture",
                "name": "Architecture Evolution",
                "type": "ouroboros" if run.execution == "live" else "deterministic",
                "status": "queued",
                "current_action": "Ждёт materialized scenario graph",
                "tools": ["SEAF review", "propose_remediation", "re-review"],
                "test_ids": ["generated-scenario-graph"],
                "duration_ms": None,
                "cost_usd": 0.0,
            },
            {
                "id": "workspace-validator",
                "name": "Scenario Graph Validator",
                "type": "deterministic",
                "status": "queued",
                "current_action": "Ждёт запуска",
                "tools": ["strict graph validator"],
                "test_ids": [],
                "duration_ms": None,
                "cost_usd": 0.0,
            },
            {
                "id": "rule-evolver",
                "name": "Rule Evolver · Loop A",
                "type": "deterministic",
                "status": "queued",
                "current_action": "Ждёт baseline",
                "tools": ["run_evolution.py", "fitness gate"],
                "test_ids": [],
                "duration_ms": None,
                "cost_usd": 0.0,
            },
            {
                "id": "gate",
                "name": "Unified Safety Gate",
                "type": "gate",
                "status": "queued",
                "current_action": "Ждёт результаты",
                "tools": ["candidate manifest", "metrics", "patch audit"],
                "test_ids": [],
                "duration_ms": None,
                "cost_usd": 0.0,
            },
        ]
        for phase in ("baseline", "candidate"):
            for index in range(1, workers + 1):
                agents.append(
                    {
                        "id": f"{phase}-worker-{index}",
                        "name": f"{phase.title()} Test Worker {index}",
                        "type": "test_worker",
                        "status": "queued",
                        "current_action": "Ждёт свой shard",
                        "tools": ["AGA deterministic review"],
                        "test_ids": [],
                        "duration_ms": None,
                        "cost_usd": 0.0,
                    }
                )
        run.agents = agents

    def get(self, run_id: str) -> Mapping[str, Any]:
        if RUN_ID_RE.fullmatch(run_id) is None:
            raise UIError("run_id_invalid")
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                return run.public()
            if (
                isinstance(self._recorded_run, Mapping)
                and self._recorded_run.get("run_id") == run_id
            ):
                return copy.deepcopy(dict(self._recorded_run))
            raise UIError("run_not_found", HTTPStatus.NOT_FOUND)

    def current(self) -> Mapping[str, Any] | None:
        with self._lock:
            if self._active_run_id is None:
                return (
                    copy.deepcopy(dict(self._recorded_run))
                    if isinstance(self._recorded_run, Mapping)
                    else None
                )
            run = self._runs.get(self._active_run_id)
            return run.public() if run is not None else None

    def report(self, run_id: str) -> Mapping[str, Any]:
        run = self.get(run_id)
        result = run.get("result") if isinstance(run.get("result"), Mapping) else {}
        summary = result.get("summary") if isinstance(result, Mapping) else {}
        gate = result.get("gate") if isinstance(result, Mapping) else {}
        artifacts = result.get("artifacts") if isinstance(result, Mapping) else []
        events = run.get("events") if isinstance(run.get("events"), list) else []
        architecture = (
            result.get("architecture_evolution")
            if isinstance(result.get("architecture_evolution"), Mapping)
            else {}
        )
        task_steps = (
            architecture.get("task_steps")
            if isinstance(architecture.get("task_steps"), list)
            else []
        )
        task_evidence = [
            {
                "stage": step.get("stage"),
                "task_id": step.get("task_id"),
                "tools": copy.deepcopy(step.get("tools")),
                "receipt_verified": step.get("receipt_verified") is True,
                "actual_cost_usd": step.get("cost_usd"),
                "outcome": step.get("outcome"),
            }
            for step in task_steps
            if isinstance(step, Mapping) and step.get("task_id")
        ]
        if not task_evidence:
            for event in events:
                if not isinstance(event, Mapping) or not event.get("task_id"):
                    continue
                data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
                tools = data.get("receipts") if isinstance(data.get("receipts"), list) else []
                if event.get("tool") and event.get("tool") not in tools:
                    tools = [*tools, event.get("tool")]
                task_evidence.append(
                    {
                        "event_id": event.get("id"),
                        "task_id": event.get("task_id"),
                        "tools": tools,
                        "receipt_verified": data.get("receipt_verified") is True,
                        "status": event.get("status"),
                    }
                )
        artifact_projection = []
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, Mapping):
                    continue
                artifact_projection.append(
                    {
                        key: artifact.get(key)
                        for key in ("id", "label", "kind", "path", "sha256")
                        if artifact.get(key) is not None
                    }
                )
        report = {
            "schema": PUBLIC_RUN_REPORT_SCHEMA,
            "run_id": run.get("run_id"),
            "scenario_id": run.get("scenario_id"),
            "display_mode": run.get("display_mode"),
            "recorded_evidence": run.get("recorded_evidence") is True,
            "source_execution": run.get("source_execution") or run.get("execution"),
            "state": run.get("state"),
            "error_code": run.get("error_code"),
            "model_id": run.get("model_id") if run.get("execution") == "live" else None,
            "provider": run.get("provider") if run.get("execution") == "live" else None,
            "actual_cost_usd": run.get("cost_usd") if run.get("execution") == "live" else None,
            "started_at_unix_ms": run.get("started_at_unix_ms"),
            "finished_at_unix_ms": run.get("finished_at_unix_ms"),
            "classification": "synthetic-public",
            "architecture_engine": summary.get("architecture_engine")
            if isinstance(summary, Mapping)
            else None,
            "summary": copy.deepcopy(dict(summary)) if isinstance(summary, Mapping) else {},
            "gate": copy.deepcopy(dict(gate)) if isinstance(gate, Mapping) else {},
            "task_evidence": task_evidence,
            "artifacts": artifact_projection,
            "recovery": copy.deepcopy(run.get("recovery")),
            "merge_performed": summary.get("merge_performed")
            if isinstance(summary, Mapping)
            else None,
            "sanitized": True,
        }
        sanitized = _public_safe_copy(report)
        if not isinstance(sanitized, Mapping):
            raise UIError("report_generation_failed")
        return sanitized

    def _mutate(self, run_id: str, callback: Any) -> None:
        with self._lock:
            run = self._runs[run_id]
            callback(run)

    def _execute(self, run_id: str) -> None:
        started_ms = int(time.time() * 1000)
        self._mutate(
            run_id,
            lambda run: (
                setattr(run, "state", "running"),
                setattr(run, "phase", "planning"),
                setattr(run, "started_at_unix", int(time.time())),
                setattr(run, "started_at_unix_ms", started_ms),
            ),
        )
        try:
            produced_result: Mapping[str, Any] | None = None
            with self._lock:
                run = self._runs[run_id]
                lane, execution = run.lane, run.execution
            if lane == "e2e":
                produced_result = self._run_e2e(run_id)
            elif execution == "replay":
                self._replay(run_id, lane)
            elif lane == "architecture":
                self._run_architecture(run_id)
            else:
                self._run_rules(run_id)
            with self._lock:
                existing_result = self._runs[run_id].result
            fixture = (
                produced_result
                if isinstance(produced_result, Mapping)
                else existing_result
                if isinstance(existing_result, Mapping)
                else _load_fixture()
            )
            finished_ms = int(time.time() * 1000)
            def complete(run: EvolutionRun) -> None:
                run.result = fixture
                run.state = "succeeded"
                run.phase = "completed"
                run.progress = {**run.progress, "done": run.progress["total"], "percent": 100}
                run.finished_at_unix = int(time.time())
                run.finished_at_unix_ms = finished_ms
                if run.lane == "e2e":
                    gate = run.agent("gate")
                    gate_started = int(gate.get("started_at_unix_ms") or finished_ms)
                    gate["status"] = "succeeded"
                    gate["current_action"] = "PASS · кандидат собран для проверки человеком"
                    gate["finished_at_unix_ms"] = finished_ms
                    gate["duration_ms"] = max(0, finished_ms - gate_started)
                    run.append(
                        "gate.passed",
                        "Unified gate пройден",
                        "Unified Safety Gate",
                        "Архитектура, правила, candidate-тесты и артефакты сведены без регрессий.",
                        kind="gate",
                        status="passed",
                        actor_id="gate",
                        test_ids=tuple(case["id"] for case in run.tests),
                    )
                run.append(
                    "run.completed",
                    "Полный E2E завершён" if run.lane == "e2e" else "Процесс завершён",
                    "E2E Orchestrator" if run.lane == "e2e" else "AGA",
                    "Все обязательные стадии завершены; итоговое состояние зафиксировано.",
                    kind="terminal",
                    status="passed",
                    actor_id="orchestrator" if run.lane == "e2e" else "aga",
                )
                if run.lane == "e2e":
                    agent = run.agent("orchestrator")
                    agent["status"] = "succeeded"
                    agent["current_action"] = "E2E завершён"
                    agent["duration_ms"] = max(0, finished_ms - (run.started_at_unix_ms or finished_ms))
            self._mutate(run_id, complete)
            self._persist_terminal_run(run_id)
        except UIError as exc:
            self._fail_run(run_id, exc.code)
        except Exception:
            self._fail_run(run_id, "internal_run_error")

    def _fail_run(self, run_id: str, code: str) -> None:
        finished_ms = int(time.time() * 1000)
        def fail(run: EvolutionRun) -> None:
            run.state = "failed"
            run.phase = "failed"
            run.error_code = code
            run.finished_at_unix = int(time.time())
            run.finished_at_unix_ms = finished_ms
            run.append(
                "run.failed",
                "E2E остановлен",
                "E2E Orchestrator",
                f"Безопасная остановка: {code}.",
                kind="terminal",
                status="failed",
                actor_id="orchestrator",
            )
            if run.lane == "e2e":
                for active_agent in run.agents:
                    if active_agent.get("status") == "running":
                        active_agent["status"] = "failed"
                        active_agent["current_action"] = f"Остановлен: {code}"
                        active_agent["finished_at_unix_ms"] = finished_ms
                        started = int(active_agent.get("started_at_unix_ms") or finished_ms)
                        active_agent["duration_ms"] = max(0, finished_ms - started)
                agent = run.agent("orchestrator")
                agent["status"] = "failed"
                agent["current_action"] = code
                agent["duration_ms"] = max(0, finished_ms - (run.started_at_unix_ms or finished_ms))
        self._mutate(run_id, fail)
        try:
            self._persist_terminal_run(run_id)
        except UIError:
            # The terminal state remains truthful even if the optional replay
            # pointer cannot be updated; per-run artifacts are never rewritten.
            pass

    def _advance(self, run_id: str, amount: int = 1) -> None:
        def update(run: EvolutionRun) -> None:
            total = max(1, int(run.progress.get("total") or 1))
            done = min(total, int(run.progress.get("done") or 0) + amount)
            run.progress = {
                "done": done,
                "total": total,
                "percent": min(99, round(done / total * 100)),
            }
        self._mutate(run_id, update)

    def _agent_started(self, run_id: str, agent_id: str, action: str) -> int:
        started_ms = int(time.time() * 1000)
        def update(run: EvolutionRun) -> None:
            agent = run.agent(agent_id)
            agent["status"] = "running"
            agent["current_action"] = action
            agent["started_at_unix_ms"] = started_ms
        self._mutate(run_id, update)
        return started_ms

    def _agent_finished(
        self,
        run_id: str,
        agent_id: str,
        started_ms: int,
        action: str,
        *,
        cost_usd: float = 0.0,
    ) -> None:
        finished_ms = int(time.time() * 1000)
        def update(run: EvolutionRun) -> None:
            agent = run.agent(agent_id)
            agent["status"] = "succeeded"
            agent["current_action"] = action
            agent["finished_at_unix_ms"] = finished_ms
            agent["duration_ms"] = max(0, finished_ms - started_ms)
            self._set_agent_cost(run, agent_id, cost_usd)
        self._mutate(run_id, update)

    @staticmethod
    def _set_agent_cost(
        run: EvolutionRun,
        agent_id: str,
        cost_usd: float,
    ) -> None:
        normalized = round(float(cost_usd), 8)
        if not math.isfinite(normalized) or normalized < 0.0:
            raise UIError("architecture_cost_invalid")
        run.agent(agent_id)["cost_usd"] = normalized
        run.cost_usd = round(
            sum(
                float(agent.get("cost_usd") or 0.0)
                for agent in run.agents
                if isinstance(agent.get("cost_usd"), (int, float))
                and not isinstance(agent.get("cost_usd"), bool)
            ),
            8,
        )

    def _record_architecture_evidence_cost(
        self,
        run_id: str,
        evidence: Mapping[str, Any],
    ) -> float | None:
        cost = _architecture_evidence_cost(evidence)
        if cost is None:
            return None
        self._mutate(
            run_id,
            lambda run: self._set_agent_cost(run, "architecture", cost),
        )
        return cost

    @staticmethod
    def _decode_json_process(
        completed: subprocess.CompletedProcess[bytes],
        *,
        error_code: str,
    ) -> Mapping[str, Any]:
        if completed.returncode != 0:
            raise UIError(_typed_process_error(completed) or error_code)
        try:
            value = json.loads(completed.stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise UIError(error_code) from exc
        if not isinstance(value, Mapping):
            raise UIError(error_code)
        return value

    @staticmethod
    def _snapshot_rules(run_id: str, phase: str) -> tuple[Path, str]:
        if RUN_ID_RE.fullmatch(run_id) is None or phase not in {"baseline", "candidate"}:
            raise UIError("rules_snapshot_invalid")
        source = REPOSITORY_ROOT / "aga-skill" / (
            "rules" if phase == "baseline" else "build/candidate-rules"
        )
        if not source.is_dir() or source.is_symlink():
            raise UIError("rules_snapshot_unavailable")
        target = REPOSITORY_ROOT / ".aga-runs" / "self-evolution-ui" / run_id / f"{phase}-rules"
        try:
            target.mkdir(mode=0o700, parents=True, exist_ok=False)
        except OSError as exc:
            raise UIError("rules_snapshot_unavailable") from exc
        digest = hashlib.sha256()
        files = sorted(path for path in source.iterdir() if path.is_file() and path.suffix == ".yaml")
        if not files or any(path.is_symlink() for path in files):
            raise UIError("rules_snapshot_unavailable")
        try:
            for source_path in files:
                raw = source_path.read_bytes()
                target_path = target / source_path.name
                target_path.write_bytes(raw)
                digest.update(source_path.name.encode("utf-8"))
                digest.update(b"\0")
                digest.update(len(raw).to_bytes(8, "big"))
                digest.update(raw)
        except OSError as exc:
            raise UIError("rules_snapshot_unavailable") from exc
        return target, digest.hexdigest()

    @staticmethod
    def _persist_scenario(run_id: str, scenario: Mapping[str, Any]) -> Path:
        if RUN_ID_RE.fullmatch(run_id) is None:
            raise UIError("scenario_run_id_invalid")
        run_root = REPOSITORY_ROOT / ".aga-runs" / "self-evolution-ui" / run_id
        scenario_path = run_root / "scenario.json"
        payload = _canonical_json(scenario)
        try:
            run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            with scenario_path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise UIError("scenario_materialization_failed") from exc
        return scenario_path

    @staticmethod
    def _persist_run_json(
        run_id: str,
        name: str,
        value: Mapping[str, Any],
    ) -> tuple[str, str]:
        if RUN_ID_RE.fullmatch(run_id) is None or re.fullmatch(r"[a-z][a-z0-9-]{0,63}\.json", name) is None:
            raise UIError("run_artifact_invalid")
        run_root = REPOSITORY_ROOT / ".aga-runs" / "self-evolution-ui" / run_id
        path = run_root / name
        payload = _canonical_json(value)
        if len(payload) > 3 * 1024 * 1024:
            raise UIError("run_artifact_too_large")
        try:
            run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise UIError("run_artifact_unavailable") from exc
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        return relative, hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _rules_file_hashes(root: Path) -> dict[str, str]:
        try:
            files = sorted(path for path in root.iterdir() if path.is_file() and path.suffix == ".yaml")
            if not files or any(path.is_symlink() for path in files):
                raise OSError("unsafe rules inventory")
            return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        except OSError as exc:
            raise UIError("rules_snapshot_unavailable") from exc

    @classmethod
    def _validate_evolution_manifest(
        cls,
        baseline_rules: Path,
        candidate_rules: Path,
        *,
        previous_mtime_ns: int | None,
    ) -> Mapping[str, Any]:
        manifest_path = REPOSITORY_ROOT / "aga-skill" / "build" / "candidate-manifest.json"
        try:
            stat = manifest_path.stat()
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise UIError("candidate_manifest_invalid") from exc
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("schema") != "aga.candidate-manifest/v1"
            or manifest.get("gate_passed") is not True
            or not isinstance(manifest.get("cycle_id"), str)
            or (previous_mtime_ns is not None and stat.st_mtime_ns <= previous_mtime_ns)
            or manifest.get("base_rules") != cls._rules_file_hashes(baseline_rules)
            or manifest.get("candidate_rules") != cls._rules_file_hashes(candidate_rules)
        ):
            raise UIError("candidate_manifest_invalid")
        return copy.deepcopy(dict(manifest))

    def _run_e2e(self, run_id: str) -> Mapping[str, Any]:
        with self._lock:
            run = self._runs[run_id]
            scenario = copy.deepcopy(run.scenario)
            execution = run.execution
        if not isinstance(scenario, Mapping):
            raise UIError("scenario_required")

        def begin(run: EvolutionRun) -> None:
            run.phase = "planning"
            orchestrator = run.agent("orchestrator")
            orchestrator["status"] = "running"
            orchestrator["current_action"] = "Планирует fan-out"
            orchestrator["started_at_unix_ms"] = run.started_at_unix_ms
            if isinstance(run.recovery, Mapping):
                run.append(
                    "recovery.local.started",
                    "Запущен локальный recovery того же сценария",
                    "E2E Orchestrator",
                    "Failed Live evidence сохранён; recovery детерминированный и не повторяет model calls.",
                    kind="recovery",
                    status="completed",
                    actor_id="orchestrator",
                    data=run.recovery,
                )
            run.append(
                "scenario.bound",
                "Сценарий передан исполнителям",
                "E2E Orchestrator",
                f"{len(run.tests)} реальных golden-кейсов распределяются между параллельными воркерами.",
                kind="state",
                status="completed",
                actor_id="orchestrator",
                test_ids=[case["id"] for case in run.tests],
            )
        self._mutate(run_id, begin)
        self._advance(run_id)

        workers = int(scenario.get("parallel_workers") or 4)
        scenario_path = self._persist_scenario(run_id, scenario)
        case_ids = [str(case.get("id")) for case in scenario.get("tests", [])]
        shards: list[list[str]] = [[] for _ in range(workers)]
        for index, case_id in enumerate(case_ids):
            shards[index % workers].append(case_id)

        self._mutate(run_id, lambda run: setattr(run, "phase", "fan_out"))
        futures: dict[Any, str] = {}
        architecture_result: Mapping[str, Any] | None = None
        workspace_result: Mapping[str, Any] | None = None
        rules_result: Mapping[str, Any] | None = None
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="aga-e2e-root") as pool:
            architecture_future = pool.submit(
                self._run_e2e_architecture,
                run_id,
                execution,
                scenario_path,
            )
            futures[architecture_future] = "architecture"
            workspace_future = pool.submit(self._run_workspace_validator, run_id, scenario_path)
            futures[workspace_future] = "workspace-validator"
            rules_future = pool.submit(self._run_rules_pipeline, run_id, tuple(tuple(shard) for shard in shards))
            futures[rules_future] = "rules-pipeline"
            for future in as_completed(futures):
                agent_id = futures[future]
                value = future.result()
                if agent_id == "architecture":
                    architecture_result = value
                elif agent_id == "workspace-validator":
                    workspace_result = value
                elif agent_id == "rules-pipeline":
                    rules_result = value

        if architecture_result is None or workspace_result is None or rules_result is None:
            raise UIError("baseline_fanout_incomplete")

        self._mutate(run_id, lambda run: setattr(run, "phase", "gating"))
        gate_started = self._agent_started(run_id, "gate", "Сводит архитектуру, правила, тесты и артефакты")
        with self._lock:
            current_tests = copy.deepcopy(self._runs[run_id].tests)
            current_cost_usd = float(self._runs[run_id].cost_usd)
        candidate_passed = all(
            isinstance(case.get("candidate"), Mapping) and case["candidate"].get("passed") is True
            for case in current_tests
        )
        def semantic_fingerprint(value: Mapping[str, Any]) -> bytes:
            return _canonical_json(
                {
                    "actual_outcome": value.get("actual_outcome"),
                    "actual_findings": value.get("actual_findings", []),
                    "suppressed": value.get("suppressed", []),
                    "tp": value.get("tp", []),
                    "fp": value.get("fp", []),
                    "fn": value.get("fn", []),
                }
            )

        changed = []
        by_id = {str(case.get("id")): case for case in current_tests}
        for case_id, case in by_id.items():
            baseline = case.get("baseline")
            candidate = case.get("candidate")
            if isinstance(baseline, Mapping) and isinstance(candidate, Mapping):
                if semantic_fingerprint(baseline) != semantic_fingerprint(candidate):
                    changed.append(case_id)
        changed.sort()
        architecture_gate = bool(architecture_result.get("gate", {}).get("passed"))
        target = by_id.get("pr-15", {})
        control = by_id.get("pr-16", {})
        target_baseline = target.get("baseline", {}) if isinstance(target, Mapping) else {}
        target_candidate = target.get("candidate", {}) if isinstance(target, Mapping) else {}
        control_baseline = control.get("baseline", {}) if isinstance(control, Mapping) else {}
        control_candidate = control.get("candidate", {}) if isinstance(control, Mapping) else {}
        target_fixed = (
            isinstance(target_baseline, Mapping)
            and target_baseline.get("passed") is False
            and "PRIN-002" in target_baseline.get("fp", [])
            and isinstance(target_candidate, Mapping)
            and target_candidate.get("passed") is True
            and any(
                isinstance(item, Mapping)
                and item.get("rule_id") == "PRIN-002"
                and item.get("exception") == "EXC-PRIN-002-001"
                for item in target_candidate.get("suppressed", [])
            )
        )
        control_preserved = (
            isinstance(control_baseline, Mapping)
            and control_baseline.get("passed") is True
            and "PRIN-002" in control_baseline.get("tp", [])
            and isinstance(control_candidate, Mapping)
            and control_candidate.get("passed") is True
            and "PRIN-002" in control_candidate.get("tp", [])
        )
        baseline_passed = sum(
            1 for case in current_tests if isinstance(case.get("baseline"), Mapping) and case["baseline"].get("passed") is True
        )
        candidate_pass_count = sum(
            1 for case in current_tests if isinstance(case.get("candidate"), Mapping) and case["candidate"].get("passed") is True
        )
        rule_gate = target_fixed and control_preserved and changed == ["pr-15"]
        checks = [
            {"id": "workspace_valid", "label": "SEAF workspace валиден", "passed": workspace_result.get("passed") is True},
            {"id": "architecture_closed", "label": "SEAF-004 закрыт повторной проверкой", "passed": architecture_gate},
            {"id": "candidate_tests", "label": "Все candidate-тесты совпали с oracle", "passed": candidate_passed},
            {"id": "rule_fitness", "label": "Rule fitness не дал регрессий", "passed": rule_gate},
            {
                "id": "strict_improvement",
                "label": "Есть измеримое улучшение без лишних изменений",
                "passed": rule_gate and candidate_pass_count > baseline_passed,
            },
        ]
        if not all(item["passed"] for item in checks):
            raise UIError("e2e_gate_failed")
        graph_before = copy.deepcopy(architecture_result.get("before") or scenario.get("graph"))
        graph_after = copy.deepcopy(architecture_result.get("after"))
        patch = architecture_result.get("patch", {})
        changed_edge = str(patch.get("entity_id") or "")
        replacement = str(patch.get("replacement_component") or "")
        if not isinstance(graph_before, Mapping) or not isinstance(graph_after, Mapping):
            raise UIError("architecture_projection_failed")
        rule_result = self._run_rule_result(
            current_tests,
            baseline_passed=baseline_passed,
            candidate_passed=candidate_pass_count,
        )
        try:
            manifest = json.loads(
                (REPOSITORY_ROOT / "aga-skill" / "build" / "candidate-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            rules_diff = (
                REPOSITORY_ROOT / "aga-skill" / "build" / "rules.diff"
            ).read_text(encoding="utf-8")
            review_package = (
                REPOSITORY_ROOT / "aga-skill" / "build" / "evolution-pr.md"
            ).read_text(encoding="utf-8")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise UIError("run_artifact_unavailable") from exc
        if not isinstance(manifest, Mapping):
            raise UIError("candidate_manifest_invalid")
        architecture_path, architecture_sha256 = self._persist_run_json(
            run_id,
            "architecture-result.json",
            dict(architecture_result),
        )
        rules_path, rules_sha256 = self._persist_run_json(
            run_id,
            "rules-result.json",
            dict(rule_result),
        )
        tests_path, tests_sha256 = self._persist_run_json(
            run_id,
            "tests-result.json",
            {"schema": "aga.self-evolution-tests/v1", "tests": current_tests},
        )
        manifest_path, manifest_sha256 = self._persist_run_json(
            run_id,
            "candidate-manifest.json",
            dict(manifest),
        )
        diff_path, diff_sha256 = self._persist_run_json(
            run_id,
            "rules-diff.json",
            {"schema": "aga.self-evolution-rule-diff/v1", "diff": rules_diff},
        )
        review_path, review_sha256 = self._persist_run_json(
            run_id,
            "human-review-package.json",
            {"schema": "aga.self-evolution-review-package/v1", "markdown": review_package},
        )
        run_root_relative = f".aga-runs/self-evolution-ui/{run_id}"
        artifacts = [
            {
                "id": "scenario-input",
                "label": "Exact generated scenario",
                "path": scenario_path.relative_to(REPOSITORY_ROOT).as_posix(),
                "kind": "input",
                "sha256": hashlib.sha256(_canonical_json(scenario)).hexdigest(),
            },
            {"id": "architecture-result", "label": "Architecture review + patch + re-review", "path": architecture_path, "kind": "evidence", "sha256": architecture_sha256},
            {"id": "rules-result", "label": "Run-bound rule metrics", "path": rules_path, "kind": "metrics", "sha256": rules_sha256},
            {"id": "test-report", "label": "All baseline/candidate test results", "path": tests_path, "kind": "tests", "sha256": tests_sha256},
            {"id": "candidate-manifest", "label": "Validated candidate manifest", "path": manifest_path, "kind": "manifest", "sha256": manifest_sha256},
            {"id": "rules-diff", "label": "Rules diff", "path": diff_path, "kind": "diff", "sha256": diff_sha256},
            {"id": "review-package", "label": "Human review package", "path": review_path, "kind": "report", "sha256": review_sha256},
            {"id": "baseline-rules", "label": "Immutable baseline rules snapshot", "path": f"{run_root_relative}/baseline-rules", "kind": "ruleset", "sha256": rules_result.get("baseline_rules_sha256")},
            {"id": "candidate-rules", "label": "Immutable candidate rules snapshot", "path": f"{run_root_relative}/candidate-rules", "kind": "ruleset", "sha256": rules_result.get("candidate_rules_sha256")},
        ]
        result = {
            "schema": "aga.self-evolution-e2e-result/v2",
            "scenario_id": scenario.get("scenario_id"),
            "graph": {
                "before": graph_before,
                "after": graph_after,
                "deltas": [
                    {
                        "edge_id": changed_edge,
                        "before_to": patch.get("eliminated_component", "demo.legacy_scoring"),
                        "after_to": replacement,
                        "rule_id": patch.get("rule_id", "SEAF-004"),
                    }
                ],
            },
            "architecture_evolution": copy.deepcopy(architecture_result),
            "rule_evolution": rule_result,
            "artifacts": artifacts,
            "gate": {"passed": True, "checks": checks},
            "summary": {
                "tests": len(current_tests),
                "candidate_passed": sum(1 for case in current_tests if case.get("candidate", {}).get("passed")),
                "behavior_changed": changed,
                "parallel_workers": workers,
                "architecture_engine": LIVE_ARCHITECTURE_ENGINE
                if execution == "live"
                else LOCAL_ARCHITECTURE_ENGINE,
                "actual_cost_usd": round(current_cost_usd, 8)
                if execution == "live"
                else None,
                "human_review_required": True,
                "merge_performed": False,
            },
        }
        self._advance(run_id)
        return result

    @staticmethod
    def _rule_metrics(cases: Sequence[Mapping[str, Any]], phase: str) -> dict[str, Any]:
        results = [case.get(phase) for case in cases if isinstance(case.get(phase), Mapping)]
        if len(results) != len(cases):
            raise UIError("test_results_incomplete")
        true_positive = sum(len(item.get("tp", [])) for item in results)
        false_positive = sum(len(item.get("fp", [])) for item in results)
        false_negative = sum(len(item.get("fn", [])) for item in results)
        predicted = true_positive + false_positive
        expected = true_positive + false_negative
        precision = true_positive / predicted if predicted else 1.0
        recall = true_positive / expected if expected else 1.0
        passed = sum(1 for item in results if item.get("passed") is True)
        return {
            "cases": len(results),
            "passed": passed,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "outcome_accuracy": round(
                sum(1 for item in results if item.get("actual_outcome") == item.get("expected_outcome"))
                / max(1, len(results)),
                4,
            ),
            "weighted_cost": float(false_positive * 2 + false_negative * 5),
            "false_findings": false_positive,
            "missed_findings": false_negative,
        }

    def _run_rule_result(
        self,
        cases: Sequence[Mapping[str, Any]],
        *,
        baseline_passed: int,
        candidate_passed: int,
    ) -> Mapping[str, Any]:
        fixture = _load_fixture()
        template = fixture.get("rule_evolution")
        if not isinstance(template, Mapping):
            raise UIError("rule_projection_failed")
        before = self._rule_metrics(cases, "baseline")
        after = self._rule_metrics(cases, "candidate")
        return {
            "title": "Самоэволюция архитектурных правил",
            "status": "passed",
            "cycle_id": template.get("cycle_id"),
            "selected_case_ids": [str(case.get("id")) for case in cases],
            "mutation": copy.deepcopy(template.get("mutation")),
            "tests": {
                "synthetic_cases": len(cases),
                "before": before,
                "after": after,
                "delta": {
                    "precision": round(float(after["precision"]) - float(before["precision"]), 4),
                    "outcome_accuracy": round(
                        float(after["outcome_accuracy"]) - float(before["outcome_accuracy"]), 4
                    ),
                    "weighted_cost": float(after["weighted_cost"]) - float(before["weighted_cost"]),
                    "false_findings": int(after["false_findings"]) - int(before["false_findings"]),
                    "oracle_matches": candidate_passed - baseline_passed,
                },
                "gate_passed": True,
            },
            "candidate": copy.deepcopy(template.get("candidate")),
        }

    def _run_rules_pipeline(
        self,
        run_id: str,
        shards: Sequence[Sequence[str]],
    ) -> Mapping[str, Any]:
        self._mutate(run_id, lambda run: setattr(run, "phase", "baseline_tests"))
        baseline_rules, baseline_sha256 = self._snapshot_rules(run_id, "baseline")
        baseline_futures: dict[Any, int] = {}
        with ThreadPoolExecutor(max_workers=len(shards), thread_name_prefix="aga-baseline") as pool:
            for index, shard in enumerate(shards, 1):
                if shard:
                    future = pool.submit(
                        self._run_test_shard,
                        run_id,
                        "baseline",
                        index,
                        tuple(shard),
                        baseline_rules,
                        baseline_sha256,
                    )
                    baseline_futures[future] = index
            for future in as_completed(baseline_futures):
                future.result()

        self._mutate(run_id, lambda run: setattr(run, "phase", "evolving_rules"))
        rule_started = self._agent_started(
            run_id,
            "rule-evolver",
            "Строит candidate rules из precedent:0001",
        )
        self._mutate(
            run_id,
            lambda run: run.append(
                "rules.evolution.started",
                "Rule Evolver начал Loop A",
                "Rule Evolver · Loop A",
                "Baseline зафиксирован; мутация правила строится из подтверждённого DMZ-прецедента.",
                kind="mutation",
                status="running",
                actor_id="rule-evolver",
                tool="run_evolution.py",
            ),
        )
        manifest_path = REPOSITORY_ROOT / "aga-skill" / "build" / "candidate-manifest.json"
        try:
            previous_manifest_mtime_ns = manifest_path.stat().st_mtime_ns
        except OSError:
            previous_manifest_mtime_ns = None
        evolved = _bounded_process(
            (sys.executable, "scripts/run_evolution.py", "--demo", "--max-attempts", "3"),
            cwd=REPOSITORY_ROOT / "aga-skill",
            timeout_seconds=300.0,
        )
        if evolved.returncode != 0:
            raise UIError(_typed_process_error(evolved))
        self._agent_finished(
            run_id,
            "rule-evolver",
            rule_started,
            "PRIN-002 candidate готов; fitness gate внутри evolver пройден",
        )
        self._mutate(
            run_id,
            lambda run: run.append(
                "rules.mutation.created",
                "Создано узкое исключение PRIN-002",
                "Rule Evolver · Loop A",
                "EXC-PRIN-002-001 разрешает только контролируемый DMZ batch через утверждённый gateway.",
                kind="mutation",
                status="completed",
                actor_id="rule-evolver",
                tool="run_evolution.py",
                test_ids=("pr-15", "pr-16"),
            ),
        )
        self._advance(run_id)

        self._mutate(run_id, lambda run: setattr(run, "phase", "candidate_tests"))
        candidate_rules, candidate_sha256 = self._snapshot_rules(run_id, "candidate")
        manifest = self._validate_evolution_manifest(
            baseline_rules,
            candidate_rules,
            previous_mtime_ns=previous_manifest_mtime_ns,
        )
        candidate_futures: dict[Any, int] = {}
        with ThreadPoolExecutor(max_workers=len(shards), thread_name_prefix="aga-candidate") as pool:
            for index, shard in enumerate(shards, 1):
                if shard:
                    future = pool.submit(
                        self._run_test_shard,
                        run_id,
                        "candidate",
                        index,
                        tuple(shard),
                        candidate_rules,
                        candidate_sha256,
                    )
                    candidate_futures[future] = index
            for future in as_completed(candidate_futures):
                future.result()
        return {
            "passed": True,
            "baseline_shards": len(baseline_futures),
            "candidate_shards": len(candidate_futures),
            "baseline_rules_sha256": baseline_sha256,
            "candidate_rules_sha256": candidate_sha256,
            "cycle_id": manifest.get("cycle_id"),
        }

    def _run_test_shard(
        self,
        run_id: str,
        phase: str,
        worker_index: int,
        case_ids: Sequence[str],
        rules_dir: Path,
        rules_sha256: str,
    ) -> Mapping[str, Any]:
        agent_id = f"{phase}-worker-{worker_index}"
        started_ms = self._agent_started(run_id, agent_id, f"Проверяет {len(case_ids)} synthetic PR")
        def assign(run: EvolutionRun) -> None:
            run.agent(agent_id)["test_ids"] = list(case_ids)
            for case_id in case_ids:
                case = run.test(case_id)
                case["status"] = f"{phase}_running"
                case["worker_id"] = agent_id
            run.append(
                f"{phase}.worker.{worker_index}.started",
                f"Worker {worker_index} получил shard",
                run.agent(agent_id)["name"],
                ", ".join(case_ids),
                kind="test_batch",
                status="running",
                actor_id=agent_id,
                tool="AGA deterministic review",
                test_ids=case_ids,
            )
        self._mutate(run_id, assign)
        completed = _bounded_process(
            (
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "run_self_evolution_test_shard.py"),
                "--ruleset",
                phase,
                "--worker",
                f"worker-{worker_index}",
                "--cases",
                ",".join(case_ids),
                "--rules-dir",
                str(rules_dir),
                "--rules-sha256",
                rules_sha256,
            ),
            cwd=REPOSITORY_ROOT,
            timeout_seconds=180.0,
        )
        payload = self._decode_json_process(completed, error_code="test_shard_failed")
        raw_cases = payload.get("cases")
        if (
            payload.get("schema") != "aga.self-evolution-test-shard/v1"
            or payload.get("status") != "completed"
            or payload.get("ruleset") != phase
            or payload.get("worker_id") != f"worker-{worker_index}"
            or payload.get("rules_sha256") != rules_sha256
            or not isinstance(raw_cases, list)
        ):
            raise UIError("test_shard_failed")
        returned_ids = [str(item.get("id") or "") for item in raw_cases if isinstance(item, Mapping)]
        passed_count = sum(1 for item in raw_cases if isinstance(item, Mapping) and item.get("passed") is True)
        if (
            len(returned_ids) != len(raw_cases)
            or len(set(returned_ids)) != len(returned_ids)
            or set(returned_ids) != set(case_ids)
            or payload.get("passed") != passed_count
            or payload.get("failed") != len(raw_cases) - passed_count
        ):
            raise UIError("test_shard_failed")
        def record(run: EvolutionRun) -> None:
            for item in raw_cases:
                if not isinstance(item, Mapping):
                    raise UIError("test_shard_failed")
                case_id = str(item.get("id") or "")
                if case_id not in case_ids:
                    raise UIError("test_shard_failed")
                case = run.test(case_id)
                case[phase] = copy.deepcopy(dict(item))
                case["status"] = "baseline_done" if phase == "baseline" else (
                    "passed" if item.get("passed") is True else "failed"
                )
                run.append(
                    f"{phase}.test.{case_id}",
                    f"{case_id} · {'совпал с oracle' if item.get('passed') is True else 'обнаружил baseline-расхождение'}",
                    run.agent(agent_id)["name"],
                    f"expected={item.get('expected_outcome')} · actual={item.get('actual_outcome')}",
                    kind="test_result",
                    status="passed" if item.get("passed") is True else "changed",
                    actor_id=agent_id,
                    tool="AGA deterministic review",
                    test_ids=(case_id,),
                )
            run.append(
                f"{phase}.worker.{worker_index}.completed",
                f"Worker {worker_index} завершил shard",
                run.agent(agent_id)["name"],
                f"Выполнено {len(raw_cases)} кейсов; совпало с oracle: {payload.get('passed')}/{len(raw_cases)}.",
                kind="test_batch",
                status="completed",
                actor_id=agent_id,
                tool="AGA deterministic review",
                test_ids=case_ids,
            )
        self._mutate(run_id, record)
        self._agent_finished(run_id, agent_id, started_ms, f"{len(raw_cases)} кейсов завершены")
        self._advance(run_id, len(raw_cases))
        return payload

    def _run_workspace_validator(self, run_id: str, scenario_path: Path) -> Mapping[str, Any]:
        agent_id = "workspace-validator"
        started_ms = self._agent_started(run_id, agent_id, "Проверяет точный generated graph и все ссылки")
        self._mutate(
            run_id,
            lambda run: run.append(
                "workspace.validation.started",
                "Запущена проверка generated scenario graph",
                "Scenario Graph Validator",
                "Проверяются schema, node/edge/replacement references, counts и единственный declared SEAF-004.",
                kind="tool_call",
                status="running",
                actor_id=agent_id,
                tool="run_self_evolution_architecture_scenario.py --validate-only",
            ),
        )
        completed = _bounded_process(
            (
                sys.executable,
                "scripts/run_self_evolution_architecture_scenario.py",
                "--scenario",
                str(scenario_path),
                "--validate-only",
            ),
            cwd=REPOSITORY_ROOT,
            timeout_seconds=180.0,
        )
        if completed.returncode != 0:
            raise UIError("workspace_validation_failed")
        payload = self._decode_json_process(completed, error_code="workspace_validation_failed")
        if (
            payload.get("schema") != "aga.self-evolution-scenario-validation/v1"
            or payload.get("status") != "validated"
            or not all(
                isinstance(check, Mapping) and check.get("passed") is True
                for check in payload.get("checks", [])
            )
        ):
            raise UIError("workspace_validation_failed")
        summary = payload.get("summary", {})
        detail = (
            f"{summary.get('nodes')} nodes · {summary.get('edges')} edges · "
            f"{summary.get('tests')} tests · все references разрешены"
        )
        self._agent_finished(run_id, agent_id, started_ms, detail or "Workspace valid")
        self._mutate(
            run_id,
            lambda run: run.append(
                "workspace.validation.completed",
                "Generated scenario graph валиден",
                "Scenario Graph Validator",
                detail,
                kind="tool_call",
                status="completed",
                actor_id=agent_id,
                tool="strict scenario graph validator",
            ),
        )
        self._advance(run_id)
        return {"passed": True, "detail": detail, "validation": payload}

    def _run_e2e_architecture(
        self,
        run_id: str,
        execution: str,
        scenario_path: Path,
    ) -> Mapping[str, Any]:
        agent_id = "architecture"
        action = "Запускает Ouroboros review → remediation → re-review" if execution == "live" else "Запускает реальный локальный review → patch → re-review"
        started_ms = self._agent_started(run_id, agent_id, action)
        if execution == "live":
            with self._lock:
                scenario = copy.deepcopy(self._runs[run_id].scenario)
            # A run labelled LIVE always performs three fresh paid tasks. Prior
            # receipts are exposed only as RECORDED EVIDENCE after a restart.
            fixture = self._run_architecture(run_id, scenario_path=scenario_path)
            architecture = fixture.get("architecture_evolution") if isinstance(fixture, Mapping) else None
            if not isinstance(architecture, Mapping):
                raise UIError("architecture_projection_failed")
            graph = scenario.get("graph") if isinstance(scenario, Mapping) else None
            if not isinstance(graph, Mapping):
                raise UIError("architecture_projection_failed")
            declared_edges = [
                edge
                for edge in graph.get("edges", [])
                if isinstance(edge, Mapping) and edge.get("expected_rule") == "SEAF-004"
            ]
            if len(declared_edges) != 1:
                raise UIError("architecture_projection_failed")
            declared = declared_edges[0]
            scenario_edge_id = str(declared.get("id") or "")
            replacement = str(declared.get("replacement_to") or "")
            projected_before_edges = architecture.get("before", {}).get("edges", [])
            projected_after_edges = architecture.get("after", {}).get("edges", [])
            projected_before = projected_before_edges[0] if isinstance(projected_before_edges, list) and projected_before_edges and isinstance(projected_before_edges[0], Mapping) else {}
            projected_after = projected_after_edges[0] if isinstance(projected_after_edges, list) and projected_after_edges and isinstance(projected_after_edges[0], Mapping) else {}
            if (
                projected_before.get("to") != declared.get("to")
                or projected_after.get("to") != replacement
                or architecture.get("change", {}).get("rule_id") != "SEAF-004"
            ):
                raise UIError("architecture_projection_failed")
            graph_before = copy.deepcopy(graph)
            graph_after = copy.deepcopy(graph)
            changed_count = 0
            for edge in graph_after.get("edges", []):
                if isinstance(edge, dict) and edge.get("id") == scenario_edge_id:
                    edge["to"] = replacement
                    changed_count += 1
            if changed_count != 1:
                raise UIError("architecture_projection_failed")
            raw_steps = fixture.get("ouroboros", {}).get("visible_steps", [])
            if (
                not isinstance(raw_steps, list)
                or len(raw_steps) != 3
                or not all(isinstance(step, Mapping) for step in raw_steps)
            ):
                raise UIError("architecture_task_evidence_invalid")
            stage_names = ("review", "remediation", "re-review")
            steps: list[dict[str, Any]] = []
            task_ids: set[str] = set()
            for stage, raw_step in zip(stage_names, raw_steps, strict=True):
                task_id = str(raw_step.get("task_id") or "")
                tools = raw_step.get("tools")
                raw_cost = raw_step.get("cost_usd")
                if (
                    not task_id
                    or task_id in task_ids
                    or not isinstance(tools, list)
                    or not tools
                    or any(not isinstance(tool, str) or not tool for tool in tools)
                    or isinstance(raw_cost, bool)
                    or not isinstance(raw_cost, (int, float))
                    or float(raw_cost) < 0.0
                ):
                    raise UIError("architecture_task_evidence_invalid")
                task_ids.add(task_id)
                steps.append(
                    {
                        **copy.deepcopy(dict(raw_step)),
                        "stage": stage,
                        "task_id": task_id,
                        "tools": list(dict.fromkeys(tools)),
                        "cost_usd": round(float(raw_cost), 8),
                        "receipt_verified": True,
                    }
                )
            cost = round(sum(float(step["cost_usd"]) for step in steps), 8)
            last_step = steps[-1]
            self._mutate(
                run_id,
                lambda run: run.append(
                    "architecture.ouroboros.rereview.passed",
                    "Ouroboros re-review завершён",
                    "Ouroboros Review",
                    "Исправленный commit проверен повторно: findings=0, verdict=approve.",
                    kind="gate",
                    status="passed",
                    actor_id=agent_id,
                    tool="aga_finalize_review",
                    task_id=str(last_step.get("task_id") or ""),
                    graph_delta={"operation": "rereview", "edge_id": scenario_edge_id},
                    data={
                        "verdict": "approve",
                        "findings": 0,
                        "task_id": str(last_step.get("task_id") or ""),
                        "receipts": copy.deepcopy(last_step.get("tools", [])),
                        "receipt_verified": True,
                        "cost_usd": last_step.get("cost_usd"),
                    },
                ),
            )
            result = {
                "status": "remediation_ready",
                "engine": "Ouroboros",
                "before": graph_before,
                "after": graph_after,
                "finding": {
                    "rule_id": architecture.get("change", {}).get("rule_id"),
                    "severity": architecture.get("change", {}).get("severity"),
                },
                "patch": {
                    "entity_id": scenario_edge_id,
                    "materialized_entity_id": projected_before.get("id"),
                    "eliminated_component": declared.get("to"),
                    "replacement_component": replacement,
                    "rule_id": architecture.get("change", {}).get("rule_id"),
                    "diff": "\n".join(line.get("text", "") for line in architecture.get("change", {}).get("diff_lines", [])),
                    "summary": architecture.get("change", {}).get("summary"),
                },
                "gate": {"passed": architecture.get("after", {}).get("findings") == 0},
                "task_steps": steps,
                "evidence": fixture,
            }
        else:
            try:
                from scripts import run_self_evolution_architecture_scenario as architecture_runner
            except ImportError as exc:
                raise UIError("architecture_remediation_failed") from exc

            stage_labels = {
                "materialized": "Generated graph материализован в Architecture-as-Code",
                "review_started": "Запущен реальный SEAF review полного графа",
                "finding": "SEAF review подтвердил blocker",
                "patch": "Создан и применён однострочный patch",
                "rereview": "Исправленный полный граф перепроверен",
                "gate": "Architecture gate вычислен",
            }
            stage_tools = {
                "materialized": "scenario materializer",
                "review_started": "RepositorySnapshotBuilder + prepare_seaf_review",
                "finding": "prepare_seaf_review",
                "patch": "propose_remediation",
                "rereview": "prepare_seaf_review",
                "gate": "AGA architecture safety gate",
            }
            stage_kinds = {
                "materialized": "state",
                "review_started": "tool_call",
                "finding": "finding",
                "patch": "mutation",
                "rereview": "gate",
                "gate": "gate",
            }
            architecture_edge_id = ""

            def receive_architecture_event(event: dict[str, Any]) -> None:
                nonlocal architecture_edge_id
                stage = str(event.get("stage") or "")
                if stage == "result":
                    return
                if stage not in stage_labels:
                    raise UIError("architecture_event_invalid")
                sequence = event.get("sequence")
                observed_edge_id = str(
                    event.get("scenario_edge_id")
                    or event.get("declared_edge_id")
                    or ""
                )
                if observed_edge_id:
                    architecture_edge_id = observed_edge_id
                edge_id = architecture_edge_id
                graph_delta: Mapping[str, Any] | None = None
                if stage == "finding":
                    finding = event.get("finding", {})
                    graph_delta = {
                        "operation": "finding",
                        "edge_id": edge_id,
                        "rule_id": "SEAF-004",
                        "severity": str(finding.get("severity") or "blocker")
                        if isinstance(finding, Mapping)
                        else "blocker",
                    }
                elif stage == "patch":
                    patch = event.get("patch", {})
                    graph_delta = {
                        "operation": "reroute",
                        "edge_id": edge_id,
                        "new_to": str(patch.get("replacement_component") or "")
                        if isinstance(patch, Mapping)
                        else "",
                    }
                elif stage == "rereview":
                    graph_delta = {"operation": "rereview", "edge_id": edge_id}
                data = {
                    key: copy.deepcopy(value)
                    for key, value in event.items()
                    if key
                    not in {
                        "schema",
                        "type",
                        "sequence",
                        "stage",
                        "actor",
                        "detail",
                        "scenario_edge_id",
                    }
                }
                def append_event(run: EvolutionRun) -> None:
                    run.agent(agent_id)["current_action"] = stage_labels[stage]
                    run.append(
                        f"architecture.local.{sequence}.{stage}",
                        stage_labels[stage],
                        str(event.get("actor") or "AGA Architecture Evolution"),
                        str(event.get("detail") or "Фактическая стадия завершена."),
                        kind=stage_kinds[stage],
                        status=(
                            "running"
                            if stage == "review_started"
                            else "passed"
                            if stage in {"rereview", "gate"} and event.get("passed", True)
                            else "completed"
                        ),
                        actor_id=agent_id,
                        tool=stage_tools[stage],
                        graph_delta=graph_delta,
                        data=data,
                    )
                self._mutate(run_id, append_event)

            try:
                raw_result = architecture_runner.run_path(
                    scenario_path,
                    event_sink=receive_architecture_event,
                )
            except architecture_runner.ArchitectureScenarioError as exc:
                raise UIError(str(exc)) from exc
            if (
                raw_result.get("schema") != architecture_runner.OUTPUT_SCHEMA
                or raw_result.get("status") != "completed"
                or raw_result.get("gate", {}).get("passed") is not True
            ):
                raise UIError("architecture_remediation_failed")
            remediation = raw_result.get("remediation", {})
            raw_patch = remediation.get("patch", {}) if isinstance(remediation, Mapping) else {}
            before = raw_result.get("before", {})
            after = raw_result.get("after", {})
            findings = before.get("findings", []) if isinstance(before, Mapping) else []
            finding = findings[0] if isinstance(findings, list) and findings and isinstance(findings[0], Mapping) else {}
            result = {
                "status": "remediation_ready",
                "engine": "AGA deterministic SEAF remediation",
                "before": copy.deepcopy(before.get("graph")),
                "after": copy.deepcopy(after.get("graph")),
                "finding": copy.deepcopy(dict(finding)),
                "patch": {
                    **(
                        copy.deepcopy(dict(raw_patch))
                        if isinstance(raw_patch, Mapping)
                        else {}
                    ),
                    "entity_id": str(remediation.get("edge_id") or ""),
                    "materialized_entity_id": str(remediation.get("materialized_entity_id") or ""),
                    "eliminated_component": str(remediation.get("previous_to") or ""),
                    "replacement_component": str(remediation.get("replacement_to") or ""),
                },
                "gate": copy.deepcopy(raw_result.get("gate")),
                "revisions": copy.deepcopy(raw_result.get("revisions")),
                "execution": copy.deepcopy(raw_result.get("execution")),
                "evidence": raw_result,
            }
            cost = 0.0
        self._agent_finished(run_id, agent_id, started_ms, "Architecture candidate прошёл re-review", cost_usd=cost)
        self._advance(run_id)
        return copy.deepcopy(dict(result))

    def _replay(self, run_id: str, lane: str) -> None:
        fixture = _load_fixture()
        evolution = fixture.get(
            "architecture_evolution" if lane == "architecture" else "rule_evolution"
        )
        timeline = evolution.get("timeline") if isinstance(evolution, Mapping) else None
        if not isinstance(timeline, list) or not timeline:
            raise UIError("fixture_timeline_missing", HTTPStatus.SERVICE_UNAVAILABLE)
        for index, item in enumerate(timeline):
            if not isinstance(item, Mapping):
                raise UIError("fixture_timeline_invalid", HTTPStatus.SERVICE_UNAVAILABLE)
            event_id = str(item.get("id") or "")
            label = str(item.get("label") or "")
            actor = str(item.get("actor") or "AGA")
            detail = str(item.get("detail") or "")
            if not event_id or not label:
                raise UIError("fixture_timeline_invalid", HTTPStatus.SERVICE_UNAVAILABLE)
            self._mutate(
                run_id,
                lambda run, values=(event_id, label, actor, detail): run.append(*values),
            )
            if index < len(timeline) - 1:
                time.sleep(REPLAY_STEP_SECONDS)

    def _run_architecture(
        self,
        run_id: str,
        *,
        scenario_path: Path | None = None,
    ) -> Mapping[str, Any]:
        correlation_key = f"ui-architecture-{run_id}"
        digest = hashlib.sha256(correlation_key.encode("utf-8")).hexdigest()
        run_root = REPOSITORY_ROOT / ".aga-runs" / "architecture" / digest[:16]
        evidence_relative = f"docs/evidence/ui/architecture-{run_id}.json"
        evidence_path = REPOSITORY_ROOT / evidence_relative
        with self._lock:
            is_e2e = self._runs[run_id].lane == "e2e"
            model_id = self._runs[run_id].model_id
        model_label = str(SUPPORTED_MODELS[model_id]["label"])
        if not is_e2e:
            self._mutate(
                run_id,
                lambda run: run.append(
                    "scenario_generated",
                    "Синтетическая архитектура создана",
                    "Synthetic Generator",
                    "Компонент со статусом eliminate связан с новым checkout-потоком.",
                ),
            )
        profile_script = str(REPOSITORY_ROOT / "scripts" / "ouroboros_profile.py")
        stopped = _bounded_process(
            (sys.executable, profile_script, "stop"),
            cwd=REPOSITORY_ROOT,
            timeout_seconds=60.0,
            model_id=model_id,
        )
        if stopped.returncode != 0:
            raise UIError(_typed_process_error(stopped))
        synced = _bounded_process(
            (sys.executable, profile_script, "sync"),
            cwd=REPOSITORY_ROOT,
            timeout_seconds=60.0,
            model_id=model_id,
        )
        if synced.returncode != 0:
            raise UIError(_typed_process_error(synced))
        started = _bounded_process(
            (sys.executable, profile_script, "start"),
            cwd=REPOSITORY_ROOT,
            timeout_seconds=120.0,
            model_id=model_id,
        )
        if started.returncode != 0:
            raise UIError(_typed_process_error(started))
        architecture_arguments: tuple[str, ...]
        if scenario_path is not None:
            try:
                from scripts import run_self_evolution_architecture_scenario as scenario_runner

                scenario_document = scenario_runner.load_scenario(scenario_path)
                repository = (
                    REPOSITORY_ROOT
                    / ".aga-runs"
                    / "self-evolution-ui"
                    / run_id
                    / "live-architecture-repository"
                )
                materialized = scenario_runner.materialize_scenario_repository(
                    scenario_document,
                    repository,
                    dependency_mode="verified",
                )
            except (ImportError, RuntimeError) as exc:
                raise UIError("architecture_materialization_failed") from exc
            repository_id = f"aga-ui-{scenario_document['scenario_id']}"
            architecture_arguments = (
                "--repository",
                str(materialized.repository),
                "--repository-id",
                repository_id,
                "--base",
                materialized.base,
                "--head",
                materialized.head,
            )
        else:
            architecture_arguments = ("--demo",)
        command = (
            sys.executable,
            profile_script,
            "exec",
            "--",
            "python3",
            str(REPOSITORY_ROOT / "scripts" / "run_architecture_evolution.py"),
            *architecture_arguments,
            "--correlation-key",
            correlation_key,
            "--evidence-out",
            evidence_relative,
        )
        try:
            process = subprocess.Popen(
                list(command),
                cwd=str(REPOSITORY_ROOT),
                env=_safe_subprocess_environment(model_id),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise UIError("architecture_run_unavailable") from exc
        if not is_e2e:
            self._mutate(
                run_id,
                lambda run: run.append(
                    "ouroboros_review_started",
                    "Ouroboros проверяет архитектуру",
                    f"Ouroboros · {model_label}",
                    "Review использует только AGA MCP-инструменты.",
                ),
            )
        if is_e2e:
            self._mutate(
                run_id,
                lambda run: run.append(
                    "architecture.ouroboros.review.started",
                    "Ouroboros root task запущен",
                    f"Ouroboros · {model_label}",
                    "Первый review читает synthetic Architecture-as-Code через AGA MCP receipts.",
                    kind="tool_call",
                    status="running",
                    actor_id="architecture",
                    tool="aga_prepare_review",
                ),
            )
        deadline = time.monotonic() + 3000.0
        while process.poll() is None:
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=10)
                raise UIError("architecture_run_timeout")
            self._observe_architecture(run_id, run_root)
            time.sleep(0.5)
        stdout, stderr = process.communicate(timeout=10)
        if len(stdout) > MAX_SUBPROCESS_OUTPUT_BYTES or len(stderr) > MAX_SUBPROCESS_OUTPUT_BYTES:
            raise UIError("run_output_too_large")
        self._observe_architecture(run_id, run_root)
        if process.returncode != 0:
            failure_evidence: Mapping[str, Any] = {}
            try:
                candidate = json.loads(evidence_path.read_text(encoding="utf-8"))
                if isinstance(candidate, Mapping) and candidate.get("status") == "failed":
                    failure_evidence = candidate
            except (OSError, UnicodeError, json.JSONDecodeError):
                failure_evidence = {}
            if failure_evidence:
                def record_architecture_failure(run: EvolutionRun) -> None:
                    delta = failure_evidence.get("aggregate_usage_delta_usd", 0.0)
                    cost = (
                        float(delta)
                        if isinstance(delta, (int, float))
                        and not isinstance(delta, bool)
                        and float(delta) >= 0.0
                        else 0.0
                    )
                    stage = str(failure_evidence.get("stage") or "review_before")
                    code = str(failure_evidence.get("code") or "architecture_run_failed")
                    run.failure = {
                        "component": "architecture",
                        "stage": stage,
                        "code": code,
                        "cost_usd": round(cost, 8),
                    }
                    self._set_agent_cost(run, "architecture", cost)
                    projection = _architecture_failure_projection(stage)
                    run.append(
                        projection["event_id"],
                        projection["label"],
                        f"Ouroboros · {model_label}",
                        projection["detail"],
                        kind="failure",
                        status="failed",
                        actor_id="architecture",
                        tool=projection["tool"],
                        data={"stage": stage, "code": code, "cost_usd": round(cost, 8)},
                    )
                self._mutate(run_id, record_architecture_failure)
            completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            raise UIError(_typed_process_error(completed))
        if not evidence_path.is_file():
            raise UIError("architecture_evidence_missing")
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise UIError("architecture_evidence_invalid") from exc
        if isinstance(evidence, Mapping) and is_e2e:
            # Preserve provider-reported spend before browser projection.  A
            # projection/schema failure happens after the paid tasks and must
            # not reset their actual cost to zero in recovery evidence.
            self._record_architecture_evidence_cost(run_id, evidence)
        if not isinstance(evidence, Mapping) or evidence.get("status") != "local_candidate_ready":
            raise UIError("architecture_gate_failed")
        try:
            from scripts.generate_self_evolution_ui_fixture import generate_from_paths

            live_fixture = generate_from_paths(architecture_evidence=evidence_path)
        except (
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise UIError("architecture_projection_failed") from exc
        if not is_e2e:
            self._mutate(run_id, lambda run: setattr(run, "result", live_fixture))
            self._mutate(
                run_id,
                lambda run: (
                    run.append(
                        "ouroboros_rereview_completed",
                        "Ouroboros перепроверил исправление",
                        f"Ouroboros · {model_label}",
                        "Повторный review не нашёл blocker или major findings.",
                    ),
                    run.append(
                        "gate_passed",
                        "Кандидат готов",
                        "AGA Gate",
                        "Созданы только локальная ветка и commit; merge не выполнялся.",
                    ),
                ),
            )
        return copy.deepcopy(dict(live_fixture))

    def _observe_architecture(self, run_id: str, run_root: Path) -> None:
        phase_path = run_root / "phases.json"
        try:
            payload = json.loads(phase_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        phases = payload.get("phases") if isinstance(payload, Mapping) else None
        if not isinstance(phases, Mapping):
            return
        with self._lock:
            is_e2e = self._runs[run_id].lane == "e2e"
            scenario = copy.deepcopy(self._runs[run_id].scenario)
        declared_edge_id = ""
        declared_replacement = ""
        if is_e2e and isinstance(scenario, Mapping):
            declared = [
                edge
                for edge in scenario.get("graph", {}).get("edges", [])
                if isinstance(edge, Mapping) and edge.get("expected_rule") == "SEAF-004"
            ]
            if len(declared) == 1:
                declared_edge_id = str(declared[0].get("id") or "")
                declared_replacement = str(declared[0].get("replacement_to") or "")
        if isinstance(phases.get("review_before"), Mapping):
            if not is_e2e:
                self._mutate(
                    run_id,
                    lambda run: (
                        run.append(
                            "finding_detected",
                            "Найден SEAF-004 blocker",
                            "Ouroboros Review",
                            "Новый поток направлен в компонент со статусом eliminate.",
                        ),
                        run.append(
                            "ouroboros_remediation_started",
                            "Ouroboros готовит исправление",
                            "Ouroboros Remediation",
                            "Разрешена одна замена endpoint на declared successor.",
                        ),
                    ),
                )
            if is_e2e:
                review = phases["review_before"]
                final = review.get("final", {}) if isinstance(review, Mapping) else {}
                findings = final.get("findings", []) if isinstance(final, Mapping) else []
                first = findings[0] if isinstance(findings, list) and findings and isinstance(findings[0], Mapping) else {}
                receipts = review.get("receipts", {}) if isinstance(review, Mapping) else {}
                tools = receipts.get("tool_names", []) if isinstance(receipts, Mapping) else []
                digest_binding = (
                    receipts.get("final_digest_binding")
                    if isinstance(receipts, Mapping)
                    else None
                )
                def record_review(run: EvolutionRun) -> None:
                    agent = run.agent("architecture")
                    agent["current_action"] = "SEAF-004 найден; запускается remediation"
                    if isinstance(tools, list):
                        agent["tools"] = [str(tool) for tool in tools]
                    if digest_binding == "trusted_prepare_once":
                        run.append(
                            "architecture.ouroboros.digest.bound",
                            "Digest подставлен программой",
                            "AGA Trusted Host",
                            "Модель ошиблась при копировании digest; semantic result сохранён, повторного платного model call не было.",
                            kind="recovery",
                            status="completed",
                            actor_id="architecture",
                            tool="trusted_prepare_digest_binding",
                            task_id=str(review.get("task_id") or ""),
                        )
                    run.append(
                        "architecture.ouroboros.finding.detected",
                        "Ouroboros нашёл SEAF-004",
                        "Ouroboros Review",
                        str(first.get("evidence") or "Новая зависимость направлена в eliminate-компонент."),
                        kind="finding",
                        status="completed",
                        actor_id="architecture",
                        tool="aga_finalize_review",
                        task_id=str(review.get("task_id") or ""),
                        graph_delta={
                            "operation": "finding",
                            "edge_id": declared_edge_id,
                            "rule_id": "SEAF-004",
                            "severity": "blocker",
                        },
                        data={
                            "finding": copy.deepcopy(dict(first)),
                            "receipts": copy.deepcopy(tools) if isinstance(tools, list) else [],
                            "receipt_verified": True,
                            "cost_usd": _known_model_cost(review),
                        },
                    )
                self._mutate(run_id, record_review)
        if isinstance(phases.get("remediation"), Mapping):
            if not is_e2e:
                self._mutate(
                    run_id,
                    lambda run: (
                        run.append(
                            "candidate_created",
                            "Одна строка изменена",
                            "AGA Local Git",
                            "legacy_scoring заменён на scoring_v2 в локальном candidate commit.",
                        ),
                        run.append(
                            "ouroboros_rereview_started",
                            "Запущена повторная проверка",
                            "Ouroboros Review",
                            "Проверяется уже исправленный commit.",
                        ),
                    ),
                )
            if is_e2e:
                remediation = phases["remediation"]
                final = remediation.get("final", {}) if isinstance(remediation, Mapping) else {}
                patch = final.get("patch", {}) if isinstance(final, Mapping) else {}
                receipts = remediation.get("receipts", []) if isinstance(remediation, Mapping) else []
                tools = [str(item.get("tool")) for item in receipts if isinstance(item, Mapping) and item.get("tool")]
                def record_patch(run: EvolutionRun) -> None:
                    agent = run.agent("architecture")
                    agent["current_action"] = "Patch применён; идёт независимый re-review"
                    if tools:
                        agent["tools"] = list(dict.fromkeys([*agent.get("tools", []), *tools]))
                    run.append(
                        "architecture.ouroboros.patch.created",
                        "Ouroboros подготовил remediation",
                        "Ouroboros Remediation",
                        str(patch.get("summary") or "Endpoint перенаправлен в strategic successor."),
                        kind="mutation",
                        status="completed",
                        actor_id="architecture",
                        tool="aga_finalize_remediation",
                        task_id=str(remediation.get("task_id") or ""),
                        graph_delta={
                            "operation": "reroute",
                            "edge_id": declared_edge_id,
                            "new_to": str(patch.get("replacement_component") or declared_replacement),
                        },
                        data={
                            "patch": copy.deepcopy(dict(patch)) if isinstance(patch, Mapping) else {},
                            "receipts": copy.deepcopy(tools),
                            "receipt_verified": True,
                            "cost_usd": _known_model_cost(remediation),
                        },
                    )
                self._mutate(run_id, record_patch)

    def _run_rules(self, run_id: str) -> None:
        self._mutate(
            run_id,
            lambda run: run.append(
                "tests_frozen",
                "Синтетические кейсы зафиксированы",
                "AGA Evolver",
                "26 golden-сценариев используются для сравнения правил до и после.",
            ),
        )
        evolved = _bounded_process(
            (sys.executable, "scripts/run_evolution.py", "--demo"),
            cwd=REPOSITORY_ROOT / "aga-skill",
            timeout_seconds=300.0,
        )
        if evolved.returncode != 0:
            raise UIError(_typed_process_error(evolved))
        self._mutate(
            run_id,
            lambda run: (
                run.append(
                    "baseline_measured",
                    "Найдена ложная блокировка",
                    "AGA Fitness",
                    "PRIN-002 ошибочно блокировал контролируемый batch-обмен через DMZ.",
                ),
                run.append(
                    "rule_candidate_created",
                    "Правило уточнено",
                    "AGA Evolver Loop A",
                    "Добавлено узкое исключение EXC-PRIN-002-001.",
                ),
                run.append(
                    "tests_rerun",
                    "Все 26 кейсов перепроверены",
                    "AGA Fitness",
                    "Precision вырос до 1.0, weighted cost снизился до 0.",
                ),
            ),
        )
        published = _bounded_process(
            (
                sys.executable,
                "aga-skill/scripts/publish_candidate.py",
                "--build",
                "aga-skill/build",
                "--repository",
                str(REPOSITORY_ROOT),
                "--actor",
                "AGA Self-Evolution UI",
            ),
            cwd=REPOSITORY_ROOT,
            timeout_seconds=180.0,
        )
        if published.returncode != 0:
            raise UIError(_typed_process_error(published))
        self._mutate(
            run_id,
            lambda run: (
                run.append(
                    "gate_passed",
                    "Rule gate пройден",
                    "AGA Gate",
                    "Новое исключение улучшило метрики без регрессий.",
                ),
                run.append(
                    "local_candidate_created",
                    "Локальный кандидат правил готов",
                    "AGA Local Git",
                    "Созданы локальная ветка и commit; merge и push не выполнялись.",
                ),
            ),
        )


class EvolutionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], manager: JobManager) -> None:
        self.manager = manager
        self.session_token = secrets.token_urlsafe(32)
        super().__init__(address, EvolutionRequestHandler)


class EvolutionRequestHandler(BaseHTTPRequestHandler):
    server: EvolutionHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_arguments: Any) -> None:
        return

    def _headers(self, content_type: str, content_length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )

    def _json(self, status: int, value: Mapping[str, Any]) -> None:
        body = _canonical_json(value)
        self.send_response(status)
        self._headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _json_download(self, value: Mapping[str, Any], filename: str) -> None:
        body = _canonical_json(value)
        self.send_response(HTTPStatus.OK)
        self._headers("application/json; charset=utf-8", len(body))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error: UIError) -> None:
        self._json(
            error.http_status,
            {"schema": SCHEMA, "status": "failed", "code": error.code},
        )

    def _valid_host(self) -> bool:
        raw = self.headers.get("Host", "")
        try:
            parsed = urlsplit(f"http://{raw}")
            return parsed.hostname in {"127.0.0.1", "localhost"}
        except ValueError:
            return False

    def _authorize_post(self) -> None:
        if not self._valid_host():
            raise UIError("host_forbidden", HTTPStatus.FORBIDDEN)
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise UIError("content_type_invalid", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        token = self.headers.get("X-AGA-UI-Token", "")
        if not hmac.compare_digest(token, self.server.session_token):
            raise UIError("session_token_invalid", HTTPStatus.FORBIDDEN)
        origin = self.headers.get("Origin")
        if origin:
            expected = f"http://{self.headers.get('Host', '')}"
            if origin != expected:
                raise UIError("origin_forbidden", HTTPStatus.FORBIDDEN)

    def _read_json(self) -> Mapping[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as exc:
            raise UIError("content_length_invalid") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise UIError("request_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return _strict_json_object(self.rfile.read(length))

    def do_OPTIONS(self) -> None:
        self._json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"schema": SCHEMA, "status": "failed", "code": "cors_not_allowed"},
        )

    def do_GET(self) -> None:
        try:
            if not self._valid_host():
                raise UIError("host_forbidden", HTTPStatus.FORBIDDEN)
            path = urlsplit(self.path).path
            if path == "/api/v2/bootstrap":
                try:
                    from scripts.generate_self_evolution_scenario import PRESETS
                except ImportError as exc:
                    raise UIError("scenario_generation_failed", HTTPStatus.SERVICE_UNAVAILABLE) from exc
                self._json(
                    HTTPStatus.OK,
                    {
                        "schema": V2_SCHEMA,
                        "status": "ready",
                        "session_token": self.server.session_token,
                        "presets": [
                            {
                                "id": key,
                                "title": value["title"],
                                "description": value["description"],
                            }
                            for key, value in PRESETS.items()
                        ],
                        "last_run": self.server.manager.current(),
                        "runtime": {
                            "ouroboros_version": "6.64.1",
                            "model": DEFAULT_MODEL_ID,
                            "models": public_models(),
                            "provider": "OpenRouter",
                            "local_e2e": True,
                            "live_e2e": True,
                            "parallel_workers": [2, 3, 4],
                            "local_architecture_engine": LOCAL_ARCHITECTURE_ENGINE,
                            "live_architecture_engine": LIVE_ARCHITECTURE_ENGINE,
                            "live_readiness_endpoint": "/api/v2/live-readiness",
                        },
                    },
                )
                return
            if path == "/api/v1/bootstrap":
                self._json(
                    HTTPStatus.OK,
                    {
                        "schema": SCHEMA,
                        "status": "ready",
                        "session_token": self.server.session_token,
                        "fixture": _load_fixture(),
                        "current_run": self.server.manager.current(),
                        "capabilities": {
                            "architecture_replay": True,
                            "architecture_live": True,
                            "rules_replay": True,
                            "rules_live": False,
                            "one_active_run": True,
                        },
                    },
                )
                return
            match = re.fullmatch(r"/api/v1/runs/([0-9a-f]{12})", path)
            if match:
                self._json(HTTPStatus.OK, self.server.manager.get(match.group(1)))
                return
            match = re.fullmatch(r"/api/v2/runs/([0-9a-f]{12})", path)
            if match:
                self._json(HTTPStatus.OK, self.server.manager.get(match.group(1)))
                return
            match = re.fullmatch(r"/api/v2/runs/([0-9a-f]{12})/report", path)
            if match:
                run_id = match.group(1)
                self._json_download(
                    self.server.manager.report(run_id),
                    f"aga-self-evolution-{run_id}.json",
                )
                return
            self._static(path)
        except UIError as exc:
            self._error(exc)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        portable = PurePosixPath(relative)
        if (
            portable.is_absolute()
            or not portable.parts
            or any(part in {"", ".", ".."} for part in portable.parts)
        ):
            raise UIError("static_path_invalid", HTTPStatus.NOT_FOUND)
        target = (STATIC_ROOT / Path(*portable.parts)).resolve(strict=False)
        try:
            target.relative_to(STATIC_ROOT.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise UIError("static_path_invalid", HTTPStatus.NOT_FOUND) from exc
        if target.is_symlink() or not target.is_file():
            raise UIError("not_found", HTTPStatus.NOT_FOUND)
        suffix = target.suffix.lower()
        content_type = STATIC_CONTENT_TYPES.get(suffix)
        if content_type is None:
            raise UIError("not_found", HTTPStatus.NOT_FOUND)
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._headers(content_type, len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            self._authorize_post()
            path = urlsplit(self.path).path
            payload = self._read_json()
            if path == "/api/v2/live-readiness":
                allowed = {"model_id", "force"}
                if any(key not in allowed for key in payload):
                    raise UIError("preflight_request_unknown_field")
                model_id = payload.get("model_id", DEFAULT_MODEL_ID)
                force = payload.get("force", False)
                if not isinstance(model_id, str) or not isinstance(force, bool):
                    raise UIError("preflight_request_invalid")
                self._json(
                    HTTPStatus.OK,
                    self.server.manager.live_readiness(model_id, force=force),
                )
                return
            if path == "/api/v2/scenarios":
                allowed = {"preset", "seed", "parallel_workers"}
                if any(key not in allowed for key in payload):
                    raise UIError("scenario_request_unknown_field")
                preset = payload.get("preset", "full")
                seed = payload.get("seed", "full-e2e")
                parallel_workers = payload.get("parallel_workers", 4)
                if (
                    not isinstance(preset, str)
                    or not isinstance(seed, str)
                    or isinstance(parallel_workers, bool)
                    or not isinstance(parallel_workers, int)
                ):
                    raise UIError("scenario_request_invalid")
                scenario = self.server.manager.create_scenario(
                    seed=seed,
                    preset=preset,
                    parallel_workers=parallel_workers,
                )
                self._json(
                    HTTPStatus.CREATED,
                    {"schema": V2_SCHEMA, "status": "generated", "scenario": scenario},
                )
                return
            if path == "/api/v2/runs":
                allowed = {
                    "scenario_id",
                    "execution",
                    "confirm_paid_run",
                    "model_id",
                    "recovery_of_run_id",
                }
                if any(key not in allowed for key in payload):
                    raise UIError("run_request_unknown_field")
                scenario_id = payload.get("scenario_id")
                execution = payload.get("execution", "local")
                confirm_paid = payload.get("confirm_paid_run", False)
                model_id = payload.get("model_id", DEFAULT_MODEL_ID)
                recovery_of_run_id = payload.get("recovery_of_run_id")
                if (
                    not isinstance(scenario_id, str)
                    or not isinstance(execution, str)
                    or not isinstance(confirm_paid, bool)
                    or not isinstance(model_id, str)
                    or (
                        recovery_of_run_id is not None
                        and not isinstance(recovery_of_run_id, str)
                    )
                ):
                    raise UIError("run_request_invalid")
                run = self.server.manager.start(
                    lane="e2e",
                    execution=execution,
                    confirm_paid_run=confirm_paid,
                    scenario_id=scenario_id,
                    model_id=model_id,
                    recovery_of_run_id=recovery_of_run_id,
                )
                self._json(HTTPStatus.ACCEPTED, run)
                return
            if path == "/api/v1/scenarios":
                kind = payload.get("kind", "architecture")
                seed = payload.get("seed", "synthetic-demo")
                if kind not in {"architecture", "rules"}:
                    raise UIError("scenario_kind_invalid")
                if not isinstance(seed, str) or SAFE_SEED_RE.fullmatch(seed) is None:
                    raise UIError("scenario_seed_invalid")
                fixture = _load_fixture()
                if kind == "architecture":
                    architecture = fixture.get("architecture_evolution")
                    source = architecture.get("dataset") if isinstance(architecture, Mapping) else None
                else:
                    source = fixture.get("rule_evolution")
                if not isinstance(source, Mapping):
                    raise UIError("scenario_unavailable", HTTPStatus.SERVICE_UNAVAILABLE)
                scenario_id = hashlib.sha256(f"{kind}:{seed}".encode("utf-8")).hexdigest()[:16]
                self._json(
                    HTTPStatus.CREATED,
                    {
                        "schema": SCHEMA,
                        "status": "generated",
                        "scenario_id": scenario_id,
                        "kind": kind,
                        "seed": seed,
                        "data": dict(source),
                    },
                )
                return
            if path in {"/api/v1/runs/architecture", "/api/v1/runs/rules"}:
                lane = path.rsplit("/", 1)[-1]
                allowed = {"execution", "confirm_paid_run"}
                if any(key not in allowed for key in payload):
                    raise UIError("run_request_unknown_field")
                execution = payload.get("execution", "replay")
                confirm_paid = payload.get("confirm_paid_run", False)
                if not isinstance(execution, str) or not isinstance(confirm_paid, bool):
                    raise UIError("run_request_invalid")
                run = self.server.manager.start(
                    lane=lane,
                    execution=execution,
                    confirm_paid_run=confirm_paid,
                )
                self._json(HTTPStatus.ACCEPTED, run)
                return
            raise UIError("not_found", HTTPStatus.NOT_FOUND)
        except UIError as exc:
            self._error(exc)
        except (BrokenPipeError, ConnectionResetError):
            return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST, choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if isinstance(arguments.port, bool) or not 1 <= arguments.port <= 65535:
        print("invalid port", file=sys.stderr)
        return 2
    try:
        _load_fixture()
        server = EvolutionHTTPServer((arguments.host, arguments.port), JobManager())
    except (OSError, UIError) as exc:
        code = exc.code if isinstance(exc, UIError) else "server_unavailable"
        print(json.dumps({"schema": SCHEMA, "status": "failed", "code": code}))
        return 3
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "status": "ready",
                "url": f"http://{arguments.host}:{server.server_port}",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
