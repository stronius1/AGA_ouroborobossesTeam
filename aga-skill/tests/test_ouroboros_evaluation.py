# -*- coding: utf-8 -*-
"""Offline contracts for trusted in-process Ouroboros evaluation."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evaluation.gigaagent import runner as evaluator  # noqa: E402
from scripts import run_ouroboros_e2e as e2e  # noqa: E402
from scripts import run_ouroboros_evaluation as evaluation  # noqa: E402


FIXTURE_BUNDLE = (
    REPOSITORY_ROOT
    / "evaluation"
    / "gigaagent"
    / "fixtures"
    / "sanitized-response-bundle.json"
)
PROMPT_HASH = "a" * 64
CONFIG_HASH = "b" * 64


def _responses() -> dict[str, dict[str, Any]]:
    bundle = json.loads(FIXTURE_BUNDLE.read_text(encoding="utf-8"))
    return {
        response["case_id"]: copy.deepcopy(response)
        for response in bundle["responses"]
    }


def _case_runner(
    responses: Mapping[str, Mapping[str, Any]], calls: list[str]
):
    def run(
        case_id: str,
        *,
        timeout_seconds: float,
        evidence_out: Path | None,
        require_acceptance: bool,
    ) -> e2e.TrustedCaseRun:
        calls.append(case_id)
        assert timeout_seconds == 600.0
        assert evidence_out is None
        assert require_acceptance is False
        response = copy.deepcopy(responses[case_id])
        evidence = {
            "schema": e2e.EVIDENCE_SCHEMA,
            "prompt_template_sha256": PROMPT_HASH,
            "config_sha256": CONFIG_HASH,
        }
        return e2e.TrustedCaseRun(
            case_id=case_id,
            response=response,
            evidence=evidence,
            score={},
        )

    return run


def test_confirmation_gate_precedes_case_selection_and_every_runner_call(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    output = tmp_path / "must-not-exist.json"

    with pytest.raises(evaluation.EvaluationError) as caught:
        evaluation.run_evaluation(
            "development",
            confirmed=False,
            output=output,
            case_runner=_case_runner(_responses(), calls),
            evidence_root=tmp_path,
        )

    assert caught.value.status == "not_authorized"
    assert caught.value.code == "full_run_confirmation_required"
    assert calls == []
    assert not output.exists()


def test_complete_development_split_scores_in_memory_and_writes_atomically(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    output = tmp_path / "development.json"
    result = evaluation.run_evaluation(
        "development",
        confirmed=True,
        output=output,
        case_runner=_case_runner(_responses(), calls),
        now=lambda: datetime(2026, 7, 16, 13, 0, tzinfo=timezone.utc),
        evidence_root=tmp_path,
    )

    assert calls == [f"ga-{index:02d}-{suffix}" for index, suffix in (
        (1, "reuse-duplicate"),
        (2, "reuse-existing"),
        (3, "second-master"),
        (4, "read-replica"),
        (5, "critical-eliminate"),
        (6, "noncritical-near-miss"),
        (7, "significant-no-adr"),
        (8, "cosmetic-no-adr"),
    )]
    assert result["schema"] == evaluator.TRUSTED_OUROBOROS_RESULTS_SCHEMA
    assert result["selection"]["kind"] == "development"
    assert result["cases_evaluated"] == 8
    assert result["release_evidence"] is False
    assert result["development"]["exact_case_accuracy"] == 1.0
    assert result["gate"]["evaluation_passed"] is True
    assert result["gate"]["release_eligible"] is False
    assert result["gate"]["release_passed"] is False
    assert all("expected" not in run and "fn" not in run for run in result["runs"])
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_gate_failure_publishes_no_result(tmp_path: Path) -> None:
    responses = _responses()
    responses["ga-01-reuse-duplicate"]["normalized"] = {
        "status": "complete",
        "verdict": "approve",
        "findings": [],
    }
    output = tmp_path / "must-not-exist.json"

    with pytest.raises(evaluation.EvaluationError) as caught:
        evaluation.run_evaluation(
            "development",
            confirmed=True,
            output=output,
            case_runner=_case_runner(responses, []),
            evidence_root=tmp_path,
        )

    assert caught.value.code == "evaluation_gate_failed"
    assert not output.exists()


def test_aggregate_gate_pass_allows_a_nonperfect_case(tmp_path: Path) -> None:
    responses = _responses()
    duplicate = copy.deepcopy(
        responses["ga-01-reuse-duplicate"]["normalized"]["findings"][0]
    )
    duplicate["location"] = "/components/demo.profile"
    responses["ga-01-reuse-duplicate"]["normalized"]["findings"].append(duplicate)

    result = evaluation.run_evaluation(
        "development",
        confirmed=True,
        output=tmp_path / "development.json",
        case_runner=_case_runner(responses, []),
        evidence_root=tmp_path,
    )

    assert result["development"]["cases_passed"] == 7
    assert result["development"]["precision"] == 0.8
    assert result["runs"][0]["assessment"] == "FAIL"
    assert result["gate"]["evaluation_passed"] is True


def test_trusted_scorer_rejects_cherry_picked_measurement_selection() -> None:
    responses = list(_responses().values())[:2]

    with pytest.raises(ValueError, match="one smoke case, one complete"):
        evaluator.score_trusted_ouroboros_responses(
            responses,
            captured_at="2026-07-16T13:00:00Z",
            runtime_version=e2e.PINNED_VERSION,
            provider=e2e.PROVIDER,
            model_name=e2e.MODEL_ID,
            prompt_hash=PROMPT_HASH,
            config_hash=CONFIG_HASH,
        )


def test_real_bundle_path_remains_untrusted_and_disabled() -> None:
    with pytest.raises(ValueError, match="real bundle scoring is forbidden"):
        evaluator.score_response_bundle(FIXTURE_BUNDLE, mode="real")


def test_full_selection_cannot_write_to_an_arbitrary_path_before_any_case_call(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    with pytest.raises(evaluation.EvaluationError) as caught:
        evaluation.run_evaluation(
            "all",
            confirmed=True,
            output=tmp_path / "forged-results.json",
            case_runner=_case_runner(_responses(), calls),
            evidence_root=tmp_path,
        )

    assert caught.value.code == "full_results_path_mismatch"
    assert calls == []


def test_cli_without_confirmation_is_typed_and_does_not_start_evaluation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = evaluation.main(["--split", "holdout"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload == {
        "schema": evaluation.CLI_RESULT_SCHEMA,
        "status": "not_authorized",
        "code": "full_run_confirmation_required",
        "split": "holdout",
    }
