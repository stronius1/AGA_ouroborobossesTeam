# -*- coding: utf-8 -*-
"""Fast replay and loopback API coverage for the self-evolution UI."""

from __future__ import annotations

from contextlib import contextmanager
from http import HTTPStatus
import http.client
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Iterator

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import self_evolution_ui as ui  # noqa: E402
from scripts.generate_self_evolution_scenario import build_scenario  # noqa: E402


FRONTEND_ROOT = REPOSITORY_ROOT / "self-evolution-ui"


def _ready_live(model_id: str) -> dict:
    payload = ui._base_live_readiness(model_id)
    payload.update({"status": "ready", "code": "ok", "model": model_id})
    return payload


def test_profile_model_switch_is_bounded_and_uses_one_allowlisted_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = iter(("stopped", "synced", "started"))
    calls: list[tuple[str, str]] = []

    def fake_process(command, **kwargs):
        action = command[-1]
        calls.append((action, kwargs["model_id"]))
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"status": next(statuses)}).encode(),
            b"",
        )

    monkeypatch.setattr(ui, "_bounded_process", fake_process)

    assert ui._switch_profile_model(
        "scripts/ouroboros_profile.py", "moonshotai/kimi-k3"
    )
    assert calls == [
        ("stop", "moonshotai/kimi-k3"),
        ("sync", "moonshotai/kimi-k3"),
        ("start", "moonshotai/kimi-k3"),
    ]


def _json_body(raw: bytes) -> dict:
    value = json.loads(raw.decode("utf-8"))
    assert isinstance(value, dict)
    return value


def _request(
    server: ui.EvolutionHTTPServer,
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers or {})
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")
        request_headers.setdefault("Content-Length", str(len(body)))
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_port, timeout=3
    )
    try:
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@contextmanager
def _running_server(
    manager: ui.JobManager | None = None,
) -> Iterator[ui.EvolutionHTTPServer]:
    server = ui.EvolutionHTTPServer(
        ("127.0.0.1", 0), manager or ui.JobManager()
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _wait_for_terminal_run(
    server: ui.EvolutionHTTPServer,
    run_id: str,
) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status, _, raw = _request(server, "GET", f"/api/v1/runs/{run_id}")
        assert status == HTTPStatus.OK
        run = _json_body(raw)
        if run["state"] in {"succeeded", "failed"}:
            return run
        threading.Event().wait(0.01)
    pytest.fail("replay run did not finish")


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [
        (b'{"key":1,"key":2}', "request_invalid_json"),
        (b'{"value":NaN}', "request_invalid_json"),
        (b"[]", "request_must_be_object"),
        (b"\xff", "request_invalid_json"),
    ],
)
def test_strict_json_rejects_ambiguous_or_unsafe_input(
    raw: bytes,
    error_code: str,
) -> None:
    with pytest.raises(ui.UIError) as caught:
        ui._strict_json_object(raw)
    assert caught.value.code == error_code

    with pytest.raises(ui.UIError) as oversized:
        ui._strict_json_object(b"{" + b" " * ui.MAX_REQUEST_BYTES + b"}")
    assert oversized.value.code == "request_too_large"


def test_job_manager_blocks_unconfirmed_paid_run_and_parallel_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ui.JobManager()
    with pytest.raises(ui.UIError) as unconfirmed:
        manager.start(
            lane="architecture",
            execution="live",
            confirm_paid_run=False,
        )
    assert unconfirmed.value.code == "paid_run_confirmation_required"

    release = threading.Event()
    monkeypatch.setattr(manager, "_execute", lambda _run_id: release.wait(1))
    first = manager.start(
        lane="architecture",
        execution="replay",
        confirm_paid_run=False,
    )
    try:
        with pytest.raises(ui.UIError) as parallel:
            manager.start(
                lane="rules",
                execution="replay",
                confirm_paid_run=False,
            )
        assert parallel.value.code == "run_already_active"
        assert parallel.value.http_status == HTTPStatus.CONFLICT
        assert ui.RUN_ID_RE.fullmatch(first["run_id"])
    finally:
        release.set()


def test_legacy_rules_lane_rejects_false_live_provenance(
    tmp_path: Path,
) -> None:
    manager = ui.JobManager(
        public_run_store=tmp_path / "last-public-run.json",
        readiness_probe=_ready_live,
    )
    with pytest.raises(ui.UIError) as caught:
        manager.start(
            lane="rules",
            execution="live",
            confirm_paid_run=True,
        )
    assert caught.value.code == "execution_invalid"


