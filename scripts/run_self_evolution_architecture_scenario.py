#!/usr/bin/env python3
"""Validate and remediate the declared SEAF-004 edge in an E2E scenario graph."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGA_ROOT = REPOSITORY_ROOT / "aga-skill"
if str(AGA_ROOT) not in sys.path:
    sys.path.insert(0, str(AGA_ROOT))

from tools.remediation import (  # noqa: E402
    COMPONENT_ID_RE,
    RemediationNotAvailable,
    propose_remediation,
)
from tools.repository_snapshot import (  # noqa: E402
    DEFAULT_ARCHTOOL_COMMIT,
    DEFAULT_ARCHTOOL_PATH,
    DEFAULT_SEAF_CORE_COMMIT,
    DEFAULT_SEAF_CORE_PATH,
    RepositorySnapshotBuilder,
)
from tools.seaf_review import prepare_seaf_review  # noqa: E402
from tools.validation import strict_load_yaml_text  # noqa: E402


SCENARIO_SCHEMA = "aga.self-evolution-scenario/v2"
OUTPUT_SCHEMA = "aga.self-evolution-architecture-run/v1"
EVENT_SCHEMA = "aga.self-evolution-architecture-event/v1"
VALIDATION_SCHEMA = "aga.self-evolution-scenario-validation/v1"
RULE_ID = "SEAF-004"
MAX_SCENARIO_BYTES = 5 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SCENARIO_ID_RE = re.compile(r"^e2e-[0-9a-f]{16}$")
SAFE_TARGET_STATUSES = frozenset({"strategic", "tactical", "tolerate", "eliminate"})
EventSink = Callable[[dict[str, Any]], None]

COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "AGA Synthetic E2E",
    "GIT_AUTHOR_EMAIL": "aga-e2e@example.invalid",
    "GIT_COMMITTER_NAME": "AGA Synthetic E2E",
    "GIT_COMMITTER_EMAIL": "aga-e2e@example.invalid",
}

DOCHUB_TEXT = """aga:
  schema: seaf-core/v1.4.0
  extensions: [aga.project/v1]
  data_classification: synthetic-public
imports:
  - aga-extension.yaml
  - model/components.yaml
  - model/integrations.yaml
  - model/adrs.yaml
"""

VERIFIED_DOCHUB_TEXT = """$package:
  aga-self-evolution:
    name: AGA generated self-evolution scenario
    vendor: AGA
    description: Controlled synthetic-public Architecture-as-Code review.
    version: 1.0.0

aga:
  schema: seaf-core/v1.4.0
  extensions:
    - aga.project/v1
  data_classification: synthetic-public

imports:
  - seaf-core-v1.4.0-overlay.yaml
  - metamodel/aga-extension.yaml
  - model/components.yaml
  - model/integrations.yaml
  - model/adrs.yaml
  - model/contexts.yaml
