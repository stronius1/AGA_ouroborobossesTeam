#!/usr/bin/env python3
"""Offline scorer and trusted in-memory scorer for development-v2.

Fixture bundles are explicitly non-release.  Trusted scoring accepts only an
in-memory complete development selection and additionally requires the human
review plus series-freeze gate.  This module never starts a model/API call.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import corpus_tool  # noqa: E402


FIXTURE_SCHEMA = "aga.synthetic-development-fixture-bundle/v2"
RESULT_SCHEMA = "aga.synthetic-development-results/v2"
SERIES_RESULT_SCHEMA = "aga.synthetic-development-series-results/v2"
CAPTURED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SOURCE_REFS = {
    "PRIN-004": "aga-skill/rules/principles.yaml#/rules/3",
    "PRIN-005": "aga-skill/rules/principles.yaml#/rules/4",
    "PRIN-006": "aga-skill/rules/principles.yaml#/rules/5",
    "PRIN-007": "aga-skill/rules/principles.yaml#/rules/6",
    "SEAF-004": "workspace/aga-extension.yaml#/entities/components/schema",
}
FORBIDDEN_RAW_KEYS = frozenset(
    {
        "authorization", "cookie", "credentials", "developer_prompt", "messages",
        "password", "prompt", "raw_prompt", "secret", "system_prompt", "token",
        "access_token", "refresh_token",
    }
)
TRUSTED_RAW_FIELDS = {
    "task_id", "review_id_sha256", "receipts", "host_attestation",
    "execution", "model_usage",
}
TRUSTED_USAGE_FIELDS = {
    "provider", "model", "call_count", "prompt_tokens", "completion_tokens",
    "known_cost_usd", "cost_complete", "unresolved_upper_bound_usd",
    "unknown_unmetered",
}
HOST_ATTESTATION_FIELDS = {
    "kind", "mcp_tool_invoked", "review_id_sha256", "prepare_args_sha256",
    "prepare_output_sha256", "service_final_output_sha256",
    "projection_output_sha256", "prepare_analysis_error_codes",
    "analysis_error_codes", "deterministic_finding_rule_ids",
    "auxiliary_deterministic_findings", "referenced_entity_ids",
    "unresolved_reference_ids",
}
REVIEW_TOOL_NAMES = {
    "aga_prepare_review", "aga_seaf_lookup", "aga_parse_diagram",
    "aga_finalize_review",
}


def _exact(value: Any, fields: set[str], context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{context} must contain exactly {sorted(fields)}")
    return value


def _scan_sanitized(value: Any, context: str = "raw_sanitized") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{context} contains a non-string key")
            if key.strip().lower().replace("-", "_") in FORBIDDEN_RAW_KEYS:
                raise ValueError(f"{context} contains forbidden field {key!r}")
            _scan_sanitized(item, f"{context}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_sanitized(item, f"{context}[{index}]")
        return
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    raise ValueError(f"{context} is not JSON-compatible")


def _validate_normalized(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        root = _exact(value, {"status", "verdict", "findings"}, "normalized")
        if root["status"] not in {"complete", "incomplete", "error"}:
            raise ValueError("normalized.status is invalid")
        if root["verdict"] not in {
            "approve", "approve_with_warnings", "request_changes_escalate", "incomplete"
        }:
            raise ValueError("normalized.verdict is invalid")
        if root["status"] == "complete" and root["verdict"] == "incomplete":
            raise ValueError("complete response cannot use incomplete verdict")
        if root["status"] in {"incomplete", "error"} and root["verdict"] != "incomplete":
            raise ValueError("incomplete/error response must fail closed")
        if not isinstance(root["findings"], list) or len(root["findings"]) > 100:
            raise ValueError("normalized.findings must be a list of at most 100")
        findings: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        fields = {
            "rule_id", "severity", "confidence", "artifact", "location", "evidence",
            "source_ref", "suggested_fix",
        }
        for index, raw in enumerate(root["findings"]):
            finding = _exact(raw, fields, f"normalized.findings[{index}]")
            rule_id = finding["rule_id"]
            if rule_id not in corpus_tool.RULE_SEVERITY:
                raise ValueError(f"normalized.findings[{index}].rule_id is invalid")
            if finding["severity"] != corpus_tool.RULE_SEVERITY[rule_id]:
                raise ValueError(f"normalized.findings[{index}].severity is invalid")
            confidence = finding["confidence"]
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
                raise ValueError(f"normalized.findings[{index}].confidence is invalid")
            artifact = corpus_tool._safe_path(finding["artifact"], "normalized artifact")
            location = corpus_tool._text(finding["location"], "normalized location", limit=500)
            corpus_tool._decode_pointer(location)
            evidence = corpus_tool._text(finding["evidence"], "normalized evidence", limit=4_000)
            if finding["source_ref"] != SOURCE_REFS[rule_id]:
                raise ValueError(f"normalized.findings[{index}].source_ref is not trusted")
            if not isinstance(finding["suggested_fix"], str):
                raise ValueError(f"normalized.findings[{index}].suggested_fix must be text")
            key = (rule_id, artifact, location)
            if key in seen:
                raise ValueError(f"normalized.findings[{index}] duplicates a finding")
            seen.add(key)
            findings.append(
                {
                    "rule_id": rule_id, "severity": finding["severity"],
                    "confidence": float(confidence), "artifact": artifact,
                    "location": location, "evidence": evidence,
                    "source_ref": finding["source_ref"],
                    "suggested_fix": finding["suggested_fix"],
                }
            )
        return {"status": root["status"], "verdict": root["verdict"], "findings": findings}, []
    except (KeyError, TypeError, ValueError) as error:
        return None, [str(error)]


def _grounded(case: Mapping[str, Any], finding: Mapping[str, Any]) -> tuple[bool, str]:
    documents = corpus_tool.native_state(case, "head")
    artifact = finding["artifact"]
    if artifact not in documents:
        return False, "artifact is absent from the materialized head"
    try:
        corpus_tool.pointer_value(
            corpus_tool._binding_document(artifact, documents[artifact]), finding["location"]
        )
    except ValueError:
        return False, "JSON Pointer does not resolve in the materialized head"
    return True, "artifact and JSON Pointer resolve in the materialized head"


def _matches(predicted: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return (
        predicted["rule_id"] == expected["rule_id"]
        and predicted["severity"] == expected["severity"]
        and predicted["artifact"] == expected["artifact"]
        and predicted["location"] == expected["location"]
        and expected["evidence_contains"].casefold() in predicted["evidence"].casefold()
    )


def _auxiliary_matches(
    case: Mapping[str, Any], response: Mapping[str, Any]
) -> bool:
    expected = case["expected"].get("auxiliary_findings", [])
    raw = response.get("raw_sanitized")
    host = raw.get("host_attestation") if isinstance(raw, Mapping) else None
    actual = (
        host.get("auxiliary_deterministic_findings")
        if isinstance(host, Mapping)
        else None
    )
    if not expected:
        return actual is None or actual == [] or actual == ()
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    return all(
        isinstance(finding, Mapping)
        and finding.get("rule_id") == locked["rule_id"]
        and finding.get("severity") == locked["severity"]
        and finding.get("artifact") == locked["artifact"]
        and finding.get("location") == locked["location"]
        and isinstance(finding.get("evidence"), str)
        and locked["evidence_contains"].casefold() in finding["evidence"].casefold()
        and finding.get("source_ref")
        == "aga-skill/rules/seaf-checks.yaml#/rules/0"
        for locked, finding in zip(expected, actual)
    )


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and corpus_tool.SHA256_RE.fullmatch(value) is not None


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _trusted_usage_matches(
    usage: Any, *, identity: Mapping[str, Any], zero: bool,
) -> bool:
    if not isinstance(usage, Mapping) or set(usage) != TRUSTED_USAGE_FIELDS:
        return False
    if (
        usage.get("provider") != identity.get("provider_id")
        or usage.get("model") != identity.get("model_id")
        or usage.get("cost_complete") is not True
        or not _finite_number(usage.get("known_cost_usd"))
        or float(usage["known_cost_usd"]) < 0.0
        or not _finite_number(usage.get("unresolved_upper_bound_usd"))
        or float(usage["unresolved_upper_bound_usd"]) != 0.0
        or isinstance(usage.get("unknown_unmetered"), bool)
        or not isinstance(usage.get("unknown_unmetered"), int)
        or usage["unknown_unmetered"] != 0
    ):
        return False
    for field in ("call_count", "prompt_tokens", "completion_tokens"):
        value = usage.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
    if zero:
        return (
            usage["call_count"] == 0
            and usage["prompt_tokens"] == 0
            and usage["completion_tokens"] == 0
            and float(usage["known_cost_usd"]) == 0.0
        )
    return usage["call_count"] >= 1


def _trusted_receipts_match(receipts: Any, *, review_id_sha256: str) -> bool:
    if not isinstance(receipts, Mapping) or set(receipts) != {
        "review_id_sha256", "tool_names", "final_digest_binding", "prepare", "finalize",
    }:
        return False
    names = receipts.get("tool_names")
    prepare = receipts.get("prepare")
    finalize = receipts.get("finalize")
    digest_binding = receipts.get("final_digest_binding")
    if (
        receipts.get("review_id_sha256") != review_id_sha256
        or not isinstance(digest_binding, str)
        or digest_binding not in {"none", "trusted_prepare_once"}
        or not isinstance(names, list)
        or len(names) < 2
        or names[0] != "aga_prepare_review"
        or names[-1] != "aga_finalize_review"
        or any(not isinstance(name, str) or name not in REVIEW_TOOL_NAMES for name in names)
        or names.count("aga_prepare_review") != 1
        or names.count("aga_finalize_review") != 1
        or not isinstance(prepare, Mapping)
        or set(prepare) != {"args_sha256", "output_sha256", "status"}
        or not isinstance(finalize, Mapping)
        or set(finalize) != {"args_sha256", "output_sha256", "status"}
        or prepare.get("status") != "ready"
        or finalize.get("status") != "completed"
    ):
        return False
    return all(
        _sha256(receipt.get(field))
        for receipt in (prepare, finalize)
        for field in ("args_sha256", "output_sha256")
    )


def _trusted_host_attestation_matches(
    case: Mapping[str, Any], response: Mapping[str, Any], host: Any,
) -> bool:
    if not isinstance(host, Mapping) or set(host) != HOST_ATTESTATION_FIELDS:
        return False
    expected_context = case["expected"]["unresolved_context"]
    expected_prepare_codes = [
        "unresolved_entity_references"
        if item["kind"] in {"target", "context"}
        else "extension_field_missing"
        for item in expected_context
    ]
    expected_references = {
        item["reference"]
        for item in expected_context
        if item["kind"] in {"target", "context"}
    }
    expected_auxiliary = case["expected"].get("auxiliary_findings", [])
    referenced = host.get("referenced_entity_ids")
    unresolved = host.get("unresolved_reference_ids")
    if (
        host.get("kind") != "trusted_host_prepare_attestation"
        or host.get("mcp_tool_invoked") is not False
        or host.get("review_id_sha256") != response.get("raw_sanitized", {}).get(
            "review_id_sha256"
        )
        or any(
            not _sha256(host.get(field))
            for field in (
                "review_id_sha256", "prepare_args_sha256", "prepare_output_sha256",
                "service_final_output_sha256", "projection_output_sha256",
            )
        )
        or host.get("prepare_analysis_error_codes") != expected_prepare_codes
        or host.get("analysis_error_codes")
        != [*expected_prepare_codes, "semantic_unavailable"]
        or host.get("deterministic_finding_rule_ids")
        != [item["rule_id"] for item in expected_auxiliary]
        or not _auxiliary_matches(case, response)
        or not isinstance(referenced, list)
        or not isinstance(unresolved, list)
        or any(not isinstance(value, str) or not value for value in [*referenced, *unresolved])
        or len(referenced) != len(set(referenced))
        or len(unresolved) != len(set(unresolved))
        or not set(unresolved).issubset(referenced)
        or not expected_references.issubset(referenced)
        or not expected_references.issubset(unresolved)
    ):
        return False
    return True


def _trusted_execution_matches(
    case: Mapping[str, Any], response: Mapping[str, Any], identity: Mapping[str, Any],
) -> bool:
    raw = response.get("raw_sanitized")
    if (
        not isinstance(raw, Mapping)
        or set(raw) != TRUSTED_RAW_FIELDS
        or not isinstance(raw.get("task_id"), str)
        or not raw["task_id"]
        or not _sha256(raw.get("review_id_sha256"))
    ):
        return False
    if case["expected"]["status"] == "incomplete":
        return bool(
            raw.get("execution")
            == {
                "kind": "trusted_host_prepare_incomplete",
                "model_task_scheduled": False,
            }
            and raw.get("receipts") is None
            and _trusted_host_attestation_matches(
                case, response, raw.get("host_attestation")
            )
            and _trusted_usage_matches(
                raw.get("model_usage"), identity=identity, zero=True
            )
        )
    return bool(
        raw.get("execution")
        == {"kind": "ouroboros_model_review", "model_task_scheduled": True}
        and raw.get("host_attestation") is None
        and _trusted_receipts_match(
            raw.get("receipts"), review_id_sha256=raw["review_id_sha256"]
        )
        and _trusted_usage_matches(
            raw.get("model_usage"), identity=identity, zero=False
        )
    )


def _score_case(
    case: Mapping[str, Any], response: Mapping[str, Any],
    *, trusted_identity: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized, errors = _validate_normalized(response["normalized"])
    predicted = normalized["findings"] if normalized is not None else []
    evidence_checks: list[dict[str, Any]] = []
    grounded_indexes: set[int] = set()
    for index, finding in enumerate(predicted):
        valid, reason = _grounded(case, finding)
        if valid:
            grounded_indexes.add(index)
        evidence_checks.append(
            {"finding_index": index, "rule_id": finding["rule_id"], "valid": valid, "reason": reason}
        )
    unmatched = set(range(len(predicted)))
    tp: list[dict[str, Any]] = []
    fn: list[dict[str, Any]] = []
    for expected in case["expected"]["findings"]:
        match = next(
            (index for index in sorted(unmatched & grounded_indexes) if _matches(predicted[index], expected)),
            None,
        )
        if match is None:
            fn.append(dict(expected))
        else:
            unmatched.remove(match)
            tp.append(dict(expected))
    fp = [predicted[index] for index in sorted(unmatched)]
    raw = response["normalized"]
    raw_status = raw.get("status") if isinstance(raw, Mapping) else None
    raw_verdict = raw.get("verdict") if isinstance(raw, Mapping) else None
    status_ok = raw_status == case["expected"]["status"]
    outcome_ok = raw_verdict == case["expected"]["verdict"]
    invalid_evidence = sum(not item["valid"] for item in evidence_checks)
    auxiliary_ok = _auxiliary_matches(case, response)
    trusted_execution_ok = bool(
        trusted_identity is None
        or _trusted_execution_matches(case, response, trusted_identity)
    )
    invalid_or_hallucinated_evidence = invalid_evidence + int(
        not auxiliary_ok or not trusted_execution_ok
    )
    unsafe_approve = bool(
        raw_verdict in {"approve", "approve_with_warnings"}
        and case["expected"]["verdict"] not in {"approve", "approve_with_warnings"}
    )
    passed = bool(
        normalized is not None and not errors and status_ok and outcome_ok
        and not fp and not fn and invalid_evidence == 0 and auxiliary_ok
        and trusted_execution_ok
    )
    failures: list[str] = []
    if errors:
        failures.append(f"schema invalid: {'; '.join(errors)}")
    if not status_ok:
        failures.append("status mismatch")
    if not outcome_ok:
        failures.append("verdict mismatch")
    if fn:
        failures.append(f"{len(fn)} expected finding(s) missed")
    if fp:
        failures.append(f"{len(fp)} unexpected finding(s)")
    if invalid_evidence:
        failures.append(f"{invalid_evidence} invalid evidence binding(s)")
    if not auxiliary_ok:
        failures.append("auxiliary deterministic finding mismatch")
    if not trusted_execution_ok:
        failures.append("trusted execution contract mismatch")
    if unsafe_approve:
        failures.append("unsafe approve")
    public = {
        "case_id": case["id"], "split": "development",
        "base_revision": response["base_revision"], "head_revision": response["head_revision"],
        "latency_ms": float(response["latency_ms"]), "normalized_output": normalized or raw,
        "raw_sanitized_response": response["raw_sanitized"],
        "schema_valid": normalized is not None and not errors, "schema_errors": errors,
        "evidence_checks": evidence_checks, "tp_count": len(tp), "fp_count": len(fp),
        "fn_count": len(fn), "unsafe_approve": unsafe_approve,
        "auxiliary_deterministic_valid": auxiliary_ok,
        "trusted_execution_valid": trusted_execution_ok,
        "assessment": "PASS" if passed else "FAIL",
        "reason": "strict outcome, findings, and evidence match development ground truth" if passed else "; ".join(failures),
    }
    internal = {
        "expected": len(case["expected"]["findings"]), "predicted": len(predicted),
        "tp": len(tp), "fp": len(fp), "fn": len(fn),
        "tp_blocker": sum(item["severity"] == "blocker" for item in tp),
        "fn_blocker": sum(item["severity"] == "blocker" for item in fn),
        "outcome_ok": outcome_ok, "status_ok": status_ok, "passed": passed,
        "schema_valid": normalized is not None and not errors,
        "invalid_evidence": invalid_or_hallucinated_evidence,
        "unsafe_approve": unsafe_approve,
        "auxiliary_ok": auxiliary_ok,
        "trusted_execution_ok": trusted_execution_ok,
        "latency_ms": float(response["latency_ms"]),
    }
    return public, internal


def _ratio(numerator: int, denominator: int, *, empty: float) -> float:
    return round(numerator / denominator, 6) if denominator else empty


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tp = sum(row["tp"] for row in rows); fp = sum(row["fp"] for row in rows); fn = sum(row["fn"] for row in rows)
    blockers_tp = sum(row["tp_blocker"] for row in rows); blockers_fn = sum(row["fn_blocker"] for row in rows)
    return {
        "cases_evaluated": len(rows), "cases_passed": sum(row["passed"] for row in rows),
        "findings_expected": sum(row["expected"] for row in rows),
        "findings_predicted": sum(row["predicted"] for row in rows),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": _ratio(tp, tp + fp, empty=1.0), "recall": _ratio(tp, tp + fn, empty=1.0),
        "blocker_recall": _ratio(blockers_tp, blockers_tp + blockers_fn, empty=1.0),
        "outcome_accuracy": _ratio(sum(row["outcome_ok"] for row in rows), len(rows), empty=0.0),
        "schema_valid_rate": _ratio(sum(row["schema_valid"] for row in rows), len(rows), empty=0.0),
        "unsafe_approve_count": sum(row["unsafe_approve"] for row in rows),
        "invalid_or_hallucinated_evidence_count": sum(row["invalid_evidence"] for row in rows),
        "exact_case_accuracy": _ratio(sum(row["passed"] for row in rows), len(rows), empty=0.0),
    }


def _gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    gate = corpus_tool._validate_gate(ROOT)
    thresholds = gate["thresholds"]
    definitions = (
        ("blocker_recall", metrics["blocker_recall"], ">=", thresholds["blocker_recall"]),
        ("unsafe_approve_count", metrics["unsafe_approve_count"], "<=", thresholds["unsafe_approve_count"]),
        (
            "invalid_or_hallucinated_evidence_count",
            metrics["invalid_or_hallucinated_evidence_count"],
            "<=",
            thresholds["invalid_or_hallucinated_evidence_count_max"],
        ),
        ("schema_valid_rate", metrics["schema_valid_rate"], ">=", thresholds["schema_valid_rate"]),
        ("precision", metrics["precision"], ">=", thresholds["precision_min"]),
        ("recall", metrics["recall"], ">=", thresholds["recall_min"]),
        ("outcome_accuracy", metrics["outcome_accuracy"], ">=", thresholds["outcome_accuracy_min"]),
        (
            "exact_case_accuracy",
            metrics["exact_case_accuracy"],
            ">=",
            thresholds["exact_case_accuracy_min"],
        ),
    )
    checks = [
        {"id": name, "actual": actual, "operator": operator, "threshold": threshold,
         "passed": bool(actual >= threshold if operator == ">=" else actual <= threshold)}
        for name, actual, operator, threshold in definitions
    ]
    return {"evaluation_passed": all(item["passed"] for item in checks), "checks": checks, "release_eligible": False, "release_passed": False}


def _validate_response(response: Any, case_id: str, revision: Mapping[str, Any]) -> Mapping[str, Any]:
    response = _exact(
        response,
        {"case_id", "base_revision", "head_revision", "latency_ms", "raw_sanitized", "normalized"},
        f"response {case_id}",
    )
    if response["case_id"] != case_id:
        raise ValueError("response/case correlation mismatch")
    if response["base_revision"] != revision["base"] or response["head_revision"] != revision["head"]:
        raise ValueError(f"{case_id}: response revisions do not match deterministic materialization")
    latency = response["latency_ms"]
    if isinstance(latency, bool) or not isinstance(latency, (int, float)) or not math.isfinite(float(latency)) or not 0 <= float(latency) <= 3_600_000:
        raise ValueError(f"{case_id}: latency is invalid")
    _scan_sanitized(response["raw_sanitized"])
    return response


def _capture_set_hash(runs: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        b"aga.synthetic-development-capture-set/v2\0"
        + json.dumps(
            list(runs), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _score_responses(
    responses: Sequence[Mapping[str, Any]], *, captured_at: str, provenance: str,
    series: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if CAPTURED_AT_RE.fullmatch(captured_at) is None:
        raise ValueError("captured_at must use YYYY-MM-DDTHH:MM:SSZ")
    lock = corpus_tool.verify_lock(ROOT, require_measurement_ready=provenance == "trusted")
    cases = corpus_tool.load_cases(ROOT)
    if provenance == "fixture":
        if series is not None:
            raise ValueError("fixture scoring cannot claim a measurement series")
        series_context = None
    else:
        series = _exact(
            series,
            {"series_id", "capture_id", "repeat_ordinal", "measurement_identity"},
            "trusted series context",
        )
        freeze = lock["series_freeze"]
        if series["series_id"] != freeze["series_id"]:
            raise ValueError("trusted series ID does not match the frozen lock")
        capture_id = corpus_tool._text(series["capture_id"], "capture_id", limit=128)
        if corpus_tool.SERIES_ID_RE.fullmatch(capture_id) is None:
            raise ValueError("capture_id is invalid")
        ordinal = series["repeat_ordinal"]
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or not 1 <= ordinal <= 5:
            raise ValueError("repeat_ordinal must be an integer in 1..5")
        if series["measurement_identity"] != freeze["measurement_identity"]:
            raise ValueError("trusted scorer measurement identity does not match the frozen lock")
        series_context = {
            "series_id": freeze["series_id"],
            "capture_id": capture_id,
            "repeat_ordinal": ordinal,
            "required_repeated_runs": freeze["required_repeated_runs"],
            "measurement_identity": dict(freeze["measurement_identity"]),
        }
    by_id = {case["id"]: case for case in cases}
    if not responses or len(responses) != len({item.get("case_id") for item in responses if isinstance(item, Mapping)}):
        raise ValueError("responses must be a non-empty unique selection")
    ids = [str(item.get("case_id")) for item in responses]
    if any(case_id not in by_id for case_id in ids):
        raise ValueError("selection contains unknown case ids")
    selection = "smoke" if len(ids) == 1 else "development" if set(ids) == set(by_id) else "invalid"
    if selection == "invalid" or (provenance == "trusted" and selection != "development"):
        raise ValueError("measurement must cover the complete 48-case development selection")
    supplied = {str(item["case_id"]): item for item in responses}
    selected = [case for case in cases if case["id"] in supplied]
    public: list[dict[str, Any]] = []
    internal: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="aga-development-v2-score-") as raw:
        root = Path(raw)
        for case in selected:
            revision = corpus_tool.materialize_case(case["id"], root / case["id"], root=ROOT)
            response = _validate_response(supplied[case["id"]], case["id"], revision)
            row, private = _score_case(
                case,
                response,
                trusted_identity=(
                    series_context["measurement_identity"]
                    if series_context is not None
                    else None
                ),
            )
            public.append(row); internal.append(private)
    metrics = _metrics(internal)
    gate = _gate(metrics)
    capture_set_sha256 = _capture_set_hash(public)
    selection_contract = corpus_tool.measurement_selection(cases)
    selection_result = {"kind": selection, "case_count": len(selected)}
    if provenance == "trusted":
        selection_result.update(
            {
                "selection_id": selection_contract["selection_id"],
                "selection_sha256": selection_contract["selection_sha256"],
                "case_ids": selection_contract["case_ids"],
            }
        )
    return {
        "schema": RESULT_SCHEMA,
        "status": "fixture_scored_non_release" if provenance == "fixture" else "trusted_development_scored_non_release",
        "measurement_class": "synthetic_fixture" if provenance == "fixture" else "trusted_ouroboros_development",
        "release_evidence": False, "captured_at": captured_at,
        "corpus": "synthetic-public-semantic-development-v2",
        "corpus_hash": lock["corpus_sha256"], "ground_truth_hash": lock["ground_truth_sha256"],
        "validator_hash": lock["validator_sha256"], "scorer_hash": lock["scorer_sha256"],
        "capture_set_sha256": capture_set_sha256,
        "series": series_context,
        "selection": selection_result,
        "overall": metrics, "gate": gate, "runs": public,
    }


def score_fixture_bundle(path: Path) -> dict[str, Any]:
    bundle = json.loads(path.read_text(encoding="utf-8"))
    fields = {
        "schema", "mode", "captured_at", "corpus_sha256", "ground_truth_sha256",
        "validator_sha256", "scorer_sha256", "responses",
    }
    bundle = _exact(bundle, fields, "fixture bundle")
    if bundle["schema"] != FIXTURE_SCHEMA or bundle["mode"] != "fixture":
        raise ValueError("only explicit fixture bundles can use the offline file scorer")
    lock = corpus_tool.verify_lock(ROOT)
    for field in ("corpus_sha256", "ground_truth_sha256", "validator_sha256", "scorer_sha256"):
        lock_field = field.replace("corpus_sha256", "corpus_sha256").replace("ground_truth_sha256", "ground_truth_sha256")
        if bundle[field] != lock[lock_field]:
            raise ValueError(f"fixture bundle {field} does not match lock")
    if not isinstance(bundle["responses"], list):
        raise ValueError("fixture responses must be a list")
    return _score_responses(
        bundle["responses"], captured_at=bundle["captured_at"], provenance="fixture"
    )


def score_trusted_responses(
    responses: Sequence[Mapping[str, Any]], *, captured_at: str, series_id: str,
    capture_id: str, repeat_ordinal: int, measurement_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Score trusted in-process captures; caller-provided files cannot enter here."""
    if isinstance(responses, (str, bytes)) or not isinstance(responses, Sequence):
        raise ValueError("trusted responses must be an in-memory sequence")
    return _score_responses(
        responses,
        captured_at=captured_at,
        provenance="trusted",
        series={
            "series_id": series_id,
            "capture_id": capture_id,
            "repeat_ordinal": repeat_ordinal,
            "measurement_identity": measurement_identity,
        },
    )


