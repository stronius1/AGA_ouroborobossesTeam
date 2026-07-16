# -*- coding: utf-8 -*-
"""Independent GigaAgent basket, scorer, and mode-separation tests."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPOSITORY_ROOT / "evaluation" / "gigaagent" / "runner.py"
FIXTURE_BUNDLE = (
    REPOSITORY_ROOT
    / "evaluation"
    / "gigaagent"
    / "fixtures"
    / "sanitized-response-bundle.json"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("aga_gigaagent_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _bundle() -> dict:
    return json.loads(FIXTURE_BUNDLE.read_text(encoding="utf-8"))


def _write_bundle(tmp_path: Path, bundle: dict, name: str = "bundle.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return path


def _recorded_revisions(bundle: dict) -> dict[str, dict[str, str]]:
    return {
        response["case_id"]: {
            "base": response["base_revision"],
            "head": response["head_revision"],
        }
        for response in bundle["responses"]
    }


def test_frozen_corpus_is_balanced_and_ground_truth_lock_is_independent():
    paths = runner.corpus_files()
    digest = runner.verify_lock(paths)
    cases = runner._cases_from_paths(paths)

    assert len(cases) == 16
    assert digest == "df2d16746342fe71dedadb04252bfdec9c670a2bed65fe001b784bba15bba951"
    assert runner.ground_truth_hash(cases) == (
        "80d465f0b01dff5acad92946b99d7009da987da7eeeb97df01f569415d33ad01"
    )
    balance = runner._validate_balance(cases)
    assert balance["split_counts"] == {"development": 8, "holdout": 8}
    assert all(balance["coverage"].values())

    changed = copy.deepcopy(cases)
    changed[0]["labels"] = [*changed[0]["labels"], "post-lock-change"]
    assert runner.ground_truth_hash(changed) != runner.ground_truth_hash(cases)


def test_all_cases_materialize_as_nonempty_git_and_valid_seaf_native_workspaces():
    paths = runner.corpus_files()
    revisions = runner.materialize_all(paths)

    assert len(revisions) == 16
    for case_id, pair in revisions.items():
        assert re.fullmatch(r"[0-9a-f]{40}", pair["base"]), case_id
        assert re.fullmatch(r"[0-9a-f]{40}", pair["head"]), case_id
        assert pair["base"] != pair["head"]
        assert pair["changed_files"]
        assert set(pair["base_entities"]) == {"systems", "integrations", "adrs", "diagrams"}
        assert set(pair["head_entities"]) == {"systems", "integrations", "adrs", "diagrams"}


def test_materialization_ignores_hostile_global_git_configuration(tmp_path, monkeypatch):
    marker = tmp_path / "host-git-code-executed"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    pre_commit = hooks / "pre-commit"
    pre_commit.write_text(
        "#!/bin/sh\nprintf 'hook\\n' >> \"$HOSTILE_GIT_MARKER\"\nexit 97\n",
        encoding="utf-8",
    )
    pre_commit.chmod(0o755)
    filter_script = tmp_path / "hostile-filter.sh"
    filter_script.write_text(
        "#!/bin/sh\nprintf 'filter\\n' >> \"$HOSTILE_GIT_MARKER\"\ncat\n",
        encoding="utf-8",
    )
    filter_script.chmod(0o755)
    attributes = tmp_path / "hostile-attributes"
    attributes.write_text("* filter=hostile\n", encoding="utf-8")
    hostile_config = tmp_path / "hostile.gitconfig"
    hostile_config.write_text(
        "\n".join(
            (
                "[init]",
                "\tdefaultObjectFormat = sha256",
                "[commit]",
                "\tgpgSign = true",
                "[core]",
                f"\thooksPath = {hooks.as_posix()}",
                f"\tattributesFile = {attributes.as_posix()}",
                '[filter "hostile"]',
                f"\tclean = {filter_script.as_posix()}",
                f"\tsmudge = {filter_script.as_posix()}",
                "\trequired = true",
                "",
            )
        ),
        encoding="utf-8",
    )
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    (hostile_home / ".gitconfig").write_bytes(hostile_config.read_bytes())
    monkeypatch.setenv("HOME", str(hostile_home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile_config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(hostile_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "0")
    monkeypatch.setenv("GIT_DEFAULT_HASH", "sha256")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hooks))
    monkeypatch.setenv("HOSTILE_GIT_MARKER", str(marker))

    case = runner._cases_from_paths(runner.corpus_files())[0]
    pair = runner.materialize_case(case)
    recorded = _recorded_revisions(_bundle())[case["id"]]

    assert pair["base"] == recorded["base"]
    assert pair["head"] == recorded["head"]
    assert re.fullmatch(r"[0-9a-f]{40}", pair["base"])
    assert re.fullmatch(r"[0-9a-f]{40}", pair["head"])
    assert not marker.exists()


def test_fixture_bundle_scores_every_case_but_is_never_release_evidence():
    result = runner.score_response_bundle(FIXTURE_BUNDLE, mode="fixture")

    assert result["schema"] == runner.RESULTS_SCHEMA
    assert result["status"] == "fixture_scored_non_release"
    assert result["measurement_class"] == "synthetic_fixture"
    assert result["cases_evaluated"] == 16
    assert len(result["runs"]) == 16
    for split in ("development", "holdout"):
        metrics = result[split]
        assert metrics["cases_evaluated"] == 8
        assert metrics["precision"] == 1.0
        assert metrics["recall"] == 1.0
        assert metrics["blocker_recall"] == 1.0
        assert metrics["outcome_accuracy"] == 1.0
        assert metrics["exact_case_accuracy"] == 1.0
        assert metrics["schema_valid_rate"] == 1.0
        assert metrics["invalid_or_hallucinated_evidence_rate"] == 0.0
        assert metrics["unsafe_approve_count"] == 0
        assert metrics["latency_ms"]["count"] == 8
    assert all(row["assessment"] == "PASS" and row["reason"] for row in result["runs"])
    assert all("raw_sanitized_response" in row for row in result["runs"])
    assert all("normalized_output" in row for row in result["runs"])
    assert result["gate"]["evaluation_passed"] is True
    assert result["gate"]["release_eligible"] is False
    assert result["gate"]["release_passed"] is False


def test_scorer_counts_schema_hallucination_and_unsafe_approve_failures(tmp_path):
    bundle = _bundle()
    responses = {item["case_id"]: item for item in bundle["responses"]}
    responses["ga-01-reuse-duplicate"]["normalized"] = {
        "status": "complete",
        "verdict": "approve",
        "findings": [],
    }
    responses["ga-02-reuse-existing"]["normalized"]["findings"] = [
        {
            "rule_id": "PRIN-004",
            "severity": "major",
            "confidence": 0.9,
            "artifact": "model/components.yaml",
            "location": "/components/demo.does_not_exist",
            "evidence": "Invented duplicate capability",
            "source_ref": "aga-skill/rules/principles.yaml#/rules/3",
            "suggested_fix": "Remove it.",
        }
    ]
    responses["ga-03-second-master"]["normalized"]["unexpected"] = True

    result = runner.score_response_bundle(_write_bundle(tmp_path, bundle), mode="fixture")
    metrics = result["development"]

    assert metrics["schema_valid_rate"] == 0.875
    assert metrics["invalid_or_hallucinated_evidence_count"] == 1
    assert metrics["invalid_or_hallucinated_evidence_rate"] == pytest.approx(1 / 3)
    assert metrics["unsafe_approve_count"] == 1
    assert metrics["precision"] == pytest.approx(2 / 3)
    assert metrics["recall"] == 0.5
    assert metrics["exact_case_accuracy"] == 0.625
    assert result["gate"]["evaluation_passed"] is False
    failed = {row["case_id"]: row for row in result["runs"] if row["assessment"] == "FAIL"}
    assert "unsafe approve" in failed["ga-01-reuse-duplicate"]["reason"]
    assert "invalid/hallucinated evidence" in failed["ga-02-reuse-existing"]["reason"]
    assert failed["ga-03-second-master"]["schema_valid"] is False


def test_resolving_but_wrong_finding_location_does_not_match_ground_truth(tmp_path):
    bundle = _bundle()
    response = next(
        item for item in bundle["responses"] if item["case_id"] == "ga-01-reuse-duplicate"
    )
    response["normalized"]["findings"][0]["location"] = "/components/demo.profile"

    result = runner.score_response_bundle(_write_bundle(tmp_path, bundle), mode="fixture")
    run = next(item for item in result["runs"] if item["case_id"] == response["case_id"])

    assert run["evidence_checks"][0]["valid"] is True
    assert run["assessment"] == "FAIL"
    assert len(run["fp"]) == 1
    assert len(run["fn"]) == 1
    assert result["gate"]["evaluation_passed"] is False


def test_bundle_mode_and_output_paths_are_strictly_separated(tmp_path):
    bundle = _bundle()
    path = _write_bundle(tmp_path, bundle)
    revisions = _recorded_revisions(bundle)

    with pytest.raises(ValueError, match="does not match"):
        runner._load_bundle(
            path,
            mode="real",
            corpus_digest=bundle["corpus_hash"],
            revisions=revisions,
        )
    with pytest.raises(ValueError, match="real mode must write only"):
        runner._write_results({}, tmp_path / "real.json", mode="real")
    with pytest.raises(ValueError, match="cannot overwrite"):
        runner._write_results({}, runner.REAL_RESULTS, mode="fixture")


def test_relabelled_fixture_cannot_self_attest_as_official_real_evidence(tmp_path):
    bundle = _bundle()
    bundle["mode"] = "real"
    bundle["runtime"] = {"name": "GigaAgent Production Runtime", "version": "2026.07"}
    bundle["model"] = {"name": "GigaChat Enterprise", "version": "2.5"}
    bundle["redaction_note"] = "Captured output sanitized before offline evaluation."
    for response in bundle["responses"]:
        response["raw_sanitized"] = {}
    path = _write_bundle(tmp_path, bundle, name="unverified-real.json")
    output = tmp_path / "forged-real-results.json"

    with pytest.raises(ValueError, match="real bundle scoring is forbidden"):
        runner.score_response_bundle(path, mode="real")

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--score-bundle",
            str(path),
            "--mode",
            "real",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode != 0
    assert "real bundle scoring is forbidden" in completed.stderr
    assert not output.exists()


def test_sanitized_bundle_rejects_secrets_and_full_prompt_fields(tmp_path):
    bundle = _bundle()
    bundle["responses"][0]["raw_sanitized"] = {
        "authorization": "Bea" + "rer synthetic-but-forbidden-value"
    }
    path = _write_bundle(tmp_path, bundle)

    with pytest.raises(ValueError, match="forbidden sensitive/prompt field"):
        runner._load_bundle(
            path,
            mode="fixture",
            corpus_digest=bundle["corpus_hash"],
            revisions=_recorded_revisions(bundle),
        )


def test_fixture_result_file_is_non_release_and_real_result_remains_not_run():
    fixture = json.loads(
        (REPOSITORY_ROOT / "evaluation" / "gigaagent" / "fixture-results.json").read_text(
            encoding="utf-8"
        )
    )
    real = json.loads(runner.REAL_RESULTS.read_text(encoding="utf-8"))

    assert fixture == runner.score_response_bundle(FIXTURE_BUNDLE, mode="fixture")
    assert fixture["mode"] == "fixture"
    assert fixture["release_evidence"] is False
    assert fixture["gate"]["release_passed"] is False
    assert real["mode"] == "real"
    assert real["status"] == "not_run"
    assert real["measurement_class"] == "unconfigured_real"
    assert real["cases_evaluated"] == 0
    assert real["runs"] == []
