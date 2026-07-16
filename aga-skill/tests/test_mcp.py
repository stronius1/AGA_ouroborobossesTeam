# -*- coding: utf-8 -*-
"""Unit and Streamable HTTP contract tests for the AGA MCP boundary."""
from __future__ import annotations

import http.client
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROJECT_EXTENSION_TEXT = (
    ROOT.parent / "architecture" / "metamodel" / "aga-extension.yaml"
).read_text(encoding="utf-8")

from tools.mcp_server import (  # noqa: E402
    JsonRpcError,
    MCPApplication,
    MCPServer,
    MCPServerConfig,
    validate_json_schema,
)
from tools.review_service import (  # noqa: E402
    _materialized_path_commit,
    ReviewInputError,
    ReviewService,
    ReviewServiceError,
    SEMANTIC_RULE_IDS,
    TOOL_DEFINITIONS,
)
from scripts.run_mcp import build_parser  # noqa: E402
from tools.aga import load_rules  # noqa: E402
from tools.repository_snapshot import RepositorySnapshotBuilder  # noqa: E402
from tools.seaf_review import prepare_seaf_review  # noqa: E402


BASE = "1" * 40
HEAD = "2" * 40
DIAGRAM_TEXT = (
    "@startuml\n"
    'rectangle "AS.NEW synthetic source" as A\n'
    'rectangle "AS.OLD synthetic target" as B\n'
    "A --> B : synthetic event\n"
    "@enduml\n"
)


def fixture_callback(**_request):
    return {
        "artifacts": [
            {
                "entity_id": "AS.NEW",
                "artifact": "architecture/systems.yaml",
                "kind": "system_passport",
                "data": {
                    "id": "AS.NEW",
                    "name": "Synthetic payment profile",
                    "description": "A synthetic SEAF-native entity for contract tests.",
                    "target_status": "eliminate",
                },
                "source_ref": {
                    "file": "architecture/systems.yaml",
                    "pointer": "/components/AS.NEW",
                    "commit": HEAD,
                    "line": None,
                    "sha256": "a" * 64,
                },
                "change_status": "changed",
                "changed_pointers": [
                    "/components/AS.NEW",
                    "/components/AS.NEW/description",
                    "/components/AS.NEW/target_status",
                ],
            },
            {
                "entity_id": "IF.NEW",
                "artifact": "architecture/integrations.yaml",
                "kind": "integration_flow",
                "data": {"id": "IF.NEW", "from": "AS.NEW", "to": "AS.OLD"},
                "source_ref": {
                    "file": "architecture/integrations.yaml",
                    "pointer": "/seaf.app.integrations/IF.NEW",
                    "commit": HEAD,
                    "line": None,
                    "sha256": "b" * 64,
                },
                "change_status": "context",
                "changed_pointers": [],
            },
            {
                "entity_id": "D.NEW",
                "artifact": "architecture/context.puml",
                "kind": "diagram",
                "diagram_format": "plantuml",
                "data": {"text": DIAGRAM_TEXT},
                "source_ref": {
                    "file": "architecture/contexts.yaml",
                    "pointer": "/contexts/D.NEW",
                    "commit": HEAD,
                    "line": None,
                    "sha256": "c" * 64,
                },
                "content_source_ref": {
                    "file": "architecture/context.puml",
                    "pointer": "/contexts/D.NEW/text",
                    "commit": HEAD,
                    "line": None,
                    "sha256": hashlib.sha256(DIAGRAM_TEXT.encode("utf-8")).hexdigest(),
                },
                "change_status": "context",
                "changed_pointers": [],
            },
        ],
        "deterministic_findings": [],
    }


def deterministic_callback(**request):
    value = fixture_callback(**request)
    value["deterministic_findings"] = [
        {
            "rule_id": "SEAF-004",
            "severity": "blocker",
            "confidence": 1.0,
            "entity_id": "AS.NEW",
            "artifact": "architecture/systems.yaml",
            "location": "/components/AS.NEW/target_status",
            "evidence": "synthetic target is marked eliminate",
            "source_ref": "architecture/metamodel/aga-extension.yaml#/entities/components/schema",
            "suggested_fix": "Use the synthetic strategic replacement.",
        }
    ]
    return value


def prepare(service: ReviewService, review_id: str = "review-1") -> dict:
    return service.prepare_review(
        repository_id="synthetic-seaf",
        base=BASE,
        head=HEAD,
        review_id=review_id,
        entity_ids=["AS.NEW", "IF.NEW", "D.NEW"],
    )


def complete_result(prepared: dict, findings: list[dict] | None = None) -> dict:
    return {
        "status": "completed",
        "completed_rule_ids": list(SEMANTIC_RULE_IDS),
        "findings": findings or [],
    }


def semantic_finding(prepared: dict, **overrides) -> dict:
    artifact = next(item for item in prepared["artifacts"] if item["entity_id"] == "AS.NEW")
    source_refs = {item["rule_id"]: item["source_ref"] for item in prepared["semantic_tasks"]}
    value = {
        "rule_id": "PRIN-004",
        "severity": "major",
        "confidence": 0.91,
        "entity_id": "AS.NEW",
        "location": "/components/AS.NEW/description",
        "evidence": "The synthetic profile duplicates a prepared registry capability.",
        "evidence_refs": [artifact["evidence_ref"]],
        "source_ref": source_refs["PRIN-004"],
        "suggested_fix": "Reuse the prepared registry component.",
    }
    value.update(overrides)
    return value