def _summarize_series_documents(
    documents: Sequence[Mapping[str, Any]], *, lock: Mapping[str, Any],
    max_p95_ms: float, max_cost_usd: float, rescore: bool = True,
) -> dict[str, Any]:
    for name, value in (("max_p95_ms", max_p95_ms), ("max_cost_usd", max_cost_usd)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise ValueError(f"{name} must be an owner-supplied positive finite number")
    freeze = lock["series_freeze"]
    required_runs = freeze["required_repeated_runs"]
    if len(documents) != required_runs:
        raise ValueError(f"series requires exactly {required_runs} capture results")
    expected_ordinals = set(range(1, required_runs + 1))
    ordinals: set[int] = set()
    capture_ids: set[str] = set()
    capture_hashes: set[str] = set()
    attempt_hashes: set[str] = set()
    captured_at_values: set[str] = set()
    rows: list[dict[str, Any]] = []
    selection = corpus_tool.measurement_selection(corpus_tool.load_cases(ROOT))
    for index, document in enumerate(documents):
        if not isinstance(document, Mapping):
            raise ValueError(f"series result[{index}] must be an object")
        if (
            document.get("schema") != RESULT_SCHEMA
            or document.get("status") != "trusted_development_scored_non_release"
            or document.get("measurement_class") != "trusted_ouroboros_development"
            or document.get("release_evidence") is not False
        ):
            raise ValueError(f"series result[{index}] is not a trusted development capture")
        for field, lock_field in (
            ("corpus_hash", "corpus_sha256"),
            ("ground_truth_hash", "ground_truth_sha256"),
            ("validator_hash", "validator_sha256"),
            ("scorer_hash", "scorer_sha256"),
        ):
            if document.get(field) != lock[lock_field]:
                raise ValueError(f"series result[{index}] {field} does not match the lock")
        captured_at = document.get("captured_at")
        if not isinstance(captured_at, str) or CAPTURED_AT_RE.fullmatch(captured_at) is None:
            raise ValueError(f"series result[{index}] captured_at is invalid")
        captured_at_values.add(captured_at)
        context = document.get("series")
        if not isinstance(context, Mapping):
            raise ValueError(f"series result[{index}] lacks series context")
        if (
            context.get("series_id") != freeze["series_id"]
            or context.get("required_repeated_runs") != required_runs
            or context.get("measurement_identity") != freeze["measurement_identity"]
        ):
            raise ValueError(f"series result[{index}] identity does not match the frozen series")
        ordinal = context.get("repeat_ordinal")
        capture_id = context.get("capture_id")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise ValueError(f"series result[{index}] repeat ordinal is invalid")
        if not isinstance(capture_id, str) or corpus_tool.SERIES_ID_RE.fullmatch(capture_id) is None:
            raise ValueError(f"series result[{index}] capture ID is invalid")
        ordinals.add(ordinal)
        capture_ids.add(capture_id)
        attempt = _exact(
            document.get("attempt"),
            {"marker_sha256", "started_at", "cases_completed"},
            f"series result[{index}] attempt",
        )
        marker_sha256 = attempt["marker_sha256"]
        if (
            not isinstance(marker_sha256, str)
            or corpus_tool.SHA256_RE.fullmatch(marker_sha256) is None
            or not isinstance(attempt["started_at"], str)
            or CAPTURED_AT_RE.fullmatch(attempt["started_at"]) is None
            or attempt["cases_completed"] != 48
        ):
            raise ValueError(f"series result[{index}] attempt linkage is invalid")
        attempt_hashes.add(marker_sha256)
        selected = document.get("selection")
        if not isinstance(selected, Mapping) or (
            selected.get("kind") != "development"
            or selected.get("case_count") != 48
            or selected.get("selection_id") != selection["selection_id"]
            or selected.get("selection_sha256") != selection["selection_sha256"]
            or selected.get("case_ids") != selection["case_ids"]
        ):
            raise ValueError(f"series result[{index}] selection is not the complete frozen development set")
        runs = document.get("runs")
        if not isinstance(runs, list) or len(runs) != 48:
            raise ValueError(f"series result[{index}] must retain all 48 scored runs")
        capture_hash = document.get("capture_set_sha256")
        if (
            not isinstance(capture_hash, str)
            or corpus_tool.SHA256_RE.fullmatch(capture_hash) is None
            or capture_hash != _capture_set_hash(runs)
        ):
            raise ValueError(f"series result[{index}] capture-set hash is invalid")
        capture_hashes.add(capture_hash)
        overall = document.get("overall")
        gate = document.get("gate")
        if not isinstance(overall, Mapping) or not isinstance(gate, Mapping):
            raise ValueError(f"series result[{index}] metrics/gate are invalid")
        if rescore:
            responses: list[dict[str, Any]] = []
            for run_index, run in enumerate(runs):
                if not isinstance(run, Mapping):
                    raise ValueError(f"series result[{index}].runs[{run_index}] is invalid")
                required = {
                    "case_id", "base_revision", "head_revision", "latency_ms",
                    "raw_sanitized_response", "normalized_output",
                }
                if not required.issubset(run):
                    raise ValueError(
                        f"series result[{index}].runs[{run_index}] cannot be re-scored"
                    )
                responses.append(
                    {
                        "case_id": run["case_id"],
                        "base_revision": run["base_revision"],
                        "head_revision": run["head_revision"],
                        "latency_ms": run["latency_ms"],
                        "raw_sanitized": run["raw_sanitized_response"],
                        "normalized": run["normalized_output"],
                    }
                )
            recomputed = _score_responses(
                responses,
                captured_at=captured_at,
                provenance="trusted",
                series={
                    "series_id": context["series_id"],
                    "capture_id": capture_id,
                    "repeat_ordinal": ordinal,
                    "measurement_identity": context["measurement_identity"],
                },
            )
            for field in ("overall", "gate", "runs", "capture_set_sha256"):
                if document.get(field) != recomputed[field]:
                    raise ValueError(
                        f"series result[{index}] {field} differs from strict re-scoring"
                    )
            overall = recomputed["overall"]
            gate = recomputed["gate"]
            runs = recomputed["runs"]
        latencies = [float(run["latency_ms"]) for run in runs]
        usage = _usage_summary(runs)
        rows.append(
            {
                "repeat_ordinal": ordinal,
                "capture_id": capture_id,
                "captured_at": captured_at,
                "capture_set_sha256": capture_hash,
                "attempt_marker_sha256": marker_sha256,
                "evaluation_passed": gate.get("evaluation_passed") is True,
                "overall": dict(overall),
                "latency_ms": {
                    "p50": _percentile(latencies, 0.50),
                    "p95": _percentile(latencies, 0.95),
                },
                "usage": usage,
                "case_verdicts": {
                    str(run["case_id"]): str(run["normalized_output"].get("verdict"))
                    if isinstance(run.get("normalized_output"), Mapping)
                    else "invalid"
                    for run in runs
                },
            }
        )
    if ordinals != expected_ordinals:
        raise ValueError("series repeat ordinals must be exactly 1..5")
    if (
        len(capture_ids) != required_runs
        or len(capture_hashes) != required_runs
        or len(attempt_hashes) != required_runs
    ):
        raise ValueError(
            "series captures must have distinct IDs, attempt markers, and capture-set hashes"
        )
    if len(captured_at_values) != required_runs:
        raise ValueError("series captures must have distinct capture timestamps")
    rows.sort(key=lambda item: item["repeat_ordinal"])
    lower_is_worse = (
        "precision", "recall", "blocker_recall", "outcome_accuracy",
        "schema_valid_rate", "exact_case_accuracy",
    )
    higher_is_worse = (
        "unsafe_approve_count", "invalid_or_hallucinated_evidence_count", "fp", "fn",
    )
    worst_case = {
        **{name: min(float(row["overall"][name]) for row in rows) for name in lower_is_worse},
        **{name: max(int(row["overall"][name]) for row in rows) for name in higher_is_worse},
    }
    all_latencies = [
        float(run["latency_ms"])
        for document in documents
        for run in document["runs"]
    ]
    latency = {
        "pooled_p50_ms": _percentile(all_latencies, 0.50),
        "pooled_p95_ms": _percentile(all_latencies, 0.95),
        "max_repeat_p95_ms": max(row["latency_ms"]["p95"] for row in rows),
        "per_repeat_p95_cap_ms": float(max_p95_ms),
    }
    usage = {
        "prompt_tokens": sum(row["usage"]["prompt_tokens"] for row in rows),
        "completion_tokens": sum(row["usage"]["completion_tokens"] for row in rows),
        "known_cost_usd": round(sum(row["usage"]["known_cost_usd"] for row in rows), 8),
        "unknown_prompt_token_records": sum(
            row["usage"]["unknown_prompt_token_records"] for row in rows
        ),
        "unknown_completion_token_records": sum(
            row["usage"]["unknown_completion_token_records"] for row in rows
        ),
        "unknown_cost_records": sum(row["usage"]["unknown_cost_records"] for row in rows),
        "max_repeat_known_cost_usd": max(row["usage"]["known_cost_usd"] for row in rows),
        "per_repeat_cost_cap_usd": float(max_cost_usd),
    }
    case_ids = list(selection["case_ids"])
    flapping = []
    for case_id in case_ids:
        categories = {
            "approve" if row["case_verdicts"].get(case_id) in {"approve", "approve_with_warnings"}
            else "non_approve"
            for row in rows
        }
        if len(categories) > 1:
            flapping.append(case_id)
    quality_passed = bool(
        all(row["evaluation_passed"] for row in rows)
        and worst_case["unsafe_approve_count"] == 0
        and worst_case["invalid_or_hallucinated_evidence_count"] == 0
    )
    latency_passed = all(
        row["latency_ms"]["p95"] <= float(max_p95_ms) for row in rows
    )
    cost_complete = usage["unknown_cost_records"] == 0
    token_accounting_complete = bool(
        usage["unknown_prompt_token_records"] == 0
        and usage["unknown_completion_token_records"] == 0
    )
    cost_passed = cost_complete and all(
        row["usage"]["known_cost_usd"] <= float(max_cost_usd) for row in rows
    )
    stability_passed = not flapping
    qualified = bool(
        quality_passed
        and latency_passed
        and token_accounting_complete
        and cost_passed
        and stability_passed
    )
    public_rows = [
        {key: value for key, value in row.items() if key != "case_verdicts"}
        for row in rows
    ]
    return {
        "schema": SERIES_RESULT_SCHEMA,
        "status": "complete_qualified" if qualified else "complete_not_qualified",
        "release_evidence": False,
        "series_id": freeze["series_id"],
        "measurement_identity": dict(freeze["measurement_identity"]),
        "required_repeated_runs": required_runs,
        "distinct_capture_count": len(capture_ids),
        "qualification_passed": qualified,
        "checks": {
            "all_recomputed_quality_gates_passed": quality_passed,
            "latency_p95_cap_passed": latency_passed,
            "token_accounting_complete": token_accounting_complete,
            "cost_accounting_complete": cost_complete,
            "cost_cap_passed": cost_passed,
            "approve_non_approve_stability_passed": stability_passed,
        },
        "worst_case": worst_case,
        "latency": latency,
        "usage": usage,
        "approve_non_approve_flapping_case_ids": flapping,
        "repeats": public_rows,
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return round(ordered[lower], 6)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 6)


def _usage_summary(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "known_cost_usd": 0.0,
        "unknown_prompt_token_records": 0,
        "unknown_completion_token_records": 0,
        "unknown_cost_records": 0,
    }
    for run in runs:
        raw = run.get("raw_sanitized_response")
        usage = raw.get("model_usage") if isinstance(raw, Mapping) else None
        if not isinstance(usage, Mapping):
            result["unknown_prompt_token_records"] += 1
            result["unknown_completion_token_records"] += 1
            result["unknown_cost_records"] += 1
            continue
        for field, total, unknown in (
            ("prompt_tokens", "prompt_tokens", "unknown_prompt_token_records"),
            ("completion_tokens", "completion_tokens", "unknown_completion_token_records"),
        ):
            value = usage.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                result[unknown] += 1
            else:
                result[total] += value
        cost = usage.get("known_cost_usd")
        complete = usage.get("cost_complete") is True
        unresolved = usage.get("unresolved_upper_bound_usd", 0.0)
        unknown_unmetered = usage.get("unknown_unmetered", 0)
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or float(cost) < 0
            or not complete
            or unresolved != 0
            or unknown_unmetered != 0
        ):
            result["unknown_cost_records"] += 1
        else:
            result["known_cost_usd"] += float(cost)
    result["known_cost_usd"] = round(result["known_cost_usd"], 8)
    return result


