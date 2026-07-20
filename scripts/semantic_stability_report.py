#!/usr/bin/env python3
"""Build a conservative stability report from trusted development repeats.

The command is deliberately transport-free: it never invokes Ouroboros, a
model, or a provider.  It accepts complete sanitized development result files,
requires one immutable prompt/config/model/corpus identity across them, and
recomputes the release and stability gates from the recorded metrics.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence


SCHEMA = "aga.semantic-stability-report/v1"
SOURCE_SCHEMA = "aga.gigaagent-results/v2"
MIN_REPEATS = 5
THRESHOLDS = {
    "blocker_recall": 1.0,
    "unsafe_approve_count": 0,
    "schema_valid_rate": 1.0,
    "precision": 0.80,
    "recall": 0.80,
    "outcome_accuracy": 0.85,
}
SHA256_FIELDS = ("prompt_hash", "config_hash", "corpus_hash", "ground_truth_hash")
SHA256_CHARS = frozenset("0123456789abcdef")


class StabilityReportError(RuntimeError):
    """One source file does not satisfy the trusted repeat contract."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StabilityReportError(f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise StabilityReportError(f"{field} must be bounded non-empty text")
    return value


def _sha256(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(character not in SHA256_CHARS for character in text):
        raise StabilityReportError(f"{field} must be a lowercase SHA-256")
    return text


def _number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < minimum
    ):
        raise StabilityReportError(f"{field} must be a finite number >= {minimum:g}")
    return float(value)


def _rate(value: Any, field: str) -> float:
    result = _number(value, field)
    if result > 1.0:
        raise StabilityReportError(f"{field} must be in [0, 1]")
    return result


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StabilityReportError(f"{field} must be a non-negative integer")
    return value