def test_job_manager_accepts_only_allowlisted_live_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ui.JobManager(readiness_probe=_ready_live)
    scenario = manager.create_scenario(
        seed="pytest-model-choice",
        preset="full",
        parallel_workers=2,
    )
    release = threading.Event()
    monkeypatch.setattr(manager, "_execute", lambda _run_id: release.wait(1))
    selected = manager.start(
        lane="e2e",
        execution="live",
        confirm_paid_run=True,
        scenario_id=scenario["scenario_id"],
        model_id="moonshotai/kimi-k3",
    )
    try:
        assert selected["model_id"] == "moonshotai/kimi-k3"
        assert selected["provider"] == "OpenRouter"
        assert selected["display_mode"] == "LIVE"
        assert selected["recorded_evidence"] is False
    finally:
        release.set()

    rejected = ui.JobManager(readiness_probe=_ready_live)
    rejected_scenario = rejected.create_scenario(
        seed="pytest-model-rejected",
        preset="full",
        parallel_workers=2,
    )
    with pytest.raises(ui.UIError) as caught:
        rejected.start(
            lane="e2e",
            execution="live",
            confirm_paid_run=True,
            scenario_id=rejected_scenario["scenario_id"],
            model_id="arbitrary/untrusted-model",
        )
    assert caught.value.code == "model_not_supported"


