# -*- coding: utf-8 -*-
"""Contract tests for the pinned, fail-closed Ouroboros CLI adapter."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any, Sequence

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from tools.a2a import TaskStatus, UnknownTaskError  # noqa: E402
from tools.ouroboros_backend import (  # noqa: E402
    BoundedCommandRunner,
    CommandOutputTooLargeError,
    CommandResult,
    CommandTimeoutError,
    DISABLED_WORKSPACE_TOOLS,
    OuroborosBackendConfig,
    OuroborosContractError,
    OuroborosIdempotencyConflict,
    OuroborosNotConfiguredError,
    OuroborosTaskBackend,
)


BASE = "a" * 40
HEAD = "b" * 40
REVIEW_ID = "review-1"
REVIEW_DIGEST = "rvw_" + "c" * 64
TASK_DIGEST = "tsk_" + "d" * 64
TASK_ID = "task-1"
MODEL_ID = "deepseek/deepseek-v4-pro"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _command(stdout: str = "", *, returncode: int = 0, stderr: str = "") -> CommandResult:
    return CommandResult(
        argv=("ouroboros",),
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.01,
    )


class QueueRunner:
    def __init__(self, responses: Sequence[CommandResult | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[tuple[str, ...], float]] = []
        self._lock = threading.Lock()

    def run(self, argv: Sequence[str], *, timeout: float) -> CommandResult:
        with self._lock:
            self.calls.append((tuple(argv), timeout))
            if not self.responses:
                raise AssertionError(f"unexpected CLI call: {argv!r}")
            response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return CommandResult(
            argv=tuple(argv),
            returncode=response.returncode,
            stdout=response.stdout,
            stderr=response.stderr,
            duration_seconds=response.duration_seconds,
        )


def _final(*, blocker: bool = False, incomplete: bool = False) -> dict[str, Any]:
    if incomplete:
        status = "incomplete"
        verdict = "incomplete"
        completed = ["PRIN-004", "PRIN-005", "PRIN-006"]
        missing = ["PRIN-007"]
    else:
        status = "completed"
        verdict = "request_changes_escalate" if blocker else "approve"
        completed = ["PRIN-004", "PRIN-005", "PRIN-006", "PRIN-007"]
        missing = []
    return {
        "schema": "aga.final-review/v1",
        "status": status,
        "review_id": REVIEW_ID,
        "review_digest": REVIEW_DIGEST,
        "task_digest": TASK_DIGEST,
        "review_provenance_json": "{}",
        "findings": [],
        "observations": [],
        "completed_rule_ids": completed,
        "missing_rule_ids": missing,
        "analysis_errors": [],
        "verdict": verdict,
        "escalate": blocker or incomplete,
        "human_review_required": blocker or incomplete,
        "auto_merge": False,
        "incomplete": incomplete,
    }


def _prepare_args() -> dict[str, str]:
    return {
        "repository_id": "ga-case",
        "base": BASE,
        "head": HEAD,
        "review_id": REVIEW_ID,
    }


def _receipts(final: dict[str, Any]) -> list[dict[str, Any]]:
    review_id_hash = hashlib.sha256(REVIEW_ID.encode("utf-8")).hexdigest()
    return [
        {
            "tool": "aga_prepare_review",
            "args_sha256": hashlib.sha256(
                _canonical_bytes(_prepare_args())
            ).hexdigest(),
            "status": "ok",
            "output_status": "ready",
            "output_incomplete": False,
            "output_sha256": "e" * 64,
            "review_id_sha256": review_id_hash,
            "review_digest": REVIEW_DIGEST,
            "task_digest": TASK_DIGEST,
        },
        {
            "tool": "aga_finalize_review",
            "args_sha256": "f" * 64,
            "status": "ok" if not final["incomplete"] else "incomplete",
            "output_status": final["status"],
            "output_incomplete": final["incomplete"],
            "output_sha256": hashlib.sha256(_canonical_bytes(final)).hexdigest(),
            "review_id_sha256": review_id_hash,
            "review_digest": REVIEW_DIGEST,
            "task_digest": TASK_DIGEST,
        },
    ]


def _tool_logs(*, duplicate_finalize: bool = False) -> dict[str, Any]:
    entries: list[dict[str, Any]] = [
        {
            "tool": "mcp_aga__aga_prepare_review",
            "task_id": TASK_ID,
            "tool_call_id": "call-prepare",
            "args": _prepare_args(),
            "status": "ok",
            "is_error": False,
        },
        {
            "tool": "mcp_aga__aga_seaf_lookup",
            "task_id": TASK_ID,
            "tool_call_id": "call-lookup",
            "args": {
                "review_id": REVIEW_ID,
                "review_digest": REVIEW_DIGEST,
                "entity_id": "AS.TEST",
            },
            "status": "ok",
            "is_error": False,
        },
        {
            "tool": "mcp_aga__aga_finalize_review",
            "task_id": TASK_ID,
            "tool_call_id": "call-finalize",
            "args": {
                "review_id": REVIEW_ID,
                "review_digest": REVIEW_DIGEST,
                "task_digest": TASK_DIGEST,
                "semantic_result": {},
            },
            "status": "ok",
            "is_error": False,
        },
    ]
    if duplicate_finalize:
        second_finalize = dict(entries[-1])
        second_finalize["tool_call_id"] = "call-finalize-2"
        entries.append(second_finalize)
    return {"name": "tools", "entries": entries}


def _event_logs(*, model: str = MODEL_ID, provider: str = "openrouter") -> dict[str, Any]:
    return {
        "name": "events",
        "entries": [
            {
                "type": "llm_usage",
                "task_id": TASK_ID,
                "root_task_id": TASK_ID,
                "parent_task_id": "",
                "requested_model_lane": "auto",
                "effective_model_lane": "main",
                "category": "task",
                "model": model,
                "api_key_type": "openrouter",
                "model_category": "main",
                "provider": provider,
                "source": "loop",
                "cost": 0.001,
                "cost_known": True,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cached_tokens": 0,
                "cache_write_tokens": 0,
                "accounting_authority": "physical_attempt_ledger",
                "projection_update_status": "available",
                "ledger_attempt_ids": ["attempt-1"],
            }
        ],
    }


def _external(final: dict[str, Any]) -> dict[str, Any]:
    request = _payload()
    request["idempotency_key"] = request["review_id"]
    project_id = "aga-" + hashlib.sha256(_canonical_bytes(request)).hexdigest()[:32]
    prompt = f"Review ga-case {BASE} {HEAD} {REVIEW_ID} synthetic-public"
    return {
        "task_id": TASK_ID,
        "project_id": project_id,
        "status": "completed",
        "result": json.dumps(final, ensure_ascii=False, sort_keys=True),
        "artifact_status": "ready_no_changes",
        "cost_accounting_status": "available",
        "cost_final": True,
        "ledger_integrity_degraded": False,
        "unresolved_upper_bound_usd": 0.0,
        "unknown_unmetered": 0,
        "cost_usd": 0.001,
        "total_rounds": 1,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "artifact_bundle": {
            "schema_version": 1,
            "status": "ready_no_changes",
            "artifacts": [],
            "errors": [],
        },
        "outcome_axes": {
            "lifecycle": {"status": "completed"},
            "execution": {"status": "ok"},
            "artifacts": {"status": "ready_no_changes"},
            "objective": {"status": "not_evaluated"},
        },
        "task_contract": {
            "allowed_resources": {"network": True, "web": False},
            "disabled_tools": list(DISABLED_WORKSPACE_TOOLS),
        },
        "metadata": {
            "aga_review_id": REVIEW_ID,
            "aga_idempotency_key": REVIEW_ID,
            "aga_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "data_classification": "synthetic-public",
            "expected_model_id": MODEL_ID,
            "allowed_resources": {"network": True, "web": False},
            "disabled_tools": list(DISABLED_WORKSPACE_TOOLS),
        },
    }


def _payload(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "repository_id": "ga-case",
        "base": BASE,
        "head": HEAD,
        "review_id": REVIEW_ID,
        "data_classification": "synthetic-public",
    }
    value.update(changes)
    return value


def _backend(
    tmp_path: Path,
    runner: QueueRunner,
    receipts: list[dict[str, Any]] | None = None,
    initial_tasks: list[dict[str, Any]] | None = None,
    **config_changes: Any,
) -> OuroborosTaskBackend:
    runner.responses.insert(
        0,
        _command(
            json.dumps({"tasks": list(initial_tasks or []), "queue": {}})
        ),
    )
    prompt = (
        "Review {{REPOSITORY_ID}} {{BASE_REVISION}} {{HEAD_REVISION}} "
        "{{REVIEW_ID}} {{DATA_CLASSIFICATION}}"
    )
    config = OuroborosBackendConfig(
        model_id=MODEL_ID,
        workspaces={"ga-case": tmp_path},
        prompt_template=prompt,
        task_timeout_seconds=10,
        command_timeout_seconds=2,
        poll_interval_seconds=0.01,
        receipt_source=lambda: tuple(receipts or ()),
        **config_changes,
    )
    return OuroborosTaskBackend(config, runner=runner)


def _successful_backend(
    tmp_path: Path, *, blocker: bool = False
) -> tuple[OuroborosTaskBackend, QueueRunner, dict[str, Any]]:
    final = _final(blocker=blocker)
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(_tool_logs())),
            _command(json.dumps(_event_logs())),
        ]
    )
    return _backend(tmp_path, runner, _receipts(final)), runner, final


def test_success_requires_exact_attested_aga_final(tmp_path: Path) -> None:
    backend, runner, final = _successful_backend(tmp_path)
    task_id = backend.schedule_task("aga:review", _payload())
    result = backend.get_task_result(task_id)

    assert result.status is TaskStatus.SUCCEEDED
    assert result.metadata["aga_final"] == final
    assert result.metadata["verdict"] == "approve"
    assert result.metadata["auto_merge"] is False
    assert result.metadata["model"]["name"] == MODEL_ID
    assert result.metadata["model_usage"]["model"] == MODEL_ID
    assert result.metadata["model_usage"]["accounting_authority"] == (
        "terminal_task_ledger"
    )
    schedule_argv = next(argv for argv, _timeout in runner.calls if "run" in argv)
    assert schedule_argv[:3] == ("ouroboros", "run", "--detach")
    assert "--memory-mode" in schedule_argv
    assert schedule_argv[schedule_argv.index("--memory-mode") + 1] == "empty"
    assert str(tmp_path) in schedule_argv
    assert "--disable-tools" in schedule_argv


def test_identical_mirrored_tool_logs_are_deduplicated(tmp_path: Path) -> None:
    final = _final()
    logs = _tool_logs()
    logs["entries"] = [
        duplicate
        for entry in logs["entries"]
        for duplicate in (entry, dict(entry, _source_root="mirror"))
    ]
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(logs)),
            _command(json.dumps(_event_logs())),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.SUCCEEDED


def test_conflicting_mirrored_tool_logs_fail_closed(tmp_path: Path) -> None:
    final = _final()
    logs = _tool_logs()
    conflict = dict(logs["entries"][0], status="error", is_error=True)
    logs["entries"].insert(1, conflict)
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(logs)),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "invalid_aga_receipt"


def test_blocker_is_successful_review_but_forces_hitl(tmp_path: Path) -> None:
    backend, _runner, _final_value = _successful_backend(tmp_path, blocker=True)
    result = backend.wait_for_task(
        backend.schedule_task("aga:review", _payload()), timeout=1
    )
    assert result.status is TaskStatus.SUCCEEDED
    assert result.metadata["verdict"] == "request_changes_escalate"
    assert result.metadata["human_review_required"] is True
    assert result.metadata["auto_merge"] is False


def test_unattested_model_answer_fails_closed(tmp_path: Path) -> None:
    trusted = _final()
    untrusted = dict(trusted, verdict="approve_with_warnings")
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(untrusted))),
            _command(json.dumps(_tool_logs())),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(trusted))
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "invalid_aga_receipt"


def test_public_result_must_be_string_and_carry_exact_policy_contract(
    tmp_path: Path,
) -> None:
    for mutate in (
        lambda external, final: external.__setitem__("result", final),
        lambda external, _final: external["task_contract"].__setitem__(
            "disabled_tools", []
        ),
        lambda external, _final: external.pop("artifact_bundle"),
        lambda external, _final: external.pop("outcome_axes"),
    ):
        final = _final()
        external = _external(final)
        mutate(external, final)
        runner = QueueRunner(
            [
                _command(TASK_ID + "\n"),
                _command(json.dumps(external)),
                _command(json.dumps(_tool_logs())),
                _command(json.dumps(_event_logs())),
            ]
        )
        backend = _backend(tmp_path, runner, _receipts(final))
        result = backend.get_task_result(
            backend.schedule_task("aga:review", _payload())
        )
        assert result.status is TaskStatus.FAILED
        assert result.metadata["verdict"] == "incomplete"


@pytest.mark.parametrize(
    ("external_status", "expected_code"),
    [
        ("failed", "external_failed"),
        ("cancelled", "external_cancelled"),
        ("mystery", "unknown_external_status"),
    ],
)
def test_terminal_failure_cancel_and_unknown_status_fail_closed(
    tmp_path: Path, external_status: str, expected_code: str
) -> None:
    external = _external(_final())
    external["status"] = external_status
    external["error"] = external_status
    runner = QueueRunner(
        [_command(TASK_ID + "\n"), _command(json.dumps(external))]
    )
    backend = _backend(tmp_path, runner)
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == expected_code
    assert result.metadata["verdict"] == "incomplete"
    assert result.metadata["incomplete"] is True
    assert result.metadata["human_review_required"] is True
    assert result.metadata["auto_merge"] is False
    assert "provider" not in result.metadata
    assert "model" not in result.metadata


def test_malformed_task_json_fails_closed(tmp_path: Path) -> None:
    runner = QueueRunner([_command(TASK_ID + "\n"), _command("{not-json")])
    backend = _backend(tmp_path, runner)
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "cli_error"


def test_cli_missing_task_is_typed_failure(tmp_path: Path) -> None:
    runner = QueueRunner(
        [_command(TASK_ID + "\n"), _command(returncode=2, stderr="HTTP 404")]
    )
    backend = _backend(tmp_path, runner)
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "cli_error"


def test_missing_or_duplicate_finalize_fails_closed(tmp_path: Path) -> None:
    for logs in (
        {"name": "tools", "entries": _tool_logs()["entries"][:-1]},
        _tool_logs(duplicate_finalize=True),
    ):
        final = _final()
        runner = QueueRunner(
            [
                _command(TASK_ID + "\n"),
                _command(json.dumps(_external(final))),
                _command(json.dumps(logs)),
            ]
        )
        backend = _backend(tmp_path, runner, _receipts(final))
        result = backend.get_task_result(
            backend.schedule_task("aga:review", _payload())
        )
        assert result.status is TaskStatus.FAILED
        assert result.metadata["error_code"] == "invalid_aga_receipt"


def test_any_non_aga_tool_call_invalidates_the_run(tmp_path: Path) -> None:
    final = _final()
    logs = _tool_logs()
    logs["entries"].insert(
        1,
        {
            "tool": "run_command",
            "task_id": TASK_ID,
            "tool_call_id": "call-shell",
            "args": {"command": "true"},
            "status": "ok",
            "is_error": False,
        },
    )
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(logs)),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "invalid_aga_receipt"


def test_incomplete_aga_output_never_becomes_success(tmp_path: Path) -> None:
    final = _final(incomplete=True)
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(_tool_logs())),
            _command(json.dumps(_event_logs())),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "aga_incomplete"
    assert result.metadata["aga_final"] == final
    assert result.metadata["tool_names"] == [
        "aga_prepare_review",
        "aga_seaf_lookup",
        "aga_finalize_review",
    ]
    assert result.metadata["prepare_output_sha256"] == "e" * 64
    assert result.metadata["final_output_sha256"] == hashlib.sha256(
        _canonical_bytes(final)
    ).hexdigest()
    assert result.metadata["model_usage"]["model"] == MODEL_ID
    assert result.metadata["human_review_required"] is True
    assert result.metadata["auto_merge"] is False


def test_receipt_source_exception_is_typed_failure(tmp_path: Path) -> None:
    final = _final()
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(_tool_logs())),
        ]
    )
    backend = _backend(tmp_path, runner)

    def unavailable_receipts() -> Sequence[dict[str, Any]]:
        raise OSError("private receipt path")

    object.__setattr__(backend.config, "receipt_source", unavailable_receipts)
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "invalid_aga_receipt"
    assert "private receipt path" not in (result.error or "")


def test_timeout_cancels_once_and_freezes_result(tmp_path: Path) -> None:
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps({"ok": True, "task_id": TASK_ID})),
        ]
    )
    backend = _backend(tmp_path, runner)
    task_id = backend.schedule_task("aga:review", _payload())
    first = backend.wait_for_task(task_id, timeout=0)
    second = backend.get_task_result(task_id)
    assert first.status is TaskStatus.TIMED_OUT
    assert second is first
    assert first.metadata["verdict"] == "incomplete"
    assert first.metadata["human_review_required"] is True
    assert first.metadata["auto_merge"] is False
    assert first.metadata["cancel_attempted"] is True
    assert first.metadata["cancel_confirmed"] is True
    cancel_calls = [call for call, _ in runner.calls if "cancel" in call]
    assert len(cancel_calls) == 1
    cancel_timeouts = [
        timeout for call, timeout in runner.calls if "cancel" in call
    ]
    assert cancel_timeouts == [backend.config.command_timeout_seconds]
    assert not any("show" in call for call, _timeout in runner.calls)


@pytest.mark.parametrize(
    "cancel_response",
    [
        _command(
            json.dumps({"ok": True, "task_id": TASK_ID}),
            returncode=1,
        ),
        _command(json.dumps({"ok": False, "task_id": TASK_ID})),
        _command(json.dumps({"ok": True, "task_id": "different-task"})),
        CommandTimeoutError("cancel deadline"),
    ],
)
def test_timeout_does_not_claim_unconfirmed_cancellation(
    tmp_path: Path,
    cancel_response: CommandResult | BaseException,
) -> None:
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            cancel_response,
        ]
    )
    backend = _backend(tmp_path, runner)
    task_id = backend.schedule_task("aga:review", _payload())

    result = backend.wait_for_task(task_id, timeout=0)

    assert result.status is TaskStatus.TIMED_OUT
    assert result.metadata["cancel_attempted"] is True
    assert result.metadata["cancel_confirmed"] is False
    assert len([call for call, _ in runner.calls if "cancel" in call]) == 1


def test_completed_task_waits_for_artifact_finalization(tmp_path: Path) -> None:
    final = _final()
    finalizing = _external(final)
    finalizing["artifact_status"] = "finalizing"
    finalizing["artifact_bundle"]["status"] = "finalizing"
    finalizing["outcome_axes"]["artifacts"]["status"] = "finalizing"
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(finalizing)),
            _command(json.dumps(_external(final))),
            _command(json.dumps(_tool_logs())),
            _command(json.dumps(_event_logs())),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    task_id = backend.schedule_task("aga:review", _payload())
    assert backend.get_task_result(task_id).status is TaskStatus.PENDING
    assert backend.get_task_result(task_id).status is TaskStatus.SUCCEEDED


def test_actual_model_fallback_is_rejected(tmp_path: Path) -> None:
    final = _final()
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(_tool_logs())),
            _command(json.dumps(_event_logs(model="unapproved/model"))),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "invalid_aga_receipt"


def test_skeletal_usage_route_is_rejected(tmp_path: Path) -> None:
    final = _final()
    usage = {"type": "llm_usage", "task_id": TASK_ID, "model": MODEL_ID}
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(_tool_logs())),
            _command(json.dumps({"name": "events", "entries": [usage]})),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(
        backend.schedule_task("aga:review", _payload())
    )
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "invalid_aga_receipt"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cost_accounting_status", "unavailable"),
        ("cost_final", False),
        ("ledger_integrity_degraded", True),
        ("unresolved_upper_bound_usd", 0.01),
        ("unknown_unmetered", 1),
        ("total_rounds", 2),
    ],
)
def test_non_authoritative_terminal_cost_evidence_is_rejected(
    tmp_path: Path, field: str, value: Any
) -> None:
    final = _final()
    external = _external(final)
    external[field] = value
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(external)),
            _command(json.dumps(_tool_logs())),
            _command(json.dumps(_event_logs())),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(
        backend.schedule_task("aga:review", _payload())
    )
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "invalid_aga_receipt"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cost_usd", -0.001),
        ("total_rounds", 0),
        ("prompt_tokens", -1),
        ("completion_tokens", True),
    ],
)
def test_invalid_terminal_cost_totals_are_rejected(
    tmp_path: Path, field: str, value: Any
) -> None:
    final = _final()
    external = _external(final)
    external[field] = value
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(external)),
            _command(json.dumps(_tool_logs())),
            _command(json.dumps(_event_logs())),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(
        backend.schedule_task("aga:review", _payload())
    )
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "invalid_aga_receipt"


def test_terminal_ledger_wins_over_retry_event_projection(tmp_path: Path) -> None:
    final = _final()
    external = _external(final)
    external.update(
        cost_usd=0.007,
        total_rounds=2,
        prompt_tokens=275,
        completion_tokens=48,
    )
    usage = dict(
        _event_logs()["entries"][0],
        cost=0.001,
        prompt_tokens=100,
        completion_tokens=20,
        ledger_attempt_ids=["attempt-1", "attempt-2"],
    )
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(external)),
            _command(json.dumps(_tool_logs())),
            _command(json.dumps({"name": "events", "entries": [usage]})),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(
        backend.schedule_task("aga:review", _payload())
    )

    assert result.status is TaskStatus.SUCCEEDED
    model_usage = result.metadata["model_usage"]
    assert model_usage["call_count"] == 2
    assert model_usage["known_cost_usd"] == 0.007
    assert model_usage["prompt_tokens"] == 275
    assert model_usage["completion_tokens"] == 48
    assert "cached_tokens" not in model_usage
    assert "cache_write_tokens" not in model_usage


def test_mirrored_physical_usage_is_counted_once(tmp_path: Path) -> None:
    final = _final()
    usage = _event_logs()["entries"][0]
    runner = QueueRunner(
        [
            _command(TASK_ID + "\n"),
            _command(json.dumps(_external(final))),
            _command(json.dumps(_tool_logs())),
            _command(
                json.dumps(
                    {
                        "name": "events",
                        "entries": [usage, dict(usage, _source_root="mirror")],
                    }
                )
            ),
        ]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.SUCCEEDED
    assert result.metadata["model_usage"]["call_count"] == 1
    assert result.metadata["model_usage"]["known_cost_usd"] == 0.001


def test_workspace_changes_can_never_be_accepted_as_review_success(tmp_path: Path) -> None:
    final = _final()
    changed = _external(final)
    changed["artifact_status"] = "ready_with_changes"
    runner = QueueRunner(
        [_command(TASK_ID + "\n"), _command(json.dumps(changed))]
    )
    backend = _backend(tmp_path, runner, _receipts(final))
    result = backend.get_task_result(backend.schedule_task("aga:review", _payload()))
    assert result.status is TaskStatus.FAILED
    assert result.metadata["error_code"] == "external_objective_failed"


def test_duplicate_retry_is_idempotent_without_second_cli_call(tmp_path: Path) -> None:
    runner = QueueRunner([_command(TASK_ID + "\n")])
    backend = _backend(tmp_path, runner)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(
            pool.map(
                lambda _index: backend.schedule_task("aga:review", _payload()),
                range(2),
            )
        )
    assert ids == [TASK_ID, TASK_ID]
    assert len(runner.calls) == 2
    assert sum("run" in argv for argv, _timeout in runner.calls) == 1


def test_idempotency_key_conflict_is_rejected_before_network(tmp_path: Path) -> None:
    runner = QueueRunner([_command(TASK_ID + "\n")])
    backend = _backend(tmp_path, runner)
    backend.schedule_task("aga:review", _payload())
    with pytest.raises(OuroborosIdempotencyConflict):
        backend.schedule_task(
            "aga:review",
            _payload(head="9" * 40),
        )
    assert len(runner.calls) == 2


def test_idempotency_alias_cannot_bypass_review_binding(tmp_path: Path) -> None:
    runner = QueueRunner([])
    backend = _backend(tmp_path, runner)
    with pytest.raises(OuroborosContractError, match="must equal review_id"):
        backend.schedule_task(
            "aga:review", _payload(idempotency_key="different-key")
        )
    assert runner.calls == []


def test_ambiguous_schedule_is_reconciled_without_duplicate_run(tmp_path: Path) -> None:
    existing = _external(_final())
    runner = QueueRunner(
        [
            CommandTimeoutError("detached response timed out"),
            _command(json.dumps({"tasks": [existing], "queue": {}})),
        ]
    )
    backend = _backend(tmp_path, runner)
    assert backend.schedule_task("aga:review", _payload()) == TASK_ID
    assert sum("run" in argv for argv, _timeout in runner.calls) == 1


def test_unreconcilable_schedule_blocks_blind_retry(tmp_path: Path) -> None:
    runner = QueueRunner(
        [
            CommandTimeoutError("detached response timed out"),
            CommandTimeoutError("reconciliation timed out"),
        ]
    )
    backend = _backend(tmp_path, runner)
    with pytest.raises(CommandTimeoutError):
        backend.schedule_task("aga:review", _payload())
    calls_after_failure = len(runner.calls)
    with pytest.raises(OuroborosContractError, match="blind retry"):
        backend.schedule_task("aga:review", _payload())
    assert len(runner.calls) == calls_after_failure


def test_detach_malformed_output_is_reconciled_without_second_paid_run(
    tmp_path: Path,
) -> None:
    existing = _external(_final())
    runner = QueueRunner(
        [
            _command("not-a-valid-task-id\nextra-line\n"),
            _command(json.dumps({"tasks": [existing], "queue": {}})),
        ]
    )
    backend = _backend(tmp_path, runner)

    assert backend.schedule_task("aga:review", _payload()) == TASK_ID
    assert sum("run" in argv for argv, _timeout in runner.calls) == 1


def test_ambiguous_creation_with_no_ledger_match_poisoned_for_retry(
    tmp_path: Path,
) -> None:
    runner = QueueRunner(
        [
            CommandTimeoutError("detach timed out"),
            _command(json.dumps({"tasks": [], "queue": {}})),
        ]
    )
    backend = _backend(tmp_path, runner)

    with pytest.raises(OuroborosContractError, match="ambiguous"):
        backend.schedule_task("aga:review", _payload())
    calls_after_failure = len(runner.calls)
    with pytest.raises(OuroborosContractError, match="blind retry"):
        backend.schedule_task("aga:review", _payload())
    assert len(runner.calls) == calls_after_failure


def test_fresh_backend_reuses_exact_external_idempotency_binding(
    tmp_path: Path,
) -> None:
    existing = _external(_final())
    runner = QueueRunner([])
    backend = _backend(tmp_path, runner, initial_tasks=[existing])

    assert backend.schedule_task("aga:review", _payload()) == TASK_ID
    assert len(runner.calls) == 1
    assert not any("run" in argv for argv, _timeout in runner.calls)


def test_non_synthetic_classification_is_rejected_before_network(tmp_path: Path) -> None:
    runner = QueueRunner([])
    backend = _backend(tmp_path, runner)
    with pytest.raises(OuroborosContractError, match="synthetic-public"):
        backend.schedule_task(
            "aga:review", _payload(data_classification="private")
        )
    assert runner.calls == []


def test_unknown_task_is_not_polled(tmp_path: Path) -> None:
    backend = _backend(tmp_path, QueueRunner([]))
    with pytest.raises(UnknownTaskError):
        backend.get_task_result("not-scheduled")


def test_missing_model_is_not_configured(tmp_path: Path) -> None:
    with pytest.raises(OuroborosNotConfiguredError, match="model ID"):
        OuroborosTaskBackend(
            OuroborosBackendConfig(
                model_id="",
                workspaces={"ga-case": tmp_path},
                prompt_template="bounded prompt",
            ),
            runner=QueueRunner([]),
        )


def test_remote_or_credentialed_gateway_is_rejected(tmp_path: Path) -> None:
    for gateway in (
        "https://runtime.example.test",
        "http://user:password@127.0.0.1:8765",
        "http://127.0.0.1:8765/api?token=value",
    ):
        with pytest.raises(OuroborosNotConfiguredError, match="loopback"):
            OuroborosTaskBackend(
                OuroborosBackendConfig(
                    gateway_url=gateway,
                    model_id=MODEL_ID,
                    workspaces={"ga-case": tmp_path},
                    prompt_template="bounded prompt",
                ),
                runner=QueueRunner([]),
            )


def test_bounded_runner_kills_oversized_output() -> None:
    runner = BoundedCommandRunner(max_stdout_bytes=128, max_stderr_bytes=128)
    with pytest.raises(CommandOutputTooLargeError):
        runner.run(
            (sys.executable, "-c", "import sys; sys.stdout.write('x' * 4096)"),
            timeout=2,
        )


def test_schedule_error_redacts_openrouter_key_shape(tmp_path: Path) -> None:
    token_shaped_text = "sk-or-v1-" + "x" * 24
    runner = QueueRunner(
        [
            _command(returncode=2, stderr=f"error {token_shaped_text}"),
            _command(json.dumps({"tasks": [], "queue": {}})),
        ]
    )
    backend = _backend(tmp_path, runner)
    with pytest.raises(OuroborosContractError) as caught:
        backend.schedule_task("aga:review", _payload())
    assert token_shaped_text not in str(caught.value)
    assert "ambiguous" in str(caught.value)
