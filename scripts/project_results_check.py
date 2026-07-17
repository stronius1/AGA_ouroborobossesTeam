#!/usr/bin/env python3
"""Validate local Project Results evidence without claiming external proofs."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "THIRD_PARTY.md",
    "compose.yaml",
    "architecture/dochub.yaml",
    "architecture/metamodel/aga-extension.yaml",
    "docs/SEAF-CANONICAL-MAPPING.md",
    "docs/MCP-CONTRACT.md",
    "docs/submission/PROJECT-PROPOSAL.md",
    "docs/submission/PROPOSAL-TRACEABILITY.md",
    "docs/submission/PROJECT-RESULTS.md",
    "docs/submission/DEMO-SCRIPT.md",
    "docs/submission/presentation-source.md",
    "docs/submission/presentation.css",
    "docs/submission/presentation.pdf",
    "evaluation/gigaagent/corpus.yaml",
    "evaluation/gigaagent/corpus.lock.json",
    "evaluation/gigaagent/gate.yaml",
    "evaluation/gigaagent/results.json",
    "evaluation/gigaagent/fixture-results.json",
    "evaluation/gigaagent/fixtures/sanitized-response-bundle.json",
    "docs/evidence/baseline/2026-07-15.md",
    "docs/evidence/evaluation/RESULTS.md",
    "docs/evidence/gigaagent/README.md",
    "docs/evidence/implementation/2026-07-15.md",
    "docs/evidence/snapshots/deterministic-2026-07-15-v2/README.md",
    "docs/evidence/snapshots/deterministic-2026-07-15-v2/SHA256SUMS",
    "docs/evidence/snapshots/deterministic-2026-07-15-v2/metrics-baseline.json",
    "docs/evidence/snapshots/deterministic-2026-07-15-v2/metrics-candidate.json",
)
ACTIVE_MARKDOWN = (
    "README.md",
    "AGA-README.md",
    "aga-skill/README.md",
    "aga-skill/SKILL.md",
    "aga-skill/evolver/EVOLVER.md",
    "aga-skill/docs/CURRENT-STATE-AND-ROADMAP.md",
    "aga-skill/docs/PROJECT-RESULTS.md",
    "aga-skill/docs/RESULTS-EXAMPLES.md",
    "docs/SEAF-CANONICAL-MAPPING.md",
    "docs/MCP-CONTRACT.md",
    "docs/submission/PROJECT-RESULTS.md",
    "docs/submission/presentation-source.md",
    "docs/submission/DEMO-SCRIPT.md",
    "docs/evidence/evaluation/RESULTS.md",
    "docs/evidence/gigaagent/README.md",
    "docs/evidence/snapshots/deterministic-2026-07-15-v2/README.md",
)
PLACEHOLDER_RE = re.compile(
    r"\{\{[^}]+\}\}|<PUBLIC_URL>|\b(?:TODO|TBD|CHANGEME|INSERT[_ -]HERE)\b",
    re.IGNORECASE,
)
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CAPTURED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DIGEST_RE = re.compile(r"^(?:rvw|tsk)_[0-9a-f]{64}$")

OUROBOROS_TRACE = ROOT / "docs/evidence/ouroboros/run-sanitized.json"
OUROBOROS_TRACE_SCHEMA = "aga.ouroboros-run-sanitized/v1"
RESULTS_SCHEMA = "aga.gigaagent-results/v2"
OUROBOROS_VERSION = "6.64.1"
OUROBOROS_PROVIDER = "openrouter"
OUROBOROS_MODEL = "deepseek/deepseek-v4-pro"
OUROBOROS_SMOKE_CASE = "ga-05-critical-eliminate"
OUROBOROS_SMOKE_BASE = "5f07e7b66b55c211e4887a1c6df611ba7f7197a5"
OUROBOROS_SMOKE_HEAD = "6e6f77bd2ccc49997aced97c512f4196785ba434"
OUROBOROS_TOOLS = (
    "aga_prepare_review",
    "aga_seaf_lookup",
    "aga_parse_diagram",
    "aga_finalize_review",
)
DEVELOPMENT_CASES = (
    "ga-01-reuse-duplicate",
    "ga-02-reuse-existing",
    "ga-03-second-master",
    "ga-04-read-replica",
    "ga-05-critical-eliminate",
    "ga-06-noncritical-near-miss",
    "ga-07-significant-no-adr",
    "ga-08-cosmetic-no-adr",
)
HOLDOUT_CASES = (
    "ga-09-clean-reuse-adr",
    "ga-10-retirement-word-near-miss",
    "ga-11-prompt-injection",
    "ga-12-missing-context",
    "ga-13-master-and-dependency",
    "ga-14-weak-adr",
    "ga-15-accepted-adr",
    "ga-16-semantic-clean",
)
ALL_CASES = DEVELOPMENT_CASES + HOLDOUT_CASES
REDACTION_CONTRACT = {
    "credentials_retained": False,
    "absolute_paths_retained": False,
    "raw_prompts_retained": False,
    "raw_provider_payloads_retained": False,
}
NORMALIZED_FINDING_FIELDS = {
    "rule_id",
    "severity",
    "confidence",
    "artifact",
    "location",
    "evidence",
    "source_ref",
    "suggested_fix",
}
TRUSTED_RUN_FIELDS = {
    "case_id",
    "split",
    "base_revision",
    "head_revision",
    "latency_ms",
    "raw_sanitized_response",
    "normalized_output",
    "schema_valid",
    "schema_errors",
    "evidence_checks",
    "tp_count",
    "fp_count",
    "fn_count",
    "unsafe_approve",
    "assessment",
    "reason",
}


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _is_finite_number(value: Any, *, minimum: float = 0.0) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) >= minimum
    )


def _valid_normalized_output(value: Any) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "status",
        "verdict",
        "findings",
    }:
        return False
    status = value.get("status")
    verdict = value.get("verdict")
    findings = value.get("findings")
    if (
        status not in {"complete", "incomplete"}
        or verdict
        not in {
            "approve",
            "approve_with_warnings",
            "request_changes_escalate",
            "incomplete",
        }
        or not isinstance(findings, list)
        or len(findings) > 100
        or (status == "incomplete" and verdict != "incomplete")
        or (status == "complete" and verdict == "incomplete")
    ):
        return False
    for finding in findings:
        if not isinstance(finding, Mapping) or set(finding) != NORMALIZED_FINDING_FIELDS:
            return False
        confidence = finding.get("confidence")
        if (
            finding.get("rule_id") not in {"PRIN-004", "PRIN-005", "PRIN-006", "PRIN-007"}
            or finding.get("severity") not in {"blocker", "major", "minor"}
            or not _is_finite_number(confidence)
            or float(confidence) > 1.0
            or any(
                not isinstance(finding.get(field), str) or not finding.get(field)
                for field in (
                    "artifact",
                    "location",
                    "evidence",
                    "source_ref",
                    "suggested_fix",
                )
            )
        ):
            return False
    return True


def _valid_trusted_raw_capture(value: Any, normalized: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "task_id",
        "task_status",
        "final_answer_envelope",
        "rendered_prompt_sha256",
        "receipts",
        "model_usage",
    }:
        return False
    expected_incomplete = normalized.get("status") == "incomplete"
    if (
        not isinstance(value.get("task_id"), str)
        or TASK_ID_RE.fullmatch(value["task_id"]) is None
        or value.get("task_status") != ("failed" if expected_incomplete else "succeeded")
        or value.get("final_answer_envelope")
        not in {"strict_json", "single_json_fence"}
        or not _is_sha256(value.get("rendered_prompt_sha256"))
    ):
        return False

    usage = value.get("model_usage")
    if not isinstance(usage, Mapping) or set(usage) != {
        "provider",
        "model",
        "call_count",
        "known_cost_usd",
        "cost_complete",
    }:
        return False
    if (
        usage.get("provider") != OUROBOROS_PROVIDER
        or usage.get("model") != OUROBOROS_MODEL
        or isinstance(usage.get("call_count"), bool)
        or not isinstance(usage.get("call_count"), int)
        or usage["call_count"] < 1
        or not _is_finite_number(usage.get("known_cost_usd"))
        or usage.get("cost_complete") is not True
    ):
        return False

    receipts = value.get("receipts")
    if not isinstance(receipts, Mapping) or set(receipts) != {
        "review_id_sha256",
        "tool_names",
        "prepare",
        "finalize",
    }:
        return False
    names = receipts.get("tool_names")
    if (
        not _is_sha256(receipts.get("review_id_sha256"))
        or not isinstance(names, list)
        or len(names) < 2
        or names[0] != "aga_prepare_review"
        or names[-1] != "aga_finalize_review"
        or names.count("aga_prepare_review") != 1
        or names.count("aga_finalize_review") != 1
        or any(name not in OUROBOROS_TOOLS for name in names)
    ):
        return False
    prepare = receipts.get("prepare")
    finalize = receipts.get("finalize")
    summary_fields = {"args_sha256", "output_sha256", "status"}
    if (
        not isinstance(prepare, Mapping)
        or set(prepare) != summary_fields
        or not isinstance(finalize, Mapping)
        or set(finalize) != summary_fields
        or not _is_sha256(prepare.get("args_sha256"))
        or not _is_sha256(prepare.get("output_sha256"))
        or not _is_sha256(finalize.get("args_sha256"))
        or not _is_sha256(finalize.get("output_sha256"))
        or prepare.get("status") != "ready"
        or finalize.get("status")
        != ("incomplete" if expected_incomplete else "completed")
    ):
        return False
    return True


def check_ouroboros_trace_payload(
    payload: Any,
    errors: list[str],
    *,
    expected_corpus_hash: str,
    expected_prompt_hash: str,
) -> bool:
    """Validate the canonical one-case capture emitted by the trusted runner."""

    top_fields = {
        "schema",
        "status",
        "captured_at",
        "runtime",
        "provider",
        "model",
        "data_classification",
        "redaction",
        "corpus_hash",
        "prompt_template_sha256",
        "config_sha256",
        "preflight",
        "run",
    }
    if not isinstance(payload, Mapping) or set(payload) != top_fields:
        errors.append(
            "canonical Ouroboros trace is not an exact trusted-runner capture; "
            "fixture or manually relabelled evidence is not accepted"
        )
        return False
    if (
        payload.get("schema") != OUROBOROS_TRACE_SCHEMA
        or payload.get("status") != "passed"
        or not isinstance(payload.get("captured_at"), str)
        or CAPTURED_AT_RE.fullmatch(payload["captured_at"]) is None
        or payload.get("runtime") != {"name": "ouroboros", "version": OUROBOROS_VERSION}
        or payload.get("provider") != OUROBOROS_PROVIDER
        or payload.get("model") != {"name": OUROBOROS_MODEL}
        or payload.get("data_classification") != "synthetic-public"
        or payload.get("redaction") != REDACTION_CONTRACT
        or payload.get("corpus_hash") != expected_corpus_hash
        or payload.get("prompt_template_sha256") != expected_prompt_hash
        or not _is_sha256(payload.get("config_sha256"))
    ):
        errors.append("canonical Ouroboros trace has invalid trusted runtime provenance")
        return False

    preflight = payload.get("preflight")
    if (
        not isinstance(preflight, Mapping)
        or set(preflight) != {"status", "attestation_sha256", "tool_count", "tools"}
        or preflight.get("status") != "ready"
        or not _is_sha256(preflight.get("attestation_sha256"))
        or preflight.get("tool_count") != len(OUROBOROS_TOOLS)
        or preflight.get("tools") != list(OUROBOROS_TOOLS)
    ):
        errors.append("canonical Ouroboros trace has invalid preflight attestation")
        return False

    run = payload.get("run")
    run_fields = {
        "case_id",
        "base_revision",
        "head_revision",
        "latency_ms",
        "raw_sanitized",
        "normalized",
        "review_id_sha256",
        "final",
        "acceptance",
    }
    if not isinstance(run, Mapping) or set(run) != run_fields:
        errors.append("canonical Ouroboros trace has an invalid smoke run shape")
        return False
    normalized = run.get("normalized")
    if (
        run.get("case_id") != OUROBOROS_SMOKE_CASE
        or run.get("base_revision") != OUROBOROS_SMOKE_BASE
        or run.get("head_revision") != OUROBOROS_SMOKE_HEAD
        or not _is_finite_number(run.get("latency_ms"))
        or float(run["latency_ms"]) > 3_600_000
        or not _valid_normalized_output(normalized)
        or not isinstance(normalized, Mapping)
        or normalized.get("status") != "complete"
        or normalized.get("verdict") != "request_changes_escalate"
        or not any(
            finding.get("rule_id") == "PRIN-006"
            and finding.get("severity") == "blocker"
            and finding.get("artifact") == "model/adrs.yaml"
            and finding.get("location") == "/seaf.change.adr/demo.dependency"
            for finding in normalized.get("findings", [])
            if isinstance(finding, Mapping)
        )
        or not _valid_trusted_raw_capture(run.get("raw_sanitized"), normalized)
    ):
        errors.append("canonical Ouroboros trace is not the accepted ga-05 smoke")
        return False

    raw = run["raw_sanitized"]
    final = run.get("final")
    acceptance = run.get("acceptance")
    if (
        run.get("review_id_sha256") != raw["receipts"]["review_id_sha256"]
        or not isinstance(final, Mapping)
        or set(final)
        != {
            "final_status",
            "verdict",
            "human_review_required",
            "auto_merge",
            "task_digest",
            "review_digest",
        }
        or final.get("final_status") != "completed"
        or final.get("verdict") != "request_changes_escalate"
        or final.get("human_review_required") is not True
        or final.get("auto_merge") is not False
        or not isinstance(final.get("task_digest"), str)
        or not final["task_digest"].startswith("tsk_")
        or DIGEST_RE.fullmatch(final["task_digest"]) is None
        or not isinstance(final.get("review_digest"), str)
        or not final["review_digest"].startswith("rvw_")
        or DIGEST_RE.fullmatch(final["review_digest"]) is None
        or acceptance
        != {"assessment": "PASS", "schema_valid": True, "unsafe_approve": False}
    ):
        errors.append("canonical Ouroboros trace has invalid trusted acceptance receipts")
        return False
    return True


def _capture_set_sha256(runs: list[Mapping[str, Any]]) -> str:
    responses = [
        {
            "case_id": run["case_id"],
            "base_revision": run["base_revision"],
            "head_revision": run["head_revision"],
            "latency_ms": run["latency_ms"],
            "raw_sanitized": run["raw_sanitized_response"],
            "normalized": run["normalized_output"],
        }
        for run in runs
    ]
    canonical = json.dumps(
        responses,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


RELEASE_THRESHOLDS = {
    "blocker_recall": 1.0,
    "unsafe_approve_count": 0,
    "schema_valid_rate": 1.0,
    "precision_min": 0.8,
    "recall_min": 0.8,
    "outcome_accuracy_min": 0.85,
}


def _ratio(numerator: int, denominator: int, *, empty: float) -> float:
    return round(numerator / denominator, 6) if denominator else empty


def _valid_release_metrics(value: Any, expected_cases: int) -> bool:
    fields = {
        "cases_evaluated",
        "cases_passed",
        "schema_valid_rate",
        "status_accuracy",
        "outcome_accuracy",
        "exact_case_accuracy",
        "precision",
        "recall",
        "blocker_recall",
        "unsafe_approve_count",
        "invalid_or_hallucinated_evidence_count",
        "invalid_or_hallucinated_evidence_rate",
        "tp",
        "fp",
        "fn",
        "findings_expected",
        "findings_predicted",
        "evidence_findings_denominator",
        "expected_blockers",
        "latency_ms",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        return False
    integer_fields = {
        "cases_evaluated",
        "cases_passed",
        "unsafe_approve_count",
        "invalid_or_hallucinated_evidence_count",
        "tp",
        "fp",
        "fn",
        "findings_expected",
        "findings_predicted",
        "evidence_findings_denominator",
        "expected_blockers",
    }
    if any(
        isinstance(value.get(field), bool)
        or not isinstance(value.get(field), int)
        or value[field] < 0
        for field in integer_fields
    ):
        return False
    rate_fields = {
        "schema_valid_rate",
        "status_accuracy",
        "outcome_accuracy",
        "exact_case_accuracy",
        "precision",
        "recall",
        "blocker_recall",
        "invalid_or_hallucinated_evidence_rate",
    }
    if any(
        not _is_finite_number(value.get(field)) or float(value[field]) > 1.0
        for field in rate_fields
    ):
        return False
    latency = value.get("latency_ms")
    if (
        value.get("cases_evaluated") != expected_cases
        or value.get("cases_passed") > expected_cases
        or value.get("unsafe_approve_count") != 0
        or value.get("schema_valid_rate") != 1.0
        or value.get("blocker_recall") != 1.0
        or float(value.get("precision")) < RELEASE_THRESHOLDS["precision_min"]
        or float(value.get("recall")) < RELEASE_THRESHOLDS["recall_min"]
        or float(value.get("outcome_accuracy"))
        < RELEASE_THRESHOLDS["outcome_accuracy_min"]
        or value.get("findings_expected") != value.get("tp") + value.get("fn")
        or value.get("findings_predicted") != value.get("tp") + value.get("fp")
        or value.get("evidence_findings_denominator")
        != value.get("findings_predicted")
        or value.get("expected_blockers") != expected_cases // 8
        or value.get("findings_expected") != expected_cases // 2
        or value.get("findings_predicted") > expected_cases * 100
        or value.get("invalid_or_hallucinated_evidence_count")
        > value.get("evidence_findings_denominator")
        or value.get("precision")
        != _ratio(
            value.get("tp"),
            value.get("tp") + value.get("fp"),
            empty=1.0,
        )
        or value.get("recall")
        != _ratio(
            value.get("tp"),
            value.get("tp") + value.get("fn"),
            empty=1.0,
        )
        or value.get("exact_case_accuracy")
        != _ratio(value.get("cases_passed"), expected_cases, empty=0.0)
        or value.get("invalid_or_hallucinated_evidence_rate")
        != _ratio(
            value.get("invalid_or_hallucinated_evidence_count"),
            value.get("evidence_findings_denominator"),
            empty=0.0,
        )
        or not isinstance(latency, Mapping)
        or set(latency) != {"count", "total", "mean", "p50", "p95", "max"}
        or latency.get("count") != expected_cases
        or any(
            not _is_finite_number(latency.get(field))
            for field in ("total", "mean", "p50", "p95", "max")
        )
        or float(latency.get("max")) > 3_600_000
        or float(latency.get("total")) > expected_cases * 3_600_000
        or float(latency.get("total")) < float(latency.get("max"))
        or not (
            float(latency.get("p50"))
            <= float(latency.get("p95"))
            <= float(latency.get("max"))
        )
        or float(latency.get("mean")) > float(latency.get("max"))
    ):
        return False
    return True


def _valid_release_gate(
    value: Any, scope_metrics: Mapping[str, Mapping[str, Any]]
) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "thresholds",
        "scopes",
        "evaluation_passed",
        "release_eligible",
        "release_passed",
        "reason",
    }:
        return False
    if (
        value.get("thresholds") != RELEASE_THRESHOLDS
        or value.get("evaluation_passed") is not True
        or value.get("release_eligible") is not True
        or value.get("release_passed") is not True
        or value.get("reason")
        != "all frozen scopes passed with trusted in-process Ouroboros captures"
    ):
        return False
    scopes = value.get("scopes")
    if not isinstance(scopes, Mapping) or set(scopes) != {
        "development",
        "holdout",
        "overall",
    } or set(scope_metrics) != set(scopes):
        return False
    expected_checks = {
        "blocker_recall": ("blocker_recall", ">=", "blocker_recall"),
        "unsafe_approve_count": (
            "unsafe_approve_count",
            "<=",
            "unsafe_approve_count",
        ),
        "schema_valid_rate": ("schema_valid_rate", ">=", "schema_valid_rate"),
        "precision": ("precision", ">=", "precision_min"),
        "recall": ("recall", ">=", "recall_min"),
        "outcome_accuracy": (
            "outcome_accuracy",
            ">=",
            "outcome_accuracy_min",
        ),
    }
    for scope_name, scope in scopes.items():
        if (
            not isinstance(scope, Mapping)
            or set(scope) != {"checks", "passed"}
            or scope.get("passed") is not True
            or not isinstance(scope.get("checks"), list)
            or len(scope["checks"]) != len(expected_checks)
            or {
                check.get("id")
                for check in scope["checks"]
                if isinstance(check, Mapping)
            }
            != set(expected_checks)
        ):
            return False
        for check in scope["checks"]:
            if (
                not isinstance(check, Mapping)
                or set(check) != {"id", "operator", "threshold", "actual", "passed"}
            ):
                return False
            metric_name, operator, threshold_name = expected_checks[check["id"]]
            threshold = RELEASE_THRESHOLDS[threshold_name]
            actual = scope_metrics[scope_name].get(metric_name)
            if (
                check.get("operator") != operator
                or check.get("threshold") != threshold
                or check.get("actual") != actual
                or check.get("passed") is not True
                or (operator == ">=" and not actual >= threshold)
                or (operator == "<=" and not actual <= threshold)
            ):
                return False
    return True


def _release_metrics_match_runs(
    metrics: Mapping[str, Any], runs: list[Mapping[str, Any]]
) -> bool:
    invalid_evidence = 0
    findings_predicted = 0
    for run in runs:
        normalized = run.get("normalized_output")
        checks = run.get("evidence_checks")
        if not isinstance(normalized, Mapping) or not isinstance(checks, list):
            return False
        findings = normalized.get("findings")
        if not isinstance(findings, list) or len(checks) != len(findings):
            return False
        for index, (check, finding) in enumerate(zip(checks, findings)):
            if (
                not isinstance(check, Mapping)
                or set(check) != {"finding_index", "rule_id", "valid", "reason"}
                or check.get("finding_index") != index
                or check.get("rule_id") != finding.get("rule_id")
                or not isinstance(check.get("valid"), bool)
                or not isinstance(check.get("reason"), str)
                or not check["reason"].strip()
            ):
                return False
            invalid_evidence += check["valid"] is False
        findings_predicted += len(findings)
    expected = {
        "cases_evaluated": len(runs),
        "cases_passed": sum(run.get("assessment") == "PASS" for run in runs),
        "unsafe_approve_count": sum(
            run.get("unsafe_approve") is True for run in runs
        ),
        "invalid_or_hallucinated_evidence_count": invalid_evidence,
        "tp": sum(run.get("tp_count", 0) for run in runs),
        "fp": sum(run.get("fp_count", 0) for run in runs),
        "fn": sum(run.get("fn_count", 0) for run in runs),
        "findings_predicted": findings_predicted,
        "evidence_findings_denominator": findings_predicted,
    }
    if any(metrics.get(field) != actual for field, actual in expected.items()):
        return False
    latency = metrics.get("latency_ms")
    return isinstance(latency, Mapping) and latency.get("total") == round(
        sum(float(run.get("latency_ms", 0.0)) for run in runs), 3
    )


def check_real_results_payload(
    results: Any,
    errors: list[str],
    warnings: list[str],
    *,
    expected_corpus_hash: str,
    expected_ground_truth_hash: str,
) -> bool:
    """Accept the PASS-only sentinel state or a full all-case trusted PASS."""

    if not isinstance(results, Mapping):
        errors.append("GigaAgent results must be a JSON object")
        return False
    if results.get("status") == "not_run":
        warnings.append("canonical trusted Ouroboros all-case PASS evidence is absent")
        if (
            results.get("schema") != RESULTS_SCHEMA
            or results.get("mode") != "real"
            or results.get("measurement_class") != "unconfigured_real"
            or results.get("release_evidence") is not False
            or results.get("corpus_hash") != expected_corpus_hash
            or results.get("ground_truth_hash") != expected_ground_truth_hash
            or results.get("cases_evaluated") != 0
            or results.get("runs") != []
            or any(
                results.get(field) is not None
                for field in ("runtime", "model", "prompt_hash", "config_hash")
            )
            or not isinstance(results.get("gate"), Mapping)
            or results["gate"].get("evaluation_passed") is not False
            or results["gate"].get("release_eligible") is not False
            or results["gate"].get("release_passed") is not False
            or any(
                not isinstance(results.get(scope), Mapping)
                or results[scope].get("cases_evaluated") != 0
                or results[scope].get("metrics") is not None
                for scope in ("development", "holdout", "overall")
            )
        ):
            errors.append("not_run GigaAgent evidence has inconsistent zero-denominator fields")
        return False

    top_fields = {
        "schema",
        "status",
        "mode",
        "measurement_class",
        "release_evidence",
        "captured_at",
        "runtime",
        "provider",
        "model",
        "redaction",
        "prompt_hash",
        "config_hash",
        "corpus",
        "corpus_hash",
        "ground_truth_hash",
        "capture_set_sha256",
        "selection",
        "cases_evaluated",
        "development",
        "holdout",
        "overall",
        "gate",
        "runs",
    }
    if set(results) != top_fields:
        errors.append(
            "results.json is not an exact trusted all-case result; fixture or "
            "manually relabelled evidence is not accepted"
        )
        return False
    selection = results.get("selection")
    gate = results.get("gate")
    scope_metrics = {
        "development": results.get("development"),
        "holdout": results.get("holdout"),
        "overall": results.get("overall"),
    }
    if (
        results.get("schema") != RESULTS_SCHEMA
        or results.get("status") != "trusted_real_scored_release"
        or results.get("mode") != "real"
        or results.get("measurement_class") != "trusted_ouroboros_real"
        or results.get("release_evidence") is not True
        or not isinstance(results.get("captured_at"), str)
        or CAPTURED_AT_RE.fullmatch(results["captured_at"]) is None
        or results.get("runtime") != {"name": "ouroboros", "version": OUROBOROS_VERSION}
        or results.get("provider") != OUROBOROS_PROVIDER
        or results.get("model") != {"name": OUROBOROS_MODEL}
        or results.get("redaction") != REDACTION_CONTRACT
        or not _is_sha256(results.get("prompt_hash"))
        or not _is_sha256(results.get("config_hash"))
        or results.get("corpus_hash") != expected_corpus_hash
        or results.get("ground_truth_hash") != expected_ground_truth_hash
        or not _is_sha256(results.get("capture_set_sha256"))
        or selection != {"kind": "all", "case_ids": list(ALL_CASES)}
        or results.get("cases_evaluated") != len(ALL_CASES)
        or not _valid_release_metrics(
            scope_metrics["development"], len(DEVELOPMENT_CASES)
        )
        or not _valid_release_metrics(scope_metrics["holdout"], len(HOLDOUT_CASES))
        or not _valid_release_metrics(scope_metrics["overall"], len(ALL_CASES))
        or not _valid_release_gate(gate, scope_metrics)
    ):
        errors.append("results.json may contain only a full trusted all-case PASS")
        return False

    runs = results.get("runs")
    if not isinstance(runs, list) or len(runs) != len(ALL_CASES):
        errors.append("trusted all-case results have an invalid run denominator")
        return False
    for index, (run, expected_case) in enumerate(zip(runs, ALL_CASES)):
        expected_split = "development" if expected_case in DEVELOPMENT_CASES else "holdout"
        if (
            not isinstance(run, Mapping)
            or set(run) != TRUSTED_RUN_FIELDS
            or run.get("case_id") != expected_case
            or run.get("split") != expected_split
            or not isinstance(run.get("base_revision"), str)
            or COMMIT_RE.fullmatch(run["base_revision"]) is None
            or not isinstance(run.get("head_revision"), str)
            or COMMIT_RE.fullmatch(run["head_revision"]) is None
            or not _is_finite_number(run.get("latency_ms"))
            or float(run["latency_ms"]) > 3_600_000
            or run.get("schema_valid") is not True
            or run.get("schema_errors") != []
            or not isinstance(run.get("evidence_checks"), list)
            or any(
                isinstance(run.get(field), bool)
                or not isinstance(run.get(field), int)
                or run[field] < 0
                for field in ("tp_count", "fp_count", "fn_count")
            )
            or run.get("unsafe_approve") is not False
            or run.get("assessment") not in {"PASS", "FAIL"}
            or not isinstance(run.get("reason"), str)
            or not run["reason"].strip()
            or not _valid_normalized_output(run.get("normalized_output"))
            or not isinstance(run.get("normalized_output"), Mapping)
            or not _valid_trusted_raw_capture(
                run.get("raw_sanitized_response"), run["normalized_output"]
            )
        ):
            errors.append(f"trusted all-case result run {index} violates the capture contract")
            return False
    scoped_runs = {
        "development": runs[: len(DEVELOPMENT_CASES)],
        "holdout": runs[len(DEVELOPMENT_CASES) :],
        "overall": runs,
    }
    if any(
        not _release_metrics_match_runs(scope_metrics[name], scoped_runs[name])
        for name in scoped_runs
    ):
        errors.append("trusted all-case aggregate metrics do not match the run captures")
        return False
    try:
        capture_hash = _capture_set_sha256(runs)
    except (KeyError, TypeError, ValueError):
        errors.append("trusted all-case capture set is not strict JSON")
        return False
    if capture_hash != results["capture_set_sha256"]:
        errors.append("trusted all-case capture_set_sha256 mismatch")
        return False
    return True


def check_links(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for target in MARKDOWN_LINK_RE.findall(text):
        target = target.strip().split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("/"):
            errors.append(f"absolute local link in {path.relative_to(ROOT)}: {target}")
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"link escapes repository in {path.relative_to(ROOT)}: {target}")
            continue
        if not resolved.exists():
            errors.append(f"broken link in {path.relative_to(ROOT)}: {target}")


def check_sha256_manifest(path: Path, errors: list[str]) -> None:
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            errors.append(f"invalid SHA256SUMS line {line_number}: {line!r}")
            continue
        expected, relative = match.groups()
        if relative in seen:
            errors.append(f"duplicate SHA256SUMS path: {relative}")
            continue
        seen.add(relative)
        candidate = (path.parent / relative).resolve()
        try:
            candidate.relative_to(path.parent.resolve())
        except ValueError:
            errors.append(f"SHA256SUMS path escapes snapshot: {relative}")
            continue
        if not candidate.is_file():
            errors.append(f"SHA256SUMS file is missing: {relative}")
            continue
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(f"SHA256SUMS mismatch: {relative}")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for relative in REQUIRED:
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"required artifact is missing or empty: {relative}")

    for relative in ACTIVE_MARKDOWN:
        path = ROOT / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "Стабильность" in text:
            errors.append(f"obsolete C6 name in active document: {relative}")
        if relative.startswith("docs/submission/"):
            match = PLACEHOLDER_RE.search(text)
            if match:
                errors.append(f"placeholder in submission artifact {relative}: {match.group(0)}")
        check_links(path, errors)

    current_rules = list((ROOT / "aga-skill" / "rules").glob("*.yaml"))
    invented = re.compile(r"SEAF-МЕТАМОДЕЛЬ|АРХ-ПРИНЦИПЫ|РЕГЛАМЕНТ-")
    for path in current_rules:
        if invented.search(path.read_text(encoding="utf-8")):
            errors.append(f"unverifiable source_ref remains in {path.relative_to(ROOT)}")

    garbage = []
    for path in ROOT.rglob("*"):
        try:
            parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if ".git" in parts or "node_modules" in parts or ".tmp" in parts:
            continue
        if path.name in {".DS_Store", "__pycache__", ".pytest_cache"} or path.suffix == ".pyc":
            garbage.append(path.relative_to(ROOT).as_posix())
    if garbage:
        errors.append(f"generated cache files remain: {', '.join(sorted(garbage)[:10])}")

    lock_path = ROOT / "evaluation/gigaagent/corpus.lock.json"
    expected_corpus_hash = ""
    expected_ground_truth_hash = ""
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        errors.append("frozen corpus lock is unreadable")
    else:
        if isinstance(lock, Mapping):
            expected_corpus_hash = str(lock.get("sha256", ""))
            expected_ground_truth_hash = str(lock.get("ground_truth_sha256", ""))
        if not _is_sha256(expected_corpus_hash) or not _is_sha256(
            expected_ground_truth_hash
        ):
            errors.append("frozen corpus lock has invalid evidence hashes")

    prompt_path = (
        ROOT
        / "aga-skill"
        / "prompts"
        / "ouroboros-orchestration-v1.0.5.txt"
    )
    expected_prompt_hash = ""
    try:
        expected_prompt_hash = hashlib.sha256(
            prompt_path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
    except (OSError, UnicodeError):
        errors.append("trusted Ouroboros orchestration prompt is unreadable")

    results_path = ROOT / "evaluation/gigaagent/results.json"
    release_complete = False
    if results_path.is_file():
        try:
            results = json.loads(results_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors.append("evaluation/gigaagent/results.json is not valid JSON")
        else:
            release_complete = check_real_results_payload(
                results,
                errors,
                warnings,
                expected_corpus_hash=expected_corpus_hash,
                expected_ground_truth_hash=expected_ground_truth_hash,
            )

    trace_valid = False
    if OUROBOROS_TRACE.is_file():
        try:
            trace = json.loads(OUROBOROS_TRACE.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors.append("canonical Ouroboros run-sanitized.json is not valid JSON")
        else:
            trace_valid = check_ouroboros_trace_payload(
                trace,
                errors,
                expected_corpus_hash=expected_corpus_hash,
                expected_prompt_hash=expected_prompt_hash,
            )
    if release_complete and not trace_valid:
        errors.append(
            "full trusted results require the canonical accepted Ouroboros ga-05 trace"
        )

    fixture_path = ROOT / "evaluation/gigaagent/fixture-results.json"
    if fixture_path.is_file():
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        if (
            fixture.get("mode") != "fixture"
            or fixture.get("status") != "fixture_scored_non_release"
            or fixture.get("cases_evaluated") != 16
            or fixture.get("release_evidence") is not False
            or fixture.get("gate", {}).get("release_eligible") is not False
            or fixture.get("gate", {}).get("release_passed") is not False
        ):
            errors.append("fixture agent evidence must remain 16-case non-release evidence")

    snapshot_root = ROOT / "docs/evidence/snapshots/deterministic-2026-07-15-v2"
    sums = snapshot_root / "SHA256SUMS"
    if sums.is_file():
        check_sha256_manifest(sums, errors)
    for name in ("metrics-baseline.json", "metrics-candidate.json"):
        path = snapshot_root / name
        if not path.is_file():
            continue
        metrics = json.loads(path.read_text(encoding="utf-8"))
        if (
            metrics.get("cases_evaluated") != 26
            or len(metrics.get("per_pr", [])) != 26
            or metrics.get("llm_coverage", {}).get("cases_evaluated") != 0
        ):
            errors.append(f"deterministic evidence denominator mismatch: {name}")

    commands = (
        [sys.executable, "scripts/check_secrets.py"],
        [sys.executable, "scripts/verify_pins.py"],
        [
            sys.executable,
            "scripts/validate_architecture.py",
            "architecture/dochub.yaml",
        ],
        [sys.executable, "evaluation/gigaagent/runner.py", "--verify-only"],
    )
    for command in commands:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip().splitlines()
            errors.append(f"{' '.join(command[1:])} failed: {detail[0] if detail else 'unknown error'}")

    pdf = ROOT / "docs/submission/presentation.pdf"
    if pdf.is_file():
        try:
            completed = subprocess.run(
                ["pdfinfo", str(pdf)], check=True, capture_output=True, text=True, timeout=15
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            warnings.append("pdfinfo unavailable; presentation page count not checked")
        else:
            page = re.search(r"^Pages:\s+(\d+)$", completed.stdout, re.MULTILINE)
            if not page or int(page.group(1)) != 8:
                errors.append("presentation.pdf must contain exactly 8 concise pages")

    warnings.extend(
        [
            "public repository URL is an external action",
            "narrated public video is an external action",
            "original Project Proposal is absent",
            "GitHub Action tags and Docker base-image tags are not content-addressed",
            "Python dependency artifacts are version-pinned but do not have hashes",
            "container OS packages are not locked to a reproducible snapshot",
        ]
    )
    for warning in warnings:
        print(f"EXTERNAL/WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"PROJECT RESULTS ERROR: {error}", file=sys.stderr)
        return 1
    print("PROJECT RESULTS LOCAL CHECKS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
