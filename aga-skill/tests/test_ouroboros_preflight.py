# -*- coding: utf-8 -*-
"""Contract and safety tests for the project-owned Ouroboros preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import ouroboros_preflight as preflight  # noqa: E402


SENSITIVE_MARKER = "synthetic-sensitive-marker-must-not-leak"


def _result(value: Any, *, returncode: int = 0) -> preflight.CommandResult:
    return preflight.CommandResult(
        returncode=returncode,
        stdout=json.dumps(value, ensure_ascii=False).encode("utf-8"),
    )


def _tools(*, prefixed: bool) -> list[dict[str, str]]:
    tools = []
    for raw, qualified in zip(
        preflight.MCP_TOOL_NAMES,
        preflight.MCP_PREFIXED_TOOL_NAMES,
        strict=True,
    ):
        item = {"name": raw, "description": "synthetic-public tool"}
        if prefixed:
            item["prefixed_name"] = qualified
        tools.append(item)
    return tools


def _mcp_server_settings(*, url: str = preflight.MCP_URL) -> dict[str, Any]:
    return {
        "id": preflight.MCP_SERVER_ID,
        "name": "AGA Governance",
        "enabled": True,
        "transport": "streamable_http",
        "url": url,
        "auth_header": "Authorization",
        "auth_token": "",
        "auth_configured": False,
        "allowed_tools": list(preflight.MCP_TOOL_NAMES),
    }


def _healthy_responses() -> dict[tuple[str, ...], preflight.CommandResult]:
    test_tools = _tools(prefixed=False)
    registered_tools = _tools(prefixed=True)
    server = _mcp_server_settings()
    return {
        ("status", "--json"): _result(
            {
                "health": {
                    "status": "ok",
                    "version": preflight.PINNED_VERSION,
                    "runtime_version": preflight.PINNED_VERSION,
                    "app_version": preflight.PINNED_VERSION,
                },
                "state": {"supervisor_ready": True},
            }
        ),
        ("settings", "get", "OPENROUTER_API_KEY"): _result(
            SENSITIVE_MARKER[:8] + "..."
        ),
        ("settings", "get", "OPENAI_API_KEY"): _result(""),
        ("settings", "get", "OPENAI_COMPATIBLE_API_KEY"): _result(""),
        ("settings", "get", "CLOUDRU_FOUNDATION_MODELS_API_KEY"): _result(""),
        ("settings", "get", "GIGACHAT_CREDENTIALS"): _result(""),
        ("settings", "get", "GIGACHAT_USER"): _result(""),
        ("settings", "get", "GIGACHAT_PASSWORD"): _result(""),
        ("settings", "get", "ANTHROPIC_API_KEY"): _result(""),
        ("settings", "get", "OUROBOROS_MODEL"): _result(
            preflight.EXPECTED_MODEL
        ),
        ("settings", "get", "OUROBOROS_MODEL_HEAVY"): _result(""),
        ("settings", "get", "OUROBOROS_MODEL_LIGHT"): _result(""),
        ("settings", "get", "OUROBOROS_MODEL_VISION"): _result(""),
        ("settings", "get", "OUROBOROS_MODEL_CONSCIOUSNESS"): _result(""),
        ("settings", "get", "OUROBOROS_MODEL_DEEP_SELF_REVIEW"): _result(
            preflight.EXPECTED_MODEL
        ),
        ("settings", "get", "OUROBOROS_WEBSEARCH_MODEL"): _result(
            preflight.EXPECTED_MODEL
        ),
        ("settings", "get", "OUROBOROS_SCOPE_REVIEW_MODEL"): _result(
            preflight.EXPECTED_MODEL
        ),
        ("settings", "get", "OUROBOROS_REVIEW_MODELS"): _result(
            ",".join([preflight.EXPECTED_MODEL] * 3)
        ),
        ("settings", "get", "OUROBOROS_SCOPE_REVIEW_MODELS"): _result(
            preflight.EXPECTED_MODEL
        ),
        ("settings", "get", "OUROBOROS_MODEL_FALLBACKS"): _result(""),
        ("settings", "get", "USE_LOCAL_MAIN"): _result(False),
        ("settings", "get", "USE_LOCAL_HEAVY"): _result(False),
        ("settings", "get", "USE_LOCAL_LIGHT"): _result(False),
        ("settings", "get", "USE_LOCAL_CONSCIOUSNESS"): _result(False),
        ("settings", "get", "USE_LOCAL_FALLBACK"): _result(False),
        ("settings", "get", "TOTAL_BUDGET"): _result(1.25),
        ("settings", "get", "OUROBOROS_REVIEW_ENFORCEMENT"): _result(
            preflight.EXPECTED_REVIEW_MODE
        ),
        ("settings", "get", "OUROBOROS_TASK_REVIEW_MODE"): _result("off"),
        ("settings", "get", "MCP_ENABLED"): _result(True),
        ("settings", "get", "MCP_SERVERS"): _result([server]),
        ("skills", "list"): _result(
            {
                "skills": [
                    {
                        "name": preflight.SKILL_NAME,
                        "type": "instruction",
                        "version": preflight.SKILL_VERSION,
                        "source": "external",
                        "enabled": True,
                        "review_stale": False,
                        "permissions": [],
                        "load_error": "",
                        "review_gate": {"executable_review": True},
                    }
                ],
                "live": {
                    "tools": [],
                    "routes": [],
                    "ws_handlers": [],
                },
            }
        ),
        ("mcp", "test", "--server-id", "aga"): _result(
            {
                "ok": True,
                "server_id": "aga",
                "tool_count": len(test_tools),
                "tools": test_tools,
            }
        ),
        ("mcp", "refresh", "--server-id", "aga"): _result(
            {
                "ok": True,
                "server_id": "aga",
                "tool_count": len(registered_tools),
                "tools": registered_tools,
            }
        ),
        ("mcp", "status"): _result(
            {
                "enabled": True,
                "sdk_available": True,
                "sdk_error": "",
                "servers": [
                    {
                        **server,
                        "tool_count": len(registered_tools),
                        "tools": registered_tools,
                        "last_error": "",
                    }
                ],
            }
        ),
    }


class FakeRunner:
    def __init__(
        self,
        responses: dict[
            tuple[str, ...],
            preflight.CommandResult | BaseException,
        ],
    ) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: Any) -> preflight.CommandResult:
        key = tuple(arguments)
        self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"unexpected synthetic command: {key!r}")
        response = self.responses[key]
        if isinstance(response, BaseException):
            raise response
        return response


def _run(
    responses: dict[tuple[str, ...], preflight.CommandResult] | None = None,
) -> tuple[dict[str, Any], int, FakeRunner]:
    runner = FakeRunner(responses or _healthy_responses())
    payload, exit_code = preflight.run_preflight(runner)
    return payload, exit_code, runner


def test_preflight_ready_uses_only_readiness_commands_and_sanitizes_output() -> None:
    payload, exit_code, runner = _run()

    assert exit_code == preflight.EXIT_READY
    assert payload["status"] == "ready"
    assert payload["runtime"] == {"version": "6.64.1"}
    assert payload["configuration"] == {
        "provider": "openrouter",
        "credential_present": True,
        "model": "deepseek/deepseek-v4-pro",
        "single_model_routes": True,
        "cross_model_fallback": False,
        "global_hard_cap_present": True,
        "review_mode": "advisory",
    }
    assert payload["mcp"]["tool_count"] == 4
    assert set(payload["mcp"]["tools"]) == set(preflight.MCP_TOOL_NAMES)
    assert runner.calls[-3:] == [
        ("mcp", "test", "--server-id", "aga"),
        ("mcp", "refresh", "--server-id", "aga"),
        ("mcp", "status"),
    ]
    assert all(
        command[0] in {"status", "settings", "skills", "mcp"}
        for command in runner.calls
    )
    serialized = json.dumps(payload)
    assert SENSITIVE_MARKER not in serialized
    assert "sk-or" not in serialized
    assert "/Users/" not in serialized


@pytest.mark.parametrize(
    ("command", "value", "expected_code"),
    [
        (("settings", "get", "OPENROUTER_API_KEY"), "", "openrouter_not_configured"),
        (("settings", "get", "ANTHROPIC_API_KEY"), "masked...", "provider_configuration_not_isolated"),
        (("settings", "get", "OUROBOROS_MODEL"), "private/other-model", "model_not_configured"),
        (("settings", "get", "OUROBOROS_MODEL_HEAVY"), "private/other-model", "model_routes_not_configured"),
        (("settings", "get", "OUROBOROS_REVIEW_MODELS"), "private/other-model", "model_routes_not_configured"),
        (("settings", "get", "OUROBOROS_MODEL_FALLBACKS"), "private/other-model", "fallback_model_not_disabled"),
        (("settings", "get", "TOTAL_BUDGET"), 0, "budget_not_configured"),
        (("settings", "get", "OUROBOROS_REVIEW_ENFORCEMENT"), "blocking", "review_mode_not_configured"),
        (("settings", "get", "OUROBOROS_TASK_REVIEW_MODE"), "auto", "task_review_not_disabled"),
    ],
)
def test_missing_provider_model_budget_or_review_is_typed_and_stops_before_mcp(
    command: tuple[str, ...],
    value: Any,
    expected_code: str,
) -> None:
    responses = _healthy_responses()
    responses[command] = _result(value)
    payload, exit_code, runner = _run(responses)

    assert exit_code == preflight.EXIT_NOT_CONFIGURED
    assert payload["status"] == "not_configured"
    assert payload["code"] == expected_code
    assert not any(call[0] == "mcp" for call in runner.calls)
    serialized = json.dumps(payload)
    assert SENSITIVE_MARKER not in serialized
    assert str(value) not in serialized if value == "private/other-model" else True


def test_runtime_version_mismatch_fails_closed() -> None:
    responses = _healthy_responses()
    responses[("status", "--json")] = _result(
        {
            "health": {
                "status": "ok",
                "version": "6.64.0",
                "runtime_version": "6.64.0",
                "app_version": "6.64.0",
            },
            "state": {"supervisor_ready": True},
        }
    )
    payload, exit_code, runner = _run(responses)

    assert exit_code == preflight.EXIT_FAILED
    assert payload["status"] == "failed"
    assert payload["code"] == "runtime_version_mismatch"
    assert runner.calls == [("status", "--json")]
    assert "6.64.0" not in json.dumps(payload)


def test_non_loopback_mcp_is_rejected_before_probe() -> None:
    responses = _healthy_responses()
    external_url = "https://mcp.example.invalid/mcp"
    responses[("settings", "get", "MCP_SERVERS")] = _result(
        [_mcp_server_settings(url=external_url)]
    )
    payload, exit_code, runner = _run(responses)

    assert exit_code == preflight.EXIT_NOT_CONFIGURED
    assert payload["code"] == "mcp_not_configured"
    assert not any(call[0] == "mcp" for call in runner.calls)
    assert external_url not in json.dumps(payload)


def test_mcp_discovery_requires_exactly_four_expected_tools() -> None:
    responses = _healthy_responses()
    tools = _tools(prefixed=False) + [
        {"name": "unexpected_tool", "description": "synthetic-public"}
    ]
    responses[("mcp", "test", "--server-id", "aga")] = _result(
        {
            "ok": True,
            "server_id": "aga",
            "tool_count": len(tools),
            "tools": tools,
        }
    )
    payload, exit_code, runner = _run(responses)

    assert exit_code == preflight.EXIT_NOT_CONFIGURED
    assert payload["code"] == "mcp_tools_not_ready"
    assert ("mcp", "refresh", "--server-id", "aga") not in runner.calls
    assert "unexpected_tool" not in json.dumps(payload)


def test_live_extension_tools_are_rejected_before_mcp_probe() -> None:
    responses = _healthy_responses()
    responses[("skills", "list")] = _result(
        {
            "skills": _healthy_skills(),
            "live": {
                "tools": ["extension_side_effect"],
                "routes": [],
                "ws_handlers": [],
            },
        }
    )
    payload, exit_code, runner = _run(responses)

    assert exit_code == preflight.EXIT_NOT_CONFIGURED
    assert payload["code"] == "extension_tools_not_isolated"
    assert not any(call[0] == "mcp" for call in runner.calls)
    assert "extension_side_effect" not in json.dumps(payload)


def _healthy_skills() -> list[dict[str, Any]]:
    return json.loads(
        _healthy_responses()[("skills", "list")].stdout.decode("utf-8")
    )["skills"]


def test_aga_instruction_skill_must_be_reviewed_enabled_and_isolated() -> None:
    for skills in (
        [],
        [dict(_healthy_skills()[0], enabled=False)],
        [dict(_healthy_skills()[0], review_stale=True)],
        [
            *_healthy_skills(),
            {
                "name": "other_external",
                "source": "external",
                "enabled": True,
            },
        ],
    ):
        responses = _healthy_responses()
        extension_payload = json.loads(
            responses[("skills", "list")].stdout.decode("utf-8")
        )
        extension_payload["skills"] = skills
        responses[("skills", "list")] = _result(extension_payload)
        payload, exit_code, runner = _run(responses)

        assert exit_code == preflight.EXIT_NOT_CONFIGURED
        assert payload["code"] in {
            "aga_skill_not_ready",
            "skill_configuration_not_isolated",
        }
        assert not any(call[0] == "mcp" for call in runner.calls)


def test_malformed_or_failed_cli_output_is_never_echoed() -> None:
    responses = _healthy_responses()
    raw_marker = b"raw-private-cli-output " + SENSITIVE_MARKER.encode("ascii")
    responses[("status", "--json")] = preflight.CommandResult(0, raw_marker)
    payload, exit_code, _ = _run(responses)

    assert exit_code == preflight.EXIT_FAILED
    assert payload["code"] == "malformed_cli_output"
    serialized = json.dumps(payload)
    assert SENSITIVE_MARKER not in serialized
    assert "raw-private-cli-output" not in serialized

    responses = _healthy_responses()
    responses[("mcp", "test", "--server-id", "aga")] = preflight.CommandResult(
        2,
        raw_marker,
    )
    payload, exit_code, _ = _run(responses)
    assert exit_code == preflight.EXIT_NOT_CONFIGURED
    assert payload["code"] == "mcp_not_ready"
    assert SENSITIVE_MARKER not in json.dumps(payload)


def test_main_without_runtime_emits_one_typed_sanitized_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(preflight, "_find_executable", lambda _explicit="": None)

    assert preflight.main() == preflight.EXIT_NOT_CONFIGURED
    captured = capsys.readouterr()
    assert captured.err == ""
    lines = captured.out.splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["status"] == "not_configured"
    assert payload["code"] == "runtime_not_installed"
    assert "/" not in payload["code"]


def test_bounded_runner_does_not_use_a_shell_and_strips_sensitive_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", SENSITIVE_MARKER)
    monkeypatch.setenv("OUROBOROS_URL", "https://external.example.invalid")
    monkeypatch.setenv("PYTHONPATH", "/private/synthetic/path")
    seen: dict[str, Any] = {}
    real_popen = subprocess.Popen

    def recording_popen(*args: Any, **kwargs: Any) -> Any:
        seen["command"] = args[0]
        seen["shell"] = kwargs.get("shell")
        seen["env"] = kwargs.get("env")
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(preflight.subprocess, "Popen", recording_popen)
    runner = preflight.BoundedCommandRunner(sys.executable, timeout_seconds=2)
    result = runner.run(("-c", "import sys; sys.stdout.write('{}')"))

    assert result.returncode == 0
    assert result.stdout == b"{}"
    assert isinstance(seen["command"], list)
    assert seen["shell"] is False
    assert "OPENROUTER_API_KEY" not in seen["env"]
    assert "OUROBOROS_URL" not in seen["env"]
    assert "PYTHONPATH" not in seen["env"]
    assert seen["env"]["NO_PROXY"] == "127.0.0.1,localhost,::1"


def test_bounded_runner_targets_the_explicit_loopback_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    real_popen = subprocess.Popen

    def recording_popen(*args: Any, **kwargs: Any) -> Any:
        seen["command"] = args[0]
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(preflight.subprocess, "Popen", recording_popen)
    runner = preflight.BoundedCommandRunner(
        (sys.executable,),
        gateway_url="http://127.0.0.1:9876",
        timeout_seconds=2,
    )
    result = runner.run(("-c", "import sys; sys.stdout.write('{}')"))

    assert result.returncode == 2
    assert seen["command"][:3] == [
        sys.executable,
        "--url",
        "http://127.0.0.1:9876",
    ]


def test_remote_gateway_is_rejected_without_starting_a_command() -> None:
    with pytest.raises(ValueError, match="loopback"):
        preflight.BoundedCommandRunner(
            sys.executable,
            gateway_url="https://runtime.example.invalid",
        )


def test_bounded_runner_rejects_oversized_output() -> None:
    runner = preflight.BoundedCommandRunner(
        sys.executable,
        timeout_seconds=2,
        stdout_limit_bytes=128,
        stderr_limit_bytes=128,
    )
    with pytest.raises(preflight.CommandOutputLimit):
        runner.run(("-c", "import os; os.write(1, b'x' * 4096)"))


def test_bounded_runner_terminates_on_timeout() -> None:
    runner = preflight.BoundedCommandRunner(
        sys.executable,
        timeout_seconds=0.05,
        stdout_limit_bytes=128,
        stderr_limit_bytes=128,
    )
    with pytest.raises(preflight.CommandTimeout):
        runner.run(("-c", "import time; time.sleep(5)"))


def test_runner_timeout_maps_to_sanitized_failed_status() -> None:
    responses = _healthy_responses()
    runner = FakeRunner(
        {
            **responses,
            ("status", "--json"): preflight.CommandTimeout("private timeout detail"),
        }
    )
    payload, exit_code = preflight.run_preflight(runner)

    assert exit_code == preflight.EXIT_FAILED
    assert payload["code"] == "command_timeout"
    assert "private timeout detail" not in json.dumps(payload)


def test_unexpected_runner_error_is_sanitized() -> None:
    responses = _healthy_responses()
    runner = FakeRunner(
        {
            **responses,
            ("status", "--json"): RuntimeError(
                "private /absolute/path and secret detail"
            ),
        }
    )
    payload, exit_code = preflight.run_preflight(runner)

    assert exit_code == preflight.EXIT_FAILED
    assert payload["code"] == "internal_preflight_error"
    serialized = json.dumps(payload)
    assert "/absolute/path" not in serialized
    assert "secret detail" not in serialized
