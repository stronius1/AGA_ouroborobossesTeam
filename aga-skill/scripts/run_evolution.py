# -*- coding: utf-8 -*-
"""Offline, candidate-only AGA evolution cycle.

The evolver never applies, merges, approves or pushes a candidate.  It emits
verifiable artifacts under ``build/`` and uses a dry-run publisher by default.
Applying a passed candidate is a separate, externally reviewed VCS action.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from evolver.fitness import FitnessValidationError, evaluate, gate, markdown_report  # noqa: E402
from evolver.mutations import (  # noqa: E402
    MutationValidationError,
    UnsupportedMutationTypeError,
    validate_mutation,
)
from evolver.policy import CandidateChange, PolicyViolation, guard_candidate_changes  # noqa: E402
from tools.aga import RULE_FILES, load_rules, parse_frontmatter  # noqa: E402
from tools.feedback import append_jsonl_atomic, precedent_priority  # noqa: E402
from tools.publisher import (  # noqa: E402
    DryRunPublisher,
    PublicationResult,
    PublishRequest,
    PublisherPolicyError,
    validate_publish_request,
)
from tools.validation import (  # noqa: E402
    DEFAULT_MAX_ARTIFACT_BYTES,
    ValidationError,
    open_directory_no_follow,
    safe_read_bytes,
    strict_load_yaml,
    strict_load_yaml_text,
)

SEMVER_BUMP = {
    "add_exception": "minor", "adjust_severity": "minor", "add_rule": "minor",
    "activate_rule": "minor", "deprecate_rule": "minor",
}
DOMAIN_FILE = {"PRIN": "principles.yaml", "SEAF": "seaf-checks.yaml",
               "DIAG": "diagram-checks.yaml", "ADR": "adr-checks.yaml"}
MAX_LOCKED_FIXTURE_FILES = 4_096
MAX_LOCKED_FIXTURE_BYTES = 32 * 1024 * 1024


class _IndentedSafeDumper(yaml.SafeDumper):
    """Emit only newly inserted YAML fragments with readable indentation."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, False)


@dataclass(frozen=True)
class LockedEvaluationInputs:
    """Exact human-approved bytes used by both sides of the fitness gate."""

    corpus: Mapping[str, Any]
    corpus_lock_payload: bytes
    corpus_payload: bytes
    corpus_sha256: str
    fixture_files: tuple[tuple[str, bytes], ...]
    fixture_tree_sha256: str
    seaf_payload: bytes
    seaf_sha256: str
    fixtures_revision: str


