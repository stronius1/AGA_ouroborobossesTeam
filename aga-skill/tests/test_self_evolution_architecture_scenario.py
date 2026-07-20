# -*- coding: utf-8 -*-
"""Real SEAF graph-remediation coverage for generated E2E scenarios."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.generate_self_evolution_scenario import build_scenario  # noqa: E402
from scripts import run_self_evolution_architecture_scenario as runner  # noqa: E402


def _declared_edge(scenario: dict) -> dict:
    return next(
        edge
        for edge in scenario["graph"]["edges"]
        if edge.get("expected_rule") == runner.RULE_ID
    )


def _edge(graph: dict, edge_id: str) -> dict:
    return next(edge for edge in graph["edges"] if edge["id"] == edge_id)


def test_full_generated_graph_runs_real_review_patch_rereview_and_gate() -> None:
    scenario = build_scenario(seed="architecture-runner", preset="full", parallel_workers=4)
    events: list[dict] = []

    result = runner.run_scenario(scenario, event_sink=events.append)

    declared = _declared_edge(scenario)
    assert result["schema"] == runner.OUTPUT_SCHEMA
    assert result["status"] == "completed"
    assert result["execution"] == {
        "real": True,
        "review_engine": "prepare_seaf_review",
        "remediation_engine": "propose_remediation",
        "workspace": "ephemeral-git",
        "external_side_effects": False,
        "merge_performed": False,
    }
    assert result["summary"] == {
        "nodes": 11,
        "edges": 9,
        "findings_before": 1,
        "findings_after": 0,
        "changed_edges": 1,
        "gate_passed": True,
    }
    assert result["before"]["verdict"] == "request_changes_escalate"
    assert result["after"]["verdict"] == "approve"
    assert result["gate"]["passed"] is True
    assert result["gate"]["target_finding_closed"] is True
    assert result["gate"]["new_findings"] == []
    assert result["remediation"]["edge_id"] == declared["id"]
    assert result["remediation"]["previous_to"] == declared["to"]
    assert result["remediation"]["replacement_to"] == declared["replacement_to"]
    assert result["remediation"]["changed_fields"] == ["to"]
    assert result["remediation"]["patch"]["rule_id"] == "SEAF-004"
    assert result["remediation"]["patch"]["mutation_kind"] == "reroute_target"
    assert "model/integrations.yaml" == result["remediation"]["patch"]["artifact"]
    assert [event["stage"] for event in events] == [
        "materialized",
        "review_started",
        "finding",
        "patch",
        "rereview",
        "gate",
        "result",
    ]
    assert [event["sequence"] for event in events] == list(range(1, 8))
    assert events[2]["finding"]["rule_id"] == "SEAF-004"
    assert events[2]["finding"]["entity_id"] == result["remediation"][
        "materialized_entity_id"
    ]
    assert events[-1]["type"] == "result"
    assert events[-1]["result"] == result


def test_after_graph_is_derived_from_real_patch_and_changes_only_declared_edge() -> None:
    scenario = build_scenario(seed="single-real-change", preset="integration", parallel_workers=3)
    result = runner.run_scenario(scenario)
    declared = _declared_edge(scenario)

    assert result["before"]["graph"] == scenario["graph"]
    assert result["before"]["graph"]["nodes"] == result["after"]["graph"]["nodes"]
    changed: list[str] = []
    for before, after in zip(
        result["before"]["graph"]["edges"],
        result["after"]["graph"]["edges"],
        strict=True,
    ):
        if before != after:
            changed.append(before["id"])
            expected = dict(before)
            expected["to"] = declared["replacement_to"]
            assert after == expected
    assert changed == [declared["id"]]
    assert _edge(result["after"]["graph"], declared["id"])["to"] == declared[
        "replacement_to"
    ]
    assert result["before"]["graph_sha256"] != result["after"]["graph_sha256"]
    assert result["after"]["findings"] == []
    assert "-    to: demo.legacy_scoring" in result["remediation"]["patch"]["diff"]
    assert "+    to: demo.scoring_v2" in result["remediation"]["patch"]["diff"]


def test_runner_uses_the_scenario_declared_edge_not_a_hardcoded_demo_fixture() -> None:
    scenario = build_scenario(seed="dynamic-edge", preset="full", parallel_workers=4)
    declared = _declared_edge(scenario)
    declared.update(
        {
            "id": "partner_to_legacy_archive",
            "from": "demo.partner",
            "to": "demo.legacy_archive",
            "protocol": "SFTP",
            "replacement_to": "demo.archive_v2",
        }
    )

    result = runner.run_scenario(scenario)

    assert result["status"] == "completed"
    assert result["summary"]["nodes"] == 11
    assert result["summary"]["edges"] == 9
    assert result["remediation"]["edge_id"] == "partner_to_legacy_archive"
    assert result["remediation"]["source"] == "demo.partner"
    assert result["remediation"]["previous_to"] == "demo.legacy_archive"
    assert result["remediation"]["replacement_to"] == "demo.archive_v2"
    assert _edge(result["after"]["graph"], "partner_to_legacy_archive")["to"] == (
        "demo.archive_v2"
    )
    assert result["before"]["findings"][0]["entity_id"] == result["remediation"][
        "materialized_entity_id"
    ]


def test_marker_is_not_accepted_without_a_real_seaf_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = build_scenario(seed="marker-is-not-proof", preset="full", parallel_workers=4)
    monkeypatch.setattr(
        runner,
        "prepare_seaf_review",
        lambda _snapshot: {"deterministic_findings": []},
    )

    with pytest.raises(
        runner.ArchitectureScenarioError,
        match="scenario_marker_not_confirmed_by_real_review",
    ):
        runner.run_scenario(scenario)


def test_validate_only_checks_exact_graph_without_running_remediation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = build_scenario(seed="validate-only", preset="full", parallel_workers=4)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("validate-only must not materialize or remediate")

    monkeypatch.setattr(runner, "_materialize_repository", forbidden)
    result = runner.validate_only(scenario)

    assert result["schema"] == runner.VALIDATION_SCHEMA
    assert result["status"] == "validated"
    assert result["summary"] == {
        "nodes": 11,
        "edges": 9,
        "tests": 26,
        "declared_findings": 1,
    }
    assert result["declared_remediation"]["edge_id"] == _declared_edge(scenario)["id"]
    assert all(check["passed"] is True for check in result["checks"])


def test_validate_only_cli_returns_one_structured_document(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenario = build_scenario(seed="validate-only-cli", preset="integration", parallel_workers=3)
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")

    exit_code = runner.main(["--scenario", str(path), "--validate-only"])
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["schema"] == runner.VALIDATION_SCHEMA
    assert result["status"] == "validated"
    assert result["summary"]["nodes"] == 11
    assert result["summary"]["edges"] == 9
    assert "gate" not in result


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda scenario: scenario["graph"].update({"unexpected": []}),
            "scenario_graph_shape_invalid",
        ),
        (
            lambda scenario: scenario["graph"]["nodes"][0].update(
                {"unexpected": True}
            ),
            "scenario_node_shape_invalid",
        ),
        (
            lambda scenario: scenario["graph"]["edges"][0].pop("status"),
            "scenario_edge_shape_invalid",
        ),
        (
            lambda scenario: scenario["summary"].update({"flows": 999}),
            "scenario_summary_mismatch",
        ),
    ],
)
def test_validate_only_enforces_exact_generated_graph_contract(
    mutation,
    error_code: str,
) -> None:
    scenario = build_scenario(seed="exact-graph", preset="full", parallel_workers=4)
    mutation(scenario)

    with pytest.raises(runner.ArchitectureScenarioError, match=error_code):
        runner.validate_only(scenario)


def test_public_materializer_exposes_same_repository_for_live_ouroboros(
    tmp_path: Path,
) -> None:
    scenario = build_scenario(seed="live-materialization", preset="full", parallel_workers=4)
    repository = tmp_path / "architecture"

    materialized = runner.materialize_scenario_repository(scenario, repository)

    declared = _declared_edge(scenario)
    assert materialized.repository == repository
    assert len(materialized.base) == len(materialized.head) == 40
    assert materialized.base != materialized.head
    assert materialized.declared_edge_id == declared["id"]
    assert materialized.materialized_entity_id == materialized.edge_map[declared["id"]]
    assert materialized.dependency_mode == "fixture"
    assert set(materialized.edge_map) == {
        edge["id"] for edge in scenario["graph"]["edges"]
    }
    assert (repository / ".git").is_dir()
    components = (repository / "model" / "components.yaml").read_text(encoding="utf-8")
    integrations = (repository / "model" / "integrations.yaml").read_text(encoding="utf-8")
    assert all(node["id"] in components for node in scenario["graph"]["nodes"])
    assert all(entity_id in integrations for entity_id in materialized.edge_map.values())
    assert f"to: {declared['to']}" in integrations


def test_verified_materializer_has_pinned_gitlinks_overlay_and_clean_checkout(
    tmp_path: Path,
) -> None:
    scenario = build_scenario(seed="verified-live", preset="full", parallel_workers=4)
    repository = tmp_path / "architecture"

    materialized = runner.materialize_scenario_repository(
        scenario,
        repository,
        dependency_mode="verified",
    )

    assert materialized.dependency_mode == "verified"
    assert runner._git(
        repository, "status", "--porcelain=v1", "--untracked-files=all"
    ) == ""
    for revision in (materialized.base, materialized.head):
        tree = runner._git(
            repository,
            "ls-tree",
            revision,
            runner.DEFAULT_ARCHTOOL_PATH,
            runner.DEFAULT_SEAF_CORE_PATH,
        )
        assert (
            f"160000 commit {runner.DEFAULT_ARCHTOOL_COMMIT}\t"
            f"{runner.DEFAULT_ARCHTOOL_PATH}"
        ) in tree
        assert (
            f"160000 commit {runner.DEFAULT_SEAF_CORE_COMMIT}\t"
            f"{runner.DEFAULT_SEAF_CORE_PATH}"
        ) in tree
    manifest = (repository / "dochub.yaml").read_text(encoding="utf-8")
    overlay = (repository / "seaf-core-v1.4.0-overlay.yaml").read_text(
        encoding="utf-8"
    )
    assert "seaf-core-v1.4.0-overlay.yaml" in manifest
    assert "metamodel/aga-extension.yaml" in manifest
    assert "architecture/vendor/seaf-core/" in overlay
    assert "\n  - vendor/seaf-core/" not in overlay

    declared = _declared_edge(scenario)
    base_integrations = runner._git(
        repository,
        "show",
        f"{materialized.base}:model/integrations.yaml",
    )
    head_integrations = runner._git(
        repository,
        "show",
        f"{materialized.head}:model/integrations.yaml",
    )
    assert materialized.edge_map[declared["id"]] not in base_integrations
    assert materialized.edge_map[declared["id"]] in head_integrations
    assert all(
        materialized.edge_map[edge["id"]] in base_integrations
        for edge in scenario["graph"]["edges"]
        if edge["id"] != declared["id"]
    )

    trusted_dependencies = {
        runner.DEFAULT_ARCHTOOL_PATH: {
            "checkout": REPOSITORY_ROOT / runner.DEFAULT_ARCHTOOL_PATH,
            "commit": runner.DEFAULT_ARCHTOOL_COMMIT,
        },
        runner.DEFAULT_SEAF_CORE_PATH: {
            "checkout": REPOSITORY_ROOT / runner.DEFAULT_SEAF_CORE_PATH,
            "commit": runner.DEFAULT_SEAF_CORE_COMMIT,
        },
    }
    with runner.RepositorySnapshotBuilder(
        repository,
        materialized.base,
        materialized.head,
        dependency_mode="verified",
        trusted_dependencies=trusted_dependencies,
    ).build() as snapshot:
        assert snapshot.dependency_verification == "verified-gitlinks"
        assert snapshot.changed_paths == ("model/integrations.yaml",)
        prepared = runner.prepare_seaf_review(snapshot)
        prepared_size = len(json.dumps(prepared, ensure_ascii=False))
        assert 15_000 < prepared_size < 80_000


def test_materializer_rejects_unknown_dependency_mode(tmp_path: Path) -> None:
    scenario = build_scenario(seed="bad-dependency-mode", preset="full", parallel_workers=4)

    with pytest.raises(
        runner.ArchitectureScenarioError,
        match="scenario_dependency_mode_invalid",
    ):
        runner.materialize_scenario_repository(
            scenario,
            tmp_path / "architecture",
            dependency_mode="unsafe",
        )


def test_gate_fails_if_full_graph_contains_an_additional_unremediated_defect() -> None:
    scenario = build_scenario(seed="remaining-defect", preset="full", parallel_workers=4)
    scenario["graph"]["edges"].append(
        {
            "id": "mobile_to_legacy_archive",
            "from": "demo.mobile",
            "to": "demo.legacy_archive",
            "protocol": "SFTP",
            "status": "unchecked",
        }
    )
    scenario["summary"]["flows"] += 1

    result = runner.run_scenario(scenario)

    assert result["status"] == "gate_failed"
    assert result["summary"]["findings_before"] == 2
    assert result["summary"]["findings_after"] == 1
    assert result["gate"]["target_finding_closed"] is True
    assert result["gate"]["passed"] is False
    remaining_check = next(
        check
        for check in result["gate"]["checks"]
        if check["id"] == "review.no_remaining_seaf004"
    )
    assert remaining_check["passed"] is False
    assert result["after"]["findings"][0]["rule_id"] == "SEAF-004"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda scenario: scenario["graph"]["edges"][0].update({"from": "missing.node"}), "scenario_edge_source_missing"),
        (lambda scenario: scenario["graph"]["edges"][0].update({"to": "missing.node"}), "scenario_edge_target_missing"),
        (
            lambda scenario: _declared_edge(scenario).update(
                {"replacement_to": "missing.node"}
            ),
            "scenario_edge_replacement_missing",
        ),
        (
            lambda scenario: next(
                node
                for node in scenario["graph"]["nodes"]
                if node["id"] == "demo.legacy_scoring"
            ).update({"replaced_by": "missing.node"}),
            "scenario_node_successor_invalid",
        ),
        (
            lambda scenario: scenario["graph"]["nodes"].append(
                deepcopy(scenario["graph"]["nodes"][0])
            ),
            "scenario_node_id_duplicate",
        ),
        (
            lambda scenario: scenario["graph"]["edges"].append(
                deepcopy(scenario["graph"]["edges"][0])
            ),
            "scenario_edge_id_duplicate",
        ),
    ],
)
def test_every_node_edge_and_successor_reference_is_validated(
    mutation,
    error_code: str,
) -> None:
    scenario = build_scenario(seed="bad-reference", preset="full", parallel_workers=4)
    mutation(scenario)

    with pytest.raises(runner.ArchitectureScenarioError, match=error_code):
        runner.run_scenario(scenario)


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        (b'{"schema":"x","schema":"y"}', "scenario_json_duplicate_key"),
        (b'{"value":NaN}', "scenario_json_nonfinite"),
        (b"[]", "scenario_document_invalid"),
        (b"\xff", "scenario_json_invalid"),
        (b"", "scenario_file_empty"),
    ],
)
def test_strict_loader_rejects_ambiguous_json(
    tmp_path: Path,
    payload: bytes,
    error_code: str,
) -> None:
    path = tmp_path / "scenario.json"
    path.write_bytes(payload)

    with pytest.raises(runner.ArchitectureScenarioError, match=error_code):
        runner.load_scenario(path)


def test_loader_rejects_symlinks_and_oversized_files(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "scenario.json"
    link.symlink_to(target)
    with pytest.raises(
        runner.ArchitectureScenarioError, match="scenario_file_unavailable"
    ):
        runner.load_scenario(link)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * (runner.MAX_SCENARIO_BYTES + 1))
    with pytest.raises(
        runner.ArchitectureScenarioError, match="scenario_file_too_large"
    ):
        runner.load_scenario(oversized)


def test_events_jsonl_cli_flushes_stages_and_final_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenario = build_scenario(seed="jsonl-cli", preset="governance", parallel_workers=2)
    path = tmp_path / "scenario.json"
    path.write_text(
        json.dumps(scenario, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    exit_code = runner.main(["--scenario", str(path), "--events-jsonl"])
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert exit_code == 0
    assert [record["stage"] for record in records] == [
        "materialized",
        "review_started",
        "finding",
        "patch",
        "rereview",
        "gate",
        "result",
    ]
    assert all(record["schema"] == runner.EVENT_SCHEMA for record in records)
    assert records[-1]["type"] == "result"
    assert records[-1]["result"]["status"] == "completed"
    assert records[-1]["result"]["gate"]["passed"] is True
