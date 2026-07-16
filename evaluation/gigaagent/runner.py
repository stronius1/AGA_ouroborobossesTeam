#!/usr/bin/env python3
"""Freeze, materialize and score the independent GigaAgent basket.

The runner is deliberately transport-free: it never calls a model or an API.
It accepts only an already captured, sanitized JSON response bundle, verifies
that every response belongs to the frozen materialized Git revisions, and
then produces deterministic per-case and aggregate fixture scores. Real-mode
scoring fails closed until an official capture contract and verified adapter
are integrated; caller-supplied identity labels are not provenance.
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
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import yaml


ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parents[1]
CORPUS = ROOT / "corpus.yaml"
LOCK = ROOT / "corpus.lock.json"
GATE = ROOT / "gate.yaml"
REAL_RESULTS = ROOT / "results.json"
CASE_SCHEMA = "aga.gigaagent-case/v1"
BUNDLE_SCHEMA = "aga.gigaagent-response-bundle/v1"
RESULTS_SCHEMA = "aga.gigaagent-results/v2"
TRUSTED_OUROBOROS_RESULTS_SCHEMA = RESULTS_SCHEMA
TRUSTED_OUROBOROS_VERSION = "6.64.1"
TRUSTED_OUROBOROS_PROVIDER = "openrouter"
TRUSTED_OUROBOROS_MODEL = "deepseek/deepseek-v4-pro"
ALLOWED_RULES = frozenset({"PRIN-004", "PRIN-005", "PRIN-006", "PRIN-007"})
RULE_SOURCE_REFS = {
    "PRIN-004": "aga-skill/rules/principles.yaml#/rules/3",
    "PRIN-005": "aga-skill/rules/principles.yaml#/rules/4",
    "PRIN-006": "aga-skill/rules/principles.yaml#/rules/5",
    "PRIN-007": "aga-skill/rules/principles.yaml#/rules/6",
}
RULE_SEVERITIES = {
    "PRIN-004": "major",
    "PRIN-005": "major",
    "PRIN-006": "blocker",
    "PRIN-007": "major",
}
SEVERITIES = frozenset({"blocker", "major", "minor"})
STATUSES = frozenset({"complete", "incomplete", "error"})
VERDICTS = frozenset(
    {"approve", "approve_with_warnings", "request_changes_escalate", "incomplete"}
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CAPTURED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_RAW_RESPONSE_BYTES = 256_000
MAX_TEXT_CHARS = 16_000
MAX_FINDINGS = 100
FORBIDDEN_RAW_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "developer_prompt",
        "messages",
        "password",
        "prompt",
        "raw_prompt",
        "secret",
        "system_prompt",
        "token",
        "access_token",
        "refresh_token",
    }
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{12,}"),
)
REAL_SCORING_UNSUPPORTED = (
    "real bundle scoring is unsupported/unconfigured: this workspace has no "
    "verified official GigaAgent capture contract or adapter; runtime/model "
    "labels and normalized output cannot establish official provenance"
)
_ALLOWED_GIT_ENV_OVERRIDES = frozenset(
    {"GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"}
)


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _require_exact_keys(value: Any, fields: set[str], context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    actual = set(value)
    missing = sorted(fields - actual)
    extra = sorted(actual - fields)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unknown {extra}")
        raise ValueError(f"{context} has invalid fields: {'; '.join(details)}")
    return value


def _require_text(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    if len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"{context} exceeds {MAX_TEXT_CHARS} characters")
    if not allow_empty and not value.strip():
        raise ValueError(f"{context} must not be empty")
    return value


def _safe_relative_yaml_path(value: Any, context: str) -> str:
    text = _require_text(value, context)
    portable = text.replace("\\", "/")
    path = PurePosixPath(portable)
    if path.is_absolute() or portable != path.as_posix():
        raise ValueError(f"{context} must be a canonical relative POSIX path")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{context} contains an unsafe path segment")
    if path.suffix not in {".yaml", ".yml"}:
        raise ValueError(f"{context} must identify a YAML document")
    if portable == "dochub.yaml":
        raise ValueError(f"{context}: dochub.yaml is generated by the materializer")
    return portable


def _state_documents(case: Mapping[str, Any], phase: str) -> dict[str, Any]:
    base = dict(case["change"]["base"]["documents"])
    if phase == "base":
        return base
    if phase != "head":
        raise ValueError(f"unknown phase {phase!r}")
    base.update(case["change"]["head"]["documents"])
    return base


def _validate_component(entity_id: Any, item: Any, context: str) -> None:
    _require_text(entity_id, f"{context}.id")
    if not isinstance(item, Mapping):
        raise ValueError(f"{context}.{entity_id} must be an object")
    required = {"title", "entity", "owner", "criticality", "target_status"}
    missing = sorted(required - set(item))
    if missing:
        raise ValueError(f"{context}.{entity_id} misses aga.project/v1 fields {missing}")
    for field in ("title", "entity", "owner"):
        _require_text(item[field], f"{context}.{entity_id}.{field}")
    if item["criticality"] not in {"low", "medium", "high", "mission_critical"}:
        raise ValueError(f"{context}.{entity_id}.criticality is invalid")
    if item["target_status"] not in {"strategic", "tactical", "tolerate", "eliminate"}:
        raise ValueError(f"{context}.{entity_id}.target_status is invalid")


def _validate_integration(entity_id: Any, item: Any, context: str) -> None:
    _require_text(entity_id, f"{context}.id")
    if not isinstance(item, Mapping):
        raise ValueError(f"{context}.{entity_id} must be an object")
    required = {"title", "description", "from", "to"}
    missing = sorted(required - set(item))
    if missing:
        raise ValueError(f"{context}.{entity_id} misses SEAF integration fields {missing}")
    for field in required:
        _require_text(item[field], f"{context}.{entity_id}.{field}")


def _validate_adr(entity_id: Any, item: Any, context: str) -> None:
    _require_text(entity_id, f"{context}.id")
    if not isinstance(item, Mapping):
        raise ValueError(f"{context}.{entity_id} must be an object")
    required = {"title", "moment", "status", "issue", "decision", "context", "consequences"}
    missing = sorted(required - set(item))
    if missing:
        raise ValueError(f"{context}.{entity_id} misses SEAF ADR fields {missing}")
    for field in ("title", "moment", "status", "issue", "decision"):
        _require_text(item[field], f"{context}.{entity_id}.{field}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["moment"]):
        raise ValueError(f"{context}.{entity_id}.moment must use YYYY-MM-DD")
    if item["status"] not in {"proposed", "accepted", "deprecated", "superseded"}:
        raise ValueError(f"{context}.{entity_id}.status is invalid")
    for field in ("context", "consequences"):
        if not isinstance(item[field], (str, list)):
            raise ValueError(f"{context}.{entity_id}.{field} must be text or a statement list")


def _validate_documents(case_id: str, phase: str, documents: Any) -> dict[str, Any]:
    if not isinstance(documents, Mapping) or not documents:
        raise ValueError(f"{case_id}.{phase}.documents must be a non-empty object")
    validated: dict[str, Any] = {}
    for raw_path, data in documents.items():
        relative = _safe_relative_yaml_path(raw_path, f"{case_id}.{phase}.documents path")
        if not isinstance(data, Mapping):
            raise ValueError(f"{case_id}.{phase}.{relative} must contain a YAML object")
        validated[relative] = data
        sections = {
            "components": _validate_component,
            "seaf.app.integrations": _validate_integration,
            "seaf.change.adr": _validate_adr,
        }
        for section, validator in sections.items():
            if section not in data:
                continue
            entries = data[section]
            if not isinstance(entries, Mapping):
                raise ValueError(f"{case_id}.{phase}.{relative}.{section} must be an object")
            for entity_id, item in entries.items():
                validator(entity_id, item, f"{case_id}.{phase}.{relative}.{section}")
    return validated


def ground_truth_hash(cases: Iterable[Mapping[str, Any]]) -> str:
    rows = [
        {
            "id": case["id"],
            "split": case["split"],
            "labels": case["labels"],
            "expected": case["expected"],
        }
        for case in sorted(cases, key=lambda item: item["id"])
    ]
    payload = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(b"aga-gigaagent-ground-truth/v1\0" + payload).hexdigest()


def _validate_expected(case: Mapping[str, Any], head_documents: Mapping[str, Any]) -> None:
    case_id = case["id"]
    expected = _require_exact_keys(
        case.get("expected"), {"status", "verdict", "findings"}, f"{case_id}.expected"
    )
    if expected["status"] not in {"complete", "incomplete"}:
        raise ValueError(f"{case_id}.expected.status is invalid")
    if expected["verdict"] not in {"approve", "request_changes_escalate", "incomplete"}:
        raise ValueError(f"{case_id}.expected.verdict is invalid")
    findings = expected["findings"]
    if not isinstance(findings, list):
        raise ValueError(f"{case_id}.expected.findings must be a list")
    for index, finding in enumerate(findings):
        finding = _require_exact_keys(
            finding,
            {"rule_id", "severity", "artifact", "location", "evidence_contains"},
            f"{case_id}.expected.findings[{index}]",
        )
        if finding["rule_id"] not in ALLOWED_RULES:
            raise ValueError(f"{case_id}: expected rule is outside PRIN-004..007")
        if finding["severity"] not in SEVERITIES:
            raise ValueError(f"{case_id}: expected severity is invalid")
        artifact = _safe_relative_yaml_path(
            finding["artifact"], f"{case_id}.expected.findings[{index}].artifact"
        )
        if artifact not in head_documents:
            raise ValueError(f"{case_id}: expected artifact is absent from head: {artifact}")
        location = _require_text(
            finding["location"], f"{case_id}.expected.findings[{index}].location"
        )
        if not _pointer_resolves(head_documents[artifact], location):
            raise ValueError(
                f"{case_id}: expected location does not resolve in {artifact}: {location}"
            )
        _require_text(
            finding["evidence_contains"],
            f"{case_id}.expected.findings[{index}].evidence_contains",
        )
    if expected["status"] == "incomplete":
        if expected["verdict"] != "incomplete" or findings:
            raise ValueError(f"{case_id}: incomplete ground truth must fail closed without findings")
    elif findings and expected["verdict"] != "request_changes_escalate":
        raise ValueError(f"{case_id}: findings require request_changes_escalate")
    elif not findings and expected["verdict"] != "approve":
        raise ValueError(f"{case_id}: a complete clean case must approve")


def _validate_balance(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    split_counts = Counter(case["split"] for case in cases)
    if split_counts != Counter({"development": 8, "holdout": 8}):
        raise ValueError(f"corpus requires an 8/8 development/holdout split, got {dict(split_counts)}")
    labels = {case["id"]: set(case["labels"]) for case in cases}
    for rule_id in sorted(ALLOWED_RULES):
        positives = [
            case["id"] for case in cases if rule_id in labels[case["id"]] and "positive" in labels[case["id"]]
        ]
        negatives = [
            case["id"] for case in cases if rule_id in labels[case["id"]] and "negative" in labels[case["id"]]
        ]
        if not positives or not negatives:
            raise ValueError(f"{rule_id} requires positive and negative cases")
    required_groups = {
        "clean": lambda value: "clean" in value,
        "blocker": lambda value: "blocker" in value,
        "major": lambda value: "major" in value,
        "near_miss": lambda value: bool({"near-miss", "misleading-near-miss"} & value),
        "prompt_injection": lambda value: "prompt-injection" in value,
        "missing_context": lambda value: "missing-context" in value and "incomplete" in value,
        "multi_finding": lambda value: "multi-finding" in value,
    }
    coverage = {
        name: sorted(case_id for case_id, value in labels.items() if predicate(value))
        for name, predicate in required_groups.items()
    }
    missing = sorted(name for name, case_ids in coverage.items() if not case_ids)
    if missing:
        raise ValueError(f"corpus balance groups are missing: {missing}")
    return {"split_counts": dict(sorted(split_counts.items())), "coverage": coverage}


def corpus_files() -> tuple[Path, ...]:
    corpus = load_yaml(CORPUS)
    if not isinstance(corpus, dict) or corpus.get("schema") != "aga.gigaagent-corpus/v1":
        raise ValueError("invalid corpus schema")
    entries = corpus.get("cases")
    if not isinstance(entries, list) or len(entries) != 16:
        raise ValueError("corpus requires exactly 16 frozen cases")
    workspace = corpus.get("workspace")
    if not isinstance(workspace, Mapping) or set(workspace) != {"project_extension"}:
        raise ValueError("corpus requires exactly one frozen project extension")
    extension_path = (ROOT / workspace["project_extension"]).resolve()
    extension_path.relative_to(ROOT.resolve())
    if not extension_path.is_file() or extension_path.suffix not in {".yaml", ".yml"}:
        raise ValueError("frozen project extension is missing")
    extension = load_yaml(extension_path)
    if (
        not isinstance(extension, Mapping)
        or not isinstance(extension.get("$package"), Mapping)
        or extension["$package"].get("aga-project", {}).get("version") != "1.0.0"
    ):
        raise ValueError("frozen project extension must provide aga-project 1.0.0")
    paths = [CORPUS, GATE, extension_path]
    cases: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"id", "split", "file"}:
            raise ValueError("each corpus entry requires exactly id, split and file")
        case_id = _require_text(entry["id"], "corpus case id")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        if entry["split"] not in {"development", "holdout"}:
            raise ValueError(f"invalid split for {case_id}")
        path = (ROOT / entry["file"]).resolve()
        path.relative_to(ROOT.resolve())
        if not path.is_file() or path.suffix not in {".yaml", ".yml"}:
            raise ValueError(f"case file is missing: {entry['file']}")
        case = load_yaml(path)
        if not isinstance(case, dict) or case.get("schema") != CASE_SCHEMA:
            raise ValueError(f"invalid case schema: {case_id}")
        if case.get("id") != case_id or case.get("split") != entry["split"]:
            raise ValueError(f"case metadata mismatch: {case_id}")
        labels = case.get("labels")
        if (
            not isinstance(labels, list)
            or not labels
            or any(not isinstance(label, str) or not label for label in labels)
            or len(labels) != len(set(labels))
        ):
            raise ValueError(f"case labels must be a unique non-empty string list: {case_id}")
        change = _require_exact_keys(case.get("change"), {"base", "head"}, f"{case_id}.change")
        base = _require_exact_keys(change["base"], {"documents"}, f"{case_id}.change.base")
        head = _require_exact_keys(change["head"], {"documents"}, f"{case_id}.change.head")
        base_documents = _validate_documents(case_id, "base", base["documents"])
        head_patch = _validate_documents(case_id, "head", head["documents"])
        head_documents = dict(base_documents)
        head_documents.update(head_patch)
        if all(base_documents.get(path) == data for path, data in head_patch.items()):
            raise ValueError(f"case head has no content change: {case_id}")
        _validate_expected(case, head_documents)
        cases.append(case)
        paths.append(path)
    _validate_balance(cases)
    return tuple(paths)


def corpus_hash(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256(b"aga-gigaagent-corpus/v1\0")
    for path in sorted(paths):
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _cases_from_paths(paths: tuple[Path, ...]) -> list[Mapping[str, Any]]:
    del paths  # The corpus order, not tuple slicing, defines case membership.
    corpus = load_yaml(CORPUS)
    return [load_yaml((ROOT / entry["file"]).resolve()) for entry in corpus["cases"]]


def verify_lock(paths: tuple[Path, ...]) -> str:
    actual = corpus_hash(paths)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    required = {
        "schema",
        "frozen_at",
        "case_count",
        "split_counts",
        "sha256",
        "ground_truth_sha256",
        "human_ground_truth_locked",
        "holdout_tuning_forbidden",
    }
    _require_exact_keys(lock, required, "corpus lock")
    if lock.get("schema") != "aga.gigaagent-corpus-lock/v1":
        raise ValueError("invalid corpus lock schema")
    if lock.get("sha256") != actual:
        raise ValueError(f"corpus lock mismatch: expected {lock.get('sha256')}, got {actual}")
    if lock.get("case_count") != len(_cases_from_paths(paths)):
        raise ValueError("corpus lock case count mismatch")
    cases = _cases_from_paths(paths)
    split_counts = dict(sorted(Counter(case["split"] for case in cases).items()))
    if lock.get("split_counts") != split_counts:
        raise ValueError("corpus lock split counts mismatch")
    expected_hash = ground_truth_hash(cases)
    if lock.get("ground_truth_sha256") != expected_hash:
        raise ValueError(
            "human ground-truth lock mismatch: labels or expected outcomes changed after lock"
        )
    if lock.get("human_ground_truth_locked") is not True:
        raise ValueError("human ground truth must remain locked")
    if lock.get("holdout_tuning_forbidden") is not True:
        raise ValueError("holdout tuning prohibition must remain locked")
    return actual


def _isolated_git_environment(
    repo: Path, overrides: Mapping[str, str] | None = None
) -> dict[str, str]:
    requested = dict(overrides or {})
    unexpected = sorted(set(requested) - _ALLOWED_GIT_ENV_OVERRIDES)
    if unexpected:
        raise ValueError(f"unsupported synthetic Git environment override(s): {unexpected}")

    # A synthetic measurement must not depend on the caller's Git config.  In
    # particular, global init.defaultObjectFormat, hooks, signing, filters and
    # GIT_CONFIG_* injection would otherwise change commits or execute code.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    controlled_home = repo.parent / "git-home"
    controlled_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment.update(
        {
            "HOME": str(controlled_home),
            "XDG_CONFIG_HOME": str(controlled_home / ".config"),
            "LC_ALL": "C",
            "TZ": "UTC",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "AGA Synthetic Evaluator",
            "GIT_AUTHOR_EMAIL": "aga-evaluation@example.invalid",
            "GIT_COMMITTER_NAME": "AGA Synthetic Evaluator",
            "GIT_COMMITTER_EMAIL": "aga-evaluation@example.invalid",
        }
    )
    environment.update(requested)
    return environment


def git(repo: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "tag.gpgSign=false",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=_isolated_git_environment(repo, env),
    )
    return completed.stdout.strip()


def write_documents(root: Path, documents: Mapping[str, Any]) -> None:
    for raw_relative, data in documents.items():
        relative = _safe_relative_yaml_path(raw_relative, "materialized document path")
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )


def _write_project_extension(root: Path) -> str:
    corpus = load_yaml(CORPUS)
    source = (ROOT / corpus["workspace"]["project_extension"]).resolve()
    relative = "workspace/aga-extension.yaml"
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return relative


def _write_manifest(
    root: Path, document_paths: Iterable[str], *, extension_path: str
) -> None:
    imports = sorted({extension_path, *document_paths})
    manifest = {
        "$package": {
            "aga-evaluation": {
                "name": "AGA frozen synthetic GigaAgent case",
                "vendor": "AGA hackathon team",
                "description": "Synthetic-public isolated SEAF-native evaluation workspace",
                "version": "1.0.0",
            }
        },
        "aga": {
            "schema": "seaf-core/v1.4.0",
            "extensions": ["aga.project/v1"],
            "data_classification": "synthetic-public",
        },
        "imports": imports,
    }
    (root / "dochub.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _load_seaf_native(repo: Path) -> Mapping[str, int]:
    skill_root = REPOSITORY_ROOT / "aga-skill"
    if str(skill_root) not in sys.path:
        sys.path.insert(0, str(skill_root))
    from tools.seaf_native import load_seaf_native  # pylint: disable=import-outside-toplevel

    snapshot = load_seaf_native(repo)
    return {
        "systems": len(snapshot.systems),
        "integrations": len(snapshot.integrations),
        "adrs": len(snapshot.adrs),
        "diagrams": len(snapshot.diagrams),
    }


def materialize_case_at(case: Mapping[str, Any], repo: Path) -> dict[str, Any]:
    """Materialize one frozen case at a caller-owned persistent path.

    The destination must not already exist.  This avoids mutating or deleting a
    caller's checkout and lets higher-level persistent runners stage the
    repository and publish it with an atomic rename.  Commit inputs deliberately
    match the historical temporary materializer byte-for-byte so the frozen
    base/head identities remain unchanged.
    """

    if not isinstance(repo, Path):
        raise TypeError("materialized repository path must be a pathlib.Path")
    if repo.exists() or repo.is_symlink():
        raise ValueError(f"materialized repository destination already exists: {repo}")
    if not repo.parent.is_dir() or repo.parent.is_symlink():
        raise ValueError("materialized repository parent must be an existing real directory")

    repo.mkdir()
    git(repo, "init", "--initial-branch=main", "--object-format=sha1")
    git(repo, "config", "user.name", "AGA Synthetic Evaluator")
    git(repo, "config", "user.email", "aga-evaluation@example.invalid")
    fixed = {
        "GIT_AUTHOR_DATE": "2026-07-15T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-07-15T00:00:00Z",
    }
    base_documents = _state_documents(case, "base")
    write_documents(repo, base_documents)
    extension_path = _write_project_extension(repo)
    _write_manifest(repo, base_documents, extension_path=extension_path)
    git(repo, "add", ".")
    git(repo, "commit", "-m", f"{case['id']} base", env=fixed)
    base = git(repo, "rev-parse", "HEAD")
    base_entities = _load_seaf_native(repo)

    head_patch = case["change"]["head"]["documents"]
    write_documents(repo, head_patch)
    head_documents = _state_documents(case, "head")
    _write_manifest(repo, head_documents, extension_path=extension_path)
    git(repo, "add", ".")
    git(repo, "commit", "-m", f"{case['id']} head", env=fixed)
    head = git(repo, "rev-parse", "HEAD")
    head_entities = _load_seaf_native(repo)
    changed_files = git(repo, "diff", "--name-only", base, head).splitlines()
    if base == head or not changed_files:
        raise ValueError(f"materialized revisions have no diff: {case['id']}")
    expected_changed = set(head_patch)
    if not expected_changed.issubset(changed_files):
        raise ValueError(f"materialized diff misses head documents: {case['id']}")
    if git(repo, "status", "--porcelain"):
        raise ValueError(f"materializer left a dirty repository: {case['id']}")
    return {
        "base": base,
        "head": head,
        "changed_files": changed_files,
        "base_entities": base_entities,
        "head_entities": head_entities,
    }


def materialize_case(case: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"aga-{case['id']}-") as raw:
        return materialize_case_at(case, Path(raw) / "repository")


def materialize_all(paths: tuple[Path, ...]) -> dict[str, dict[str, Any]]:
    revisions: dict[str, dict[str, Any]] = {}
    for case in _cases_from_paths(paths):
        revisions[case["id"]] = materialize_case(case)
    return revisions


def _scan_sanitized(value: Any, context: str = "raw_sanitized") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{context} contains a non-string key")
            canonical = key.strip().lower().replace("-", "_")
            if canonical in FORBIDDEN_RAW_KEYS:
                raise ValueError(f"{context} contains forbidden sensitive/prompt field {key!r}")
            _scan_sanitized(item, f"{context}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_sanitized(item, f"{context}[{index}]")
        return
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                raise ValueError(f"{context} matches a credential/private-key pattern")
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise ValueError(f"{context} is not JSON-compatible")


def _validate_runtime_identity(bundle: Mapping[str, Any], mode: str) -> None:
    for field in ("runtime", "model"):
        identity = _require_exact_keys(bundle[field], {"name", "version"}, field)
        name = _require_text(identity["name"], f"{field}.name")
        _require_text(identity["version"], f"{field}.version")
        marked_fixture = name.lower().startswith("fixture-")
        if mode == "fixture" and not marked_fixture:
            raise ValueError(f"fixture bundle {field}.name must start with 'fixture-'")
        if mode == "real" and marked_fixture:
            raise ValueError(f"real bundle {field}.name must not be fixture-marked")


def _load_bundle(
    bundle_path: Path,
    *,
    mode: str,
    corpus_digest: str,
    revisions: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    if bundle_path.suffix != ".json":
        raise ValueError("response bundle must be JSON")
    raw_bytes = bundle_path.read_bytes()
    if len(raw_bytes) > 8_000_000:
        raise ValueError("response bundle exceeds 8 MB")
    try:
        bundle = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"response bundle is not strict UTF-8 JSON: {error}") from error
    fields = {
        "schema",
        "mode",
        "captured_at",
        "runtime",
        "model",
        "prompt_hash",
        "config_hash",
        "corpus_hash",
        "redaction_note",
        "responses",
    }
    bundle = _require_exact_keys(bundle, fields, "response bundle")
    if bundle["schema"] != BUNDLE_SCHEMA:
        raise ValueError("invalid response bundle schema")
    if mode not in {"fixture", "real"} or bundle["mode"] != mode:
        raise ValueError(f"response bundle mode {bundle['mode']!r} does not match {mode!r}")
    if not isinstance(bundle["captured_at"], str) or not CAPTURED_AT_RE.fullmatch(
        bundle["captured_at"]
    ):
        raise ValueError("captured_at must use YYYY-MM-DDTHH:MM:SSZ")
    _validate_runtime_identity(bundle, mode)
    for field in ("prompt_hash", "config_hash"):
        if not isinstance(bundle[field], str) or not SHA256_RE.fullmatch(bundle[field]):
            raise ValueError(f"{field} must be a lowercase SHA-256")
    if bundle["corpus_hash"] != corpus_digest:
        raise ValueError("response bundle corpus_hash does not match the frozen corpus")
    _require_text(bundle["redaction_note"], "redaction_note")
    _scan_sanitized(bundle["redaction_note"], "redaction_note")
    responses = bundle["responses"]
    if not isinstance(responses, list) or len(responses) != len(revisions):
        raise ValueError("response bundle must contain exactly one response per frozen case")
    seen: set[str] = set()
    response_fields = {
        "case_id",
        "base_revision",
        "head_revision",
        "latency_ms",
        "raw_sanitized",
        "normalized",
    }
    for index, response in enumerate(responses):
        response = _require_exact_keys(response, response_fields, f"responses[{index}]")
        case_id = _require_text(response["case_id"], f"responses[{index}].case_id")
        if case_id in seen:
            raise ValueError(f"duplicate response case_id: {case_id}")
        seen.add(case_id)
        if case_id not in revisions:
            raise ValueError(f"unknown response case_id: {case_id}")
        for name in ("base_revision", "head_revision"):
            value = response[name]
            if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
                raise ValueError(f"{case_id}.{name} must be a 40-character Git SHA")
            expected = revisions[case_id]["base" if name == "base_revision" else "head"]
            if value != expected:
                raise ValueError(f"{case_id}.{name} does not match materialized Git revision")
        latency = response["latency_ms"]
        if (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not math.isfinite(float(latency))
            or not 0 <= float(latency) <= 3_600_000
        ):
            raise ValueError(f"{case_id}.latency_ms must be finite and in [0, 3600000]")
        if response["raw_sanitized"] is None:
            raise ValueError(f"{case_id}.raw_sanitized must be retained")
        try:
            raw_payload = json.dumps(
                response["raw_sanitized"], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError(f"{case_id}.raw_sanitized is not JSON-compatible") from error
        if len(raw_payload) > MAX_RAW_RESPONSE_BYTES:
            raise ValueError(f"{case_id}.raw_sanitized exceeds {MAX_RAW_RESPONSE_BYTES} bytes")
        _scan_sanitized(response["raw_sanitized"], f"{case_id}.raw_sanitized")
        _scan_sanitized(response["normalized"], f"{case_id}.normalized")
    missing = sorted(set(revisions) - seen)
    if missing:
        raise ValueError(f"response bundle misses cases: {missing}")
    return bundle


def _validate_normalized(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        root = _require_exact_keys(value, {"status", "verdict", "findings"}, "normalized")
        status = root["status"]
        verdict = root["verdict"]
        if status not in STATUSES:
            raise ValueError("normalized.status is invalid")
        if verdict not in VERDICTS:
            raise ValueError("normalized.verdict is invalid")
        if status == "complete" and verdict == "incomplete":
            raise ValueError("a complete normalized response cannot have incomplete verdict")
        if status in {"incomplete", "error"} and verdict != "incomplete":
            raise ValueError("an incomplete/error response must fail closed")
        findings = root["findings"]
        if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
            raise ValueError(f"normalized.findings must be a list of at most {MAX_FINDINGS}")
        validated_findings: list[dict[str, Any]] = []
        dedup: set[tuple[str, str, str]] = set()
        finding_fields = {
            "rule_id",
            "severity",
            "confidence",
            "artifact",
            "location",
            "evidence",
            "source_ref",
            "suggested_fix",
        }
        for index, raw in enumerate(findings):
            finding = _require_exact_keys(raw, finding_fields, f"normalized.findings[{index}]")
            rule_id = finding["rule_id"]
            if rule_id not in ALLOWED_RULES:
                raise ValueError(f"normalized.findings[{index}].rule_id is not allowed")
            severity = finding["severity"]
            if severity not in SEVERITIES or severity != RULE_SEVERITIES[rule_id]:
                raise ValueError(f"normalized.findings[{index}].severity differs from trusted rule")
            confidence = finding["confidence"]
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
                or not 0 <= float(confidence) <= 1
            ):
                raise ValueError(f"normalized.findings[{index}].confidence must be in [0, 1]")
            artifact = _safe_relative_yaml_path(
                finding["artifact"], f"normalized.findings[{index}].artifact"
            )
            location = _require_text(
                finding["location"], f"normalized.findings[{index}].location", allow_empty=True
            )
            evidence = _require_text(
                finding["evidence"], f"normalized.findings[{index}].evidence"
            )
            source_ref = _require_text(
                finding["source_ref"], f"normalized.findings[{index}].source_ref"
            )
            if source_ref != RULE_SOURCE_REFS[rule_id]:
                raise ValueError(f"normalized.findings[{index}].source_ref is not trusted")
            suggested_fix = _require_text(
                finding["suggested_fix"],
                f"normalized.findings[{index}].suggested_fix",
                allow_empty=True,
            )
            key = (rule_id, artifact, location)
            if key in dedup:
                raise ValueError(f"normalized.findings[{index}] duplicates a finding")
            dedup.add(key)
            validated_findings.append(
                {
                    "rule_id": rule_id,
                    "severity": severity,
                    "confidence": float(confidence),
                    "artifact": artifact,
                    "location": location,
                    "evidence": evidence,
                    "source_ref": source_ref,
                    "suggested_fix": suggested_fix,
                }
            )
        return {"status": status, "verdict": verdict, "findings": validated_findings}, errors
    except (KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
        return None, errors


def _decode_pointer(pointer: str) -> list[str] | None:
    if not pointer.startswith("/"):
        return None
    parts = pointer[1:].split("/")
    decoded: list[str] = []
    for part in parts:
        if re.search(r"~(?![01])", part):
            return None
        decoded.append(part.replace("~1", "/").replace("~0", "~"))
    return decoded


def _pointer_resolves(document: Any, pointer: str) -> bool:
    parts = _decode_pointer(pointer)
    if parts is None:
        return False
    current = document
    for part in parts:
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True


def _finding_evidence_reason(
    finding: Mapping[str, Any], documents: Mapping[str, Any]
) -> tuple[bool, str]:
    artifact = finding["artifact"]
    if artifact not in documents:
        return False, f"artifact {artifact!r} was not supplied in materialized head"
    location = finding["location"]
    if not location:
        return False, "location is empty; evidence cannot be grounded"
    if not _pointer_resolves(documents[artifact], location):
        return False, f"location {location!r} does not resolve in {artifact}"
    return True, "artifact and JSON Pointer resolve in materialized head"


def _matches_expected(predicted: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return (
        predicted["rule_id"] == expected["rule_id"]
        and predicted["severity"] == expected["severity"]
        and predicted["artifact"] == expected["artifact"]
        and predicted["location"] == expected["location"]
        and expected["evidence_contains"].casefold() in predicted["evidence"].casefold()
    )


def _score_case(
    case: Mapping[str, Any], response: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized, schema_errors = _validate_normalized(response["normalized"])
    expected = case["expected"]
    head_documents = _state_documents(case, "head")
    predicted_findings = normalized["findings"] if normalized is not None else []
    evidence_checks: list[dict[str, Any]] = []
    grounded_indexes: set[int] = set()
    for index, finding in enumerate(predicted_findings):
        valid, reason = _finding_evidence_reason(finding, head_documents)
        if valid:
            grounded_indexes.add(index)
        evidence_checks.append(
            {
                "finding_index": index,
                "rule_id": finding["rule_id"],
                "valid": valid,
                "reason": reason,
            }
        )

    unmatched = set(range(len(predicted_findings)))
    true_positives: list[dict[str, Any]] = []
    false_negatives: list[dict[str, Any]] = []
    for wanted in expected["findings"]:
        match = next(
            (
                index
                for index in sorted(unmatched & grounded_indexes)
                if _matches_expected(predicted_findings[index], wanted)
            ),
            None,
        )
        if match is None:
            false_negatives.append(dict(wanted))
        else:
            unmatched.remove(match)
            true_positives.append(dict(wanted))
    false_positives = [predicted_findings[index] for index in sorted(unmatched)]

    raw_normalized = response["normalized"]
    raw_verdict = raw_normalized.get("verdict") if isinstance(raw_normalized, Mapping) else None
    raw_status = raw_normalized.get("status") if isinstance(raw_normalized, Mapping) else None
    outcome_ok = raw_verdict == expected["verdict"]
    status_ok = raw_status == expected["status"]
    invalid_evidence = sum(not item["valid"] for item in evidence_checks)
    approve_like = raw_verdict in {"approve", "approve_with_warnings"}
    unsafe_approve = bool(approve_like and expected["verdict"] not in {"approve", "approve_with_warnings"})
    passed = bool(
        normalized is not None
        and not schema_errors
        and status_ok
        and outcome_ok
        and not false_positives
        and not false_negatives
        and invalid_evidence == 0
    )
    failures: list[str] = []
    if schema_errors:
        failures.append(f"schema invalid: {'; '.join(schema_errors)}")
    if not status_ok:
        failures.append(f"status {raw_status!r} != expected {expected['status']!r}")
    if not outcome_ok:
        failures.append(f"verdict {raw_verdict!r} != expected {expected['verdict']!r}")
    if false_negatives:
        failures.append(f"{len(false_negatives)} expected finding(s) missed")
    if false_positives:
        failures.append(f"{len(false_positives)} unexpected finding(s)")
    if invalid_evidence:
        failures.append(f"{invalid_evidence} finding(s) have invalid/hallucinated evidence")
    if unsafe_approve:
        failures.append("unsafe approve on a non-approvable case")
    reason = (
        "schema, status, verdict, findings and evidence match frozen ground truth"
        if passed
        else "; ".join(failures)
    )
    public = {
        "case_id": case["id"],
        "split": case["split"],
        "base_revision": response["base_revision"],
        "head_revision": response["head_revision"],
        "latency_ms": float(response["latency_ms"]),
        "expected": expected,
        "raw_sanitized_response": response["raw_sanitized"],
        "normalized_output": normalized if normalized is not None else response["normalized"],
        "schema_valid": normalized is not None and not schema_errors,
        "schema_errors": schema_errors,
        "evidence_checks": evidence_checks,
        "tp": true_positives,
        "fp": false_positives,
        "fn": false_negatives,
        "unsafe_approve": unsafe_approve,
        "assessment": "PASS" if passed else "FAIL",
        "reason": reason,
    }
    internal = {
        "expected_count": len(expected["findings"]),
        "predicted_count": len(predicted_findings),
        "tp": len(true_positives),
        "fp": len(false_positives),
        "fn": len(false_negatives),
        "tp_blocker": sum(item["severity"] == "blocker" for item in true_positives),
        "fn_blocker": sum(item["severity"] == "blocker" for item in false_negatives),
        "outcome_ok": outcome_ok,
        "status_ok": status_ok,
        "passed": passed,
        "schema_valid": normalized is not None and not schema_errors,
        "invalid_evidence": invalid_evidence,
        "unsafe_approve": unsafe_approve,
        "latency_ms": float(response["latency_ms"]),
        "public": public,
    }
    return public, internal


def _ratio(numerator: int, denominator: int, *, empty: float) -> float:
    return round(numerator / denominator, 6) if denominator else empty


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tp = sum(row["tp"] for row in rows)
    fp = sum(row["fp"] for row in rows)
    fn = sum(row["fn"] for row in rows)
    blockers_tp = sum(row["tp_blocker"] for row in rows)
    blockers_fn = sum(row["fn_blocker"] for row in rows)
    invalid_evidence = sum(row["invalid_evidence"] for row in rows)
    predicted = sum(row["predicted_count"] for row in rows)
    latencies = [row["latency_ms"] for row in rows]
    return {
        "cases_evaluated": len(rows),
        "cases_passed": sum(row["passed"] for row in rows),
        "findings_expected": sum(row["expected_count"] for row in rows),
        "findings_predicted": predicted,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "expected_blockers": blockers_tp + blockers_fn,
        "precision": _ratio(tp, tp + fp, empty=1.0),
        "recall": _ratio(tp, tp + fn, empty=1.0),
        "blocker_recall": _ratio(blockers_tp, blockers_tp + blockers_fn, empty=1.0),
        "outcome_accuracy": _ratio(sum(row["outcome_ok"] for row in rows), len(rows), empty=0.0),
        "status_accuracy": _ratio(sum(row["status_ok"] for row in rows), len(rows), empty=0.0),
        "exact_case_accuracy": _ratio(sum(row["passed"] for row in rows), len(rows), empty=0.0),
        "schema_valid_rate": _ratio(
            sum(row["schema_valid"] for row in rows), len(rows), empty=0.0
        ),
        "invalid_or_hallucinated_evidence_count": invalid_evidence,
        "evidence_findings_denominator": predicted,
        "invalid_or_hallucinated_evidence_rate": _ratio(
            invalid_evidence, predicted, empty=0.0
        ),
        "unsafe_approve_count": sum(row["unsafe_approve"] for row in rows),
        "latency_ms": {
            "count": len(latencies),
            "total": round(sum(latencies), 3),
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
    }


def _load_gate() -> Mapping[str, Any]:
    gate = _require_exact_keys(load_yaml(GATE), {"schema", "frozen_before_holdout", "thresholds"}, "gate")
    if gate["schema"] != "aga.gigaagent-gate/v1" or gate["frozen_before_holdout"] is not True:
        raise ValueError("release gate must be v1 and frozen before holdout")
    thresholds = _require_exact_keys(
        gate["thresholds"],
        {
            "blocker_recall",
            "unsafe_approve_count",
            "schema_valid_rate",
            "precision_min",
            "recall_min",
            "outcome_accuracy_min",
        },
        "gate.thresholds",
    )
    return thresholds


def _gate_scope(metrics: Mapping[str, Any], thresholds: Mapping[str, Any]) -> dict[str, Any]:
    definitions = (
        ("blocker_recall", metrics["blocker_recall"], ">=", thresholds["blocker_recall"]),
        (
            "unsafe_approve_count",
            metrics["unsafe_approve_count"],
            "<=",
            thresholds["unsafe_approve_count"],
        ),
        ("schema_valid_rate", metrics["schema_valid_rate"], ">=", thresholds["schema_valid_rate"]),
        ("precision", metrics["precision"], ">=", thresholds["precision_min"]),
        ("recall", metrics["recall"], ">=", thresholds["recall_min"]),
        (
            "outcome_accuracy",
            metrics["outcome_accuracy"],
            ">=",
            thresholds["outcome_accuracy_min"],
        ),
    )
    checks = []
    for identifier, actual, operator, threshold in definitions:
        passed = actual >= threshold if operator == ">=" else actual <= threshold
        checks.append(
            {
                "id": identifier,
                "actual": actual,
                "operator": operator,
                "threshold": threshold,
                "passed": bool(passed),
            }
        )
    return {"passed": all(item["passed"] for item in checks), "checks": checks}


def score_response_bundle(bundle_path: Path, *, mode: str) -> dict[str, Any]:
    if mode == "real":
        # No field inside a caller-supplied bundle can prove that an official
        # runtime produced it.  Until an organiser-defined capture contract and
        # verified adapter are present, accepting real mode would let a renamed
        # fixture self-attest as release evidence.
        raise ValueError(REAL_SCORING_UNSUPPORTED)
    if mode != "fixture":
        raise ValueError(f"unsupported scoring mode: {mode!r}")

    paths = corpus_files()
    digest = verify_lock(paths)
    cases = _cases_from_paths(paths)
    case_by_id = {case["id"]: case for case in cases}
    revisions = materialize_all(paths)
    bundle = _load_bundle(
        bundle_path, mode=mode, corpus_digest=digest, revisions=revisions
    )
    response_by_id = {response["case_id"]: response for response in bundle["responses"]}
    public_rows: list[dict[str, Any]] = []
    internal_rows: list[dict[str, Any]] = []
    for case in cases:
        public, internal = _score_case(case, response_by_id[case["id"]])
        public_rows.append(public)
        internal_rows.append(internal)
    development_rows = [
        row for case, row in zip(cases, internal_rows) if case["split"] == "development"
    ]
    holdout_rows = [
        row for case, row in zip(cases, internal_rows) if case["split"] == "holdout"
    ]
    development = _metrics(development_rows)
    holdout = _metrics(holdout_rows)
    overall = _metrics(internal_rows)
    thresholds = _load_gate()
    scopes = {
        "development": _gate_scope(development, thresholds),
        "holdout": _gate_scope(holdout, thresholds),
        "overall": _gate_scope(overall, thresholds),
    }
    evaluation_passed = all(scope["passed"] for scope in scopes.values())
    release_eligible = False
    return {
        "schema": RESULTS_SCHEMA,
        "status": "fixture_scored_non_release",
        "mode": mode,
        "measurement_class": "synthetic_fixture",
        "release_evidence": release_eligible,
        "captured_at": bundle["captured_at"],
        "runtime": bundle["runtime"],
        "model": bundle["model"],
        "prompt_hash": bundle["prompt_hash"],
        "config_hash": bundle["config_hash"],
        "corpus": "frozen-synthetic-seaf-semantic-basket",
        "corpus_hash": digest,
        "ground_truth_hash": ground_truth_hash(cases),
        "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "cases_evaluated": len(cases),
        "development": development,
        "holdout": holdout,
        "overall": overall,
        "gate": {
            "thresholds": dict(thresholds),
            "scopes": scopes,
            "evaluation_passed": evaluation_passed,
            "release_eligible": release_eligible,
            "release_passed": False,
            "reason": "fixture scores are never release evidence",
        },
        "runs": public_rows,
    }


def _trusted_ouroboros_selection(
    cases: Sequence[Mapping[str, Any]], case_ids: Sequence[str]
) -> tuple[str, list[Mapping[str, Any]]]:
    """Return a non-cherry-picked frozen selection for the trusted runner.

    A one-case selection is the explicit smoke-test shape.  A measurement
    selection must otherwise be one complete frozen split or the complete
    basket.  This prevents a caller from presenting a hand-picked subset as a
    development or holdout result.
    """

    if not case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("trusted Ouroboros case IDs must be non-empty and unique")
    case_by_id = {str(case["id"]): case for case in cases}
    unknown = sorted(set(case_ids) - set(case_by_id))
    if unknown:
        raise ValueError(f"unknown trusted Ouroboros case ID(s): {unknown}")
    requested = set(case_ids)
    development = {
        str(case["id"]) for case in cases if case["split"] == "development"
    }
    holdout = {str(case["id"]) for case in cases if case["split"] == "holdout"}
    if len(requested) == 1:
        selection = "smoke"
    elif requested == development:
        selection = "development"
    elif requested == holdout:
        selection = "holdout"
    elif requested == set(case_by_id):
        selection = "all"
    else:
        raise ValueError(
            "trusted Ouroboros responses must cover one smoke case, one complete "
            "frozen split, or all frozen cases"
        )
    return selection, [case for case in cases if str(case["id"]) in requested]


def _validate_trusted_ouroboros_response(
    response: Any,
    *,
    case_id: str,
    revision: Mapping[str, Any],
) -> Mapping[str, Any]:
    fields = {
        "case_id",
        "base_revision",
        "head_revision",
        "latency_ms",
        "raw_sanitized",
        "normalized",
    }
    response = _require_exact_keys(response, fields, f"trusted response {case_id}")
    if response["case_id"] != case_id:
        raise ValueError("trusted Ouroboros response order/case correlation mismatch")
    for field, key in (("base_revision", "base"), ("head_revision", "head")):
        value = response[field]
        if not isinstance(value, str) or COMMIT_RE.fullmatch(value) is None:
            raise ValueError(f"{case_id}.{field} must be a full SHA-1 Git revision")
        if value != revision[key]:
            raise ValueError(
                f"{case_id}.{field} does not match the frozen materialization"
            )
    latency = response["latency_ms"]
    if (
        isinstance(latency, bool)
        or not isinstance(latency, (int, float))
        or not math.isfinite(float(latency))
        or not 0 <= float(latency) <= 3_600_000
    ):
        raise ValueError(f"{case_id}.latency_ms must be finite and in [0, 3600000]")
    if response["raw_sanitized"] is None:
        raise ValueError(f"{case_id}.raw_sanitized must be retained")
    try:
        raw_payload = json.dumps(
            response["raw_sanitized"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"{case_id}.raw_sanitized is not strict JSON") from error
    if len(raw_payload) > MAX_RAW_RESPONSE_BYTES:
        raise ValueError(
            f"{case_id}.raw_sanitized exceeds {MAX_RAW_RESPONSE_BYTES} bytes"
        )
    _scan_sanitized(response["raw_sanitized"], f"{case_id}.raw_sanitized")
    _scan_sanitized(response["normalized"], f"{case_id}.normalized")
    return response


def score_trusted_ouroboros_responses(
    responses: Sequence[Mapping[str, Any]],
    *,
    captured_at: str,
    runtime_version: str,
    provider: str,
    model_name: str,
    prompt_hash: str,
    config_hash: str,
) -> dict[str, Any]:
    """Score captures supplied directly by the project-owned Ouroboros runner.

    This is deliberately an in-memory API: it accepts no bundle path, no
    caller-selected ``mode`` label, and performs no evidence write.  The live
    command must invoke Ouroboros, verify AGA receipts, and immediately pass
    its sanitized captures here.  Caller-supplied JSON files remain unable to
    self-attest through ``--score-bundle --mode real``.
    """

    if isinstance(responses, (str, bytes)) or not isinstance(responses, Sequence):
        raise ValueError("trusted Ouroboros responses must be an in-memory sequence")
    if len(responses) > 16:
        raise ValueError("trusted Ouroboros response count exceeds the frozen basket")
    if not isinstance(captured_at, str) or CAPTURED_AT_RE.fullmatch(captured_at) is None:
        raise ValueError("captured_at must use YYYY-MM-DDTHH:MM:SSZ")
    if runtime_version != TRUSTED_OUROBOROS_VERSION:
        raise ValueError("trusted Ouroboros runtime version does not match the pin")
    if provider != TRUSTED_OUROBOROS_PROVIDER:
        raise ValueError("trusted Ouroboros provider must be OpenRouter")
    if model_name != TRUSTED_OUROBOROS_MODEL:
        raise ValueError("trusted Ouroboros model does not match the owner-approved ID")
    for field, value in (("prompt_hash", prompt_hash), ("config_hash", config_hash)):
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise ValueError(f"{field} must be a lowercase SHA-256")

    paths = corpus_files()
    digest = verify_lock(paths)
    cases = _cases_from_paths(paths)
    raw_case_ids: list[str] = []
    for index, response in enumerate(responses):
        if not isinstance(response, Mapping):
            raise ValueError(f"trusted responses[{index}] must be an object")
        case_id = response.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"trusted responses[{index}].case_id is invalid")
        raw_case_ids.append(case_id)
    selection, selected_cases = _trusted_ouroboros_selection(cases, raw_case_ids)
    supplied = {str(response["case_id"]): response for response in responses}

    public_rows: list[dict[str, Any]] = []
    internal_rows: list[dict[str, Any]] = []
    validated_responses: list[Mapping[str, Any]] = []
    for case in selected_cases:
        case_id = str(case["id"])
        # Re-materializing independently is the provenance check for the
        # immutable Git pair; no revision asserted by a runtime is trusted.
        revision = materialize_case(case)
        response = _validate_trusted_ouroboros_response(
            supplied[case_id], case_id=case_id, revision=revision
        )
        public, internal = _score_case(case, response)
        # Trusted live evidence records the measured output and aggregate
        # match counts, not the frozen expected finding payload.  In
        # particular, a holdout result must not become a convenient prompt-
        # tuning answer key after its first run.
        public_rows.append(
            {
                "case_id": public["case_id"],
                "split": public["split"],
                "base_revision": public["base_revision"],
                "head_revision": public["head_revision"],
                "latency_ms": public["latency_ms"],
                "raw_sanitized_response": public["raw_sanitized_response"],
                "normalized_output": public["normalized_output"],
                "schema_valid": public["schema_valid"],
                "schema_errors": public["schema_errors"],
                "evidence_checks": public["evidence_checks"],
                "tp_count": len(public["tp"]),
                "fp_count": len(public["fp"]),
                "fn_count": len(public["fn"]),
                "unsafe_approve": public["unsafe_approve"],
                "assessment": public["assessment"],
                "reason": public["reason"],
            }
        )
        internal_rows.append(internal)
        validated_responses.append(response)

    development_rows = [
        row
        for case, row in zip(selected_cases, internal_rows)
        if case["split"] == "development"
    ]
    holdout_rows = [
        row
        for case, row in zip(selected_cases, internal_rows)
        if case["split"] == "holdout"
    ]
    development = _metrics(development_rows)
    holdout = _metrics(holdout_rows)
    overall = _metrics(internal_rows)
    thresholds = _load_gate()
    scope_metrics: dict[str, Mapping[str, Any]] = {"overall": overall}
    if development_rows:
        scope_metrics["development"] = development
    if holdout_rows:
        scope_metrics["holdout"] = holdout
    scopes = {
        name: _gate_scope(metrics, thresholds)
        for name, metrics in scope_metrics.items()
    }
    evaluation_passed = all(scope["passed"] for scope in scopes.values())
    release_eligible = selection == "all"
    release_passed = release_eligible and evaluation_passed
    capture_set_sha256 = hashlib.sha256(
        json.dumps(
            validated_responses,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": TRUSTED_OUROBOROS_RESULTS_SCHEMA,
        "status": (
            "trusted_real_scored_release"
            if release_passed
            else "trusted_real_scored_non_release"
        ),
        "mode": "real",
        "measurement_class": "trusted_ouroboros_real",
        "release_evidence": release_passed,
        "captured_at": captured_at,
        "runtime": {"name": "ouroboros", "version": runtime_version},
        "provider": provider,
        "model": {"name": model_name},
        "redaction": {
            "credentials_retained": False,
            "absolute_paths_retained": False,
            "raw_prompts_retained": False,
            "raw_provider_payloads_retained": False,
        },
        "prompt_hash": prompt_hash,
        "config_hash": config_hash,
        "corpus": "frozen-synthetic-seaf-semantic-basket",
        "corpus_hash": digest,
        "ground_truth_hash": ground_truth_hash(cases),
        "capture_set_sha256": capture_set_sha256,
        "selection": {
            "kind": selection,
            "case_ids": [str(case["id"]) for case in selected_cases],
        },
        "cases_evaluated": len(selected_cases),
        "development": development,
        "holdout": holdout,
        "overall": overall,
        "gate": {
            "thresholds": dict(thresholds),
            "scopes": scopes,
            "evaluation_passed": evaluation_passed,
            "release_eligible": release_eligible,
            "release_passed": release_passed,
            "reason": (
                "all frozen scopes passed with trusted in-process Ouroboros captures"
                if release_passed
                else "partial trusted run is not release evidence"
                if not release_eligible
                else "one or more frozen release-gate checks failed"
            ),
        },
        "runs": public_rows,
    }


def _write_results(result: Mapping[str, Any], output: Path, *, mode: str) -> None:
    if mode == "real" and output.resolve() != REAL_RESULTS.resolve():
        raise ValueError(f"real mode must write only {REAL_RESULTS}")
    if mode == "real":
        raise ValueError(REAL_SCORING_UNSUPPORTED)
    if mode == "fixture" and output.resolve() == REAL_RESULTS.resolve():
        raise ValueError("fixture mode cannot overwrite the real results.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--verify-only", action="store_true")
    actions.add_argument("--materialize-check", action="store_true")
    actions.add_argument("--score-bundle", type=Path)
    parser.add_argument("--mode", choices=("fixture", "real"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    paths = corpus_files()
    digest = verify_lock(paths)
    balance = _validate_balance(_cases_from_paths(paths))
    print(
        f"CORPUS OK: {len(_cases_from_paths(paths))} cases, splits={balance['split_counts']}, "
        f"sha256={digest}"
    )
    if args.materialize_check:
        revisions = materialize_all(paths)
        for case_id, pair in revisions.items():
            print(
                f"GIT+SEAF OK: {case_id} {pair['base'][:12]}..{pair['head'][:12]} "
                f"changed={','.join(pair['changed_files'])}"
            )
        return 0
    if args.score_bundle is not None:
        if args.mode is None or args.output is None:
            parser.error("--score-bundle requires explicit --mode and --output")
        result = score_response_bundle(args.score_bundle, mode=args.mode)
        _write_results(result, args.output, mode=args.mode)
        print(
            f"SCORE OK: mode={args.mode} cases={result['cases_evaluated']} "
            f"evaluation_gate={result['gate']['evaluation_passed']} "
            f"release_gate={result['gate']['release_passed']} output={args.output}"
        )
        return 0
    if args.mode is not None or args.output is not None:
        parser.error("--mode/--output are valid only with --score-bundle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
