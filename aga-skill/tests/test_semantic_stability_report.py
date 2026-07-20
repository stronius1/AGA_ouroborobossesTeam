# -*- coding: utf-8 -*-
"""Offline contracts for the five-repeat semantic stability report."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import semantic_stability_report as stability  # noqa: E402


SOURCE = REPOSITORY_ROOT / "docs/evidence/ouroboros/development-sanitized.json"


def _source() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def _write_repeats(tmp_path: Path, reports: list[dict]) -> list[Path]:
    paths: list[Path] = []
    for index, report in enumerate(reports, start=1):
        path = tmp_path / f"repeat-{index}.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        paths.append(path)
    return paths


def _repeats(count: int = 5) -> list[dict]:
    reports: list[dict] = []
    for index in range(1, count + 1):
        report = copy.deepcopy(_source())
        report["capture_set_sha256"] = f"{index:064x}"
        report["captured_at"] = f"2026-07-19T00:00:{index:02d}Z"
        reports.append(report)
    return reports


def test_five_identical_complete_development_repeats_pass(tmp_path: Path) -> None:
    paths = _write_repeats(tmp_path, _repeats())

    report = stability.build_report(
        paths,
        max_p95_ms=150_000,
        max_cost_usd=1.0,
        generated_at="2026-07-19T00:00:00Z",
    )

    assert report["status"] == "passed"
    assert report["stability_passed"] is True
    assert report["repeat_count"] == 5
    assert report["worst_case"]["blocker_recall"] == 1.0
    assert report["worst_case"]["unsafe_approve_count"] == 0
    assert report["decision_flaps"] == []
    assert report["dangerous_flaps"] == []
    assert all(item["gate_passed"] for item in report["repeats"])


def test_approve_vs_nonapprove_flap_fails_even_when_aggregate_metrics_pass(
    tmp_path: Path,
) -> None:
    reports = _repeats()
    case = reports[-1]["runs"][0]
    case["normalized_output"]["status"] = "complete"
    case["normalized_output"]["verdict"] = "approve"
    paths = _write_repeats(tmp_path, reports)

    report = stability.build_report(
        paths, max_p95_ms=150_000, max_cost_usd=1.0
    )

    assert report["stability_passed"] is False
    assert report["failure_reasons"] == ["approve_vs_nonapprove_flapping"]
    assert report["dangerous_flaps"] == [
        {
            "case_id": "ga-01-reuse-duplicate",
            "decisions": [
                "complete:approve",
                "complete:request_changes_escalate",
            ],
        }
    ]


def test_repeat_gate_uses_worst_case_latency_cost_and_quality(tmp_path: Path) -> None:
    reports = _repeats()
    reports[2]["development"]["unsafe_approve_count"] = 1
    reports[3]["development"]["latency_ms"]["p95"] = 200_000
    reports[4]["runs"][0]["raw_sanitized_response"]["model_usage"]["known_cost_usd"] = 2.0
    paths = _write_repeats(tmp_path, reports)

    report = stability.build_report(
        paths, max_p95_ms=150_000, max_cost_usd=1.0
    )

    assert report["stability_passed"] is False
    assert report["worst_case"]["unsafe_approve_count"] == 1
    assert report["worst_case"]["latency_p95_ms"] == 200_000
    assert report["worst_case"]["cost_usd"] > 1.0
    assert report["repeats"][2]["gate_failures"] == ["unsafe_approve_count"]
    assert report["repeats"][3]["gate_failures"] == ["latency_p95_ms"]
    assert report["repeats"][4]["gate_failures"] == ["cost_usd"]


def test_identity_drift_and_incomplete_cost_are_fail_closed(tmp_path: Path) -> None:
    reports = _repeats()
    reports[-1]["prompt_hash"] = "f" * 64
    with pytest.raises(stability.StabilityReportError, match="drift"):
        stability.build_report(
            _write_repeats(tmp_path, reports),
            max_p95_ms=150_000,
            max_cost_usd=1.0,
        )

    reports = _repeats()
    reports[-1]["runs"][0]["raw_sanitized_response"]["model_usage"]["cost_complete"] = False
    report = stability.build_report(
        _write_repeats(tmp_path, reports),
        max_p95_ms=150_000,
        max_cost_usd=1.0,
    )
    assert report["stability_passed"] is False
    assert report["repeats"][-1]["gate_failures"] == ["cost_incomplete"]


def test_fewer_than_five_repeats_are_diagnostic_only(tmp_path: Path) -> None:
    paths = _write_repeats(tmp_path, _repeats(4))

    report = stability.build_report(
        paths, max_p95_ms=150_000, max_cost_usd=1.0
    )

    assert report["stability_passed"] is False
    assert report["failure_reasons"] == ["fewer_than_five_repeats"]


def test_copying_one_capture_five_times_cannot_satisfy_repeat_gate(tmp_path: Path) -> None:
    reports = [copy.deepcopy(_source()) for _ in range(5)]

    with pytest.raises(stability.StabilityReportError, match="distinct trusted capture"):
        stability.build_report(
            _write_repeats(tmp_path, reports),
            max_p95_ms=150_000,
            max_cost_usd=1.0,
        )