def test_failed_live_preflight_is_cached_and_blocks_paid_run(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def failed_probe(model_id: str) -> dict:
        calls.append(model_id)
        payload = ui._base_live_readiness(model_id)
        payload.update(
            {
                "status": "failed",
                "code": "profile_not_running",
                "profile_status": "stopped",
            }
        )
        return payload

    manager = ui.JobManager(
        public_run_store=tmp_path / "last-public-run.json",
        readiness_probe=failed_probe,
    )
    first = manager.live_readiness(ui.DEFAULT_MODEL_ID)
    second = manager.live_readiness(ui.DEFAULT_MODEL_ID)
    assert first == second
    assert calls == [ui.DEFAULT_MODEL_ID]

    with pytest.raises(ui.UIError) as caught:
        manager.start(
            lane="architecture",
            execution="live",
            confirm_paid_run=True,
        )
    assert caught.value.code == "profile_not_running"
    assert caught.value.http_status == HTTPStatus.SERVICE_UNAVAILABLE
    assert calls == [ui.DEFAULT_MODEL_ID]

    manager.live_readiness(ui.DEFAULT_MODEL_ID, force=True)
    assert calls == [ui.DEFAULT_MODEL_ID, ui.DEFAULT_MODEL_ID]


def test_live_preflight_rejects_duplicate_or_substituted_mcp_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_id = ui.DEFAULT_MODEL_ID
    malformed_gateway = [
        *ui.ALL_MCP_TOOL_NAMES[:-1],
        ui.ALL_MCP_TOOL_NAMES[0],
    ]
    responses = iter(
        [
            ui.subprocess.CompletedProcess(
                (), 0, json.dumps({"status": "running"}).encode(), b""
            ),
            ui.subprocess.CompletedProcess(
                (),
                0,
                json.dumps(
                    {
                        "schema": "aga.ouroboros-preflight/v1",
                        "status": "ready",
                        "runtime": {"version": "6.64.1"},
                        "configuration": {
                            "provider": "openrouter",
                            "model": model_id,
                            "global_hard_cap_max_usd": 50.0,
                        },
                        "mcp": {
                            "gateway_discovery": {"tools": malformed_gateway},
                            "worker_ready_discovery": {
                                "stages": {
                                    "review": {
                                        "active_tools": list(
                                            ui.REVIEW_MCP_TOOL_NAMES
                                        )
                                    },
                                    "remediation": {
                                        "active_tools": list(
                                            ui.REMEDIATION_MCP_TOOL_NAMES
                                        )
                                    },
                                }
                            },
                        },
                    }
                ).encode(),
                b"",
            ),
        ]
    )
    monkeypatch.setattr(ui, "_bounded_process", lambda *_args, **_kwargs: next(responses))

    readiness = ui._probe_live_readiness(model_id)

    assert readiness["status"] == "failed"
    assert readiness["code"] == "mcp_tools_not_ready"
    assert readiness["mcp_gateway"] == "failed"


def test_live_readiness_endpoint_returns_sanitized_failure(
    tmp_path: Path,
) -> None:
    def failed_probe(model_id: str) -> dict:
        payload = ui._base_live_readiness(model_id)
        payload.update(
            {
                "status": "failed",
                "code": "budget_api_unavailable",
                "profile_status": "running",
                "mcp_gateway": "ready",
            }
        )
        return payload

    manager = ui.JobManager(
        public_run_store=tmp_path / "last-public-run.json",
        readiness_probe=failed_probe,
    )
    with _running_server(manager) as server:
        status, _, raw = _request(server, "GET", "/api/v2/bootstrap")
        token = _json_body(raw)["session_token"]
        assert status == HTTPStatus.OK
        status, _, raw = _request(
            server,
            "POST",
            "/api/v2/live-readiness",
            payload={"model_id": ui.DEFAULT_MODEL_ID, "force": True},
            headers={
                "X-AGA-UI-Token": token,
                "Origin": f"http://127.0.0.1:{server.server_port}",
            },
        )
    assert status == HTTPStatus.OK
    readiness = _json_body(raw)
    assert readiness["status"] == "failed"
    assert readiness["code"] == "budget_api_unavailable"
    assert readiness["classification"] == "synthetic-public"
    assert readiness["tools"]["review"]["required"] == 4
    assert readiness["tools"]["remediation"]["required"] == 2
    assert "secret" not in json.dumps(readiness).lower()


def _minimal_scenario() -> dict:
    scenario = {
        "schema": ui.SCENARIO_SCHEMA,
        "scenario_id": "",
        "seed": "pytest-public-run",
        "preset": "full",
        "parallel_workers": 2,
        "classification": "synthetic-public",
        "graph": {"nodes": [], "edges": []},
        "tests": [{"id": "pr-15"}],
    }
    scenario["content_sha256"] = ui._scenario_content_sha256(scenario)
    scenario["scenario_id"] = f"e2e-{scenario['content_sha256'][:16]}"
    return scenario


def _terminal_public_run(run_id: str = "a1b2c3d4e5f6") -> ui.EvolutionRun:
    scenario = _minimal_scenario()
    artifacts = [
        {
            "id": f"artifact-{index}",
            "label": f"Artifact {index}",
            "kind": "evidence",
            "path": f".aga-runs/self-evolution-ui/{run_id}/artifact-{index}.json",
            "sha256": f"{index:064x}"[-64:],
        }
        for index in range(1, 10)
    ]
    run = ui.EvolutionRun(
        run_id=run_id,
        lane="e2e",
        execution="local",
        state="succeeded",
        phase="completed",
        scenario_id=scenario["scenario_id"],
        scenario=scenario,
        tests=[
            {
                "id": "pr-15",
                "status": "passed",
                "candidate": {"passed": True},
            }
        ],
        result={
            "schema": ui.E2E_RESULT_SCHEMA,
            "scenario_id": scenario["scenario_id"],
            "gate": {
                "passed": True,
                "checks": [
                    {
                        "id": "architecture_closed",
                        "label": "Architecture finding closed",
                        "passed": True,
                    }
                ],
            },
            "summary": {
                "tests": 1,
                "candidate_passed": 1,
                "behavior_changed": ["pr-15"],
                "architecture_engine": ui.LOCAL_ARCHITECTURE_ENGINE,
                "actual_cost_usd": None,
                "human_review_required": True,
                "merge_performed": False,
            },
            "artifacts": artifacts,
        },
        started_at_unix_ms=1_000,
        finished_at_unix_ms=2_000,
    )
    run.append(
        "run.completed",
        "E2E complete",
        "E2E Orchestrator",
        "Gate passed",
        kind="terminal",
        status="passed",
    )
    return run


def test_terminal_run_is_atomic_checksum_verified_recorded_evidence(
    tmp_path: Path,
) -> None:
    store = tmp_path / "ui-store" / "last-public-run.json"
    manager = ui.JobManager(public_run_store=store)
    run = _terminal_public_run()
    manager._runs[run.run_id] = run
    manager._active_run_id = run.run_id
    manager._persist_terminal_run(run.run_id)

    envelope = ui._strict_public_envelope(store.read_bytes())
    assert envelope["schema"] == ui.PUBLIC_RUN_ENVELOPE_SCHEMA
    assert len(envelope["payload_sha256"]) == 64
    assert (store.parent / run.run_id / "public-run.json").is_file()

    restored = ui.JobManager(public_run_store=store).current()
    assert restored is not None
    assert restored["run_id"] == run.run_id
    assert restored["recorded_evidence"] is True
    assert restored["display_mode"] == "RECORDED EVIDENCE"
    assert restored["source_execution"] == "local"

    tampered = json.loads(store.read_text(encoding="utf-8"))
    tampered["run"]["state"] = "failed"
    store.write_text(json.dumps(tampered), encoding="utf-8")
    fallback = ui.JobManager(public_run_store=store).current()
    assert fallback is not None
    assert fallback["run_id"] == run.run_id
    (store.parent / run.run_id / "public-run.json").write_text(
        json.dumps(tampered),
        encoding="utf-8",
    )
    assert ui.JobManager(public_run_store=store).current() is None


@pytest.mark.parametrize("mutation", ("engine", "result", "scenario"))
def test_persisted_run_rejects_semantically_inconsistent_provenance(
    mutation: str,
) -> None:
    public = json.loads(json.dumps(_terminal_public_run().public()))
    if mutation == "engine":
        public["execution"] = "live"
        public["display_mode"] = "LIVE"
        public["model_id"] = ui.DEFAULT_MODEL_ID
        public["provider"] = "OpenRouter"
        public["result"]["summary"]["actual_cost_usd"] = 0.0
        # The engine deliberately remains LOCAL.
    elif mutation == "result":
        public["result"] = None
    else:
        public["scenario_id"] = "e2e-ffffffffffffffff"
    raw = ui._canonical_json(ui.JobManager._public_run_envelope(public))

    with pytest.raises(ui.UIError) as caught:
        ui._strict_public_envelope(raw)

    assert caught.value.code == "recorded_run_schema_mismatch"


def test_failed_run_restores_as_verified_recorded_evidence(
    tmp_path: Path,
) -> None:
    store = tmp_path / "last-public-run.json"
    scenario = _minimal_scenario()
    failed = ui.EvolutionRun(
        run_id="deadc0ffee00",
        lane="e2e",
        execution="live",
        state="failed",
        phase="failed",
        scenario_id=scenario["scenario_id"],
        scenario=scenario,
        tests=[{"id": "pr-15", "status": "queued"}],
        error_code="invalid_aga_receipt",
        started_at_unix_ms=1_000,
        finished_at_unix_ms=2_000,
    )
    failed.append(
        "run.failed",
        "Live failed",
        "E2E Orchestrator",
        "invalid_aga_receipt",
        kind="terminal",
        status="failed",
    )
    manager = ui.JobManager(public_run_store=store)
    manager._runs[failed.run_id] = failed
    manager._active_run_id = failed.run_id
    manager._persist_terminal_run(failed.run_id)

    restored = ui.JobManager(public_run_store=store).current()

    assert restored is not None
    assert restored["state"] == "failed"
    assert restored["result"] is None
    assert restored["recorded_evidence"] is True
    assert restored["display_mode"] == "RECORDED EVIDENCE"
    assert restored["source_execution"] == "live"


def test_sanitized_report_download_has_no_credentials(
    tmp_path: Path,
) -> None:
    manager = ui.JobManager(public_run_store=tmp_path / "last-public-run.json")
    run = _terminal_public_run("b1c2d3e4f5a6")
    run.events[0]["data"] = {
        "api_key": "sk-" + "or-v1-this-value-must-never-leave",
        "safe": "public",
    }
    manager._runs[run.run_id] = run
    manager._active_run_id = run.run_id
    with _running_server(manager) as server:
        status, headers, raw = _request(
            server,
            "GET",
            f"/api/v2/runs/{run.run_id}/report",
        )
    assert status == HTTPStatus.OK
    assert headers["Content-Disposition"].endswith(
        f'aga-self-evolution-{run.run_id}.json"'
    )
    report = _json_body(raw)
    assert report["schema"] == ui.PUBLIC_RUN_REPORT_SCHEMA
    assert report["sanitized"] is True
    assert report["architecture_engine"] == ui.LOCAL_ARCHITECTURE_ENGINE
    assert report["merge_performed"] is False
    assert "sk-or" not in raw.decode("utf-8").lower()


def test_local_recovery_links_failed_live_evidence_without_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = ui.JobManager(
        public_run_store=tmp_path / "last-public-run.json",
        readiness_probe=_ready_live,
    )
    scenario = {
        "scenario_id": "e2e-fedcba9876543210",
        "parallel_workers": 2,
        "tests": [],
    }
    manager._scenarios[scenario["scenario_id"]] = scenario
    failed = ui.EvolutionRun(
        run_id="0badc0ffee00",
        lane="e2e",
        execution="live",
        state="failed",
        phase="failed",
        scenario_id=scenario["scenario_id"],
        scenario=scenario,
        error_code="invalid_aga_receipt",
        failure={"component": "architecture", "stage": "review_before"},
        cost_usd=0.021,
    )
    failed.append(
        "run.failed",
        "Live failed",
        "E2E Orchestrator",
        "invalid_aga_receipt",
        kind="terminal",
        status="failed",
    )
    manager._runs[failed.run_id] = failed
    monkeypatch.setattr(manager, "_execute", lambda _run_id: None)

    recovery = manager.start(
        lane="e2e",
        execution="local",
        confirm_paid_run=False,
        scenario_id=scenario["scenario_id"],
        recovery_of_run_id=failed.run_id,
    )
    assert recovery["display_mode"] == "LOCAL"
    assert recovery["recovery"] == {
        "source_run_id": failed.run_id,
        "source_mode": "LIVE",
        "error_code": "invalid_aga_receipt",
        "failure": failed.failure,
        "failed_event": failed.events[-1],
        "cost_usd": 0.021,
        "same_scenario": True,
        "model_calls_replayed": False,
    }


@pytest.mark.parametrize(
    ("stage", "expected_label", "expected_tool"),
    [
        ("review_before", "первый review", "aga_prepare_review"),
        ("remediation", "remediation", "aga_prepare_remediation"),
        ("materialize", "не материализован", "aga_finalize_remediation"),
        ("review_after", "re-review", "aga_prepare_review"),
    ],
)
def test_live_failure_projection_is_stage_aware(
    stage: str,
    expected_label: str,
    expected_tool: str,
) -> None:
    projection = ui._architecture_failure_projection(stage)
    assert expected_label in projection["label"]
    assert projection["tool"] == expected_tool
    if stage != "review_before":
        assert projection["label"] != "Ouroboros не завершил первый review"


def test_live_evidence_cost_is_preserved_before_projection_without_double_count(
    tmp_path: Path,
) -> None:
    manager = ui.JobManager(public_run_store=tmp_path / "last-public-run.json")
    scenario = _minimal_scenario()
    run = ui.EvolutionRun(
        run_id="c057c057c057",
        lane="e2e",
        execution="live",
        state="running",
        scenario_id=scenario["scenario_id"],
        scenario=scenario,
    )
    manager._initialise_e2e_agents(run)
    manager._runs[run.run_id] = run
    evidence = {
        "review_before": {"model_usage": {"known_cost_usd": 0.01}},
        "remediation": {"model_usage": {"known_cost_usd": 0.02}},
        "review_after": {"model_usage": {"known_cost_usd": 0.03}},
    }

    cost = manager._record_architecture_evidence_cost(run.run_id, evidence)

    assert cost == pytest.approx(0.06)
    assert manager.get(run.run_id)["cost_usd"] == pytest.approx(0.06)
    manager._agent_finished(
        run.run_id,
        "architecture",
        int(time.time() * 1000),
        "Architecture candidate прошёл re-review",
        cost_usd=cost,
    )
    assert manager.get(run.run_id)["cost_usd"] == pytest.approx(0.06)


def test_loopback_api_serves_fixture_scenario_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ui, "REPLAY_STEP_SECONDS", 0)
    with _running_server() as server:
        status, headers, raw = _request(server, "GET", "/")
        assert status == HTTPStatus.OK
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert "Проверить весь E2E" in raw.decode("utf-8")

        status, headers, raw = _request(server, "GET", "/api/v1/bootstrap")
        assert status == HTTPStatus.OK
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Frame-Options"] == "DENY"
        assert "connect-src 'self'" in headers["Content-Security-Policy"]
        bootstrap = _json_body(raw)
        token = bootstrap["session_token"]
        assert bootstrap["status"] == "ready"
        assert bootstrap["fixture"]["schema"] == "aga.self-evolution-ui/v1"
        assert bootstrap["capabilities"]["one_active_run"] is True
        assert bootstrap["capabilities"]["rules_live"] is False

        authorized = {
            "X-AGA-UI-Token": token,
            "Origin": f"http://127.0.0.1:{server.server_port}",
        }
        status, _, raw = _request(
            server,
            "POST",
            "/api/v1/scenarios",
            payload={"kind": "architecture", "seed": "checkout-demo-1"},
            headers=authorized,
        )
        assert status == HTTPStatus.CREATED
        scenario = _json_body(raw)
        assert scenario["status"] == "generated"
        assert scenario["data"]["classification"] == "synthetic-public"
        assert len(scenario["data"]["components"]) == 3

        status, _, raw = _request(
            server,
            "POST",
            "/api/v1/runs/architecture",
            payload={"execution": "replay", "confirm_paid_run": False},
            headers=authorized,
        )
        assert status == HTTPStatus.ACCEPTED
        run_id = _json_body(raw)["run_id"]
        run = _wait_for_terminal_run(server, run_id)
        assert run["state"] == "succeeded"
        assert len(run["events"]) == 7
        assert run["events"][-1]["id"] == "run.completed"
        assert sum(event["actor"] == "Ouroboros" for event in run["events"]) == 3
        assert run["result"]["summary"]["architecture_gate_passed"] is True
        assert run["result"]["classification"] == "synthetic-public"

        status, _, raw = _request(
            server,
            "POST",
            "/api/v1/runs/rules",
            payload={"execution": "replay", "confirm_paid_run": False},
            headers=authorized,
        )
        assert status == HTTPStatus.ACCEPTED
        rules_run = _wait_for_terminal_run(server, _json_body(raw)["run_id"])
        assert rules_run["state"] == "succeeded"
        assert len(rules_run["events"]) == 6
        assert rules_run["events"][-1]["id"] == "run.completed"
        assert all(event["actor"] != "Ouroboros" for event in rules_run["events"])
        assert rules_run["result"]["rule_evolution"]["tests"]["synthetic_cases"] == 26
        assert rules_run["result"]["rule_evolution"]["tests"]["gate_passed"] is True


