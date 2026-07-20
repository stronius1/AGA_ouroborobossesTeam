# -*- coding: utf-8 -*-
"""State, correlation and immutable-snapshot tests for Loop-B remediation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
import threading
from typing import Any

import pytest


PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from scripts.run_remediation import _materialize  # noqa: E402
from tools.mcp_server import (  # noqa: E402
    MCPApplication,
    MCPServerConfig,
    validate_json_schema,
)
from tools.remediation_service import (  # noqa: E402
    RemediationService,
    RemediationServiceError,
    TOOL_DEFINITIONS_REMEDIATION,
    TOOL_DEFINITIONS_REMediation,
    canonical_sha256,
    finding_sha256,
)
from tools.review_service import (  # noqa: E402
    ReviewService,
    SEMANTIC_PREDICATES,
    SEMANTIC_RULE_IDS,
)


REPOSITORY_ID = "synthetic-remediation"
REVIEW_ID = "trusted-review-1"
REMEDIATION_ID = "remediation-1"


def _clean_semantic_result(prepared: dict[str, Any]) -> dict[str, Any]:
    artifacts = {
        artifact["entity_id"]: artifact for artifact in prepared["artifacts"]
    }
    rule_results = []
    for task in prepared["semantic_tasks"]:
        applicable = bool(task["entity_ids"])
        rule_results.append(
            {
                "rule_id": task["rule_id"],
                "applicable": applicable,
                "complete": True,
                "evaluated_entity_ids": list(task["entity_ids"]),
                "predicate_checks": [
                    {
                        "predicate_id": predicate_id,
                        "status": "not_satisfied" if applicable else "not_applicable",
                        "evidence": (
                            "Reviewed all prepared evidence for this predicate."
                            if applicable
                            else ""
                        ),
                        "evidence_refs": (
                            [
                                artifacts[entity_id]["evidence_ref"]
                                for entity_id in task["entity_ids"]
                            ]
                            if applicable
                            else []
                        ),
                    }
                    for predicate_id in SEMANTIC_PREDICATES[task["rule_id"]]
                ],
                "findings": [],
                "error": "",
            }
        )
    return {
        "status": "completed",
        "completed_rule_ids": list(SEMANTIC_RULE_IDS),
        "findings": [],
        "rule_results": rule_results,
    }


@dataclass
class TrustedCase:
    repository: Path
    base: str
    head: str
    registry: dict[str, Any]
    final_review: dict[str, Any]
    finding: dict[str, Any]
    service: RemediationService

    def prepare(self, **overrides: Any) -> dict[str, Any]:
        arguments = {
            "repository_id": REPOSITORY_ID,
            "base": self.base,
            "head": self.head,
            "review_id": REVIEW_ID,
            "review_digest": self.final_review["review_digest"],
            "task_digest": self.final_review["task_digest"],
            "remediation_id": REMEDIATION_ID,
            "finding_sha256": finding_sha256(self.finding),
        }
        arguments.update(overrides)
        return self.service.prepare_remediation(**arguments)


def _complete_final_review(
    repository: Path,
    base: str,
    head: str,
    registry: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    review_service = ReviewService(
        repositories=registry,
        digest_secret=b"trusted-review-test-secret",
    )
    prepared = review_service.prepare_review(
        repository_id=REPOSITORY_ID,
        base=base,
        head=head,
        review_id=REVIEW_ID,
        entity_ids=(),
    )
    assert prepared["status"] == "ready"
    final = review_service.finalize_review(
        review_id=REVIEW_ID,
        review_digest=prepared["review_digest"],
        task_digest=prepared["task_digest"],
        semantic_result=_clean_semantic_result(prepared),
    )
    findings = [
        item
        for item in final["findings"]
        if item.get("rule_id") == "SEAF-004"
    ]
    assert final["status"] == "completed"
    assert final["incomplete"] is False
    assert len(findings) == 1
    return final, findings[0]


@pytest.fixture()
def trusted_case(tmp_path: Path) -> TrustedCase:
    repository = tmp_path / "synthetic-repository"
    base, head = _materialize(repository)
    registry = {
        REPOSITORY_ID: {
            "repository": repository,
            "manifest_path": "dochub.yaml",
            "dependency_mode": "fixture",
        }
    }
    final, finding = _complete_final_review(repository, base, head, registry)
    service = RemediationService(
        repositories=registry,
        digest_secret=b"trusted-remediation-test-secret",
    )
    service.register_trusted_review(
        repository_id=REPOSITORY_ID,
        base=base,
        head=head,
        final_review=final,
        final_output_sha256=canonical_sha256(final),
    )
    return TrustedCase(
        repository=repository,
        base=base,
        head=head,
        registry=registry,
        final_review=final,
        finding=finding,
        service=service,
    )


def _definition(name: str) -> dict[str, Any]:
    return next(item for item in TOOL_DEFINITIONS_REMEDIATION if item["name"] == name)


def test_tool_contract_is_exact_and_accepts_no_caller_paths() -> None:
    assert TOOL_DEFINITIONS_REMediation is TOOL_DEFINITIONS_REMEDIATION
    assert [item["name"] for item in TOOL_DEFINITIONS_REMEDIATION] == [
        "aga_prepare_remediation",
        "aga_finalize_remediation",
    ]
    prepare_properties = set(
        _definition("aga_prepare_remediation")["inputSchema"]["properties"]
    )
    assert prepare_properties == {
        "repository_id",
        "base",
        "head",
        "review_id",
        "review_digest",
        "task_digest",
        "remediation_id",
        "finding_sha256",
    }
    assert not any("path" in field or "root" in field for field in prepare_properties)
    finalize_properties = set(
        _definition("aga_finalize_remediation")["inputSchema"]["properties"]
    )
    assert finalize_properties == {
        "remediation_id",
        "remediation_digest",
        "candidate",
    }


def test_prepare_and_finalize_are_hash_bound_strict_and_idempotent(
    trusted_case: TrustedCase,
) -> None:
    prepared = trusted_case.prepare()
    assert trusted_case.prepare() == prepared
    assert prepared["schema"] == "aga.prepare-remediation/v1"
    assert prepared["status"] == "ready"
    assert prepared["review_output_sha256"] == canonical_sha256(
        trusted_case.final_review
    )
    assert prepared["human_review_required"] is True
    assert prepared["auto_merge"] is False
    assert prepared["incomplete"] is False
    validate_json_schema(
        prepared,
        _definition("aga_prepare_remediation")["outputSchema"],
        "$result",
    )

    finalized = trusted_case.service.finalize_remediation(
        remediation_id=REMEDIATION_ID,
        remediation_digest=prepared["remediation_digest"],
        candidate=prepared["candidate"],
    )
    assert finalized == trusted_case.service.finalize_remediation(
        remediation_id=REMEDIATION_ID,
        remediation_digest=prepared["remediation_digest"],
        candidate=prepared["candidate"],
    )
    assert finalized["schema"] == "aga.final-remediation/v1"
    assert finalized["status"] == "completed"
    assert finalized["outcome"] == "candidate_ready"
    diff_lines = finalized["patch"]["diff"].splitlines()
    assert len([line for line in diff_lines if line.startswith("-") and not line.startswith("---")]) == 1
    assert len([line for line in diff_lines if line.startswith("+") and not line.startswith("+++")]) == 1
    assert finalized["patch"]["before_sha256"] == hashlib.sha256(
        (trusted_case.repository / "model/integrations.yaml").read_bytes()
    ).hexdigest()
    assert finalized["patch"]["after_sha256"] != finalized["patch"][
        "before_sha256"
    ]
    assert finalized["human_review_required"] is True
    assert finalized["auto_merge"] is False
    validate_json_schema(
        finalized,
        _definition("aga_finalize_remediation")["outputSchema"],
        "$result",
    )


def test_mcp_application_emits_backend_compatible_bounded_receipts(
    trusted_case: TrustedCase,
) -> None:
    review_service = ReviewService(
        repositories=trusted_case.registry,
        digest_secret=b"unused-review-secret",
    )
    application = MCPApplication(
        review_service,
        MCPServerConfig(),
        remediation_service=trusted_case.service,
    )
    prepare_arguments = {
        "repository_id": REPOSITORY_ID,
        "base": trusted_case.base,
        "head": trusted_case.head,
        "review_id": REVIEW_ID,
        "review_digest": trusted_case.final_review["review_digest"],
        "task_digest": trusted_case.final_review["task_digest"],
        "remediation_id": REMEDIATION_ID,
        "finding_sha256": finding_sha256(trusted_case.finding),
    }
    prepare_response = application.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "aga_prepare_remediation",
                "arguments": prepare_arguments,
            },
        }
    )
    prepared = prepare_response["result"]["structuredContent"]
    finalize_arguments = {
        "remediation_id": REMEDIATION_ID,
        "remediation_digest": prepared["remediation_digest"],
        "candidate": prepared["candidate"],
    }
    finalize_response = application.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "aga_finalize_remediation",
                "arguments": finalize_arguments,
            },
        }
    )
    finalized = finalize_response["result"]["structuredContent"]

    prepare_receipt, finalize_receipt = application.trace
    assert prepare_receipt["tool"] == "aga_prepare_remediation"
    assert prepare_receipt["args_sha256"] == canonical_sha256(prepare_arguments)
    assert prepare_receipt["output_status"] == "ready"
    assert prepare_receipt["output_incomplete"] is False
    assert prepare_receipt["remediation_digest"] == prepared["remediation_digest"]
    assert prepare_receipt["candidate_sha256"] == prepared["candidate_sha256"]
    assert finalize_receipt["tool"] == "aga_finalize_remediation"
    assert finalize_receipt["args_sha256"] == canonical_sha256(finalize_arguments)
    assert finalize_receipt["output_status"] == "completed"
    assert finalize_receipt["output_incomplete"] is False
    assert finalize_receipt["output_sha256"] == canonical_sha256(finalized)
    assert finalize_receipt["candidate_sha256"] == finalized["candidate_sha256"]
    assert finalize_receipt["diff_sha256"] == finalized["patch"]["diff_sha256"]


def test_prepare_uses_immutable_git_head_not_dirty_worktree(
    trusted_case: TrustedCase,
) -> None:
    integrations = trusted_case.repository / "model/integrations.yaml"
    integrations.write_text("WORKTREE CONTENT MUST NOT BE READ\n", encoding="utf-8")

    prepared = trusted_case.prepare()

    assert prepared["status"] == "ready"
    assert prepared["candidate"]["artifact"] == "model/integrations.yaml"
    assert prepared["candidate"]["before_sha256"] == trusted_case.finding[
        "source_provenance"
    ]["sha256"]


def test_prepare_rejects_unregistered_or_mismatched_review_correlation(
    trusted_case: TrustedCase,
) -> None:
    with pytest.raises(RemediationServiceError) as excinfo:
        trusted_case.prepare(head="f" * 40)
    assert excinfo.value.code == "trusted_review_mismatch"

    with pytest.raises(RemediationServiceError) as excinfo:
        trusted_case.prepare(finding_sha256="0" * 64)
    assert excinfo.value.code == "finding_not_found"


def test_finalize_rejects_mutated_candidate_and_first_write_conflicts(
    trusted_case: TrustedCase,
) -> None:
    prepared = trusted_case.prepare()
    mutated = dict(prepared["candidate"], replacement_component="demo.attacker")
    with pytest.raises(RemediationServiceError) as excinfo:
        trusted_case.service.finalize_remediation(
            remediation_id=REMEDIATION_ID,
            remediation_digest=prepared["remediation_digest"],
            candidate=mutated,
        )
    assert excinfo.value.code == "candidate_mismatch"

    trusted_case.service.finalize_remediation(
        remediation_id=REMEDIATION_ID,
        remediation_digest=prepared["remediation_digest"],
        candidate=prepared["candidate"],
    )
    with pytest.raises(RemediationServiceError) as excinfo:
        trusted_case.service.finalize_remediation(
            remediation_id=REMEDIATION_ID,
            remediation_digest=prepared["remediation_digest"],
            candidate=mutated,
        )
    assert excinfo.value.code == "remediation_finalization_conflict"


def test_register_trusted_review_requires_exact_receipt_hash(
    trusted_case: TrustedCase,
) -> None:
    other = RemediationService(
        repositories=trusted_case.registry,
        digest_secret=b"other-remediation-secret",
    )
    with pytest.raises(RemediationServiceError) as excinfo:
        other.register_trusted_review(
            repository_id=REPOSITORY_ID,
            base=trusted_case.base,
            head=trusted_case.head,
            final_review=trusted_case.final_review,
            final_output_sha256="0" * 64,
        )
    assert excinfo.value.code == "trusted_review_hash_mismatch"


def test_host_registered_artifact_scope_rejects_other_model_documents(
    trusted_case: TrustedCase,
) -> None:
    restricted_registry = {
        REPOSITORY_ID: {
            **trusted_case.registry[REPOSITORY_ID],
            "remediation_artifacts": ["other/model/integrations.yaml"],
        }
    }
    service = RemediationService(
        repositories=restricted_registry,
        digest_secret=b"restricted-remediation-secret",
    )
    service.register_trusted_review(
        repository_id=REPOSITORY_ID,
        base=trusted_case.base,
        head=trusted_case.head,
        final_review=trusted_case.final_review,
        final_output_sha256=canonical_sha256(trusted_case.final_review),
    )
    with pytest.raises(RemediationServiceError) as excinfo:
        service.prepare_remediation(
            repository_id=REPOSITORY_ID,
            base=trusted_case.base,
            head=trusted_case.head,
            review_id=REVIEW_ID,
            review_digest=trusted_case.final_review["review_digest"],
            task_digest=trusted_case.final_review["task_digest"],
            remediation_id=REMEDIATION_ID,
            finding_sha256=finding_sha256(trusted_case.finding),
        )
    assert excinfo.value.code == "finding_not_remediable"


def test_trusted_review_expiry_fails_closed(trusted_case: TrustedCase) -> None:
    now = [0.0]
    service = RemediationService(
        repositories=trusted_case.registry,
        ttl_seconds=1.0,
        digest_secret=b"expiring-remediation-secret",
        clock=lambda: now[0],
    )
    service.register_trusted_review(
        repository_id=REPOSITORY_ID,
        base=trusted_case.base,
        head=trusted_case.head,
        final_review=trusted_case.final_review,
        final_output_sha256=canonical_sha256(trusted_case.final_review),
    )
    now[0] = 2.0
    with pytest.raises(RemediationServiceError) as excinfo:
        service.prepare_remediation(
            repository_id=REPOSITORY_ID,
            base=trusted_case.base,
            head=trusted_case.head,
            review_id=REVIEW_ID,
            review_digest=trusted_case.final_review["review_digest"],
            task_digest=trusted_case.final_review["task_digest"],
            remediation_id=REMEDIATION_ID,
            finding_sha256=finding_sha256(trusted_case.finding),
        )
    assert excinfo.value.code == "trusted_review_not_found"
    assert service.trusted_review_count == 0


def test_oversized_trusted_review_is_not_left_in_store(
    trusted_case: TrustedCase,
) -> None:
    service = RemediationService(
        repositories=trusted_case.registry,
        max_store_bytes=1,
        digest_secret=b"bounded-remediation-secret",
    )
    with pytest.raises(RemediationServiceError) as excinfo:
        service.register_trusted_review(
            repository_id=REPOSITORY_ID,
            base=trusted_case.base,
            head=trusted_case.head,
            final_review=trusted_case.final_review,
            final_output_sha256=canonical_sha256(trusted_case.final_review),
        )
    assert excinfo.value.code == "remediation_store_limit"
    assert service.trusted_review_count == 0


def test_prepare_timeout_cannot_commit_late_state(trusted_case: TrustedCase) -> None:
    service = RemediationService(
        repositories=trusted_case.registry,
        prepare_timeout_seconds=0.01,
        max_prepare_workers=1,
        digest_secret=b"timeout-remediation-secret",
    )
    service.register_trusted_review(
        repository_id=REPOSITORY_ID,
        base=trusted_case.base,
        head=trusted_case.head,
        final_review=trusted_case.final_review,
        final_output_sha256=canonical_sha256(trusted_case.final_review),
    )
    started = threading.Event()
    release = threading.Event()

    def slow_compute(**_arguments: Any) -> Any:
        started.set()
        release.wait(timeout=1.0)
        return None, "synthetic", "synthetic"

    service._compute_patch = slow_compute  # type: ignore[method-assign]
    try:
        with pytest.raises(RemediationServiceError) as excinfo:
            service.prepare_remediation(
                repository_id=REPOSITORY_ID,
                base=trusted_case.base,
                head=trusted_case.head,
                review_id=REVIEW_ID,
                review_digest=trusted_case.final_review["review_digest"],
                task_digest=trusted_case.final_review["task_digest"],
                remediation_id=REMEDIATION_ID,
                finding_sha256=finding_sha256(trusted_case.finding),
            )
        assert excinfo.value.code == "remediation_timeout"
        assert excinfo.value.retryable is True
        assert started.is_set()
        assert service.remediation_count == 0
    finally:
        release.set()


def test_unavailable_remediation_finalizes_fail_closed(tmp_path: Path) -> None:
    repository = tmp_path / "no-successor-repository"
    base, head = _materialize(repository)
    components = repository / "model/components.yaml"
    components.write_text(
        components.read_text(encoding="utf-8").replace(
            "    replaced_by: demo.scoring_v2\n", ""
        ),
        encoding="utf-8",
    )
    # The immutable head itself must contain the no-successor state.
    from scripts.run_seaf_review import _commit

    head = _commit(
        repository,
        "remove synthetic governed successor",
        "2026-07-18T08:02:00Z",
    )
    registry = {
        REPOSITORY_ID: {
            "repository": repository,
            "manifest_path": "dochub.yaml",
            "dependency_mode": "fixture",
        }
    }
    final, finding = _complete_final_review(repository, base, head, registry)
    service = RemediationService(
        repositories=registry,
        digest_secret=b"no-successor-remediation-secret",
    )
    service.register_trusted_review(
        repository_id=REPOSITORY_ID,
        base=base,
        head=head,
        final_review=final,
        final_output_sha256=canonical_sha256(final),
    )
    prepared = service.prepare_remediation(
        repository_id=REPOSITORY_ID,
        base=base,
        head=head,
        review_id=REVIEW_ID,
        review_digest=final["review_digest"],
        task_digest=final["task_digest"],
        remediation_id=REMEDIATION_ID,
        finding_sha256=finding_sha256(finding),
    )
    assert prepared["status"] == "remediation_not_available"
    assert prepared["reason_code"] == "no_declared_successor"
    assert prepared["incomplete"] is True
    validate_json_schema(
        prepared,
        _definition("aga_prepare_remediation")["outputSchema"],
        "$result",
    )

    finalized = service.finalize_remediation(
        remediation_id=REMEDIATION_ID,
        remediation_digest=prepared["remediation_digest"],
    )
    assert finalized["status"] == "remediation_not_available"
    assert finalized["outcome"] == "hitl_required"
    assert finalized["human_review_required"] is True
    assert finalized["auto_merge"] is False
    assert finalized["incomplete"] is True
    validate_json_schema(
        finalized,
        _definition("aga_finalize_remediation")["outputSchema"],
        "$result",
    )
