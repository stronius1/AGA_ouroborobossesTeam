# -*- coding: utf-8 -*-
"""Contract tests for the synthetic E2E scenario and real shard executor."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.generate_self_evolution_scenario import (  # noqa: E402
    MAX_PREVIEW_CHARS,
    SCHEMA as SCENARIO_SCHEMA,
    ScenarioError,
    build_scenario,
    build_test_catalog,
)
from scripts.run_self_evolution_test_shard import (  # noqa: E402
    SCHEMA as SHARD_SCHEMA,
    execute_shard,
)


def _case(result: dict, case_id: str) -> dict:
    return next(item for item in result["cases"] if item["id"] == case_id)


def _write_catalog_source(
    root: Path,
    *,
    changed_file: str = "flows/IF-0001.md",
    content: str = "---\nid: IF-0001\n---\nSynthetic input.\n",
) -> Path:
    golden = root / "aga-skill" / "golden"
    case_root = golden / "prs" / "pr-01"
    artifact = case_root / "files" / "flows" / "IF-0001.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(content, encoding="utf-8")
    (case_root / "meta.yaml").write_text(
        "id: pr-01\n"
        "title: Synthetic case\n"
        f"changed_files: [{changed_file!r}]\n"
        "context_files: []\n",
        encoding="utf-8",
    )
    (golden / "corpus.yaml").write_text(
        "schema_version: 1\n"
        "cases:\n"
        "  - id: pr-01\n"
        "    title: Synthetic case\n"
        "    scenario: Safe preview contract\n"
        "    materialized: true\n"
        "    expected: {findings: [], outcome: approve}\n",
        encoding="utf-8",
    )
    return artifact


def test_same_seed_produces_the_same_complete_scenario() -> None:
    first = build_scenario(seed="deterministic-e2e", preset="full", parallel_workers=4)
    second = build_scenario(seed="deterministic-e2e", preset="full", parallel_workers=4)

    assert first == second
    assert first["schema"] == SCENARIO_SCHEMA
    assert first["scenario_id"].startswith("e2e-")
    assert first["agent_plan"]["real_execution"] is True


def test_distinct_seeds_materially_change_work_order_and_architecture() -> None:
    first = build_scenario(seed="scale-a", preset="full", parallel_workers=4)
    second = build_scenario(seed="scale-b", preset="full", parallel_workers=4)

    assert first["scenario_id"] != second["scenario_id"]
    assert [case["id"] for case in first["tests"]] != [
        case["id"] for case in second["tests"]
    ]
    assert first["graph"]["edges"] != second["graph"]["edges"]
    assert {
        (edge["from"], edge["to"], edge["protocol"])
        for edge in first["graph"]["edges"]
    } != {
        (edge["from"], edge["to"], edge["protocol"])
        for edge in second["graph"]["edges"]
    }


@pytest.mark.parametrize(
    ("preset", "expected_count", "expected_domains"),
    [
        ("demo", 6, {"clean", "ADR", "DIAG", "PRIN", "SEAF"}),
        ("full", 26, {"clean", "ADR", "DIAG", "PRIN", "SEAF"}),
        ("integration", 18, {"clean", "PRIN", "SEAF"}),
        ("governance", 17, {"clean", "ADR", "DIAG", "PRIN"}),
    ],
)
def test_presets_select_the_declared_real_corpus(
    preset: str,
    expected_count: int,
    expected_domains: set[str],
) -> None:
    scenario = build_scenario(seed="preset-contract", preset=preset, parallel_workers=3)

    assert len(scenario["tests"]) == expected_count
    assert scenario["summary"]["tests"] == expected_count
    assert set(scenario["summary"]["domains"]) == expected_domains
    assert {case["domain"] for case in scenario["tests"]} == expected_domains
    assert len({case["id"] for case in scenario["tests"]}) == expected_count


def test_demo_preset_contains_the_key_cross_domain_controls() -> None:
    scenario = build_scenario(
        seed="short-live-demo", preset="demo", parallel_workers=2
    )

    assert {case["id"] for case in scenario["tests"]} == {
        "pr-09",
        "pr-12",
        "pr-15",
        "pr-16",
        "pr-18",
        "pr-21",
    }


def test_catalog_exposes_only_relative_paths_and_bounded_input_previews(
    tmp_path: Path,
) -> None:
    payload = "x" * (MAX_PREVIEW_CHARS + 200)
    _write_catalog_source(tmp_path, content=payload)

    catalog = build_test_catalog(tmp_path)

    assert len(catalog) == 1
    case = catalog[0]
    assert case["changed_files"] == ["flows/IF-0001.md"]
    assert case["input_artifacts"] == [
        {
            "path": "flows/IF-0001.md",
            "preview": "x" * MAX_PREVIEW_CHARS + "\n…",
            "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }
    ]
    for artifact in case["input_artifacts"]:
        path = PurePosixPath(artifact["path"])
        assert not path.is_absolute()
        assert ".." not in path.parts
        assert "\\" not in artifact["path"]
        assert str(tmp_path) not in artifact["preview"]
        assert len(artifact["preview"]) <= MAX_PREVIEW_CHARS + 2


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.md",
        "/tmp/outside.md",
        r"flows\\outside.md",
    ],
)
def test_catalog_rejects_unsafe_artifact_paths(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    _write_catalog_source(tmp_path, changed_file=unsafe_path)

    with pytest.raises(ScenarioError, match="scenario_artifact_invalid"):
        build_test_catalog(tmp_path)


def test_catalog_rejects_an_artifact_symlink_that_escapes_case_root(
    tmp_path: Path,
) -> None:
    artifact = _write_catalog_source(tmp_path)
    artifact.unlink()
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    artifact.symlink_to(outside)

    with pytest.raises(ScenarioError, match="scenario_artifact_invalid"):
        build_test_catalog(tmp_path)


def test_real_candidate_fixes_pr15_without_weakening_pr16() -> None:
    selected = ("pr-15", "pr-16")
    baseline = execute_shard(
        ruleset="baseline",
        case_ids=selected,
        worker_id="worker-1",
    )
    candidate = execute_shard(
        ruleset="candidate",
        case_ids=selected,
        worker_id="worker-2",
    )

    assert baseline["schema"] == candidate["schema"] == SHARD_SCHEMA
    assert baseline["status"] == candidate["status"] == "completed"
    assert (baseline["passed"], baseline["failed"]) == (1, 1)
    assert (candidate["passed"], candidate["failed"]) == (2, 0)

    baseline_pr15 = _case(baseline, "pr-15")
    candidate_pr15 = _case(candidate, "pr-15")
    assert baseline_pr15["passed"] is False
    assert baseline_pr15["actual_outcome"] == "request_changes_escalate"
    assert baseline_pr15["fp"] == ["PRIN-002"]
    assert candidate_pr15["passed"] is True
    assert candidate_pr15["actual_outcome"] == "approve"
    assert candidate_pr15["actual_findings"] == []
    assert candidate_pr15["suppressed"] == [
        {"rule_id": "PRIN-002", "exception": "EXC-PRIN-002-001"}
    ]

    for result in (baseline, candidate):
        protected = _case(result, "pr-16")
        assert protected["passed"] is True
        assert protected["actual_outcome"] == "request_changes_escalate"
        assert protected["tp"] == ["PRIN-002"]
        assert protected["fp"] == []
        assert protected["fn"] == []
        assert protected["suppressed"] == []
        assert [item["rule_id"] for item in protected["actual_findings"]] == [
            "PRIN-002"
        ]


@pytest.mark.parametrize(
    "seed",
    ["", "../escape", "contains space", "slash/name", "x" * 65, None, True],
)
def test_scenario_rejects_invalid_seeds(seed: object) -> None:
    with pytest.raises(ScenarioError, match="scenario_seed_invalid"):
        build_scenario(seed=seed, preset="full", parallel_workers=4)  # type: ignore[arg-type]


@pytest.mark.parametrize("preset", ["", "unknown", None])
def test_scenario_rejects_invalid_presets(preset: object) -> None:
    with pytest.raises(ScenarioError, match="scenario_preset_invalid"):
        build_scenario(seed="valid", preset=preset, parallel_workers=4)  # type: ignore[arg-type]


@pytest.mark.parametrize("workers", [True, False, 0, 1, 5, "4", None])
def test_scenario_rejects_invalid_worker_counts(workers: object) -> None:
    with pytest.raises(ScenarioError, match="scenario_workers_invalid"):
        build_scenario(seed="valid", preset="full", parallel_workers=workers)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "arguments",
    [
        {"ruleset": "other", "case_ids": ("pr-15",), "worker_id": "worker-1"},
        {"ruleset": "baseline", "case_ids": ("pr-15",), "worker_id": "worker-0"},
        {"ruleset": "baseline", "case_ids": (), "worker_id": "worker-1"},
        {
            "ruleset": "baseline",
            "case_ids": ("pr-15", "pr-15"),
            "worker_id": "worker-1",
        },
        {"ruleset": "baseline", "case_ids": ("pr-99",), "worker_id": "worker-1"},
        {"ruleset": "baseline", "case_ids": ("PR-15",), "worker_id": "worker-1"},
    ],
)
def test_shard_rejects_invalid_execution_inputs(arguments: dict) -> None:
    with pytest.raises(ValueError):
        execute_shard(**arguments)
