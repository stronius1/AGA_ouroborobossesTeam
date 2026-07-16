# -*- coding: utf-8 -*-
"""Contract tests for the severity-aware fitness evaluator and gate.

The tests use real corpus/rules files in ``tmp_path`` and replace only the PR
review boundary.  This keeps scoring, validation, hashing and gate behavior
under test without coupling the suite to unrelated parser fixtures.
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest
import yaml


PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from evolver import fitness  # noqa: E402
from evolver.mutations import validate_mutation  # noqa: E402
from scripts.run_evolution import apply_mutation  # noqa: E402


ERROR_COSTS = {
    "missed_blocker": 10.0,
    "missed_major": 5.0,
    "missed_minor": 1.0,
    "false_blocker": 3.0,
    "false_major": 2.0,
    "false_minor": 0.5,
}


def _rule(rule_id: str, check_type: str) -> dict:
    rule = {
        "id": rule_id,
        "title": f"Rule {rule_id}",
        "statement": "Test statement",
        "severity": "major",
        "scope": ["integration_flow"],
        "check_type": check_type,
        "source_ref": "TEST-POLICY section 1",
        "exceptions": [],
        "provenance": {"origin": "seed", "added_in": "1.0.0"},
        "status": "active",
    }
    if check_type in {"deterministic", "hybrid"}:
        rule["detect"] = {"field_required": "owner"}
    return rule


def _write_rules(
    tmp_path: Path,
    *,
    costs: dict[str, float] | None = None,
    rules: list[dict] | None = None,
) -> Path:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    domain_by_file = {
        "principles.yaml": "principles",
        "seaf-checks.yaml": "seaf",
        "diagram-checks.yaml": "diagram",
        "adr-checks.yaml": "adr",
    }
    for name in fitness.RULE_FILES:
        document = {
            "schema": "aga.rules/v1",
            "domain": domain_by_file[name],
            "rules": list(rules or []) if name == "principles.yaml" else [],
        }
        (rules_dir / name).write_text(
            yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
        )
    policy = {
        "schema": "aga.severity-policy/v1",
        "severities": ["blocker", "major", "minor"],
        "aggregation": "max_severity",
        "verdict_policy": {
            "has_blocker": "request_changes_escalate",
            "has_major": "request_changes_escalate",
            "minor_only": "approve_with_warnings",
            "none": "approve",
        },
        "confidence": {"min_for_blocker": 0.70, "min_for_finding": 0.40},
        "autonomy": {
            "auto_merge": False,
            "auto_verdicts": ["approve", "approve_with_warnings"],
            "human_required_for": ["request_changes_escalate"],
        },
        "escalation": {"assignee": "architect_on_duty"},
        "error_costs": dict(costs or ERROR_COSTS),
    }
    (rules_dir / "severity-policy.yaml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    return rules_dir


def _finding(
    rule_id: str,
    severity: str,
    *,
    artifact: str | None = None,
    location: str | None = None,
    canonical_defect: str | None = None,
) -> dict:
    finding = {"rule_id": rule_id, "severity": severity}
    if artifact is not None:
        finding["artifact"] = artifact
    if location is not None:
        finding["location"] = location
    if canonical_defect is not None:
        finding["canonical_defect"] = canonical_defect
    return finding


def _case(
    case_id: str,
    *,
    findings: list[dict] | None = None,
    outcome: str = "approve",
    materialized: bool = True,
) -> dict:
    return {
        "id": case_id,
        "title": f"Case {case_id}",
        "scenario": f"Fitness test scenario for {case_id}",
        "materialized": materialized,
        "expected": {"findings": list(findings or []), "outcome": outcome},
    }


def _write_corpus(tmp_path: Path, cases: list[dict]) -> Path:
    path = tmp_path / "corpus.yaml"
    path.write_text(
        yaml.safe_dump(
            {"schema": "aga.golden-corpus/v1", "cases": cases},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _review(findings: list[dict] | None = None, *, verdict: str = "approve",
            reviewed_files: list[str] | None = None) -> dict:
    return {
        "findings": list(findings or []),
        "verdict": verdict,
        "input_errors": [],
        "analysis_errors": [],
        "reviewed_files": list(reviewed_files or ["flows/IF-0001.md"]),
    }


def _evaluate(
    monkeypatch,
    tmp_path: Path,
    cases: list[dict],
    reviews: dict[str, dict],
    *,
    minimum_cases: int = 1,
    costs: dict[str, float] | None = None,
    protected_error_costs: dict[str, float] | None = None,
    rules: list[dict] | None = None,
) -> dict:
    rules_dir = _write_rules(tmp_path, costs=costs, rules=rules)
    corpus_path = _write_corpus(tmp_path, cases)
    prs_root = tmp_path / "prs"
    prs_root.mkdir()

    def fake_review(pr_dir, *_args, **_kwargs):
        case_id = Path(pr_dir).name
        return copy.deepcopy(reviews[case_id])

    monkeypatch.setattr(fitness, "review_pr", fake_review)
    return fitness.evaluate(
        rules_dir,
        corpus_path,
        prs_root,
        minimum_cases=minimum_cases,
        protected_error_costs=protected_error_costs,
    )


def _check(checks: list[dict], check_id: str) -> dict:
    return next(item for item in checks if item["id"] == check_id)


def _metrics(
    *,
    fp: dict[str, int] | None = None,
    fn: dict[str, int] | None = None,
    precision: float = 1.0,
    recall: float = 1.0,
    blocker_recall: float = 1.0,
    outcome_accuracy: float = 1.0,
    weighted_cost: float = 0.0,
    severity_confusion: dict[str, int] | None = None,
    corpus_revision: str = "corpus-v1",
    error_costs_hash: str = "costs-v1",
    invariant_violations: list | None = None,
) -> dict:
    fp_by = {severity: 0 for severity in fitness.SEVERITIES}
    fn_by = {severity: 0 for severity in fitness.SEVERITIES}
    fp_by.update(fp or {})
    fn_by.update(fn or {})
    return {
        "schema_invariant_violations": list(invariant_violations or []),
        "corpus_revision": corpus_revision,
        "error_costs_hash": error_costs_hash,
        "blocker_recall": blocker_recall,
        "recall": recall,
        "precision": precision,
        "outcome_accuracy": outcome_accuracy,
        "weighted_cost": weighted_cost,
        "fp_by_severity": fp_by,
        "fn_by_severity": fn_by,
        "fp_total": sum(fp_by.values()),
        "fn_total": sum(fn_by.values()),
        "severity_confusion": dict(severity_confusion or {}),
        "deterministic_coverage": {"positive_cases": {}, "negative_cases": {}},
    }


def test_severity_mismatch_is_fn_fp_and_confusion(monkeypatch, tmp_path):
    expected = _finding(
        "SEAF-004", "blocker", artifact="flows/IF-0001.md", location="frontmatter"
    )
    predicted = _finding(
        "SEAF-004", "major", artifact="flows/IF-0001.md", location="frontmatter"
    )
    metrics = _evaluate(
        monkeypatch,
        tmp_path,
        [_case("pr-01", findings=[expected], outcome="request_changes_escalate")],
        {"pr-01": _review([predicted], verdict="request_changes_escalate")},
    )

    assert metrics["tp_total"] == 0
    assert metrics["fn_by_severity"] == {"blocker": 1, "major": 0, "minor": 0}
    assert metrics["fp_by_severity"] == {"blocker": 0, "major": 1, "minor": 0}
    assert metrics["severity_confusion"] == {"blocker->major": 1}
    assert metrics["per_pr"][0]["exact_findings"] is False


def test_one_prediction_is_reserved_for_only_one_confusion_pair():
    expected = [
        _finding("TEST-001", "blocker", artifact="flows/IF-0001.md"),
        _finding("TEST-001", "major", artifact="flows/IF-0001.md"),
    ]
    predicted = [_finding("TEST-001", "minor", artifact="flows/IF-0001.md")]

    true_pos, false_pos, false_neg, confusion = fitness._match_findings(
        expected, predicted
    )

    assert true_pos == []
    assert len(false_pos) == 1  # confusion bookkeeping must not consume the FP
    assert len(false_neg) == 2
    assert dict(confusion) == {"blocker->minor": 1}


def test_blocker_predicted_as_major_reduces_blocker_recall(monkeypatch, tmp_path):
    metrics = _evaluate(
        monkeypatch,
        tmp_path,
        [_case(
            "pr-01",
            findings=[_finding("SEAF-004", "blocker")],
            outcome="request_changes_escalate",
        )],
        {
            "pr-01": _review(
                [_finding("SEAF-004", "major")],
                verdict="request_changes_escalate",
            )
        },
    )
    assert metrics["blocker_recall"] == 0.0
    assert metrics["recall_by_severity"]["blocker"] == 0.0


def test_unknown_rule_firing_counts_as_false_positive(monkeypatch, tmp_path):
    metrics = _evaluate(
        monkeypatch,
        tmp_path,
        [_case("pr-01")],
        {"pr-01": _review([_finding("NEW-999", "major")], verdict="request_changes_escalate")},
    )
    assert metrics["tp_total"] == 0
    assert metrics["fp_total"] == 1
    assert metrics["fp_by_severity"]["major"] == 1
    assert metrics["per_pr"][0]["fp"] == ["NEW-999"]


def test_multiple_same_rule_findings_are_not_collapsed(monkeypatch, tmp_path):
    expected = [
        _finding("DIAG-004", "major", artifact="diagrams/a.puml"),
        _finding("DIAG-004", "major", artifact="diagrams/b.puml"),
    ]
    predicted = list(reversed(expected))
    metrics = _evaluate(
        monkeypatch,
        tmp_path,
        [_case("pr-01", findings=expected, outcome="request_changes_escalate")],
        {"pr-01": _review(predicted, verdict="request_changes_escalate")},
    )
    assert metrics["findings_expected"] == 2
    assert metrics["findings_predicted"] == 2
    assert metrics["tp_total"] == 2
    assert metrics["fp_total"] == metrics["fn_total"] == 0
    assert metrics["per_pr"][0]["tp"] == ["DIAG-004", "DIAG-004"]


def test_empty_corpus_rejected(monkeypatch, tmp_path):
    rules_dir = _write_rules(tmp_path)
    corpus = _write_corpus(tmp_path, [])
    monkeypatch.setattr(fitness, "review_pr", lambda *_args, **_kwargs: _review())
    with pytest.raises(fitness.FitnessValidationError, match="corpus has 0 cases"):
        fitness.evaluate(rules_dir, corpus, tmp_path / "prs", minimum_cases=1)


def test_too_few_materialized_cases_rejected(monkeypatch, tmp_path):
    cases = [
        _case("pr-01"),
        _case("pr-02", materialized=False),
    ]
    rules_dir = _write_rules(tmp_path)
    corpus = _write_corpus(tmp_path, cases)
    monkeypatch.setattr(fitness, "review_pr", lambda *_args, **_kwargs: _review())
    with pytest.raises(
        fitness.FitnessValidationError,
        match="corpus has 1 executable cases; minimum is 2",
    ):
        fitness.evaluate(rules_dir, corpus, tmp_path / "prs", minimum_cases=2)


def test_candidate_cannot_change_protected_error_costs(monkeypatch, tmp_path):
    protected = dict(ERROR_COSTS)
    candidate_costs = dict(ERROR_COSTS)
    candidate_costs["false_major"] = 0.01
    with pytest.raises(
        fitness.FitnessValidationError,
        match="candidate changed protected error-cost policy",
    ):
        _evaluate(
            monkeypatch,
            tmp_path,
            [_case("pr-01")],
            {"pr-01": _review()},
            costs=candidate_costs,
            protected_error_costs=protected,
        )


def test_denominators_hashes_and_llm_metrics_are_explicit(monkeypatch, tmp_path):
    cases = [
        _case("pr-01"),
        _case("pr-02"),
        _case("pr-03", materialized=False),
    ]
    reviews = {"pr-01": _review(), "pr-02": _review()}
    loaded_rules = [_rule("TEST-001", "deterministic"), _rule("TEST-002", "llm")]
    metrics = _evaluate(
        monkeypatch,
        tmp_path,
        cases,
        reviews,
        minimum_cases=2,
        rules=loaded_rules,
    )

    assert metrics["cases_evaluated"] == 2
    assert metrics["materialized_case_ids"] == ["pr-01", "pr-02"]
    assert metrics["cases_skipped_not_materialized"] == ["pr-03"]
    assert metrics["findings_expected"] == metrics["findings_predicted"] == 0
    assert re.fullmatch(r"[0-9a-f]{64}", metrics["corpus_revision"])
    assert re.fullmatch(r"[0-9a-f]{64}", metrics["rules_revision"])
    assert re.fullmatch(r"[0-9a-f]{64}", metrics["error_costs_hash"])
    assert metrics["deterministic_coverage"]["cases_evaluated"] == 2
    assert metrics["deterministic_coverage"]["rules_evaluated"] == 1
    assert metrics["llm_coverage"] == {
        "cases_evaluated": 0,
        "findings_evaluated": 0,
        "status": "not_measured_offline",
    }


def test_negative_coverage_requires_a_scope_relevant_case(monkeypatch, tmp_path):
    rule = _rule("PRIN-099", "deterministic")
    expected = _finding("PRIN-099", "major")
    cases = [
        _case("pr-91", findings=[expected], outcome="request_changes_escalate"),
        _case("pr-92"),
        _case("pr-93"),
    ]
    reviews = {
        "pr-91": _review(
            [expected], verdict="request_changes_escalate",
            reviewed_files=["flows/IF-0001.md"]),
        "pr-92": _review(reviewed_files=["adrs/ADR-0001.md"]),
        "pr-93": _review(reviewed_files=["flows/IF-0002.md"]),
    }
    metrics = _evaluate(
        monkeypatch, tmp_path, cases, reviews, minimum_cases=1, rules=[rule])
    coverage = metrics["deterministic_coverage"]
    assert coverage["positive_cases"]["PRIN-099"] == ["pr-91"]
    assert coverage["negative_cases"]["PRIN-099"] == ["pr-93"]


def _deprecation_metrics() -> tuple[dict, dict, dict]:
    rule_id = "PRIN-099"
    base = _metrics(
        fp={"major": 1},
        precision=0.5,
        outcome_accuracy=0.5,
        weighted_cost=2.0,
    )
    candidate = _metrics()
    case_ids = ["pr-positive", "pr-negative"]
    base["materialized_case_ids"] = list(case_ids)
    candidate["materialized_case_ids"] = list(case_ids)
    target = _finding(rule_id, "major", artifact="flows/IF-0099.md")
    base["per_pr"] = [
        {
            "pr": "pr-positive",
            "tp_findings": [],
            "fp_findings": [target],
            "fn_findings": [],
            "predicted_outcome": "request_changes_escalate",
            "expected_outcome": "approve",
        },
        {
            "pr": "pr-negative",
            "tp_findings": [],
            "fp_findings": [],
            "fn_findings": [],
            "predicted_outcome": "approve",
            "expected_outcome": "approve",
        },
    ]
    candidate["per_pr"] = [
        {
            "pr": case_id,
            "tp_findings": [],
            "fp_findings": [],
            "fn_findings": [],
            "predicted_outcome": "approve",
            "expected_outcome": "approve",
        }
        for case_id in case_ids
    ]
    base["deterministic_coverage"] = {
        "positive_cases": {rule_id: []},
        "negative_cases": {rule_id: ["pr-negative"]},
    }
    candidate["deterministic_coverage"] = {
        "positive_cases": {},
        "negative_cases": {},
    }
    mutation = {
        "type": "deprecate_rule",
        "rule_id": rule_id,
        "coverage": {
            "positive_cases": ["pr-positive"],
            "negative_cases": ["pr-negative"],
        },
    }
    return base, candidate, mutation


def test_deprecate_gate_uses_exact_trusted_false_positive_coverage():
    base, candidate, mutation = _deprecation_metrics()

    passed, checks = fitness.gate(
        base,
        candidate,
        changed_rule_ids={"PRIN-099"},
        mutation=mutation,
    )

    assert passed is True
    assert _check(checks, "deprecation_no_expected_findings")["passed"] is True
    assert _check(checks, "deprecation_target_disabled")["passed"] is True
    assert _check(checks, "deprecation_non_target_stability")["passed"] is True
    assert _check(checks, "deprecation_declared_coverage")["passed"] is True
    assert _check(checks, "changed_rule_coverage")["passed"] is True


def test_deprecate_gate_rejects_mutation_claims_not_equal_to_trusted_coverage():
    base, candidate, mutation = _deprecation_metrics()
    mutation["coverage"]["positive_cases"] = ["pr-negative"]

    passed, checks = fitness.gate(
        base,
        candidate,
        changed_rule_ids={"PRIN-099"},
        mutation=mutation,
    )

    assert passed is False
    assert _check(checks, "deprecation_declared_coverage")["passed"] is False
    assert _check(checks, "changed_rule_coverage")["passed"] is False


def test_deprecate_gate_does_not_waive_locked_expected_findings_or_fn_growth():
    base, candidate, mutation = _deprecation_metrics()
    target = _finding("PRIN-099", "major", artifact="flows/IF-0099.md")
    base["per_pr"][0]["fp_findings"] = []
    base["per_pr"][0]["tp_findings"] = [target]
    base["deterministic_coverage"]["positive_cases"]["PRIN-099"] = ["pr-positive"]
    candidate["per_pr"][0]["fn_findings"] = [target]
    candidate["fn_by_severity"]["major"] = 1
    candidate["fn_total"] = 1
    candidate["recall"] = 0.0
    candidate["weighted_cost"] = 5.0

    passed, checks = fitness.gate(
        base,
        candidate,
        changed_rule_ids={"PRIN-099"},
        mutation=mutation,
    )

    assert passed is False
    assert _check(checks, "fn_major")["passed"] is False
    assert _check(checks, "deprecation_no_expected_findings")["passed"] is False
    assert _check(checks, "changed_rule_coverage")["passed"] is False


def _evaluate_applied_deprecation(
    monkeypatch, tmp_path: Path, *, target_is_expected: bool
) -> tuple[bool, list[dict]]:
    rule_id = "PRIN-099"
    rule = _rule(rule_id, "deterministic")
    base_rules = _write_rules(tmp_path, rules=[rule])
    mutation = validate_mutation(
        {
            "type": "deprecate_rule",
            "rule_id": rule_id,
            "provenance": "precedent:test-deprecation",
            "reason": "Locked corpus proves the detector is obsolete",
            "evidence": "policy:synthetic-v2",
            "coverage": {
                "positive_cases": ["pr-91"],
                "negative_cases": ["pr-92"],
            },
        },
        [rule],
        approved_provenance={"precedent:test-deprecation"},
    )
    candidate_rules = tmp_path / "candidate-rules"
    apply_mutation(base_rules, candidate_rules, mutation, "1.1.0")

    corpus = _write_corpus(
        tmp_path,
        [
            _case(
                "pr-91",
                findings=[_finding(rule_id, "major")]
                if target_is_expected
                else [],
                outcome="request_changes_escalate"
                if target_is_expected
                else "approve",
            ),
            _case("pr-92"),
        ],
    )
    prs_root = tmp_path / "prs"
    prs_root.mkdir()

    def fake_review(pr_dir, rules_dir, *_args, **_kwargs):
        loaded, _ = fitness.load_rules(rules_dir)
        fires = Path(pr_dir).name == "pr-91" and any(
            item["id"] == rule_id for item in loaded
        )
        return _review(
            [_finding(rule_id, "major")] if fires else [],
            verdict="request_changes_escalate" if fires else "approve",
        )

    monkeypatch.setattr(fitness, "review_pr", fake_review)
    base = fitness.evaluate(
        base_rules, corpus, prs_root, minimum_cases=2
    )
    candidate = fitness.evaluate(
        candidate_rules,
        corpus,
        prs_root,
        minimum_cases=2,
        protected_error_costs=base["error_costs"],
    )
    return fitness.gate(
        base,
        candidate,
        changed_rule_ids={rule_id},
        mutation=mutation,
    )


def test_applied_deprecation_passes_for_trusted_fp_and_relevant_negative(
    monkeypatch, tmp_path
):
    passed, checks = _evaluate_applied_deprecation(
        monkeypatch, tmp_path, target_is_expected=False
    )

    assert passed is True
    assert _check(checks, "strict_improvement")["passed"] is True
    assert _check(checks, "changed_rule_coverage")["passed"] is True


def test_applied_deprecation_of_true_positive_rule_fails_closed(
    monkeypatch, tmp_path
):
    passed, checks = _evaluate_applied_deprecation(
        monkeypatch, tmp_path, target_is_expected=True
    )

    assert passed is False
    assert _check(checks, "recall")["passed"] is False
    assert _check(checks, "fn_major")["passed"] is False
    assert _check(checks, "deprecation_no_expected_findings")["passed"] is False


def test_severity_downgrade_does_not_pass_gate():
    base = _metrics()
    candidate = _metrics(
        fp={"major": 1},
        fn={"blocker": 1},
        precision=0.0,
        recall=0.0,
        blocker_recall=0.0,
        weighted_cost=15.0,
        severity_confusion={"blocker->major": 1},
    )
    passed, checks = fitness.gate(base, candidate)
    assert passed is False
    assert _check(checks, "no_blocker_downgrade")["passed"] is False
    assert _check(checks, "blocker_recall")["passed"] is False


def test_recall_drop_does_not_pass_gate():
    passed, checks = fitness.gate(_metrics(), _metrics(recall=0.9))
    assert passed is False
    assert _check(checks, "recall")["passed"] is False


def test_precision_drop_does_not_pass_gate():
    passed, checks = fitness.gate(_metrics(), _metrics(precision=0.9))
    assert passed is False
    assert _check(checks, "precision")["passed"] is False


def test_false_blocker_increase_never_passes_despite_other_improvement():
    base = _metrics(
        fn={"major": 1}, recall=0.5, outcome_accuracy=0.5, weighted_cost=10.0
    )
    candidate = _metrics(
        fp={"blocker": 1}, precision=0.8, recall=1.0,
        outcome_accuracy=1.0, weighted_cost=9.0,
    )
    passed, checks = fitness.gate(base, candidate)
    assert _check(checks, "strict_improvement")["passed"] is True
    assert _check(checks, "weighted_cost")["passed"] is True
    assert _check(checks, "false_blocker")["passed"] is False
    assert passed is False


@pytest.mark.parametrize("family", ["fp", "fn"])
@pytest.mark.parametrize("severity", fitness.SEVERITIES)
def test_per_severity_error_growth_does_not_pass_gate(family, severity):
    kwargs = {family: {severity: 1}}
    if family == "fp":
        kwargs["precision"] = 0.5
    else:
        kwargs["recall"] = 0.5
        if severity == "blocker":
            kwargs["blocker_recall"] = 0.0
    passed, checks = fitness.gate(_metrics(), _metrics(**kwargs))
    assert passed is False
    assert _check(checks, f"{family}_{severity}")["passed"] is False


def test_false_major_to_false_minor_is_not_improvement():
    base = _metrics(fp={"major": 1}, precision=0.5, weighted_cost=2.0)
    candidate = _metrics(fp={"minor": 1}, precision=0.5, weighted_cost=0.5)
    passed, checks = fitness.gate(base, candidate)
    assert _check(checks, "weighted_cost")["passed"] is True
    assert _check(checks, "fp_minor")["passed"] is False
    assert _check(checks, "strict_improvement")["passed"] is False
    assert passed is False


def test_gate_rejects_changed_error_cost_hash_even_with_improvement():
    base = _metrics(fp={"minor": 1}, precision=0.5, weighted_cost=0.5)
    candidate = _metrics(error_costs_hash="candidate-costs-v2")
    passed, checks = fitness.gate(base, candidate)
    assert _check(checks, "strict_improvement")["passed"] is True
    assert _check(checks, "same_error_costs")["passed"] is False
    assert passed is False
