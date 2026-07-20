from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


DEV_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = DEV_ROOT.parents[1]
AGA_SKILL_ROOT = REPOSITORY_ROOT / "aga-skill"
for root in (DEV_ROOT, REPOSITORY_ROOT, AGA_SKILL_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import corpus_tool  # noqa: E402
import run_paid_evaluation as paid  # noqa: E402
import runner  # noqa: E402
from tools.review_service import ReviewService  # noqa: E402


def _perfect_response(case: dict, revision: dict) -> dict:
    findings = [
        {
            "rule_id": expected["rule_id"],
            "severity": expected["severity"],
            "confidence": 1.0,
            "artifact": expected["artifact"],
            "location": expected["location"],
            "evidence": f"Grounded synthetic evidence: {expected['evidence_contains']}",
            "source_ref": runner.SOURCE_REFS[expected["rule_id"]],
            "suggested_fix": "Use the governed synthetic alternative.",
        }
        for expected in case["expected"]["findings"]
    ]
    return {
        "case_id": case["id"],
        "base_revision": revision["base"],
        "head_revision": revision["head"],
        "latency_ms": 1.0,
        "raw_sanitized": {"fixture": True},
        "normalized": {
            "status": case["expected"]["status"],
            "verdict": case["expected"]["verdict"],
            "findings": findings,
        },
    }


def _fixture_bundle(tmp_path: Path, case_id: str) -> tuple[Path, dict]:
    cases = {case["id"]: case for case in corpus_tool.load_cases(DEV_ROOT)}
    revision = corpus_tool.materialize_case(case_id, tmp_path / "fixture-repository", root=DEV_ROOT)
    lock = corpus_tool.verify_lock(DEV_ROOT)
    bundle = {
        "schema": runner.FIXTURE_SCHEMA,
        "mode": "fixture",
        "captured_at": "2026-07-19T12:00:00Z",
        "corpus_sha256": lock["corpus_sha256"],
        "ground_truth_sha256": lock["ground_truth_sha256"],
        "validator_sha256": lock["validator_sha256"],
        "scorer_sha256": lock["scorer_sha256"],
        "responses": [_perfect_response(cases[case_id], revision)],
    }
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return path, bundle


def test_lock_covers_corpus_ground_truth_validator_scorer_and_series_policy() -> None:
    cases = corpus_tool.load_cases(DEV_ROOT)
    lock = corpus_tool.verify_lock(DEV_ROOT)
    report = corpus_tool.coverage_report(cases)

    assert len(cases) == 48
    for rule_id in corpus_tool.RULES:
        assert report["rules"][rule_id]["positive"] >= 4
        assert report["rules"][rule_id]["negative"] >= 4
    assert lock["corpus_sha256"] == corpus_tool.corpus_hash(DEV_ROOT)
    assert lock["ground_truth_sha256"] == corpus_tool.ground_truth_hash(cases)
    assert lock["validator_sha256"] == corpus_tool.file_sha256(DEV_ROOT / "corpus_tool.py")
    assert lock["scorer_sha256"] == corpus_tool.file_sha256(DEV_ROOT / "runner.py")
    assert lock["paid_runner_sha256"] == corpus_tool.file_sha256(DEV_ROOT / "run_paid_evaluation.py")
    assert lock["series_freeze"]["state"] == "pre_measurement"
    assert set(lock["series_freeze"]["measurement_identity"].values()) == {None}
    assert set(lock["series_freeze"]["mutation_policy"].values()) == {"forbidden_after_start"}


def test_strict_expected_verdict_pointer_and_evidence_binding_for_every_finding() -> None:
    cases = corpus_tool.load_cases(DEV_ROOT)
    for case in cases:
        expected = case["expected"]
        if expected["findings"]:
            assert expected["verdict"] == "request_changes_escalate"
        documents = corpus_tool.native_state(case, "head")
        for finding in expected["findings"]:
            assert finding["location"].startswith("/")
            document = corpus_tool._binding_document(
                finding["artifact"], documents[finding["artifact"]]
            )
            value = corpus_tool.pointer_value(document, finding["location"])
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            assert finding["evidence_contains"].casefold() in text.casefold()


def test_each_positive_has_an_explicit_clean_metamorphic_negative_control() -> None:
    cases = corpus_tool.load_cases(DEV_ROOT)
    by_id = {case["id"]: case for case in cases}
    for case in cases:
        positives = {rule for rule, value in case["coverage"].items() if value == "positive"}
        assert set(case.get("dangerous_controls", {})) == positives
        for rule_id, control_id in case.get("dangerous_controls", {}).items():
            control = by_id[control_id]
            assert control["coverage"][rule_id] == "negative"
            assert "metamorphic-control" in control["features"]
            assert control["expected"]["verdict"] == "approve"
            assert corpus_tool.CONTROL_REMOVAL_FEATURES[rule_id].intersection(
                control["features"]
            )
            counterpart = case["metamorphic"]["counterpart"]
            if control_id == counterpart:
                assert case["metamorphic"]["relation"] == "predicate_flip"
            else:
                assert case["metamorphic"]["relation"] in corpus_tool.SAME_EXPECTED_RELATIONS
                assert by_id[counterpart]["coverage"][rule_id] == "positive"


def test_prin006_semantic_contract_is_distinct_from_structural_seaf004() -> None:
    cases = corpus_tool.load_cases(DEV_ROOT)
    structural = next(case for case in cases if "structural-seaf004" in case["features"])
    assert structural["coverage"]["PRIN-006"] == "not_targeted"
    assert [item["rule_id"] for item in structural["expected"]["findings"]] == ["SEAF-004"]
    for case in cases:
        if case["coverage"]["PRIN-006"] == "positive":
            finding = next(item for item in case["expected"]["findings"] if item["rule_id"] == "PRIN-006")
            assert not finding["location"].startswith("/seaf.app.integrations/")
    compounds = [
        case for case in cases
        if case["coverage"]["PRIN-005"] == "positive"
        and case["coverage"]["PRIN-006"] == "positive"
    ]
    assert len(compounds) == 1
    assert compounds[0]["dangerous_controls"]["PRIN-005"] == compounds[0]["dangerous_controls"]["PRIN-006"]


def test_materializer_creates_deterministic_clean_git_and_seaf_native_repositories(tmp_path: Path) -> None:
    first = corpus_tool.materialize_case("dv2-001-reuse-duplicate", tmp_path / "first", root=DEV_ROOT)
    second = corpus_tool.materialize_case("dv2-001-reuse-duplicate", tmp_path / "second", root=DEV_ROOT)

    assert first["base"] == second["base"]
    assert first["head"] == second["head"]
    assert first["sha256"] == second["sha256"]
    assert len(first["base"]) == len(first["head"]) == 40
    assert first["base"] != first["head"]
    assert first["base_entities"]["status"] == "ready"
    assert first["head_entities"]["systems"] == 2
    assert (tmp_path / "first/dochub.yaml").is_file()
    assert (tmp_path / "first/workspace/aga-extension.yaml").is_file()
    assert not (tmp_path / "first/expected.json").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path / "first",
        capture_output=True, text=True, check=True,
    )
    assert status.stdout == ""