"""


class ArchitectureScenarioError(RuntimeError):
    """A stable, non-sensitive validation failure suitable for CLI output."""


@dataclass(frozen=True)
class MaterializedScenarioRepository:
    """Caller-owned ephemeral Architecture-as-Code repository coordinates."""

    repository: Path
    base: str
    head: str
    edge_map: Mapping[str, str]
    declared_edge_id: str
    materialized_entity_id: str
    dependency_mode: str


def _fail(code: str) -> None:
    raise ArchitectureScenarioError(code)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("scenario_json_duplicate_key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    _fail("scenario_json_nonfinite")


def _strict_json(payload: bytes) -> dict[str, Any]:
    if not payload:
        _fail("scenario_file_empty")
    if len(payload) > MAX_SCENARIO_BYTES:
        _fail("scenario_file_too_large")
    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except ArchitectureScenarioError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchitectureScenarioError("scenario_json_invalid") from exc
    if not isinstance(document, dict):
        _fail("scenario_document_invalid")
    return document


def load_scenario(path: Path) -> dict[str, Any]:
    """Read one regular, non-symlink JSON file with a fixed size ceiling."""

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArchitectureScenarioError("scenario_file_unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            _fail("scenario_file_not_regular")
        if metadata.st_size <= 0:
            _fail("scenario_file_empty")
        if metadata.st_size > MAX_SCENARIO_BYTES:
            _fail("scenario_file_too_large")
        chunks: list[bytes] = []
        remaining = MAX_SCENARIO_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_SCENARIO_BYTES:
            _fail("scenario_file_too_large")
        return _strict_json(payload)
    finally:
        os.close(descriptor)


def _required_string(
    value: Any,
    *,
    code: str,
    maximum: int = 512,
    pattern: re.Pattern[str] | None = None,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail(code)
    if pattern is not None and pattern.fullmatch(value) is None:
        _fail(code)
    return value


def _validate_graph(graph: Any) -> tuple[dict[str, Mapping[str, Any]], list[Mapping[str, Any]]]:
    if not isinstance(graph, Mapping):
        _fail("scenario_graph_invalid")
    if set(graph) != {"nodes", "edges"}:
        _fail("scenario_graph_shape_invalid")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not nodes:
        _fail("scenario_nodes_invalid")
    if not isinstance(edges, list) or not edges:
        _fail("scenario_edges_invalid")

    node_map: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping):
            _fail("scenario_node_invalid")
        if not {"id", "label", "kind", "target_status"} <= set(node) or not set(
            node
        ) <= {"id", "label", "kind", "target_status", "replaced_by"}:
            _fail("scenario_node_shape_invalid")
        node_id = _required_string(
            node.get("id"),
            code="scenario_node_id_invalid",
            maximum=128,
            pattern=COMPONENT_ID_RE,
        )
        if node_id in node_map:
            _fail("scenario_node_id_duplicate")
        _required_string(node.get("label"), code="scenario_node_label_invalid", maximum=256)
        _required_string(node.get("kind"), code="scenario_node_kind_invalid", maximum=64)
        target_status = _required_string(
            node.get("target_status"), code="scenario_node_status_invalid", maximum=64
        )
        if target_status not in SAFE_TARGET_STATUSES:
            _fail("scenario_node_status_invalid")
        node_map[node_id] = node

    for node_id, node in node_map.items():
        successor = node.get("replaced_by")
        if successor is None:
            continue
        successor_id = _required_string(
            successor,
            code="scenario_node_successor_invalid",
            maximum=128,
            pattern=COMPONENT_ID_RE,
        )
        if successor_id == node_id or successor_id not in node_map:
            _fail("scenario_node_successor_invalid")

    edge_ids: set[str] = set()
    validated_edges: list[Mapping[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, Mapping):
            _fail("scenario_edge_invalid")
        if not {"id", "from", "to", "protocol", "status"} <= set(edge) or not set(
            edge
        ) <= {
            "id",
            "from",
            "to",
            "protocol",
            "status",
            "expected_rule",
            "replacement_to",
        }:
            _fail("scenario_edge_shape_invalid")
        edge_id = _required_string(
            edge.get("id"), code="scenario_edge_id_invalid", maximum=128, pattern=ID_RE
        )
        if edge_id in edge_ids:
            _fail("scenario_edge_id_duplicate")
        edge_ids.add(edge_id)
        source = _required_string(
            edge.get("from"),
            code="scenario_edge_source_invalid",
            maximum=128,
            pattern=COMPONENT_ID_RE,
        )
        target = _required_string(
            edge.get("to"),
            code="scenario_edge_target_invalid",
            maximum=128,
            pattern=COMPONENT_ID_RE,
        )
        if source not in node_map:
            _fail("scenario_edge_source_missing")
        if target not in node_map:
            _fail("scenario_edge_target_missing")
        if source == target:
            _fail("scenario_edge_self_reference")
        _required_string(edge.get("protocol"), code="scenario_edge_protocol_invalid", maximum=128)
        if edge.get("status") != "unchecked":
            _fail("scenario_edge_status_invalid")
        expected_rule = edge.get("expected_rule")
        if expected_rule is not None:
            _required_string(
                expected_rule, code="scenario_edge_expected_rule_invalid", maximum=64, pattern=ID_RE
            )
        replacement = edge.get("replacement_to")
        if replacement is not None:
            replacement_id = _required_string(
                replacement,
                code="scenario_edge_replacement_invalid",
                maximum=128,
                pattern=COMPONENT_ID_RE,
            )
            if replacement_id not in node_map or replacement_id == source:
                _fail("scenario_edge_replacement_missing")
        if (expected_rule is None) != (replacement is None):
            _fail("scenario_edge_declaration_incomplete")
        validated_edges.append(edge)
    return node_map, validated_edges


def validate_scenario(document: Any) -> tuple[dict[str, Mapping[str, Any]], list[Mapping[str, Any]]]:
    if not isinstance(document, Mapping):
        _fail("scenario_document_invalid")
    if document.get("schema") != SCENARIO_SCHEMA:
        _fail("scenario_schema_invalid")
    _required_string(
        document.get("scenario_id"),
        code="scenario_id_invalid",
        maximum=20,
        pattern=SCENARIO_ID_RE,
    )
    if document.get("classification") != "synthetic-public":
        _fail("scenario_classification_invalid")
    return _validate_graph(document.get("graph"))


def _declared_edge(
    node_map: Mapping[str, Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    declared = [edge for edge in edges if edge.get("expected_rule") == RULE_ID]
    if not declared:
        _fail("scenario_declared_edge_missing")
    if len(declared) != 1:
        _fail("scenario_declared_edge_ambiguous")
    edge = declared[0]
    target = node_map[str(edge["to"])]
    successor = edge.get("replacement_to")
    if successor is None:
        _fail("scenario_declared_successor_missing")
    if target.get("target_status") != "eliminate":
        _fail("scenario_declared_edge_not_defect")
    if target.get("replaced_by") != successor:
        _fail("scenario_declared_successor_mismatch")
    successor_node = node_map[str(successor)]
    if successor_node.get("target_status") == "eliminate":
        _fail("scenario_declared_successor_invalid")
    return edge


def validate_only(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one generated scenario without materializing or remediating it."""

    input_sha256 = _canonical_digest(document)
    node_map, edges = validate_scenario(document)
    declared = _declared_edge(node_map, edges)
    summary = document.get("summary")
    if not isinstance(summary, Mapping):
        _fail("scenario_summary_invalid")
    expected_counts = {
        "systems": len(node_map),
        "flows": len(edges),
        "architecture_checks": sum(
            edge.get("expected_rule") == RULE_ID for edge in edges
        ),
    }
    for field, expected in expected_counts.items():
        value = summary.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value != expected:
            _fail("scenario_summary_mismatch")
    tests = document.get("tests")
    if not isinstance(tests, list) or not tests:
        _fail("scenario_tests_invalid")
    tests_count = summary.get("tests")
    if (
        isinstance(tests_count, bool)
        or not isinstance(tests_count, int)
        or tests_count != len(tests)
    ):
        _fail("scenario_summary_mismatch")
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "validated",
        "scenario_id": str(document["scenario_id"]),
        "classification": str(document["classification"]),
        "input_sha256": input_sha256,
        "graph_sha256": _canonical_digest(document["graph"]),
        "summary": {
            "nodes": len(node_map),
            "edges": len(edges),
            "tests": len(tests),
            "declared_findings": expected_counts["architecture_checks"],
        },
        "declared_remediation": {
            "rule_id": RULE_ID,
            "edge_id": str(declared["id"]),
            "source": str(declared["from"]),
            "eliminated_target": str(declared["to"]),
            "declared_successor": str(declared["replacement_to"]),
        },
        "checks": [
            {"id": "scenario.schema", "passed": True},
            {"id": "graph.exact_shape", "passed": True},
            {"id": "graph.all_references_resolve", "passed": True},
            {"id": "graph.summary_counts_match", "passed": True},
            {"id": "graph.one_declared_seaf004", "passed": True},
            {"id": "graph.declared_successor_resolves", "passed": True},
        ],
    }


