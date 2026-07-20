#!/usr/bin/env python3
"""Cross-check submission claims against retained evidence and formulas."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any, Mapping
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FACTS_PATH = ROOT / "docs" / "SUBMISSION-FACTS.json"
CANONICAL_DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "PROJECT-RESULTS.md",
    ROOT / "docs" / "PROPOSAL-TRACEABILITY.md",
    ROOT / "docs" / "BUSINESS-EFFECT.md",
    ROOT / "docs" / "PRESENTATION-OUTLINE.md",
    ROOT / "docs" / "PRESENTATION.md",
    ROOT / "docs" / "DEMO-VIDEO-SCRIPT.md",
    ROOT / "docs" / "SUBMISSION-CHECKLIST.md",
)


def _read_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"unreadable JSON: {path.relative_to(ROOT)} ({type(exc).__name__})")
        return None


def _mapping(value: Any, label: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        errors.append(f"{label} must be an object")
        return {}
    return value


def _equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-6)
    return actual == expected


def _expect(
    actual: Any,
    expected: Any,
    label: str,
    errors: list[str],
) -> None:
    if not _equal(actual, expected):
        errors.append(f"{label}: facts={actual!r}, evidence/calculation={expected!r}")


def _passed_cases(metrics: Mapping[str, Any]) -> int:
    runs = metrics.get("per_pr")
    if not isinstance(runs, list):
        return -1
    return sum(
        isinstance(run, Mapping)
        and run.get("exact_findings") is True
        and run.get("outcome_ok") is True
        for run in runs
    )


def _check_deterministic(facts: Mapping[str, Any], errors: list[str]) -> None:
    section = _mapping(facts.get("deterministic_rule_fitness"), "deterministic_rule_fitness", errors)
    snapshot = ROOT / "docs/evidence/snapshots/deterministic-2026-07-15-v2"
    for scope, filename in (
        ("baseline", "metrics-baseline.json"),
        ("candidate", "metrics-candidate.json"),
    ):
        claimed = _mapping(section.get(scope), f"deterministic_rule_fitness.{scope}", errors)
        measured = _mapping(_read_json(snapshot / filename, errors), filename, errors)
        expected = {
            "cases_evaluated": measured.get("cases_evaluated"),
            "cases_passed": _passed_cases(measured),
            "precision": measured.get("precision"),
            "recall": measured.get("recall"),
            "blocker_recall": measured.get("blocker_recall"),
            "exact_case_accuracy": measured.get("exact_case_accuracy"),
            "weighted_cost": measured.get("weighted_cost"),
        }
        for key, value in expected.items():
            _expect(claimed.get(key), value, f"deterministic_rule_fitness.{scope}.{key}", errors)

    local_demo = _mapping(facts.get("local_demo"), "local_demo", errors)
    _expect(
        local_demo.get("baseline_cases_passed"),
        _passed_cases(_mapping(_read_json(snapshot / "metrics-baseline.json", errors), "baseline metrics", errors)),
        "local_demo.baseline_cases_passed",
        errors,
    )
    _expect(
        local_demo.get("candidate_cases_passed"),
        _passed_cases(_mapping(_read_json(snapshot / "metrics-candidate.json", errors), "candidate metrics", errors)),
        "local_demo.candidate_cases_passed",
        errors,
    )


def _check_generated_scenario(facts: Mapping[str, Any], errors: list[str]) -> None:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/generate_self_evolution_scenario.py",
                "--seed",
                "submission-facts",
                "--preset",
                "full",
                "--parallel-workers",
                "4",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"scenario generation failed: {type(exc).__name__}")
        return
    if completed.returncode:
        errors.append("scenario generation failed for the canonical full preset")
        return
    try:
        scenario = json.loads(completed.stdout)
    except json.JSONDecodeError:
        errors.append("scenario generator did not return JSON")
        return
    summary = _mapping(_mapping(scenario, "generated scenario", errors).get("summary"), "scenario.summary", errors)
    local_demo = _mapping(facts.get("local_demo"), "local_demo", errors)
    for fact_key, summary_key in (
        ("scenario_nodes", "systems"),
        ("scenario_flows", "flows"),
        ("golden_cases", "tests"),
    ):
        _expect(local_demo.get(fact_key), summary.get(summary_key), f"local_demo.{fact_key}", errors)


def _check_live_e2e(facts: Mapping[str, Any], errors: list[str]) -> None:
    claimed = _mapping(facts.get("controlled_live_self_evolution"), "controlled_live_self_evolution", errors)
    evidence = _mapping(
        _read_json(ROOT / "docs/evidence/ouroboros-self-evolution-v1.json", errors),
        "controlled live evidence",
        errors,
    )
    stages = [
        _mapping(evidence.get("review_before"), "review_before", errors),
        _mapping(evidence.get("remediation"), "remediation", errors),
        _mapping(evidence.get("review_after"), "review_after", errors),
    ]
    costs = [
        _mapping(stage.get("model_usage"), "model_usage", errors).get("known_cost_usd")
        for stage in stages
    ]
    if all(isinstance(cost, (int, float)) and not isinstance(cost, bool) for cost in costs):
        total_cost = round(sum(float(cost) for cost in costs), 6)
    else:
        total_cost = None
    gate = _mapping(evidence.get("gate"), "controlled live gate", errors)
    expected = {
        "status": evidence.get("status"),
        "task_count": len(stages),
        "known_cost_usd": total_cost,
        "gate_passed": gate.get("passed"),
        "human_review_required": gate.get("human_review_required"),
        "auto_merge": gate.get("auto_merge"),
    }
    for key, value in expected.items():
        _expect(claimed.get(key), value, f"controlled_live_self_evolution.{key}", errors)


def _check_semantic(facts: Mapping[str, Any], errors: list[str]) -> None:
    claimed = _mapping(facts.get("semantic_evaluation"), "semantic_evaluation", errors)
    canonical = _mapping(
        _read_json(ROOT / "evaluation/gigaagent/results.json", errors),
        "canonical semantic results",
        errors,
    )
    _expect(claimed.get("canonical_results_status"), canonical.get("status"), "semantic_evaluation.canonical_results_status", errors)
    _expect(
        claimed.get("canonical_trusted_cases_evaluated"),
        canonical.get("cases_evaluated"),
        "semantic_evaluation.canonical_trusted_cases_evaluated",
        errors,
    )

    fixture_claim = _mapping(claimed.get("fixture"), "semantic_evaluation.fixture", errors)
    fixture = _mapping(
        _read_json(ROOT / "evaluation/gigaagent/fixture-results.json", errors),
        "semantic fixture results",
        errors,
    )
    for key, value in (
        ("cases_evaluated", fixture.get("cases_evaluated")),
        ("cases_passed", _mapping(fixture.get("overall"), "fixture.overall", errors).get("cases_passed")),
        ("release_evidence", fixture.get("release_evidence")),
    ):
        _expect(fixture_claim.get(key), value, f"semantic_evaluation.fixture.{key}", errors)

    frozen_claim = _mapping(claimed.get("historical_frozen_run"), "semantic_evaluation.historical_frozen_run", errors)
    frozen = _mapping(
        _read_json(ROOT / "docs/evidence/ouroboros/frozen-run-failure-sanitized.json", errors),
        "historical frozen evidence",
        errors,
    )
    overall = _mapping(_mapping(frozen.get("metrics"), "frozen.metrics", errors).get("overall"), "frozen.metrics.overall", errors)
    expected = {
        "cases_evaluated": overall.get("cases_evaluated"),
        "cases_passed": overall.get("cases_passed"),
        "precision": overall.get("precision"),
        "recall": overall.get("recall"),
        "blocker_recall": overall.get("blocker_recall"),
        "outcome_accuracy": overall.get("outcome_accuracy"),
        "schema_valid_rate": overall.get("schema_valid_rate"),
        "unsafe_approve_count": overall.get("unsafe_approve_count"),
        "known_cost_usd": _mapping(frozen.get("usage"), "frozen.usage", errors).get("known_cost_usd"),
        "release_gate": "FAIL" if overall.get("gate_passed") is False else "PASS",
    }
    for key, value in expected.items():
        _expect(frozen_claim.get(key), value, f"semantic_evaluation.historical_frozen_run.{key}", errors)


def _check_development_v2(facts: Mapping[str, Any], errors: list[str]) -> None:
    claimed = _mapping(
        facts.get("semantic_development_v2"),
        "semantic_development_v2",
        errors,
    )
    lock_relative = "evaluation/development-v2/corpus.lock.json"
    _expect(claimed.get("lock"), lock_relative, "semantic_development_v2.lock", errors)
    lock = _mapping(
        _read_json(ROOT / lock_relative, errors),
        "development-v2 lock",
        errors,
    )
    review = _mapping(
        lock.get("independent_human_review"),
        "development-v2 independent_human_review",
        errors,
    )
    freeze = _mapping(
        lock.get("series_freeze"),
        "development-v2 series_freeze",
        errors,
    )
    measurement_ready = review.get("status") == "accepted" and freeze.get("state") == "frozen"
    expected = {
        "case_count": lock.get("case_count"),
        "independent_human_review_status": review.get("status"),
        "series_state": freeze.get("state"),
        "required_repeated_runs": freeze.get("required_repeated_runs"),
        "trusted_measurement_status": "ready" if measurement_ready else "blocked",
        "release_evidence": False,
    }
    for key, value in expected.items():
        _expect(claimed.get(key), value, f"semantic_development_v2.{key}", errors)


def _check_business_case(facts: Mapping[str, Any], errors: list[str]) -> None:
    section = _mapping(facts.get("business_case"), "business_case", errors)
    assumptions = _mapping(section.get("assumptions"), "business_case.assumptions", errors)
    derived = _mapping(section.get("derived"), "business_case.derived", errors)
    try:
        prs = float(assumptions["prs_per_week"])
        manual_minutes = float(assumptions["manual_minutes_per_pr"])
        quick_share = float(assumptions["quick_share"])
        quick_minutes = float(assumptions["quick_minutes_per_pr"])
        escalated_minutes = float(assumptions["escalated_minutes_per_pr"])
        architects = float(assumptions["architects"])
        weeks = float(assumptions["working_weeks_per_year"])
        hour_rub = float(assumptions["loaded_architect_hour_rub"])
        call_usd = float(assumptions["model_cost_usd_per_pr"])
        rub_per_usd = float(assumptions["rub_per_usd"])
    except (KeyError, TypeError, ValueError):
        errors.append("business_case assumptions are incomplete or non-numeric")
        return
    manual_hours = prs * manual_minutes / 60
    agent_hours = prs * (quick_share * quick_minutes + (1 - quick_share) * escalated_minutes) / 60
    saved = manual_hours - agent_hours
    annual_gross = saved * weeks * hour_rub
    annual_model = prs * weeks * call_usd * rub_per_usd
    expected = {
        "manual_hours_per_week": manual_hours,
        "agent_hours_per_week": agent_hours,
        "saved_hours_per_week_team": saved,
        "saved_hours_per_week_per_architect": saved / architects,
        "annual_gross_effect_rub": annual_gross,
        "annual_model_cost_rub": annual_model,
        "annual_effect_after_model_calls_rub": annual_gross - annual_model,
        "gross_value_to_model_cost": annual_gross / annual_model,
    }
    for key, value in expected.items():
        _expect(derived.get(key), value, f"business_case.derived.{key}", errors)


def _check_local_submission_artifacts(
    facts: Mapping[str, Any], errors: list[str]
) -> None:
    section = _mapping(
        facts.get("local_submission_artifacts"),
        "local_submission_artifacts",
        errors,
    )
    for artifact_name in ("project_results_pdf", "presentation_pptx"):
        artifact = _mapping(
            section.get(artifact_name),
            f"local_submission_artifacts.{artifact_name}",
            errors,
        )
        relative = artifact.get("path")
        if not isinstance(relative, str):
            errors.append(f"local_submission_artifacts.{artifact_name}.path must be text")
            continue
        portable = PurePosixPath(relative)
        if portable.is_absolute() or ".." in portable.parts or portable.as_posix() != relative:
            errors.append(f"local_submission_artifacts.{artifact_name}.path is unsafe")
            continue
        path = ROOT / portable
        try:
            raw = path.read_bytes()
        except OSError:
            errors.append(f"local submission artifact is missing: {relative}")
            continue
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        _expect(
            artifact.get("sha256"),
            actual_sha256,
            f"local_submission_artifacts.{artifact_name}.sha256",
            errors,
        )
        sources = artifact.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append(
                f"local_submission_artifacts.{artifact_name}.sources must be a non-empty array"
            )
        else:
            seen_sources: set[str] = set()
            for index, raw_source in enumerate(sources):
                source_label = (
                    f"local_submission_artifacts.{artifact_name}.sources[{index}]"
                )
                if not isinstance(raw_source, Mapping) or set(raw_source) != {
                    "path",
                    "sha256",
                }:
                    errors.append(f"{source_label} must contain exactly path and sha256")
                    continue
                source_relative = raw_source.get("path")
                if not isinstance(source_relative, str):
                    errors.append(f"{source_label}.path must be text")
                    continue
                source_portable = PurePosixPath(source_relative)
                if (
                    source_portable.is_absolute()
                    or ".." in source_portable.parts
                    or source_portable.as_posix() != source_relative
                    or source_relative == relative
                    or source_relative in seen_sources
                ):
                    errors.append(f"{source_label}.path is unsafe or duplicated")
                    continue
                seen_sources.add(source_relative)
                try:
                    source_raw = (ROOT / source_portable).read_bytes()
                except OSError:
                    errors.append(f"local submission source is missing: {source_relative}")
                    continue
                _expect(
                    raw_source.get("sha256"),
                    hashlib.sha256(source_raw).hexdigest(),
                    f"{source_label}.sha256",
                    errors,
                )
        if artifact_name == "presentation_pptx":
            try:
                with zipfile.ZipFile(path) as archive:
                    slide_count = sum(
                        1
                        for name in archive.namelist()
                        if name.startswith("ppt/slides/slide")
                        and name.removeprefix("ppt/slides/slide").removesuffix(".xml").isdigit()
                    )
            except (OSError, zipfile.BadZipFile):
                errors.append("local presentation is not a valid PPTX archive")
            else:
                _expect(
                    artifact.get("slides"),
                    slide_count,
                    "local_submission_artifacts.presentation_pptx.slides",
                    errors,
                )


def _check_docs(facts: Mapping[str, Any], errors: list[str]) -> None:
    for path in CANONICAL_DOCS:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append(f"canonical submission document is missing: {path.relative_to(ROOT)}")
            continue
        if "SUBMISSION-FACTS.json" not in text:
            errors.append(f"canonical facts link is missing: {path.relative_to(ROOT)}")

    publication = _mapping(facts.get("publication"), "publication", errors)
    for field in ("public_repository_url", "demo_video_url", "project_results_pdf_url"):
        value = publication.get(field)
        if value is not None and (
            not isinstance(value, str) or not value.startswith("https://")
        ):
            errors.append(f"publication.{field} must be null or an https URL")


def main() -> int:
    errors: list[str] = []
    facts = _mapping(_read_json(FACTS_PATH, errors), "submission facts", errors)
    if facts.get("schema") != "aga.submission-facts/v1":
        errors.append("submission facts schema is invalid")
    _check_deterministic(facts, errors)
    _check_generated_scenario(facts, errors)
    _check_live_e2e(facts, errors)
    _check_semantic(facts, errors)
    _check_development_v2(facts, errors)
    _check_business_case(facts, errors)
    _check_local_submission_artifacts(facts, errors)
    _check_docs(facts, errors)
    if errors:
        for error in errors:
            print(f"SUBMISSION CONSISTENCY ERROR: {error}", file=sys.stderr)
        return 1
    print("SUBMISSION FACTS AND MATERIALS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