def test_all_48_cases_materialize_as_git_repositories(tmp_path: Path) -> None:
    result = corpus_tool.materialize_all(tmp_path / "all", root=DEV_ROOT)
    assert result["case_count"] == 48
    index = json.loads((tmp_path / "all/index.json").read_text(encoding="utf-8"))
    assert len(index["cases"]) == 48
    for item in index["cases"]:
        repository = tmp_path / "all" / item["id"]
        assert (repository / ".git").is_dir()
        assert (repository / "dochub.yaml").is_file()
        assert not (repository / "expected.json").exists()


def test_trusted_aga_preparation_observes_seaf004_and_semantic_prin006_separately(tmp_path: Path) -> None:
    structural = corpus_tool.materialize_case(
        "dv2-029-dependency-direction", tmp_path / "structural", root=DEV_ROOT
    )
    semantic = corpus_tool.materialize_case(
        "dv2-021-critical-eliminate", tmp_path / "semantic", root=DEV_ROOT
    )
    for name, revision in (("structural", structural), ("semantic", semantic)):
        service = ReviewService(
            repositories={
                name: {
                    "repository": Path(revision["repository"]),
                    "manifest_path": "dochub.yaml",
                    "dependency_mode": "fixture",
                }
            },
            digest_secret="development-v2-offline-test",
        )
        try:
            prepared = service.prepare_review(
                repository_id=name,
                base=revision["base"],
                head=revision["head"],
                review_id=f"{name}-review",
            )
        finally:
            service.close()
        assert prepared["status"] == "ready"
        deterministic = [item["rule_id"] for item in prepared["deterministic_findings"]]
        if name == "structural":
            assert deterministic == ["SEAF-004"]
            assert any(item["entity_id"] == "syn.monitor_query" for item in prepared["artifacts"])
        else:
            assert "SEAF-004" not in deterministic
            artifact = next(
                item for item in prepared["artifacts"]
                if item["entity_id"] == "syn.dv2-021-critical-eliminate.change"
            )
            assert artifact["kind"] == "system_passport"


def test_actual_review_service_enforces_every_incomplete_context_pair(tmp_path: Path) -> None:
    pairs = (
        (
            "dv2-041-missing-target",
            "dv2-042-resolved-target",
            "unresolved_entity_references",
            "syn.catalog.unresolved",
        ),
        (
            "dv2-043-missing-context",
            "dv2-044-resolved-context",
            "unresolved_entity_references",
            "ADR-SYN-404",
        ),
        (
            "dv2-045-missing-criticality",
            "dv2-046-resolved-criticality",
            "extension_field_missing",
            None,
        ),
        (
            "dv2-047-missing-status",
            "dv2-048-resolved-status",
            "extension_field_missing",
            None,
        ),
    )
    for incomplete_id, control_id, error_code, unresolved_id in pairs:
        prepared_by_id: dict[str, dict] = {}
        for case_id in (incomplete_id, control_id):
            revision = corpus_tool.materialize_case(
                case_id, tmp_path / case_id, root=DEV_ROOT
            )
            service = ReviewService(
                repositories={
                    case_id: {
                        "repository": Path(revision["repository"]),
                        "manifest_path": "dochub.yaml",
                        "dependency_mode": "fixture",
                    }
                },
                digest_secret="development-v2-incomplete-contract-test",
            )
            try:
                prepared_by_id[case_id] = service.prepare_review(
                    repository_id=case_id,
                    base=revision["base"],
                    head=revision["head"],
                    review_id=f"{case_id}-review",
                )
            finally:
                service.close()

        incomplete = prepared_by_id[incomplete_id]
        assert incomplete["status"] == "incomplete"
        assert incomplete["incomplete"] is True
        if incomplete_id == "dv2-041-missing-target":
            assert [
                item["rule_id"] for item in incomplete["deterministic_findings"]
            ] == ["SEAF-001"]
        assert error_code in {item["code"] for item in incomplete["analysis_errors"]}
        if unresolved_id is not None:
            assert unresolved_id in incomplete["referenced_entity_ids"]
            assert unresolved_id in incomplete["unresolved_reference_ids"]

        control = prepared_by_id[control_id]
        assert control["status"] == "ready"
        assert control["incomplete"] is False
        assert control["analysis_errors"] == []
        assert control["unresolved_reference_ids"] == []


def test_paid_case_runner_projects_all_prepare_incomplete_cases_without_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_ouroboros_live_review as live  # noqa: PLC0415

    def forbidden_preflight() -> object:
        raise AssertionError("prepare-incomplete path must not schedule a model task")

    monkeypatch.setattr(live.e2e, "_default_preflight", forbidden_preflight)
    cases = {case["id"]: case for case in corpus_tool.load_cases(DEV_ROOT)}
    for case_id, expected_error in (
        ("dv2-041-missing-target", "unresolved_entity_references"),
        ("dv2-043-missing-context", "unresolved_entity_references"),
        ("dv2-045-missing-criticality", "extension_field_missing"),
        ("dv2-047-missing-status", "extension_field_missing"),
    ):
        revision = corpus_tool.materialize_case(
            case_id, tmp_path / f"repository-{case_id}", root=DEV_ROOT
        )
        result = paid._default_case_runner(
            repository=Path(revision["repository"]),
            repository_id=case_id,
            base=revision["base"],
            head=revision["head"],
            idempotency_key=f"series-a:1:capture-a:{case_id}",
            timeout_seconds=900.0,
            state_root=tmp_path / f"state-{case_id}",
        )
        assert result["status"] == "incomplete"
        assert result["reused"] is False
        assert result["final"]["status"] == "incomplete"
        assert result["final"]["verdict"] == "incomplete"
        expected_auxiliary = cases[case_id]["expected"]["auxiliary_findings"]
        assert [item["rule_id"] for item in result["final"]["findings"]] == [
            item["rule_id"] for item in expected_auxiliary
        ]
        assert result["final"]["human_review_required"] is True
        assert result["execution"] == {
            "kind": "trusted_host_prepare_incomplete",
            "model_task_scheduled": False,
        }
        assert result["receipts"] is None
        assert result["host_attestation"]["kind"] == "trusted_host_prepare_attestation"
        assert result["host_attestation"]["mcp_tool_invoked"] is False
        assert expected_error in result["host_attestation"]["analysis_error_codes"]
        assert expected_error in {
            item["code"] for item in result["final"]["analysis_errors"]
        }
        assert result["host_attestation"]["auxiliary_deterministic_findings"] == result[
            "final"
        ]["findings"]
        assert result["model_usage"] == {
            "provider": "openrouter",
            "model": "deepseek/deepseek-v4-pro",
            "call_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "known_cost_usd": 0.0,
            "cost_complete": True,
            "unresolved_upper_bound_usd": 0.0,
            "unknown_unmetered": 0,
        }
        assert paid._project_final(
            result["final"],
            auxiliary_rule_ids=frozenset(
                item["rule_id"] for item in expected_auxiliary
            ),
        ) == {
            "status": "incomplete", "verdict": "incomplete", "findings": []
        }
        paid._validate_case_execution(
            result,
            case=cases[case_id],
            identity={"provider_id": "openrouter", "model_id": "deepseek/deepseek-v4-pro"},
        )


