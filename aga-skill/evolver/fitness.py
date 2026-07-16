# -*- coding: utf-8 -*-
"""Severity- and artifact-aware fitness evaluation for AGA evolution."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from tools.aga import (  # noqa: E402
    RULE_FILES,
    ChangedFilesProvider,
    classify,
    load_rules,
    review_pr,
)
from tools.validation import ValidationError, strict_load_yaml, validate_corpus  # noqa: E402

SEVERITIES = ("blocker", "major", "minor")


class FitnessValidationError(ValueError):
    """The examination itself is invalid and must not yield perfect metrics."""


def _hash_bytes(chunks: Sequence[bytes]) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(len(chunk).to_bytes(8, "big"))
        digest.update(chunk)
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    return _hash_bytes([path.read_bytes()])


def _rules_hash(rules_dir: Path) -> str:
    names = [*RULE_FILES, "severity-policy.yaml"]
    chunks = [name.encode("utf-8") + b"\0" + (rules_dir / name).read_bytes() for name in names]
    return _hash_bytes(chunks)


def _normalise_expected(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": raw["rule_id"],
        "severity": raw["severity"],
        "artifact": raw.get("artifact"),
        "location": raw.get("location"),
        "canonical_defect": raw.get("canonical_defect"),
    }


def _normalise_predicted(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": raw.get("rule_id"),
        "severity": raw.get("severity"),
        "artifact": raw.get("artifact"),
        "location": raw.get("location") or "",
        "canonical_defect": raw.get("canonical_defect") or raw.get("evidence") or "",
    }


def _matches(expected: Mapping[str, Any], predicted: Mapping[str, Any], *,
             include_severity: bool = True) -> bool:
    if expected["rule_id"] != predicted["rule_id"]:
        return False
    if include_severity and expected["severity"] != predicted["severity"]:
        return False
    for field in ("artifact", "location", "canonical_defect"):
        if expected.get(field) not in (None, "") and expected[field] != predicted.get(field):
            return False
    return True


def _match_findings(expected: list[dict[str, Any]], predicted: list[dict[str, Any]]) -> tuple[
        list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]],
        list[dict[str, Any]], Counter[str]]:
    remaining = list(range(len(predicted)))
    true_positives: list[tuple[dict[str, Any], dict[str, Any]]] = []
    false_negatives: list[dict[str, Any]] = []
    confusion: Counter[str] = Counter()
    unmatched_expected: list[dict[str, Any]] = []
    for item in expected:
        index = next((candidate for candidate in remaining
                      if _matches(item, predicted[candidate])), None)
        if index is None:
            unmatched_expected.append(item)
        else:
            remaining.remove(index)
            true_positives.append((item, predicted[index]))

    # Record severity mismatch without converting it into a TP. It remains one
    # FN at expected severity and one FP at predicted severity.
    confusion_used: set[int] = set()
    for item in unmatched_expected:
        index = next((candidate for candidate in remaining
                      if candidate not in confusion_used
                      and _matches(item, predicted[candidate], include_severity=False)), None)
        if index is not None:
            confusion[f"{item['severity']}->{predicted[index]['severity']}"] += 1
            confusion_used.add(index)
        false_negatives.append(item)
    false_positives = [predicted[index] for index in remaining]
    return true_positives, false_positives, false_negatives, confusion


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def evaluate(rules_dir: str | Path | None = None, corpus_path: str | Path | None = None,
             prs_root: str | Path | None = None, seaf_path: str | Path | None = None, *,
             minimum_cases: int = 15, include_candidates: bool = False,
             protected_error_costs: Mapping[str, float] | None = None,
             changed_files_provider: ChangedFilesProvider | None = None) -> dict[str, Any]:
    """Evaluate one immutable corpus snapshot against one rules snapshot."""
    rules_path = Path(rules_dir or PKG_ROOT / "rules")
    corpus_file = Path(corpus_path or PKG_ROOT / "golden" / "corpus.yaml")
    prs_path = Path(prs_root or PKG_ROOT / "golden" / "prs")
    if minimum_cases < 1:
        raise FitnessValidationError("minimum_cases must be at least one")
    try:
        corpus = strict_load_yaml(corpus_file, expected_type=dict)
        validate_corpus(corpus, path=corpus_file)
        loaded_rules, policy = load_rules(
            rules_path, include_candidates=include_candidates)
    except ValidationError as exc:
        raise FitnessValidationError(str(exc)) from exc
    cases = corpus.get("cases", [])
    materialized = [case for case in cases if case.get("materialized") is True]
    skipped = [case["id"] for case in cases if case.get("materialized") is not True]
    if len(materialized) < minimum_cases:
        raise FitnessValidationError(
            f"corpus has {len(materialized)} executable cases; minimum is {minimum_cases}")
    costs = dict(policy["error_costs"])
    if protected_error_costs is not None and costs != dict(protected_error_costs):
        raise FitnessValidationError("candidate changed protected error-cost policy")

    tp_by = Counter({severity: 0 for severity in SEVERITIES})
    fp_by = Counter({severity: 0 for severity in SEVERITIES})
    fn_by = Counter({severity: 0 for severity in SEVERITIES})
    severity_confusion: Counter[str] = Counter()
    outcome_hits = 0
    exact_hits = 0
    findings_expected = 0
    findings_predicted = 0
    per_pr: list[dict[str, Any]] = []
    positive_cases: dict[str, set[str]] = {}
    negative_cases: dict[str, set[str]] = {}
    relevant_cases: dict[str, set[str]] = {}
    deterministic_rules = [
        rule for rule in loaded_rules
        if rule["check_type"] in {"deterministic", "hybrid"}
    ]
    deterministic_rule_ids = {rule["id"] for rule in deterministic_rules}

    for case in materialized:
        case_id = case["id"]
        result = review_pr(prs_path / case_id, rules_path, seaf_path,
                           include_candidates=include_candidates,
                           changed_files_provider=changed_files_provider)
        if result.get("input_errors") or result.get("verdict") in {"input_error", "incomplete"}:
            raise FitnessValidationError(
                f"case {case_id} failed closed during evaluation: "
                f"{result.get('input_errors') or result.get('analysis_errors')}")
        predicted = [_normalise_predicted(item) for item in result["findings"]]
        expected = [_normalise_expected(item) for item in case["expected"].get("findings", [])]
        true_pos, false_pos, false_neg, confusion = _match_findings(expected, predicted)
        for wanted in expected:
            if wanted["rule_id"] in deterministic_rule_ids:
                positive_cases.setdefault(wanted["rule_id"], set()).add(case_id)
        reviewed_kinds = {
            classify(path, {}, strict=False)
            for path in result.get("reviewed_files", [])
            if isinstance(path, str)
        }
        for rule in deterministic_rules:
            if reviewed_kinds.intersection(rule["scope"]):
                relevant_cases.setdefault(rule["id"], set()).add(case_id)
        severity_confusion.update(confusion)
        findings_expected += len(expected)
        findings_predicted += len(predicted)
        for wanted, _ in true_pos:
            tp_by[wanted["severity"]] += 1
        for item in false_pos:
            severity = item["severity"]
            if severity not in SEVERITIES:
                raise FitnessValidationError(f"case {case_id}: predicted invalid severity {severity!r}")
            fp_by[severity] += 1
        for item in false_neg:
            fn_by[item["severity"]] += 1
        expected_ids = {item["rule_id"] for item in expected}
        predicted_ids = {item["rule_id"] for item in predicted}
        for rule_id in expected_ids | predicted_ids:
            if rule_id not in expected_ids and rule_id not in predicted_ids:
                negative_cases.setdefault(rule_id, set()).add(case_id)
        outcome_ok = result["verdict"] == case["expected"]["outcome"]
        exact = not false_pos and not false_neg
        outcome_hits += int(outcome_ok)
        exact_hits += int(exact and outcome_ok)
        per_pr.append({
            "pr": case_id,
            "tp": [item[0]["rule_id"] for item in true_pos],
            "fp": [item["rule_id"] for item in false_pos],
            "fn": [item["rule_id"] for item in false_neg],
            "tp_findings": [item[0] for item in true_pos],
            "fp_findings": false_pos, "fn_findings": false_neg,
            "severity_confusion": dict(confusion),
            "predicted_outcome": result["verdict"],
            "expected_outcome": case["expected"]["outcome"],
            "outcome_ok": outcome_ok, "exact_findings": exact,
        })

    # A negative control must exercise the rule's scope. An unrelated ADR is
    # not evidence that an integration-flow detector avoids false positives.
    for rule in deterministic_rules:
        rule_id = rule["id"]
        positive_cases.setdefault(rule_id, set())
        fired_or_expected = {row["pr"] for row in per_pr
                             if rule_id in set(row["tp"] + row["fp"] + row["fn"])}
        negative_cases[rule_id] = relevant_cases.get(rule_id, set()) - fired_or_expected

    tp_total = sum(tp_by.values())
    fp_total = sum(fp_by.values())
    fn_total = sum(fn_by.values())
    weighted_cost = (
        costs["missed_blocker"] * fn_by["blocker"]
        + costs["missed_major"] * fn_by["major"]
        + costs["missed_minor"] * fn_by["minor"]
        + costs["false_blocker"] * fp_by["blocker"]
        + costs["false_major"] * fp_by["major"]
        + costs["false_minor"] * fp_by["minor"]
    )
    expected_blockers = tp_by["blocker"] + fn_by["blocker"]
    corpus_revision = _file_hash(corpus_file)
    rules_revision = _rules_hash(rules_path)
    return {
        "schema": "aga.fitness/v2",
        "cases_evaluated": len(materialized),
        "cases_skipped_not_materialized": skipped,
        "materialized_case_ids": [case["id"] for case in materialized],
        "findings_expected": findings_expected,
        "findings_predicted": findings_predicted,
        "tp": tp_total, "tp_total": tp_total,
        "fp": {severity: fp_by[severity] for severity in SEVERITIES},
        "fn": {severity: fn_by[severity] for severity in SEVERITIES},
        "tp_by_severity": {severity: tp_by[severity] for severity in SEVERITIES},
        "fp_by_severity": {severity: fp_by[severity] for severity in SEVERITIES},
        "fn_by_severity": {severity: fn_by[severity] for severity in SEVERITIES},
        "fp_total": fp_total, "fn_total": fn_total,
        "precision": _ratio(tp_total, tp_total + fp_total),
        "recall": _ratio(tp_total, tp_total + fn_total),
        "precision_by_severity": {
            severity: _ratio(tp_by[severity], tp_by[severity] + fp_by[severity])
            for severity in SEVERITIES},
        "recall_by_severity": {
            severity: _ratio(tp_by[severity], tp_by[severity] + fn_by[severity])
            for severity in SEVERITIES},
        "blocker_recall": _ratio(tp_by["blocker"], expected_blockers),
        "outcome_accuracy": _ratio(outcome_hits, len(materialized)),
        "exact_case_accuracy": _ratio(exact_hits, len(materialized)),
        "severity_confusion": dict(sorted(severity_confusion.items())),
        "weighted_cost": round(weighted_cost, 2),
        "error_costs": costs,
        "error_costs_hash": hashlib.sha256(
            json.dumps(costs, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "corpus_revision": corpus_revision,
        "rules_revision": rules_revision,
        "deterministic_coverage": {
            "cases_evaluated": len(materialized),
            "rules_evaluated": len(deterministic_rules),
            "positive_cases": {key: sorted(value) for key, value in positive_cases.items()},
            "negative_cases": {key: sorted(value) for key, value in negative_cases.items()},
        },
        "llm_coverage": {"cases_evaluated": 0, "findings_evaluated": 0,
                         "status": "not_measured_offline"},
        "schema_invariant_violations": [],
        "per_pr": per_pr,
    }


def _check(identifier: str, description: str, passed: bool, before: Any = None,
           after: Any = None) -> dict[str, Any]:
    return {"id": identifier, "description": description, "passed": bool(passed),
            "before": before, "after": after}


def _coverage_cases(
    metrics: Mapping[str, Any], bucket: str, rule_id: str
) -> set[str] | None:
    """Read one trusted coverage bucket, rejecting malformed metric payloads."""

    coverage = metrics.get("deterministic_coverage")
    if not isinstance(coverage, Mapping):
        return None
    values_by_rule = coverage.get(bucket)
    if not isinstance(values_by_rule, Mapping):
        return None
    values = values_by_rule.get(rule_id)
    if (
        not isinstance(values, list)
        or any(not isinstance(item, str) or not item for item in values)
        or len(values) != len(set(values))
    ):
        return None
    return set(values)


def _per_pr_rows(metrics: Mapping[str, Any]) -> dict[str, Mapping[str, Any]] | None:
    """Return complete, unique per-case rows or fail closed with ``None``."""

    rows = metrics.get("per_pr")
    case_ids = metrics.get("materialized_case_ids")
    if (
        not isinstance(rows, list)
        or not isinstance(case_ids, list)
        or any(not isinstance(case_id, str) or not case_id for case_id in case_ids)
        or len(case_ids) != len(set(case_ids))
    ):
        return None
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        case_id = row.get("pr")
        if not isinstance(case_id, str) or not case_id or case_id in result:
            return None
        for key in ("tp_findings", "fp_findings", "fn_findings"):
            findings = row.get(key)
            if not isinstance(findings, list) or any(
                not isinstance(finding, Mapping) for finding in findings
            ):
                return None
        if not isinstance(row.get("expected_outcome"), str):
            return None
        result[case_id] = row
    if set(result) != set(case_ids):
        return None
    return result


def _finding_fingerprint(
    row: Mapping[str, Any], *, excluding_rule: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    """Canonicalize non-target TP/FP/FN details for an exact case comparison."""

    groups: list[tuple[str, ...]] = []
    for key in ("tp_findings", "fp_findings", "fn_findings"):
        findings = row.get(key)
        if not isinstance(findings, list):
            return None
        encoded: list[str] = []
        for finding in findings:
            if not isinstance(finding, Mapping):
                return None
            if finding.get("rule_id") == excluding_rule:
                continue
            try:
                encoded.append(
                    json.dumps(
                        dict(finding),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            except (TypeError, ValueError):
                return None
        groups.append(tuple(sorted(encoded)))
    return groups[0], groups[1], groups[2]


def _target_cases(
    rows: Mapping[str, Mapping[str, Any]], rule_id: str, keys: Sequence[str]
) -> set[str] | None:
    result: set[str] = set()
    for case_id, row in rows.items():
        for key in keys:
            findings = row.get(key)
            if not isinstance(findings, list):
                return None
            for finding in findings:
                if not isinstance(finding, Mapping):
                    return None
                if finding.get("rule_id") == rule_id:
                    result.add(case_id)
    return result


def _deprecation_checks(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    changed_rule_ids: set[str],
    mutation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Prove a deprecation from locked evaluation evidence, not its claims.

    A removable deterministic rule must fire only as a false positive on the
    locked corpus, have at least one scope-relevant non-trigger control, and
    disappear completely in the candidate.  All non-target case results must
    remain byte-for-byte equivalent at the normalized finding boundary.  The
    ordinary gate still enforces no FN/FP/severity/outcome regression.
    """

    rule_id = mutation.get("rule_id")
    context_valid = (
        isinstance(rule_id, str)
        and bool(rule_id)
        and changed_rule_ids == {rule_id}
    )
    checks = [
        _check(
            "deprecation_context",
            "deprecate_rule меняет ровно заявленное target-rule",
            context_valid,
            sorted(changed_rule_ids),
            rule_id,
        )
    ]
    if not context_valid:
        checks.append(
            _check(
                "changed_rule_coverage",
                "deprecate_rule имеет trusted positive/negative coverage",
                False,
            )
        )
        return checks
    assert isinstance(rule_id, str)

    base_rows = _per_pr_rows(base)
    candidate_rows = _per_pr_rows(candidate)
    base_negative = _coverage_cases(base, "negative_cases", rule_id)

    rows_complete = (
        base_rows is not None
        and candidate_rows is not None
        and set(base_rows) == set(candidate_rows)
    )
    expected_target: set[str] | None = None
    base_false_positives: set[str] | None = None
    base_triggered: set[str] | None = None
    candidate_target: set[str] | None = None
    non_target_stable = False
    if rows_complete and base_rows is not None and candidate_rows is not None:
        expected_target = _target_cases(
            base_rows, rule_id, ("tp_findings", "fn_findings")
        )
        base_false_positives = _target_cases(
            base_rows, rule_id, ("fp_findings",)
        )
        base_triggered = _target_cases(
            base_rows, rule_id, ("tp_findings", "fp_findings")
        )
        candidate_target = _target_cases(
            candidate_rows, rule_id, ("tp_findings", "fp_findings")
        )
        non_target_stable = True
        for case_id in base_rows:
            base_fingerprint = _finding_fingerprint(
                base_rows[case_id], excluding_rule=rule_id
            )
            candidate_fingerprint = _finding_fingerprint(
                candidate_rows[case_id], excluding_rule=rule_id
            )
            if (
                base_rows[case_id].get("expected_outcome")
                != candidate_rows[case_id].get("expected_outcome")
                or base_fingerprint is None
                or candidate_fingerprint is None
                or base_fingerprint != candidate_fingerprint
            ):
                non_target_stable = False
                break

    no_expected_target = expected_target == set()
    target_disabled = candidate_target == set()
    trusted_positive = (
        base_false_positives
        if base_false_positives is not None
        and base_triggered is not None
        and base_false_positives == base_triggered
        and bool(base_false_positives)
        and no_expected_target
        and target_disabled
        else set()
    )
    trusted_negative = (
        set(base_negative)
        if base_negative is not None and base_negative and non_target_stable
        else set()
    )

    declared = mutation.get("coverage")
    declared_positive: set[str] | None = None
    declared_negative: set[str] | None = None
    if isinstance(declared, Mapping):
        raw_positive = declared.get("positive_cases")
        raw_negative = declared.get("negative_cases")
        if (
            isinstance(raw_positive, list)
            and isinstance(raw_negative, list)
            and raw_positive
            and raw_negative
            and all(isinstance(case_id, str) and case_id for case_id in raw_positive)
            and all(isinstance(case_id, str) and case_id for case_id in raw_negative)
            and len(raw_positive) == len(set(raw_positive))
            and len(raw_negative) == len(set(raw_negative))
        ):
            declared_positive = set(raw_positive)
            declared_negative = set(raw_negative)
    declarations_verified = (
        declared_positive is not None
        and declared_negative is not None
        and declared_positive.isdisjoint(declared_negative)
        and declared_positive == trusted_positive
        and declared_negative == trusted_negative
    )

    checks.extend(
        [
            _check(
                "deprecation_no_expected_findings",
                "locked ground truth не требует target-rule",
                no_expected_target,
                sorted(expected_target) if expected_target is not None else None,
                [],
            ),
            _check(
                "deprecation_target_disabled",
                "deprecated target-rule не срабатывает в candidate",
                target_disabled,
                sorted(base_triggered) if base_triggered is not None else None,
                sorted(candidate_target) if candidate_target is not None else None,
            ),
            _check(
                "deprecation_non_target_stability",
                "candidate не меняет per-case findings других правил",
                rows_complete and non_target_stable,
            ),
            _check(
                "deprecation_declared_coverage",
                "заявленные case IDs подтверждены locked evaluation",
                declarations_verified,
                {
                    "positive": sorted(declared_positive or set()),
                    "negative": sorted(declared_negative or set()),
                },
                {
                    "trusted_positive": sorted(trusted_positive),
                    "trusted_negative": sorted(trusted_negative),
                },
            ),
            _check(
                "changed_rule_coverage",
                "deprecate_rule имеет trusted false-positive и "
                "scope-relevant negative coverage",
                bool(trusted_positive)
                and bool(trusted_negative)
                and declarations_verified,
                None,
                {
                    "positive": sorted(trusted_positive),
                    "negative": sorted(trusted_negative),
                },
            ),
        ]
    )
    return checks


