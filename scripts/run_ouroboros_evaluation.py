#!/usr/bin/env python3
"""Trusted paid Ouroboros evaluation over a complete frozen selection.

Unlike the legacy bundle scorer, this command accepts no response file and no
caller-provided real/fixture label.  It invokes the trusted one-case runner for
every member of one complete frozen split (or all 16 cases), keeps captures in
memory, scores them immediately, and writes only a passing sanitized result.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evaluation.gigaagent import runner as evaluator  # noqa: E402
from scripts import run_ouroboros_e2e as e2e  # noqa: E402


CLI_RESULT_SCHEMA = "aga.ouroboros-evaluation-result/v1"
DEFAULT_OUTPUTS = {
    "development": (
        REPOSITORY_ROOT
        / "docs"
        / "evidence"
        / "ouroboros"
        / "development-sanitized.json"
    ),
    "holdout": (
        REPOSITORY_ROOT
        / "docs"
        / "evidence"
        / "ouroboros"
        / "holdout-sanitized.json"
    ),
    "all": evaluator.REAL_RESULTS,
}


class EvaluationError(RuntimeError):
    def __init__(self, status: str, code: str) -> None:
        if status not in {"not_authorized", "not_configured", "failed"}:
            raise ValueError("invalid evaluation status")
        self.status = status
        self.code = code
        super().__init__(code)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvaluationError("failed", "clock_not_utc")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _selected_cases(split: str) -> list[Mapping[str, Any]]:
    if split not in {"development", "holdout", "all"}:
        raise EvaluationError("failed", "invalid_split")
    try:
        paths = evaluator.corpus_files()
        evaluator.verify_lock(paths)
        cases = evaluator._cases_from_paths(paths)
    except (OSError, TypeError, ValueError) as exc:
        raise EvaluationError("failed", "corpus_lock_failed") from exc
    selected = list(cases) if split == "all" else [
        case for case in cases if case["split"] == split
    ]
    expected_count = 16 if split == "all" else 8
    if len(selected) != expected_count:
        raise EvaluationError("failed", "frozen_selection_mismatch")
    return selected


def _validated_output_path(
    split: str,
    output: Path | None,
    *,
    root: Path = REPOSITORY_ROOT,
) -> Path:
    target = Path(output) if output is not None else DEFAULT_OUTPUTS[split]
    target = (
        target if target.is_absolute() else root / target
    ).resolve(strict=False)
    root = root.resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise EvaluationError("failed", "output_path_outside_repository") from exc
    if split == "all" and target != evaluator.REAL_RESULTS.resolve(strict=False):
        raise EvaluationError("failed", "full_results_path_mismatch")
    if split != "all" and target == evaluator.REAL_RESULTS.resolve(strict=False):
        raise EvaluationError("failed", "partial_cannot_overwrite_results")
    return target


def run_evaluation(
    split: str,
    *,
    confirmed: bool,
    timeout_per_case: float = 600.0,
    output: Path | None = None,
    case_runner: Callable[..., e2e.TrustedCaseRun] = e2e.run_trusted_case,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    evidence_root: Path = REPOSITORY_ROOT,
) -> Mapping[str, Any]:
    """Execute and atomically publish one complete trusted selection."""

    # This check intentionally precedes lock verification, materialization,
    # preflight, and every possible provider call.
    if confirmed is not True:
        raise EvaluationError("not_authorized", "full_run_confirmation_required")
    if (
        isinstance(timeout_per_case, bool)
        or not isinstance(timeout_per_case, (int, float))
        or not math.isfinite(float(timeout_per_case))
        or not 0 < float(timeout_per_case) <= e2e.MAX_TASK_TIMEOUT_SECONDS
    ):
        raise EvaluationError("failed", "invalid_timeout")
    target = _validated_output_path(split, output, root=evidence_root)
    cases = _selected_cases(split)
    responses: list[Mapping[str, Any]] = []
    prompt_hash: str | None = None
    config_hash: str | None = None
    for case in cases:
        try:
            run = case_runner(
                str(case["id"]),
                timeout_seconds=float(timeout_per_case),
                evidence_out=None,
                require_acceptance=False,
            )
        except e2e.E2ERunnerError as exc:
            status = "not_configured" if exc.status == "not_configured" else "failed"
            raise EvaluationError(status, exc.code) from exc
        except Exception as exc:
            raise EvaluationError("failed", "case_runner_failed") from exc
        evidence = run.evidence
        current_prompt = evidence.get("prompt_template_sha256")
        current_config = evidence.get("config_sha256")
        if not isinstance(current_prompt, str) or not isinstance(current_config, str):
            raise EvaluationError("failed", "case_capture_contract_mismatch")
        if prompt_hash is None:
            prompt_hash = current_prompt
            config_hash = current_config
        elif current_prompt != prompt_hash or current_config != config_hash:
            raise EvaluationError("failed", "evaluation_configuration_drift")
        responses.append(run.response)

    if prompt_hash is None or config_hash is None:
        raise EvaluationError("failed", "empty_evaluation")
    captured_at = _timestamp(now())
    try:
        result = evaluator.score_trusted_ouroboros_responses(
            responses,
            captured_at=captured_at,
            runtime_version=e2e.PINNED_VERSION,
            provider=e2e.PROVIDER,
            model_name=e2e.MODEL_ID,
            prompt_hash=prompt_hash,
            config_hash=config_hash,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise EvaluationError("failed", "trusted_scoring_failed") from exc
    runs = result.get("runs")
    if (
        not isinstance(runs, list)
        or len(runs) != len(cases)
        or any(not isinstance(run, Mapping) for run in runs)
        or result.get("gate", {}).get("evaluation_passed") is not True
    ):
        raise EvaluationError("failed", "evaluation_gate_failed")
    if split == "all" and result.get("gate", {}).get("release_passed") is not True:
        raise EvaluationError("failed", "release_gate_failed")
    if split != "all" and result.get("gate", {}).get("release_eligible") is not False:
        raise EvaluationError("failed", "partial_release_boundary_failed")
    try:
        e2e._assert_sanitized(result)
    except (TypeError, ValueError) as exc:
        raise EvaluationError("failed", "result_sanitization_failed") from exc
    try:
        e2e._atomic_write_json(target, result, root=evidence_root)
    except e2e.E2ERunnerError as exc:
        raise EvaluationError("failed", exc.code) from exc
    return result


def _positive_timeout(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(result) or not 0 < result <= e2e.MAX_TASK_TIMEOUT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"must be in (0, {e2e.MAX_TASK_TIMEOUT_SECONDS:g}]"
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a complete trusted paid Ouroboros evaluation selection"
    )
    parser.add_argument(
        "--split", choices=("development", "holdout", "all"), required=True
    )
    parser.add_argument(
        "--confirm-full-run",
        action="store_true",
        help="assert that the owner approved the paid post-smoke evaluation",
    )
    parser.add_argument(
        "--timeout-per-case", type=_positive_timeout, default=600.0
    )
    parser.add_argument("--output", type=Path)
    return parser


def _emit(value: Mapping[str, Any]) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not arguments.confirm_full_run:
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "status": "not_authorized",
                "code": "full_run_confirmation_required",
                "split": arguments.split,
            }
        )
        return 2
    try:
        result = run_evaluation(
            arguments.split,
            confirmed=True,
            timeout_per_case=arguments.timeout_per_case,
            output=arguments.output,
        )
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "status": "passed",
                "code": "ok",
                "split": arguments.split,
                "cases_evaluated": result["cases_evaluated"],
                "release_passed": result["gate"]["release_passed"],
            }
        )
        return 0
    except EvaluationError as exc:
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "status": exc.status,
                "code": exc.code,
                "split": arguments.split,
            }
        )
        return 2 if exc.status in {"not_authorized", "not_configured"} else 3
    except Exception:
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "status": "failed",
                "code": "internal_evaluation_error",
                "split": arguments.split,
            }
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
