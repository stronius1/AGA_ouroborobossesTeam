# -*- coding: utf-8 -*-
"""Deterministic and sanitized browser fixture coverage."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.generate_self_evolution_ui_fixture import (  # noqa: E402
    SCHEMA,
    UIFixtureError,
    build_fixture,
    build_fixture_from_evidence,
    generate_from_paths,
)


def _architecture() -> dict:
    return {
        "schema": "aga.architecture-self-evolution/v1",
        "status": "local_candidate_ready",
        "data_classification": "synthetic-public",
        "correlation_sha256": "a" * 64,
        "head": "1" * 40,
        "patched_head": "2" * 40,
        "model": "synthetic/model",
        "provider": "openrouter",
        "runtime": {"name": "ouroboros", "version": "6.64.1", "source_commit": "3" * 40},
        "review_before": {
            "task_id": "before-task",
            "final": {
                "verdict": "request_changes_escalate",
                "findings": [{"severity": "blocker"}],
            },
            "receipts": {"tool_names": ["aga_prepare_review", "aga_finalize_review"]},
            "model_usage": {"known_cost_usd": 0.01},
        },
        "remediation": {
            "task_id": "remediation-task",
            "final": {
                "outcome": "candidate_ready",
                "patch": {
                    "artifact": "model/integrations.yaml",
                    "entity_id": "demo.checkout_to_legacy",
                    "eliminated_component": "demo.legacy",
                    "replacement_component": "demo.v2",
                    "rule_id": "SEAF-004",
                    "summary": "Reroute the synthetic dependency.",
                    "diff": "--- a/model/integrations.yaml\n+++ b/model/integrations.yaml\n@@ -1,3 +1,3 @@\n     from: demo.checkout\n-    to: demo.legacy\n+    to: demo.v2\n",
                },
            },
            "receipts": [
                {"tool": "aga_prepare_remediation"},
                {"tool": "aga_finalize_remediation"},
            ],
            "model_usage": {"known_cost_usd": 0.02},
        },
        "review_after": {
            "task_id": "after-task",
            "final": {"verdict": "approve", "findings": []},
            "receipts": {"tool_names": ["aga_prepare_review", "aga_finalize_review"]},
            "model_usage": {"known_cost_usd": 0.03},
        },
        "gate": {"passed": True},
    }


def _manifest() -> dict:
    return {
        "schema": "aga.candidate-manifest/v1",
        "cycle_id": "aga-test-cycle",
        "version_from": "2.0.0",
        "version_to": "2.1.0",
        "gate_passed": True,
        "human_confirmation_required": True,
        "auto_merge": False,
    }


def _metrics(*, candidate: bool) -> dict:
    return {
        "cases_evaluated": 26,
        "precision": 1.0 if candidate else 0.9524,
        "recall": 1.0,
        "blocker_recall": 1.0,
        "exact_case_accuracy": 1.0 if candidate else 0.9615,
        "weighted_cost": 0 if candidate else 2,
        "fp": {"blocker": 0, "major": 0 if candidate else 1, "minor": 0},
        "fn": {"blocker": 0, "major": 0, "minor": 0},
    }


RULE_DIFF = """--- a/rules/principles.yaml
+++ b/rules/principles.yaml
@@ -1 +1,2 @@
   id: PRIN-002