def test_loopback_api_rejects_missing_token_cross_origin_and_traversal() -> None:
    with _running_server() as server:
        status, _, raw = _request(server, "GET", "/api/v1/bootstrap")
        token = _json_body(raw)["session_token"]
        assert status == HTTPStatus.OK

        status, headers, raw = _request(
            server,
            "POST",
            "/api/v1/scenarios",
            payload={"kind": "rules", "seed": "rules-demo"},
        )
        assert status == HTTPStatus.FORBIDDEN
        assert _json_body(raw)["code"] == "session_token_invalid"
        assert "Access-Control-Allow-Origin" not in headers

        status, _, raw = _request(
            server,
            "POST",
            "/api/v1/scenarios",
            payload={"kind": "rules", "seed": "rules-demo"},
            headers={
                "X-AGA-UI-Token": token,
                "Origin": "https://evil.example",
            },
        )
        assert status == HTTPStatus.FORBIDDEN
        assert _json_body(raw)["code"] == "origin_forbidden"

        status, _, raw = _request(
            server,
            "GET",
            "/api/v1/bootstrap",
            headers={"Host": "evil.example"},
        )
        assert status == HTTPStatus.FORBIDDEN
        assert _json_body(raw)["code"] == "host_forbidden"

        status, _, raw = _request(server, "GET", "/../README.md")
        assert status == HTTPStatus.NOT_FOUND
        assert _json_body(raw)["code"] == "static_path_invalid"

        status, headers, raw = _request(server, "OPTIONS", "/api/v1/scenarios")
        assert status == HTTPStatus.METHOD_NOT_ALLOWED
        assert _json_body(raw)["code"] == "cors_not_allowed"
        assert "Access-Control-Allow-Origin" not in headers