class ReviewServiceTests(unittest.TestCase):
    def make_service(self, callback=fixture_callback, **kwargs) -> ReviewService:
        return ReviewService(callback, digest_secret="unit-test-secret", **kwargs)

    def test_prepare_is_deterministic_idempotent_and_opaque(self):
        calls = []

        def callback(**request):
            calls.append(request)
            return fixture_callback(**request)

        service = self.make_service(callback)
        first = prepare(service)
        second = prepare(service)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["status"], "ready")
        self.assertRegex(first["review_digest"], r"^rvw_[0-9a-f]{64}$")
        self.assertRegex(first["task_digest"], r"^tsk_[0-9a-f]{64}$")
        self.assertEqual(
            [task["rule_id"] for task in first["semantic_tasks"]],
            list(SEMANTIC_RULE_IDS),
        )
        artifacts = {item["entity_id"]: item for item in first["artifacts"]}
        self.assertEqual(artifacts["AS.NEW"]["change_status"], "changed")
        self.assertTrue(artifacts["AS.NEW"]["changed_pointers"])
        self.assertEqual(artifacts["IF.NEW"]["change_status"], "context")
        self.assertEqual(artifacts["IF.NEW"]["changed_pointers"], [])
        self.assertIsNone(artifacts["AS.NEW"]["content_provenance"])
        self.assertEqual(
            artifacts["D.NEW"]["content_provenance"]["file"],
            "architecture/context.puml",
        )
        self.assertEqual(
            artifacts["D.NEW"]["content_provenance"]["sha256"],
            hashlib.sha256(DIAGRAM_TEXT.encode("utf-8")).hexdigest(),
        )
        prin_005 = next(
            task for task in first["semantic_tasks"] if task["rule_id"] == "PRIN-005"
        )
        self.assertEqual(prin_005["entity_ids"], ["AS.NEW"])
        self.assertEqual(prin_005["context_entity_ids"], ["IF.NEW"])
        self.assertEqual(
            set(prin_005["evidence_refs"]),
            {artifacts["AS.NEW"]["evidence_ref"], artifacts["IF.NEW"]["evidence_ref"]},
        )
        self.assertEqual(
            set(calls[0]), {"repository_id", "base", "head", "review_id", "entity_ids"}
        )
        self.assertNotIn("path", " ".join(calls[0]))

    def test_review_id_conflict_fails_closed(self):
        service = self.make_service()
        prepare(service)
        with self.assertRaisesRegex(ReviewServiceError, "review_conflict"):
            service.prepare_review(
                repository_id="synthetic-seaf",
                base=BASE,
                head="3" * 40,
                review_id="review-1",
            )

    def test_prepare_requires_full_immutable_commit_ids(self):
        service = self.make_service()
        with self.assertRaises(ReviewInputError):
            service.prepare_review(
                repository_id="synthetic-seaf",
                base="1" * 7,
                head=HEAD,
                review_id="review-short-sha",
            )

    def test_materialized_path_commit_uses_longest_dependency_prefix(self):
        dependency = "3" * 40
        nested_dependency = "4" * 40
        commits = (
            ("architecture/vendor", dependency),
            ("architecture/vendor/nested", nested_dependency),
        )
        self.assertEqual(
            _materialized_path_commit(
                "architecture/vendor/nested/diagrams/view.puml", HEAD, commits
            ),
            nested_dependency,
        )
        self.assertEqual(
            _materialized_path_commit(
                "architecture/vendor/diagrams/view.puml", HEAD, commits
            ),
            dependency,
        )
        self.assertEqual(
            _materialized_path_commit("architecture/diagrams/view.puml", HEAD, commits),
            HEAD,
        )

    def test_prepare_requires_exact_artifact_source_provenance(self):
        def missing_sha256(**request):
            value = fixture_callback(**request)
            del value["artifacts"][0]["source_ref"]["sha256"]
            return value

        result = prepare(self.make_service(missing_sha256))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["artifacts"], [])
        self.assertEqual(result["analysis_errors"][0]["code"], "prepare_schema_error")

    def test_prepare_requires_strict_delta_metadata(self):
        callbacks = []

        def missing_status(**request):
            value = fixture_callback(**request)
            del value["artifacts"][0]["change_status"]
            return value

        callbacks.append(missing_status)

        def pointer_outside_entity(**request):
            value = fixture_callback(**request)
            value["artifacts"][0]["changed_pointers"] = [
                "/components/AS.OTHER/description"
            ]
            return value

        callbacks.append(pointer_outside_entity)

        def context_with_changed_pointer(**request):
            value = fixture_callback(**request)
            value["artifacts"][1]["changed_pointers"] = [
                "/seaf.app.integrations/IF.NEW/from"
            ]
            return value

        callbacks.append(context_with_changed_pointer)

        def diagram_without_content_provenance(**request):
            value = fixture_callback(**request)
            del value["artifacts"][2]["content_source_ref"]
            return value

        callbacks.append(diagram_without_content_provenance)

        def diagram_with_wrong_content_hash(**request):
            value = fixture_callback(**request)
            value["artifacts"][2]["content_source_ref"]["sha256"] = "0" * 64
            return value

        callbacks.append(diagram_with_wrong_content_hash)

        for index, callback in enumerate(callbacks):
            with self.subTest(callback=callback.__name__):
                result = prepare(
                    self.make_service(callback), f"review-invalid-delta-{index}"
                )
                self.assertEqual(result["status"], "incomplete")
                self.assertEqual(result["artifacts"], [])
                self.assertEqual(
                    result["analysis_errors"][0]["code"], "prepare_schema_error"
                )

    def test_ambiguous_deterministic_finding_is_not_heuristically_bound(self):
        def ambiguous(**request):
            value = fixture_callback(**request)
            value["artifacts"][1]["artifact"] = "architecture/systems.yaml"
            value["artifacts"][1]["source_ref"]["pointer"] = "/components/AS.NEW"
            value["artifacts"][1]["data"]["target_status"] = "eliminate"
            value["artifacts"][1]["change_status"] = "changed"
            value["artifacts"][1]["changed_pointers"] = [
                "/components/AS.NEW/target_status"
            ]
            value["deterministic_findings"] = [
                {
                    "rule_id": "SEAF-004",
                    "severity": "blocker",
                    "confidence": 1.0,
                    "artifact": "architecture/systems.yaml",
                    "location": "/components/AS.NEW/target_status",
                    "evidence": "synthetic ambiguous evidence",
                    "source_ref": "architecture/metamodel/aga-extension.yaml#/entities/components/schema",
                    "suggested_fix": "Bind the finding to one exact entity ID.",
                }
            ]
            return value

        result = prepare(self.make_service(ambiguous))
        self.assertTrue(result["incomplete"])
        self.assertEqual(
            result["analysis_errors"][-1]["code"], "deterministic_evidence_unbound"
        )
        self.assertEqual(result["deterministic_findings"], [])

    def test_unresolving_deterministic_location_is_dropped_fail_closed(self):
        def wrong_location(**request):
            value = deterministic_callback(**request)
            value["deterministic_findings"][0]["location"] = (
                "/components/AS.NEW/missing"
            )
            return value

        result = prepare(self.make_service(wrong_location))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["deterministic_findings"], [])
        self.assertIn(
            "deterministic_evidence_unbound",
            {item["code"] for item in result["analysis_errors"]},
        )

    def test_server_bound_deterministic_finding_preserves_dependency_commit(self):
        dependency_commit = "3" * 40

        def dependency_finding(**request):
            value = deterministic_callback(**request)
            value["artifacts"][0]["source_ref"]["commit"] = dependency_commit
            return value

        result = prepare(self.make_service(dependency_finding))
        accepted = result["deterministic_findings"][0]
        self.assertEqual(accepted["head_revision"], HEAD)
        self.assertEqual(accepted["source_provenance"]["commit"], dependency_commit)

    def test_deterministic_diagram_text_uses_exact_content_provenance(self):
        def diagram_finding(**request):
            value = fixture_callback(**request)
            diagram = value["artifacts"][2]
            diagram["change_status"] = "changed"
            diagram["changed_pointers"] = ["/contexts/D.NEW/text"]
            value["deterministic_findings"] = [
                {
                    "rule_id": "SEAF-004",
                    "severity": "blocker",
                    "confidence": 1.0,
                    "entity_id": "D.NEW",
                    "artifact": "architecture/context.puml",
                    "location": "/contexts/D.NEW/text",
                    "evidence": "Synthetic deterministic diagram-text evidence.",
                    "source_ref": (
                        "architecture/metamodel/aga-extension.yaml"
                        "#/entities/components/schema"
                    ),
                    "suggested_fix": "Update the synthetic diagram.",
                    "base_revision": BASE,
                    "head_revision": HEAD,
                    "source_provenance": dict(diagram["content_source_ref"]),
                }
            ]
            return value

        result = prepare(self.make_service(diagram_finding))
        diagram = next(
            item for item in result["artifacts"] if item["entity_id"] == "D.NEW"
        )
        accepted = result["deterministic_findings"][0]
        self.assertEqual(accepted["source_provenance"], diagram["content_provenance"])
        self.assertNotEqual(
            accepted["source_provenance"], diagram["source_provenance"]
        )

    def test_trusted_exact_deterministic_binding_can_report_impacted_context(self):
        def impacted_context(**request):
            value = fixture_callback(**request)
            integration = value["artifacts"][1]
            value["deterministic_findings"] = [
                {
                    "rule_id": "SEAF-004",
                    "severity": "blocker",
                    "confidence": 1.0,
                    "entity_id": "IF.NEW",
                    "artifact": "architecture/integrations.yaml",
                    "location": "/seaf.app.integrations/IF.NEW/to",
                    "evidence": (
                        "Synthetic unchanged flow is impacted by a changed endpoint."
                    ),
                    "source_ref": (
                        "architecture/metamodel/aga-extension.yaml"
                        "#/entities/components/schema"
                    ),
                    "suggested_fix": "Use the synthetic strategic endpoint.",
                    "base_revision": BASE,
                    "head_revision": HEAD,
                    "source_provenance": dict(integration["source_ref"]),
                }
            ]
            return value

        result = prepare(self.make_service(impacted_context))
        self.assertEqual(result["status"], "ready")
        accepted = result["deterministic_findings"][0]
        self.assertEqual(accepted["entity_id"], "IF.NEW")
        self.assertEqual(
            accepted["source_provenance"],
            next(
                item["source_provenance"]
                for item in result["artifacts"]
                if item["entity_id"] == "IF.NEW"
            ),
        )

    def test_context_deterministic_finding_without_exact_binding_is_dropped(self):
        def unbound_context(**request):
            value = fixture_callback(**request)
            value["deterministic_findings"] = [
                {
                    "rule_id": "SEAF-004",
                    "severity": "blocker",
                    "confidence": 1.0,
                    "artifact": "architecture/integrations.yaml",
                    "location": "/seaf.app.integrations/IF.NEW/to",
                    "evidence": "Synthetic context-only callback claim.",
                    "source_ref": (
                        "architecture/metamodel/aga-extension.yaml"
                        "#/entities/components/schema"
                    ),
                    "suggested_fix": "Bind the trusted impacted context exactly.",
                }
            ]
            return value

        result = prepare(self.make_service(unbound_context))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["deterministic_findings"], [])
        self.assertIn(
            "deterministic_evidence_unbound",
            {item["code"] for item in result["analysis_errors"]},
        )

    def test_ttl_and_capacity_bound_the_store(self):
        now = [10.0]
        service = self.make_service(ttl_seconds=5, max_reviews=1, clock=lambda: now[0])
        first = prepare(service, "review-1")
        prepare(service, "review-2")
        self.assertEqual(service.review_count, 1)
        with self.assertRaisesRegex(ReviewServiceError, "review_not_found"):
            service.seaf_lookup(
                review_id="review-1",
                review_digest=first["review_digest"],
                entity_id="AS.NEW",
            )
        now[0] = 20.0
        self.assertEqual(service.review_count, 0)

    def test_default_unavailable_repository_is_incomplete(self):
        service = ReviewService(digest_secret="unit-test-secret")
        result = prepare(service)
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["analysis_errors"][0]["code"], "repository_unavailable")

    def test_default_hook_runs_native_git_snapshot_and_deterministic_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "synthetic-architecture"
            repository.mkdir()

            def git(*arguments, env=None):
                completed = subprocess.run(
                    ["git", "-C", str(repository), *arguments],
                    check=True,
                    capture_output=True,
                    text=True,
                    env=env,
                )
                return completed.stdout.strip()

            git("init", "--initial-branch=main")
            git("config", "user.name", "AGA Synthetic Test")
            git("config", "user.email", "aga@example.invalid")
            (repository / "model").mkdir()
            (repository / "aga-extension.yaml").write_text(
                PROJECT_EXTENSION_TEXT, encoding="utf-8"
            )
            (repository / "dochub.yaml").write_text(
                """aga:
  schema: seaf-core/v1.4.0
  extensions: [aga.project/v1]
  data_classification: synthetic-public
imports: [aga-extension.yaml, model/components.yaml, model/integrations.yaml, model/adrs.yaml, model/contexts.yaml]
""",
                encoding="utf-8",
            )
            (repository / "model/components.yaml").write_text(
                """components:
  demo.portal:
    title: Synthetic Portal
    entity: component
    description: Synthetic mission-critical portal
    owner: Synthetic Team
    criticality: mission_critical
    target_status: strategic
  demo.legacy:
    title: Synthetic Legacy
    entity: component
    description: Synthetic retiring component
    owner: Synthetic Team
    criticality: high
    target_status: eliminate
""",
                encoding="utf-8",
            )
            integration_path = repository / "model/integrations.yaml"
            integration_path.write_text("seaf.app.integrations: {}\n", encoding="utf-8")
            (repository / "model/adrs.yaml").write_text(
                "seaf.change.adr: {}\n", encoding="utf-8"
            )
            (repository / "model/diagrams").mkdir()
            (repository / "model/diagrams/landscape.plantuml").write_text(
                """@startuml
rectangle "Synthetic Portal" as PORTAL
rectangle "Synthetic Legacy" as LEGACY
PORTAL --> LEGACY : synthetic request
@enduml
""",
                encoding="utf-8",
            )
            (repository / "model/contexts.yaml").write_text(
                """contexts:
  demo.landscape:
    title: Synthetic landscape
    uml: diagrams/landscape.plantuml
    components: [demo.portal, demo.legacy]
""",
                encoding="utf-8",
            )
            commit_env = dict(os.environ)
            commit_env.update(
                {
                    "GIT_AUTHOR_DATE": "2026-07-15T00:00:00Z",
                    "GIT_COMMITTER_DATE": "2026-07-15T00:00:00Z",
                }
            )
            git("add", ".")
            git("commit", "-m", "synthetic base", env=commit_env)
            base = git("rev-parse", "HEAD")
            integration_path.write_text(
                """seaf.app.integrations:
  demo.portal_to_legacy:
    title: Synthetic legacy dependency
    description: Synthetic portal calls the retiring component.
    from: demo.portal
    to: demo.legacy
""",
                encoding="utf-8",
            )
            commit_env.update(
                {
                    "GIT_AUTHOR_DATE": "2026-07-15T00:01:00Z",
                    "GIT_COMMITTER_DATE": "2026-07-15T00:01:00Z",
                }
            )
            git("add", ".")
            git("commit", "-m", "synthetic head", env=commit_env)
            head = git("rev-parse", "HEAD")

            with RepositorySnapshotBuilder(
                repository, base, head, dependency_mode="fixture"
            ).build() as direct_snapshot:
                direct = prepare_seaf_review(direct_snapshot)
            direct_finding = direct["deterministic_findings"][0]

            service = ReviewService(
                repositories={
                    "architecture": {
                        "repository": repository,
                        "manifest_path": "dochub.yaml",
                        "dependency_mode": "fixture",
                    }
                },
                digest_secret="unit-test-secret",
            )
            prepared = service.prepare_review(
                repository_id="architecture",
                base=base,
                head=head,
                review_id="native-review",
                entity_ids=[
                    "demo.portal",
                    "demo.legacy",
                    "demo.portal_to_legacy",
                    "demo.landscape",
                ],
            )
            self.assertEqual(prepared["status"], "ready")
            self.assertEqual(
                json.loads(prepared["review_provenance_json"]),
                direct["review_provenance"],
            )
            self.assertIn(
                "SEAF-004",
                [item["rule_id"] for item in prepared["deterministic_findings"]],
            )
            native_artifacts = {
                item["entity_id"]: item for item in prepared["artifacts"]
            }
            self.assertEqual(
                native_artifacts["demo.portal_to_legacy"]["change_status"],
                "changed",
            )
            self.assertEqual(
                native_artifacts["demo.portal_to_legacy"]["changed_pointers"],
                ["/seaf.app.integrations/demo.portal_to_legacy"],
            )
            self.assertEqual(
                native_artifacts["demo.portal"]["change_status"], "context"
            )
            prin_005 = next(
                task
                for task in prepared["semantic_tasks"]
                if task["rule_id"] == "PRIN-005"
            )
            self.assertEqual(prin_005["entity_ids"], ["demo.portal_to_legacy"])
            self.assertIn("demo.portal", prin_005["context_entity_ids"])
            mcp_finding = prepared["deterministic_findings"][0]
            for field in (
                "rule_id",
                "severity",
                "confidence",
                "entity_id",
                "artifact",
                "location",
                "evidence",
                "source_ref",
                "suggested_fix",
                "canonical_defect",
                "base_revision",
                "head_revision",
                "source_provenance",
                "origin",
            ):
                self.assertEqual(mcp_finding[field], direct_finding[field])
            self.assertEqual(len(mcp_finding["evidence_refs"]), 1)
            parsed = service.parse_diagram(
                review_id=prepared["review_id"],
                review_digest=prepared["review_digest"],
                entity_id="demo.landscape",
            )
            self.assertEqual(parsed["diagram_format"], "plantuml")
            self.assertIn("PORTAL", json.loads(parsed["diagram_json"])["nodes"])
            self.assertEqual(
                parsed["source_provenance"],
                native_artifacts["demo.landscape"]["content_provenance"],
            )
            final = service.finalize_review(
                review_id=prepared["review_id"],
                review_digest=prepared["review_digest"],
                task_digest=prepared["task_digest"],
                semantic_result=complete_result(prepared),
            )
            self.assertEqual(final["verdict"], "request_changes_escalate")
            self.assertEqual(
                final["findings"][0]["source_provenance"],
                direct_finding["source_provenance"],
            )
            self.assertEqual(
                final["review_provenance_json"], prepared["review_provenance_json"]
            )

            components_path = repository / "model/components.yaml"
            components_path.write_text(
                components_path.read_text(encoding="utf-8").replace(
                    "target_status: eliminate", "target_status: strategic"
                ),
                encoding="utf-8",
            )
            commit_env.update(
                {
                    "GIT_AUTHOR_DATE": "2026-07-15T00:02:00Z",
                    "GIT_COMMITTER_DATE": "2026-07-15T00:02:00Z",
                }
            )
            git("add", ".")
            git("commit", "-m", "synthetic endpoint base", env=commit_env)
            endpoint_base = git("rev-parse", "HEAD")
            components_path.write_text(
                components_path.read_text(encoding="utf-8").replace(
                    "description: Synthetic retiring component\n"
                    "    owner: Synthetic Team\n"
                    "    criticality: high\n"
                    "    target_status: strategic",
                    "description: Synthetic retiring component\n"
                    "    owner: Synthetic Team\n"
                    "    criticality: high\n"
                    "    target_status: eliminate",
                ),
                encoding="utf-8",
            )
            commit_env.update(
                {
                    "GIT_AUTHOR_DATE": "2026-07-15T00:03:00Z",
                    "GIT_COMMITTER_DATE": "2026-07-15T00:03:00Z",
                }
            )
            git("add", ".")
            git("commit", "-m", "synthetic endpoint head", env=commit_env)
            endpoint_head = git("rev-parse", "HEAD")
            impacted = service.prepare_review(
                repository_id="architecture",
                base=endpoint_base,
                head=endpoint_head,
                review_id="native-impacted-context-review",
                entity_ids=["demo.legacy", "demo.portal_to_legacy"],
            )
            impacted_artifacts = {
                item["entity_id"]: item for item in impacted["artifacts"]
            }
            self.assertEqual(impacted["status"], "ready")
            self.assertEqual(
                impacted_artifacts["demo.legacy"]["change_status"], "changed"
            )
            self.assertEqual(
                impacted_artifacts["demo.portal_to_legacy"]["change_status"],
                "context",
            )
            impacted_finding = next(
                item
                for item in impacted["deterministic_findings"]
                if item["rule_id"] == "SEAF-004"
            )
            self.assertEqual(impacted_finding["entity_id"], "demo.portal_to_legacy")
            self.assertEqual(
                impacted_finding["source_provenance"],
                impacted_artifacts["demo.portal_to_legacy"]["source_provenance"],
            )

    def test_callback_rule_catalog_and_policy_are_bound_to_review(self):
        rules, policy = load_rules()
        catalog = {
            rule["id"]: rule for rule in rules if rule["id"] in SEMANTIC_RULE_IDS
        }
        policy = json.loads(json.dumps(policy))
        policy["verdict_policy"]["none"] = "approve_with_warnings"

        def callback(**request):
            value = fixture_callback(**request)
            value["semantic_rule_catalog"] = catalog
            value["verdict_policy"] = policy
            value["review_provenance"] = {
                "base_commit": request["base"],
                "head_commit": request["head"],
                "rules_sha256": "a" * 64,
            }
            return value

        service = self.make_service(callback)
        prepared = prepare(service, "bound-policy-review")
        final = service.finalize_review(
            review_id=prepared["review_id"],
            review_digest=prepared["review_digest"],
            task_digest=prepared["task_digest"],
            semantic_result=complete_result(prepared),
        )
        self.assertEqual(final["verdict"], "approve_with_warnings")
        self.assertEqual(
            json.loads(final["review_provenance_json"])["rules_sha256"], "a" * 64
        )

    def test_callback_policy_cannot_approve_blockers(self):
        rules, policy = load_rules()
        catalog = {
            rule["id"]: rule for rule in rules if rule["id"] in SEMANTIC_RULE_IDS
        }
        policy = json.loads(json.dumps(policy))
        policy["verdict_policy"]["has_blocker"] = "approve"

        def callback(**request):
            value = fixture_callback(**request)
            value["semantic_rule_catalog"] = catalog
            value["verdict_policy"] = policy
            return value

        service = self.make_service(callback)
        with self.assertRaisesRegex(ReviewServiceError, "fail-closed contract"):
            prepare(service, "unsafe-policy-review")

    def test_prepare_callback_timeout_is_incomplete(self):
        def slow(**_request):
            time.sleep(0.1)
            return fixture_callback()

        service = self.make_service(slow, prepare_timeout_seconds=0.01)
        result = prepare(service)
        self.assertTrue(result["incomplete"])
        self.assertEqual(result["analysis_errors"][0]["code"], "prepare_timeout")

    def test_timed_out_prepare_hooks_remain_worker_bounded(self):
        release = threading.Event()
        started = threading.Event()

        def hanging(**_request):
            started.set()
            release.wait(2.0)
            return fixture_callback()

        service = self.make_service(
            hanging,
            prepare_timeout_seconds=0.01,
            max_prepare_workers=1,
        )
        first = prepare(service, "bounded-hook-1")
        self.assertEqual(first["analysis_errors"][0]["code"], "prepare_timeout")
        self.assertTrue(started.is_set())
        second = prepare(service, "bounded-hook-2")
        self.assertEqual(second["analysis_errors"][0]["code"], "prepare_busy")
        self.assertLessEqual(
            len(
                [
                    thread
                    for thread in threading.enumerate()
                    if thread.name == "aga-prepare-hook" and thread.is_alive()
                ]
            ),
            1,
        )
        release.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if not any(
                thread.name == "aga-prepare-hook" and thread.is_alive()
                for thread in threading.enumerate()
            ):
                break
            time.sleep(0.01)
        third = prepare(service, "bounded-hook-3")
        self.assertEqual(third["status"], "ready")

    def test_prepared_review_and_store_have_aggregate_byte_limits(self):
        limited = self.make_service(max_review_bytes=1_000, max_store_bytes=1_000)
        with self.assertRaisesRegex(ReviewServiceError, "aggregate byte limit"):
            prepare(limited, "oversized-review")

        def bulky(**request):
            value = fixture_callback(**request)
            value["artifacts"][0]["data"]["description"] = "x" * 4_000
            return value

        service = self.make_service(
            bulky,
            max_artifact_bytes=10_000,
            max_review_bytes=20_000,
            max_store_bytes=20_000,
            max_reviews=10,
        )
        prepared = [prepare(service, f"bounded-store-{index}") for index in range(3)]
        self.assertLess(service.review_count, 3)
        self.assertLessEqual(service.stored_bytes, 20_000)
        with self.assertRaisesRegex(ReviewServiceError, "review_not_found"):
            service.seaf_lookup(
                review_id=prepared[0]["review_id"],
                review_digest=prepared[0]["review_digest"],
                entity_id="AS.NEW",
            )

    def test_lookup_and_diagram_use_entity_ids(self):
        service = self.make_service()
        result = prepare(service)
        lookup = service.seaf_lookup(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            entity_id="AS.NEW",
        )
        self.assertEqual(lookup["entity"]["entity_id"], "AS.NEW")
        parsed = service.parse_diagram(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            entity_id="D.NEW",
        )
        self.assertEqual(parsed["diagram_format"], "plantuml")
        self.assertIn("nodes", json.loads(parsed["diagram_json"]))
        diagram = next(
            item for item in result["artifacts"] if item["entity_id"] == "D.NEW"
        )
        self.assertEqual(parsed["source_provenance"], diagram["content_provenance"])
        with self.assertRaises(ReviewInputError):
            service.seaf_lookup(
                review_id=result["review_id"],
                review_digest=result["review_digest"],
                entity_id="../../etc/passwd",
            )

    def test_missing_semantic_stage_never_approves(self):
        service = self.make_service()
        result = prepare(service)
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
        )
        self.assertEqual(final["verdict"], "incomplete")
        self.assertTrue(final["human_review_required"])
        self.assertEqual(final["missing_rule_ids"], list(SEMANTIC_RULE_IDS))

    def test_error_and_timeout_semantic_stage_never_approve(self):
        for status in ("error", "timeout", "unavailable"):
            with self.subTest(status=status):
                service = self.make_service()
                result = prepare(service, f"review-{status}")
                final = service.finalize_review(
                    review_id=result["review_id"],
                    review_digest=result["review_digest"],
                    task_digest=result["task_digest"],
                    semantic_result={"status": status, "error": "synthetic adapter failure"},
                )
                self.assertEqual(final["status"], "incomplete")
                self.assertEqual(final["verdict"], "incomplete")

    def test_exact_completed_rules_are_required(self):
        service = self.make_service()
        result = prepare(service)
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result={
                "status": "completed",
                "completed_rule_ids": list(SEMANTIC_RULE_IDS[:-1]),
                "findings": [],
            },
        )
        self.assertTrue(final["incomplete"])
        self.assertEqual(final["missing_rule_ids"], ["PRIN-007"])

    def test_complete_clean_semantic_stage_can_approve(self):
        service = self.make_service()
        result = prepare(service)
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result),
        )
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["verdict"], "approve")
        self.assertFalse(final["auto_merge"])

    def test_finalize_is_idempotent_and_immutable(self):
        service = self.make_service()
        result = prepare(service)
        clean = complete_result(result)
        first = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=clean,
        )
        retry = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=json.dumps(clean, sort_keys=True),
        )
        self.assertEqual(retry, first)
        with self.assertRaisesRegex(ReviewServiceError, "finalization_conflict"):
            service.finalize_review(
                review_id=result["review_id"],
                review_digest=result["review_digest"],
                task_digest=result["task_digest"],
                semantic_result=complete_result(result, [semantic_finding(result)]),
            )

    def test_concurrent_finalize_is_first_write_wins(self):
        service = self.make_service()
        result = prepare(service)
        payloads = [
            complete_result(result),
            complete_result(result, [semantic_finding(result)]),
        ]

        def invoke(payload):
            try:
                final = service.finalize_review(
                    review_id=result["review_id"],
                    review_digest=result["review_digest"],
                    task_digest=result["task_digest"],
                    semantic_result=payload,
                )
                return "ok", final["verdict"]
            except ReviewServiceError as error:
                return "error", error.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(invoke, payloads))
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1)
        self.assertIn(("error", "finalization_conflict"), outcomes)

    def test_valid_semantic_finding_changes_the_verdict(self):
        service = self.make_service()
        result = prepare(service)
        finding = semantic_finding(result)
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [finding]),
        )
        self.assertEqual(final["verdict"], "request_changes_escalate")
        accepted = final["findings"][0]
        artifact = next(
            item for item in result["artifacts"] if item["entity_id"] == "AS.NEW"
        )
        self.assertEqual(accepted["origin"], "semantic")
        self.assertEqual(accepted["artifact"], "architecture/systems.yaml")
        self.assertEqual(accepted["base_revision"], BASE)
        self.assertEqual(accepted["head_revision"], HEAD)
        self.assertEqual(accepted["source_provenance"], artifact["source_provenance"])

    def test_semantic_location_accepts_exact_entity_and_resolving_descendant(self):
        for location in (
            "/components/AS.NEW",
            "/components/AS.NEW/description",
        ):
            with self.subTest(location=location):
                service = self.make_service()
                result = prepare(service)
                final = service.finalize_review(
                    review_id=result["review_id"],
                    review_digest=result["review_digest"],
                    task_digest=result["task_digest"],
                    semantic_result=complete_result(
                        result, [semantic_finding(result, location=location)]
                    ),
                )
                self.assertEqual(final["findings"][0]["location"], location)

    def test_semantic_finding_keeps_dependency_commit_distinct_from_head(self):
        dependency_commit = "3" * 40

        def dependency_provenance(**request):
            value = fixture_callback(**request)
            value["artifacts"][0]["source_ref"]["commit"] = dependency_commit
            return value

        service = self.make_service(dependency_provenance)
        result = prepare(service)
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [semantic_finding(result)]),
        )
        accepted = final["findings"][0]
        self.assertEqual(accepted["head_revision"], HEAD)
        self.assertEqual(accepted["source_provenance"]["commit"], dependency_commit)

    def test_diagram_text_finding_uses_exact_materialized_content_provenance(self):
        def changed_diagram(**request):
            value = fixture_callback(**request)
            value["artifacts"][2]["change_status"] = "changed"
            value["artifacts"][2]["changed_pointers"] = [
                "/contexts/D.NEW/text"
            ]
            return value

        service = self.make_service(changed_diagram)
        result = prepare(service)
        diagram = next(
            item for item in result["artifacts"] if item["entity_id"] == "D.NEW"
        )
        task = next(
            item for item in result["semantic_tasks"] if item["rule_id"] == "PRIN-007"
        )
        finding = semantic_finding(
            result,
            rule_id="PRIN-007",
            severity="major",
            source_ref=task["source_ref"],
            entity_id="D.NEW",
            location="/contexts/D.NEW/text",
            evidence_refs=[diagram["evidence_ref"]],
        )
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [finding]),
        )
        accepted = final["findings"][0]
        self.assertEqual(accepted["source_provenance"], diagram["content_provenance"])
        self.assertEqual(
            accepted["source_provenance"]["sha256"],
            hashlib.sha256(DIAGRAM_TEXT.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(
            accepted["source_provenance"]["sha256"],
            diagram["source_provenance"]["sha256"],
        )

    def test_semantic_location_fails_closed_when_unbound_or_noncanonical(self):
        for location in (
            "/components/AS.OTHER/description",
            "/components/AS.NEW/missing",
            "/components/AS.NEW/bad~2escape",
        ):
            with self.subTest(location=location):
                service = self.make_service()
                result = prepare(service)
                final = service.finalize_review(
                    review_id=result["review_id"],
                    review_digest=result["review_digest"],
                    task_digest=result["task_digest"],
                    semantic_result=complete_result(
                        result, [semantic_finding(result, location=location)]
                    ),
                )
                self.assertEqual(final["status"], "incomplete")
                self.assertEqual(final["verdict"], "incomplete")
                self.assertEqual(final["findings"], [])
                self.assertTrue(final["human_review_required"])
                self.assertIn(
                    "semantic_validation_error",
                    {item["code"] for item in final["analysis_errors"]},
                )

    def test_semantic_finding_must_use_catalog_source_and_prepared_evidence(self):
        for changes in (
            {"source_ref": "invented source"},
            {"entity_id": "AS.UNKNOWN"},
            {"evidence_refs": ["ev_" + "0" * 64]},
            {"unexpected": "raw prose"},
            {
                "base_revision": BASE,
                "head_revision": HEAD,
                "source_provenance": {
                    "file": "agent-controlled.yaml",
                    "pointer": "/agent",
                    "commit": HEAD,
                    "line": 1,
                    "sha256": "0" * 64,
                },
            },
        ):
            with self.subTest(changes=changes):
                service = self.make_service()
                result = prepare(service)
                finding = semantic_finding(result, **changes)
                with self.assertRaises(ReviewInputError):
                    service.finalize_review(
                        review_id=result["review_id"],
                        review_digest=result["review_digest"],
                        task_digest=result["task_digest"],
                        semantic_result=complete_result(result, [finding]),
                    )

    def test_semantic_finding_must_stay_inside_rule_task_scope(self):
        service = self.make_service()
        result = prepare(service)
        integration = next(
            item for item in result["artifacts"] if item["entity_id"] == "IF.NEW"
        )
        finding = semantic_finding(
            result,
            entity_id="IF.NEW",
            evidence_refs=[integration["evidence_ref"]],
        )
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [finding]),
        )
        self.assertEqual(final["status"], "incomplete")
        self.assertEqual(final["findings"], [])
        self.assertIn(
            "semantic_validation_error",
            {item["code"] for item in final["analysis_errors"]},
        )

    def test_semantic_finding_cannot_target_context_entity(self):
        service = self.make_service()
        result = prepare(service)
        integration = next(
            item for item in result["artifacts"] if item["entity_id"] == "IF.NEW"
        )
        task = next(
            item for item in result["semantic_tasks"] if item["rule_id"] == "PRIN-005"
        )
        self.assertIn("IF.NEW", task["context_entity_ids"])
        finding = semantic_finding(
            result,
            rule_id="PRIN-005",
            severity="major",
            source_ref=task["source_ref"],
            entity_id="IF.NEW",
            location="/seaf.app.integrations/IF.NEW/from",
            evidence_refs=[integration["evidence_ref"]],
        )
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [finding]),
        )
        self.assertEqual(final["status"], "incomplete")
        self.assertEqual(final["findings"], [])
        self.assertIn(
            "semantic_validation_error",
            {item["code"] for item in final["analysis_errors"]},
        )

    def test_semantic_finding_may_cite_bounded_context_evidence(self):
        service = self.make_service()
        result = prepare(service)
        artifacts = {item["entity_id"]: item for item in result["artifacts"]}
        task = next(
            item for item in result["semantic_tasks"] if item["rule_id"] == "PRIN-005"
        )
        refs = [
            artifacts["AS.NEW"]["evidence_ref"],
            artifacts["IF.NEW"]["evidence_ref"],
        ]
        finding = semantic_finding(
            result,
            rule_id="PRIN-005",
            severity="major",
            source_ref=task["source_ref"],
            evidence_refs=refs,
        )
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [finding]),
        )
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["findings"][0]["evidence_refs"], refs)

    def test_diagram_only_artifact_cannot_fill_system_rule_scope(self):
        def diagram_only(**request):
            value = fixture_callback(**request)
            value["artifacts"] = [value["artifacts"][2]]
            return value

        service = self.make_service(diagram_only)
        result = service.prepare_review(
            repository_id="synthetic-seaf",
            base=BASE,
            head=HEAD,
            review_id="review-diagram-only",
            entity_ids=["D.NEW"],
        )
        task = next(
            item for item in result["semantic_tasks"] if item["rule_id"] == "PRIN-004"
        )
        diagram = result["artifacts"][0]
        self.assertEqual(result["status"], "ready")
        self.assertEqual(task["entity_ids"], [])
        self.assertEqual(task["evidence_refs"], [])
        finding = {
            "rule_id": "PRIN-004",
            "severity": "major",
            "confidence": 0.91,
            "entity_id": "D.NEW",
            "location": "/contexts/D.NEW/text",
            "evidence": "Synthetic diagram-only claim outside the rule scope.",
            "evidence_refs": [diagram["evidence_ref"]],
            "source_ref": task["source_ref"],
            "suggested_fix": "Do not use diagrams as system-passport evidence.",
        }
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [finding]),
        )
        self.assertEqual(final["status"], "incomplete")
        self.assertEqual(final["findings"], [])
        self.assertIn(
            "semantic_validation_error",
            {item["code"] for item in final["analysis_errors"]},
        )

    def test_semantic_finding_cannot_downgrade_catalog_severity(self):
        service = self.make_service()
        result = prepare(service)
        source_ref = next(
            item["source_ref"]
            for item in result["semantic_tasks"]
            if item["rule_id"] == "PRIN-006"
        )
        finding = semantic_finding(
            result,
            rule_id="PRIN-006",
            severity="minor",
            source_ref=source_ref,
        )
        with self.assertRaisesRegex(ReviewInputError, "trusted rule catalog"):
            service.finalize_review(
                review_id=result["review_id"],
                review_digest=result["review_digest"],
                task_digest=result["task_digest"],
                semantic_result=complete_result(result, [finding]),
            )

    def test_duplicate_key_semantic_json_is_rejected(self):
        service = self.make_service()
        result = prepare(service)
        duplicate = '{"status":"completed","status":"timeout"}'
        with self.assertRaises(ReviewInputError):
            service.finalize_review(
                review_id=result["review_id"],
                review_digest=result["review_digest"],
                task_digest=result["task_digest"],
                semantic_result=duplicate,
            )

    def test_low_confidence_major_is_observed_and_requires_human_review(self):
        service = self.make_service()
        result = prepare(service)
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(
                result, [semantic_finding(result, confidence=0.2)]
            ),
        )
        self.assertEqual(final["status"], "incomplete")
        self.assertEqual(final["verdict"], "incomplete")
        self.assertEqual(final["findings"], [])
        self.assertEqual(final["observations"][0]["observation_type"], "low_confidence")
        self.assertTrue(final["escalate"])
        self.assertTrue(final["human_review_required"])
        self.assertIn(
            "semantic_low_confidence",
            {item["code"] for item in final["analysis_errors"]},
        )

    def test_low_confidence_blocker_never_approves_even_with_all_rules_complete(self):
        service = self.make_service()
        result = prepare(service)
        source_ref = next(
            item["source_ref"]
            for item in result["semantic_tasks"]
            if item["rule_id"] == "PRIN-006"
        )
        finding = semantic_finding(
            result,
            rule_id="PRIN-006",
            severity="blocker",
            confidence=0.1,
            source_ref=source_ref,
        )
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [finding]),
        )
        self.assertEqual(final["completed_rule_ids"], list(SEMANTIC_RULE_IDS))
        self.assertEqual(final["status"], "incomplete")
        self.assertEqual(final["verdict"], "incomplete")
        self.assertEqual(final["findings"], [])
        self.assertEqual(final["observations"][0]["rule_id"], "PRIN-006")
        self.assertTrue(final["escalate"])
        self.assertTrue(final["human_review_required"])
        self.assertIn(
            "semantic_low_confidence",
            {item["code"] for item in final["analysis_errors"]},
        )

    def test_low_confidence_blocker_is_marked_and_downgraded(self):
        service = self.make_service()
        result = prepare(service)
        source_ref = next(
            item["source_ref"]
            for item in result["semantic_tasks"]
            if item["rule_id"] == "PRIN-006"
        )
        finding = semantic_finding(
            result,
            rule_id="PRIN-006",
            severity="blocker",
            confidence=0.6,
            source_ref=source_ref,
        )
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [finding]),
        )
        accepted = final["findings"][0]
        self.assertEqual(accepted["severity"], "major")
        self.assertTrue(accepted["low_confidence"])
        self.assertEqual(accepted["original_severity"], "blocker")

    def test_deterministic_precedence_suppresses_duplicate_prin_006(self):
        service = self.make_service(deterministic_callback)
        result = prepare(service)
        system = next(
            item for item in result["artifacts"] if item["entity_id"] == "AS.NEW"
        )
        source_ref = next(
            item["source_ref"] for item in result["semantic_tasks"] if item["rule_id"] == "PRIN-006"
        )
        semantic = semantic_finding(
            result,
            rule_id="PRIN-006",
            severity="blocker",
            entity_id="AS.NEW",
            location="/components/AS.NEW/target_status",
            evidence="synthetic target is marked eliminate",
            evidence_refs=[system["evidence_ref"]],
            source_ref=source_ref,
        )
        final = service.finalize_review(
            review_id=result["review_id"],
            review_digest=result["review_digest"],
            task_digest=result["task_digest"],
            semantic_result=complete_result(result, [semantic]),
        )
        self.assertEqual([item["rule_id"] for item in final["findings"]], ["SEAF-004"])
        accepted = final["findings"][0]
        self.assertEqual(accepted["base_revision"], BASE)
        self.assertEqual(accepted["head_revision"], HEAD)
        self.assertEqual(accepted["source_provenance"], system["source_provenance"])