def _git(repository: Path, *arguments: str, date: str | None = None) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    controlled_home = repository.parent / "git-home"
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
            **COMMIT_ENV,
        }
    )
    if date is not None:
        environment.update({"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
    try:
        completed = subprocess.run(
            [
                "git",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "commit.gpgSign=false",
                "-c",
                "tag.gpgSign=false",
                *arguments,
            ],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchitectureScenarioError("scenario_git_failed") from exc
    return completed.stdout.strip()


def _write(repository: Path, relative: str, content: str) -> None:
    target = repository / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _commit(repository: Path, message: str, date: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message, date=date)
    return _git(repository, "rev-parse", "HEAD")


def _materialized_edge_id(edge_id: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", edge_id.lower()).strip("_-")
    if not slug or not slug[0].isalnum():
        slug = "edge"
    digest = hashlib.sha256(edge_id.encode("utf-8")).hexdigest()[:10]
    return f"scenario.{slug[:72]}_{digest}"


def _yaml_document(value: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        dict(value),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def _architecture_documents(
    graph: Mapping[str, Any],
) -> tuple[str, str, str, dict[str, str]]:
    components: dict[str, dict[str, Any]] = {}
    for node in graph["nodes"]:
        component = {
            "title": node["label"],
            "entity": "component",
            "description": f"Synthetic {node['kind']} component {node['id']}.",
            "owner": f"Synthetic {str(node['kind']).title()} Team",
            "criticality": "high",
            "target_status": node["target_status"],
        }
        if node.get("replaced_by") is not None:
            component["replaced_by"] = node["replaced_by"]
        components[node["id"]] = component

    edge_map: dict[str, str] = {}
    materialized_ids: set[str] = set()
    baseline_integrations: dict[str, dict[str, Any]] = {}
    integrations: dict[str, dict[str, Any]] = {}
    for edge in graph["edges"]:
        materialized_id = _materialized_edge_id(str(edge["id"]))
        if materialized_id in materialized_ids:
            _fail("scenario_edge_materialization_collision")
        materialized_ids.add(materialized_id)
        edge_map[str(edge["id"])] = materialized_id
        materialized = {
            "title": f"Synthetic flow {edge['id']}",
            "description": f"Materialized scenario edge {edge['id']}.",
            "from": edge["from"],
            "to": edge["to"],
            "protocol": edge["protocol"],
        }
        integrations[materialized_id] = materialized
        if edge.get("expected_rule") != RULE_ID:
            baseline_integrations[materialized_id] = materialized
    return (
        _yaml_document({"components": components}),
        _yaml_document({"seaf.app.integrations": baseline_integrations}),
        _yaml_document({"seaf.app.integrations": integrations}),
        edge_map,
    )


def _verified_documents(
    graph: Mapping[str, Any],
    *,
    components_text: str,
) -> dict[str, str]:
    architecture = REPOSITORY_ROOT / "architecture"
    documents: dict[str, str] = {
        "dochub.yaml": VERIFIED_DOCHUB_TEXT,
        "model/components.yaml": components_text,
        "model/integrations.yaml": "seaf.app.integrations: {}\n",
        "model/adrs.yaml": "seaf.change.adr: {}\n",
        "model/contexts.yaml": _yaml_document(
            {
                "contexts": {
                    "demo.self_evolution": {
                        "title": "Generated self-evolution landscape",
                        "location": "AGA/Self Evolution",
                        "presentation": "integration",
                        "extra-links": False,
                        "components": [node["id"] for node in graph["nodes"]],
                    }
                }
            }
        ),
    }
    copies = {
        "metamodel/aga-extension.yaml": architecture
        / "metamodel"
        / "aga-extension.yaml",
        "overrides/seaf-core-v1.4.0/entities/ta/presentation/components.yaml": architecture
        / "overrides"
        / "seaf-core-v1.4.0"
        / "entities"
        / "ta"
        / "presentation"
        / "components.yaml",
        "overrides/seaf-core-v1.4.0/entities/ta/presentation/templates/list.md": architecture
        / "overrides"
        / "seaf-core-v1.4.0"
        / "entities"
        / "ta"
        / "presentation"
        / "templates"
        / "list.md",
    }
    try:
        for relative, source in copies.items():
            documents[relative] = source.read_text(encoding="utf-8")
        overlay = (architecture / "seaf-core-v1.4.0-overlay.yaml").read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as exc:
        raise ArchitectureScenarioError("scenario_verified_documents_unavailable") from exc
    documents["seaf-core-v1.4.0-overlay.yaml"] = overlay.replace(
        "vendor/seaf-core/", "architecture/vendor/seaf-core/"
    )
    return documents


def _ensure_gitlink_placeholders(repository: Path) -> None:
    for relative in (DEFAULT_ARCHTOOL_PATH, DEFAULT_SEAF_CORE_PATH):
        (repository / relative).mkdir(parents=True, exist_ok=True)


def _materialize_repository(
    repository: Path,
    graph: Mapping[str, Any],
    *,
    dependency_mode: str,
) -> tuple[str, str, dict[str, str]]:
    (
        components_text,
        baseline_integrations_text,
        integrations_text,
        edge_map,
    ) = _architecture_documents(graph)
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main", "--object-format=sha1")
    if dependency_mode == "verified":
        base_documents = _verified_documents(graph, components_text=components_text)
        # The live review must inspect the proposed change, not re-send the
        # whole already-existing landscape through the model.  Keep every
        # healthy scenario edge in the immutable base and add only the one
        # generated SEAF-004 edge in ``head``.  The checked-out head still
        # contains the complete synthetic graph used by the UI and by the
        # deterministic workers, while the AGA prepare receipt stays below the
        # managed MCP transport limit.
        base_documents["model/integrations.yaml"] = baseline_integrations_text
    else:
        try:
            extension_text = (
                REPOSITORY_ROOT / "architecture" / "metamodel" / "aga-extension.yaml"
            ).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ArchitectureScenarioError("scenario_extension_unavailable") from exc
        base_documents = {
            "dochub.yaml": DOCHUB_TEXT,
            "aga-extension.yaml": extension_text,
            "model/components.yaml": components_text,
            "model/integrations.yaml": "seaf.app.integrations: {}\n",
            "model/adrs.yaml": "seaf.change.adr: {}\n",
        }
    for relative, content in base_documents.items():
        _write(repository, relative, content)
    if dependency_mode == "verified":
        _git(repository, "add", "--all")
        for dependency_path, commit_sha in (
            (DEFAULT_ARCHTOOL_PATH, DEFAULT_ARCHTOOL_COMMIT),
            (DEFAULT_SEAF_CORE_PATH, DEFAULT_SEAF_CORE_COMMIT),
        ):
            _git(
                repository,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{commit_sha},{dependency_path}",
            )
        _git(
            repository,
            "commit",
            "-m",
            "materialize verified synthetic scenario base",
            date="2026-07-19T08:00:00Z",
        )
        base = _git(repository, "rev-parse", "HEAD")
    else:
        base = _commit(
            repository,
            "materialize synthetic scenario base",
            "2026-07-19T08:00:00Z",
        )
    _write(repository, "model/integrations.yaml", integrations_text)
    if dependency_mode == "verified":
        _git(repository, "add", "model/integrations.yaml")
        _git(
            repository,
            "commit",
            "-m",
            "materialize synthetic scenario graph",
            date="2026-07-19T08:01:00Z",
        )
        head = _git(repository, "rev-parse", "HEAD")
        _ensure_gitlink_placeholders(repository)
    else:
        head = _commit(
            repository,
            "materialize synthetic scenario graph",
            "2026-07-19T08:01:00Z",
        )
    return base, head, edge_map


def materialize_scenario_repository(
    document: Mapping[str, Any],
    repository: Path,
    *,
    dependency_mode: str = "fixture",
) -> MaterializedScenarioRepository:
    """Materialize the validated generated graph for local or live runners.

    The caller owns ``repository`` and its parent directory.  The target must
    not already exist, which prevents mixing a scenario with stale files.
    """

    validate_only(document)
    if dependency_mode not in {"fixture", "verified"}:
        _fail("scenario_dependency_mode_invalid")
    node_map, edges = validate_scenario(document)
    declared = _declared_edge(node_map, edges)
    target = Path(repository)
    if target.exists() or target.is_symlink() or not target.parent.is_dir():
        _fail("scenario_repository_target_invalid")
    base, head, edge_map = _materialize_repository(
        target,
        document["graph"],
        dependency_mode=dependency_mode,
    )
    edge_id = str(declared["id"])
    return MaterializedScenarioRepository(
        repository=target,
        base=base,
        head=head,
        edge_map=dict(edge_map),
        declared_edge_id=edge_id,
        materialized_entity_id=edge_map[edge_id],
        dependency_mode=dependency_mode,
    )


def _prepare_review(repository: Path, base: str, head: str) -> dict[str, Any]:
    try:
        with RepositorySnapshotBuilder(
            repository, base, head, dependency_mode="fixture"
        ).build() as snapshot:
            return prepare_seaf_review(snapshot)
    except ArchitectureScenarioError:
        raise
    except Exception as exc:
        raise ArchitectureScenarioError("scenario_real_review_failed") from exc


def _defect_keys(findings: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {
        (str(finding.get("rule_id")), str(finding.get("canonical_defect")))
        for finding in findings
    }


def _graph_from_materialized_patch(
    before_graph: Mapping[str, Any],
    *,
    patch_text: str,
    edge_map: Mapping[str, str],
) -> dict[str, Any]:
    try:
        document = strict_load_yaml_text(patch_text, source="model/integrations.yaml")
    except Exception as exc:
        raise ArchitectureScenarioError("scenario_patch_document_invalid") from exc
    flows = document.get("seaf.app.integrations")
    if not isinstance(flows, Mapping) or set(flows) != set(edge_map.values()):
        _fail("scenario_patch_inventory_changed")
    after_graph = deepcopy(before_graph)
    for edge in after_graph["edges"]:
        flow = flows.get(edge_map[str(edge["id"])])
        if not isinstance(flow, Mapping):
            _fail("scenario_patch_inventory_changed")
        if flow.get("from") != edge["from"] or flow.get("protocol") != edge["protocol"]:
            _fail("scenario_patch_changed_unrelated_field")
        target = flow.get("to")
        if not isinstance(target, str):
            _fail("scenario_patch_target_invalid")
        edge["to"] = target
    _validate_graph(after_graph)
    return after_graph


def _canonical_digest(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArchitectureScenarioError("scenario_document_invalid") from exc
    return hashlib.sha256(payload).hexdigest()


def _only_declared_target_changed(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    edge_id: str,
    successor: str,
) -> bool:
    if before.get("nodes") != after.get("nodes"):
        return False
    before_edges = before.get("edges")
    after_edges = after.get("edges")
    if not isinstance(before_edges, list) or not isinstance(after_edges, list):
        return False
    if len(before_edges) != len(after_edges):
        return False
    changed = 0
    for original, candidate in zip(before_edges, after_edges, strict=True):
        if not isinstance(original, Mapping) or not isinstance(candidate, Mapping):
            return False
        if original.get("id") != candidate.get("id"):
            return False
        if original.get("id") != edge_id:
            if original != candidate:
                return False
            continue
        expected = dict(original)
        expected["to"] = successor
        if dict(candidate) != expected:
            return False
        changed += 1
    return changed == 1


def run_scenario(
    document: Mapping[str, Any],
    *,
    event_sink: EventSink | None = None,
) -> dict[str, Any]:
    """Run a real SEAF review/remediation/re-review in an ephemeral Git repo."""

    sequence = 0

    def emit(stage: str, **payload: Any) -> None:
        nonlocal sequence
        if event_sink is None:
            return
        sequence += 1
        event_sink(
            {
                "schema": EVENT_SCHEMA,
                "type": "result" if stage == "result" else "stage",
                "sequence": sequence,
                "stage": stage,
                **payload,
            }
        )

    input_sha256 = _canonical_digest(document)
    node_map, edges = validate_scenario(document)
    declared = _declared_edge(node_map, edges)
    edge_id = str(declared["id"])
    successor = str(declared["replacement_to"])
    before_graph = deepcopy(document["graph"])

    with tempfile.TemporaryDirectory(prefix="aga-scenario-architecture-") as temporary:
        repository = Path(temporary) / "architecture"
        materialized = materialize_scenario_repository(document, repository)
        base = materialized.base
        head = materialized.head
        edge_map = materialized.edge_map
        materialized_entity = materialized.materialized_entity_id
        emit(
            "materialized",
            actor="AGA Scenario Materializer",
            detail="Полный граф записан в изолированный SEAF Architecture-as-Code Git repository.",
            nodes=len(before_graph["nodes"]),
            edges=len(before_graph["edges"]),
            base_revision=base,
            head_revision=head,
            declared_edge_id=edge_id,
            materialized_entity_id=materialized_entity,
        )

        emit(
            "review_started",
            actor="AGA Deterministic SEAF Review",
            detail="Запущена настоящая проверка base → head через RepositorySnapshotBuilder.",
            engine="prepare_seaf_review",
        )
        prepared_before = _prepare_review(repository, base, head)
        findings_before = list(prepared_before["deterministic_findings"])
        declared_findings = [
            finding
            for finding in findings_before
            if finding.get("rule_id") == RULE_ID
            and finding.get("entity_id") == materialized_entity
        ]
        if not declared_findings:
            _fail("scenario_marker_not_confirmed_by_real_review")
        if len(declared_findings) != 1:
            _fail("scenario_real_finding_ambiguous")
        finding = declared_findings[0]
        if finding.get("location", "").rsplit("/", 1)[-1] != "to":
            _fail("scenario_real_finding_endpoint_mismatch")
        emit(
            "finding",
            actor="AGA Deterministic SEAF Review",
            detail="SEAF-004 подтверждён вычислением по materialized SEAF graph, а не marker-полем.",
            scenario_edge_id=edge_id,
            finding=finding,
            findings_total=len(findings_before),
        )

        try:
            patch = propose_remediation(finding, repository)
        except RemediationNotAvailable as exc:
            raise ArchitectureScenarioError(
                f"scenario_remediation_unavailable_{exc.code}"
            ) from exc
        if (
            patch.entity_id != materialized_entity
            or patch.endpoint != "to"
            or patch.eliminated_component != declared["to"]
            or patch.replacement_component != successor
        ):
            _fail("scenario_real_patch_mismatch")
        patch_payload = patch.as_dict()
        emit(
            "patch",
            actor="AGA propose_remediation",
            detail="Сформирован реальный однострочный candidate patch к integrations.yaml.",
            scenario_edge_id=edge_id,
            patch=patch_payload,
        )

        _write(repository, patch.artifact, patch.after_text)
        patched_head = _commit(
            repository,
            f"AGA scenario remediation: {patch.summary}",
            "2026-07-19T08:02:00Z",
        )
        after_graph = _graph_from_materialized_patch(
            before_graph,
            patch_text=patch.after_text,
            edge_map=edge_map,
        )
        target_change_only = _only_declared_target_changed(
            before_graph,
            after_graph,
            edge_id=edge_id,
            successor=successor,
        )

        # base → patched_head reviews the complete resulting graph, including
        # every flow originally introduced by the scenario, not just the line
        # changed by the candidate patch.
        prepared_after = _prepare_review(repository, base, patched_head)
        findings_after = list(prepared_after["deterministic_findings"])
        emit(
            "rereview",
            actor="AGA Deterministic SEAF Review",
            detail="Повторная настоящая проверка base → patched candidate завершена.",
            engine="prepare_seaf_review",
            patched_revision=patched_head,
            findings_total=len(findings_after),
            findings=findings_after,
        )

        before_keys = _defect_keys(findings_before)
        after_keys = _defect_keys(findings_after)
        target_key = (str(finding["rule_id"]), str(finding["canonical_defect"]))
        target_closed = target_key not in after_keys
        new_findings = sorted(after_keys - before_keys)
        remaining_seaf = [
            item for item in findings_after if item.get("rule_id") == RULE_ID
        ]
        checks = [
            {
                "id": "graph.references_before",
                "label": "Все node/edge/replacement ссылки исходного графа разрешены",
                "passed": True,
            },
            {
                "id": "review.real_seaf004_before",
                "label": "SEAF-004 подтверждён реальным deterministic SEAF review",
                "passed": True,
            },
            {
                "id": "remediation.propose_remediation",
                "label": "Patch создан существующим AGA propose_remediation",
                "passed": True,
            },
            {
                "id": "remediation.single_edge_target_only",
                "label": "Изменено только поле to заявленного ребра",
                "passed": target_change_only,
            },
            {
                "id": "graph.references_after",
                "label": "Все ссылки исправленного полного графа разрешены",
                "passed": True,
            },
            {
                "id": "review.target_finding_closed",
                "label": "Исходный canonical SEAF-004 finding исчез",
                "passed": target_closed,
            },
            {
                "id": "review.no_new_findings",
                "label": "Повторная проверка не создала новых findings",
                "passed": not new_findings,
            },
            {
                "id": "review.no_remaining_seaf004",
                "label": "В полном candidate graph не осталось SEAF-004",
                "passed": not remaining_seaf,
            },
        ]
        gate_passed = all(check["passed"] for check in checks)
        emit(
            "gate",
            actor="AGA Safety Gate",
            detail=(
                "Защитный gate пройден. Candidate остаётся локальным."
                if gate_passed
                else "Защитный gate отклонил candidate."
            ),
            passed=gate_passed,
            checks=checks,
        )

        result = {
            "schema": OUTPUT_SCHEMA,
            "status": "completed" if gate_passed else "gate_failed",
            "scenario_id": str(document["scenario_id"]),
            "classification": str(document["classification"]),
            "execution": {
                "real": True,
                "review_engine": "prepare_seaf_review",
                "remediation_engine": "propose_remediation",
                "workspace": "ephemeral-git",
                "external_side_effects": False,
                "merge_performed": False,
            },
            "input_sha256": input_sha256,
            "revisions": {
                "base": base,
                "head": head,
                "patched_head": patched_head,
            },
            "summary": {
                "nodes": len(before_graph["nodes"]),
                "edges": len(before_graph["edges"]),
                "findings_before": len(findings_before),
                "findings_after": len(findings_after),
                "changed_edges": 1 if target_change_only else 0,
                "gate_passed": gate_passed,
            },
            "before": {
                "graph": before_graph,
                "graph_sha256": _canonical_digest(before_graph),
                "prepared_review_key": prepared_before["review_key"],
                "findings": findings_before,
                "verdict": prepared_before["provisional_verdict"],
            },
            "remediation": {
                "strategy": "declared_successor",
                "rule_id": RULE_ID,
                "edge_id": edge_id,
                "materialized_entity_id": materialized_entity,
                "source": str(declared["from"]),
                "previous_to": str(declared["to"]),
                "replacement_to": successor,
                "changed_fields": ["to"],
                "patch": patch_payload,
                "operation": {
                    "op": "replace",
                    "entity": f"graph.edges[{edge_id}]",
                    "field": "to",
                    "before": str(declared["to"]),
                    "after": successor,
                },
            },
            "after": {
                "graph": after_graph,
                "graph_sha256": _canonical_digest(after_graph),
                "prepared_review_key": prepared_after["review_key"],
                "findings": findings_after,
                "verdict": prepared_after["provisional_verdict"],
            },
            "gate": {
                "passed": gate_passed,
                "target_finding_closed": target_closed,
                "new_findings": [
                    {"rule_id": rule_id, "canonical_defect": defect}
                    for rule_id, defect in new_findings
                ],
                "checks": checks,
            },
        }
        emit("result", result=result)
        return result


def run_path(path: Path, *, event_sink: EventSink | None = None) -> dict[str, Any]:
    return run_scenario(load_scenario(path), event_sink=event_sink)


def validate_path(path: Path) -> dict[str, Any]:
    return validate_only(load_scenario(path))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument(
        "--events-jsonl",
        action="store_true",
        help="Flush real stage events and the final result as JSON Lines.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate exact generated graph shape and references without remediation.",
    )
    args = parser.parse_args(argv)
    last_jsonl_sequence = 0

    def jsonl_sink(event: dict[str, Any]) -> None:
        nonlocal last_jsonl_sequence
        sequence = event.get("sequence")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            last_jsonl_sequence = max(last_jsonl_sequence, sequence)
        print(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            flush=True,
        )

    try:
        if args.validate_only:
            result = validate_path(args.scenario)
            if args.events_jsonl:
                jsonl_sink(
                    {
                        "schema": EVENT_SCHEMA,
                        "type": "result",
                        "sequence": 1,
                        "stage": "validation",
                        "result": result,
                    }
                )
        else:
            result = run_path(
                args.scenario,
                event_sink=jsonl_sink if args.events_jsonl else None,
            )
    except ArchitectureScenarioError as exc:
        result = {
            "schema": VALIDATION_SCHEMA if args.validate_only else OUTPUT_SCHEMA,
            "status": "failed",
            "code": str(exc),
        }
        if args.events_jsonl:
            jsonl_sink(
                {
                    "schema": EVENT_SCHEMA,
                    "type": "error",
                    "sequence": last_jsonl_sequence + 1,
                    "stage": "error",
                    "error": result,
                }
            )
        else:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    if not args.events_jsonl:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.validate_only:
        return 0
    return 0 if result["gate"]["passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
