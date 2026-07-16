# -*- coding: utf-8 -*-
"""Offline contracts for the trusted one-case Ouroboros E2E runner."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for root in (REPOSITORY_ROOT, REPOSITORY_ROOT / "aga-skill"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from evaluation.gigaagent import runner as evaluator  # noqa: E402
from scripts import run_ouroboros_e2e as e2e  # noqa: E402
from tools.a2a import TaskResult, TaskStatus  # noqa: E402


REVIEW_ID = "aga-test-review"
TASK_ID = "ouroboros-task-1"
REVIEW_DIGEST = "rvw_" + "c" * 64
TASK_DIGEST = "tsk_" + "d" * 64


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _case(case_id: str) -> Mapping[str, Any]:
    paths = evaluator.corpus_files()
    evaluator.verify_lock(paths)
    return next(
        case for case in evaluator._cases_from_paths(paths) if case["id"] == case_id
    )


def _finding(expected: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": expected["rule_id"],
        "severity": expected["severity"],
        "confidence": 0.95,
        "entity_id": "AS.SYNTHETIC",
        "artifact": expected["artifact"],
        "location": expected["location"],
        "evidence": f"Synthetic evidence: {expected['evidence_contains']}",
        "evidence_refs": ["evd_" + "e" * 64],
        "source_ref": evaluator.RULE_SOURCE_REFS[expected["rule_id"]],
        "suggested_fix": "Use the synthetic-public governed alternative.",
        "origin": "semantic",
        "base_revision": payload["base"],
        "head_revision": payload["head"],
        "source_provenance": {
            "file": expected["artifact"],
            "pointer": expected["location"],
            "commit": payload["head"],
            "line": None,
            "sha256": "f" * 64,
        },
    }


def _final(case_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    expected = _case(case_id)["expected"]
    incomplete = expected["status"] == "incomplete"
    findings = [] if incomplete else [
        _finding(item, payload) for item in expected["findings"]
    ]
    completed = ["PRIN-004", "PRIN-005", "PRIN-006", "PRIN-007"]
    missing: list[str] = []
    errors: list[dict[str, str]] = []
    if incomplete:
        completed = ["PRIN-004", "PRIN-005", "PRIN-006"]
        missing = ["PRIN-007"]
        errors = [
            {
                "code": "semantic_rules_incomplete",
                "message": "Synthetic missing context is intentionally incomplete.",
            }
        ]
    escalate = incomplete or bool(findings)
    return {
        "schema": "aga.final-review/v1",
        "status": "incomplete" if incomplete else "completed",
        "review_id": payload["review_id"],
        "review_digest": REVIEW_DIGEST,
        "task_digest": TASK_DIGEST,
        "review_provenance_json": "{}",
        "findings": findings,
        "observations": [],
        "completed_rule_ids": completed,
        "missing_rule_ids": missing,
        "analysis_errors": errors,
        "verdict": expected["verdict"],
        "escalate": escalate,
        "human_review_required": escalate,
        "auto_merge": False,
        "incomplete": incomplete,
    }


class FakeServer:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.trace: list[dict[str, Any]] = []

    def __enter__(self) -> "FakeServer":
        self.events.append("server_enter")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.events.append("server_exit")


class FakeBackend:
    def __init__(
        self,
        case_id: str,
        server: FakeServer,
        events: list[str],
        *,
        mutate_workspace: Path | None = None,
        technical_failure: bool = False,
    ) -> None:
        self.case_id = case_id
        self.server = server
        self.events = events
        self.mutate_workspace = mutate_workspace
        self.technical_failure = technical_failure
        self.payload: Mapping[str, Any] | None = None

    def schedule_task(
        self, task_name: str, payload: Mapping[str, Any] | None = None
    ) -> str:
        self.events.append("schedule")
        assert self.events.index("preflight") < self.events.index("schedule")
        assert task_name == "aga:review"
        assert payload is not None
        assert set(payload) == {
            "repository_id",
            "base",
            "head",
            "review_id",
            "data_classification",
            "idempotency_key",
        }
        assert payload["data_classification"] == "synthetic-public"
        assert payload["review_id"] == payload["idempotency_key"] == REVIEW_ID
        self.payload = dict(payload)
        return TASK_ID

    def wait_for_task(self, task_id: str, timeout: float | None = None) -> TaskResult:
        del timeout
        self.events.append("wait")
        assert task_id == TASK_ID and self.payload is not None
        if self.mutate_workspace is not None:
            (self.mutate_workspace / "model-write.txt").write_text(
                "synthetic forbidden mutation\n", encoding="utf-8"
            )
        if self.technical_failure:
            return TaskResult(
                task_id=TASK_ID,
                task_name="aga:review",
                status=TaskStatus.FAILED,
                error="synthetic provider failure",
                metadata={"error_code": "external_failed"},
            )
        final = _final(self.case_id, self.payload)
        final_hash = hashlib.sha256(_canonical(final)).hexdigest()
        review_hash = hashlib.sha256(REVIEW_ID.encode("utf-8")).hexdigest()
        prepare_hash = "a" * 64
        self.server.trace[:] = [
            {
                "tool": "aga_prepare_review",
                "args_sha256": "b" * 64,
                "status": "ok",
                "output_status": "ready",
                "output_incomplete": False,
                "output_sha256": prepare_hash,
                "review_id_sha256": review_hash,
                "review_digest": REVIEW_DIGEST,
                "task_digest": TASK_DIGEST,
            },
            {
                "tool": "aga_finalize_review",
                "args_sha256": "c" * 64,
                "status": "incomplete" if final["incomplete"] else "ok",
                "output_status": final["status"],
                "output_incomplete": final["incomplete"],
                "output_sha256": final_hash,
                "review_id_sha256": review_hash,
                "review_digest": REVIEW_DIGEST,
                "task_digest": TASK_DIGEST,
            },
        ]
        incomplete = final["incomplete"]
        metadata: dict[str, Any] = {
            "external_status": "completed",
            "review_id": REVIEW_ID,
            "review_digest": REVIEW_DIGEST,
            "task_digest": TASK_DIGEST,
            "aga_status": final["status"],
            "verdict": final["verdict"],
            "human_review_required": final["human_review_required"],
            "auto_merge": False,
            "runtime": {"name": "ouroboros", "version": e2e.PINNED_VERSION},
            "provider": e2e.PROVIDER,
            "model": {"name": e2e.MODEL_ID},
            "prompt_sha256": "d" * 64,
            "tool_names": ["aga_prepare_review", "aga_finalize_review"],
            "prepare_output_sha256": prepare_hash,
            "final_output_sha256": final_hash,
            "aga_final": final,
            "model_usage": {
                "provider": e2e.PROVIDER,
                "model": e2e.MODEL_ID,
                "call_count": 1,
                "known_cost_usd": 0.001,
                "cost_complete": True,
            },
        }
        if incomplete:
            metadata["error_code"] = "aga_incomplete"
        return TaskResult(
            task_id=TASK_ID,
            task_name="aga:review",
            status=TaskStatus.FAILED if incomplete else TaskStatus.SUCCEEDED,
            error="aga_incomplete" if incomplete else None,
            metadata=metadata,
        )

    def get_task_result(self, task_id: str) -> TaskResult:  # pragma: no cover
        raise AssertionError(f"unexpected get_task_result({task_id!r})")


def _dependencies(
    tmp_path: Path,
    events: list[str],
    *,
    preflight_error: e2e.E2ERunnerError | None = None,
    mutate: bool = False,
    technical_failure: bool = False,
) -> e2e._Dependencies:
    server_holder: dict[str, FakeServer] = {}

    def server_factory(_case_id: str, _workspace: Path) -> FakeServer:
        events.append("server_factory")
        server = FakeServer(events)
        server_holder["server"] = server
        return server

    def preflight_check() -> e2e.PreflightReady:
        events.append("preflight")
        if preflight_error is not None:
            raise preflight_error
        return e2e.PreflightReady(
            payload={"status": "ready"}, executable="/synthetic/ouroboros"
        )

    def backend_factory(
        workspace: Path,
        server: e2e.ServerHandle,
        executable: str,
        timeout: float,
    ) -> FakeBackend:
        events.append("backend_factory")
        assert server is server_holder["server"]
        assert executable == "/synthetic/ouroboros"
        assert timeout == 600.0
        return FakeBackend(
            workspace.name,
            server_holder["server"],
            events,
            mutate_workspace=workspace if mutate else None,
            technical_failure=technical_failure,
        )

    ticks = iter((10.0, 10.125))
    return replace(
        e2e._Dependencies(),
        server_factory=server_factory,
        preflight_check=preflight_check,
        backend_factory=backend_factory,
        materialized_root=tmp_path / "materialized",
        evidence_root=tmp_path,
        review_id_factory=lambda: REVIEW_ID,
        monotonic=lambda: next(ticks),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )


def test_blocker_smoke_preflights_before_task_and_writes_sanitized_evidence(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    output = tmp_path / "evidence" / "run.json"
    run = e2e.run_trusted_case(
        "ga-05-critical-eliminate",
        evidence_out=output,
        _dependencies=_dependencies(tmp_path, events),
    )

    assert events == [
        "server_factory",
        "server_enter",
        "preflight",
        "backend_factory",
        "schedule",
        "wait",
        "server_exit",
    ]
    assert run.score["runs"][0]["assessment"] == "PASS"
    assert run.evidence["run"]["final"] == {
        "final_status": "completed",
        "verdict": "request_changes_escalate",
        "human_review_required": True,
        "auto_merge": False,
        "task_digest": TASK_DIGEST,
        "review_digest": REVIEW_DIGEST,
    }
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == run.evidence
    serialized = output.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert "expected" not in serialized
    assert "labels" not in serialized
    assert '"raw_prompt":' not in serialized


def test_verified_aga_incomplete_is_a_scored_domain_outcome(tmp_path: Path) -> None:
    events: list[str] = []
    run = e2e.run_trusted_case(
        "ga-12-missing-context",
        evidence_out=None,
        _dependencies=_dependencies(tmp_path, events),
    )

    assert run.response["normalized"] == {
        "status": "incomplete",
        "verdict": "incomplete",
        "findings": [],
    }
    assert run.response["raw_sanitized"]["task_status"] == "failed"
    assert run.score["runs"][0]["assessment"] == "PASS"
    assert run.evidence["run"]["final"]["human_review_required"] is True
    assert run.evidence["run"]["final"]["auto_merge"] is False


def test_not_configured_preflight_stops_before_backend_and_writes_nothing(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    output = tmp_path / "must-not-exist.json"
    with pytest.raises(e2e.E2ERunnerError) as caught:
        e2e.run_trusted_case(
            "ga-05-critical-eliminate",
            evidence_out=output,
            _dependencies=_dependencies(
                tmp_path,
                events,
                preflight_error=e2e.E2ERunnerError(
                    "not_configured", "budget_not_configured"
                ),
            ),
        )

    assert caught.value.status == "not_configured"
    assert caught.value.code == "budget_not_configured"
    assert "backend_factory" not in events
    assert "schedule" not in events
    assert not output.exists()


def test_task_failure_and_workspace_mutation_fail_without_evidence(
    tmp_path: Path,
) -> None:
    for suffix, options, expected_code in (
        ("provider", {"technical_failure": True}, "external_failed"),
        ("mutation", {"mutate": True}, "workspace_not_clean"),
    ):
        root = tmp_path / suffix
        root.mkdir()
        output = root / "must-not-exist.json"
        with pytest.raises(e2e.E2ERunnerError) as caught:
            e2e.run_trusted_case(
                "ga-05-critical-eliminate",
                evidence_out=output,
                _dependencies=_dependencies(root, [], **options),
            )
        assert caught.value.code == expected_code
        assert not output.exists()


def test_capture_scanner_rejects_provider_secret_and_absolute_local_paths() -> None:
    with pytest.raises(ValueError, match="credential"):
        e2e._assert_sanitized({"value": "sk-or-v1-" + "x" * 32})
    for path in (
        "/Users/synthetic/private/repo",
        "/",
        "//server/share/private",
        "///private/tmp/repo",
        "////",
        "/private/tmp/local/repo",
        "/tmp/local/repo",
        "/var/folders/local/repo",
        "/opt/custom/repo",
        "prefix /mnt/data/repo",
        "prefix,/srv/local/repo",
        "see)/Users/private/repo",
        "see]/tmp/private",
        "see}/home/private",
        "see>/var/private",
        "prefix-/etc/passwd",
        r"prefix-\Windows\System32",
        r"prefix-\\server\share\secret",
        r"prefix-\\.\pipe\secret",
        "-file:///etc/passwd",
        "prefix#/etc/passwd",
        ":\\\\server\\share\\secret",
        "_/etc/passwd",
        r"_\Windows\System32",
        r"_\\server\share\secret",
        "_file:///etc/passwd",
        "C:\\local\\repo",
        "D:/local/repo",
        r"\\server\share\repo",
        "\\\\\\server\\share\\repo",
        r"\Users\private\repo",
        "\\",
        "file:///tmp/local/repo",
    ):
        with pytest.raises(ValueError, match="absolute local path"):
            e2e._assert_sanitized({"value": path})


def test_capture_scanner_preserves_semantic_slash_values_and_urls() -> None:
    e2e._assert_sanitized(
        {
            "location": "/components/demo.synthetic",
            "pointer": "/seaf.change.adr/demo.synthetic",
            "endpoint": "/mcp",
            "reference": "https://example.invalid/synthetic/path",
            "artifact": "model/components.yaml",
            "nested_artifact": "synthetic_only/value",
            "source_ref": "aga-skill/rules/principles.yaml#/rules/5",
        }
    )
    e2e._assert_sanitized({"artifact": "model_dir/synthetic_file.yaml"})
    for path in (
        "/private/tmp/repo",
        "/components/../tmp/repo",
        "/components/demo.synthetic /private/tmp/repo",
        "/components/demo.synthetic\n/tmp/repo",
        r"/components/C:\Users\private\repo",
        "/components/~1private~1tmp~1repo",
        "/components/~1~1server~1share~1private",
        "/components/-~1etc~1passwd",
    ):
        with pytest.raises(ValueError, match="absolute local path"):
            e2e._assert_sanitized({"location": path})

    for key in (
        "/etc/passwd",
        r"C:\Windows\System32",
        r"\\server\share\secret",
        "file:///etc/passwd",
    ):
        with pytest.raises(ValueError, match="absolute local path"):
            e2e._assert_sanitized({key: "safe"})
    with pytest.raises(ValueError, match="non-string key"):
        e2e._assert_sanitized({1: "safe"})


def test_versioned_prompt_contains_no_frozen_case_id() -> None:
    prompt = e2e.PROMPT_PATH.read_text(encoding="utf-8")
    cases = evaluator._cases_from_paths(evaluator.corpus_files())
    assert all(case["id"] not in prompt for case in cases)
    assert e2e._prompt_template_sha256() == hashlib.sha256(
        prompt.encode("utf-8")
    ).hexdigest()


def test_default_mcp_factory_is_exact_loopback_fixture_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def review_service(**kwargs: Any) -> object:
        captured["service"] = kwargs
        return object()

    def server_config(**kwargs: Any) -> Mapping[str, Any]:
        captured["config"] = kwargs
        return kwargs

    def server(service: object, *, config: Mapping[str, Any]) -> tuple[object, Mapping[str, Any]]:
        captured["server_service"] = service
        captured["server_config"] = config
        return service, config

    workspace = tmp_path / "ga-05-critical-eliminate"
    workspace.mkdir()
    monkeypatch.setattr(e2e, "ReviewService", review_service)
    monkeypatch.setattr(e2e, "MCPServerConfig", server_config)
    monkeypatch.setattr(e2e, "MCPServer", server)

    result = e2e._default_server_factory(workspace.name, workspace)

    assert result == (captured["server_service"], captured["server_config"])
    assert captured["service"]["repositories"] == {
        workspace.name: {
            "repository": workspace,
            "manifest_path": "dochub.yaml",
            "dependency_mode": "fixture",
        }
    }
    assert captured["config"] == {
        "host": "127.0.0.1",
        "port": 8788,
        "endpoint": "/mcp",
        "mode": "none",
        "bearer_token": None,
        "request_timeout_seconds": 20.0,
        "max_concurrency": 4,
    }


def test_default_backend_binds_receipts_exact_model_and_versioned_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    workspace = tmp_path / "ga-05-critical-eliminate"
    workspace.mkdir()
    server = FakeServer([])
    server.trace.append({"tool": "aga_prepare_review"})

    def backend(config: Any) -> Any:
        captured["config"] = config
        return config

    monkeypatch.setattr(e2e, "OuroborosTaskBackend", backend)
    result = e2e._default_backend_factory(
        workspace, server, "/synthetic/ouroboros", 600.0
    )

    assert result is captured["config"]
    config = captured["config"]
    assert config.command_prefix == ("/synthetic/ouroboros",)
    assert config.runtime_version == "6.64.1"
    assert config.model_id == "deepseek/deepseek-v4-pro"
    assert config.workspaces == {workspace.name: workspace}
    assert config.prompt_path == e2e.PROMPT_PATH
    assert config.task_timeout_seconds == 600.0
    assert config.server_id == "aga"
    assert config.receipt_source() == tuple(server.trace)


def test_capture_rejects_incomplete_provider_cost_accounting() -> None:
    server = FakeServer([])
    backend = FakeBackend("ga-05-critical-eliminate", server, ["preflight"])
    payload = {
        "repository_id": "ga-05-critical-eliminate",
        "base": "a" * 40,
        "head": "b" * 40,
        "review_id": REVIEW_ID,
        "data_classification": "synthetic-public",
        "idempotency_key": REVIEW_ID,
    }
    task_id = backend.schedule_task("aga:review", payload)
    result = backend.wait_for_task(task_id)
    metadata = dict(result.metadata)
    metadata["model_usage"] = {
        **dict(metadata["model_usage"]),
        "cost_complete": False,
    }

    with pytest.raises(e2e.E2ERunnerError) as caught:
        e2e._task_response(
            replace(result, metadata=metadata),
            record={
                "case_id": "ga-05-critical-eliminate",
                "base_revision": payload["base"],
                "head_revision": payload["head"],
            },
            review_id=REVIEW_ID,
            trace=server.trace,
            latency_ms=1.0,
        )

    assert caught.value.code == "model_usage_contract_mismatch"


def test_public_smoke_cli_rejects_every_other_case_before_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def forbidden_runner(*_args: Any, **_kwargs: Any) -> None:
        nonlocal called
        called = True
        raise AssertionError("paid runner must not start")

    monkeypatch.setattr(e2e, "run_trusted_case", forbidden_runner)
    exit_code = e2e.main(["--case", "ga-16-semantic-clean"])

    assert exit_code == 2
    assert called is False
    assert json.loads(capsys.readouterr().out) == {
        "schema": e2e.CLI_RESULT_SCHEMA,
        "status": "not_authorized",
        "code": "smoke_case_not_authorized",
        "case_id": "ga-16-semantic-clean",
    }