def gate(base: Mapping[str, Any], candidate: Mapping[str, Any], *,
         changed_rule_ids: set[str] | None = None,
         mutation: Mapping[str, Any] | None = None) -> tuple[bool, list[dict[str, Any]]]:
    """Strict, machine-readable gate. Cost shifting can never be improvement."""
    checks: list[dict[str, Any]] = [
        _check("no_invariant_violations", "нет schema/invariant violations",
               not candidate.get("schema_invariant_violations")),
        _check("same_corpus", "base и candidate используют один corpus snapshot",
               candidate.get("corpus_revision") == base.get("corpus_revision"),
               base.get("corpus_revision"), candidate.get("corpus_revision")),
        _check("same_fixtures", "base и candidate используют один materialized fixture snapshot",
               candidate.get("fixtures_revision") == base.get("fixtures_revision"),
               base.get("fixtures_revision"), candidate.get("fixtures_revision")),
        _check("same_error_costs", "candidate не меняет веса ошибок",
               candidate.get("error_costs_hash") == base.get("error_costs_hash"),
               base.get("error_costs_hash"), candidate.get("error_costs_hash")),
        _check("blocker_recall", "blocker recall не падает",
               candidate["blocker_recall"] >= base["blocker_recall"],
               base["blocker_recall"], candidate["blocker_recall"]),
        _check("no_blocker_downgrade", "expected blocker не найден другой severity",
               not any(key.startswith("blocker->") and value
                       for key, value in candidate.get("severity_confusion", {}).items()),
               base.get("severity_confusion", {}), candidate.get("severity_confusion", {})),
        _check("recall", "общий recall не падает", candidate["recall"] >= base["recall"],
               base["recall"], candidate["recall"]),
        _check("precision", "общая precision не падает",
               candidate["precision"] >= base["precision"], base["precision"], candidate["precision"]),
        _check("outcome_accuracy", "точность вердиктов не падает",
               candidate["outcome_accuracy"] >= base["outcome_accuracy"],
               base["outcome_accuracy"], candidate["outcome_accuracy"]),
        _check("weighted_cost", "weighted cost не растёт",
               candidate["weighted_cost"] <= base["weighted_cost"],
               base["weighted_cost"], candidate["weighted_cost"]),
        _check("false_blocker", "false blocker count не растёт",
               candidate["fp_by_severity"]["blocker"] <= base["fp_by_severity"]["blocker"],
               base["fp_by_severity"]["blocker"], candidate["fp_by_severity"]["blocker"]),
    ]
    for severity in SEVERITIES:
        checks.append(_check(f"fp_{severity}", f"FP {severity} не растут",
                             candidate["fp_by_severity"][severity]
                             <= base["fp_by_severity"][severity],
                             base["fp_by_severity"][severity], candidate["fp_by_severity"][severity]))
        checks.append(_check(f"fn_{severity}", f"FN {severity} не растут",
                             candidate["fn_by_severity"][severity]
                             <= base["fn_by_severity"][severity],
                             base["fn_by_severity"][severity], candidate["fn_by_severity"][severity]))
    substantive = (
        candidate["fp_total"] < base["fp_total"]
        or candidate["fn_total"] < base["fn_total"]
        or candidate["outcome_accuracy"] > base["outcome_accuracy"]
        or sum(candidate.get("severity_confusion", {}).values())
        < sum(base.get("severity_confusion", {}).values())
    )
    checks.append(_check("strict_improvement", "есть содержательное строгое улучшение",
                         substantive,
                         {"fp": base["fp_total"], "fn": base["fn_total"]},
                         {"fp": candidate["fp_total"], "fn": candidate["fn_total"]}))
    if changed_rule_ids and isinstance(mutation, Mapping) \
            and mutation.get("type") == "deprecate_rule":
        checks.extend(_deprecation_checks(
            base,
            candidate,
            changed_rule_ids=changed_rule_ids,
            mutation=mutation,
        ))
    elif changed_rule_ids:
        coverage = candidate.get("deterministic_coverage", {})
        positive = coverage.get("positive_cases", {})
        negative = coverage.get("negative_cases", {})
        covered = all(positive.get(rule_id) and negative.get(rule_id) for rule_id in changed_rule_ids)
        checks.append(_check("changed_rule_coverage",
                             "каждое изменяемое правило имеет positive и scope-relevant negative coverage", covered,
                             None, {rule_id: {"positive": positive.get(rule_id, []),
                                             "negative": negative.get(rule_id, [])}
                                    for rule_id in sorted(changed_rule_ids)}))
    return all(check["passed"] for check in checks), checks