def verify_series_result_files(
    paths: Sequence[Path], *, max_p95_ms: float, max_cost_usd: float,
    attestation_key_file: Path | None,
) -> dict[str, Any]:
    lock = corpus_tool.verify_lock(ROOT, require_measurement_ready=True)
    key = _series_attestation_key(attestation_key_file, lock["series_freeze"]["capture_attestation"])
    if not paths or len(paths) != len({str(Path(path).resolve(strict=False)) for path in paths}):
        raise ValueError("series result paths must be non-empty and unique")
    documents: list[Mapping[str, Any]] = []
    for path in paths:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 20_000_000:
            raise ValueError("series result must be a bounded regular JSON file")
        document = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            raise ValueError("series result JSON must contain an object")
        raw_attestation = document.get("capture_attestation")
        attestation = _exact(
            raw_attestation, {"scheme", "key_id", "signature"},
            "capture attestation",
        )
        expected_attestation = lock["series_freeze"]["capture_attestation"]
        if (
            attestation["scheme"] != "hmac-sha256"
            or attestation["key_id"] != expected_attestation["key_id"]
            or not isinstance(attestation["signature"], str)
            or corpus_tool.SHA256_RE.fullmatch(attestation["signature"]) is None
        ):
            raise ValueError("capture attestation metadata is invalid")
        unsigned = dict(document)
        del unsigned["capture_attestation"]
        payload = json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        expected_signature = hmac.new(key, payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(attestation["signature"], expected_signature):
            raise ValueError("capture attestation signature mismatch")
        documents.append(document)
    return _summarize_series_documents(
        documents, lock=lock, max_p95_ms=max_p95_ms, max_cost_usd=max_cost_usd
    )


def _series_attestation_key(
    value: Path | None, attestation: Mapping[str, Any]
) -> bytes:
    if value is None:
        raise ValueError("an external capture attestation key file is required")
    supplied = Path(value)
    if supplied.is_symlink():
        raise ValueError("capture attestation key file must not be a symlink")
    try:
        path = supplied.resolve(strict=True)
        path.relative_to(ROOT.parents[1].resolve())
    except ValueError:
        pass
    except OSError as error:
        raise ValueError("capture attestation key file is unavailable") from error
    else:
        raise ValueError("capture attestation key file must stay outside the repository")
    info = path.lstat()
    payload = path.read_bytes()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_mode & 0o077
        or not 32 <= len(payload) <= 4096
        or hashlib.sha256(payload).hexdigest() != attestation["key_sha256"]
    ):
        raise ValueError("capture attestation key does not match the frozen secure key")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--score-fixture", type=Path)
    action.add_argument("--verify-series", type=Path, nargs="+")
    parser.add_argument("--max-p95-ms", type=float)
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--attestation-key-file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = (
            score_fixture_bundle(args.score_fixture)
            if args.score_fixture is not None
            else verify_series_result_files(
                args.verify_series,
                max_p95_ms=args.max_p95_ms,
                max_cost_usd=args.max_cost_usd,
                attestation_key_file=args.attestation_key_file,
            )
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"development-v2 scorer: FAIL: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 3 if result.get("qualification_passed") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