def test_seeded_scenarios_change_real_work_assignment_and_graph() -> None:
    first = build_scenario(seed="scale-a", preset="full", parallel_workers=4)
    second = build_scenario(seed="scale-b", preset="full", parallel_workers=4)
    assert first["scenario_id"] != second["scenario_id"]
    assert [case["id"] for case in first["tests"]] != [case["id"] for case in second["tests"]]
    assert first["graph"] != second["graph"]
    assert len(first["tests"]) == 26
    assert first["summary"]["systems"] == 11
    assert first["summary"]["flows"] >= 9


def test_real_local_e2e_runs_parallel_workers_and_finishes_atomically(
    tmp_path: Path,
) -> None:
    manager = ui.JobManager(
        public_run_store=tmp_path / "last-public-run.json",
        readiness_probe=_ready_live,
    )
    scenario = manager.create_scenario(
        seed="pytest-real-e2e",
        preset="full",
        parallel_workers=4,
    )
    started = manager.start(
        lane="e2e",
        execution="local",
        confirm_paid_run=False,
        scenario_id=scenario["scenario_id"],
    )
    assert started["state"] == "queued"
    assert started["events"] == []
    assert started["result"] is None
    assert all(case["baseline"] is None and case["candidate"] is None for case in started["tests"])

    deadline = time.monotonic() + 20
    maximum_parallel = 0
    run = started
    while time.monotonic() < deadline:
        run = manager.get(started["run_id"])
        maximum_parallel = max(
            maximum_parallel,
            sum(agent["status"] == "running" for agent in run["agents"]),
        )
        if run["state"] in {"queued", "running"}:
            assert run["result"] is None
            assert not any(
                event["id"] in {"gate.passed", "run.completed"}
                for event in run["events"]
            )
            assert next(agent for agent in run["agents"] if agent["id"] == "gate")[
                "status"
            ] != "succeeded"
        if run["state"] in {"succeeded", "failed"}:
            break
        threading.Event().wait(0.01)
    assert run["state"] == "succeeded", run["error_code"]
    assert maximum_parallel >= 3
    assert run["phase"] == "completed"
    assert run["progress"] == {"done": 57, "total": 57, "percent": 100}
    assert len(run["tests"]) == 26
    assert all(case["candidate"]["passed"] is True for case in run["tests"])
    changed = [
        case["id"]
        for case in run["tests"]
        if case["baseline"]["passed"] != case["candidate"]["passed"]
    ]
    assert changed == ["pr-15"]
    assert run["result"]["gate"]["passed"] is True
    assert (
        run["result"]["summary"]["architecture_engine"]
        == ui.LOCAL_ARCHITECTURE_ENGINE
    )
    assert run["model_id"] is None
    assert run["provider"] is None
    assert run["display_mode"] == "LOCAL"
    assert run["result"]["summary"]["merge_performed"] is False
    declared = next(
        edge for edge in scenario["graph"]["edges"] if edge.get("expected_rule") == "SEAF-004"
    )
    before_edges = {edge["id"]: edge for edge in run["result"]["graph"]["before"]["edges"]}
    after_edges = {edge["id"]: edge for edge in run["result"]["graph"]["after"]["edges"]}
    assert after_edges[declared["id"]]["to"] == declared["replacement_to"]
    assert [
        edge_id for edge_id in before_edges if before_edges[edge_id] != after_edges[edge_id]
    ] == [declared["id"]]
    assert {
        event["graph_delta"]["edge_id"]
        for event in run["events"]
        if event.get("graph_delta")
    } == {declared["id"]}
    for artifact in run["result"]["artifacts"]:
        artifact_path = REPOSITORY_ROOT / artifact["path"]
        assert artifact_path.exists()
        assert len(artifact["sha256"]) == 64
    assert run["events"][-2]["id"] == "gate.passed"
    assert run["events"][-1]["id"] == "run.completed"
    assert run["finished_at_unix_ms"] is not None


