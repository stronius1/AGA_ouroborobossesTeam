# -*- coding: utf-8 -*-
"""Submission review pipeline for trusted SEAF-native Git snapshots.

This module does not implement a model adapter or transport. It converts one
immutable :class:`RepositorySnapshot` into canonical entities, deterministic
findings and bounded semantic tasks. A semantic task set is deliberately
incomplete until the separate finalize boundary accepts validated agent JSON.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from tools.aga import deduplicate_findings, load_rules, verdict_from
from tools.repository_snapshot import RepositorySnapshot, rules_directory_sha256
from tools.seaf_native import (
    CanonicalSnapshot,
    ChangedArtifact,
    SeafCanonicalAdapter,
    SourceProvenance,
)
from tools.validation import ValidationError


RULE_SOURCE_REFS = {
    "SEAF-001": "aga-skill/rules/seaf-checks.yaml#/rules/0",
}
SEMANTIC_RULES = ("PRIN-004", "PRIN-005", "PRIN-006", "PRIN-007")


def _changed_artifacts(snapshot: RepositorySnapshot) -> tuple[ChangedArtifact, ...]:
    native = getattr(snapshot, "changed_artifacts", None)
    if native is not None:
        return tuple(native)
    status_map = getattr(snapshot, "changed_statuses", {})
    artifacts: list[ChangedArtifact] = []
    for relative in snapshot.changed_paths:
        path = snapshot.root / relative
        payload = path.read_bytes() if path.is_file() else None
        status = status_map.get(relative, "modified") if isinstance(status_map, Mapping) else "modified"
        artifacts.append(
            ChangedArtifact(
                path=relative,
                status=str(status),
                sha256=hashlib.sha256(payload).hexdigest() if payload is not None else None,
                source_ref=SourceProvenance(
                    file=relative,
                    pointer="",
                    commit=snapshot.revision.head_commit,
                    sha256=hashlib.sha256(payload).hexdigest() if payload is not None else None,
                ),
            )
        )
    return tuple(artifacts)


def _finding(
    *,
    rule_id: str,
    artifact: str,
    location: str,
    evidence: str,
    suggested_fix: str,
    snapshot: RepositorySnapshot,
    source_provenance: SourceProvenance,
    entity_id: str,
    source_ref: str,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": "blocker",
        "confidence": 1.0,
        "artifact": artifact,
        "location": location,
        "evidence": evidence,
        "source_ref": source_ref,
        "suggested_fix": suggested_fix,
        "canonical_defect": f"{rule_id}:{location}",
        "base_revision": snapshot.revision.base_commit,
        "head_revision": snapshot.revision.head_commit,
        "source_provenance": source_provenance.as_dict(),
        "origin": "deterministic",
        "entity_id": entity_id,
    }


def deterministic_findings(
    canonical: CanonicalSnapshot,
    snapshot: RepositorySnapshot,
    *,
    source_refs: Mapping[str, str],
) -> tuple[dict[str, Any], ...]:
    """Evaluate native structural references and lifecycle guardrails."""

    systems = {system.id: system for system in canonical.systems}
    changed_entities = {
        artifact.path: set(getattr(artifact, "changed_pointers", ()))
        for artifact in canonical.changed_artifacts
    }
    all_changed_pointers = set().union(*changed_entities.values()) if changed_entities else set()

    def pointer(section: str, entity_id: str, field: str | None = None) -> str:
        escaped_section = section.replace("~", "~0").replace("/", "~1")
        escaped_id = entity_id.replace("~", "~0").replace("/", "~1")
        value = f"/{escaped_section}/{escaped_id}"
        if field is not None:
            value += "/" + field.replace("~", "~0").replace("/", "~1")
        return value

    findings: list[dict[str, Any]] = []
    for flow in canonical.integrations:
        flow_changed = flow.source_ref.pointer in changed_entities.get(
            flow.source_ref.file, set()
        )
        endpoint_changed = any(
            (
                pointer("components", endpoint) in all_changed_pointers
                if systems.get(endpoint) is None
                else pointer("components", endpoint, "target_status")
                in all_changed_pointers
            )
            for endpoint in (flow.source, flow.target)
        )
        if not flow_changed and not endpoint_changed:
            continue
        for endpoint_name, endpoint in (("from", flow.source), ("to", flow.target)):
            system = systems.get(endpoint)
            location = f"{flow.source_ref.pointer}/{endpoint_name}"
            if system is None:
                findings.append(
                    _finding(
                        rule_id="SEAF-001",
                        artifact=flow.source_ref.file,
                        location=location,
                        evidence=f"integration endpoint {endpoint!r} does not resolve to a component",
                        suggested_fix="Define the referenced SEAF component or correct the endpoint ID.",
                        snapshot=snapshot,
                        source_provenance=flow.source_ref,
                        entity_id=flow.id,
                        source_ref=source_refs["SEAF-001"],
                    )
                )
                continue
            if system.target_status == "eliminate":
                findings.append(
                    _finding(
                        rule_id="SEAF-004",
                        artifact=flow.source_ref.file,
                        location=location,
                        evidence=(
                            f"new integration endpoint {endpoint!r} has "
                            "target_status=eliminate"
                        ),
                        suggested_fix=(
                            "Use a strategic replacement or record an approved migration decision "
                            "before adding the dependency."
                        ),
                        snapshot=snapshot,
                        source_provenance=flow.source_ref,
                        entity_id=flow.id,
                        source_ref=source_refs["SEAF-004"],
                    )
                )
    return tuple(deduplicate_findings(findings))


def _deterministic_source_refs(workspace: Any) -> dict[str, str]:
    extension_path = ""
    for document in workspace.documents:
        package = document.data.get("$package")
        if isinstance(package, Mapping) and "aga-project" in package:
            extension_path = document.path
            break
    if not extension_path:
        raise ValueError("validated aga.project extension document is unavailable")
    return {
        **RULE_SOURCE_REFS,
        "SEAF-004": f"{extension_path}#/entities/components/schema",
    }


def _semantic_tasks(
    canonical: CanonicalSnapshot,
    rules: list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    by_id = {rule["id"]: rule for rule in rules}
    artifacts = [
        {
            "kind": kind,
            "id": item.id,
            "artifact": item.source_ref.file,
            "pointer": item.source_ref.pointer,
        }
        for kind, values in (
            ("system", canonical.systems),
            ("integration", canonical.integrations),
            ("adr", canonical.adrs),
            ("diagram", canonical.diagrams),
        )
        for item in values
    ]
    tasks: list[dict[str, Any]] = []
    for rule_id in SEMANTIC_RULES:
        rule = by_id[rule_id]
        tasks.append(
            {
                "rule_id": rule_id,
                "severity": rule["severity"],
                "statement": rule["statement"],
                "source_ref": rule["source_ref"],
                "allowed_artifacts": artifacts,
            }
        )
    return tuple(tasks)


def prepare_seaf_review(
    snapshot: RepositorySnapshot,
    *,
    rules_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare one deterministic result; semantic completion is mandatory."""

    # Load one immutable rule/policy pair for both task construction and the
    # provisional verdict.  The exact pair is returned to the stateful MCP
    # boundary so a per-repository rules directory cannot be replaced by the
    # process defaults during finalization.
    rules_root = (
        Path(rules_dir)
        if rules_dir is not None
        else Path(__file__).resolve().parents[1] / "rules"
    )
    rules_digest_before = rules_directory_sha256(rules_root)
    if rules_digest_before != snapshot.revision.rules_sha256:
        raise ValidationError(
            "rule files do not match snapshot provenance",
            path=rules_root,
            code="rules_provenance_mismatch",
        )
    rules, policy = load_rules(rules_dir)
    if rules_directory_sha256(rules_root) != rules_digest_before:
        raise ValidationError(
            "rule files changed while preparing the review",
            path=rules_root,
            code="rules_changed_during_review",
        )

    workspace = snapshot.resolve(
        max_files=1024,
        max_depth=64,
        max_total_bytes=32 * 1024 * 1024,
        max_yaml_nodes=750_000,
    )
    canonical = SeafCanonicalAdapter().adapt(
        workspace,
        revision=snapshot.revision,
        changed_artifacts=_changed_artifacts(snapshot),
    )
    snapshot.assert_integrity()
    deterministic = deterministic_findings(
        canonical,
        snapshot,
        source_refs=_deterministic_source_refs(workspace),
    )
    tasks = _semantic_tasks(canonical, rules)
    semantic_rule_catalog = {
        rule["id"]: rule for rule in rules if rule["id"] in SEMANTIC_RULES
    }
    provisional = verdict_from(deterministic, policy)
    task_digest = hashlib.sha256(
        json.dumps(tasks, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    review_key = hashlib.sha256(
        f"aga.prepare/v1\0{snapshot.content_sha256}\0{task_digest}".encode("utf-8")
    ).hexdigest()
    return {
        "schema": "aga.prepared-review/v1",
        "review_key": review_key,
        "status": "needs_semantic_review",
        "incomplete": True,
        "verdict": "incomplete",
        "provisional_verdict": provisional,
        "escalate": True,
        "deterministic_findings": list(deterministic),
        "semantic_tasks": list(tasks),
        "task_digest": task_digest,
        "canonical_snapshot": canonical.as_dict(),
        "review_provenance": snapshot.review_provenance,
        "semantic_rule_catalog": semantic_rule_catalog,
        "verdict_policy": policy,
    }


__all__ = [
    "RULE_SOURCE_REFS",
    "SEMANTIC_RULES",
    "deterministic_findings",
    "prepare_seaf_review",
]
