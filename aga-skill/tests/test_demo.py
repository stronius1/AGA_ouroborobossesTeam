# -*- coding: utf-8 -*-
"""End-to-end Make demo contract in an isolated package copy."""
from __future__ import annotations

import shutil
import subprocess
import json
import hashlib
from pathlib import Path

import yaml


PKG_ROOT = Path(__file__).resolve().parents[1]


def _protected_source_snapshot(package: Path) -> dict[str, bytes]:
    paths = [
        package / "VERSION",
        package / "CHANGELOG.md",
        package / "precedents" / "cases" / "0001-dmz-file-exchange.md",
        *(package / "rules").glob("*.yaml"),
    ]
    return {
        path.relative_to(package).as_posix(): path.read_bytes()
        for path in sorted(paths)
    }


def _copy_package(tmp_path: Path) -> Path:
    destination = tmp_path / "aga-skill"
    shutil.copytree(
        PKG_ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".venv", "build", "__pycache__", ".pytest_cache", "*.pyc"
        ),
    )
    return destination


def _configure_synthetic_deprecation(
    package: Path, *, incomplete_claim: bool = False
) -> tuple[list[str], list[str]]:
    """Install an obsolete synthetic rule and derive claims from real baseline evidence."""

    rule_id = "PRIN-099"
    principles_path = package / "rules" / "principles.yaml"
    principles = yaml.safe_load(principles_path.read_text(encoding="utf-8"))
    principles["rules"].append(
        {
            "id": rule_id,
            "title": "Synthetic obsolete file detector",
            "statement": "Synthetic detector used only by the deprecation E2E test.",
            "rationale": "The locked corpus classifies every firing as a false positive.",
            "severity": "major",
            "scope": ["integration_flow"],
            "check_type": "deterministic",
            "detect": {"field": "pattern", "banned": ["file"]},
            "source_ref": "synthetic/policy-v1#/obsolete-file-detector",
            "exceptions": [],
            "provenance": {"origin": "seed", "added_in": "1.0.0"},
            "status": "active",
        }
    )
    principles_path.write_text(
        yaml.safe_dump(principles, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )

    baseline_path = package / "synthetic-deprecation-baseline.json"
    evaluated = subprocess.run(
        [
            "python3",
            "evolver/fitness.py",
            "--rules",
            "rules",
            "--out",
            str(baseline_path),
        ],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert evaluated.returncode == 0, evaluated.stdout + evaluated.stderr
    metrics = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline_path.unlink()
    positive = sorted(
        row["pr"]
        for row in metrics["per_pr"]
        if any(
            finding["rule_id"] == rule_id for finding in row["fp_findings"]
        )
    )
    negative = metrics["deterministic_coverage"]["negative_cases"][rule_id]
    assert len(positive) >= 2
    assert negative

    precedent_path = package / "precedents" / "cases" / "0001-dmz-file-exchange.md"
    text = precedent_path.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    metadata["rule_id"] = rule_id
    metadata.pop("proposed_mutations", None)
    metadata["proposed_mutation"] = {
        "type": "deprecate_rule",
        "provenance": "precedent:0001",
        "rule_id": rule_id,
        "reason": "Locked synthetic policy no longer has a valid finding",
        "evidence": "synthetic/policy-v2",
        "coverage": {
            "positive_cases": positive[:1] if incomplete_claim else positive,
            "negative_cases": negative,
        },
    }
    precedent_path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---"
        + body,
        encoding="utf-8",
    )
    return positive, negative


def test_make_demo_runs_full_contract(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    completed = subprocess.run(
        ["make", "demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    for marker in (
        "SEAF-004",
        "GATE PASS",
        "precision",
        "weighted cost",
        "Merge — только человеком",
    ):
        assert marker in output
    for relative in (
        "evolution-pr.md",
        "rules.diff",
        "metrics-baseline.json",
        "metrics-candidate.json",
        "candidate-manifest.json",
    ):
        assert (package / "build" / relative).is_file()
    events = [
        json.loads(line)
        for line in (package / "logs" / "evolution.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event = events[-1]
    assert event["result"] == "passed"
    assert event["gate_checks"]
    assert event["generated_artifacts"]["rules.diff"]
    assert event["publisher_result"]["status"] == "dry_run"


def test_make_demo_does_not_mask_unexpected_review_exit(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    runner = package / "scripts" / "run_review.py"
    runner.write_text("raise SystemExit(3)\n", encoding="utf-8")
    completed = subprocess.run(
        ["make", "demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode != 0
    assert "expected blocker escalation exit 1, got 3" in (
        completed.stdout + completed.stderr
    )


def test_candidate_command_independently_validates_without_writing_sources(
    tmp_path: Path,
) -> None:
    package = _copy_package(tmp_path)
    demo = subprocess.run(
        ["make", "demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert demo.returncode == 0, demo.stdout + demo.stderr
    before = _protected_source_snapshot(package)
    applied = subprocess.run(
        ["python3", "scripts/apply_candidate.py", "--actor", "Test Architect"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert '"status": "validated_candidate_bundle"' in applied.stdout
    assert '"apply_supported": false' in applied.stdout
    assert '"external_apply_required": true' in applied.stdout
    assert _protected_source_snapshot(package) == before


def test_human_apply_rejects_stale_candidate_after_base_rule_drift(
    tmp_path: Path,
) -> None:
    package = _copy_package(tmp_path)
    demo = subprocess.run(
        ["make", "demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert demo.returncode == 0, demo.stdout + demo.stderr
    source = package / "rules" / "principles.yaml"
    source.write_bytes(source.read_bytes() + b"\n# concurrent human change\n")
    applied = subprocess.run(
        ["python3", "scripts/apply_candidate.py", "--actor", "Test Architect"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert applied.returncode == 2
    assert "base rule drift detected" in applied.stderr


def test_removed_confirmation_option_cannot_change_sources(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    demo = subprocess.run(
        ["make", "demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert demo.returncode == 0, demo.stdout + demo.stderr
    before = _protected_source_snapshot(package)
    attempted = subprocess.run(
        [
            "python3",
            "scripts/apply_candidate.py",
            "--actor",
            "Test Architect",
            "--confirm",
            "APPLY_PASSED_CANDIDATE",
        ],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert attempted.returncode == 2
    assert "unrecognized arguments: --confirm" in attempted.stderr
    assert _protected_source_snapshot(package) == before


def test_self_signed_forged_metrics_are_rejected(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    demo = subprocess.run(
        ["make", "demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert demo.returncode == 0, demo.stdout + demo.stderr
    before = _protected_source_snapshot(package)
    metrics_path = package / "build" / "metrics-baseline.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["precision"] = 0.1234
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path = package / "build" / "candidate-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["metrics-baseline.json"] = hashlib.sha256(
        metrics_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    attempted = subprocess.run(
        ["python3", "scripts/apply_candidate.py", "--actor", "Test Architect"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert attempted.returncode == 2
    assert (
        "stored baseline metrics differ from independent evaluation" in attempted.stderr
    )
    assert _protected_source_snapshot(package) == before


def test_candidate_validation_rejects_symlinked_artifact(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    demo = subprocess.run(
        ["make", "demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert demo.returncode == 0, demo.stdout + demo.stderr
    before = _protected_source_snapshot(package)
    linked_build = package / "linked-build"
    linked_build.symlink_to(package / "build", target_is_directory=True)
    linked_attempt = subprocess.run(
        [
            "python3",
            "scripts/apply_candidate.py",
            "--actor",
            "Test Architect",
            "--build",
            str(linked_build),
        ],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert linked_attempt.returncode == 2
    assert "directory contains an unavailable or linked component" in linked_attempt.stderr
    artifact = package / "build" / "rules.diff"
    outside = tmp_path / "same-rules.diff"
    outside.write_bytes(artifact.read_bytes())
    artifact.unlink()
    artifact.symlink_to(outside)
    attempted = subprocess.run(
        ["python3", "scripts/apply_candidate.py", "--actor", "Test Architect"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert attempted.returncode == 2
    assert "cannot safely open artifact rules.diff" in attempted.stderr
    assert _protected_source_snapshot(package) == before


def test_evolution_rejects_seaf_registry_drift_before_metrics(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    seaf = package / "fixtures" / "seaf.yaml"
    seaf.write_bytes(seaf.read_bytes() + b"\n# unapproved registry drift\n")

    attempted = subprocess.run(
        ["python3", "scripts/run_evolution.py", "--demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert attempted.returncode == 2
    assert "SEAF registry differs from the approved pre-cycle snapshot" in (
        attempted.stdout + attempted.stderr
    )
    assert not (package / "build" / "metrics-baseline.json").exists()


def test_deprecate_rule_e2e_passes_with_exact_locked_coverage_and_validator(
    tmp_path: Path,
) -> None:
    package = _copy_package(tmp_path)
    positive, negative = _configure_synthetic_deprecation(package)

    evolved = subprocess.run(
        ["python3", "scripts/run_evolution.py", "--demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert evolved.returncode == 0, evolved.stdout + evolved.stderr
    attempts = json.loads(
        (package / "build" / "evolution-attempts.json").read_text(encoding="utf-8")
    )
    checks = {item["id"]: item for item in attempts[-1]["gate_checks"]}
    assert attempts[-1]["result"] == "passed"
    assert checks["changed_rule_coverage"]["passed"] is True
    assert checks["changed_rule_coverage"]["after"] == {
        "positive": positive,
        "negative": negative,
    }
    assert checks["deprecation_no_expected_findings"]["passed"] is True
    assert checks["deprecation_target_disabled"]["passed"] is True
    assert checks["deprecation_non_target_stability"]["passed"] is True

    validated = subprocess.run(
        ["python3", "scripts/apply_candidate.py", "--actor", "Test Architect"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert '"status": "validated_candidate_bundle"' in validated.stdout


def test_deprecate_rule_e2e_rejects_incomplete_self_declared_coverage(
    tmp_path: Path,
) -> None:
    package = _copy_package(tmp_path)
    positive, _ = _configure_synthetic_deprecation(
        package, incomplete_claim=True
    )
    assert len(positive) > 1

    evolved = subprocess.run(
        ["python3", "scripts/run_evolution.py", "--demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert evolved.returncode == 1, evolved.stdout + evolved.stderr
    attempts = json.loads(
        (package / "build" / "evolution-attempts.json").read_text(encoding="utf-8")
    )
    checks = {item["id"]: item for item in attempts[-1]["gate_checks"]}
    assert attempts[-1]["result"] == "failed_gate"
    assert checks["deprecation_declared_coverage"]["passed"] is False
    assert checks["changed_rule_coverage"]["passed"] is False


def test_circuit_breaker_logs_every_available_attempt(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    precedent_path = package / "precedents" / "cases" / "0001-dmz-file-exchange.md"
    text = precedent_path.read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    invalid = {
        "type": "add_exception",
        "provenance": "precedent:0001",
        "rule_id": "PRIN-002",
        "exception": {"when": {}},
    }
    metadata["proposed_mutations"] = [invalid, invalid, invalid]
    precedent_path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---"
        + body,
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["python3", "scripts/run_evolution.py", "--demo", "--max-attempts", "3"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    attempts = json.loads((package / "build" / "evolution-attempts.json").read_text())
    assert len(attempts) == 3
    assert [item["attempt"] for item in attempts] == [1, 2, 3]
    assert all(item["result"] == "validation_error" for item in attempts)
