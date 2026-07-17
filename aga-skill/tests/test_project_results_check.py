# -*- coding: utf-8 -*-
"""Offline release-boundary checks for trusted Ouroboros evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evaluation.gigaagent import runner as evaluator  # noqa: E402
from scripts import project_results_check as checker  # noqa: E402


FIXTURE_BUNDLE = (
    REPOSITORY_ROOT
    / "evaluation"
    / "gigaagent"
    / "fixtures"
    / "sanitized-response-bundle.json"
)
FIXTURE_RESULTS = REPOSITORY_ROOT / "evaluation/gigaagent/fixture-results.json"


def _raw_capture(index: int, normalized: Mapping[str, Any]) -> dict[str, Any]:
    incomplete = normalized["status"] == "incomplete"
    review_hash = hashlib.sha256(f"review-{index}".encode()).hexdigest()
    return {
        "task_id": f"ouroboros-task-{index}",
        "task_status": "failed" if incomplete else "succeeded",
        "rendered_prompt_sha256": "a" * 64,
        "receipts": {
            "review_id_sha256": review_hash,
            "tool_names": ["aga_prepare_review", "aga_finalize_review"],
            "prepare": {
                "args_sha256": "b" * 64,
                "output_sha256": "c" * 64,
                "status": "ready",
            },
            "finalize": {
                "args_sha256": "d" * 64,
                "output_sha256": "e" * 64,
                "status": "incomplete" if incomplete else "completed",
            },
        },
        "model_usage": {
            "provider": checker.OUROBOROS_PROVIDER,
            "model": checker.OUROBOROS_MODEL,
            "call_count": 1,
            "known_cost_usd": 0.001,
            "cost_complete": True,
        },
    }


def _valid_smoke_trace(corpus_hash: str, prompt_hash: str) -> dict[str, Any]:
    bundle = json.loads(FIXTURE_BUNDLE.read_text(encoding="utf-8"))
    response = next(
        item
        for item in bundle["responses"]
        if item["case_id"] == checker.OUROBOROS_SMOKE_CASE
    )
    normalized = copy.deepcopy(response["normalized"])
    raw = _raw_capture(5, normalized)
    return {
        "schema": checker.OUROBOROS_TRACE_SCHEMA,
        "status": "passed",
        "captured_at": "2026-07-16T13:00:00Z",
        "runtime": {"name": "ouroboros", "version": checker.OUROBOROS_VERSION},
        "provider": checker.OUROBOROS_PROVIDER,
        "model": {"name": checker.OUROBOROS_MODEL},
        "data_classification": "synthetic-public",
        "redaction": dict(checker.REDACTION_CONTRACT),
        "corpus_hash": corpus_hash,
        "prompt_template_sha256": prompt_hash,
        "config_sha256": "f" * 64,
        "preflight": {
            "status": "ready",
            "attestation_sha256": "1" * 64,
            "tool_count": len(checker.OUROBOROS_TOOLS),
            "tools": list(checker.OUROBOROS_TOOLS),
        },
        "run": {
            "case_id": checker.OUROBOROS_SMOKE_CASE,
            "base_revision": checker.OUROBOROS_SMOKE_BASE,
            "head_revision": checker.OUROBOROS_SMOKE_HEAD,
            "latency_ms": 123.5,
            "raw_sanitized": raw,
            "normalized": normalized,
            "review_id_sha256": raw["receipts"]["review_id_sha256"],
            "final": {
                "final_status": "completed",
                "verdict": "request_changes_escalate",
                "human_review_required": True,
                "auto_merge": False,
                "task_digest": "tsk_" + "2" * 64,
                "review_digest": "rvw_" + "3" * 64,
            },
            "acceptance": {
                "assessment": "PASS",
                "schema_valid": True,
                "unsafe_approve": False,
            },
        },
    }


def _trusted_full_result(
    *, with_grounded_false_positive: bool = False
) -> Mapping[str, Any]:
    bundle = json.loads(FIXTURE_BUNDLE.read_text(encoding="utf-8"))
    responses = copy.deepcopy(bundle["responses"])
    if with_grounded_false_positive:
        duplicate = copy.deepcopy(responses[0]["normalized"]["findings"][0])
        duplicate["location"] = "/components/demo.profile"
        responses[0]["normalized"]["findings"].append(duplicate)
    for index, response in enumerate(responses, 1):
        response["raw_sanitized"] = _raw_capture(index, response["normalized"])
    return evaluator.score_trusted_ouroboros_responses(
        responses,
        captured_at="2026-07-16T13:00:00Z",
        runtime_version=checker.OUROBOROS_VERSION,
        provider=checker.OUROBOROS_PROVIDER,
        model_name=checker.OUROBOROS_MODEL,
        prompt_hash="4" * 64,
        config_hash="5" * 64,
    )


def test_canonical_smoke_trace_accepts_only_exact_trusted_shape() -> None:
    errors: list[str] = []
    trace = _valid_smoke_trace("6" * 64, "7" * 64)

    assert checker.check_ouroboros_trace_payload(
        trace,
        errors,
        expected_corpus_hash="6" * 64,
        expected_prompt_hash="7" * 64,
    )
    assert errors == []

    trace["mode"] = "real"
    assert not checker.check_ouroboros_trace_payload(
        trace,
        errors := [],
        expected_corpus_hash="6" * 64,
        expected_prompt_hash="7" * 64,
    )
    assert any("manually relabelled" in error for error in errors)


def test_fixture_result_cannot_be_used_as_canonical_real_trace() -> None:
    fixture = json.loads(FIXTURE_RESULTS.read_text(encoding="utf-8"))
    errors: list[str] = []

    assert not checker.check_ouroboros_trace_payload(
        fixture,
        errors,
        expected_corpus_hash=fixture["corpus_hash"],
        expected_prompt_hash=fixture["prompt_hash"],
    )
    assert any("fixture" in error for error in errors)


def test_results_accept_only_full_all_case_trusted_pass() -> None:
    result = _trusted_full_result()
    errors: list[str] = []
    warnings: list[str] = []

    assert checker.check_real_results_payload(
        result,
        errors,
        warnings,
        expected_corpus_hash=result["corpus_hash"],
        expected_ground_truth_hash=result["ground_truth_hash"],
    )
    assert errors == []
    assert warnings == []

    partial = dict(result)
    partial["status"] = "trusted_real_scored_non_release"
    partial["release_evidence"] = False
    partial["selection"] = {
        "kind": "development",
        "case_ids": list(checker.DEVELOPMENT_CASES),
    }
    partial["cases_evaluated"] = len(checker.DEVELOPMENT_CASES)
    assert not checker.check_real_results_payload(
        partial,
        errors := [],
        warnings := [],
        expected_corpus_hash=result["corpus_hash"],
        expected_ground_truth_hash=result["ground_truth_hash"],
    )
    assert any("full trusted all-case PASS" in error for error in errors)


def test_results_accept_nonperfect_cases_when_all_aggregate_gates_pass() -> None:
    result = _trusted_full_result(with_grounded_false_positive=True)
    errors: list[str] = []

    assert result["development"]["cases_passed"] == 7
    assert result["development"]["precision"] == 0.8
    assert result["runs"][0]["assessment"] == "FAIL"
    assert result["gate"]["release_passed"] is True
    assert checker.check_real_results_payload(
        result,
        errors,
        [],
        expected_corpus_hash=result["corpus_hash"],
        expected_ground_truth_hash=result["ground_truth_hash"],
    )
    assert errors == []


def test_results_reject_gate_actual_that_disagrees_with_scope_metrics() -> None:
    result = copy.deepcopy(_trusted_full_result(with_grounded_false_positive=True))
    precision_check = next(
        check
        for check in result["gate"]["scopes"]["development"]["checks"]
        if check["id"] == "precision"
    )
    precision_check["actual"] = 0.9

    assert not checker.check_real_results_payload(
        result,
        errors := [],
        [],
        expected_corpus_hash=result["corpus_hash"],
        expected_ground_truth_hash=result["ground_truth_hash"],
    )
    assert any("full trusted all-case PASS" in error for error in errors)


def test_results_reject_metric_denominator_inconsistency() -> None:
    result = copy.deepcopy(_trusted_full_result(with_grounded_false_positive=True))
    result["development"]["findings_predicted"] += 1

    assert not checker.check_real_results_payload(
        result,
        errors := [],
        [],
        expected_corpus_hash=result["corpus_hash"],
        expected_ground_truth_hash=result["ground_truth_hash"],
    )
    assert any("full trusted all-case PASS" in error for error in errors)


def test_fixture_results_cannot_be_relabelled_as_release_results() -> None:
    fixture = json.loads(FIXTURE_RESULTS.read_text(encoding="utf-8"))
    fixture["mode"] = "real"
    fixture["status"] = "trusted_real_scored_release"
    fixture["measurement_class"] = "trusted_ouroboros_real"
    fixture["release_evidence"] = True
    errors: list[str] = []

    assert not checker.check_real_results_payload(
        fixture,
        errors,
        [],
        expected_corpus_hash=fixture["corpus_hash"],
        expected_ground_truth_hash=fixture["ground_truth_hash"],
    )
    assert any("manually relabelled" in error for error in errors)


def test_makefile_keeps_smoke_fixed_and_all_paid_targets_double_gated() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    assert (
        "ouroboros-materialize:\n"
        "\t$(PYTHON) scripts/materialize_ouroboros_cases.py "
        "--case ga-05-critical-eliminate\n"
        in makefile
    )
    assert (
        "demo-e2e:\n"
        "\t$(OUROBOROS_PROFILE_MANAGER) exec -- $(PYTHON) "
        "scripts/run_ouroboros_e2e.py --case ga-05-critical-eliminate\n"
        in makefile
    )
    for split in ("development", "holdout", "all"):
        assert (
            f"evaluate-ouroboros-{split}: ouroboros-full-run-approval\n"
            "\t$(OUROBOROS_PROFILE_MANAGER) exec -- $(PYTHON) "
            f"scripts/run_ouroboros_evaluation.py --split {split} "
            "--confirm-full-run\n"
            in makefile
        )
    assert "ifeq ($(OUROBOROS_FULL_RUN_APPROVED),yes)" in makefile