def test_paid_boundary_covers_all_48_with_exact_host_and_model_execution_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_ouroboros_live_review as live  # noqa: PLC0415

    case_list = corpus_tool.load_cases(DEV_ROOT)
    cases = {case["id"]: case for case in case_list}
    identity = corpus_tool.active_measurement_identity(DEV_ROOT, cases=case_list)
    trusted_lock = corpus_tool.build_lock(DEV_ROOT)
    key = b"development-v2-boundary-regression-key"
    trusted_lock["independent_human_review"] = {
        "required": True,
        "status": "accepted",
        "reviewer": "synthetic-boundary-regression",
        "reviewed_at": "2026-07-20T12:00:00Z",
    }
    trusted_lock["series_freeze"].update(
        {
            "state": "frozen",
            "series_id": "dv2-boundary-test-series",
            "frozen_at": "2026-07-20T12:00:00Z",
            "measurement_identity": identity,
            "capture_attestation": {
                "scheme": "hmac-sha256",
                "key_id": "dv2-boundary-test-key",
                "key_sha256": hashlib.sha256(key).hexdigest(),
            },
        }
    )

    resolved_tmp = tmp_path.resolve()
    output_root = resolved_tmp / "captures"
    state_root = resolved_tmp / "state"
    monkeypatch.setattr(paid, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(paid, "DEFAULT_STATE_ROOT", state_root)
    monkeypatch.setattr(
        corpus_tool,
        "verify_lock",
        lambda *_args, **_kwargs: deepcopy(trusted_lock),
    )

    def forbidden_preflight() -> object:
        raise AssertionError("prepare-incomplete path must not schedule a model task")

    monkeypatch.setattr(live.e2e, "_default_preflight", forbidden_preflight)
    observed: dict[str, dict] = {}
    verified_prepare: dict[str, dict] = {}

    def hybrid_case_runner(**arguments: object) -> dict:
        case_id = str(arguments["repository_id"])
        case = cases[case_id]
        if case["expected"]["status"] == "incomplete":
            result = dict(paid._default_case_runner(**arguments))
            verified_prepare[case_id] = {
                "status": "incomplete",
                "analysis_error_codes": result["host_attestation"][
                    "prepare_analysis_error_codes"
                ],
                "deterministic_finding_rule_ids": result["host_attestation"][
                    "deterministic_finding_rule_ids"
                ],
            }
        else:
            binding = live.bind_repository(
                Path(arguments["repository"]),
                case_id,
                str(arguments["base"]),
                str(arguments["head"]),
            )
            service = live._review_service(binding)
            try:
                prepared = service.prepare_review(
                    repository_id=case_id,
                    base=str(arguments["base"]),
                    head=str(arguments["head"]),
                    review_id=f"{case_id}-verified-boundary-review",
                    entity_ids=[],
                )
            finally:
                service.close()
            verified_prepare[case_id] = {
                "status": prepared["status"],
                "analysis_error_codes": [
                    item["code"] for item in prepared["analysis_errors"]
                ],
                "deterministic_finding_rule_ids": [
                    item["rule_id"] for item in prepared["deterministic_findings"]
                ],
            }
            findings = [
                {
                    "rule_id": expected["rule_id"],
                    "severity": expected["severity"],
                    "confidence": 1.0,
                    "artifact": expected["artifact"],
                    "location": expected["location"],
                    "evidence": (
                        "Grounded synthetic boundary evidence: "
                        f"{expected['evidence_contains']}"
                    ),
                    "source_ref": runner.SOURCE_REFS[expected["rule_id"]],
                    "suggested_fix": "Use the governed synthetic alternative.",
                }
                for expected in case["expected"]["findings"]
            ]
            review_hash = hashlib.sha256(
                str(arguments["idempotency_key"]).encode("utf-8")
            ).hexdigest()
            result = {
                "repository_id": case_id,
                "base": arguments["base"],
                "head": arguments["head"],
                "status": "completed",
                "reused": False,
                "runtime": {
                    "name": identity["runtime_id"],
                    "version": identity["runtime_version"],
                    "source_commit": identity["runtime_source_commit"],
                },
                "provider": identity["provider_id"],
                "model": identity["model_id"],
                "task_id": f"synthetic-model-{case_id}",
                "review_id_sha256": review_hash,
                "receipts": {
                    "review_id_sha256": review_hash,
                    "tool_names": ["aga_prepare_review", "aga_finalize_review"],
                    "final_digest_binding": "none",
                    "prepare": {
                        "args_sha256": hashlib.sha256(
                            f"{case_id}:prepare-args".encode("utf-8")
                        ).hexdigest(),
                        "output_sha256": hashlib.sha256(
                            f"{case_id}:prepare-output".encode("utf-8")
                        ).hexdigest(),
                        "status": "ready",
                    },
                    "finalize": {
                        "args_sha256": hashlib.sha256(
                            f"{case_id}:finalize-args".encode("utf-8")
                        ).hexdigest(),
                        "output_sha256": hashlib.sha256(
                            f"{case_id}:finalize-output".encode("utf-8")
                        ).hexdigest(),
                        "status": "completed",
                    },
                },
                "host_attestation": None,
                "execution": {
                    "kind": "ouroboros_model_review",
                    "model_task_scheduled": True,
                },
                "model_usage": {
                    "provider": identity["provider_id"],
                    "model": identity["model_id"],
                    "call_count": 1,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "known_cost_usd": 0.0,
                    "cost_complete": True,
                    "unresolved_upper_bound_usd": 0.0,
                    "unknown_unmetered": 0,
                },
                "final": {
                    "status": "completed",
                    "verdict": case["expected"]["verdict"],
                    "findings": findings,
                },
            }
        observed[case_id] = result
        return result

    key_path = resolved_tmp / "capture-attestation.key"
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    clock_values = iter(
        (
            datetime(2026, 7, 20, 12, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 20, 12, 0, 2, tzinfo=timezone.utc),
            datetime(2026, 7, 20, 12, 0, 3, tzinfo=timezone.utc),
        )
    )
    capture_id = "boundary-capture"
    output = (
        output_root
        / trusted_lock["series_freeze"]["series_id"]
        / f"repeat-01-{capture_id}.json"
    )
    scored = paid.run_paid_evaluation(
        confirmed=True,
        selection="development",
        repeat_ordinal=1,
        capture_id=capture_id,
        attestation_key_file=key_path,
        output=output,
        state_root=state_root,
        case_runner=hybrid_case_runner,
        now=lambda: next(clock_values),
    )

    host_ids = {
        case_id
        for case_id, result in observed.items()
        if result["execution"]["model_task_scheduled"] is False
    }
    expected_host_ids = {
        "dv2-041-missing-target",
        "dv2-043-missing-context",
        "dv2-045-missing-criticality",
        "dv2-047-missing-status",
    }
    assert len(observed) == 48
    assert len(verified_prepare) == 48
    assert host_ids == expected_host_ids
    assert sum(
        result["execution"]["model_task_scheduled"] is True
        for result in observed.values()
    ) == 44
    expected_prepare_errors = {
        "dv2-041-missing-target": ["unresolved_entity_references"],
        "dv2-043-missing-context": ["unresolved_entity_references"],
        "dv2-045-missing-criticality": ["extension_field_missing"],
        "dv2-047-missing-status": ["extension_field_missing"],
    }
    assert {
        case_id
        for case_id, prepared in verified_prepare.items()
        if prepared["status"] == "incomplete"
    } == expected_host_ids
    for case_id, prepared in verified_prepare.items():
        assert "dependency_gitlink_missing" not in prepared["analysis_error_codes"]
        assert prepared["analysis_error_codes"] == expected_prepare_errors.get(
            case_id, []
        )
        assert ("SEAF-001" in prepared["deterministic_finding_rule_ids"]) is (
            case_id == "dv2-041-missing-target"
        )
    for case_id, result in observed.items():
        if case_id in expected_host_ids:
            assert result["receipts"] is None
            assert result["model_usage"]["call_count"] == 0
            assert result["host_attestation"]["mcp_tool_invoked"] is False
        else:
            assert isinstance(result["receipts"], dict)
            assert result["model_usage"]["call_count"] >= 1
            assert result["host_attestation"] is None

    assert scored["overall"]["cases_evaluated"] == 48
    assert scored["overall"]["cases_passed"] == 48
    assert scored["gate"]["evaluation_passed"] is True
    persisted = json.loads(output.read_text(encoding="utf-8"))
    persisted_runs = {run["case_id"]: run for run in persisted["runs"]}
    assert len(persisted_runs) == 48
    assert {
        case_id
        for case_id, run in persisted_runs.items()
        if run["raw_sanitized_response"]["execution"]["model_task_scheduled"]
        is False
    } == expected_host_ids
    assert persisted_runs["dv2-041-missing-target"]["raw_sanitized_response"][
        "host_attestation"
    ]["deterministic_finding_rule_ids"] == ["SEAF-001"]


def test_offline_fixture_scorer_is_non_release_and_checks_pointer_binding(tmp_path: Path) -> None:
    path, bundle = _fixture_bundle(tmp_path, "dv2-001-reuse-duplicate")
    result = runner.score_fixture_bundle(path)
    assert result["status"] == "fixture_scored_non_release"
    assert result["release_evidence"] is False
    assert result["selection"] == {"kind": "smoke", "case_count": 1}
    assert result["runs"][0]["assessment"] == "PASS"

    bundle["responses"][0]["normalized"]["findings"][0]["location"] = "/components/missing/description"
    bad = tmp_path / "bad-fixture.json"
    bad.write_text(json.dumps(bundle), encoding="utf-8")
    failed = runner.score_fixture_bundle(bad)
    assert failed["runs"][0]["assessment"] == "FAIL"
    assert failed["overall"]["invalid_or_hallucinated_evidence_count"] == 1
    evidence_gate = next(
        check for check in failed["gate"]["checks"]
        if check["id"] == "invalid_or_hallucinated_evidence_count"
    )
    assert evidence_gate == {
        "id": "invalid_or_hallucinated_evidence_count",
        "actual": 1,
        "operator": "<=",
        "threshold": 0,
        "passed": False,
    }
    assert failed["gate"]["evaluation_passed"] is False


def test_development_gate_enforces_evidence_and_exact_case_accuracy_thresholds() -> None:
    passing_metrics = {
        "blocker_recall": 1.0,
        "unsafe_approve_count": 0,
        "invalid_or_hallucinated_evidence_count": 0,
        "schema_valid_rate": 1.0,
        "precision": 1.0,
        "recall": 1.0,
        "outcome_accuracy": 1.0,
        "exact_case_accuracy": 0.85,
    }
    passing = runner._gate(passing_metrics)
    exact_check = next(
        check for check in passing["checks"] if check["id"] == "exact_case_accuracy"
    )
    assert exact_check == {
        "id": "exact_case_accuracy",
        "actual": 0.85,
        "operator": ">=",
        "threshold": 0.85,
        "passed": True,
    }
    assert passing["evaluation_passed"] is True

    invalid_evidence_metrics = dict(
        passing_metrics, invalid_or_hallucinated_evidence_count=1
    )
    invalid_evidence = runner._gate(invalid_evidence_metrics)
    evidence_check = next(
        check for check in invalid_evidence["checks"]
        if check["id"] == "invalid_or_hallucinated_evidence_count"
    )
    assert evidence_check["passed"] is False
    assert invalid_evidence["evaluation_passed"] is False

    failing_metrics = dict(passing_metrics, exact_case_accuracy=0.849999)
    failing = runner._gate(failing_metrics)
    exact_check = next(
        check for check in failing["checks"] if check["id"] == "exact_case_accuracy"
    )
    assert exact_check["passed"] is False
    assert failing["evaluation_passed"] is False


def test_auxiliary_tampering_trips_zero_tolerance_evidence_gate() -> None:
    cases = corpus_tool.load_cases(DEV_ROOT)
    revision = {"base": "1" * 40, "head": "2" * 40}
    responses = {
        case["id"]: _perfect_response(case, revision)
        for case in cases
    }
    auxiliary_case = next(
        case for case in cases if case["id"] == "dv2-041-missing-target"
    )
    locked = auxiliary_case["expected"]["auxiliary_findings"][0]
    responses[auxiliary_case["id"]]["raw_sanitized"] = {
        "host_attestation": {
            "auxiliary_deterministic_findings": [
                {
                    "rule_id": locked["rule_id"],
                    "severity": locked["severity"],
                    "artifact": locked["artifact"],
                    "location": locked["location"],
                    "evidence": f"trusted evidence: {locked['evidence_contains']}",
                    "source_ref": "aga-skill/rules/seaf-checks.yaml#/rules/0",
                }
            ]
        }
    }

    def score(candidate: dict[str, dict]) -> tuple[dict, dict]:
        private_rows = [
            runner._score_case(case, candidate[case["id"]])[1]
            for case in cases
        ]
        metrics = runner._metrics(private_rows)
        return metrics, runner._gate(metrics)

    passing_metrics, passing_gate = score(responses)
    assert passing_metrics["cases_passed"] == 48
    assert passing_metrics["invalid_or_hallucinated_evidence_count"] == 0
    assert passing_gate["evaluation_passed"] is True

    for tamper in ("missing", "wrong"):
        altered = deepcopy(responses)
        host = altered[auxiliary_case["id"]]["raw_sanitized"]["host_attestation"]
        if tamper == "missing":
            host["auxiliary_deterministic_findings"] = []
        else:
            host["auxiliary_deterministic_findings"][0]["source_ref"] = (
                "aga-skill/rules/seaf-checks.yaml#/rules/999"
            )
        metrics, gate = score(altered)
        assert metrics["cases_passed"] == 47
        assert metrics["exact_case_accuracy"] == round(47 / 48, 6)
        assert metrics["invalid_or_hallucinated_evidence_count"] == 1
        evidence_check = next(
            check
            for check in gate["checks"]
            if check["id"] == "invalid_or_hallucinated_evidence_count"
        )
        assert evidence_check["passed"] is False
        assert gate["evaluation_passed"] is False


def test_trusted_rescore_rejects_execution_usage_and_receipt_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = corpus_tool.load_cases(DEV_ROOT)
    identity = corpus_tool.active_measurement_identity(DEV_ROOT, cases=cases)
    lock = corpus_tool.build_lock(DEV_ROOT)
    lock["series_freeze"].update(
        {
            "state": "frozen",
            "series_id": "trusted-rescore-test",
            "frozen_at": "2026-07-20T13:00:00Z",
            "measurement_identity": identity,
        }
    )
    monkeypatch.setattr(
        corpus_tool,
        "verify_lock",
        lambda *_args, **_kwargs: deepcopy(lock),
    )
    revision = {"base": "1" * 40, "head": "2" * 40}

    def fake_materialize(case_id: str, destination: Path, **_kwargs: object) -> dict:
        return {
            "case_id": case_id,
            "repository": str(destination),
            **revision,
        }

    monkeypatch.setattr(corpus_tool, "materialize_case", fake_materialize)

    responses: dict[str, dict] = {}
    for case in cases:
        case_id = case["id"]
        response = _perfect_response(case, revision)
        review_hash = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
        usage = {
            "provider": identity["provider_id"],
            "model": identity["model_id"],
            "call_count": 1,
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "known_cost_usd": 0.001,
            "cost_complete": True,
            "unresolved_upper_bound_usd": 0.0,
            "unknown_unmetered": 0,
        }
        if case["expected"]["status"] == "incomplete":
            expected_context = case["expected"]["unresolved_context"]
            prepare_codes = [
                "unresolved_entity_references"
                if item["kind"] in {"target", "context"}
                else "extension_field_missing"
                for item in expected_context
            ]
            auxiliary = [
                {
                    "rule_id": locked["rule_id"],
                    "severity": locked["severity"],
                    "artifact": locked["artifact"],
                    "location": locked["location"],
                    "evidence": f"trusted evidence: {locked['evidence_contains']}",
                    "source_ref": "aga-skill/rules/seaf-checks.yaml#/rules/0",
                }
                for locked in case["expected"]["auxiliary_findings"]
            ]
            references = [
                item["reference"]
                for item in expected_context
                if item["kind"] in {"target", "context"}
            ]
            usage.update(
                {
                    "call_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "known_cost_usd": 0.0,
                }
            )
            response["raw_sanitized"] = {
                "task_id": f"host-{case_id}",
                "review_id_sha256": review_hash,
                "receipts": None,
                "execution": {
                    "kind": "trusted_host_prepare_incomplete",
                    "model_task_scheduled": False,
                },
                "model_usage": usage,
                "host_attestation": {
                    "kind": "trusted_host_prepare_attestation",
                    "mcp_tool_invoked": False,
                    "review_id_sha256": review_hash,
                    "prepare_args_sha256": "a" * 64,
                    "prepare_output_sha256": "b" * 64,
                    "service_final_output_sha256": "c" * 64,
                    "projection_output_sha256": "d" * 64,
                    "prepare_analysis_error_codes": prepare_codes,
                    "analysis_error_codes": [*prepare_codes, "semantic_unavailable"],
                    "deterministic_finding_rule_ids": [
                        item["rule_id"] for item in auxiliary
                    ],
                    "auxiliary_deterministic_findings": auxiliary,
                    "referenced_entity_ids": references,
                    "unresolved_reference_ids": references,
                },
            }
        else:
            response["raw_sanitized"] = {
                "task_id": f"model-{case_id}",
                "review_id_sha256": review_hash,
                "receipts": {
                    "review_id_sha256": review_hash,
                    "tool_names": ["aga_prepare_review", "aga_finalize_review"],
                    "final_digest_binding": "none",
                    "prepare": {
                        "args_sha256": "a" * 64,
                        "output_sha256": "b" * 64,
                        "status": "ready",
                    },
                    "finalize": {
                        "args_sha256": "c" * 64,
                        "output_sha256": "d" * 64,
                        "status": "completed",
                    },
                },
                "host_attestation": None,
                "execution": {
                    "kind": "ouroboros_model_review",
                    "model_task_scheduled": True,
                },
                "model_usage": usage,
            }
        responses[case_id] = response

    def score(candidate: dict[str, dict]) -> dict:
        return runner.score_trusted_responses(
            list(candidate.values()),
            captured_at="2026-07-20T13:00:01Z",
            series_id="trusted-rescore-test",
            capture_id="trusted-rescore-capture",
            repeat_ordinal=1,
            measurement_identity=identity,
        )

    passing = score(responses)
    assert passing["overall"]["cases_passed"] == 48
    assert passing["overall"]["invalid_or_hallucinated_evidence_count"] == 0
    assert passing["gate"]["evaluation_passed"] is True
    assert all(run["trusted_execution_valid"] is True for run in passing["runs"])

    target_id = "dv2-001-reuse-duplicate"
    tampered: list[tuple[dict[str, dict], str]] = []
    wrong_execution = deepcopy(responses)
    wrong_execution[target_id]["raw_sanitized"]["execution"] = {
        "kind": "trusted_host_prepare_incomplete",
        "model_task_scheduled": False,
    }
    tampered.append((wrong_execution, target_id))
    wrong_usage = deepcopy(responses)
    wrong_usage[target_id]["raw_sanitized"]["model_usage"]["call_count"] = 0
    tampered.append((wrong_usage, target_id))
    wrong_receipt = deepcopy(responses)
    wrong_receipt[target_id]["raw_sanitized"]["receipts"][
        "review_id_sha256"
    ] = "f" * 64
    tampered.append((wrong_receipt, target_id))
    host_id = "dv2-041-missing-target"
    wrong_host_usage = deepcopy(responses)
    wrong_host_usage[host_id]["raw_sanitized"]["model_usage"][
        "prompt_tokens"
    ] = 1
    tampered.append((wrong_host_usage, host_id))

    for altered, failed_case_id in tampered:
        failed = score(altered)
        assert failed["overall"]["cases_passed"] == 47
        assert failed["overall"]["invalid_or_hallucinated_evidence_count"] == 1
        assert failed["gate"]["evaluation_passed"] is False
        failed_run = next(
            run for run in failed["runs"] if run["case_id"] == failed_case_id
        )
        assert failed_run["trusted_execution_valid"] is False
        assert failed_run["assessment"] == "FAIL"


def test_gate_policy_cannot_be_weakened_before_regenerating_lock(tmp_path: Path) -> None:
    copied = tmp_path / "development-v2"
    shutil.copytree(DEV_ROOT, copied)
    gate_path = copied / "gate.yaml"
    gate_path.write_text(
        gate_path.read_text(encoding="utf-8").replace(
            "exact_case_accuracy_min: 0.85", "exact_case_accuracy_min: 0.10"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exact_case_accuracy_min was weakened"):
        corpus_tool.load_cases(copied)


def test_measurement_bundle_hash_ignores_only_classified_generated_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "aga-skill/tools/runtime.py"
    source.parent.mkdir(parents=True)
    source.write_text("SOURCE = 1\n", encoding="utf-8")
    before = corpus_tool._source_tree_sha256(tmp_path, ["aga-skill"])

    build = tmp_path / "aga-skill/build/generated.json"
    build.parent.mkdir(parents=True)
    build.write_text("generated\n", encoding="utf-8")
    logs = tmp_path / "aga-skill/logs"
    logs.mkdir()
    (logs / "reviews.jsonl").write_text("runtime review\n", encoding="utf-8")
    (logs / "evolution.jsonl").write_text("runtime evolution\n", encoding="utf-8")
    assert corpus_tool._source_tree_sha256(tmp_path, ["aga-skill"]) == before

    source.write_text("SOURCE = 2\n", encoding="utf-8")
    assert corpus_tool._source_tree_sha256(tmp_path, ["aga-skill"]) != before


def test_five_capture_series_is_distinct_recomputed_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = corpus_tool.load_cases(DEV_ROOT)
    selection = corpus_tool.measurement_selection(cases)
    lock = corpus_tool.build_lock(DEV_ROOT)
    identity = corpus_tool.active_measurement_identity(DEV_ROOT, cases=cases)
    lock["series_freeze"].update(
        {
            "state": "frozen",
            "series_id": "series-test",
            "frozen_at": "2026-07-20T11:00:00Z",
            "measurement_identity": identity,
        }
    )
    documents: list[dict] = []
    for ordinal in range(1, 6):
        runs = []
        for case in cases:
            runs.append(
                {
                    "case_id": case["id"],
                    "base_revision": "1" * 40,
                    "head_revision": "2" * 40,
                    "latency_ms": float(ordinal),
                    "raw_sanitized_response": {
                        "task_id": f"task-{ordinal}-{case['id']}",
                        "model_usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 10,
                            "known_cost_usd": 0.001,
                            "cost_complete": True,
                            "unresolved_upper_bound_usd": 0.0,
                            "unknown_unmetered": 0,
                        },
                    },
                    "normalized_output": {
                        "status": case["expected"]["status"],
                        "verdict": case["expected"]["verdict"],
                        "findings": [],
                    },
                }
            )
        documents.append(
            {
                "schema": runner.RESULT_SCHEMA,
                "status": "trusted_development_scored_non_release",
                "measurement_class": "trusted_ouroboros_development",
                "release_evidence": False,
                "captured_at": f"2026-07-20T12:00:0{ordinal}Z",
                "corpus_hash": lock["corpus_sha256"],
                "ground_truth_hash": lock["ground_truth_sha256"],
                "validator_hash": lock["validator_sha256"],
                "scorer_hash": lock["scorer_sha256"],
                "series": {
                    "series_id": "series-test",
                    "capture_id": f"capture-{ordinal}",
                    "repeat_ordinal": ordinal,
                    "required_repeated_runs": 5,
                    "measurement_identity": identity,
                },
                "attempt": {
                    "marker_sha256": f"{ordinal:064x}",
                    "started_at": f"2026-07-20T11:00:0{ordinal}Z",
                    "cases_completed": 48,
                },
                "selection": {
                    "kind": "development",
                    "case_count": 48,
                    **selection,
                },
                "overall": {
                    "precision": 1.0,
                    "recall": 1.0,
                    "blocker_recall": 1.0,
                    "outcome_accuracy": 1.0,
                    "schema_valid_rate": 1.0,
                    "exact_case_accuracy": 1.0,
                    "unsafe_approve_count": 0,
                    "invalid_or_hallucinated_evidence_count": 0,
                    "fp": 0,
                    "fn": 0,
                },
                "gate": {"evaluation_passed": True},
                "runs": runs,
                "capture_set_sha256": runner._capture_set_hash(runs),
            }
        )

    summary = runner._summarize_series_documents(
        documents, lock=lock, max_p95_ms=100.0, max_cost_usd=0.10, rescore=False
    )
    assert summary["qualification_passed"] is True
    assert summary["distinct_capture_count"] == 5
    assert summary["checks"]["token_accounting_complete"] is True
    assert summary["approve_non_approve_flapping_case_ids"] == []
    assert summary["usage"]["prompt_tokens"] == 24_000
    assert summary["usage"]["completion_tokens"] == 2_400
    assert summary["usage"]["max_repeat_known_cost_usd"] == 0.048

    capped = runner._summarize_series_documents(
        documents, lock=lock, max_p95_ms=100.0, max_cost_usd=0.04, rescore=False
    )
    assert capped["qualification_passed"] is False
    assert capped["checks"]["cost_cap_passed"] is False

    slow_repeat = deepcopy(documents)
    for run in slow_repeat[0]["runs"][:3]:
        run["latency_ms"] = 1_000.0
    slow_repeat[0]["capture_set_sha256"] = runner._capture_set_hash(
        slow_repeat[0]["runs"]
    )
    slow = runner._summarize_series_documents(
        slow_repeat, lock=lock, max_p95_ms=100.0, max_cost_usd=0.10,
        rescore=False,
    )
    assert slow["latency"]["pooled_p95_ms"] < 100.0
    assert slow["latency"]["max_repeat_p95_ms"] > 100.0
    assert slow["checks"]["latency_p95_cap_passed"] is False
    assert slow["qualification_passed"] is False

    flapping = deepcopy(documents)
    flap_case_id = cases[0]["id"]
    flapping[0]["runs"][0]["normalized_output"]["verdict"] = "approve"
    flapping[0]["capture_set_sha256"] = runner._capture_set_hash(
        flapping[0]["runs"]
    )
    unstable = runner._summarize_series_documents(
        flapping, lock=lock, max_p95_ms=100.0, max_cost_usd=0.10,
        rescore=False,
    )
    assert unstable["checks"]["approve_non_approve_stability_passed"] is False
    assert unstable["approve_non_approve_flapping_case_ids"] == [flap_case_id]
    assert unstable["qualification_passed"] is False

    unknown_tokens = deepcopy(documents)
    del unknown_tokens[0]["runs"][0]["raw_sanitized_response"]["model_usage"][
        "prompt_tokens"
    ]
    unknown_tokens[0]["capture_set_sha256"] = runner._capture_set_hash(
        unknown_tokens[0]["runs"]
    )
    incomplete = runner._summarize_series_documents(
        unknown_tokens, lock=lock, max_p95_ms=100.0, max_cost_usd=0.10,
        rescore=False,
    )
    assert incomplete["qualification_passed"] is False
    assert incomplete["checks"]["token_accounting_complete"] is False

    duplicate = deepcopy(documents)
    duplicate[-1]["attempt"]["marker_sha256"] = duplicate[-2]["attempt"][
        "marker_sha256"
    ]
    with pytest.raises(ValueError, match="distinct IDs, attempt markers"):
        runner._summarize_series_documents(
            duplicate, lock=lock, max_p95_ms=100.0, max_cost_usd=0.10,
            rescore=False,
        )

    canonical = deepcopy(documents)

    def recompute(_responses: list[dict], *, series: dict, **_kwargs: object) -> dict:
        source = canonical[series["repeat_ordinal"] - 1]
        return {
            field: deepcopy(source[field])
            for field in ("overall", "gate", "runs", "capture_set_sha256")
        }

    monkeypatch.setattr(runner, "_score_responses", recompute)
    tampered = deepcopy(documents)
    tampered[0]["overall"]["precision"] = 0.25
    with pytest.raises(ValueError, match="differs from strict re-scoring"):
        runner._summarize_series_documents(
            tampered, lock=lock, max_p95_ms=100.0, max_cost_usd=0.10
        )


def test_series_file_trust_boundary_requires_external_key_and_valid_hmac(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = b"series-verifier-external-key-32bytes"
    key_file = tmp_path / "series.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    lock = corpus_tool.build_lock(DEV_ROOT)
    attestation = {
        "scheme": "hmac-sha256",
        "key_id": "series-key",
        "key_sha256": hashlib.sha256(key).hexdigest(),
    }
    lock["series_freeze"]["capture_attestation"] = attestation
    monkeypatch.setattr(corpus_tool, "verify_lock", lambda *_args, **_kwargs: lock)
    monkeypatch.setattr(
        runner,
        "_summarize_series_documents",
        lambda documents, **_kwargs: {"verified_documents": len(documents)},
    )
    paths = []
    for ordinal in range(1, 6):
        signed = paid._attest_capture(
            {"ordinal": ordinal}, key=key, attestation=attestation
        )
        path = tmp_path / f"capture-{ordinal}.json"
        path.write_text(json.dumps(signed), encoding="utf-8")
        paths.append(path)
    assert runner.verify_series_result_files(
        paths, max_p95_ms=100.0, max_cost_usd=1.0,
        attestation_key_file=key_file,
    ) == {"verified_documents": 5}

    tampered = json.loads(paths[0].read_text(encoding="utf-8"))
    tampered["ordinal"] = 99
    paths[0].write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="signature mismatch"):
        runner.verify_series_result_files(
            paths, max_p95_ms=100.0, max_cost_usd=1.0,
            attestation_key_file=key_file,
        )

    wrong_key = tmp_path / "wrong.key"
    wrong_key.write_bytes(b"wrong-series-key-material-32-bytes!")
    wrong_key.chmod(0o600)
    with pytest.raises(ValueError, match="does not match"):
        runner._series_attestation_key(wrong_key, attestation)

    key_file.chmod(0o644)
    with pytest.raises(ValueError, match="does not match"):
        runner._series_attestation_key(key_file, attestation)

    key_file.chmod(0o600)
    key_link = tmp_path / "series-link.key"
    key_link.symlink_to(key_file)
    with pytest.raises(ValueError, match="must not be a symlink"):
        runner._series_attestation_key(key_link, attestation)

    fake_root = tmp_path / "repository/evaluation/development-v2"
    fake_root.mkdir(parents=True)
    in_repository_key = tmp_path / "repository/inside.key"
    in_repository_key.write_bytes(key)
    in_repository_key.chmod(0o600)
    monkeypatch.setattr(runner, "ROOT", fake_root)
    with pytest.raises(ValueError, match="outside the repository"):
        runner._series_attestation_key(in_repository_key, attestation)


def test_file_scorer_rejects_relabelled_real_bundle(tmp_path: Path) -> None:
    path, bundle = _fixture_bundle(tmp_path, "dv2-002-reuse-control")
    del path
    bundle["mode"] = "real"
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(ValueError, match="only explicit fixture"):
        runner.score_fixture_bundle(forged)


def test_paid_runner_checks_confirmation_and_human_gate_before_case_runner() -> None:
    calls: list[dict] = []

    def forbidden(**arguments: object) -> dict:
        calls.append(dict(arguments))
        raise AssertionError("model-capable case runner must not be reached")

    with pytest.raises(paid.PaidEvaluationError, match="explicit_paid_confirmation_required"):
        paid.run_paid_evaluation(
            confirmed=False, selection="development", case_runner=forbidden
        )
    with pytest.raises(paid.PaidEvaluationError, match="independent_human_review_required"):
        paid.run_paid_evaluation(
            confirmed=True, selection="development", repeat_ordinal=1,
            capture_id="capture-a", case_runner=forbidden
        )
    with pytest.raises(paid.PaidEvaluationError, match="repeat_ordinal_1_to_5_required"):
        paid.run_paid_evaluation(
            confirmed=True, selection="development", repeat_ordinal=0,
            capture_id="capture-a", case_runner=forbidden
        )
    assert calls == []


def test_paid_runner_retains_failed_attempt_and_forbids_ordinal_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(paid.PaidEvaluationError, match="state_root_must_be_canonical"):
        paid._bounded_state_root(tmp_path / "unapproved-state")
    with pytest.raises(
        paid.PaidEvaluationError, match="capture_output_path_must_be_canonical"
    ):
        paid._output_path(
            REPOSITORY_ROOT / "scripts/forged-capture.json",
            series_id="series-attempt-test",
            repeat_ordinal=1,
            capture_id="capture-a",
        )

    key = b"development-v2-test-attestation-key"
    key_file = tmp_path / "attestation.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    identity = corpus_tool.active_measurement_identity(DEV_ROOT)
    lock = corpus_tool.build_lock(DEV_ROOT)
    lock["series_freeze"].update(
        {
            "state": "frozen",
            "series_id": "series-attempt-test",
            "frozen_at": "2026-07-20T12:00:00Z",
            "measurement_identity": identity,
            "capture_attestation": {
                "scheme": "hmac-sha256",
                "key_id": "test-key",
                "key_sha256": hashlib.sha256(key).hexdigest(),
            },
        }
    )
    state_root = tmp_path / "state"
    output_root = tmp_path / "captures"
    monkeypatch.setattr(paid, "DEFAULT_STATE_ROOT", state_root)
    monkeypatch.setattr(paid, "DEFAULT_OUTPUT_ROOT", output_root)
    monkeypatch.setattr(corpus_tool, "verify_lock", lambda *_args, **_kwargs: lock)
    monkeypatch.setattr(paid, "_active_runtime_identity", lambda _identity: None)
    calls: list[str] = []

    def failing_runner(**arguments: object) -> dict:
        calls.append(str(arguments["repository_id"]))
        raise RuntimeError("provider unavailable; must not enter retained evidence")

    times = iter(
        [
            datetime(2026, 7, 20, 12, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 20, 12, 0, 2, tzinfo=timezone.utc),
            datetime(2026, 7, 20, 12, 0, 3, tzinfo=timezone.utc),
        ]
    )
    with pytest.raises(paid.PaidEvaluationError, match="trusted_case_runner_failed"):
        paid.run_paid_evaluation(
            confirmed=True,
            selection="development",
            repeat_ordinal=1,
            capture_id="capture-a",
            attestation_key_file=key_file,
            state_root=state_root,
            case_runner=failing_runner,
            now=lambda: next(times),
        )

    attempt_root = state_root / "series-attempt-test/repeat-01"
    marker = json.loads((attempt_root / "attempt.json").read_text(encoding="utf-8"))
    terminal = json.loads((attempt_root / "terminal.json").read_text(encoding="utf-8"))
    assert marker["status"] == "started_non_release"
    assert terminal["status"] == "failed_non_release"
    assert terminal["code"] == "trusted_case_runner_failed"
    assert terminal["cases_completed"] == 0
    assert terminal["finished_at"] > marker["started_at"]
    assert "provider unavailable" not in json.dumps(terminal)

    with pytest.raises(paid.PaidEvaluationError, match="repeat_ordinal_already_attempted"):
        paid.run_paid_evaluation(
            confirmed=True,
            selection="development",
            repeat_ordinal=1,
            capture_id="capture-b",
            attestation_key_file=key_file,
            state_root=state_root,
            case_runner=failing_runner,
            now=lambda: next(times),
        )
    assert len(calls) == 1


def test_make_paid_target_is_blocked_before_profile_execution() -> None:
    completed = subprocess.run(
        [
            "make", "-s", "evaluate-ouroboros-development-v2",
            "DEVELOPMENT_V2_PAID_APPROVED=yes", "OUROBOROS_PROFILE_MANAGER=false",
            "DEVELOPMENT_V2_REPEAT_ORDINAL=1",
            "DEVELOPMENT_V2_CAPTURE_ID=capture-a",
            "DEVELOPMENT_V2_ATTESTATION_KEY_FILE=/tmp/not-read-before-human-gate",
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode != 0
    assert "independent human review is pending" in completed.stderr
    assert "false exec" not in completed.stderr


def test_human_review_and_series_freeze_are_both_measurement_blockers() -> None:
    lock = corpus_tool.verify_lock(DEV_ROOT)
    assert lock["independent_human_review"]["status"] == "pending"
    identity = corpus_tool.active_measurement_identity(DEV_ROOT)
    assert identity["model_id"] == "deepseek/deepseek-v4-pro"
    assert identity["selection_sha256"] == corpus_tool.measurement_selection(
        corpus_tool.load_cases(DEV_ROOT)
    )["selection_sha256"]
    assert all(corpus_tool.SHA256_RE.fullmatch(identity[field]) for field in (
        "prompt_sha256", "config_sha256", "live_runner_sha256",
        "reviewer_skill_sha256", "execution_bundle_sha256", "selection_sha256",
    ))
    with pytest.raises(ValueError, match="human review is pending"):
        corpus_tool.verify_lock(DEV_ROOT, require_measurement_ready=True)


def test_locked_scorer_code_tamper_fails_closed(tmp_path: Path) -> None:
    copied = tmp_path / "development-v2"
    shutil.copytree(DEV_ROOT, copied)
    scorer_path = copied / "runner.py"
    scorer_path.write_text(scorer_path.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="scorer_sha256 lock mismatch"):
        corpus_tool.verify_lock(copied)


def test_duplicate_yaml_key_and_path_traversal_fail_closed(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate"
    shutil.copytree(DEV_ROOT, duplicate)
    case_path = duplicate / "cases/dv2-001-reuse-duplicate.yaml"
    case_path.write_text(case_path.read_text(encoding="utf-8") + "split: development\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate YAML key"):
        corpus_tool.load_cases(duplicate)

    traversal = tmp_path / "traversal"
    shutil.copytree(DEV_ROOT, traversal)
    case_path = traversal / "cases/dv2-001-reuse-duplicate.yaml"
    case_path.write_text(
        case_path.read_text(encoding="utf-8").replace("proposals/loyalty.yaml", "../escape.yaml"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsafe path segment"):
        corpus_tool.load_cases(traversal)
