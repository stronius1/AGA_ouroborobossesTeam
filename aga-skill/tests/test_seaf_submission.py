# -*- coding: utf-8 -*-
"""Submission lookup uses an actual Git base/head SEAF-native snapshot."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))
PROJECT_EXTENSION_TEXT = (
    PKG_ROOT.parent / "architecture" / "metamodel" / "aga-extension.yaml"
).read_text(encoding="utf-8")

from tools.repository_snapshot import RepositorySnapshotBuilder  # noqa: E402
from tools.seaf_review import prepare_seaf_review  # noqa: E402


def _git(repository: Path, *args: str, date: str | None = None) -> str:
    env = os.environ.copy()
    if date:
        env.update(
            {
                "GIT_AUTHOR_DATE": date,
                "GIT_COMMITTER_DATE": date,
                "GIT_AUTHOR_NAME": "AGA Synthetic Test",
                "GIT_AUTHOR_EMAIL": "aga@example.invalid",
                "GIT_COMMITTER_NAME": "AGA Synthetic Test",
                "GIT_COMMITTER_EMAIL": "aga@example.invalid",
            }
        )
    return subprocess.run(
        ["git", *args], cwd=repository, check=True, capture_output=True,
        text=True, env=env, timeout=30,
    ).stdout.strip()


def _write(repository: Path, relative: str, content: str) -> None:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repository: Path, message: str, date: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message, date=date)
    return _git(repository, "rev-parse", "HEAD")


def test_submission_lookup_uses_seaf_native_snapshot(tmp_path: Path) -> None:
    repository = tmp_path / "architecture"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "AGA Synthetic Test")
    _git(repository, "config", "user.email", "aga@example.invalid")
    _write(
        repository,
        "dochub.yaml",
        """aga:
  schema: seaf-core/v1.4.0
  extensions: [aga.project/v1]
  data_classification: synthetic-public
imports: [aga-extension.yaml, model/components.yaml, model/integrations.yaml, model/adrs.yaml]
""",
    )
    _write(repository, "aga-extension.yaml", PROJECT_EXTENSION_TEXT)
    _write(
        repository,
        "model/components.yaml",
        """components:
  demo.portal:
    title: Portal
    entity: component
    description: Synthetic portal
    owner: Synthetic Team
    criticality: mission_critical
    target_status: strategic
  demo.legacy:
    title: Legacy
    entity: component
    description: Synthetic retiring system
    owner: Synthetic Team
    criticality: high
    target_status: eliminate
""",
    )
    _write(
        repository,
        "model/integrations.yaml",
        """seaf.app.integrations:
  demo.preexisting_to_legacy:
    title: Existing legacy dependency
    description: Existing synthetic dependency predates the reviewed change.
    from: demo.portal
    to: demo.legacy
""",
    )
    _write(repository, "model/adrs.yaml", "seaf.change.adr: {}\n")
    base = _commit(repository, "base", "2026-07-15T00:00:00Z")

    _write(
        repository,
        "model/integrations.yaml",
        """seaf.app.integrations:
  demo.preexisting_to_legacy:
    title: Existing legacy dependency
    description: Existing synthetic dependency predates the reviewed change.
    from: demo.portal
    to: demo.legacy
  demo.portal_to_legacy:
    title: New legacy dependency
    description: Portal synchronously calls the retiring legacy system.
    from: demo.portal
    to: demo.legacy
""",
    )
    head = _commit(repository, "head", "2026-07-15T00:01:00Z")

    with RepositorySnapshotBuilder(
        repository, base, head, dependency_mode="fixture"
    ).build() as snapshot:
        result = prepare_seaf_review(snapshot)

    assert result["schema"] == "aga.prepared-review/v1"
    assert result["status"] == "needs_semantic_review"
    assert result["verdict"] == "incomplete"
    assert result["provisional_verdict"] == "request_changes_escalate"
    finding = result["deterministic_findings"][0]
    assert len(result["deterministic_findings"]) == 1
    assert finding["rule_id"] == "SEAF-004"
    assert finding["entity_id"] == "demo.portal_to_legacy"
    assert finding["artifact"] == "model/integrations.yaml"
    assert finding["location"].endswith("/to")
    assert finding["base_revision"] == base
    assert finding["head_revision"] == head
    assert finding["source_ref"] == "aga-extension.yaml#/entities/components/schema"
    assert result["review_provenance"]["base_commit"] == base
    assert result["review_provenance"]["dependency_verification"] == "fixture-unverified"
    assert {task["rule_id"] for task in result["semantic_tasks"]} == {
        "PRIN-004", "PRIN-005", "PRIN-006", "PRIN-007"
    }


@pytest.mark.parametrize(
    ("head_components", "expected_rule", "expected_source_ref"),
    [
        (
            """components:
  demo.source:
    title: Source
    entity: component
    owner: Synthetic Team
    criticality: high
    target_status: strategic
""",
            "SEAF-001",
            "aga-skill/rules/seaf-checks.yaml#/rules/0",
        ),
        (
            """components:
  demo.source:
    title: Source
    entity: component
    owner: Synthetic Team
    criticality: high
    target_status: strategic
  demo.target:
    title: Target
    entity: component
    owner: Synthetic Team
    criticality: high
    target_status: eliminate
""",
            "SEAF-004",
            "aga-extension.yaml#/entities/components/schema",
        ),
    ],
)
def test_unchanged_flow_is_reviewed_when_endpoint_lifecycle_changes(
    tmp_path: Path,
    head_components: str,
    expected_rule: str,
    expected_source_ref: str,
) -> None:
    repository = tmp_path / "endpoint-change"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "AGA Synthetic Test")
    _git(repository, "config", "user.email", "aga@example.invalid")
    _write(
        repository,
        "dochub.yaml",
        """aga:
  schema: seaf-core/v1.4.0
  extensions: [aga.project/v1]
  data_classification: synthetic-public
imports: [aga-extension.yaml, components.yaml, integrations.yaml, adrs.yaml]
""",
    )
    _write(repository, "aga-extension.yaml", PROJECT_EXTENSION_TEXT)
    _write(
        repository,
        "components.yaml",
        """components:
  demo.source:
    title: Source
    entity: component
    owner: Synthetic Team
    criticality: high
    target_status: strategic
  demo.target:
    title: Target
    entity: component
    owner: Synthetic Team
    criticality: high
    target_status: strategic
""",
    )
    _write(
        repository,
        "integrations.yaml",
        """seaf.app.integrations:
  demo.source_to_target:
    title: Source to target
    description: Unchanged synthetic integration.
    from: demo.source
    to: demo.target
""",
    )
    _write(repository, "adrs.yaml", "seaf.change.adr: {}\n")
    base = _commit(repository, "endpoint base", "2026-07-15T01:00:00Z")
    _write(repository, "components.yaml", head_components)
    head = _commit(repository, "endpoint head", "2026-07-15T01:01:00Z")

    with RepositorySnapshotBuilder(
        repository, base, head, dependency_mode="fixture"
    ).build() as snapshot:
        result = prepare_seaf_review(snapshot)

    assert len(result["deterministic_findings"]) == 1
    finding = result["deterministic_findings"][0]
    assert finding["rule_id"] == expected_rule
    assert finding["entity_id"] == "demo.source_to_target"
    assert finding["source_ref"] == expected_source_ref
