#!/usr/bin/env python3
"""Strict offline validator and SEAF-native Git materializer for development-v2.

The module has no provider/model route.  It validates public development ground
truth, verifies the measurement lock, and creates isolated deterministic Git
repositories consumable by the trusted AGA review boundary.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

import yaml


ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[1]
CORPUS_FILE = ROOT / "corpus.yaml"
LOCK_FILE = ROOT / "corpus.lock.json"
GATE_FILE = ROOT / "gate.yaml"
VALIDATOR_FILE = ROOT / "corpus_tool.py"
SCORER_FILE = ROOT / "runner.py"
PAID_RUNNER_FILE = ROOT / "run_paid_evaluation.py"
MEASUREMENT_CONFIG_FILE = ROOT / "measurement-config.yaml"

CORPUS_SCHEMA = "aga.synthetic-development-corpus/v2"
CASE_SCHEMA = "aga.synthetic-development-case/v2"
LOCK_SCHEMA = "aga.synthetic-development-lock/v2"
MATERIALIZATION_SCHEMA = "aga.synthetic-development-materialization/v2"
MEASUREMENT_CONFIG_SCHEMA = "aga.synthetic-development-measurement-config/v2"
RULES = ("PRIN-004", "PRIN-005", "PRIN-006", "PRIN-007")
RULE_SEVERITY = {
    "PRIN-004": "major",
    "PRIN-005": "major",
    "PRIN-006": "blocker",
    "PRIN-007": "major",
    "SEAF-001": "blocker",
    "SEAF-004": "blocker",
}
COVERAGE_VALUES = frozenset({"positive", "negative", "not_targeted", "unresolved"})
LANGUAGES = frozenset({"en", "ru", "mixed"})
RELATIONS = frozenset(
    {
        "predicate_flip",
        "deterministic_predicate_flip",
        "same_meaning_paraphrase",
        "translation",
        "injection_invariance",
        "format_invariance",
        "context_completion",
    }
)
SAME_EXPECTED_RELATIONS = frozenset(
    {"same_meaning_paraphrase", "translation", "injection_invariance", "format_invariance"}
)
CONTROL_REMOVAL_FEATURES = {
    "PRIN-004": frozenset({"reuse-near-miss"}),
    "PRIN-005": frozenset({"read-only-replica", "noncritical-near-miss"}),
    "PRIN-006": frozenset({"noncritical-near-miss"}),
    "PRIN-007": frozenset({"valid-adr"}),
}
UNRESOLVED_KINDS = frozenset({"target", "context", "criticality", "status"})
ALLOWED_SUFFIXES = frozenset({".yaml", ".yml", ".md"})
CASE_ID_RE = re.compile(r"^dv2-[0-9]{3}-[a-z0-9]+(?:-[a-z0-9]+)*$")
PAIR_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SERIES_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
MAX_YAML_BYTES = 512_000
MAX_ARTIFACT_CHARS = 64_000
MIN_CASES = 32
MAX_CASES = 48
TRUSTED_DEPENDENCY_GITLINKS = {
    "seaf-archtool-core": "83c82ab1673f1245b499c26b82d507fa602a11d6",
    "architecture/vendor/seaf-core": "60ce335832d2734814c020306a85d1e8b12cf67b",
}

GATE_SCHEMA = "aga.synthetic-development-gate/v2"
GATE_THRESHOLD_FIELDS = frozenset(
    {
        "blocker_recall",
        "unsafe_approve_count",
        "invalid_or_hallucinated_evidence_count_max",
        "schema_valid_rate",
        "precision_min",
        "recall_min",
        "outcome_accuracy_min",
        "exact_case_accuracy_min",
    }
)
GATE_MINIMUM_RATES = {
    "blocker_recall": 1.0,
    "schema_valid_rate": 1.0,
    "precision_min": 0.80,
    "recall_min": 0.80,
    "outcome_accuracy_min": 0.85,
    "exact_case_accuracy_min": 0.85,
}

REQUIRED_FEATURE_MINIMUMS = {
    "synthetic-public": 32,
    "reuse-duplicate": 1,
    "reuse-near-miss": 1,
    "writable-master": 1,
    "read-only-replica": 1,
    "critical-dependency": 1,
    "noncritical-near-miss": 1,
    "missing-target": 1,
    "missing-context": 1,
    "missing-criticality": 1,
    "missing-status": 1,
    "significant-no-adr": 1,
    "weak-adr": 2,
    "valid-adr": 2,
    "prompt-injection": 4,
    "compound": 2,
    "clean": 4,
    "multilingual": 4,
    "paraphrase": 2,
    "metamorphic-control": 4,
    "yaml-adr": 1,
    "markdown-adr": 1,
    "structural-seaf004": 1,
    "structural-seaf004-control": 1,
}
FORBIDDEN_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{16,}"),
)


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _fields(
    value: Any,
    required: set[str],
    context: str,
    *,
    optional: set[str] = frozenset(),
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required - optional)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unknown {extra}")
        raise ValueError(f"{context} has invalid fields: {'; '.join(details)}")
    return value


def _exact(value: Any, fields: set[str], context: str) -> Mapping[str, Any]:
    return _fields(value, fields, context)


def _text(value: Any, context: str, *, limit: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    if len(value) > limit:
        raise ValueError(f"{context} exceeds {limit} characters")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{context} must use NFC Unicode normalization")
    return value


def _string_list(value: Any, context: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{context} must be a non-empty list")
    result = [_text(item, f"{context}[{index}]", limit=100) for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise ValueError(f"{context} must not contain duplicates")
    return result


def _strict_yaml_text(text: str, context: str) -> Any:
    try:
        return yaml.load(text, Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML in {context}: {error}") from error


def _load_yaml(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"YAML input must be a regular file: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_YAML_BYTES:
        raise ValueError(f"YAML input exceeds {MAX_YAML_BYTES} bytes: {path}")
    try:
        return _strict_yaml_text(raw.decode("utf-8"), str(path))
    except UnicodeDecodeError as error:
        raise ValueError(f"YAML input is not UTF-8: {path}") from error


def _load_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"JSON input must be a regular file: {path}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid UTF-8 JSON in {path}: {error}") from error


def _validate_gate(root: Path = ROOT) -> Mapping[str, Any]:
    gate = _exact(
        _load_yaml(root / "gate.yaml"),
        {"schema", "release_eligible", "required_repeated_runs", "thresholds"},
        "development gate",
    )
    if gate["schema"] != GATE_SCHEMA:
        raise ValueError("invalid development gate schema")
    if gate["release_eligible"] is not False:
        raise ValueError("development gate cannot claim release eligibility")
    if gate["required_repeated_runs"] != 5:
        raise ValueError("development gate must require five repeated captures")
    thresholds = _exact(
        gate["thresholds"], set(GATE_THRESHOLD_FIELDS), "development gate thresholds"
    )
    for name, minimum in GATE_MINIMUM_RATES.items():
        value = thresholds[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not minimum <= float(value) <= 1.0
        ):
            raise ValueError(f"development gate threshold {name} was weakened or is invalid")
    for name in (
        "unsafe_approve_count", "invalid_or_hallucinated_evidence_count_max"
    ):
        value = thresholds[name]
        if isinstance(value, bool) or not isinstance(value, int) or value != 0:
            raise ValueError(f"development gate threshold {name} must remain zero")
    return gate


def _safe_path(value: Any, context: str) -> str:
    text = _text(value, context, limit=240)
    if "\\" in text:
        raise ValueError(f"{context} must use POSIX separators")
    path = PurePosixPath(text)
    if path.is_absolute() or path.as_posix() != text:
        raise ValueError(f"{context} must be a canonical relative POSIX path")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{context} contains an unsafe path segment")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"{context} must identify YAML or Markdown")
    if text in {"dochub.yaml", "workspace/aga-extension.yaml"}:
        raise ValueError(f"{context} collides with a materializer-owned file")
    return text


def _validate_files(value: Any, context: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{context} must be a non-empty object")
    result: dict[str, str] = {}
    for raw_path, raw_content in value.items():
        path = _safe_path(raw_path, f"{context} path")
        content = _text(raw_content, f"{context}.{path}", limit=MAX_ARTIFACT_CHARS)
        if not content.endswith("\n"):
            raise ValueError(f"{context}.{path} must end with a newline")
        for pattern in FORBIDDEN_SECRET_PATTERNS:
            if pattern.search(content):
                raise ValueError(f"{context}.{path} resembles a credential/private key")
        result[path] = content
    return result


def _component(
    entity_id: str,
    item: Mapping[str, Any],
    *,
    case: Mapping[str, Any],
) -> dict[str, Any]:
    result = dict(item)
    result.setdefault("title", entity_id)
    result.setdefault("entity", "component")
    result.setdefault("owner", "Synthetic Development Team")
    if "criticality" not in result and "missing-criticality" not in case["features"]:
        result["criticality"] = "medium"
    if "target_status" not in result and "missing-status" not in case["features"]:
        result["target_status"] = "tactical"
    result.setdefault(
        "description",
        yaml.safe_dump(dict(item), allow_unicode=True, sort_keys=True).strip(),
    )
    return result


def _native_adr(raw: Mapping[str, Any], raw_text: str, case: Mapping[str, Any]) -> dict[str, Any]:
    entity_id = str(raw.get("id") or f"ADR-{case['id'].upper()}")
    consequences = raw.get("consequences", "Not recorded")
    consequences_text = (
        yaml.safe_dump(consequences, allow_unicode=True, sort_keys=True).strip()
        if isinstance(consequences, (list, Mapping))
        else str(consequences)
    )
    return {
        "seaf.change.adr": {
            entity_id: {
                "title": str(raw.get("title") or raw.get("decision") or entity_id),
                "moment": "2026-07-19",
                "status": str(raw.get("status") or "proposed"),
                "issue": str(raw.get("issue") or case["summary"]),
                "decision": str(raw.get("decision") or "Decision not recorded"),
                # Preserve all authored rationale/constraints/alternatives text
                # in a canonical field exposed by the trusted AGA adapter.
                "context": [
                    {
                        "area": "technology",
                        "vector": "unknown",
                        "content": raw_text.strip(),
                    }
                ],
                "consequences": [
                    {
                        "area": "technology",
                        "vector": "unknown",
                        "content": consequences_text,
                    }
                ],
            }
        }
    }


def _native_yaml_document(
    case: Mapping[str, Any], path: str, content: str, *, phase: str
) -> Mapping[str, Any]:
    parsed = _strict_yaml_text(content, f"{case['id']}:{path}")
    if not isinstance(parsed, Mapping):
        parsed = {"artifact_text": content.strip()}
    if isinstance(parsed.get("seaf.change.adr"), Mapping):
        return parsed
    if isinstance(parsed.get("adr"), Mapping):
        return _native_adr(parsed["adr"], content, case)

    native_integration = bool(
        {
            "structural-seaf004",
            "structural-seaf004-control",
            "trusted-reference-integration",
        }
        & set(case["features"])
    )
    if native_integration and isinstance(parsed.get("integrations"), Mapping):
        integrations: dict[str, Any] = {}
        for raw_id, raw_item in parsed["integrations"].items():
            item = dict(raw_item) if isinstance(raw_item, Mapping) else {}
            entity_id = str(raw_id) if "." in str(raw_id) else f"syn.{raw_id}"
            integrations[entity_id] = {
                "title": entity_id,
                "description": yaml.safe_dump(item, allow_unicode=True, sort_keys=True).strip(),
                "from": str(item.get("from") or "syn.unknown.source"),
                "to": str(item.get("to") or "syn.unknown.target"),
                "pattern": str(item.get("mode") or "unspecified"),
            }
        return {"seaf.app.integrations": integrations}

    components: dict[str, Any] = {}
    if isinstance(parsed.get("components"), Mapping):
        for entity_id, raw_item in parsed["components"].items():
            item = dict(raw_item) if isinstance(raw_item, Mapping) else {}
            components[str(entity_id)] = _component(str(entity_id), item, case=case)
    if isinstance(parsed.get("systems"), Mapping):
        for entity_id, raw_item in parsed["systems"].items():
            item = dict(raw_item) if isinstance(raw_item, Mapping) else {}
            components[str(entity_id)] = _component(str(entity_id), item, case=case)
    if isinstance(parsed.get("domains"), Mapping):
        for domain_id, raw_domain in parsed["domains"].items():
            if not isinstance(raw_domain, Mapping) or not raw_domain.get("master_system"):
                continue
            master = str(raw_domain["master_system"])
            current = dict(components.get(master, {}))
            current.setdefault("domain", str(domain_id))
            current.setdefault("description", f"Authoritative master for {domain_id}")
            components[master] = _component(master, current, case=case)
    if components:
        return {"components": components}

    entity_id = f"syn.{case['id']}.{'change' if phase == 'head' else 'base'}"
    return {
        "components": {
            entity_id: {
                "title": case["summary"],
                "entity": "component",
                "owner": "Synthetic Development Team",
                "criticality": "medium",
                "target_status": "tactical",
                "description": content.strip(),
            }
        }
    }


def native_state(case: Mapping[str, Any], phase: str) -> dict[str, Any]:
    if phase not in {"base", "head"}:
        raise ValueError(f"unknown materialization phase: {phase}")
    base = dict(case["change"]["base"]["files"])
    raw = base if phase == "base" else {**base, **case["change"]["head"]["files"]}
    head_paths = set(case["change"]["head"]["files"])
    result: dict[str, Any] = {}
    for path, content in raw.items():
        if path.endswith(".md"):
            result[path] = content
        else:
            document_phase = "head" if phase == "head" and path in head_paths else "base"
            result[path] = _native_yaml_document(case, path, content, phase=document_phase)
    return result


def _decode_pointer(pointer: str) -> list[str]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("location must be a non-empty JSON Pointer")
    result: list[str] = []
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError("location contains invalid JSON Pointer escaping")
        result.append(token.replace("~1", "/").replace("~0", "~"))
    return result


def _binding_document(path: str, document: Any) -> Any:
    if path.endswith(".md"):
        candidate = PurePosixPath(path)
        if candidate.parent.name not in {"adrs", "decisions"} or not candidate.stem.startswith("ADR-"):
            return {"markdown": {"body": document}}
        return {"seaf.change.adr": {candidate.stem: {"body": document}}}
    return document


def pointer_value(document: Any, pointer: str) -> Any:
    current = document
    for token in _decode_pointer(pointer):
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f"JSON Pointer does not resolve: {pointer}")
    return current


def _expected_signature(case: Mapping[str, Any]) -> tuple[Any, ...]:
    expected = case["expected"]
    findings = tuple(sorted((item["rule_id"], item["severity"]) for item in expected["findings"]))
    auxiliary = tuple(
        sorted(
            (item["rule_id"], item["severity"])
            for item in expected.get("auxiliary_findings", [])
        )
    )
    unresolved = tuple(sorted(item["kind"] for item in expected["unresolved_context"]))
    return expected["status"], expected["verdict"], findings, auxiliary, unresolved


def _validate_case(raw: Any, *, expected_id: str, expected_split: str) -> Mapping[str, Any]:
    case = _fields(
        raw,
        {
            "schema", "id", "split", "language", "summary", "features", "coverage",
            "metamorphic", "change", "expected",
        },
        expected_id,
        optional={"dangerous_controls"},
    )
    if case["schema"] != CASE_SCHEMA:
        raise ValueError(f"{expected_id}: invalid case schema")
    if case["id"] != expected_id or CASE_ID_RE.fullmatch(str(case["id"])) is None:
        raise ValueError(f"{expected_id}: case id mismatch or invalid format")
    if case["split"] != expected_split or case["split"] != "development":
        raise ValueError(f"{expected_id}: only development split is allowed")
    if case["language"] not in LANGUAGES:
        raise ValueError(f"{expected_id}: invalid language")
    _text(case["summary"], f"{expected_id}.summary", limit=500)
    features = _string_list(case["features"], f"{expected_id}.features")
    if "synthetic-public" not in features:
        raise ValueError(f"{expected_id}: synthetic-public feature is mandatory")
    coverage = _exact(case["coverage"], set(RULES), f"{expected_id}.coverage")
    if any(value not in COVERAGE_VALUES for value in coverage.values()):
        raise ValueError(f"{expected_id}: invalid rule coverage value")

    pair = _exact(
        case["metamorphic"], {"pair_id", "counterpart", "relation", "role"},
        f"{expected_id}.metamorphic",
    )
    if PAIR_ID_RE.fullmatch(_text(pair["pair_id"], f"{expected_id}.pair_id", limit=100)) is None:
        raise ValueError(f"{expected_id}: invalid pair id")
    counterpart = _text(pair["counterpart"], f"{expected_id}.counterpart", limit=100)
    if CASE_ID_RE.fullmatch(counterpart) is None or counterpart == expected_id:
        raise ValueError(f"{expected_id}: invalid metamorphic counterpart")
    if pair["relation"] not in RELATIONS or pair["role"] not in {"source", "variant", "control"}:
        raise ValueError(f"{expected_id}: invalid metamorphic relation or role")

    change = _exact(case["change"], {"base", "head"}, f"{expected_id}.change")
    base = _exact(change["base"], {"files"}, f"{expected_id}.change.base")
    head = _exact(change["head"], {"files"}, f"{expected_id}.change.head")
    base_files = _validate_files(base["files"], f"{expected_id}.change.base.files")
    head_patch = _validate_files(head["files"], f"{expected_id}.change.head.files")
    if all(base_files.get(path) == content for path, content in head_patch.items()):
        raise ValueError(f"{expected_id}: head patch has no content change")

    expected = _fields(
        case["expected"], {"status", "verdict", "findings", "unresolved_context"},
        f"{expected_id}.expected", optional={"auxiliary_findings"},
    )
    expected.setdefault("auxiliary_findings", [])
    if expected["status"] not in {"complete", "incomplete"}:
        raise ValueError(f"{expected_id}: invalid expected status")
    if expected["verdict"] not in {"approve", "request_changes_escalate", "incomplete"}:
        raise ValueError(f"{expected_id}: invalid strict expected verdict")
    if not isinstance(expected["findings"], list):
        raise ValueError(f"{expected_id}: findings must be a list")
    native_head = native_state(case, "head")
    finding_rules: list[str] = []
    for index, raw_finding in enumerate(expected["findings"]):
        finding = _exact(
            raw_finding,
            {"rule_id", "severity", "artifact", "location", "evidence_contains"},
            f"{expected_id}.expected.findings[{index}]",
        )
        rule_id = finding["rule_id"]
        if rule_id not in {*RULES, "SEAF-004"}:
            raise ValueError(f"{expected_id}: unsupported expected rule")
        if finding["severity"] != RULE_SEVERITY[rule_id]:
            raise ValueError(f"{expected_id}: severity does not match {rule_id}")
        artifact = _safe_path(finding["artifact"], f"{expected_id}.finding.artifact")
        if artifact not in native_head:
            raise ValueError(f"{expected_id}: finding artifact is absent from native head")
        location = _text(finding["location"], f"{expected_id}.finding.location", limit=500)
        bound = pointer_value(_binding_document(artifact, native_head[artifact]), location)
        evidence = _text(finding["evidence_contains"], f"{expected_id}.finding.evidence", limit=500)
        bound_text = bound if isinstance(bound, str) else json.dumps(bound, ensure_ascii=False, sort_keys=True)
        if evidence.casefold() not in bound_text.casefold():
            raise ValueError(f"{expected_id}: expected evidence is not bound at {artifact}{location}")
        finding_rules.append(rule_id)
    if len(finding_rules) != len(set(finding_rules)):
        raise ValueError(f"{expected_id}: at most one finding per rule is allowed")

    auxiliary_rules: list[str] = []
    if not isinstance(expected["auxiliary_findings"], list):
        raise ValueError(f"{expected_id}: auxiliary_findings must be a list")
    for index, raw_finding in enumerate(expected["auxiliary_findings"]):
        finding = _exact(
            raw_finding,
            {"rule_id", "severity", "artifact", "location", "evidence_contains"},
            f"{expected_id}.expected.auxiliary_findings[{index}]",
        )
        rule_id = finding["rule_id"]
        if rule_id != "SEAF-001" or finding["severity"] != RULE_SEVERITY[rule_id]:
            raise ValueError(f"{expected_id}: unsupported auxiliary deterministic finding")
        artifact = _safe_path(finding["artifact"], f"{expected_id}.auxiliary.artifact")
        if artifact not in native_head:
            raise ValueError(f"{expected_id}: auxiliary artifact is absent from native head")
        location = _text(finding["location"], f"{expected_id}.auxiliary.location", limit=500)
        bound = pointer_value(_binding_document(artifact, native_head[artifact]), location)
        evidence = _text(
            finding["evidence_contains"], f"{expected_id}.auxiliary.evidence", limit=500
        )
        bound_text = bound if isinstance(bound, str) else json.dumps(
            bound, ensure_ascii=False, sort_keys=True
        )
        if evidence.casefold() not in bound_text.casefold():
            raise ValueError(f"{expected_id}: auxiliary evidence is not bound")
        auxiliary_rules.append(rule_id)
    if len(auxiliary_rules) != len(set(auxiliary_rules)):
        raise ValueError(f"{expected_id}: auxiliary findings must be unique")

    unresolved_raw = expected["unresolved_context"]
    if not isinstance(unresolved_raw, list):
        raise ValueError(f"{expected_id}: unresolved_context must be a list")
    unresolved_kinds: list[str] = []
    for index, raw_item in enumerate(unresolved_raw):
        item = _exact(raw_item, {"kind", "reference", "reason"}, f"{expected_id}.unresolved[{index}]")
        if item["kind"] not in UNRESOLVED_KINDS:
            raise ValueError(f"{expected_id}: invalid unresolved context kind")
        _text(item["reference"], f"{expected_id}.unresolved.reference", limit=200)
        _text(item["reason"], f"{expected_id}.unresolved.reason", limit=500)
        unresolved_kinds.append(item["kind"])
    if len(unresolved_kinds) != len(set(unresolved_kinds)):
        raise ValueError(f"{expected_id}: unresolved kinds must be unique")

    positives = {rule_id for rule_id, value in coverage.items() if value == "positive"}
    semantic_findings = {rule_id for rule_id in finding_rules if rule_id in RULES}
    unresolved_rules = {rule_id for rule_id, value in coverage.items() if value == "unresolved"}
    if expected["status"] == "incomplete":
        if expected["verdict"] != "incomplete" or finding_rules or not unresolved_kinds:
            raise ValueError(f"{expected_id}: incomplete cases must fail closed without findings")
        if not unresolved_rules or positives:
            raise ValueError(f"{expected_id}: incomplete coverage must be unresolved")
    else:
        if unresolved_kinds or unresolved_rules:
            raise ValueError(f"{expected_id}: complete cases cannot retain unresolved context")
        if semantic_findings != positives:
            raise ValueError(f"{expected_id}: positive semantic coverage must match findings")
        required_verdict = "request_changes_escalate" if finding_rules else "approve"
        if expected["verdict"] != required_verdict:
            raise ValueError(f"{expected_id}: verdict conflicts with findings")
    if expected_id == "dv2-041-missing-target":
        if auxiliary_rules != ["SEAF-001"]:
            raise ValueError("dv2-041-missing-target must lock exactly one auxiliary SEAF-001")
    elif auxiliary_rules:
        raise ValueError(f"{expected_id}: auxiliary findings are forbidden")

    controls = case.get("dangerous_controls", {})
    if not isinstance(controls, Mapping) or set(controls) != positives:
        raise ValueError(f"{expected_id}: every positive rule needs exactly one dangerous control")
    for rule_id, control_id in controls.items():
        if not isinstance(control_id, str) or CASE_ID_RE.fullmatch(control_id) is None:
            raise ValueError(f"{expected_id}: invalid dangerous control for {rule_id}")

    if "prompt-injection" in features:
        joined = "\n".join(head_patch.values()).lower()
        if not any(marker in joined for marker in ("ignore previous", "ignore all", "игнориру", "verdict: approve")):
            raise ValueError(f"{expected_id}: injection feature lacks injection text")
    if "compound" in features and len(finding_rules) < 2:
        raise ValueError(f"{expected_id}: compound case requires at least two findings")
    if "clean" in features and (finding_rules or expected["status"] != "complete"):
        raise ValueError(f"{expected_id}: clean feature conflicts with expected outcome")
    if "markdown-adr" in features and not any(path.endswith(".md") for path in native_head):
        raise ValueError(f"{expected_id}: markdown ADR feature lacks Markdown")
    if "structural-seaf004" in features:
        if finding_rules != ["SEAF-004"] or coverage["PRIN-006"] == "positive":
            raise ValueError(f"{expected_id}: structural dependency must be SEAF-004, not PRIN-006")
    if coverage["PRIN-006"] == "positive":
        finding = next(item for item in expected["findings"] if item["rule_id"] == "PRIN-006")
        if finding["location"].startswith("/seaf.app.integrations/"):
            raise ValueError(f"{expected_id}: semantic PRIN-006 cannot target structural integration fields")
    return case


def coverage_report(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rules = {
        rule_id: {
            "positive": sum(case["coverage"][rule_id] == "positive" for case in cases),
            "negative": sum(case["coverage"][rule_id] == "negative" for case in cases),
            "unresolved": sum(case["coverage"][rule_id] == "unresolved" for case in cases),
        }
        for rule_id in RULES
    }
    return {
        "rules": rules,
        "features": dict(sorted(Counter(x for case in cases for x in case["features"]).items())),
        "languages": dict(sorted(Counter(case["language"] for case in cases).items())),
        "relations": dict(sorted(Counter(case["metamorphic"]["relation"] for case in cases).items())),
    }


def _validate_balance_and_pairs(cases: Sequence[Mapping[str, Any]]) -> None:
    report = coverage_report(cases)
    for rule_id in RULES:
        counts = report["rules"][rule_id]
        if counts["positive"] < 4 or counts["negative"] < 4:
            raise ValueError(f"{rule_id} requires at least four positive and four negative cases")
    for feature, minimum in REQUIRED_FEATURE_MINIMUMS.items():
        if report["features"].get(feature, 0) < minimum:
            raise ValueError(f"feature {feature!r} requires at least {minimum} cases")
    if report["languages"].get("en", 0) < 4 or report["languages"].get("ru", 0) < 4:
        raise ValueError("corpus requires at least four English and four Russian cases")
    by_id = {case["id"]: case for case in cases}
    for case in cases:
        for rule_id, control_id in case.get("dangerous_controls", {}).items():
            control = by_id.get(control_id)
            if control is None or control["coverage"][rule_id] != "negative":
                raise ValueError(f"{case['id']}: {rule_id} dangerous control is not negative")
            if "metamorphic-control" not in control["features"] or control["expected"]["verdict"] != "approve":
                raise ValueError(f"{case['id']}: dangerous control is not a clean metamorphic control")
            if not CONTROL_REMOVAL_FEATURES[rule_id].intersection(control["features"]):
                raise ValueError(
                    f"{case['id']}: {rule_id} control lacks a validated danger-removal predicate"
                )
            counterpart_id = case["metamorphic"]["counterpart"]
            relation = case["metamorphic"]["relation"]
            if control_id == counterpart_id:
                if relation != "predicate_flip":
                    raise ValueError(
                        f"{case['id']}: reciprocal dangerous control must be a predicate flip"
                    )
            else:
                counterpart = by_id.get(counterpart_id)
                if (
                    relation not in SAME_EXPECTED_RELATIONS
                    or counterpart is None
                    or counterpart["coverage"][rule_id] != "positive"
                ):
                    raise ValueError(
                        f"{case['id']}: secondary dangerous control is allowed only when the "
                        "reciprocal pair preserves the dangerous predicate"
                    )

    pairs: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        link = case["metamorphic"]
        other = by_id.get(link["counterpart"])
        if other is None:
            raise ValueError(f"{case['id']}: metamorphic counterpart is missing")
        reverse = other["metamorphic"]
        if reverse["counterpart"] != case["id"] or reverse["pair_id"] != link["pair_id"] or reverse["relation"] != link["relation"]:
            raise ValueError(f"{case['id']}: metamorphic link is not reciprocal")
        pairs.setdefault(link["pair_id"], []).append(case)

    completed_context: set[str] = set()
    for pair_id, members in pairs.items():
        if len(members) != 2:
            raise ValueError(f"{pair_id}: metamorphic pair must contain exactly two cases")
        roles = {member["metamorphic"]["role"] for member in members}
        relation = members[0]["metamorphic"]["relation"]
        if "source" not in roles or not roles.intersection({"variant", "control"}):
            raise ValueError(f"{pair_id}: invalid pair roles")
        if relation in SAME_EXPECTED_RELATIONS and _expected_signature(members[0]) != _expected_signature(members[1]):
            raise ValueError(f"{pair_id}: {relation} must preserve expected semantics")
        if relation == "translation" and members[0]["language"] == members[1]["language"]:
            raise ValueError(f"{pair_id}: translation must change language")
        if relation == "same_meaning_paraphrase" and any("paraphrase" not in member["features"] for member in members):
            raise ValueError(f"{pair_id}: paraphrase feature is missing")
        if relation == "injection_invariance":
            injected = sorted("prompt-injection" in member["features"] for member in members)
            if injected != [False, True]:
                raise ValueError(f"{pair_id}: injection pair needs one injected variant")
        if relation == "format_invariance":
            features = {feature for member in members for feature in member["features"]}
            if not {"yaml-adr", "markdown-adr"}.issubset(features):
                raise ValueError(f"{pair_id}: format pair must cover YAML and Markdown ADR")
        if relation == "predicate_flip":
            if not any({member["coverage"][rule] for member in members} == {"positive", "negative"} for rule in RULES):
                raise ValueError(f"{pair_id}: predicate flip lacks positive/negative coverage")
        if relation == "deterministic_predicate_flip":
            rules = [{item["rule_id"] for item in member["expected"]["findings"]} for member in members]
            if not any("SEAF-004" in item for item in rules) or not any(not item for item in rules):
                raise ValueError(f"{pair_id}: deterministic pair must flip SEAF-004 to clean")
        if relation == "context_completion":
            if {member["expected"]["status"] for member in members} != {"complete", "incomplete"}:
                raise ValueError(f"{pair_id}: context completion must flip status")
            incomplete = next(member for member in members if member["expected"]["status"] == "incomplete")
            control = next(member for member in members if member["expected"]["status"] == "complete")
            if "metamorphic-control" not in control["features"]:
                raise ValueError(f"{pair_id}: context completion lacks clean control")
            completed_context.update(item["kind"] for item in incomplete["expected"]["unresolved_context"])
    if completed_context != set(UNRESOLVED_KINDS):
        raise ValueError("each missing-context kind requires a completion control")
    compound_005_006 = [
        case for case in cases
        if case["coverage"]["PRIN-005"] == "positive" and case["coverage"]["PRIN-006"] == "positive"
    ]
    if not compound_005_006:
        raise ValueError("corpus needs a compound PRIN-005 + PRIN-006 case")
    for case in compound_005_006:
        controls = case["dangerous_controls"]
        if controls["PRIN-005"] != controls["PRIN-006"]:
            raise ValueError("compound PRIN-005 + PRIN-006 needs one paired near-miss control")


def load_cases(root: Path = ROOT) -> list[Mapping[str, Any]]:
    root = root.resolve()
    _validate_gate(root)
    corpus = _exact(
        _load_yaml(root / "corpus.yaml"),
        {
            "schema", "name", "version", "split", "data_policy", "purpose",
            "expected_policy", "network_policy", "workspace", "gate", "measurement",
            "rules", "cases",
        },
        "corpus",
    )
    if corpus["schema"] != CORPUS_SCHEMA or corpus["version"] != "2.0.0":
        raise ValueError("invalid development-v2 corpus schema/version")
    if corpus["split"] != "development" or corpus["purpose"] != "development-only":
        raise ValueError("development-v2 cannot contain or represent a holdout")
    if corpus["data_policy"] != "synthetic-public":
        raise ValueError("development-v2 must remain synthetic-public")
    expected_policy = _exact(
        corpus["expected_policy"],
        {"expected_visible", "lock_before_measurement", "mutation_after_measurement"},
        "corpus.expected_policy",
    )
    if expected_policy != {"expected_visible": True, "lock_before_measurement": True, "mutation_after_measurement": "forbidden"}:
        raise ValueError("expected/measurement policy was weakened")
    if _exact(corpus["network_policy"], {"model_calls", "api_calls"}, "network_policy") != {"model_calls": "forbidden", "api_calls": "forbidden"}:
        raise ValueError("validator/materializer must stay offline")
    workspace = _exact(corpus["workspace"], {"project_extension"}, "corpus.workspace")
    if (
        workspace["project_extension"] != "workspace/aga-extension.yaml"
        or corpus["gate"] != "gate.yaml"
        or corpus["measurement"] != "measurement-config.yaml"
    ):
        raise ValueError("workspace extension, gate, or measurement path is not canonical")
    if corpus["rules"] != list(RULES):
        raise ValueError("corpus rules must be exactly PRIN-004..007")
    entries = corpus["cases"]
    if not isinstance(entries, list) or not MIN_CASES <= len(entries) <= MAX_CASES:
        raise ValueError(f"corpus must contain {MIN_CASES}..{MAX_CASES} cases")
    cases: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(entries):
        entry = _exact(raw_entry, {"id", "split", "file"}, f"corpus.cases[{index}]")
        case_id = _text(entry["id"], f"corpus.cases[{index}].id", limit=100)
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        if entry["split"] != "development":
            raise ValueError(f"{case_id}: only development entries are allowed")
        relative = _safe_path(entry["file"], f"{case_id}.file")
        if not relative.startswith("cases/"):
            raise ValueError(f"{case_id}: case must live below cases/")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(f"{case_id}: case file escapes corpus root") from error
        if path.name != f"{case_id}.yaml":
            raise ValueError(f"{case_id}: filename must match id")
        cases.append(_validate_case(_load_yaml(path), expected_id=case_id, expected_split="development"))
    _validate_balance_and_pairs(cases)
    return cases


def corpus_files(root: Path = ROOT) -> tuple[Path, ...]:
    corpus = _load_yaml(root / "corpus.yaml")
    if not isinstance(corpus, Mapping) or not isinstance(corpus.get("cases"), list):
        raise ValueError("invalid corpus manifest")
    paths = [
        root / "corpus.yaml",
        root / "gate.yaml",
        root / "measurement-config.yaml",
        root / "workspace/aga-extension.yaml",
    ]
    paths.extend(root / entry["file"] for entry in corpus["cases"])
    return tuple(paths)


def _digest_files(paths: Iterable[Path], root: Path, domain: bytes) -> str:
    digest = hashlib.sha256(domain)
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big")); digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big")); digest.update(payload)
    return digest.hexdigest()


def corpus_hash(root: Path = ROOT) -> str:
    return _digest_files(corpus_files(root), root, b"aga.synthetic-development-corpus/v2\0")


def ground_truth_hash(cases: Iterable[Mapping[str, Any]]) -> str:
    rows = [
        {
            "id": case["id"], "coverage": case["coverage"],
            "dangerous_controls": case.get("dangerous_controls", {}),
            "metamorphic": case["metamorphic"], "expected": case["expected"],
        }
        for case in sorted(cases, key=lambda item: item["id"])
    ]
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b"aga.synthetic-development-ground-truth/v2\0" + payload).hexdigest()


def file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"locked implementation file is missing: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _measurement_config(root: Path = ROOT) -> Mapping[str, Any]:
    config = _exact(
        _load_yaml(root / "measurement-config.yaml"),
        {
            "schema", "runtime", "provider_id", "model_id", "prompt_path",
            "live_runner_path", "reviewer_skill_path", "execution_bundle_paths",
            "selection_id", "timeout_per_case_seconds", "required_repeated_runs",
            "data_classification", "state_cache_policy", "output_policy",
        },
        "measurement config",
    )
    if config["schema"] != MEASUREMENT_CONFIG_SCHEMA:
        raise ValueError("invalid measurement config schema")
    runtime = _exact(
        config["runtime"], {"id", "version", "source_commit"},
        "measurement config runtime",
    )
    if runtime["id"] != "ouroboros" or runtime["version"] != "6.64.1":
        raise ValueError("measurement runtime ID/version does not match the approved pin")
    if not isinstance(runtime["source_commit"], str) or COMMIT_RE.fullmatch(runtime["source_commit"]) is None:
        raise ValueError("measurement runtime source commit must be a full SHA-1")
    _text(config["provider_id"], "measurement provider_id", limit=100)
    _text(config["model_id"], "measurement model_id", limit=200)
    if config["provider_id"] != "openrouter":
        raise ValueError("measurement provider must be OpenRouter")
    if config["selection_id"] != "synthetic-public-semantic-development-v2/development":
        raise ValueError("measurement selection ID is not canonical")
    timeout = config["timeout_per_case_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or float(timeout) != 900.0:
        raise ValueError("measurement timeout must remain exactly 900 seconds per case")
    if config["required_repeated_runs"] != 5:
        raise ValueError("measurement config must require five repeated captures")
    if config["data_classification"] != "synthetic-public":
        raise ValueError("measurement data classification was weakened")
    if config["state_cache_policy"] != "isolate-by-series-repeat-capture":
        raise ValueError("measurement state cache policy was weakened")
    if config["output_policy"] != "create-new":
        raise ValueError("measurement output policy must forbid overwrite")
    for field, suffix in (("prompt_path", ".txt"), ("live_runner_path", ".py")):
        value = _text(config[field], f"measurement {field}", limit=240)
        candidate = PurePosixPath(value)
        if (
            candidate.is_absolute()
            or candidate.as_posix() != value
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or candidate.suffix != suffix
        ):
            raise ValueError(f"measurement {field} is not a safe canonical repository path")
    if config["prompt_path"] != "aga-skill/prompts/ouroboros-orchestration-v1.1.0.txt":
        raise ValueError("measurement prompt path does not match the executed prompt")
    if config["live_runner_path"] != "scripts/run_ouroboros_live_review.py":
        raise ValueError("measurement live runner path does not match the executed runner")
    if config["reviewer_skill_path"] != "ouroboros-skill/aga-review-v1.1":
        raise ValueError("measurement reviewer skill path does not match the profile sync source")
    if config["execution_bundle_paths"] != [
        "aga-skill", "scripts", "ouroboros-skill/aga-review-v1.1"
    ]:
        raise ValueError("measurement execution bundle paths are not canonical")
    return config


def measurement_selection(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    case_ids = [str(case["id"]) for case in cases]
    if len(case_ids) != 48 or len(case_ids) != len(set(case_ids)):
        raise ValueError("measurement selection must contain exactly 48 unique cases")
    selection_id = "synthetic-public-semantic-development-v2/development"
    payload = {"selection_id": selection_id, "case_ids": case_ids}
    digest = hashlib.sha256(
        b"aga.synthetic-development-selection/v2\0"
        + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**payload, "selection_sha256": digest}


def _source_tree_sha256(repository_root: Path, relative_paths: Sequence[str]) -> str:
    files: dict[str, Path] = {}
    for relative in relative_paths:
        candidate = PurePosixPath(relative)
        if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
            raise ValueError("measurement execution bundle contains an unsafe path")
        target = repository_root / relative
        if target.is_symlink() or not target.exists():
            raise ValueError("measurement execution bundle path is missing or linked")
        members = [target] if target.is_file() else list(target.rglob("*"))
        for member in members:
            if any(part in {".git", "__pycache__", ".pytest_cache"} for part in member.parts):
                continue
            if member.is_symlink():
                raise ValueError("measurement execution bundle contains a symlink")
            if not member.is_file() or member.suffix in {".pyc", ".pyo"}:
                continue
            key = member.relative_to(repository_root).as_posix()
            if key.startswith("aga-skill/build/") or key in {
                "aga-skill/logs/reviews.jsonl",
                "aga-skill/logs/evolution.jsonl",
            }:
                continue
            files[key] = member
    if not files:
        raise ValueError("measurement execution bundle is empty")
    digest = hashlib.sha256(b"aga.synthetic-development-execution-bundle/v2\0")
    for relative, path in sorted(files.items()):
        raw_path = relative.encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(raw_path).to_bytes(8, "big")); digest.update(raw_path)
        digest.update(len(payload).to_bytes(8, "big")); digest.update(payload)
    return digest.hexdigest()


def active_measurement_identity(
    root: Path = ROOT, *, cases: Sequence[Mapping[str, Any]] | None = None
) -> dict[str, str]:
    config = _measurement_config(root)
    selected = measurement_selection(list(cases) if cases is not None else load_cases(root))
    repository_root = root.resolve().parents[1]
    prompt = repository_root / str(config["prompt_path"])
    live_runner = repository_root / str(config["live_runner_path"])
    reviewer_skill = repository_root / str(config["reviewer_skill_path"])
    prompt_sha256 = file_sha256(prompt)
    live_runner_sha256 = file_sha256(live_runner)
    reviewer_skill_sha256 = _source_tree_sha256(
        repository_root, [str(config["reviewer_skill_path"])]
    )
    execution_bundle_sha256 = _source_tree_sha256(
        repository_root, list(config["execution_bundle_paths"])
    )
    material = {
        "schema": MEASUREMENT_CONFIG_SCHEMA,
        "config": config,
        "prompt_sha256": prompt_sha256,
        "live_runner_sha256": live_runner_sha256,
        "reviewer_skill_sha256": reviewer_skill_sha256,
        "execution_bundle_sha256": execution_bundle_sha256,
        "selection_sha256": selected["selection_sha256"],
    }
    config_sha256 = hashlib.sha256(
        b"aga.synthetic-development-active-config/v2\0"
        + json.dumps(
            material, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "runtime_id": str(config["runtime"]["id"]),
        "runtime_version": str(config["runtime"]["version"]),
        "runtime_source_commit": str(config["runtime"]["source_commit"]),
        "provider_id": str(config["provider_id"]),
        "model_id": str(config["model_id"]),
        "prompt_sha256": prompt_sha256,
        "config_sha256": config_sha256,
        "live_runner_sha256": live_runner_sha256,
        "reviewer_skill_sha256": reviewer_skill_sha256,
        "execution_bundle_sha256": execution_bundle_sha256,
        "selection_id": str(config["selection_id"]),
        "selection_sha256": selected["selection_sha256"],
    }


def build_lock(root: Path = ROOT, *, locked_at: str = "2026-07-19T00:00:00Z") -> dict[str, Any]:
    if UTC_RE.fullmatch(locked_at) is None:
        raise ValueError("locked_at must use YYYY-MM-DDTHH:MM:SSZ")
    cases = load_cases(root)
    return {
        "schema": LOCK_SCHEMA,
        "locked_at": locked_at,
        "development_only": True,
        "synthetic_public": True,
        "case_count": len(cases),
        "split_counts": {"development": len(cases)},
        "coverage": coverage_report(cases)["rules"],
        "corpus_sha256": corpus_hash(root),
        "ground_truth_sha256": ground_truth_hash(cases),
        "validator_sha256": file_sha256(root / "corpus_tool.py"),
        "scorer_sha256": file_sha256(root / "runner.py"),
        "paid_runner_sha256": file_sha256(root / "run_paid_evaluation.py"),
        "ground_truth_locked": True,
        "expected_mutation_after_measurement_forbidden": True,
        "series_freeze": {
            "state": "pre_measurement",
            "series_id": None,
            "frozen_at": None,
            "required_repeated_runs": 5,
            "measurement_identity": {
                "runtime_id": None,
                "runtime_version": None,
                "runtime_source_commit": None,
                "provider_id": None,
                "model_id": None,
                "prompt_sha256": None,
                "config_sha256": None,
                "live_runner_sha256": None,
                "reviewer_skill_sha256": None,
                "execution_bundle_sha256": None,
                "selection_id": None,
                "selection_sha256": None,
            },
            "capture_attestation": {
                "scheme": "hmac-sha256",
                "key_id": None,
                "key_sha256": None,
            },
            "mutation_policy": {
                "corpus": "forbidden_after_start",
                "ground_truth": "forbidden_after_start",
                "validator": "forbidden_after_start",
                "scorer": "forbidden_after_start",
                "paid_runner": "forbidden_after_start",
                "prompt": "forbidden_after_start",
                "config": "forbidden_after_start",
                "model": "forbidden_after_start",
                "selection": "forbidden_after_start",
            },
        },
        "independent_human_review": {
            "required": True, "status": "pending", "reviewer": None, "reviewed_at": None,
        },
    }


def verify_lock(
    root: Path = ROOT,
    *,
    require_human_review: bool = False,
    require_measurement_ready: bool = False,
) -> dict[str, Any]:
    cases = load_cases(root)
    required = {
        "schema", "locked_at", "development_only", "synthetic_public", "case_count",
        "split_counts", "coverage", "corpus_sha256", "ground_truth_sha256",
        "validator_sha256", "scorer_sha256", "paid_runner_sha256", "ground_truth_locked",
        "expected_mutation_after_measurement_forbidden", "series_freeze", "independent_human_review",
    }
    lock = _exact(_load_json(root / "corpus.lock.json"), required, "corpus lock")
    if lock["schema"] != LOCK_SCHEMA or UTC_RE.fullmatch(str(lock["locked_at"])) is None:
        raise ValueError("invalid corpus lock schema/timestamp")
    for field in (
        "development_only", "synthetic_public", "ground_truth_locked",
        "expected_mutation_after_measurement_forbidden",
    ):
        if lock[field] is not True:
            raise ValueError(f"lock field {field} was weakened")
    if lock["case_count"] != len(cases) or lock["split_counts"] != {"development": len(cases)}:
        raise ValueError("lock case/split count mismatch")
    if lock["coverage"] != coverage_report(cases)["rules"]:
        raise ValueError("lock coverage mismatch")
    actual = {
        "corpus_sha256": corpus_hash(root),
        "ground_truth_sha256": ground_truth_hash(cases),
        "validator_sha256": file_sha256(root / "corpus_tool.py"),
        "scorer_sha256": file_sha256(root / "runner.py"),
        "paid_runner_sha256": file_sha256(root / "run_paid_evaluation.py"),
    }
    for field, value in actual.items():
        if not isinstance(lock[field], str) or SHA256_RE.fullmatch(lock[field]) is None:
            raise ValueError(f"{field} must be a lowercase SHA-256")
        if lock[field] != value:
            raise ValueError(f"{field} lock mismatch")

    review = _exact(
        lock["independent_human_review"], {"required", "status", "reviewer", "reviewed_at"},
        "independent_human_review",
    )
    if review["required"] is not True or review["status"] not in {"pending", "accepted"}:
        raise ValueError("independent human review metadata is invalid")
    if review["status"] == "pending":
        if review["reviewer"] is not None or review["reviewed_at"] is not None:
            raise ValueError("pending review cannot claim reviewer evidence")
    else:
        _text(review["reviewer"], "independent_human_review.reviewer", limit=200)
        if UTC_RE.fullmatch(str(review["reviewed_at"])) is None:
            raise ValueError("accepted review requires UTC timestamp")

    freeze = _exact(
        lock["series_freeze"],
        {
            "state", "series_id", "frozen_at", "required_repeated_runs",
            "measurement_identity", "capture_attestation", "mutation_policy",
        },
        "series_freeze",
    )
    policy = _exact(
        freeze["mutation_policy"],
        {
            "corpus", "ground_truth", "validator", "scorer", "paid_runner",
            "prompt", "config", "model", "selection",
        },
        "series_freeze.mutation_policy",
    )
    identity = _exact(
        freeze["measurement_identity"],
        {
            "runtime_id", "runtime_version", "runtime_source_commit", "provider_id",
            "model_id", "prompt_sha256", "config_sha256", "live_runner_sha256",
            "reviewer_skill_sha256", "execution_bundle_sha256", "selection_id",
            "selection_sha256",
        },
        "series_freeze.measurement_identity",
    )
    attestation = _exact(
        freeze["capture_attestation"], {"scheme", "key_id", "key_sha256"},
        "series_freeze.capture_attestation",
    )
    if attestation["scheme"] != "hmac-sha256":
        raise ValueError("series capture attestation scheme is invalid")
    if set(policy.values()) != {"forbidden_after_start"} or freeze["required_repeated_runs"] != 5:
        raise ValueError("series freeze mutation/repetition policy was weakened")
    if freeze["state"] == "pre_measurement":
        if (
            freeze["series_id"] is not None
            or freeze["frozen_at"] is not None
            or any(value is not None for value in identity.values())
            or attestation["key_id"] is not None
            or attestation["key_sha256"] is not None
        ):
            raise ValueError("pre-measurement series cannot claim freeze evidence")
    elif freeze["state"] == "frozen":
        series_id = _text(freeze["series_id"], "series_freeze.series_id", limit=128)
        if SERIES_ID_RE.fullmatch(series_id) is None:
            raise ValueError("frozen series ID is invalid")
        if UTC_RE.fullmatch(str(freeze["frozen_at"])) is None:
            raise ValueError("frozen series requires UTC timestamp")
        active_identity = active_measurement_identity(root, cases=cases)
        if identity != active_identity:
            raise ValueError("frozen measurement identity does not match active model/prompt/config/selection")
        key_id = _text(attestation["key_id"], "capture_attestation.key_id", limit=128)
        if SERIES_ID_RE.fullmatch(key_id) is None:
            raise ValueError("capture attestation key ID is invalid")
        if (
            not isinstance(attestation["key_sha256"], str)
            or SHA256_RE.fullmatch(attestation["key_sha256"]) is None
        ):
            raise ValueError("capture attestation key hash must be a SHA-256")
    else:
        raise ValueError("invalid series freeze state")
    if require_human_review and review["status"] != "accepted":
        raise ValueError("independent human ground-truth review is still pending")
    if require_measurement_ready:
        if review["status"] != "accepted":
            raise ValueError("measurement blocked: independent human review is pending")
        if freeze["state"] != "frozen":
            raise ValueError("measurement blocked: development series is not frozen")
    return dict(lock)


def _isolated_git_environment(repo: Path, dates: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    controlled_home = repo.parent / ".git-home"
    controlled_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment.update(
        {
            "HOME": str(controlled_home), "XDG_CONFIG_HOME": str(controlled_home / ".config"),
            "LC_ALL": "C", "TZ": "UTC", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "AGA Development Evaluator",
            "GIT_AUTHOR_EMAIL": "aga-development@example.invalid",
            "GIT_COMMITTER_NAME": "AGA Development Evaluator",
            "GIT_COMMITTER_EMAIL": "aga-development@example.invalid",
        }
    )
    environment.update(dates or {})
    return environment


def _git(repo: Path, *arguments: str, dates: Mapping[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", "-c", f"core.hooksPath={os.devnull}", "-c", "commit.gpgSign=false", *arguments],
        cwd=repo, check=True, capture_output=True, text=True, timeout=30,
        env=_isolated_git_environment(repo, dates),
    )
    return completed.stdout.strip()


def _write_native_documents(repo: Path, documents: Mapping[str, Any]) -> None:
    for relative, document in documents.items():
        target = repo / _safe_path(relative, "materialized artifact")
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith(".md"):
            target.write_text(str(document), encoding="utf-8")
        else:
            target.write_text(
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )


def _write_manifest(repo: Path, documents: Mapping[str, Any]) -> None:
    imports = ["workspace/aga-extension.yaml"] + sorted(
        path for path in documents if path.endswith((".yaml", ".yml"))
    )
    manifest = {
        "$package": {
            "aga-development-v2": {
                "name": "AGA synthetic development v2 case", "vendor": "AGA hackathon team",
                "description": "Isolated SEAF-native synthetic-public development workspace",
                "version": "2.0.0",
            }
        },
        "aga": {
            "schema": "seaf-core/v1.4.0", "extensions": ["aga.project/v1"],
            "data_classification": "synthetic-public",
        },
        "imports": imports,
    }
    (repo / "dochub.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _stage_trusted_dependency_gitlinks(repo: Path) -> None:
    for relative, commit in TRUSTED_DEPENDENCY_GITLINKS.items():
        (repo / relative).mkdir(mode=0o755, parents=True, exist_ok=True)
        _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit},{relative}")


def _native_counts(repo: Path, *, allow_incomplete: bool) -> dict[str, Any]:
    skill_root = REPOSITORY_ROOT / "aga-skill"
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))
    try:
        from tools.seaf_native import load_seaf_native  # pylint: disable=import-outside-toplevel

        snapshot = load_seaf_native(repo)
    except Exception as error:
        if not allow_incomplete:
            raise ValueError("complete case is not a valid SEAF-native workspace") from error
        return {"status": "incomplete", "error_type": type(error).__name__}
    return {
        "status": "ready", "systems": len(snapshot.systems),
        "integrations": len(snapshot.integrations), "adrs": len(snapshot.adrs),
        "diagrams": len(snapshot.diagrams),
    }


def materialize_case(case_id: str, destination: Path, *, root: Path = ROOT) -> dict[str, Any]:
    if not isinstance(destination, Path):
        raise TypeError("materialization destination must be pathlib.Path")
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"materialization destination already exists: {destination}")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("materialization parent must be an existing real directory")
    lock = verify_lock(root)
    cases = {case["id"]: case for case in load_cases(root)}
    if case_id not in cases:
        raise ValueError(f"unknown development-v2 case: {case_id}")
    case = cases[case_id]
    destination.mkdir(mode=0o755)
    try:
        _git(destination, "init", "--initial-branch=main", "--object-format=sha1")
        base_documents = native_state(case, "base")
        _write_native_documents(destination, base_documents)
        extension = root / "workspace/aga-extension.yaml"
        extension_target = destination / "workspace/aga-extension.yaml"
        extension_target.parent.mkdir(parents=True, exist_ok=True)
        extension_target.write_bytes(extension.read_bytes())
        _write_manifest(destination, base_documents)
        _git(destination, "add", ".")
        _stage_trusted_dependency_gitlinks(destination)
        base_dates = {"GIT_AUTHOR_DATE": "2026-07-19T00:00:00Z", "GIT_COMMITTER_DATE": "2026-07-19T00:00:00Z"}
        _git(destination, "commit", "-m", f"{case_id} base", dates=base_dates)
        base = _git(destination, "rev-parse", "HEAD")
        base_entities = _native_counts(destination, allow_incomplete=case["expected"]["status"] == "incomplete")

        head_documents = native_state(case, "head")
        _write_native_documents(destination, head_documents)
        _write_manifest(destination, head_documents)
        _git(destination, "add", ".")
        _stage_trusted_dependency_gitlinks(destination)
        head_dates = {"GIT_AUTHOR_DATE": "2026-07-19T00:01:00Z", "GIT_COMMITTER_DATE": "2026-07-19T00:01:00Z"}
        _git(destination, "commit", "-m", f"{case_id} head", dates=head_dates)
        head = _git(destination, "rev-parse", "HEAD")
        head_entities = _native_counts(destination, allow_incomplete=case["expected"]["status"] == "incomplete")
        changed_files = _git(destination, "diff", "--name-only", base, head).splitlines()
        if base == head or not changed_files or _git(destination, "status", "--porcelain"):
            raise ValueError(f"{case_id}: materialized Git revisions are not clean and distinct")
        expected_changed = set(case["change"]["head"]["files"])
        if not expected_changed.issubset(changed_files):
            raise ValueError(f"{case_id}: materialized diff misses changed case artifacts")
    except Exception:
        shutil.rmtree(destination)
        raise
    identity = json.dumps(
        {"case_id": case_id, "base": base, "head": head, "changed_files": changed_files},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": MATERIALIZATION_SCHEMA, "case_id": case_id, "repository": str(destination),
        "base": base, "head": head, "changed_files": changed_files,
        "base_entities": base_entities, "head_entities": head_entities,
        "corpus_sha256": lock["corpus_sha256"], "sha256": hashlib.sha256(identity).hexdigest(),
    }


def materialize_all(destination: Path, *, root: Path = ROOT) -> dict[str, Any]:
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"materialization destination already exists: {destination}")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("materialization parent must be an existing real directory")
    verify_lock(root)
    cases = load_cases(root)
    destination.mkdir(mode=0o755)
    results: list[dict[str, Any]] = []
    try:
        for case in cases:
            results.append(materialize_case(case["id"], destination / case["id"], root=root))
        index = {
            "schema": MATERIALIZATION_SCHEMA, "case_count": len(results),
            "cases": [
                {"id": item["case_id"], "base": item["base"], "head": item["head"], "sha256": item["sha256"]}
                for item in results
            ],
        }
        (destination / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(destination)
        raise
    digest = hashlib.sha256(
        json.dumps(index, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"case_count": len(results), "destination": str(destination), "sha256": digest}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    validate = actions.add_parser("validate")
    validate.add_argument("--require-human-review", action="store_true")
    validate.add_argument("--require-measurement-ready", action="store_true")
    actions.add_parser("hash")
    actions.add_parser("print-lock")
    materialize = actions.add_parser("materialize")
    choice = materialize.add_mutually_exclusive_group(required=True)
    choice.add_argument("--case")
    choice.add_argument("--all", action="store_true")
    materialize.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "validate":
            lock = verify_lock(
                ROOT, require_human_review=args.require_human_review,
                require_measurement_ready=args.require_measurement_ready,
            )
            cases = load_cases(ROOT)
            result: Mapping[str, Any] = {
                "status": "PASS", "case_count": len(cases), "coverage": coverage_report(cases),
                "corpus_sha256": lock["corpus_sha256"],
                "ground_truth_sha256": lock["ground_truth_sha256"],
                "human_review_status": lock["independent_human_review"]["status"],
                "series_state": lock["series_freeze"]["state"],
            }
        elif args.action == "hash":
            cases = load_cases(ROOT)
            result = {"corpus_sha256": corpus_hash(ROOT), "ground_truth_sha256": ground_truth_hash(cases)}
        elif args.action == "print-lock":
            result = build_lock(ROOT)
        elif args.all:
            result = materialize_all(args.output, root=ROOT)
        else:
            result = materialize_case(args.case, args.output, root=ROOT)
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as error:
        print(f"development-v2: FAIL: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