-  exceptions: []
+  exceptions:
+    - id: EXC-PRIN-002-001
"""


def _publisher() -> dict:
    return {
        "details": {"candidate_branch": "skill/evolution-test"},
        "external_side_effects": False,
    }


def test_fixture_is_deterministic_and_ui_ready() -> None:
    arguments = {
        "architecture_evidence": _architecture(),
        "rule_manifest": _manifest(),
        "rule_metrics_before": _metrics(candidate=False),
        "rule_metrics_after": _metrics(candidate=True),
        "rule_diff": RULE_DIFF,
        "rule_publisher": _publisher(),
    }
    first = build_fixture_from_evidence(**arguments)
    second = build_fixture_from_evidence(**arguments)
    assert first == second
    assert first["schema"] == SCHEMA
    assert first["scenario_id"].startswith("self-evolution-")
    assert first["architecture_evolution"]["before"]["edges"][0]["to"] == "demo.legacy"
    assert first["architecture_evolution"]["after"]["edges"][0]["to"] == "demo.v2"
    assert first["rule_evolution"]["tests"]["before"]["precision"] == 0.9524
    assert first["rule_evolution"]["tests"]["after"]["precision"] == 1.0
    assert [step["timeline_id"] for step in first["ouroboros"]["visible_steps"]] == [
        "architecture.review_before",
        "architecture.remediation",
        "architecture.review_after",
    ]
    assert all(
        set(("id", "label", "actor", "status", "detail")) <= set(item)
        for item in first["architecture_evolution"]["timeline"]
        + first["rule_evolution"]["timeline"]
    )


def test_fixture_allows_additional_semantic_finding_before_remediation() -> None:
    architecture = _architecture()
    architecture["review_before"]["final"]["findings"] = [
        {
            "rule_id": "SEAF-004",
            "severity": "blocker",
            "origin": "deterministic",
        },
        {
            "rule_id": "PRIN-007",
            "severity": "major",
            "origin": "semantic",
        },
    ]

    fixture = build_fixture_from_evidence(
        architecture_evidence=architecture,
        rule_manifest=_manifest(),
        rule_metrics_before=_metrics(candidate=False),
        rule_metrics_after=_metrics(candidate=True),
        rule_diff=RULE_DIFF,
        rule_publisher=_publisher(),
    )

    assert fixture["architecture_evolution"]["change"]["rule_id"] == "SEAF-004"


def test_fixture_rejects_secret_or_absolute_path() -> None:
    architecture = _architecture()
    architecture["remediation"]["final"]["patch"]["summary"] = "secret sk-or-v1-abcdefghijk"
    with pytest.raises(UIFixtureError, match="output_contains_secret_marker"):
        build_fixture_from_evidence(
            architecture_evidence=architecture,
            rule_manifest=_manifest(),
            rule_metrics_before=_metrics(candidate=False),
            rule_metrics_after=_metrics(candidate=True),
            rule_diff=RULE_DIFF,
            rule_publisher=_publisher(),
        )

    architecture = _architecture()
    architecture["remediation"]["final"]["patch"]["summary"] = "see /Users/example/private"
    with pytest.raises(UIFixtureError, match="output_contains_absolute_path"):
        build_fixture_from_evidence(
            architecture_evidence=architecture,
            rule_manifest=_manifest(),
            rule_metrics_before=_metrics(candidate=False),
            rule_metrics_after=_metrics(candidate=True),
            rule_diff=RULE_DIFF,
            rule_publisher=_publisher(),
        )


def test_real_evidence_materializes_same_document_twice(tmp_path: Path) -> None:
    paths = {
        "architecture_evidence": REPOSITORY_ROOT / "docs/evidence/ouroboros-self-evolution-v1.json",
        "rule_manifest": REPOSITORY_ROOT / "aga-skill/build/candidate-manifest.json",
        "rule_metrics_before": REPOSITORY_ROOT / "aga-skill/build/metrics-baseline.json",
        "rule_metrics_after": REPOSITORY_ROOT / "aga-skill/build/metrics-candidate.json",
        "rule_diff": REPOSITORY_ROOT / "aga-skill/build/rules.diff",
        "rule_publisher": REPOSITORY_ROOT / "aga-skill/build/publisher-result.json",
    }
    first = generate_from_paths(**paths)
    second = generate_from_paths(**paths)
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )
    assert first["classification"] == "synthetic-public"
    assert first["summary"] == {
        "architecture_gate_passed": True,
        "rule_gate_passed": True,
        "human_review_required": True,
        "external_side_effects": False,
    }
    assert build_fixture(REPOSITORY_ROOT) == first
