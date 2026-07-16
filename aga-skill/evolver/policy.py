# -*- coding: utf-8 -*-
"""Runtime policy guard for candidate evolution changes.

The guard complements repository/CI protection; it cannot provide process
isolation against code with unrestricted filesystem access.  It is intended
to run before fitness evaluation and again before candidate publication.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml


PROTECTED_PATHS = frozenset(
    {
        "SKILL.md",
        "VERSION",
        "CHANGELOG.md",
        "evolver/fitness.py",
        "evolver/permissions.yaml",
        # A candidate must not rewrite the guards used to inspect itself.
        "evolver/mutations.py",
        "evolver/policy.py",
        "golden/corpus.lock.json",
    }
)

SEVERITY_POLICY_PATH = "rules/severity-policy.yaml"
CORPUS_PATH = "golden/corpus.yaml"
ALLOWED_RULE_PATHS = frozenset(
    {
        "rules/principles.yaml",
        "rules/seaf-checks.yaml",
        "rules/diagram-checks.yaml",
        "rules/adr-checks.yaml",
        SEVERITY_POLICY_PATH,
    }
)


class PolicyViolation(ValueError):
    """A typed runtime policy violation."""

    def __init__(self, code: str, message: str, *, path: str | None = None):
        self.code = code
        self.path = path
        prefix = f"{path}: " if path else ""
        super().__init__(f"{code}: {prefix}{message}")


@dataclass(frozen=True)
class CandidateChange:
    """A candidate file change with trusted base and candidate contents."""

    path: str
    before: Any
    after: Any


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _fail(code: str, message: str, *, path: str | None = None) -> None:
    raise PolicyViolation(code, message, path=path)


def _normalise_path(raw_path: Any) -> str:
    if not isinstance(raw_path, str) or not raw_path.strip():
        _fail("invalid_path", "path must be a non-empty relative string")
    path_text = raw_path.strip().replace("\\", "/")
    if path_text.startswith("/") or re.match(r"^[A-Za-z]:/", path_text):
        _fail("invalid_path", "absolute paths are forbidden", path=raw_path)
    pure = PurePosixPath(path_text)
    if ".." in pure.parts:
        _fail("invalid_path", "parent traversal is forbidden", path=raw_path)
    normalised = str(pure)
    if normalised in {"", "."}:
        _fail("invalid_path", "empty path is forbidden", path=raw_path)
    return normalised.removeprefix("./")


def _coerce_change(raw: Any) -> CandidateChange:
    if isinstance(raw, CandidateChange):
        return CandidateChange(_normalise_path(raw.path), raw.before, raw.after)
    if not isinstance(raw, Mapping):
        _fail("invalid_change", "each change must be CandidateChange or a mapping")
    missing = {"path", "before", "after"} - set(raw)
    if missing:
        _fail("invalid_change", f"missing fields: {', '.join(sorted(missing))}")
    return CandidateChange(_normalise_path(raw["path"]), raw["before"], raw["after"])


def _yaml_mapping(content: Any, path: str, side: str) -> Mapping[str, Any]:
    if isinstance(content, Mapping):
        return copy.deepcopy(content)
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PolicyViolation(
                "invalid_candidate_content", f"{side} is not UTF-8", path=path
            ) from exc
    if not isinstance(content, str):
        _fail(
            "candidate_content_required",
            f"{side} content is required for semantic policy validation",
            path=path,
        )
    try:
        loaded = yaml.load(content, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise PolicyViolation(
            "invalid_candidate_yaml", f"cannot parse {side}: {exc}", path=path
        ) from exc
    if not isinstance(loaded, Mapping):
        _fail("invalid_candidate_yaml", f"{side} must be a mapping", path=path)
    return loaded


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _guard_severity_policy(change: CandidateChange) -> None:
    before = _yaml_mapping(change.before, change.path, "base")
    after = _yaml_mapping(change.after, change.path, "candidate")

    before_auto_merge = _nested(before, "autonomy", "auto_merge")
    after_auto_merge = _nested(after, "autonomy", "auto_merge")
    if before_auto_merge is not False or after_auto_merge is not False:
        _fail(
            "auto_merge_invariant",
            "autonomy.auto_merge must exist and remain false",
            path=change.path,
        )
    if before_auto_merge != after_auto_merge:
        _fail(
            "auto_merge_change_forbidden",
            "candidate cannot change autonomy.auto_merge",
            path=change.path,
        )

    for key in ("error_costs", "error_weights"):
        base_weights = before.get(key)
        candidate_weights = after.get(key)
        if base_weights != candidate_weights:
            _fail(
                "error_weights_change_forbidden",
                f"candidate cannot change {key}",
                path=change.path,
            )


def _cases_by_id(document: Mapping[str, Any], path: str, side: str) -> dict[str, Mapping[str, Any]]:
    cases = document.get("cases")
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        _fail("invalid_corpus", f"{side}.cases must be a list", path=path)
    result: dict[str, Mapping[str, Any]] = {}
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            _fail("invalid_corpus", f"{side}.cases[{index}] must be a mapping", path=path)
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            _fail("invalid_corpus", f"{side}.cases[{index}].id is required", path=path)
        if case_id in result:
            _fail("duplicate_case_id", f"duplicate case id {case_id!r}", path=path)
        result[case_id] = case
    return result


def _guard_corpus(change: CandidateChange) -> None:
    before = _yaml_mapping(change.before, change.path, "base")
    after = _yaml_mapping(change.after, change.path, "candidate")
    base_cases = _cases_by_id(before, change.path, "base")
    candidate_cases = _cases_by_id(after, change.path, "candidate")

    for case_id, base_case in base_cases.items():
        candidate_case = candidate_cases.get(case_id)
        if candidate_case is None:
            _fail(
                "existing_case_removed",
                f"existing case {case_id!r} cannot be removed",
                path=change.path,
            )
        if "expected" not in base_case:
            _fail(
                "invalid_corpus",
                f"base case {case_id!r} has no expected ground truth",
                path=change.path,
            )
        if candidate_case.get("expected") != base_case["expected"]:
            _fail(
                "existing_expected_change_forbidden",
                f"expected ground truth changed for {case_id!r}",
                path=change.path,
            )


def guard_candidate_changes(changes: Iterable[CandidateChange | Mapping[str, Any]]) -> tuple[CandidateChange, ...]:
    """Validate a candidate change set and return normalized immutable records.

    The caller must provide both base and candidate content for semantic files
    (`rules/severity-policy.yaml` and `golden/corpus.yaml`).  Missing evidence
    fails closed.  New corpus cases are allowed; existing expected values are
    immutable.
    """
    if isinstance(changes, (str, bytes)) or not isinstance(changes, Iterable):
        _fail("invalid_change_set", "changes must be an iterable of file changes")

    validated: list[CandidateChange] = []
    seen_paths: set[str] = set()
    for raw in changes:
        change = _coerce_change(raw)
        if change.path in seen_paths:
            _fail("duplicate_changed_path", "path occurs more than once", path=change.path)
        seen_paths.add(change.path)

        # An entry with identical contents is not a change and cannot affect a
        # candidate.  It is safe to omit it from the normalized result.
        if change.before == change.after:
            continue

        if change.path in PROTECTED_PATHS:
            _fail("protected_path", "candidate cannot modify this path", path=change.path)
        if not (change.path in ALLOWED_RULE_PATHS or change.path == CORPUS_PATH):
            _fail(
                "unapproved_path",
                "candidate path is outside the rules/corpus mutation allowlist",
                path=change.path,
            )
        if change.path.startswith(f"{CORPUS_PATH}#"):
            _fail(
                "existing_expected_change_forbidden",
                "fragment-level corpus mutation is forbidden; validate the complete document",
                path=change.path,
            )
        if change.path.startswith(f"{SEVERITY_POLICY_PATH}#"):
            _fail(
                "protected_policy_field",
                "fragment-level severity-policy mutation is forbidden",
                path=change.path,
            )
        if change.path == SEVERITY_POLICY_PATH:
            _guard_severity_policy(change)
        elif change.path == CORPUS_PATH:
            _guard_corpus(change)
        validated.append(change)

    return tuple(validated)


# An explicit alias reads naturally at call sites that use "validate" for all
# boundary checks.
validate_candidate_changes = guard_candidate_changes


__all__ = [
    "ALLOWED_RULE_PATHS",
    "CORPUS_PATH",
    "CandidateChange",
    "PROTECTED_PATHS",
    "PolicyViolation",
    "SEVERITY_POLICY_PATH",
    "guard_candidate_changes",
    "validate_candidate_changes",
]
