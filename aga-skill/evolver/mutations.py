# -*- coding: utf-8 -*-
"""Fail-closed validation for AGA evolution mutations.

This module deliberately does not apply mutations.  Callers must validate a
mutation before creating a candidate tree and may then pass the returned copy
to their applicator.  Approval of a precedent/incident is supplied through a
trusted registry instead of being inferred from mutation-controlled data.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any, NoReturn


SUPPORTED_MUTATION_TYPES = frozenset(
    {
        "add_exception",
        "adjust_severity",
        "add_rule",
        "activate_rule",
        "deprecate_rule",
    }
)

# They are mentioned in the current documentation but have no safe applicator
# contract yet.  A distinct exception lets a caller report "unsupported"
# instead of treating the input as malformed or silently ignoring it.
DOCUMENTED_UNSUPPORTED_TYPES = frozenset(
    {"add_fewshot", "edit_template", "refine_wording"}
)

VALID_SEVERITIES = frozenset({"blocker", "major", "minor"})
VALID_STATUSES = frozenset({"active", "candidate", "deprecated"})
VALID_CHECK_TYPES = frozenset({"deterministic", "llm", "hybrid"})
VALID_SCOPES = frozenset(
    {"system_passport", "integration_flow", "adr", "diagram", "out_of_scope"}
)

_PROVENANCE_RE = re.compile(r"(?:precedent|incident):[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_RULE_ID_RE = re.compile(r"[A-Z][A-Z0-9]*-[0-9]{3,}\Z")
_CONDITION_OPERATORS = frozenset({"equals", "contains", "in"})


class MutationValidationError(ValueError):
    """A typed, user-actionable mutation validation failure."""

    def __init__(self, code: str, message: str, *, field: str | None = None):
        self.code = code
        self.field = field
        prefix = f"{field}: " if field else ""
        super().__init__(f"{code}: {prefix}{message}")


class UnsupportedMutationTypeError(MutationValidationError):
    """The mutation is known/documented but has no safe implementation."""


def _fail(code: str, message: str, *, field: str | None = None) -> NoReturn:
    raise MutationValidationError(code, message, field=field)


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("invalid_type", "expected a mapping", field=field)
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("required_field", "must be a non-empty string", field=field)
    return value.strip()


def _require_string_list(value: Any, field: str, *, non_empty: bool = True) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _fail("invalid_type", "expected a list of strings", field=field)
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_require_text(item, f"{field}[{index}]"))
    if non_empty and not result:
        _fail("required_field", "must not be empty", field=field)
    return result


def _normalise_rules(rules: Any) -> list[Mapping[str, Any]]:
    if isinstance(rules, Mapping):
        rules = rules.get("rules")
    if isinstance(rules, (str, bytes)) or not isinstance(rules, Sequence):
        _fail("invalid_rules", "rules must be a list or a mapping containing rules")

    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, raw_rule in enumerate(rules):
        rule = _require_mapping(raw_rule, f"rules[{index}]")
        rule_id = _require_text(rule.get("id"), f"rules[{index}].id")
        if rule_id in seen:
            _fail("duplicate_rule_id", f"duplicate rule id {rule_id!r}", field="rules")
        seen.add(rule_id)
        result.append(rule)
    return result


def _approved_refs(registry: Any) -> frozenset[str]:
    """Return refs explicitly marked approved by a trusted caller.

    A collection of strings is treated as an already-filtered approval set.
    A mapping is stricter: each value must be ``True`` or a record containing
    ``approved: true``.  Merely appearing in a mapping is not approval.
    """
    if isinstance(registry, Mapping):
        approved_refs = {
            str(ref)
            for ref, record in registry.items()
            if record is True
            or (isinstance(record, Mapping) and record.get("approved") is True)
        }
        return frozenset(approved_refs)
    if isinstance(registry, (str, bytes)) or not isinstance(registry, Collection):
        _fail(
            "invalid_approval_registry",
            "approved_provenance must be a collection of refs or an approval mapping",
        )
    approved: set[str] = set()
    for ref in registry:
        approved.add(_require_text(ref, "approved_provenance[]"))
    return frozenset(approved)


def _validate_mutation_provenance(mutation: Mapping[str, Any], registry: Any) -> str:
    ref = _require_text(mutation.get("provenance"), "provenance")
    if not _PROVENANCE_RE.fullmatch(ref):
        _fail(
            "invalid_provenance",
            "expected precedent:<id> or incident:<id>",
            field="provenance",
        )
    if ref not in _approved_refs(registry):
        _fail(
            "unapproved_provenance",
            f"{ref!r} is not present in the trusted approved registry",
            field="provenance",
        )
    return ref


def _validate_rule_provenance(value: Any, field: str, *, expected_origin: str | None = None) -> None:
    provenance = _require_mapping(value, field)
    origin = _require_text(provenance.get("origin"), f"{field}.origin")
    _require_text(provenance.get("added_in"), f"{field}.added_in")
    if expected_origin is not None and origin != expected_origin:
        _fail(
            "provenance_mismatch",
            f"rule origin must equal mutation provenance {expected_origin!r}",
            field=f"{field}.origin",
        )


def _validate_existing_rule(rule: Mapping[str, Any], *, field: str = "rule") -> None:
    _require_text(rule.get("source_ref"), f"{field}.source_ref")
    _validate_rule_provenance(rule.get("provenance"), f"{field}.provenance")
    if rule.get("severity") not in VALID_SEVERITIES:
        _fail("invalid_severity", "unknown severity", field=f"{field}.severity")
    if rule.get("status") not in VALID_STATUSES:
        _fail("invalid_status", "unknown status", field=f"{field}.status")


def _find_rule(rules: Sequence[Mapping[str, Any]], rule_id: Any) -> Mapping[str, Any]:
    target_id = _require_text(rule_id, "rule_id")
    for rule in rules:
        if rule["id"] == target_id:
            _validate_existing_rule(rule)
            return rule
    _fail("unknown_rule_id", f"rule {target_id!r} does not exist", field="rule_id")


def _validate_condition(condition: Any, field: str = "exception.when") -> None:
    cond = _require_mapping(condition, field)
    if not cond:
        _fail("tautological_exception", "an empty condition matches globally", field=field)

    logical = [name for name in ("all", "any") if name in cond]
    if logical:
        if len(logical) != 1 or len(cond) != 1:
            _fail(
                "malformed_exception",
                "logical all/any cannot be mixed with other condition keys",
                field=field,
            )
        operator = logical[0]
        clauses = cond[operator]
        if isinstance(clauses, (str, bytes)) or not isinstance(clauses, Sequence):
            _fail("malformed_exception", f"{operator} must contain a list", field=field)
        if not clauses:
            code = "tautological_exception" if operator == "all" else "malformed_exception"
            _fail(code, f"{operator} must not be empty", field=field)
        for index, clause in enumerate(clauses):
            _validate_condition(clause, f"{field}.{operator}[{index}]")
        return

    allowed = {"field", *_CONDITION_OPERATORS}
    unknown = set(cond) - allowed
    if unknown:
        _fail(
            "malformed_exception",
            f"unsupported condition keys: {', '.join(sorted(map(str, unknown)))}",
            field=field,
        )
    lookup = _require_text(cond.get("field"), f"{field}.field")
    if lookup == "*":
        _fail("tautological_exception", "wildcard field is not allowed", field=field)
    operators = [name for name in _CONDITION_OPERATORS if name in cond]
    if len(operators) != 1:
        _fail(
            "malformed_exception",
            "exactly one of equals/contains/in is required",
            field=field,
        )
    operator = operators[0]
    operand = cond[operator]
    if operator == "in":
        if isinstance(operand, (str, bytes)) or not isinstance(operand, Sequence) or not operand:
            _fail("malformed_exception", "in requires a non-empty list", field=f"{field}.in")
    elif operator == "contains" and operand is None:
        _fail("malformed_exception", "contains requires a value", field=f"{field}.contains")


def _condition_trigger_values(condition: Mapping[str, Any], trigger_field: str) -> set[Any] | None:
    """Return values covered *only* by trigger_field, else None.

    Returning None for a conjunction with another predicate is intentional:
    that conjunction narrows an exception and therefore does not globally
    disable the detector.
    """
    if "all" in condition:
        clauses = condition["all"]
        if len(clauses) != 1:
            return None
        return _condition_trigger_values(clauses[0], trigger_field)
    if "any" in condition:
        covered: set[Any] = set()
        for clause in condition["any"]:
            values = _condition_trigger_values(clause, trigger_field)
            if values is None:
                return None
            covered.update(values)
        return covered
    if condition.get("field") != trigger_field:
        return None
    if "equals" in condition:
        try:
            return {condition["equals"]}
        except TypeError:
            return None
    if "in" in condition:
        try:
            return set(condition["in"])
        except TypeError:
            return None
    return None


def _banned_trigger(rule: Mapping[str, Any]) -> tuple[str, set[Any]] | None:
    detect = rule.get("detect")
    if not isinstance(detect, Mapping):
        return None

    if isinstance(detect.get("field"), str) and isinstance(detect.get("banned"), Sequence):
        banned = detect["banned"]
        if not isinstance(banned, (str, bytes)):
            try:
                return detect["field"], set(banned)
            except TypeError:
                return None

    field_banned = detect.get("field_banned")
    if isinstance(field_banned, Mapping):
        field = field_banned.get("field")
        values = field_banned.get("values", field_banned.get("banned"))
        if isinstance(field, str) and isinstance(values, Sequence) and not isinstance(
            values, (str, bytes)
        ):
            try:
                return field, set(values)
            except TypeError:
                return None
    return None


def _reject_global_exception(rule: Mapping[str, Any], condition: Mapping[str, Any]) -> None:
    trigger = _banned_trigger(rule)
    if trigger is None:
        return
    field, trigger_values = trigger
    covered = _condition_trigger_values(condition, field)
    if trigger_values and covered is not None and trigger_values.issubset(covered):
        _fail(
            "global_exception",
            "condition suppresses every trigger of the target rule",
            field="exception.when",
        )


def _validate_committee_decision(value: Any, field: str = "committee_decision") -> None:
    decision = _require_mapping(value, field)
    decision_id = decision.get("id", decision.get("decision_id"))
    _require_text(decision_id, f"{field}.id")
    if decision.get("approved") is not True:
        _fail("committee_approval_required", "approved must be true", field=f"{field}.approved")
    evidence = decision.get("evidence", decision.get("rationale"))
    _require_text(evidence, f"{field}.evidence")


def _validate_human_approval(value: Any) -> None:
    approval = _require_mapping(value, "human_approval")
    if approval.get("approved") is not True:
        _fail(
            "human_approval_required",
            "approved must be true",
            field="human_approval.approved",
        )
    _require_text(approval.get("actor"), "human_approval.actor")
    evidence = approval.get("evidence", approval.get("decision_id"))
    _require_text(evidence, "human_approval.evidence")


def _validate_add_exception(
    mutation: Mapping[str, Any], rules: Sequence[Mapping[str, Any]], provenance: str
) -> None:
    rule = _find_rule(rules, mutation.get("rule_id"))
    exception = _require_mapping(mutation.get("exception"), "exception")
    _require_text(exception.get("rationale"), "exception.rationale")
    nested_provenance = _require_text(exception.get("provenance"), "exception.provenance")
    if nested_provenance != provenance:
        _fail(
            "provenance_mismatch",
            "exception provenance must equal mutation provenance",
            field="exception.provenance",
        )
    if "added_in" in exception:
        _require_text(exception.get("added_in"), "exception.added_in")

    exception_id = exception.get("id")
    if exception_id is not None:
        exception_id = _require_text(exception_id, "exception.id")
        existing_ids = {
            item.get("id")
            for item in rule.get("exceptions", [])
            if isinstance(item, Mapping)
        }
        if exception_id in existing_ids:
            _fail(
                "duplicate_exception_id",
                f"exception id {exception_id!r} already exists",
                field="exception.id",
            )

    condition = _require_mapping(exception.get("when"), "exception.when")
    _validate_condition(condition)
    _reject_global_exception(rule, condition)


def _validate_adjust_severity(
    mutation: Mapping[str, Any], rules: Sequence[Mapping[str, Any]]
) -> None:
    rule = _find_rule(rules, mutation.get("rule_id"))
    severity = mutation.get("new_severity")
    if severity not in VALID_SEVERITIES:
        _fail("invalid_severity", "unknown severity", field="new_severity")
    if severity == rule["severity"]:
        _fail("no_op_mutation", "new severity equals current severity", field="new_severity")
    if rule["severity"] == "blocker" and severity != "blocker":
        _validate_committee_decision(mutation.get("committee_decision"))


def _validate_new_rule(rule: Any, provenance: str) -> None:
    item = _require_mapping(rule, "rule")
    required_text = ("id", "title", "statement", "source_ref")
    for key in required_text:
        _require_text(item.get(key), f"rule.{key}")
    if not _RULE_ID_RE.fullmatch(item["id"]):
        _fail("invalid_rule_id", "expected DOMAIN-NNN format", field="rule.id")
    if item.get("severity") not in VALID_SEVERITIES:
        _fail("invalid_severity", "unknown severity", field="rule.severity")
    if item.get("status") not in {"active", "candidate"}:
        _fail(
            "invalid_status",
            "add_rule status must be active or candidate",
            field="rule.status",
        )
    if item["status"] == "active" and item["severity"] == "blocker":
        _fail(
            "active_blocker_rule_forbidden",
            "add_rule cannot create an active blocker",
            field="rule.status",
        )
    if item.get("check_type") not in VALID_CHECK_TYPES:
        _fail("invalid_check_type", "unknown check_type", field="rule.check_type")
    scopes = _require_string_list(item.get("scope"), "rule.scope")
    unknown_scopes = set(scopes) - VALID_SCOPES
    if unknown_scopes:
        _fail(
            "invalid_scope",
            f"unknown scopes: {', '.join(sorted(unknown_scopes))}",
            field="rule.scope",
        )
    if item["check_type"] in {"deterministic", "hybrid"}:
        detect = _require_mapping(item.get("detect"), "rule.detect")
        if not detect:
            _fail("required_field", "deterministic rule requires detect", field="rule.detect")
    _validate_rule_provenance(item.get("provenance"), "rule.provenance", expected_origin=provenance)


def _validate_add_rule(
    mutation: Mapping[str, Any], rules: Sequence[Mapping[str, Any]], provenance: str
) -> None:
    new_rule = _require_mapping(mutation.get("rule"), "rule")
    _validate_new_rule(new_rule, provenance)
    existing = {rule["id"] for rule in rules}
    if new_rule["id"] in existing:
        _fail("duplicate_rule_id", f"rule {new_rule['id']!r} already exists", field="rule.id")


def _validate_activate_rule(
    mutation: Mapping[str, Any], rules: Sequence[Mapping[str, Any]]
) -> None:
    rule = _find_rule(rules, mutation.get("rule_id"))
    if rule["status"] != "candidate":
        _fail(
            "invalid_status_transition",
            "only candidate rules can be activated",
            field="rule_id",
        )
    _validate_human_approval(mutation.get("human_approval"))


def _validate_deprecate_rule(
    mutation: Mapping[str, Any], rules: Sequence[Mapping[str, Any]]
) -> None:
    rule = _find_rule(rules, mutation.get("rule_id"))
    if rule["status"] == "deprecated":
        _fail("invalid_status_transition", "rule is already deprecated", field="rule_id")
    _require_text(mutation.get("reason"), "reason")
    _require_text(mutation.get("evidence"), "evidence")
    coverage = _require_mapping(mutation.get("coverage"), "coverage")
    positive = _require_string_list(
        coverage.get("positive_cases"), "coverage.positive_cases"
    )
    negative = _require_string_list(
        coverage.get("negative_cases"), "coverage.negative_cases"
    )
    if len(positive) != len(set(positive)):
        _fail(
            "duplicate_coverage_case",
            "case IDs must be unique",
            field="coverage.positive_cases",
        )
    if len(negative) != len(set(negative)):
        _fail(
            "duplicate_coverage_case",
            "case IDs must be unique",
            field="coverage.negative_cases",
        )
    overlap = set(positive).intersection(negative)
    if overlap:
        _fail(
            "overlapping_coverage_case",
            f"positive and negative coverage overlap: {', '.join(sorted(overlap))}",
            field="coverage",
        )
    if rule["severity"] == "blocker":
        _validate_committee_decision(mutation.get("committee_decision"))


def validate_mutation(
    mutation: Any,
    rules: Any,
    *,
    approved_provenance: Any,
) -> dict[str, Any]:
    """Validate and return a defensive copy of a mutation.

    Args:
        mutation: Mutation mapping controlled by the evolver.
        rules: Existing rule list or a ``{"rules": [...]}`` document.
        approved_provenance: Trusted approved refs.  Pass either a collection
            such as ``{"precedent:0001"}``, or a mapping whose values are
            ``True``/``{"approved": True}``.

    Raises:
        MutationValidationError: malformed, unsafe or unapproved mutation.
        UnsupportedMutationTypeError: documented type without a safe runtime
            implementation.
    """
    item = _require_mapping(mutation, "mutation")
    mutation_type = _require_text(item.get("type"), "type")
    if mutation_type in DOCUMENTED_UNSUPPORTED_TYPES:
        raise UnsupportedMutationTypeError(
            "unsupported_mutation_type",
            f"{mutation_type!r} has no safe applicator contract",
            field="type",
        )
    if mutation_type not in SUPPORTED_MUTATION_TYPES:
        raise UnsupportedMutationTypeError(
            "unknown_mutation_type",
            f"unknown mutation type {mutation_type!r}",
            field="type",
        )

    existing_rules = _normalise_rules(rules)
    provenance = _validate_mutation_provenance(item, approved_provenance)

    validators = {
        "add_exception": lambda: _validate_add_exception(item, existing_rules, provenance),
        "adjust_severity": lambda: _validate_adjust_severity(item, existing_rules),
        "add_rule": lambda: _validate_add_rule(item, existing_rules, provenance),
        "activate_rule": lambda: _validate_activate_rule(item, existing_rules),
        "deprecate_rule": lambda: _validate_deprecate_rule(item, existing_rules),
    }
    validators[mutation_type]()
    return copy.deepcopy(dict(item))


__all__ = [
    "DOCUMENTED_UNSUPPORTED_TYPES",
    "MutationValidationError",
    "SUPPORTED_MUTATION_TYPES",
    "UnsupportedMutationTypeError",
    "VALID_SEVERITIES",
    "VALID_STATUSES",
    "validate_mutation",
]