class SchemaContractTests(unittest.TestCase):
    def test_every_tool_has_strict_input_and_output_schema(self):
        self.assertEqual(len(TOOL_DEFINITIONS), 4)

        def assert_strict(schema):
            if schema.get("type") == "object":
                self.assertIs(schema.get("additionalProperties"), False)
                for child in schema.get("properties", {}).values():
                    assert_strict(child)
            if schema.get("type") == "array" and isinstance(schema.get("items"), dict):
                assert_strict(schema["items"])

        for tool in TOOL_DEFINITIONS:
            with self.subTest(tool=tool["name"]):
                assert_strict(tool["inputSchema"])
                assert_strict(tool["outputSchema"])

    def test_client_schemas_expose_no_filesystem_path_argument(self):
        serialized = json.dumps(
            {item["name"]: item["inputSchema"] for item in TOOL_DEFINITIONS},
            sort_keys=True,
        )
        self.assertNotIn('"path"', serialized)
        self.assertNotIn('"pr_dir"', serialized)
        self.assertNotIn('"rules_dir"', serialized)
        self.assertNotIn('"seaf_path"', serialized)

    def test_json_pointer_patterns_are_anchored_in_advertised_schemas(self):
        patterns = []

        def collect(schema):
            if isinstance(schema, dict):
                if "pattern" in schema and (
                    schema.get("minLength") == 1
                    or "pointer" in json.dumps(schema, sort_keys=True)
                ):
                    patterns.append(schema["pattern"])
                for child in schema.values():
                    collect(child)
            elif isinstance(schema, list):
                for child in schema:
                    collect(child)

        for tool in TOOL_DEFINITIONS:
            collect(tool["inputSchema"])
            collect(tool["outputSchema"])
        pointer_patterns = [value for value in patterns if "~[01]" in value]
        self.assertTrue(pointer_patterns)
        self.assertTrue(all(value.startswith("^") and value.endswith("$") for value in pointer_patterns))

    def test_runtime_schema_validator_rejects_additional_properties(self):
        schema = TOOL_DEFINITIONS[0]["inputSchema"]
        with self.assertRaisesRegex(ValueError, "unknown properties"):
            validate_json_schema(
                {
                    "repository_id": "synthetic-seaf",
                    "base": BASE,
                    "head": HEAD,
                    "review_id": "review-1",
                    "filesystem_path": "/tmp/repository",
                },
                schema,
            )

    def test_cli_reads_compose_environment_with_cli_precedence(self):
        environment = {
            "AGA_MCP_HOST": "0.0.0.0",
            "AGA_MCP_PORT": "8000",
            "AGA_MCP_PATH": "/mcp",
            "AGA_MCP_AUTH_MODE": "internal-network",
            "AGA_MAX_REQUEST_BYTES": "262144",
            "AGA_MAX_RESPONSE_BYTES": "1048576",
            "AGA_MAX_CONCURRENCY": "8",
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            args = build_parser().parse_args(["--port", "9000"])
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9000)
        self.assertEqual(args.endpoint, "/mcp")
        self.assertEqual(args.mode, "internal-network")
        self.assertEqual(args.max_request_bytes, 262144)