def bump(version: str, level: str) -> str:
    try:
        major, minor, patch = (int(part) for part in version.split("."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid semantic version: {version!r}") from exc
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fixture_tree_error(message: str, path: Path) -> None:
    raise ValidationError(
        message,
        path=path,
        code="same_cycle_corpus_change",
    )


def _read_opened_fixture_bytes(
    path: Path, descriptor: int, expected: os.stat_result
) -> bytes:
    """Read an already descriptor-anchored fixture and verify its identity."""

    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
    ):
        _fixture_tree_error("golden fixture changed during safe open", path)
    if opened.st_size > DEFAULT_MAX_ARTIFACT_BYTES:
        _fixture_tree_error("golden fixture exceeds the artifact size limit", path)
    chunks: list[bytes] = []
    remaining = DEFAULT_MAX_ARTIFACT_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > DEFAULT_MAX_ARTIFACT_BYTES:
        _fixture_tree_error("golden fixture exceeds the artifact size limit", path)
    final = os.fstat(descriptor)
    if (
        not stat.S_ISREG(final.st_mode)
        or final.st_nlink != 1
        or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
        != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    ):
        _fixture_tree_error("golden fixture changed while it was read", path)
    return payload


def _capture_fixtures(
    approved_ids: Sequence[str],
) -> tuple[str, tuple[tuple[str, bytes], ...]]:
    """Capture and hash canonical ``relative path + exact bytes`` fixtures."""

    if isinstance(approved_ids, (str, bytes)) or not approved_ids:
        _fixture_tree_error(
            "approved fixture IDs must be a non-empty sequence",
            PKG_ROOT / "golden" / "corpus.lock.json",
        )
    if len(set(approved_ids)) != len(approved_ids):
        _fixture_tree_error(
            "approved fixture IDs contain duplicates",
            PKG_ROOT / "golden" / "corpus.lock.json",
        )
    fixtures_root = PKG_ROOT / "golden" / "prs"
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    captured: list[tuple[str, bytes]] = []
    total_bytes = 0
    root_descriptor = open_directory_no_follow(fixtures_root)

    def walk(directory_fd: int, relative_dir: str, *, depth: int) -> list[str]:
        nonlocal total_bytes
        if depth > 16:
            _fixture_tree_error(
                "golden fixture directory depth exceeds 16",
                fixtures_root / relative_dir,
            )
        case_files: list[str] = []
        try:
            names = sorted(os.listdir(directory_fd))
            for name in names:
                if (
                    name in {"", ".", ".."}
                    or "/" in name
                    or "\\" in name
                    or any(ord(character) < 32 for character in name)
                ):
                    _fixture_tree_error(
                        "unsafe filename in golden fixtures",
                        fixtures_root / relative_dir / name,
                    )
                relative = f"{relative_dir}/{name}"
                display_path = fixtures_root / Path(relative)
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    _fixture_tree_error(
                        "symlink in golden fixtures is not allowed", display_path
                    )
                if stat.S_ISDIR(info.st_mode):
                    child = os.open(name, directory_flags, dir_fd=directory_fd)
                    opened = os.fstat(child)
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        os.close(child)
                        _fixture_tree_error(
                            "golden fixture directory changed during safe open",
                            display_path,
                        )
                    case_files.extend(walk(child, relative, depth=depth + 1))
                    continue
                if not stat.S_ISREG(info.st_mode):
                    _fixture_tree_error(
                        "non-regular golden fixture is not allowed", display_path
                    )
                descriptor = os.open(name, file_flags, dir_fd=directory_fd)
                try:
                    payload = _read_opened_fixture_bytes(
                        display_path, descriptor, info
                    )
                finally:
                    os.close(descriptor)
                total_bytes += len(payload)
                if total_bytes > MAX_LOCKED_FIXTURE_BYTES:
                    _fixture_tree_error(
                        f"golden fixture tree exceeds {MAX_LOCKED_FIXTURE_BYTES} bytes",
                        fixtures_root,
                    )
                captured.append((relative, payload))
                case_files.append(relative)
                if len(captured) > MAX_LOCKED_FIXTURE_FILES:
                    _fixture_tree_error(
                        f"golden fixture file count exceeds {MAX_LOCKED_FIXTURE_FILES}",
                        fixtures_root,
                    )
            return case_files
        finally:
            os.close(directory_fd)

    try:
        for case_id in approved_ids:
            if not isinstance(case_id, str) or not case_id or any(
                separator in case_id for separator in ("/", "\\")
            ) or case_id in {".", ".."}:
                _fixture_tree_error(
                    "approved fixture ID is not a safe path segment", fixtures_root
                )
            try:
                case_descriptor = os.open(
                    case_id, directory_flags, dir_fd=root_descriptor
                )
            except OSError as exc:
                raise ValidationError(
                    f"approved golden fixture is unavailable: {exc}",
                    path=fixtures_root / case_id,
                    code="same_cycle_corpus_change",
                ) from exc
            case_files = walk(case_descriptor, case_id, depth=0)
            required_manifest = f"{case_id}/meta.yaml"
            files_prefix = f"{case_id}/files/"
            if required_manifest not in case_files or not any(
                relative.startswith(files_prefix) for relative in case_files
            ):
                _fixture_tree_error(
                    "approved fixture requires meta.yaml and at least one materialized artifact",
                    fixtures_root / case_id,
                )
    finally:
        os.close(root_descriptor)

    digest = hashlib.sha256()
    digest.update(b"aga-fixtures/v1\0")
    captured.sort(key=lambda item: item[0])
    for relative, payload in captured:
        relative_bytes = relative.encode("utf-8")
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest(), tuple(captured)


def _fixtures_sha256(approved_ids: Sequence[str]) -> str:
    """Compatibility helper returning the captured golden-tree digest."""

    return _capture_fixtures(approved_ids)[0]


def _combined_fixtures_revision(fixture_tree_sha256: str, seaf_sha256: str) -> str:
    digest = hashlib.sha256()
    digest.update(b"aga-evaluation-fixtures/v2\0")
    for name, value in (
        ("golden/prs", fixture_tree_sha256),
        ("fixtures/seaf.yaml", seaf_sha256),
    ):
        name_bytes = name.encode("utf-8")
        value_bytes = value.encode("ascii")
        digest.update(len(name_bytes).to_bytes(8, "big"))
        digest.update(name_bytes)
        digest.update(len(value_bytes).to_bytes(8, "big"))
        digest.update(value_bytes)
    return digest.hexdigest()


def _evaluate_with_locked_inputs(
    rules_dir: str | Path,
    inputs: LockedEvaluationInputs,
    *,
    minimum_cases: int,
    include_candidates: bool = False,
    protected_error_costs: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate against a private snapshot of the exact locked input bytes."""

    from tools.aga import ManifestChangedFilesProvider

    with tempfile.TemporaryDirectory(prefix="aga-locked-evaluation-") as temporary:
        root = Path(temporary)
        corpus_path = root / "corpus.yaml"
        prs_root = root / "prs"
        seaf_path = root / "seaf.yaml"
        corpus_path.write_bytes(inputs.corpus_payload)
        seaf_path.write_bytes(inputs.seaf_payload)
        for relative, payload in inputs.fixture_files:
            target = prs_root / Path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        metrics = evaluate(
            rules_dir,
            corpus_path=corpus_path,
            prs_root=prs_root,
            seaf_path=seaf_path,
            minimum_cases=minimum_cases,
            include_candidates=include_candidates,
            protected_error_costs=protected_error_costs,
            changed_files_provider=ManifestChangedFilesProvider(),
        )
    metrics["fixtures_revision"] = inputs.fixtures_revision
    return metrics


def _capture_base_rules() -> dict[str, bytes]:
    """Capture one exact no-follow snapshot of every protected rule file."""

    rules_root = PKG_ROOT / "rules"
    expected_names = {*RULE_FILES, "severity-policy.yaml"}
    descriptor = open_directory_no_follow(rules_root)
    file_flags = (
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    captured: dict[str, bytes] = {}
    try:
        names = set(os.listdir(descriptor))
        if names != expected_names:
            raise ValidationError(
                f"protected rules inventory mismatch: {sorted(names)}",
                path=rules_root,
                code="base_rule_drift",
            )
        for name in sorted(expected_names):
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            path = rules_root / name
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValidationError(
                    "protected rule must be a non-hardlinked regular file",
                    path=path,
                    code="base_rule_drift",
                )
            child = os.open(name, file_flags, dir_fd=descriptor)
            try:
                opened = os.fstat(child)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                    or opened.st_size > DEFAULT_MAX_ARTIFACT_BYTES
                ):
                    raise ValidationError(
                        "protected rule changed during safe open",
                        path=path,
                        code="base_rule_drift",
                    )
                chunks: list[bytes] = []
                remaining = DEFAULT_MAX_ARTIFACT_BYTES + 1
                while remaining:
                    chunk = os.read(child, min(65_536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                payload = b"".join(chunks)
                final = os.fstat(child)
                if (
                    len(payload) > DEFAULT_MAX_ARTIFACT_BYTES
                    or not stat.S_ISREG(final.st_mode)
                    or final.st_nlink != 1
                    or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
                    != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                ):
                    raise ValidationError(
                        "protected rule changed while it was read",
                        path=path,
                        code="base_rule_drift",
                    )
                captured[name] = payload
            finally:
                os.close(child)
    except OSError as exc:
        raise ValidationError(
            f"cannot capture protected rules safely: {exc}",
            path=rules_root,
            code="base_rule_drift",
        ) from exc
    finally:
        os.close(descriptor)
    return captured


def _materialize_rule_payloads(directory: Path, payloads: Mapping[str, bytes]) -> None:
    directory.mkdir(mode=0o700)
    for name, payload in payloads.items():
        (directory / name).write_bytes(payload)


def _all_rules_from_payloads(payloads: Mapping[str, bytes]) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="aga-locked-rules-") as temporary:
        rules_dir = Path(temporary) / "rules"
        _materialize_rule_payloads(rules_dir, payloads)
        return _all_rules(rules_dir)


def _evaluate_base_rule_payloads(
    payloads: Mapping[str, bytes], inputs: LockedEvaluationInputs
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="aga-locked-rules-") as temporary:
        rules_dir = Path(temporary) / "rules"
        _materialize_rule_payloads(rules_dir, payloads)
        return _evaluate_with_locked_inputs(rules_dir, inputs, minimum_cases=15)


def _apply_mutation_to_payloads(
    payloads: Mapping[str, bytes],
    destination: Path,
    mutation: Mapping[str, Any],
    new_version: str,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="aga-locked-rules-") as temporary:
        rules_dir = Path(temporary) / "rules"
        _materialize_rule_payloads(rules_dir, payloads)
        return apply_mutation(rules_dir, destination, mutation, new_version)


def _all_rules(directory: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for name in RULE_FILES:
        document = strict_load_yaml(directory / name, expected_type=dict)
        rules = document.get("rules")
        if not isinstance(rules, list):
            raise ValidationError("rules must be a list", path=directory / name,
                                  field="rules", code="schema_type")
        result.extend(dict(rule) for rule in rules)
    return result


def _precedent_candidates() -> list[tuple[Path, dict[str, Any], str]]:
    candidates: list[tuple[Path, dict[str, Any], str]] = []
    for path in sorted((PKG_ROOT / "precedents" / "cases").glob("*.md")):
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
        if metadata.get("status") == "pending":
            candidates.append((path, metadata, body))
    candidates.sort(key=lambda item: (precedent_priority(item[1]), item[1].get("date", ""), item[0].name))
    return candidates


def find_pending_precedent() -> tuple[Path | None, dict[str, Any] | None]:
    candidates = _precedent_candidates()
    if not candidates:
        return None, None
    path, metadata, _ = candidates[0]
    return path, metadata


def _target_file(mutation: Mapping[str, Any]) -> str:
    rule_id = mutation.get("rule_id")
    if not rule_id and mutation.get("type") == "add_rule":
        rule_id = mutation.get("rule", {}).get("id")
    if not isinstance(rule_id, str) or "-" not in rule_id:
        raise ValueError("mutation requires a rule id with a known domain")
    filename = DOMAIN_FILE.get(rule_id.split("-", 1)[0])
    if not filename:
        raise ValueError(f"unsupported rule domain in {rule_id!r}")
    return filename


def _node_mapping(
    node: yaml.Node | None, *, label: str
) -> dict[str, tuple[yaml.Node, yaml.Node]]:
    if not isinstance(node, yaml.MappingNode):
        raise ValueError(f"{label} must be a YAML mapping")
    result: dict[str, tuple[yaml.Node, yaml.Node]] = {}
    for key, value in node.value:
        if not isinstance(key, yaml.ScalarNode) or key.value in result:
            raise ValueError(f"{label} has an invalid or duplicate key")
        result[key.value] = (key, value)
    return result


def _dump_fragment(value: Any, *, indent: int) -> str:
    """Serialize a new node without re-emitting its surrounding document."""

    dumped = yaml.dump(
        value,
        Dumper=_IndentedSafeDumper,
        allow_unicode=True,
        sort_keys=False,
        width=100,
        default_flow_style=False,
    ).rstrip("\n")
    prefix = " " * indent
    return "\n".join(prefix + line if line else "" for line in dumped.splitlines())


def _apply_text_patches(
    text: str, patches: Sequence[tuple[int, int, str]]
) -> str:
    """Apply non-overlapping character patches from right to left."""

    ordered = sorted(patches, key=lambda item: (item[0], item[1]))
    previous_end = -1
    for start, end, _replacement in ordered:
        if start < 0 or end < start or end > len(text) or start < previous_end:
            raise ValueError("candidate patch contains an invalid or overlapping span")
        previous_end = end
    result = text
    for start, end, replacement in reversed(ordered):
        result = result[:start] + replacement + result[end:]
    return result


def _rule_nodes(text: str, rule_id: str) -> tuple[yaml.SequenceNode, yaml.MappingNode]:
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    root_items = _node_mapping(root, label="rules document")
    rules_pair = root_items.get("rules")
    if rules_pair is None or not isinstance(rules_pair[1], yaml.SequenceNode):
        raise ValueError("rules document has no YAML rules sequence")
    rules_node = rules_pair[1]
    matches: list[yaml.MappingNode] = []
    for item in rules_node.value:
        item_values = _node_mapping(item, label="rule")
        identifier = item_values.get("id")
        if (
            identifier is not None
            and isinstance(identifier[1], yaml.ScalarNode)
            and identifier[1].value == rule_id
        ):
            matches.append(item)
    if len(matches) != 1:
        raise ValueError(f"target rule {rule_id!r} is absent or duplicated")
    return rules_node, matches[0]


def _replace_scalar(
    node: yaml.Node, value: str, *, label: str
) -> tuple[int, int, str]:
    if not isinstance(node, yaml.ScalarNode):
        raise ValueError(f"{label} must be a scalar")
    return node.start_mark.index, node.end_mark.index, value


def _patch_rule_text(
    before: str,
    document: Mapping[str, Any],
    mutation: Mapping[str, Any],
    new_version: str,
) -> tuple[str, dict[str, Any]]:
    """Apply a validated mutation while preserving all unrelated bytes."""

    expected = dict(document)
    expected["rules"] = [dict(rule) for rule in document["rules"]]
    mutation_type = mutation["type"]
    rule_id = mutation.get("rule_id")

    if mutation_type == "add_rule":
        rule = dict(mutation["rule"])
        rule.setdefault("status", "candidate")
        expected["rules"].append(rule)
        root = yaml.compose(before, Loader=yaml.SafeLoader)
        root_items = _node_mapping(root, label="rules document")
        rules_pair = root_items.get("rules")
        if rules_pair is None or not isinstance(rules_pair[1], yaml.SequenceNode):
            raise ValueError("rules document has no YAML rules sequence")
        rules_node = rules_pair[1]
        fragment = _dump_fragment([rule], indent=rules_node.start_mark.column)
        insertion = rules_node.end_mark.index
        separator = "\n" if before[:insertion].endswith("\n") else "\n\n"
        return _apply_text_patches(
            before, [(insertion, insertion, separator + fragment + "\n")]
        ), expected

    if not isinstance(rule_id, str):
        raise ValueError("mutation requires a target rule")
    _rules_node, target_node = _rule_nodes(before, rule_id)
    target_values = _node_mapping(target_node, label=f"rule {rule_id}")
    expected_rule = next(rule for rule in expected["rules"] if rule["id"] == rule_id)
    patches: list[tuple[int, int, str]] = []

    if mutation_type == "add_exception":
        exception = dict(mutation["exception"])
        exception.setdefault(
            "id", f"EXC-{rule_id}-{len(expected_rule.get('exceptions', [])) + 1:03d}"
        )
        exception["added_in"] = new_version
        expected_rule.setdefault("exceptions", []).append(exception)
        pair = target_values.get("exceptions")
        if pair is None or not isinstance(pair[1], yaml.SequenceNode):
            raise ValueError(f"rule {rule_id} has no exceptions sequence")
        key_node, sequence_node = pair
        if not sequence_node.value or sequence_node.flow_style:
            start = sequence_node.start_mark.index
            if start > key_node.end_mark.index and before[start - 1 : start] == " ":
                start -= 1
            replacement = "\n" + _dump_fragment(
                list(expected_rule["exceptions"]),
                indent=key_node.start_mark.column + 2,
            )
            patches.append((start, sequence_node.end_mark.index, replacement))
        else:
            insertion = sequence_node.end_mark.index - sequence_node.end_mark.column
            fragment = _dump_fragment(
                [exception], indent=key_node.start_mark.column + 2
            )
            patches.append((insertion, insertion, fragment + "\n"))
    elif mutation_type == "adjust_severity":
        expected_rule["severity"] = mutation["new_severity"]
        if "severity" not in target_values:
            raise ValueError(f"rule {rule_id} has no severity")
        patches.append(
            _replace_scalar(
                target_values["severity"][1],
                mutation["new_severity"],
                label="severity",
            )
        )
    elif mutation_type == "activate_rule":
        expected_rule["status"] = "active"
        if "status" not in target_values:
            raise ValueError(f"rule {rule_id} has no status")
        patches.append(
            _replace_scalar(target_values["status"][1], "active", label="status")
        )
    elif mutation_type == "deprecate_rule":
        expected_rule["status"] = "deprecated"
        expected_rule["deprecated_reason"] = mutation["reason"]
        expected_rule["deprecated_evidence"] = mutation["evidence"]
        if "status" not in target_values:
            raise ValueError(f"rule {rule_id} has no status")
        if "deprecated_reason" in target_values or "deprecated_evidence" in target_values:
            raise ValueError("deprecation metadata already exists")
        status_key, status_node = target_values["status"]
        patches.append(_replace_scalar(status_node, "deprecated", label="status"))
        line_end = before.find("\n", status_node.end_mark.index)
        if line_end < 0:
            insertion = len(before)
            prefix = "\n"
        else:
            insertion = line_end + 1
            prefix = ""
        metadata = _dump_fragment(
            {
                "deprecated_reason": mutation["reason"],
                "deprecated_evidence": mutation["evidence"],
            },
            indent=status_key.start_mark.column,
        )
        patches.append((insertion, insertion, prefix + metadata + "\n"))
    else:
        raise ValueError(f"unsupported mutation applicator: {mutation_type}")

    return _apply_text_patches(before, patches), expected


def apply_mutation(src_rules: str | Path, dst_rules: str | Path,
                   mutation: Mapping[str, Any], new_version: str) -> tuple[str, str]:
    """Apply one already-validated mutation to a disposable rules copy."""
    source = Path(src_rules)
    destination = Path(dst_rules)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=False)
    filename = _target_file(mutation)
    target = destination / filename
    before = target.read_text(encoding="utf-8")
    document = strict_load_yaml(target, expected_type=dict)
    after, expected = _patch_rule_text(before, document, mutation, new_version)
    reproduced = strict_load_yaml_text(after, source=target, expected_type=dict)
    if reproduced != expected:
        raise ValueError("format-preserving mutation does not match expected semantics")
    target.write_text(after, encoding="utf-8")
    # Loading the full candidate validates duplicate IDs, detect operators and
    # security policy before fitness sees it.
    load_rules(destination, include_candidates=True)
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/rules/{filename}", tofile=f"b/rules/{filename}"))
    if not diff:
        raise ValueError("mutation produced an empty diff")
    return diff, filename


def render_pr_body(context: Mapping[str, Any]) -> str:
    template = (PKG_ROOT / "templates" / "evolution-pr.md").read_text(encoding="utf-8")
    for key, value in context.items():
        template = template.replace("{{" + key + "}}", str(value))
    unresolved = [part for part in template.split() if "{{" in part]
    if unresolved:
        raise ValueError(f"unresolved evolution template placeholders: {unresolved}")
    return template


def _verify_locked_corpus(
    precedent: Mapping[str, Any],
) -> LockedEvaluationInputs:
    corpus_path = PKG_ROOT / "golden" / "corpus.yaml"
    lock_path = PKG_ROOT / "golden" / "corpus.lock.json"
    seaf_path = PKG_ROOT / "fixtures" / "seaf.yaml"

    def read_locked(path: Path) -> bytes:
        try:
            relative = path.relative_to(PKG_ROOT).as_posix()
            return safe_read_bytes(
                PKG_ROOT,
                relative,
                max_bytes=DEFAULT_MAX_ARTIFACT_BYTES,
                reject_hardlinks=True,
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise ValidationError(
                f"protected evaluation input is unavailable: {exc}",
                path=path,
                code="same_cycle_corpus_change",
            ) from exc

    try:
        lock_payload = read_locked(lock_path)

        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate corpus-lock key: {key}")
                result[key] = value
            return result

        lock = json.loads(lock_payload.decode("utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(
            f"protected corpus lock unavailable: {exc}",
            path=lock_path,
            code="corpus_lock_error",
        ) from exc
    expected_lock_keys = {
        "schema",
        "approved_at",
        "approval",
        "corpus_sha256",
        "fixtures_sha256",
        "seaf_fixture_sha256",
        "expected_sha256",
        "approved_cases",
        "note",
    }
    if not isinstance(lock, dict) or set(lock) != expected_lock_keys \
            or lock.get("schema") != "aga.corpus-lock/v2":
        raise ValidationError(
            "protected corpus lock has an invalid exact schema",
            path=lock_path,
            code="corpus_lock_error",
        )
    corpus_payload = read_locked(corpus_path)
    corpus_hash = hashlib.sha256(corpus_payload).hexdigest()
    if lock.get("corpus_sha256") != corpus_hash:
        raise ValidationError("corpus differs from the approved pre-cycle snapshot",
                              path=corpus_path, code="same_cycle_corpus_change")
    corpus = strict_load_yaml_text(corpus_payload, source=corpus_path, expected_type=dict)
    expected_hash = _json_sha256({case["id"]: case["expected"] for case in corpus["cases"]})
    if expected_hash != lock.get("expected_sha256"):
        raise ValidationError("existing expected ground truth differs from protected snapshot",
                              path=corpus_path, code="expected_changed")
    approved_ids = lock.get("approved_cases")
    if approved_ids != [case["id"] for case in corpus["cases"]]:
        raise ValidationError("corpus case set differs from approved snapshot", path=corpus_path,
                              code="corpus_case_set_changed")
    fixture_tree_hash, fixture_files = _capture_fixtures(approved_ids)
    if lock.get("fixtures_sha256") != fixture_tree_hash:
        raise ValidationError(
            "materialized golden fixtures differ from the approved pre-cycle snapshot",
            path=PKG_ROOT / "golden" / "prs",
            code="same_cycle_corpus_change",
        )
    seaf_payload = read_locked(seaf_path)
    seaf_hash = hashlib.sha256(seaf_payload).hexdigest()
    if lock.get("seaf_fixture_sha256") != seaf_hash:
        raise ValidationError(
            "SEAF registry differs from the approved pre-cycle snapshot",
            path=seaf_path,
            code="same_cycle_corpus_change",
        )
    golden_case = precedent.get("golden_case")
    matching = [case for case in corpus["cases"] if case.get("id") == golden_case]
    if len(matching) != 1:
        raise ValidationError("precedent golden case is absent or duplicated", path=corpus_path,
                              field="cases", code="anti_goodhart")
    case = matching[0]
    expected_origin = f"precedent:{precedent['id']}"
    if case.get("origin") != expected_origin:
        raise ValidationError(f"golden case origin must be exactly {expected_origin}",
                              path=corpus_path, field=f"cases.{golden_case}.origin",
                              code="wrong_precedent_origin")
    fixture_map = dict(fixture_files)
    manifest_name = f"{golden_case}/meta.yaml"
    manifest_payload = fixture_map.get(manifest_name)
    files_prefix = f"{golden_case}/files/"
    if manifest_payload is None or not any(
        name.startswith(files_prefix) for name in fixture_map
    ):
        raise ValidationError(
            "golden case is not materially present",
            path=PKG_ROOT / "golden" / "prs" / str(golden_case),
            code="unmaterialized_case",
        )
    manifest = strict_load_yaml_text(
        manifest_payload,
        source=PKG_ROOT / "golden" / "prs" / manifest_name,
        expected_type=dict,
    )
    if manifest.get("id") != golden_case:
        raise ValidationError(
            "golden case manifest has the wrong id",
            path=PKG_ROOT / "golden" / "prs" / manifest_name,
            code="unmaterialized_case",
        )
    return LockedEvaluationInputs(
        corpus=corpus,
        corpus_lock_payload=lock_payload,
        corpus_payload=corpus_payload,
        corpus_sha256=corpus_hash,
        fixture_files=fixture_files,
        fixture_tree_sha256=fixture_tree_hash,
        seaf_payload=seaf_payload,
        seaf_sha256=seaf_hash,
        fixtures_revision=_combined_fixtures_revision(fixture_tree_hash, seaf_hash),
    )


def _distilled_precedent_text(text: str, *, source: str | Path, version: str) -> str:
    """Patch only precedent lifecycle fields and preserve every other byte."""

    metadata, _body = parse_frontmatter(text, source=str(source))
    if metadata.get("status") != "pending":
        raise ValueError("only a pending precedent can be distilled")
    if not text.startswith("---\n"):
        raise ValueError("precedent frontmatter must use LF delimiters")
    delimiter = text.find("\n---\n", 4)
    if delimiter < 0:
        raise ValueError("precedent frontmatter closing delimiter is missing")
    metadata_start = 4
    metadata_text = text[metadata_start:delimiter]
    values = _node_mapping(
        yaml.compose(metadata_text, Loader=yaml.SafeLoader),
        label="precedent frontmatter",
    )
    if "status" not in values:
        raise ValueError("precedent has no lifecycle status")
    status_node = values["status"][1]
    patches: list[tuple[int, int, str]] = [
        (
            metadata_start + status_node.start_mark.index,
            metadata_start + status_node.end_mark.index,
            "distilled",
        )
    ]
    distilled = values.get("distilled_in")
    if distilled is not None:
        patches.append(
            (
                metadata_start + distilled[1].start_mark.index,
                metadata_start + distilled[1].end_mark.index,
                version,
            )
        )
    else:
        status_end = metadata_start + status_node.end_mark.index
        line_end = text.find("\n", status_end)
        if line_end < 0 or line_end > delimiter:
            line_end = delimiter
        patches.append((line_end + 1, line_end + 1, f"distilled_in: {version}\n"))
    result = _apply_text_patches(text, patches)
    result_metadata, _ = parse_frontmatter(result, source=str(source))
    if (
        result_metadata.get("status") != "distilled"
        or result_metadata.get("distilled_in") != version
    ):
        raise ValueError("distilled precedent patch failed semantic verification")
    return result


def _distilled_precedent(path: Path, version: str) -> str:
    return _distilled_precedent_text(
        path.read_text(encoding="utf-8"), source=path, version=version
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _artifact_manifest(build: Path, *, cycle_id: str, version_from: str,
                       version_to: str, gate_checks: Sequence[Mapping[str, Any]],
                       precedent_path: Path,
                       base_rule_hashes: Mapping[str, str]) -> dict[str, Any]:
    names = ["rules.diff", "metrics-baseline.json", "metrics-candidate.json",
             "evolution-pr.md", "CHANGELOG-entry.md", precedent_path.name]
    hashes = {name: _sha256(build / name) for name in names}
    candidate_rule_hashes = {name: _sha256(build / "candidate-rules" / name)
                             for name in [*RULE_FILES, "severity-policy.yaml"]}
    rule_names = {*RULE_FILES, "severity-policy.yaml"}
    if set(base_rule_hashes) != rule_names:
        raise ValueError("captured base rule hash inventory is incomplete")
    return {
        "schema": "aga.candidate-manifest/v1", "cycle_id": cycle_id,
        "version_from": version_from, "version_to": version_to,
        "gate_passed": all(check["passed"] for check in gate_checks),
        "artifacts": hashes, "base_rules": dict(base_rule_hashes),
        "candidate_rules": candidate_rule_hashes,
        "precedent_artifact": precedent_path.name,
        "human_confirmation_required": True, "auto_merge": False,
    }


def _publish_local_dry_run(
    request: PublishRequest,
) -> dict[str, Any]:
    """Execute the only publisher permitted inside the local evolver.

    External publisher implementations belong to a separately authorised
    integration entrypoint.  Keeping this boundary structural prevents an
    injected object from turning a local candidate run into a network, push,
    approval, or merge operation.  The result is validated before it can be
    persisted as evidence.
    """

    validate_publish_request(request)
    selected = DryRunPublisher()
    if selected.requires_network is not False:
        raise PublisherPolicyError("local evolution publisher must not require network access")

    result = selected.publish(request)
    if type(result) is not PublicationResult:
        raise PublisherPolicyError("local evolution publisher returned an invalid result type")
    expected_artifacts = tuple(request.artifacts.keys())
    if (
        result.publisher != selected.name
        or result.status != "dry_run"
        or result.cycle_id != request.cycle_id
        or result.artifacts != expected_artifacts
        or result.external_side_effects is not False
        or result.branch_name is not None
        or result.draft_pr_url is not None
    ):
        raise PublisherPolicyError(
            "local evolution publisher result violates the no-side-effect contract"
        )
    return result.as_dict()


def run_cycle(*, max_attempts: int = 3) -> int:
    if max_attempts < 1 or max_attempts > 3:
        print("max_attempts должен быть в диапазоне 1..3", file=sys.stderr)
        return 2
    build = PKG_ROOT / "build"
    build.mkdir(exist_ok=True)
    version = (PKG_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    cycle_id = f"aga-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    print(f"AGA Evolver · skill v{version}\n{'=' * 58}")
    try:
        precedent_path, precedent = find_pending_precedent()
        if not precedent or precedent_path is None:
            print("Нет pending-прецедентов — кандидат не создаётся.")
            return 0
        if precedent.get("architect_action") not in {"override", "missed"} \
                or not precedent.get("architect") or not precedent.get("rationale"):
            raise ValidationError("precedent lacks an approved architect action",
                                  path=precedent_path, code="unapproved_precedent")
        provenance = f"precedent:{precedent['id']}"
        print(f"[1/6] Прецедент: {precedent['id']} ({precedent_path.name}), "
              f"architect_action={precedent['architect_action']}")
        locked_inputs = _verify_locked_corpus(precedent)
        print(f"[2/6] Anti-Goodhart OK: protected corpus sha256="
              f"{locked_inputs.corpus_sha256[:12]}…, "
              f"origin={provenance}")
        base_rule_payloads = _capture_base_rules()
        base_rule_hashes = {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in base_rule_payloads.items()
        }
        base = _evaluate_base_rule_payloads(base_rule_payloads, locked_inputs)
        _write_json(build / "metrics-baseline.json", base)
        print(f"[3/6] Baseline ({base['cases_evaluated']} cases): "
              f"precision={base['precision']}, recall={base['recall']}, "
              f"weighted cost={base['weighted_cost']}")

        raw_mutations = precedent.get("proposed_mutations")
        if raw_mutations is None:
            raw_mutations = [precedent.get("proposed_mutation")]
        if not isinstance(raw_mutations, list) or not raw_mutations or raw_mutations == [None]:
            raise ValidationError("precedent has no candidate mutations", path=precedent_path,
                                  code="missing_mutation")
        mutations = raw_mutations[:max_attempts]
        attempts_log: list[dict[str, Any]] = []
        all_rules = _all_rules_from_payloads(base_rule_payloads)
        for attempt_number, raw_mutation in enumerate(mutations, 1):
            attempt: dict[str, Any] = {"attempt": attempt_number, "result": "started"}
            try:
                mutation = validate_mutation(raw_mutation, all_rules,
                                             approved_provenance={provenance})
                mutation_type = mutation["type"]
                new_version = bump(version, SEMVER_BUMP[mutation_type])
                changed_rule = mutation.get("rule_id") or mutation.get("rule", {}).get("id")
                print(f"[4/6] Попытка {attempt_number}/{len(mutations)}: {mutation_type} → "
                      f"{changed_rule} (v{version} → v{new_version})")
                diff, filename = _apply_mutation_to_payloads(
                    base_rule_payloads,
                    build / "candidate-rules",
                    mutation,
                    new_version,
                )
                before = base_rule_payloads[filename].decode("utf-8")
                after = (build / "candidate-rules" / filename).read_text(encoding="utf-8")
                guard_candidate_changes([CandidateChange(f"rules/{filename}", before, after)])
                (build / "rules.diff").write_text(diff, encoding="utf-8")
                include_candidates = mutation_type == "add_rule"
                candidate = _evaluate_with_locked_inputs(
                    build / "candidate-rules", locked_inputs, minimum_cases=15,
                    include_candidates=include_candidates,
                    protected_error_costs=base["error_costs"])
                _write_json(build / "metrics-candidate.json", candidate)
                passed, checks = gate(
                    base,
                    candidate,
                    changed_rule_ids={changed_rule} if changed_rule else None,
                    mutation=mutation,
                )
                attempt.update({"mutation": mutation, "metrics_before": base,
                                "metrics_after": candidate, "gate_checks": checks,
                                "result": "passed" if passed else "failed_gate"})
                attempts_log.append(attempt)
                evolution_event = {
                    "event_type": "evolution_attempt", "cycle_id": cycle_id,
                    "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "precedent": provenance, "base_revision": base["rules_revision"],
                    "candidate_revision": candidate["rules_revision"],
                    "corpus_revision": base["corpus_revision"], "mutation": mutation,
                    "attempt": attempt_number, "metrics_before": {
                        "precision": base["precision"], "recall": base["recall"],
                        "weighted_cost": base["weighted_cost"]},
                    "metrics_after": {"precision": candidate["precision"],
                                      "recall": candidate["recall"],
                                      "weighted_cost": candidate["weighted_cost"]},
                    "gate_checks": checks, "result": attempt["result"],
                }
                print(f"[5/6] Candidate ({candidate['cases_evaluated']} cases): "
                      f"precision={candidate['precision']}, recall={candidate['recall']}, "
                      f"weighted cost={candidate['weighted_cost']} → "
                      f"GATE {'PASS' if passed else 'FAIL'}")
                if not passed:
                    append_jsonl_atomic(
                        PKG_ROOT / "logs" / "evolution.jsonl", evolution_event)
                    for check in checks:
                        if not check["passed"]:
                            print(f"      - {check['id']}: {check['description']}")
                    continue

                today = dt.datetime.strptime(cycle_id[4:12], "%Y%m%d").date().isoformat()
                cycle_suffix = cycle_id.rsplit("-", 1)[-1]
                branch = (
                    f"skill/evolution-{today}-{changed_rule or mutation_type}-{cycle_suffix}"
                )
                report = markdown_report(base, candidate, checks)
                pr_body = render_pr_body({
                    "version_from": version, "version_to": new_version,
                    "mutation_type": mutation_type, "rule_id": changed_rule or "—",
                    "precedent": provenance, "rationale": str(precedent["rationale"]).strip(),
                    "branch": branch, "date": today, "diff": diff,
                    "metrics_table": report,
                })
                (build / "evolution-pr.md").write_text(pr_body, encoding="utf-8")
                changelog = (
                    f"## v{new_version} — {today}\n"
                    f"- {mutation_type} для {changed_rule} (provenance: {provenance}); "
                    f"precision {base['precision']} → {candidate['precision']}, "
                    f"weighted cost {base['weighted_cost']} → {candidate['weighted_cost']} "
                    f"на {candidate['cases_evaluated']} cases.\n")
                (build / "CHANGELOG-entry.md").write_text(changelog, encoding="utf-8")
                (build / precedent_path.name).write_text(
                    _distilled_precedent(precedent_path, new_version), encoding="utf-8")
                if _capture_base_rules() != base_rule_payloads:
                    raise ValidationError(
                        "protected base rules changed during the evolution cycle",
                        path=PKG_ROOT / "rules",
                        code="base_rule_drift",
                    )
                if (PKG_ROOT / "VERSION").read_text(encoding="utf-8").strip() != version:
                    raise ValidationError(
                        "VERSION changed during the evolution cycle",
                        path=PKG_ROOT / "VERSION",
                        code="base_rule_drift",
                    )
                manifest = _artifact_manifest(
                    build, cycle_id=cycle_id, version_from=version, version_to=new_version,
                    gate_checks=checks, precedent_path=precedent_path,
                    base_rule_hashes=base_rule_hashes)
                _write_json(build / "candidate-manifest.json", manifest)
                publication = _publish_local_dry_run(PublishRequest(
                    cycle_id=cycle_id,
                    artifacts={name: build / name for name in manifest["artifacts"]},
                    branch_name=branch, commit_message=f"AGA evolution {new_version}",
                    draft=True, requested_actions=(),
                    metadata={"gate_passed": True, "auto_merge": False}))
                _write_json(build / "publisher-result.json", publication)
                attempts_log[-1]["publisher_result"] = publication
                attempts_log[-1]["generated_artifacts"] = manifest["artifacts"]
                _write_json(build / "evolution-attempts.json", attempts_log)
                evolution_event["generated_artifacts"] = manifest["artifacts"]
                evolution_event["publisher_result"] = publication
                append_jsonl_atomic(
                    PKG_ROOT / "logs" / "evolution.jsonl", evolution_event)
                print("[6/6] Артефакты готовы: evolution-pr.md, rules.diff, "
                      "metrics-*.json, candidate-manifest.json")
                print(f"      Publisher: {publication['status']} (external_side_effects=false)")
                print("      Merge — только человеком.")
                return 0
            except (MutationValidationError, UnsupportedMutationTypeError, PolicyViolation,
                    FitnessValidationError, ValidationError, ValueError, OSError) as exc:
                attempt.update({"result": "validation_error", "error": str(exc)})
                attempts_log.append(attempt)
                append_jsonl_atomic(PKG_ROOT / "logs" / "evolution.jsonl", {
                    "event_type": "evolution_attempt", "cycle_id": cycle_id,
                    "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "precedent": provenance, "attempt": attempt_number,
                    "result": "validation_error", "error": str(exc),
                    "gate_checks": [],
                })
                print(f"      Попытка отклонена: {exc}", file=sys.stderr)
        _write_json(build / "evolution-attempts.json", attempts_log)
        print(f"CIRCUIT BREAKER: проверены все {len(attempts_log)} доступных кандидата; "
              "ни один не прошёл. Автоматическое ослабление правил запрещено.")
        return 1
    except (ValidationError, FitnessValidationError, OSError, ValueError) as exc:
        print(f"EVOLUTION INPUT ERROR: {exc}", file=sys.stderr)
        return 2


def main() -> None:
    parser = argparse.ArgumentParser(description="AGA candidate-only evolution cycle")
    parser.add_argument("--demo", action="store_true", help="offline cycle on approved fixtures")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    raise SystemExit(run_cycle(max_attempts=args.max_attempts))


if __name__ == "__main__":
    main()