def test_failed_live_run_is_terminal_and_keeps_the_real_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A failed paid call must stop polling and remain inspectable after refresh."""

    manager = ui.JobManager(
        public_run_store=tmp_path / "last-public-run.json",
        readiness_probe=_ready_live,
    )
    scenario = manager.create_scenario(
        seed="pytest-invalid-receipt",
        preset="integration",
        parallel_workers=2,
    )

    def reject_receipt(_run_id: str) -> None:
        raise ui.UIError("invalid_aga_receipt")

    monkeypatch.setattr(manager, "_run_e2e", reject_receipt)
    started = manager.start(
        lane="e2e",
        execution="live",
        confirm_paid_run=True,
        scenario_id=scenario["scenario_id"],
    )

    deadline = time.monotonic() + 3
    run = started
    while time.monotonic() < deadline:
        run = manager.get(started["run_id"])
        if run["state"] == "failed":
            break
        threading.Event().wait(0.01)

    assert run["state"] == "failed"
    assert run["phase"] == "failed"
    assert run["execution"] == "live"
    assert run["error_code"] == "invalid_aga_receipt"
    assert run["finished_at_unix_ms"] is not None
    assert run["events"][-1]["id"] == "run.failed"
    assert run["events"][-1]["status"] == "failed"
    assert "invalid_aga_receipt" in run["events"][-1]["detail"]


def test_frontend_explains_invalid_live_receipt_in_plain_language() -> None:
    """The raw backend code is not an acceptable explanation to a demo user."""

    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="demo-profile-quick"' in html
    assert "invalid_aga_receipt:" in app
    message = app.split("invalid_aga_receipt:", 1)[1][:700].lower()
    assert "ouroboros" in message
    assert "ответ" in message or "receipt" in message
    assert "локаль" in message or "$0" in message or "бесплат" in message


def test_frontend_offers_one_click_local_recovery_after_live_failure() -> None:
    """Recovery must reuse the generated scenario without another paid call."""

    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="recovery-local-button"' in html
    assert "function recoverLocally" in app
    recovery = app.split("function recoverLocally", 1)[1][:1200]
    assert 'ui.execution.value = "local"' in recovery
    assert "ui.paid.checked = false" in recovery
    assert "startRun()" in recovery
    assert "recovery-local-button" in app
    assert "recoverLocally" in app.split("recovery-local-button", 1)[-1]


def test_frontend_calls_a_failed_terminal_run_a_failure() -> None:
    """The scenario badge must not say merely 'finished' when the run failed."""

    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    failed_label = app.index('"Прогон завершён с ошибкой"')
    nearby_logic = app[max(0, failed_label - 500) : failed_label + 250]
    assert 'terminal === "failed"' in nearby_logic


def test_frontend_architecture_checkpoints_follow_actual_run_events() -> None:
    """The proof strip must be driven by finding/patch/re-review/gate evidence."""

    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="architecture-checkpoints"' in html
    assert "function renderArchitectureCheckpoints" in app
    renderer = app.split("function renderArchitectureCheckpoints", 1)[1][:6000]
    assert '"finding"' in renderer
    assert '"reroute"' in renderer
    assert '"rereview"' in renderer
    assert "gate.passed" in renderer
    render_all = app.split("function renderAll", 1)[1][:1200]
    assert "renderArchitectureCheckpoints()" in render_all


def test_frontend_exposes_kimi_and_passes_the_selected_model() -> None:
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="model-select"' in html
    assert "moonshotai/kimi-k3" in app
    assert "model_id: ui.model.value" in app
    assert "await generateScenario()" in app


def test_frontend_labels_local_and_live_execution_truthfully() -> None:
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert "Локальный deterministic E2E" in html
    assert "AGA review, remediation, Loop A и 26 тестов, без model calls · $0" in html
    assert "три реальные Ouroboros/OpenRouter задачи" in html
    assert 'id="launch-detail"' in html
    assert "Три Live-задачи Ouroboros/OpenRouter" in app
    assert 'showZero: state.run?.execution !== "live"' in app


def test_frontend_has_short_demo_toggle_and_no_judging_criteria_copy() -> None:
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'name="demo-profile"' in html
    assert "Короткое демо" in html
    assert "6 ключевых тестов" in html
    assert 'preset: "demo"' in app
    assert 'workers: 2' in app
    assert 'model: "deepseek/deepseek-v4-pro"' in app
    assert "КРИТЕРИИ MVP" not in html
    assert "30% · E2E demo" not in html


def test_frontend_javascript_references_only_existing_unique_ids() -> None:
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    identifiers = re.findall(r'\bid="([A-Za-z0-9_-]+)"', html)
    references = set(re.findall(r'getElementById\("([A-Za-z0-9_-]+)"\)', app))
    assert len(identifiers) == len(set(identifiers))
    assert references <= set(identifiers)


def test_frontend_live_readiness_is_fail_closed_and_complete() -> None:
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="live-readiness"' in html
    assert 'id="refresh-readiness-button"' in html
    assert "function selectedLiveIsReady" in app
    assert 'request("/api/v2/live-readiness"' in app
    controls = app.split("function renderControls", 1)[1][:1800]
    assert "!selectedLiveIsReady() || !ui.paid.checked" in controls
    renderer = app.split("function renderLiveReadiness", 1)[1][:6000]
    for label in (
        "Runtime",
        "Provider / model",
        "Profile",
        "MCP gateway",
        "Review tools",
        "Remediation tools",
        "Hard budget cap",
        "Classification",
        "Estimate",
        "VPN / network",
    ):
        assert label in renderer


def test_frontend_keeps_main_progress_in_the_video_frame() -> None:
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")
    css = (FRONTEND_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'id="mini-status"' in html
    assert 'id="live-process"' in html
    assert "function renderMiniStatus" in app
    assert "ui.liveProcess.scrollIntoView" in app
    assert "position: sticky" in css
    assert "renderLiveEvidence()" in app.split("function renderAll", 1)[1][:1200]


def test_frontend_live_proof_and_result_summary_are_compact_and_exportable() -> None:
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="live-evidence"' in html
    assert 'id="live-task-list"' in html
    assert "function liveTaskEvidence" in app
    assert "RECEIPT VERIFIED" in app
    assert "merge:" in app
    for proof in (
        '"Gate"',
        '"Architecture finding"',
        '"Candidate tests"',
        '"Behavior changed only"',
        '"Human review"',
        '"Merge performed"',
        '"Artifacts"',
    ):
        assert proof in app
    assert 'id="export-report-button"' in html
    assert "function exportRunReport" in app
    assert "/report`" in app


def test_frontend_distinguishes_recorded_evidence_and_exact_recovery_error() -> None:
    html = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="failure-error-code"' in html
    assert 'return "RECORDED EVIDENCE"' in app
    assert "новых model calls не было" in app
    assert "Recorded evidence не прошло schema/checksum validation" not in app
    assert "Recorded evidence проверено; run остановлен до итогового gate" in app
    assert "это replay проверенного evidence" not in app
    assert "ui.failureErrorCode.textContent = errorCode" in app
    assert "recovery_of_run_id" in app
    assert "state.recoveryOfRunId" in app

    backend = (REPOSITORY_ROOT / "scripts" / "self_evolution_ui.py").read_text(
        encoding="utf-8"
    )
    assert "trusted_receipt_replay" not in backend
    assert "A run labelled LIVE always performs three fresh paid tasks" in backend


def test_frontend_does_not_call_a_failed_terminal_graph_post_gate() -> None:
    app = (FRONTEND_ROOT / "app.js").read_text(encoding="utf-8")
    renderer = app.split("function renderArchitectureChanges", 1)[1][:7000]

    assert 'terminal === "succeeded" ? "ПОСЛЕ GATE"' in renderer
    assert 'terminal === "failed" ? "ОСТАНОВЛЕНО ДО GATE"' in renderer
    assert "gate не пройден" in renderer