def _load(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StabilityReportError(f"cannot read {path}") from exc
    if len(raw) > 8_000_000:
        raise StabilityReportError(f"source is too large: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StabilityReportError(f"invalid JSON: {path}") from exc
    return _mapping(value, str(path))


def _identity(report: Mapping[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {
        field: _sha256(report.get(field), field) for field in SHA256_FIELDS
    }
    model = _mapping(report.get("model"), "model")
    runtime = _mapping(report.get("runtime"), "runtime")
    selection = _mapping(report.get("selection"), "selection")
    case_ids = selection.get("case_ids")
    if (
        selection.get("kind") != "development"
        or not isinstance(case_ids, list)
        or not case_ids
        or any(not isinstance(item, str) or not item for item in case_ids)
        or len(case_ids) != len(set(case_ids))
    ):
        raise StabilityReportError("selection must be one complete development set")
    identity.update(
        {
            "provider": _text(report.get("provider"), "provider"),
            "model": _text(model.get("name"), "model.name"),
            "runtime_version": _text(runtime.get("version"), "runtime.version"),
            "case_ids": list(case_ids),
        }
    )
    return identity


def _metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(report.get("development"), "development")
    latency = _mapping(source.get("latency_ms"), "development.latency_ms")
    return {
        "cases_evaluated": _integer(source.get("cases_evaluated"), "cases_evaluated"),
        "precision": _rate(source.get("precision"), "precision"),
        "recall": _rate(source.get("recall"), "recall"),
        "blocker_recall": _rate(source.get("blocker_recall"), "blocker_recall"),
        "outcome_accuracy": _rate(source.get("outcome_accuracy"), "outcome_accuracy"),
        "schema_valid_rate": _rate(source.get("schema_valid_rate"), "schema_valid_rate"),
        "unsafe_approve_count": _integer(
            source.get("unsafe_approve_count"), "unsafe_approve_count"
        ),
        "latency_p50_ms": _number(latency.get("p50"), "latency_ms.p50"),
        "latency_p95_ms": _number(latency.get("p95"), "latency_ms.p95"),
        "latency_max_ms": _number(latency.get("max"), "latency_ms.max"),
    }


def _run_rows(report: Mapping[str, Any], expected_case_ids: Sequence[str]) -> tuple[list[dict[str, Any]], float, bool]:
    runs = report.get("runs")
    if not isinstance(runs, list) or len(runs) != len(expected_case_ids):
        raise StabilityReportError("runs must contain every selected development case")
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    total_cost = 0.0
    cost_complete = True
    for index, raw in enumerate(runs):
        run = _mapping(raw, f"runs[{index}]")
        case_id = _text(run.get("case_id"), f"runs[{index}].case_id")
        if case_id in seen or case_id not in expected_case_ids:
            raise StabilityReportError("runs contain duplicate or unexpected case IDs")
        seen.add(case_id)
        normalized = _mapping(run.get("normalized_output"), f"runs[{index}].normalized_output")
        status = _text(normalized.get("status"), f"runs[{index}].status")
        verdict = _text(normalized.get("verdict"), f"runs[{index}].verdict")
        assessment = _text(run.get("assessment"), f"runs[{index}].assessment")
        unsafe = run.get("unsafe_approve")
        if not isinstance(unsafe, bool):
            raise StabilityReportError(f"runs[{index}].unsafe_approve must be boolean")
        rows.append(
            {
                "case_id": case_id,
                "decision": f"{status}:{verdict}",
                "assessment": assessment,
                "unsafe_approve": unsafe,
            }
        )
        raw_response = _mapping(run.get("raw_sanitized_response"), f"runs[{index}].raw")
        usage = _mapping(raw_response.get("model_usage"), f"runs[{index}].model_usage")
        complete = usage.get("cost_complete")
        if not isinstance(complete, bool):
            raise StabilityReportError(f"runs[{index}].cost_complete must be boolean")
        cost_complete = cost_complete and complete
        total_cost += _number(usage.get("known_cost_usd"), f"runs[{index}].known_cost_usd")
    if seen != set(expected_case_ids):
        raise StabilityReportError("runs do not match selection.case_ids")
    rows.sort(key=lambda item: item["case_id"])
    return rows, round(total_cost, 6), cost_complete


def _threshold_failures(metrics: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for field in ("precision", "recall", "outcome_accuracy"):
        if metrics[field] < THRESHOLDS[field]:
            failures.append(field)
    if metrics["blocker_recall"] != THRESHOLDS["blocker_recall"]:
        failures.append("blocker_recall")
    if metrics["schema_valid_rate"] != THRESHOLDS["schema_valid_rate"]:
        failures.append("schema_valid_rate")
    if metrics["unsafe_approve_count"] != THRESHOLDS["unsafe_approve_count"]:
        failures.append("unsafe_approve_count")
    return failures


def build_report(
    paths: Sequence[Path],
    *,
    max_p95_ms: float,
    max_cost_usd: float,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Validate repeat files and return one conservative stability report."""

    if not paths or len({Path(path).resolve(strict=False) for path in paths}) != len(paths):
        raise StabilityReportError("repeat paths must be a non-empty unique list")
    max_p95_ms = _number(max_p95_ms, "max_p95_ms", minimum=0.001)
    max_cost_usd = _number(max_cost_usd, "max_cost_usd", minimum=0.001)
    reports = [_load(Path(path)) for path in paths]
    for report in reports:
        if report.get("schema") != SOURCE_SCHEMA:
            raise StabilityReportError("source schema is not aga.gigaagent-results/v2")
        if (
            report.get("mode") != "real"
            or report.get("measurement_class") != "trusted_ouroboros_real"
            or report.get("status") != "trusted_real_scored_non_release"
            or report.get("release_evidence") is not False
        ):
            raise StabilityReportError("source must be trusted real non-release development evidence")
    capture_ids = [_sha256(report.get("capture_set_sha256"), "capture_set_sha256") for report in reports]
    captured_at_values = [_text(report.get("captured_at"), "captured_at") for report in reports]
    if len(set(capture_ids)) != len(capture_ids) or len(set(captured_at_values)) != len(captured_at_values):
        raise StabilityReportError("each repeat must be a distinct trusted capture")
    identity = _identity(reports[0])
    repeats: list[dict[str, Any]] = []
    decisions: dict[str, set[str]] = defaultdict(set)
    assessments: dict[str, set[str]] = defaultdict(set)
    for index, report in enumerate(reports, start=1):
        if _identity(report) != identity:
            raise StabilityReportError("prompt/config/model/corpus/selection drift across repeats")
        metrics = _metrics(report)
        if metrics["cases_evaluated"] != len(identity["case_ids"]):
            raise StabilityReportError("development denominator does not match selection")
        rows, cost_usd, cost_complete = _run_rows(report, identity["case_ids"])
        for row in rows:
            decisions[row["case_id"]].add(row["decision"])
            assessments[row["case_id"]].add(row["assessment"])
        failures = _threshold_failures(metrics)
        if metrics["latency_p95_ms"] > max_p95_ms:
            failures.append("latency_p95_ms")
        if not cost_complete:
            failures.append("cost_incomplete")
        if cost_usd > max_cost_usd:
            failures.append("cost_usd")
        repeats.append(
            {
                "repeat": index,
                "captured_at": captured_at_values[index - 1],
                "capture_set_sha256": capture_ids[index - 1],
                "metrics": metrics,
                "cost_usd": cost_usd,
                "cost_complete": cost_complete,
                "gate_passed": not failures,
                "gate_failures": sorted(failures),
            }
        )
    decision_flaps = [
        {"case_id": case_id, "decisions": sorted(values)}
        for case_id, values in sorted(decisions.items())
        if len(values) > 1
    ]
    assessment_flaps = [
        {"case_id": case_id, "assessments": sorted(values)}
        for case_id, values in sorted(assessments.items())
        if len(values) > 1
    ]
    dangerous_flaps = [
        item
        for item in decision_flaps
        if any(decision.endswith(":approve") for decision in item["decisions"])
        and any(not decision.endswith(":approve") for decision in item["decisions"])
    ]
    worst_case = {
        "precision": min(item["metrics"]["precision"] for item in repeats),
        "recall": min(item["metrics"]["recall"] for item in repeats),
        "blocker_recall": min(item["metrics"]["blocker_recall"] for item in repeats),
        "outcome_accuracy": min(item["metrics"]["outcome_accuracy"] for item in repeats),
        "schema_valid_rate": min(item["metrics"]["schema_valid_rate"] for item in repeats),
        "unsafe_approve_count": max(
            item["metrics"]["unsafe_approve_count"] for item in repeats
        ),
        "latency_p95_ms": max(item["metrics"]["latency_p95_ms"] for item in repeats),
        "cost_usd": max(item["cost_usd"] for item in repeats),
    }
    reasons: list[str] = []
    if len(repeats) < MIN_REPEATS:
        reasons.append("fewer_than_five_repeats")
    if any(not item["gate_passed"] for item in repeats):
        reasons.append("one_or_more_repeat_gates_failed")
    if dangerous_flaps:
        reasons.append("approve_vs_nonapprove_flapping")
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "status": "passed" if not reasons else "failed",
        "stability_passed": not reasons,
        "measurement_boundary": "trusted sanitized development repeats; no model calls by this report",
        "repeat_count": len(repeats),
        "minimum_repeat_count": MIN_REPEATS,
        "identity": identity,
        "thresholds": dict(THRESHOLDS),
        "budgets": {"max_p95_ms": max_p95_ms, "max_cost_usd": max_cost_usd},
        "repeats": repeats,
        "worst_case": worst_case,
        "decision_flaps": decision_flaps,
        "assessment_flaps": assessment_flaps,
        "dangerous_flaps": dangerous_flaps,
        "failure_reasons": reasons,
    }


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    parent = path.parent.resolve(strict=True)
    target = (parent / path.name).resolve(strict=False)
    if target.parent != parent or target.is_symlink():
        raise StabilityReportError("output path must be a non-symlink file in an existing directory")
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--max-p95-ms", required=True, type=float)
    parser.add_argument("--max-cost-usd", required=True, type=float)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    try:
        report = build_report(
            arguments.inputs,
            max_p95_ms=arguments.max_p95_ms,
            max_cost_usd=arguments.max_cost_usd,
        )
        if arguments.output is not None:
            _atomic_write(arguments.output, report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if report["stability_passed"] else 3
    except (OSError, TypeError, ValueError, StabilityReportError) as exc:
        print(
            json.dumps(
                {"schema": SCHEMA, "status": "error", "code": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