class MCPApplicationTests(unittest.TestCase):
    def make_application(self, service=None, **config_kwargs):
        service = service or ReviewService(fixture_callback, digest_secret="unit-test-secret")
        config = MCPServerConfig(**config_kwargs)
        return MCPApplication(service, config)

    def test_initialize_notification_ping_and_list(self):
        app = self.make_application()
        initialized = app.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "archtool-contract-test", "version": "1.29.0"},
                },
            }
        )
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")

        future = app.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2099-12-31",
                    "capabilities": {},
                    "clientInfo": {"name": "future-client"},
                },
            }
        )
        self.assertEqual(future["result"]["protocolVersion"], "2025-11-25")
        with self.assertRaises(JsonRpcError):
            app.dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "latest",
                        "capabilities": {},
                        "clientInfo": {"name": "invalid-client"},
                    },
                }
            )
        self.assertIsNone(
            app.dispatch(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
            )
        )
        self.assertEqual(
            app.dispatch({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"],
            {},
        )
        listed = app.dispatch(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
        )
        self.assertEqual(
            [item["name"] for item in listed["result"]["tools"]],
            [
                "aga_prepare_review",
                "aga_seaf_lookup",
                "aga_parse_diagram",
                "aga_finalize_review",
            ],
        )

    def test_tools_call_and_sanitized_trace(self):
        app = self.make_application()
        secret_repository_id = "synthetic-secret-registry"
        response = app.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "aga_prepare_review",
                    "arguments": {
                        "repository_id": secret_repository_id,
                        "base": BASE,
                        "head": HEAD,
                        "review_id": "review-1",
                        "entity_ids": ["AS.NEW", "IF.NEW", "D.NEW"],
                    },
                },
            }
        )
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["status"], "ready")
        trace = app.trace[0]
        self.assertEqual(trace["tool"], "aga_prepare_review")
        self.assertEqual(trace["status"], "ok")
        self.assertRegex(trace["args_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(trace["output_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(trace["review_id_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(trace["output_status"], "ready")
        self.assertNotIn(secret_repository_id, json.dumps(trace))
        self.assertNotIn("review-1", json.dumps(trace))

    def test_invalid_args_are_jsonrpc_invalid_params_and_traced(self):
        app = self.make_application()
        with self.assertRaises(JsonRpcError) as caught:
            app.dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "aga_prepare_review",
                        "arguments": {
                            "repository_id": "synthetic-seaf",
                            "base": BASE,
                            "head": HEAD,
                            "review_id": "review-1",
                            "path": "/tmp/forbidden",
                        },
                    },
                }
            )
        self.assertEqual(caught.exception.code, -32602)
        self.assertEqual(app.trace[0]["status"], "error")

    def test_unavailable_review_is_structured_tool_error(self):
        app = self.make_application()
        response = app.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "aga_seaf_lookup",
                    "arguments": {
                        "review_id": "missing-review",
                        "review_digest": "rvw_" + "0" * 64,
                        "entity_id": "AS.NEW",
                    },
                },
            }
        )
        self.assertTrue(response["result"]["isError"])
        error = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(error["code"], "review_not_found")

    def test_tool_timeout_is_structured_and_traceable(self):
        service = ReviewService(fixture_callback, digest_secret="unit-test-secret")
        prepared = prepare(service, "review-read-timeout")
        original_lookup = service.seaf_lookup

        def slow_lookup(**request):
            time.sleep(0.15)
            return original_lookup(**request)

        service.seaf_lookup = slow_lookup
        app = self.make_application(
            service,
            request_timeout_seconds=0.02,
            max_concurrency=1,
        )
        response = app.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "aga_seaf_lookup",
                    "arguments": {
                        "review_id": prepared["review_id"],
                        "review_digest": prepared["review_digest"],
                        "entity_id": "AS.NEW",
                    },
                },
            }
        )
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(app.trace[0]["status"], "timeout")
        self.assertEqual(
            json.loads(response["result"]["content"][0]["text"])["code"],
            "tool_timeout",
        )
        time.sleep(0.17)
        self.assertEqual(service.review_count, 1)

    def test_state_mutating_tools_are_never_abandoned_for_late_write(self):
        def slow_prepare(**_request):
            time.sleep(0.12)
            return fixture_callback()

        service = ReviewService(
            slow_prepare,
            digest_secret="unit-test-secret",
            prepare_timeout_seconds=0.01,
        )
        app = self.make_application(
            service,
            request_timeout_seconds=0.02,
            max_concurrency=1,
        )
        response = app.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "aga_prepare_review",
                    "arguments": {
                        "repository_id": "synthetic-seaf",
                        "base": BASE,
                        "head": HEAD,
                        "review_id": "review-prepare-timeout",
                    },
                },
            }
        )
        self.assertFalse(response["result"]["isError"])
        prepared = response["result"]["structuredContent"]
        self.assertEqual(prepared["status"], "incomplete")
        self.assertEqual(prepared["analysis_errors"][0]["code"], "prepare_timeout")
        self.assertEqual(service.review_count, 1)
        time.sleep(0.14)
        retry = service.prepare_review(
            repository_id="synthetic-seaf",
            base=BASE,
            head=HEAD,
            review_id="review-prepare-timeout",
        )
        self.assertEqual(retry, prepared)
        self.assertEqual(service.review_count, 1)


