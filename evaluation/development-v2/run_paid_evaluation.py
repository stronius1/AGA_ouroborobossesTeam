#!/usr/bin/env python3
"""Paid-guarded trusted Ouroboros runner for the complete development-v2 split.

Authorization, independent human review, and series freeze are checked before
materialization, preflight, provider configuration, or any case runner call.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import corpus_tool  # noqa: E402
import runner as scorer  # noqa: E402


CLI_SCHEMA = "aga.synthetic-development-paid-cli/v2"
ATTEMPT_SCHEMA = "aga.synthetic-development-attempt/v2"
ATTEMPT_TERMINAL_SCHEMA = "aga.synthetic-development-attempt-terminal/v2"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / ".aga-runs/development-v2/captures"
DEFAULT_STATE_ROOT = REPOSITORY_ROOT / ".aga-runs/development-v2/live-state"


class PaidEvaluationError(RuntimeError):
    def __init__(self, status: str, code: str) -> None:
        if status not in {"not_authorized", "not_configured", "failed"}:
            raise ValueError("invalid paid evaluation status")
        self.status = status
        self.code = code
        super().__init__(code)


def _timestamp(now: Callable[[], datetime]) -> str:
    value = now()
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaidEvaluationError("failed", "clock_not_utc")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _failure_timestamp(now: Callable[[], datetime], fallback: str) -> str:
    try:
        return _timestamp(now)
    except PaidEvaluationError:
        return fallback


def _output_path(
    value: Path, *, series_id: str, repeat_ordinal: int, capture_id: str
) -> Path:
    supplied = Path(value)
    candidate_raw = supplied if supplied.is_absolute() else REPOSITORY_ROOT / supplied
    canonical_raw = (
        DEFAULT_OUTPUT_ROOT
        / series_id
        / f"repeat-{repeat_ordinal:02d}-{capture_id}.json"
    )
    path = candidate_raw.resolve(strict=False)
    if path != canonical_raw.resolve(strict=False):
        raise PaidEvaluationError("not_authorized", "capture_output_path_must_be_canonical")
    cursor = candidate_raw
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise PaidEvaluationError("not_authorized", "capture_output_symlink_unsafe")
        if cursor.resolve(strict=False) == REPOSITORY_ROOT.resolve():
            break
        cursor = cursor.parent
    return path


def _atomic_write_new(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise PaidEvaluationError("failed", "capture_output_already_exists")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise PaidEvaluationError("failed", "capture_output_already_exists") from error
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _bounded_state_root(value: Path) -> Path:
    supplied = Path(value)
    candidate_raw = supplied if supplied.is_absolute() else REPOSITORY_ROOT / supplied
    approved_raw = DEFAULT_STATE_ROOT
    candidate = candidate_raw.resolve(strict=False)
    approved = approved_raw.resolve(strict=False)
    if candidate != approved:
        raise PaidEvaluationError("not_authorized", "state_root_must_be_canonical")
    cursor = approved_raw
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise PaidEvaluationError("not_authorized", "state_root_symlink_unsafe")
        if cursor.resolve(strict=False) == REPOSITORY_ROOT.resolve():
            break
        cursor = cursor.parent
    return approved


def _reserve_attempt(
    *, state_root: Path, series_id: str, repeat_ordinal: int, capture_id: str,
    measurement_identity: Mapping[str, Any], selection: Mapping[str, Any],
    started_at: str, key: bytes, attestation: Mapping[str, Any],
) -> tuple[Path, Path, str]:
    root = _bounded_state_root(state_root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink():
        raise PaidEvaluationError("not_authorized", "state_root_symlink_unsafe")
    series_root = root / series_id
    if series_root.is_symlink():
        raise PaidEvaluationError("not_authorized", "state_root_symlink_unsafe")
    series_root.mkdir(mode=0o700, exist_ok=True)
    attempt_root = series_root / f"repeat-{repeat_ordinal:02d}"
    try:
        attempt_root.mkdir(mode=0o700)
    except FileExistsError as error:
        raise PaidEvaluationError("failed", "repeat_ordinal_already_attempted") from error
    marker_unsigned = {
        "schema": ATTEMPT_SCHEMA,
        "status": "started_non_release",
        "release_evidence": False,
        "started_at": started_at,
        "series": {
            "series_id": series_id,
            "repeat_ordinal": repeat_ordinal,
            "capture_id": capture_id,
        },
        "measurement_identity": dict(measurement_identity),
        "selection": dict(selection),
    }
    marker_sha256 = _canonical_sha256(marker_unsigned)
    _atomic_write_new(
        attempt_root / "attempt.json",
        _attest_capture(marker_unsigned, key=key, attestation=attestation),
    )
    isolated_state_root = attempt_root / "state"
    isolated_state_root.mkdir(mode=0o700)
    return isolated_state_root, attempt_root, marker_sha256


def _write_attempt_terminal(
    *, attempt_root: Path, series_id: str, repeat_ordinal: int, capture_id: str,
    marker_sha256: str, finished_at: str, status: str, code: str,
    cases_completed: int, key: bytes, attestation: Mapping[str, Any],
) -> None:
    terminal = {
        "schema": ATTEMPT_TERMINAL_SCHEMA,
        "status": status,
        "release_evidence": False,
        "finished_at": finished_at,
        "series": {
            "series_id": series_id,
            "repeat_ordinal": repeat_ordinal,
            "capture_id": capture_id,
        },
        "attempt_marker_sha256": marker_sha256,
        "code": code,
        "cases_completed": cases_completed,
    }
    _atomic_write_new(
        attempt_root / "terminal.json",
        _attest_capture(terminal, key=key, attestation=attestation),
    )


def _active_runtime_identity(identity: Mapping[str, Any]) -> None:
    # Offline-only imports after owner/human/freeze authorization. They expose
    # pinned constants and never schedule a task or contact a provider.
    from scripts import ouroboros_preflight as preflight  # pylint: disable=import-outside-toplevel

    active = {
        "runtime_id": "ouroboros",
        "runtime_version": preflight.PINNED_VERSION,
        "runtime_source_commit": preflight.PINNED_SOURCE_COMMIT,
        "provider_id": preflight.EXPECTED_PROVIDER,
        "model_id": preflight.EXPECTED_MODEL,
    }
    if any(identity.get(field) != value for field, value in active.items()):
        raise PaidEvaluationError("not_authorized", "active_runtime_identity_mismatch")


def _attestation_key(
    value: Path | None, attestation: Mapping[str, Any]
) -> bytes:
    if value is None:
        raise PaidEvaluationError("not_authorized", "capture_attestation_key_required")
    supplied = Path(value)
    if supplied.is_symlink():
        raise PaidEvaluationError("not_authorized", "capture_attestation_key_unsafe")
    try:
        path = supplied.resolve(strict=True)
        path.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        pass
    except OSError as error:
        raise PaidEvaluationError("not_configured", "capture_attestation_key_unavailable") from error
    else:
        raise PaidEvaluationError("not_authorized", "capture_attestation_key_must_be_external")
    try:
        info = path.lstat()
        payload = path.read_bytes()
    except OSError as error:
        raise PaidEvaluationError("not_configured", "capture_attestation_key_unavailable") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_mode & 0o077
        or not 32 <= len(payload) <= 4096
    ):
        raise PaidEvaluationError("not_authorized", "capture_attestation_key_unsafe")
    if hashlib.sha256(payload).hexdigest() != attestation["key_sha256"]:
        raise PaidEvaluationError("not_authorized", "capture_attestation_key_mismatch")
    return payload


def _attest_capture(
    scored: Mapping[str, Any], *, key: bytes, attestation: Mapping[str, Any]
) -> dict[str, Any]:
    payload = json.dumps(
        scored, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        **dict(scored),
        "capture_attestation": {
            "scheme": "hmac-sha256",
            "key_id": attestation["key_id"],
            "signature": hmac.new(key, payload, hashlib.sha256).hexdigest(),
        },
    }


def _project_final(
    value: Mapping[str, Any], *, auxiliary_rule_ids: frozenset[str] = frozenset()
) -> dict[str, Any]:
    status = value.get("status")
    normalized_status = "complete" if status in {"complete", "completed"} else "incomplete" if status == "incomplete" else "error"
    raw_findings = value.get("findings")
    if not isinstance(raw_findings, list):
        raise PaidEvaluationError("failed", "trusted_final_findings_invalid")
    fields = (
        "rule_id", "severity", "confidence", "artifact", "location", "evidence",
        "source_ref", "suggested_fix",
    )
    findings: list[dict[str, Any]] = []
    for raw in raw_findings:
        if not isinstance(raw, Mapping) or any(field not in raw for field in fields):
            raise PaidEvaluationError("failed", "trusted_final_finding_contract_mismatch")
        if raw["rule_id"] in auxiliary_rule_ids:
            continue
        findings.append({field: raw[field] for field in fields})
    return {"status": normalized_status, "verdict": value.get("verdict"), "findings": findings}


def _validate_case_execution(
    result: Mapping[str, Any], *, case: Mapping[str, Any], identity: Mapping[str, Any]
) -> None:
    execution = result.get("execution")
    usage = result.get("model_usage")
    if not isinstance(execution, Mapping) or set(execution) != {
        "kind", "model_task_scheduled"
    } or not isinstance(usage, Mapping):
        raise PaidEvaluationError("failed", "trusted_execution_contract_mismatch")
    if usage.get("provider") != identity["provider_id"] or usage.get("model") != identity["model_id"]:
        raise PaidEvaluationError("failed", "trusted_execution_contract_mismatch")
    expected_incomplete = case["expected"]["status"] == "incomplete"
    if expected_incomplete:
        final = result.get("final")
        attestation = result.get("host_attestation")
        raw_final_errors = final.get("analysis_errors") if isinstance(final, Mapping) else None
        final_error_codes = (
            [item.get("code") for item in raw_final_errors]
            if isinstance(raw_final_errors, list)
            and all(isinstance(item, Mapping) for item in raw_final_errors)
            else None
        )
        expected_context = case["expected"]["unresolved_context"]
        expected_referenced = {
            item["reference"]
            for item in expected_context
            if item["kind"] in {"target", "context"}
        }
        expected_unresolved = {
            item["reference"]
            for item in expected_context
            if item["kind"] in {"target", "context"}
        }
        expected_error_codes = {
            "unresolved_entity_references"
            if item["kind"] in {"target", "context"}
            else "extension_field_missing"
            for item in expected_context
        }
        expected_auxiliary = case["expected"].get("auxiliary_findings", [])
        raw_final_findings = final.get("findings") if isinstance(final, Mapping) else None
        auxiliary_matches = bool(
            isinstance(raw_final_findings, list)
            and len(raw_final_findings) == len(expected_auxiliary)
            and all(
                isinstance(actual, Mapping)
                and actual.get("rule_id") == expected.get("rule_id")
                and actual.get("severity") == expected.get("severity")
                and actual.get("artifact") == expected.get("artifact")
                and actual.get("location") == expected.get("location")
                and isinstance(actual.get("evidence"), str)
                and expected.get("evidence_contains", "").casefold()
                in actual["evidence"].casefold()
                and actual.get("source_ref")
                == "aga-skill/rules/seaf-checks.yaml#/rules/0"
                for expected, actual in zip(expected_auxiliary, raw_final_findings)
            )
        )
        projected_final = (
            {**dict(final), "findings": []} if isinstance(final, Mapping) else {}
        )
        if (
            execution != {
                "kind": "trusted_host_prepare_incomplete",
                "model_task_scheduled": False,
            }
            or result.get("status") != "incomplete"
            or result.get("receipts") is not None
            or not isinstance(final, Mapping)
            or final.get("status") != "incomplete"
            or final.get("verdict") != "incomplete"
            or not auxiliary_matches
            or final.get("human_review_required") is not True
            or not isinstance(attestation, Mapping)
            or set(attestation)
            != {
                "kind", "mcp_tool_invoked", "review_id_sha256",
                "prepare_args_sha256", "prepare_output_sha256",
                "service_final_output_sha256", "projection_output_sha256",
                "prepare_analysis_error_codes", "analysis_error_codes",
                "deterministic_finding_rule_ids", "auxiliary_deterministic_findings",
                "referenced_entity_ids",
                "unresolved_reference_ids",
            }
            or attestation.get("kind") != "trusted_host_prepare_attestation"
            or attestation.get("mcp_tool_invoked") is not False
            or any(
                not isinstance(attestation.get(field), str)
                or corpus_tool.SHA256_RE.fullmatch(attestation[field]) is None
                for field in (
                    "review_id_sha256", "prepare_args_sha256", "prepare_output_sha256",
                    "service_final_output_sha256", "projection_output_sha256",
                )
            )
            or attestation.get("review_id_sha256") != result.get("review_id_sha256")
            or attestation.get("service_final_output_sha256") != _canonical_sha256(final)
            or attestation.get("projection_output_sha256")
            != _canonical_sha256(projected_final)
            or final_error_codes is None
            or attestation.get("analysis_error_codes") != final_error_codes
            or not isinstance(attestation.get("prepare_analysis_error_codes"), list)
            or not attestation["prepare_analysis_error_codes"]
            or not set(attestation["prepare_analysis_error_codes"]).issubset(
                attestation["analysis_error_codes"]
            )
            or not isinstance(attestation.get("analysis_error_codes"), list)
            or not attestation["analysis_error_codes"]
            or any(not isinstance(value, str) or not value for value in attestation["analysis_error_codes"])
            or not isinstance(attestation.get("deterministic_finding_rule_ids"), list)
            or any(
                not isinstance(value, str) or not value
                for value in attestation["deterministic_finding_rule_ids"]
            )
            or attestation["deterministic_finding_rule_ids"]
            != [item["rule_id"] for item in expected_auxiliary]
            or attestation.get("auxiliary_deterministic_findings")
            != raw_final_findings
            or not isinstance(attestation.get("referenced_entity_ids"), list)
            or not isinstance(attestation.get("unresolved_reference_ids"), list)
            or any(
                not isinstance(value, str) or not value
                for field in ("referenced_entity_ids", "unresolved_reference_ids")
                for value in attestation[field]
            )
            or not set(attestation["unresolved_reference_ids"]).issubset(
                attestation["referenced_entity_ids"]
            )
            or not expected_referenced.issubset(attestation["referenced_entity_ids"])
            or not expected_unresolved.issubset(attestation["unresolved_reference_ids"])
            or not expected_error_codes.issubset(
                attestation["prepare_analysis_error_codes"]
            )
            or usage.get("call_count") != 0
            or usage.get("prompt_tokens") != 0
            or usage.get("completion_tokens") != 0
            or usage.get("known_cost_usd") != 0.0
            or usage.get("cost_complete") is not True
            or usage.get("unresolved_upper_bound_usd") != 0.0
            or usage.get("unknown_unmetered") != 0
        ):
            raise PaidEvaluationError("failed", "trusted_host_incomplete_contract_mismatch")
        return
    call_count = usage.get("call_count")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    known_cost = usage.get("known_cost_usd")
    if (
        execution
        != {"kind": "ouroboros_model_review", "model_task_scheduled": True}
        or result.get("host_attestation") is not None
        or not isinstance(result.get("receipts"), Mapping)
        or isinstance(call_count, bool)
        or not isinstance(call_count, int)
        or call_count < 1
        or isinstance(prompt_tokens, bool)
        or not isinstance(prompt_tokens, int)
        or prompt_tokens < 0
        or isinstance(completion_tokens, bool)
        or not isinstance(completion_tokens, int)
        or completion_tokens < 0
        or isinstance(known_cost, bool)
        or not isinstance(known_cost, (int, float))
        or not math.isfinite(float(known_cost))
        or float(known_cost) < 0
        or usage.get("cost_complete") is not True
        or usage.get("unresolved_upper_bound_usd") != 0.0
        or usage.get("unknown_unmetered") != 0
    ):
        raise PaidEvaluationError("failed", "trusted_model_execution_contract_mismatch")


def _default_case_runner(**arguments: Any) -> Mapping[str, Any]:
    # Imported only after all paid/human/series gates pass.
    from scripts.run_ouroboros_live_review import (  # pylint: disable=import-outside-toplevel
        LiveReviewError,
        run_live_review,
    )

    try:
        return run_live_review(**arguments)
    except LiveReviewError as error:
        status = "not_configured" if error.status == "not_configured" else "failed"
        raise PaidEvaluationError(status, error.code) from error


def run_paid_evaluation(
    *,
    confirmed: bool,
    selection: str,
    repeat_ordinal: int | None = None,
    capture_id: str | None = None,
    attestation_key_file: Path | None = None,
    output: Path | None = None,
    state_root: Path = DEFAULT_STATE_ROOT,
    case_runner: Callable[..., Mapping[str, Any]] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> Mapping[str, Any]:
    # Ordering is a security contract: these checks precede every expensive or
    # externally configured operation and even precede lazy import of live code.
    if confirmed is not True:
        raise PaidEvaluationError("not_authorized", "explicit_paid_confirmation_required")
    if selection != "development":
        raise PaidEvaluationError("not_authorized", "complete_development_selection_required")
    if (
        isinstance(repeat_ordinal, bool)
        or not isinstance(repeat_ordinal, int)
        or not 1 <= repeat_ordinal <= 5
    ):
        raise PaidEvaluationError("not_authorized", "repeat_ordinal_1_to_5_required")
    try:
        safe_capture_id = corpus_tool._text(capture_id, "capture_id", limit=128)
    except (TypeError, ValueError) as error:
        raise PaidEvaluationError("not_authorized", "capture_id_required") from error
    if corpus_tool.SERIES_ID_RE.fullmatch(safe_capture_id) is None:
        raise PaidEvaluationError("not_authorized", "capture_id_invalid")
    try:
        lock = corpus_tool.verify_lock(ROOT, require_measurement_ready=True)
    except (OSError, TypeError, ValueError) as error:
        code = (
            "independent_human_review_required"
            if "human review" in str(error)
            else "measurement_series_freeze_required"
            if "series" in str(error)
            else "measurement_lock_failed"
        )
        raise PaidEvaluationError("not_authorized", code) from error
    freeze = lock["series_freeze"]
    identity = freeze["measurement_identity"]
    _active_runtime_identity(identity)
    key = _attestation_key(attestation_key_file, freeze["capture_attestation"])
    config = corpus_tool._measurement_config(ROOT)
    timeout_per_case = float(config["timeout_per_case_seconds"])
    target = _output_path(
        Path(output)
        if output is not None
        else DEFAULT_OUTPUT_ROOT
        / str(freeze["series_id"])
        / f"repeat-{repeat_ordinal:02d}-{safe_capture_id}.json",
        series_id=str(freeze["series_id"]),
        repeat_ordinal=repeat_ordinal,
        capture_id=safe_capture_id,
    )
    if target.exists() or target.is_symlink():
        raise PaidEvaluationError("failed", "capture_output_already_exists")
    safe_state_root = _bounded_state_root(state_root)
    cases = corpus_tool.load_cases(ROOT)
    if len(cases) != 48:
        raise PaidEvaluationError("failed", "complete_selection_mismatch")
    selection_contract = corpus_tool.measurement_selection(cases)
    started_at = _timestamp(now)
    isolated_state_root, attempt_root, marker_sha256 = _reserve_attempt(
        state_root=safe_state_root,
        series_id=str(freeze["series_id"]),
        repeat_ordinal=repeat_ordinal,
        capture_id=safe_capture_id,
        measurement_identity=identity,
        selection=selection_contract,
        started_at=started_at,
        key=key,
        attestation=freeze["capture_attestation"],
    )
    live = case_runner or _default_case_runner
    responses: list[Mapping[str, Any]] = []
    task_ids: set[str] = set()
    review_ids: set[str] = set()
    cases_completed = 0
    captured_at: str | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="aga-development-v2-paid-") as raw:
            materialized_root = Path(raw)
            for case in cases:
                revision = corpus_tool.materialize_case(
                    case["id"], materialized_root / case["id"], root=ROOT
                )
                started = time.monotonic()
                try:
                    result = live(
                        repository=Path(revision["repository"]),
                        repository_id=case["id"],
                        base=revision["base"],
                        head=revision["head"],
                        idempotency_key=(
                            f"{freeze['series_id']}:{repeat_ordinal}:{safe_capture_id}:{case['id']}"
                        ),
                        timeout_seconds=float(timeout_per_case),
                        state_root=isolated_state_root,
                    )
                except PaidEvaluationError:
                    raise
                except Exception as error:
                    raise PaidEvaluationError("failed", "trusted_case_runner_failed") from error
                if (
                    not isinstance(result, Mapping)
                    or result.get("repository_id") != case["id"]
                    or result.get("base") != revision["base"]
                    or result.get("head") != revision["head"]
                    or not isinstance(result.get("final"), Mapping)
                    or result.get("reused") is not False
                    or result.get("runtime")
                    != {
                        "name": identity["runtime_id"],
                        "version": identity["runtime_version"],
                        "source_commit": identity["runtime_source_commit"],
                    }
                    or result.get("provider") != identity["provider_id"]
                    or result.get("model") != identity["model_id"]
                ):
                    raise PaidEvaluationError("failed", "trusted_capture_contract_mismatch")
                _validate_case_execution(result, case=case, identity=identity)
                task_id = result.get("task_id")
                review_id = result.get("review_id_sha256")
                if (
                    not isinstance(task_id, str)
                    or not task_id
                    or task_id in task_ids
                    or not isinstance(review_id, str)
                    or corpus_tool.SHA256_RE.fullmatch(review_id) is None
                    or review_id in review_ids
                ):
                    raise PaidEvaluationError("failed", "trusted_capture_identity_reused")
                task_ids.add(task_id)
                review_ids.add(review_id)
                responses.append(
                    {
                        "case_id": case["id"], "base_revision": revision["base"],
                        "head_revision": revision["head"],
                        "latency_ms": max(0.0, (time.monotonic() - started) * 1000.0),
                        "raw_sanitized": {
                            "task_id": result.get("task_id"),
                            "review_id_sha256": result.get("review_id_sha256"),
                            "receipts": result.get("receipts"),
                            "host_attestation": result.get("host_attestation"),
                            "execution": result.get("execution"),
                            "model_usage": result.get("model_usage"),
                        },
                        "normalized": _project_final(
                            result["final"],
                            auxiliary_rule_ids=frozenset(
                                item["rule_id"]
                                for item in case["expected"].get("auxiliary_findings", [])
                            ),
                        ),
                    }
                )
                cases_completed += 1
        captured_at = _timestamp(now)
        try:
            scored_unsigned = scorer.score_trusted_responses(
                responses,
                captured_at=captured_at,
                series_id=str(freeze["series_id"]),
                capture_id=safe_capture_id,
                repeat_ordinal=repeat_ordinal,
                measurement_identity=identity,
            )
        except (OSError, TypeError, ValueError) as error:
            raise PaidEvaluationError("failed", "trusted_scoring_failed") from error
        scored_unsigned = {
            **dict(scored_unsigned),
            "attempt": {
                "marker_sha256": marker_sha256,
                "started_at": started_at,
                "cases_completed": cases_completed,
            },
        }
        scored = _attest_capture(
            scored_unsigned, key=key, attestation=freeze["capture_attestation"]
        )
        # Every completed authorized repeat is retained for worst-case/flapping
        # analysis. A failed gate remains non-release and cannot qualify a series.
        _atomic_write_new(target, scored)
        if scored.get("gate", {}).get("evaluation_passed") is not True:
            raise PaidEvaluationError("failed", "development_gate_failed")
    except PaidEvaluationError as error:
        try:
            _write_attempt_terminal(
                attempt_root=attempt_root,
                series_id=str(freeze["series_id"]),
                repeat_ordinal=repeat_ordinal,
                capture_id=safe_capture_id,
                marker_sha256=marker_sha256,
                finished_at=captured_at or _failure_timestamp(now, started_at),
                status="failed_non_release",
                code=error.code,
                cases_completed=cases_completed,
                key=key,
                attestation=freeze["capture_attestation"],
            )
        except (OSError, TypeError, ValueError, PaidEvaluationError) as terminal_error:
            raise PaidEvaluationError("failed", "attempt_terminal_write_failed") from terminal_error
        raise
    except Exception as error:
        try:
            _write_attempt_terminal(
                attempt_root=attempt_root,
                series_id=str(freeze["series_id"]),
                repeat_ordinal=repeat_ordinal,
                capture_id=safe_capture_id,
                marker_sha256=marker_sha256,
                finished_at=captured_at or _failure_timestamp(now, started_at),
                status="failed_non_release",
                code="internal_paid_evaluation_error",
                cases_completed=cases_completed,
                key=key,
                attestation=freeze["capture_attestation"],
            )
        except (OSError, TypeError, ValueError, PaidEvaluationError) as terminal_error:
            raise PaidEvaluationError("failed", "attempt_terminal_write_failed") from terminal_error
        raise PaidEvaluationError("failed", "internal_paid_evaluation_error") from error
    _write_attempt_terminal(
        attempt_root=attempt_root,
        series_id=str(freeze["series_id"]),
        repeat_ordinal=repeat_ordinal,
        capture_id=safe_capture_id,
        marker_sha256=marker_sha256,
        finished_at=captured_at,
        status="completed_non_release",
        code="ok",
        cases_completed=cases_completed,
        key=key,
        attestation=freeze["capture_attestation"],
    )
    return scored


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", choices=("development",), required=True)
    parser.add_argument("--confirm-paid-run", action="store_true")
    parser.add_argument("--repeat-ordinal", type=int)
    parser.add_argument("--capture-id")
    parser.add_argument("--attestation-key-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    return parser


def _emit(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_paid_run:
        _emit({"schema": CLI_SCHEMA, "status": "not_authorized", "code": "explicit_paid_confirmation_required"})
        return 2
    try:
        result = run_paid_evaluation(
            confirmed=True, selection=args.selection, output=args.output,
            repeat_ordinal=args.repeat_ordinal, capture_id=args.capture_id,
            attestation_key_file=args.attestation_key_file,
            state_root=args.state_root,
        )
    except PaidEvaluationError as error:
        _emit({"schema": CLI_SCHEMA, "status": error.status, "code": error.code})
        return 2 if error.status in {"not_authorized", "not_configured"} else 3
    except Exception:
        _emit({"schema": CLI_SCHEMA, "status": "failed", "code": "internal_paid_evaluation_error"})
        return 3
    _emit(
        {
            "schema": CLI_SCHEMA, "status": "passed", "code": "ok",
            "cases_evaluated": result["overall"]["cases_evaluated"],
            "series": result["series"],
            "release_evidence": False,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
