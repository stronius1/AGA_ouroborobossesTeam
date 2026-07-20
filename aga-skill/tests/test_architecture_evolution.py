# -*- coding: utf-8 -*-
"""Offline host-boundary coverage for the live architecture runner."""

from __future__ import annotations

from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for root in (REPOSITORY_ROOT, REPOSITORY_ROOT / "aga-skill"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts.run_architecture_evolution import (  # noqa: E402
    _materialize_candidate,
    _materialize_demo,
    _trusted_dependencies,
)
from tools.remediation_service import (  # noqa: E402
    RemediationService,
    canonical_sha256,
    finding_sha256,
)
from tools.review_service import (  # noqa: E402
    ReviewService,
    SEMANTIC_PREDICATES,
    SEMANTIC_RULE_IDS,
)


def _clean_semantic_result(prepared: dict) -> dict:
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


def _review_service(scenario) -> ReviewService:
    return ReviewService(
        repositories={
            scenario.repository_id: {
                "repository": scenario.repository,
                "manifest_path": "dochub.yaml",
                "dependency_mode": "verified",
                "trusted_dependencies": _trusted_dependencies(),
            }
        }
    )


def test_demo_patch_and_adr_are_materialized_in_isolated_branch(tmp_path: Path) -> None:
    scenario = _materialize_demo(tmp_path / "run", "aga-offline-evolution")
    review_service = _review_service(scenario)
    prepared = review_service.prepare_review(
        repository_id=scenario.repository_id,
        base=scenario.base,
        head=scenario.head,
        review_id="offline-review",
    )
    finding = next(
        item
        for item in prepared["deterministic_findings"]
        if item["rule_id"] == "SEAF-004"
    )
    final_review = review_service.finalize_review(
        review_id=prepared["review_id"],
        review_digest=prepared["review_digest"],
        task_digest=prepared["task_digest"],
        semantic_result=_clean_semantic_result(prepared),
    )
    remediation_service = RemediationService(
        repositories={
            scenario.repository_id: {
                "repository": scenario.repository,
                "manifest_path": "dochub.yaml",
                "dependency_mode": "verified",
                "trusted_dependencies": _trusted_dependencies(),
            }
        }
    )
    remediation_service.register_trusted_review(
        repository_id=scenario.repository_id,
        base=scenario.base,
        head=scenario.head,
        final_review=final_review,
        final_output_sha256=canonical_sha256(final_review),
    )
    prepared_remediation = remediation_service.prepare_remediation(
        repository_id=scenario.repository_id,
        base=scenario.base,
        head=scenario.head,
        review_id=final_review["review_id"],
        review_digest=final_review["review_digest"],
        task_digest=final_review["task_digest"],
        remediation_id="offline-remediation",
        finding_sha256=finding_sha256(finding),
    )
    final_remediation = remediation_service.finalize_remediation(
        remediation_id="offline-remediation",
        remediation_digest=prepared_remediation["remediation_digest"],
        candidate=prepared_remediation["candidate"],
    )
    materialized = _materialize_candidate(
        scenario=scenario,
        remediation={"final": final_remediation},
        run_root=tmp_path / "run",
        correlation_digest="a" * 64,
    )
    assert materialized["branch_name"] == "aga/architecture-aaaaaaaaaaaaaaaa"
    assert materialized["patched_head"] != scenario.head
    repeated = _materialize_candidate(
        scenario=scenario,
        remediation={"final": final_remediation},
        run_root=tmp_path / "run",
        correlation_digest="a" * 64,
    )
    assert repeated["patched_head"] == materialized["patched_head"]
    assert repeated["idempotent"] is True
    adr_text = (materialized["worktree"] / "model" / "adrs.yaml").read_text(
        encoding="utf-8"
    )
    assert materialized["adr_id"] in adr_text
    assert "strategic successor" in adr_text
    changed = [
        line
        for line in final_remediation["patch"]["diff"].splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert changed == [
        "-    to: demo.legacy_scoring",
        "+    to: demo.scoring_v2",
    ]
    patched_service = ReviewService(
        repositories={
            "aga-offline-patched": {
                "repository": materialized["worktree"],
                "manifest_path": "dochub.yaml",
                "dependency_mode": "verified",
                "trusted_dependencies": _trusted_dependencies(),
            }
        }
    )
    re_prepared = patched_service.prepare_review(
        repository_id="aga-offline-patched",
        base=scenario.head,
        head=materialized["patched_head"],
        review_id="offline-rereview",
    )
    assert not any(
        item["rule_id"] == "SEAF-004"
        for item in re_prepared["deterministic_findings"]
    )