class HTTPContractTests(unittest.TestCase):
    def setUp(self):
        service = ReviewService(fixture_callback, digest_secret="unit-test-secret")
        self.server = MCPServer(
            service,
            config=MCPServerConfig(
                host="127.0.0.1",
                port=0,
                max_request_bytes=512,
                max_response_bytes=1_048_576,
            ),
        ).start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=2)
        payload = None if body is None else (
            body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        )
        actual_headers = dict(headers or {})
        if payload is not None:
            actual_headers.setdefault("Content-Type", "application/json")
            actual_headers.setdefault("Accept", "application/json, text/event-stream")
        connection.request(method, path, body=payload, headers=actual_headers)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        response_headers = dict(response.getheaders())
        connection.close()
        return status, response_headers, data

    def rpc(self, request):
        headers = {}
        if request.get("method") != "initialize":
            headers["MCP-Protocol-Version"] = "2025-11-25"
        status, _headers, body = self.request("POST", "/mcp", request, headers=headers)
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_health_non_root_get_and_delete(self):
        status, _, body = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")
        status, headers, body = self.request(
            "GET",
            "/mcp",
            headers={
                "Accept": "text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        self.assertTrue(body.startswith(b":"))
        self.assertEqual(self.request("GET", "/")[0], 404)
        self.assertEqual(
            self.request(
                "DELETE", "/mcp", headers={"MCP-Protocol-Version": "2025-11-25"}
            )[0],
            204,
        )

    def test_archtool_style_initialize_notification_list_and_call(self):
        initialized = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "seaf-archtool", "version": "1.29.0"},
                },
            }
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "aga-governance-mcp")
        status, _, body = self.request(
            "POST",
            "/mcp",
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )
        self.assertEqual((status, body), (202, b""))
        listed = self.rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        self.assertEqual(len(listed["result"]["tools"]), 4)
        called = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "aga_prepare_review",
                    "arguments": {
                        "repository_id": "synthetic-seaf",
                        "base": BASE,
                        "head": HEAD,
                        "review_id": "review-http",
                    },
                },
            }
        )
        self.assertFalse(called["result"]["isError"])

    def test_invalid_args_and_oversized_body_are_bounded(self):
        invalid = self.rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "aga_prepare_review",
                    "arguments": {
                        "repository_id": "synthetic-seaf",
                        "base": "main",
                        "head": HEAD,
                        "review_id": "review-http",
                    },
                },
            }
        )
        self.assertEqual(invalid["error"]["code"], -32602)
        status, _, body = self.request(
            "POST",
            "/mcp",
            b"{" + b" " * 600 + b"}",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        self.assertEqual(status, 406)
        status, _, body = self.request(
            "POST",
            "/mcp",
            b"{" + b" " * 600 + b"}",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["error"]["data"]["code"], "request_too_large")

    def test_post_initialization_requests_require_negotiated_protocol_header(self):
        status, _, body = self.request(
            "POST",
            "/mcp",
            {"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": {}},
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_protocol_version")
        self.assertEqual(
            self.request("GET", "/mcp", headers={"Accept": "text/event-stream"})[0],
            400,
        )

    def test_batch_is_rejected_before_any_prepare_callback(self):
        callback_calls = []

        def forbidden_batch_callback(**request):
            callback_calls.append(request["review_id"])
            time.sleep(0.25)
            return fixture_callback()

        limited = MCPServer(
            ReviewService(
                forbidden_batch_callback,
                digest_secret="unit-test-secret",
                prepare_timeout_seconds=1.0,
            ),
            config=MCPServerConfig(
                host="127.0.0.1",
                port=0,
                max_request_bytes=4096,
                request_timeout_seconds=1.0,
            ),
        ).start()
        host, port = limited.server_address
        connection = http.client.HTTPConnection(host, port, timeout=2)
        batch = [
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": "aga_prepare_review",
                    "arguments": {
                        "repository_id": "synthetic-seaf",
                        "base": BASE,
                        "head": HEAD,
                        "review_id": f"batch-review-{request_id}",
                    },
                },
            }
            for request_id in (1, 2)
        ]
        started = time.monotonic()
        try:
            connection.request(
                "POST",
                "/mcp",
                body=json.dumps(batch),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-11-25",
                },
            )
            response = connection.getresponse()
            body = json.loads(response.read())
            duration = time.monotonic() - started
            self.assertEqual(response.status, 400)
            self.assertEqual(body["id"], None)
            self.assertEqual(body["error"]["code"], -32600)
            self.assertEqual(body["error"]["data"]["code"], "batch_not_supported")
            self.assertEqual(callback_calls, [])
            # Callback non-execution is the primary invariant.  The generous
            # threshold additionally guards against retaining the request for
            # the configured one-second tool budget without making CI timing
            # a precision assertion.
            self.assertLess(duration, 0.75)
        finally:
            connection.close()
            limited.shutdown()

    def test_oversized_response_is_a_bounded_jsonrpc_error(self):
        limited = MCPServer(
            ReviewService(fixture_callback, digest_secret="unit-test-secret"),
            config=MCPServerConfig(
                host="127.0.0.1",
                port=0,
                max_response_bytes=256,
            ),
        ).start()
        host, port = limited.server_address
        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            payload = json.dumps(
                {"jsonrpc": "2.0", "id": 99, "method": "tools/list", "params": {}}
            )
            connection.request(
                "POST",
                "/mcp",
                body=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-11-25",
                },
            )
            response = connection.getresponse()
            body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(body["id"], 99)
            self.assertEqual(body["error"]["data"]["code"], "response_too_large")
        finally:
            connection.close()
            limited.shutdown()

    def test_request_thread_concurrency_is_bounded(self):
        limited = MCPServer(
            ReviewService(fixture_callback, digest_secret="unit-test-secret"),
            config=MCPServerConfig(
                host="127.0.0.1",
                port=0,
                max_concurrency=1,
                request_timeout_seconds=0.5,
            ),
        ).start()
        host, port = limited.server_address
        stalled = socket.create_connection((host, port), timeout=2)
        try:
            stalled.sendall(
                b"POST /mcp HTTP/1.1\r\n"
                + f"Host: {host}:{port}\r\n".encode("ascii")
                + b"Content-Type: application/json\r\n"
                + b"Accept: application/json, text/event-stream\r\n"
                + b"Content-Length: 10\r\n\r\n"
            )
            time.sleep(0.05)
            connection = http.client.HTTPConnection(host, port, timeout=2)
            try:
                connection.request("GET", "/healthz")
                response = connection.getresponse()
                self.assertEqual(response.status, 503)
                self.assertEqual(json.loads(response.read())["error"]["code"], "server_busy")
            finally:
                connection.close()
        finally:
            stalled.close()
            limited.shutdown()

    def test_bearer_and_non_loopback_configuration(self):
        with self.assertRaisesRegex(ValueError, "non-loopback"):
            MCPServerConfig(host="0.0.0.0", mode="none")
        with self.assertRaisesRegex(ValueError, "bearer token"):
            MCPServerConfig(host="0.0.0.0", mode="bearer")
        with self.assertRaisesRegex(ValueError, "TLS termination"):
            MCPServerConfig(
                host="0.0.0.0", mode="bearer", bearer_token="contract-token"
            )
        proxied = MCPServerConfig(
            host="0.0.0.0",
            mode="bearer",
            bearer_token="contract-token",
            tls_terminated=True,
        )
        self.assertTrue(proxied.tls_terminated)
        internal = MCPServerConfig(host="0.0.0.0", mode="internal-network")
        self.assertEqual(internal.mode, "internal-network")
        token_server = MCPServer(
            ReviewService(fixture_callback, digest_secret="unit-test-secret"),
            config=MCPServerConfig(
                host="127.0.0.1",
                port=0,
                mode="bearer",
                bearer_token="contract-token",
            ),
        ).start()
        host, port = token_server.server_address
        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            connection.request("GET", "/mcp", headers={"Accept": "text/event-stream"})
            self.assertEqual(connection.getresponse().status, 401)
        finally:
            connection.close()
            token_server.shutdown()


if __name__ == "__main__":
    unittest.main()