def markdown_report(base: Mapping[str, Any], candidate: Mapping[str, Any],
                    checks: Sequence[Mapping[str, Any]]) -> str:
    rows = [
        ("cases evaluated", base["cases_evaluated"], candidate["cases_evaluated"]),
        ("precision (findings)", base["precision"], candidate["precision"]),
        ("recall (findings)", base["recall"], candidate["recall"]),
        ("blocker recall", base["blocker_recall"], candidate["blocker_recall"]),
        ("outcome accuracy", base["outcome_accuracy"], candidate["outcome_accuracy"]),
        ("weighted cost", base["weighted_cost"], candidate["weighted_cost"]),
        ("false findings", base["fp_total"], candidate["fp_total"]),
        ("missed findings", base["fn_total"], candidate["fn_total"]),
    ]
    lines = ["| Метрика | База | Кандидат | Δ |", "|---|---:|---:|---:|"]
    for name, before, after in rows:
        delta = round(after - before, 4)
        arrow = "→" if delta == 0 else ("↑" if delta > 0 else "↓")
        lines.append(f"| {name} | {before} | {after} | {arrow} {delta:+g} |")
    lines.extend(["", "Гейт:"])
    for check in checks:
        lines.append(f"- [{'x' if check['passed'] else ' '}] {check['description']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="AGA fitness gate")
    parser.add_argument("--rules", default=str(PKG_ROOT / "rules"))
    parser.add_argument("--out", help="write metrics JSON")
    parser.add_argument("--compare", nargs=2, metavar=("BASE.json", "CAND.json"))
    parser.add_argument("--minimum-cases", type=int, default=15)
    args = parser.parse_args()
    try:
        if args.compare:
            base = json.loads(Path(args.compare[0]).read_text(encoding="utf-8"))
            candidate = json.loads(Path(args.compare[1]).read_text(encoding="utf-8"))
            passed, checks = gate(base, candidate)
            print(markdown_report(base, candidate, checks))
            print(f"\nGATE: {'PASS' if passed else 'FAIL'}")
            raise SystemExit(0 if passed else 1)
        metrics = evaluate(args.rules, minimum_cases=args.minimum_cases)
    except (FitnessValidationError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": "fitness_validation", "message": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        raise SystemExit(2) from exc
    rendered = json.dumps(metrics, ensure_ascii=False, indent=2)
    print(rendered)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
