#!/usr/bin/env python3
"""Fail-closed, offline-safe readiness check for the pinned Ouroboros runtime.

The check talks only to the already-running local Ouroboros gateway through the
official CLI.  It never starts a task, invokes a model, persists CLI responses,
or includes raw command output in its result.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlsplit


SCHEMA = "aga.ouroboros-preflight/v1"
PINNED_VERSION = "6.64.1"
PINNED_SOURCE_COMMIT = "554b3eeeca345298d6dcc5711195ea9acec450bd"
EXPECTED_PROVIDER = "openrouter"
EXPECTED_MODEL = "deepseek/deepseek-v4-pro"
EXPECTED_REVIEW_MODE = "advisory"
MAX_BUDGET_USD = 50.0
MCP_SERVER_ID = "aga"
MCP_URL = "http://127.0.0.1:8788/mcp"
SKILL_NAME = "aga_review"
SKILL_VERSION = "1.0.0"
MCP_TOOL_NAMES = (
    "aga_prepare_review",
    "aga_seaf_lookup",
    "aga_parse_diagram",
    "aga_finalize_review",
)
MCP_PREFIXED_TOOL_NAMES = tuple(
    f"mcp_{MCP_SERVER_ID}__{name}" for name in MCP_TOOL_NAMES
)
OVERLAY_ATTESTATION_SCHEMA = "aga.ouroboros-runtime-overlay/v3"
PROFILE_PID_SCHEMA = "aga.ouroboros-profile-pid/v1"
OVERLAY_ATTESTATION_FILENAME = "aga-runtime-overlay.json"
PROFILE_PID_FILENAME = "aga-profile-runtime.json"
RUNTIME_OVERLAY_LAUNCHER = Path(__file__).resolve().with_name(
    "ouroboros_runtime_overlay.py"
)
RUNTIME_OVERLAY_BOOTSTRAP = (
    Path(__file__).resolve().parent
    / "ouroboros_overlay_bootstrap"
    / "sitecustomize.py"
)

EXIT_READY = 0
EXIT_NOT_CONFIGURED = 2
EXIT_FAILED = 3

DEFAULT_COMMAND_TIMEOUT_SECONDS = 60.0
DEFAULT_STDOUT_LIMIT_BYTES = 256 * 1024
DEFAULT_STDERR_LIMIT_BYTES = 64 * 1024


class CommandTimeout(RuntimeError):
    """A bounded CLI command exceeded its deadline."""


class CommandOutputLimit(RuntimeError):
    """A bounded CLI command exceeded its output allowance."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes


@dataclass(frozen=True)
class RuntimeOverlayPaths:
    attestation_path: Path
    pid_path: Path
    launcher_path: Path
    bootstrap_path: Path

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "RuntimeOverlayPaths":
        source = os.environ if environment is None else environment
        raw_home = str(source.get("HOME") or "").strip()
        if not raw_home:
            _fail_not_configured("runtime_overlay_not_active")
        home = Path(raw_home)
        if not home.is_absolute():
            _fail_contract("runtime_overlay_attestation_mismatch")
        state_dir = home / "Ouroboros" / "data" / "state"
        return cls(
            attestation_path=state_dir / OVERLAY_ATTESTATION_FILENAME,
            pid_path=state_dir / PROFILE_PID_FILENAME,
            launcher_path=RUNTIME_OVERLAY_LAUNCHER,
            bootstrap_path=RUNTIME_OVERLAY_BOOTSTRAP,
        )


class CommandRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> CommandResult: ...


class BoundedCommandRunner:
    """Run one fixed executable without a shell and with strict resource bounds."""

    def __init__(
        self,
        executable: str | Sequence[str],
        *,
        gateway_url: str = "",
        timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        stdout_limit_bytes: int = DEFAULT_STDOUT_LIMIT_BYTES,
        stderr_limit_bytes: int = DEFAULT_STDERR_LIMIT_BYTES,
    ) -> None:
        command_prefix = (
            (executable,) if isinstance(executable, str) else tuple(executable)
        )
        if not command_prefix or any(
            not isinstance(item, str) or not item for item in command_prefix
        ):
            raise ValueError("executable command prefix is required")
        if gateway_url and not _safe_gateway_url(gateway_url):
            raise ValueError("gateway URL must be credential-free loopback")
        if timeout_seconds <= 0 or stdout_limit_bytes <= 0 or stderr_limit_bytes <= 0:
            raise ValueError("command bounds must be positive")
        self._command_prefix = command_prefix
        self._gateway_url = gateway_url
        self._timeout_seconds = float(timeout_seconds)
        self._stdout_limit_bytes = int(stdout_limit_bytes)
        self._stderr_limit_bytes = int(stderr_limit_bytes)

    @staticmethod
    def _environment() -> dict[str, str]:
        # In particular, do not inherit provider credentials, proxy routing,
        # PYTHONPATH, OUROBOROS_URL, or alternate settings/data paths.  The
        # packaged CLI can still find its normal local install via HOME/PATH.
        allowed = (
            "PATH",
            "HOME",
            "TMPDIR",
            "XDG_CACHE_HOME",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "SYSTEMROOT",
            "WINDIR",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
        )
        environment = {
            key: os.environ[key] for key in allowed if os.environ.get(key)
        }
        environment.setdefault("PATH", os.defpath)
        environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
        environment["no_proxy"] = "127.0.0.1,localhost,::1"
        return environment

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover - exercised on Windows only
                process.kill()
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass

    def run(self, arguments: Sequence[str]) -> CommandResult:
        if not all(isinstance(item, str) for item in arguments):
            raise TypeError("CLI arguments must be strings")

        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": self._environment(),
            "shell": False,
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True
        command = list(self._command_prefix)
        if self._gateway_url:
            command.extend(("--url", self._gateway_url))
        command.extend(arguments)
        process: subprocess.Popen[bytes] = subprocess.Popen(
            command,
            **popen_kwargs,
        )
        stdout = bytearray()
        overflow = threading.Event()
        reader_failed = threading.Event()

        def read_stream(
            stream: Any,
            *,
            limit: int,
            destination: bytearray | None,
        ) -> None:
            count = 0
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        return
                    count += len(chunk)
                    if count > limit:
                        overflow.set()
                        self._kill(process)
                        return
                    if destination is not None:
                        destination.extend(chunk)
            except BaseException:  # pragma: no cover - defensive OS boundary
                reader_failed.set()
                self._kill(process)

        assert process.stdout is not None
        assert process.stderr is not None
        readers = (
            threading.Thread(
                target=read_stream,
                kwargs={
                    "stream": process.stdout,
                    "limit": self._stdout_limit_bytes,
                    "destination": stdout,
                },
                name="aga-ouroboros-preflight-stdout",
                daemon=True,
            ),
            threading.Thread(
                target=read_stream,
                kwargs={
                    "stream": process.stderr,
                    "limit": self._stderr_limit_bytes,
                    "destination": None,
                },
                name="aga-ouroboros-preflight-stderr",
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()

        def close_streams() -> None:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

        try:
            returncode = process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            self._kill(process)
            process.wait()
            for reader in readers:
                reader.join(timeout=1.0)
            close_streams()
            raise CommandTimeout("bounded command timed out") from exc

        for reader in readers:
            reader.join(timeout=1.0)
        close_streams()
        if any(reader.is_alive() for reader in readers):
            self._kill(process)
            raise CommandTimeout("bounded output reader did not finish")
        if overflow.is_set():
            raise CommandOutputLimit("bounded command output exceeded limit")
        if reader_failed.is_set():
            raise OSError("bounded command output reader failed")
        return CommandResult(returncode=returncode, stdout=bytes(stdout))


@dataclass(frozen=True)
class PreflightFailure(Exception):
    status: str
    code: str


def _expected_payload() -> dict[str, Any]:
    return {
        "runtime_version": PINNED_VERSION,
        "runtime_source_commit": PINNED_SOURCE_COMMIT,
        "provider": EXPECTED_PROVIDER,
        "model": EXPECTED_MODEL,
        "review_mode": EXPECTED_REVIEW_MODE,
        "mcp_server_id": MCP_SERVER_ID,
        "mcp_tool_count": len(MCP_TOOL_NAMES),
    }


def _failure_payload(failure: PreflightFailure) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": failure.status,
        "code": failure.code,
        "expected": _expected_payload(),
    }


def _fail_not_configured(code: str) -> None:
    raise PreflightFailure("not_configured", code)


def _fail_contract(code: str) -> None:
    raise PreflightFailure("failed", code)


def _read_private_overlay_json(path: Path) -> Mapping[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        _fail_not_configured("runtime_overlay_not_active")
    except OSError:
        _fail_contract("runtime_overlay_attestation_mismatch")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size <= 0
        or metadata.st_size > 16 * 1024
    ):
        _fail_contract("runtime_overlay_attestation_mismatch")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        _fail_contract("runtime_overlay_attestation_mismatch")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _fail_contract("runtime_overlay_attestation_mismatch")
    if not isinstance(payload, Mapping):
        _fail_contract("runtime_overlay_attestation_mismatch")
    return payload


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _runtime_process_command(pid: int) -> str:
    if os.name != "posix":  # pragma: no cover - current pinned runtime is POSIX
        return ""
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.is_file():
        try:
            return proc_cmdline.read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except OSError:
            return ""
    environment = {"PATH": os.defpath}
    for key in ("LANG", "LC_ALL", "LC_CTYPE"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    try:
        result = subprocess.run(
            ("ps", "-ww", "-p", str(pid), "-o", "command="),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 64 * 1024:
        return ""
    return result.stdout.strip()


def _validate_live_runtime_overlay(
    paths: RuntimeOverlayPaths | None = None,
) -> None:
    """Verify the live, project-owned route overlay without exposing its paths."""

    overlay_paths = RuntimeOverlayPaths.from_environment() if paths is None else paths
    state_dir = overlay_paths.attestation_path.parent
    try:
        state_metadata = state_dir.lstat()
    except FileNotFoundError:
        _fail_not_configured("runtime_overlay_not_active")
    except OSError:
        _fail_contract("runtime_overlay_attestation_mismatch")
    if (
        stat.S_ISLNK(state_metadata.st_mode)
        or not stat.S_ISDIR(state_metadata.st_mode)
        or stat.S_IMODE(state_metadata.st_mode) != 0o700
    ):
        _fail_contract("runtime_overlay_attestation_mismatch")
    if hasattr(os, "getuid") and state_metadata.st_uid != os.getuid():
        _fail_contract("runtime_overlay_attestation_mismatch")

    attestation = _read_private_overlay_json(overlay_paths.attestation_path)
    pid_record = _read_private_overlay_json(overlay_paths.pid_path)
    try:
        launcher_metadata = overlay_paths.launcher_path.lstat()
        launcher_bytes = overlay_paths.launcher_path.read_bytes()
        bootstrap_metadata = overlay_paths.bootstrap_path.lstat()
        bootstrap_bytes = overlay_paths.bootstrap_path.read_bytes()
    except OSError:
        _fail_contract("runtime_overlay_attestation_mismatch")
    if stat.S_ISLNK(launcher_metadata.st_mode) or not stat.S_ISREG(
        launcher_metadata.st_mode
    ):
        _fail_contract("runtime_overlay_attestation_mismatch")
    if stat.S_ISLNK(bootstrap_metadata.st_mode) or not stat.S_ISREG(
        bootstrap_metadata.st_mode
    ):
        _fail_contract("runtime_overlay_attestation_mismatch")
    launcher_sha256 = hashlib.sha256(launcher_bytes).hexdigest()
    bootstrap_sha256 = hashlib.sha256(bootstrap_bytes).hexdigest()

    pid = attestation.get("pid")
    expected_attestation = {
        "schema": OVERLAY_ATTESTATION_SCHEMA,
        "pid": pid,
        "runtime_version": PINNED_VERSION,
        "source_commit": PINNED_SOURCE_COMMIT,
        "source_clean": True,
        "model": EXPECTED_MODEL,
        "consolidation_model": EXPECTED_MODEL,
        "launcher_sha256": launcher_sha256,
        "spawn_bootstrap": True,
        "bootstrap_mode": "deferred_runtime_import_hooks",
        "bootstrap_sha256": bootstrap_sha256,
        "finalize_transport_retry": "exception_group_once",
        "aga_post_task_policy": "skip_synthetic_public_memory_synthesis",
    }
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 1
        or dict(attestation) != expected_attestation
        or pid_record.get("schema") != PROFILE_PID_SCHEMA
        or pid_record.get("pid") != pid
    ):
        _fail_contract("runtime_overlay_attestation_mismatch")
    if not _pid_alive(pid):
        _fail_not_configured("runtime_overlay_not_active")
    command = _runtime_process_command(pid)
    if (
        not command
        or str(overlay_paths.launcher_path) not in command
        or "--source-dir" not in command
        or "server" not in command
    ):
        _fail_contract("runtime_overlay_attestation_mismatch")


def _json_command(
    runner: CommandRunner,
    arguments: tuple[str, ...],
    *,
    unavailable_code: str,
) -> Any:
    try:
        result = runner.run(arguments)
    except CommandTimeout:
        _fail_contract("command_timeout")
    except CommandOutputLimit:
        _fail_contract("command_output_limit")
    except OSError:
        _fail_not_configured(unavailable_code)
    if result.returncode != 0:
        _fail_not_configured(unavailable_code)
    try:
        text = result.stdout.decode("utf-8", errors="strict")
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail_contract("malformed_cli_output")


def _settings_value(runner: CommandRunner, key: str) -> Any:
    return _json_command(
        runner,
        ("settings", "get", key),
        unavailable_code="settings_unavailable",
    )


def _require_mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail_contract(code)
    return value


def _validate_runtime(runner: CommandRunner) -> None:
    payload = _require_mapping(
        _json_command(
            runner,
            ("status", "--json"),
            unavailable_code="runtime_unavailable",
        ),
        "runtime_contract_mismatch",
    )
    health = _require_mapping(payload.get("health"), "runtime_contract_mismatch")
    state = _require_mapping(payload.get("state"), "runtime_contract_mismatch")
    if health.get("status") != "ok":
        _fail_not_configured("runtime_unavailable")
    versions = (
        health.get("version"),
        health.get("runtime_version"),
        health.get("app_version"),
    )
    if any(not isinstance(value, str) for value in versions):
        _fail_contract("runtime_contract_mismatch")
    if any(value != PINNED_VERSION for value in versions):
        _fail_contract("runtime_version_mismatch")
    if state.get("supervisor_ready") is not True:
        _fail_not_configured("runtime_not_ready")


def _positive_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _validate_configuration(runner: CommandRunner) -> Mapping[str, Any]:
    credential = _settings_value(runner, "OPENROUTER_API_KEY")
    if not isinstance(credential, str):
        _fail_contract("settings_contract_mismatch")
    if not credential.strip():
        _fail_not_configured("openrouter_not_configured")
    if not (
        credential == "***"
        or (len(credential) == 11 and credential.endswith("..."))
    ):
        _fail_contract("credential_masking_contract_mismatch")
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_COMPATIBLE_API_KEY",
        "CLOUDRU_FOUNDATION_MODELS_API_KEY",
        "GIGACHAT_CREDENTIALS",
        "GIGACHAT_USER",
        "GIGACHAT_PASSWORD",
        "ANTHROPIC_API_KEY",
    ):
        other_credential = _settings_value(runner, key)
        if not isinstance(other_credential, str):
            _fail_contract("settings_contract_mismatch")
        if other_credential.strip():
            _fail_not_configured("provider_configuration_not_isolated")

    model = _settings_value(runner, "OUROBOROS_MODEL")
    if not isinstance(model, str):
        _fail_contract("settings_contract_mismatch")
    if model.strip() != EXPECTED_MODEL:
        _fail_not_configured("model_not_configured")
    for key in (
        "OUROBOROS_MODEL_HEAVY",
        "OUROBOROS_MODEL_LIGHT",
        "OUROBOROS_MODEL_VISION",
        "OUROBOROS_MODEL_CONSCIOUSNESS",
    ):
        routed_model = _settings_value(runner, key)
        if not isinstance(routed_model, str):
            _fail_contract("settings_contract_mismatch")
        if routed_model.strip() not in {"", EXPECTED_MODEL}:
            _fail_not_configured("model_routes_not_configured")
    for key in (
        "OUROBOROS_MODEL_DEEP_SELF_REVIEW",
        "OUROBOROS_WEBSEARCH_MODEL",
        "OUROBOROS_SCOPE_REVIEW_MODEL",
    ):
        routed_model = _settings_value(runner, key)
        if not isinstance(routed_model, str):
            _fail_contract("settings_contract_mismatch")
        if routed_model.strip() != EXPECTED_MODEL:
            _fail_not_configured("model_routes_not_configured")
    for key in ("OUROBOROS_REVIEW_MODELS", "OUROBOROS_SCOPE_REVIEW_MODELS"):
        raw_models = _settings_value(runner, key)
        if not isinstance(raw_models, str):
            _fail_contract("settings_contract_mismatch")
        models = [item.strip() for item in raw_models.split(",") if item.strip()]
        if not models or any(item != EXPECTED_MODEL for item in models):
            _fail_not_configured("model_routes_not_configured")
    fallbacks = _settings_value(runner, "OUROBOROS_MODEL_FALLBACKS")
    if not isinstance(fallbacks, str):
        _fail_contract("settings_contract_mismatch")
    if fallbacks.strip():
        _fail_not_configured("fallback_model_not_disabled")
    for key in (
        "USE_LOCAL_MAIN",
        "USE_LOCAL_HEAVY",
        "USE_LOCAL_LIGHT",
        "USE_LOCAL_CONSCIOUSNESS",
        "USE_LOCAL_FALLBACK",
    ):
        use_local = _settings_value(runner, key)
        if use_local not in {False, 0, "", "false", "False"}:
            _fail_not_configured("openrouter_route_not_configured")

    budget = _settings_value(runner, "TOTAL_BUDGET")
    if not _positive_finite_number(budget):
        _fail_not_configured("budget_not_configured")
    if float(budget) > MAX_BUDGET_USD:
        _fail_not_configured("budget_exceeds_owner_limit")

    review_mode = _settings_value(runner, "OUROBOROS_REVIEW_ENFORCEMENT")
    if not isinstance(review_mode, str):
        _fail_contract("settings_contract_mismatch")
    if review_mode.strip().lower() != EXPECTED_REVIEW_MODE:
        _fail_not_configured("review_mode_not_configured")
    task_review_mode = _settings_value(runner, "OUROBOROS_TASK_REVIEW_MODE")
    if not isinstance(task_review_mode, str):
        _fail_contract("settings_contract_mismatch")
    if task_review_mode.strip().lower() != "off":
        _fail_not_configured("task_review_not_disabled")

    mcp_enabled = _settings_value(runner, "MCP_ENABLED")
    if mcp_enabled is not True:
        _fail_not_configured("mcp_not_configured")
    servers = _settings_value(runner, "MCP_SERVERS")
    return _validate_mcp_settings(servers)


def _safe_mcp_url(value: Any) -> bool:
    if not isinstance(value, str) or value != MCP_URL:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and port == 8788
        and parsed.path == "/mcp"
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _safe_gateway_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        loopback = hostname.lower() == "localhost" or ipaddress.ip_address(
            hostname
        ).is_loopback
    except (ValueError, TypeError):
        return False
    return (
        parsed.scheme in {"http", "https"}
        and loopback
        and parsed.port is not None
        and parsed.path in {"", "/"}
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _validate_mcp_settings(value: Any) -> Mapping[str, Any]:
    if value is None or value == []:
        _fail_not_configured("mcp_not_configured")
    if not isinstance(value, list):
        _fail_contract("settings_contract_mismatch")
    if len(value) != 1:
        _fail_not_configured("mcp_configuration_not_isolated")
    matches = [
        entry
        for entry in value
        if isinstance(entry, Mapping) and entry.get("id") == MCP_SERVER_ID
    ]
    if not matches:
        _fail_not_configured("mcp_not_configured")
    if len(matches) != 1:
        _fail_contract("mcp_configuration_invalid")
    server = matches[0]
    allowed_tools = server.get("allowed_tools")
    if not isinstance(allowed_tools, list) or not all(
        isinstance(name, str) for name in allowed_tools
    ):
        _fail_not_configured("mcp_not_configured")
    if len(allowed_tools) != len(MCP_TOOL_NAMES) or set(allowed_tools) != set(
        MCP_TOOL_NAMES
    ):
        _fail_not_configured("mcp_not_configured")
    if (
        server.get("enabled") is not True
        or server.get("transport") != "streamable_http"
        or not _safe_mcp_url(server.get("url"))
        or bool(server.get("auth_configured"))
        or bool(server.get("auth_token"))
    ):
        _fail_not_configured("mcp_not_configured")
    return server


def _names_from_tools(
    payload: Mapping[str, Any],
    *,
    include_prefixed: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tools = payload.get("tools")
    tool_count = payload.get("tool_count")
    if isinstance(tool_count, bool) or not isinstance(tool_count, int):
        _fail_contract("mcp_contract_mismatch")
    if not isinstance(tools, list) or tool_count != len(tools):
        _fail_contract("mcp_contract_mismatch")
    raw_names: list[str] = []
    prefixed_names: list[str] = []
    for tool in tools:
        if not isinstance(tool, Mapping) or not isinstance(tool.get("name"), str):
            _fail_contract("mcp_contract_mismatch")
        raw_names.append(tool["name"])
        if include_prefixed:
            prefixed = tool.get("prefixed_name")
            if not isinstance(prefixed, str):
                _fail_contract("mcp_contract_mismatch")
            prefixed_names.append(prefixed)
    return tuple(raw_names), tuple(prefixed_names)


def _require_exact_tools(
    payload: Mapping[str, Any],
    *,
    include_prefixed: bool,
) -> None:
    raw_names, prefixed_names = _names_from_tools(
        payload,
        include_prefixed=include_prefixed,
    )
    if len(set(raw_names)) != len(raw_names) or set(raw_names) != set(MCP_TOOL_NAMES):
        _fail_not_configured("mcp_tools_not_ready")
    if include_prefixed and (
        len(set(prefixed_names)) != len(prefixed_names)
        or set(prefixed_names) != set(MCP_PREFIXED_TOOL_NAMES)
    ):
        _fail_not_configured("mcp_tools_not_ready")


def _validate_probe(payload: Any, *, include_prefixed: bool) -> None:
    probe = _require_mapping(payload, "mcp_contract_mismatch")
    if probe.get("ok") is not True:
        _fail_not_configured("mcp_not_ready")
    if probe.get("server_id") != MCP_SERVER_ID:
        _fail_contract("mcp_contract_mismatch")
    _require_exact_tools(probe, include_prefixed=include_prefixed)


def _validate_mcp_status(payload: Any) -> None:
    status = _require_mapping(payload, "mcp_contract_mismatch")
    if status.get("enabled") is not True or status.get("sdk_available") is not True:
        _fail_not_configured("mcp_not_ready")
    servers = status.get("servers")
    if not isinstance(servers, list):
        _fail_contract("mcp_contract_mismatch")
    if len(servers) != 1:
        _fail_not_configured("mcp_configuration_not_isolated")
    matches = [
        entry
        for entry in servers
        if isinstance(entry, Mapping) and entry.get("id") == MCP_SERVER_ID
    ]
    if len(matches) != 1:
        _fail_not_configured("mcp_not_ready")
    server = matches[0]
    if (
        server.get("enabled") is not True
        or server.get("transport") != "streamable_http"
        or not _safe_mcp_url(server.get("url"))
        or bool(server.get("auth_configured"))
        or bool(server.get("last_error"))
    ):
        _fail_not_configured("mcp_not_ready")
    allowed_tools = server.get("allowed_tools")
    if (
        not isinstance(allowed_tools, list)
        or len(allowed_tools) != len(MCP_TOOL_NAMES)
        or set(allowed_tools) != set(MCP_TOOL_NAMES)
    ):
        _fail_not_configured("mcp_not_ready")
    _require_exact_tools(server, include_prefixed=True)


def _validate_mcp(runner: CommandRunner) -> None:
    test_payload = _json_command(
        runner,
        ("mcp", "test", "--server-id", MCP_SERVER_ID),
        unavailable_code="mcp_not_ready",
    )
    _validate_probe(test_payload, include_prefixed=False)

    refresh_payload = _json_command(
        runner,
        ("mcp", "refresh", "--server-id", MCP_SERVER_ID),
        unavailable_code="mcp_not_ready",
    )
    _validate_probe(refresh_payload, include_prefixed=True)

    status_payload = _json_command(
        runner,
        ("mcp", "status"),
        unavailable_code="mcp_not_ready",
    )
    _validate_mcp_status(status_payload)


def _validate_extension_isolation(runner: CommandRunner) -> None:
    payload = _require_mapping(
        _json_command(
            runner,
            ("skills", "list"),
            unavailable_code="extensions_unavailable",
        ),
        "extensions_contract_mismatch",
    )
    live = _require_mapping(payload.get("live"), "extensions_contract_mismatch")
    skills = payload.get("skills")
    if not isinstance(skills, list) or not all(
        isinstance(item, Mapping) for item in skills
    ):
        _fail_contract("extensions_contract_mismatch")
    matches = [item for item in skills if item.get("name") == SKILL_NAME]
    if len(matches) != 1:
        _fail_not_configured("aga_skill_not_ready")
    skill = matches[0]
    review_gate = skill.get("review_gate")
    if (
        skill.get("type") != "instruction"
        or skill.get("version") != SKILL_VERSION
        or skill.get("source") != "external"
        or skill.get("enabled") is not True
        or skill.get("review_stale") is not False
        or skill.get("permissions") != []
        or bool(skill.get("load_error"))
        or not isinstance(review_gate, Mapping)
        or review_gate.get("executable_review") is not True
    ):
        _fail_not_configured("aga_skill_not_ready")
    other_enabled_external = [
        item
        for item in skills
        if item.get("name") != SKILL_NAME
        and item.get("source") != "native"
        and item.get("enabled") is True
    ]
    if other_enabled_external:
        _fail_not_configured("skill_configuration_not_isolated")
    tools = live.get("tools")
    if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
        _fail_contract("extensions_contract_mismatch")
    if tools:
        _fail_not_configured("extension_tools_not_isolated")


def _ready_payload() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "ready",
        "code": "ok",
        "all_model_routes_pinned": True,
        "runtime": {
            "version": PINNED_VERSION,
            "source_commit": PINNED_SOURCE_COMMIT,
            "overlay": {
                "active": True,
                "consolidation_model": EXPECTED_MODEL,
                "spawn_workers_pinned": True,
                "bootstrap_mode": "deferred_runtime_import_hooks",
                "finalize_transport_retry": "exception_group_once",
                "aga_post_task_policy": "skip_synthetic_public_memory_synthesis",
            },
        },
        "configuration": {
            "provider": EXPECTED_PROVIDER,
            "credential_present": True,
            "model": EXPECTED_MODEL,
            "single_model_routes": True,
            "cross_model_fallback": False,
            "global_hard_cap_present": True,
            "global_hard_cap_max_usd": MAX_BUDGET_USD,
            "review_mode": EXPECTED_REVIEW_MODE,
        },
        "mcp": {
            "server_id": MCP_SERVER_ID,
            "transport": "streamable_http",
            "loopback": True,
            "tool_count": len(MCP_TOOL_NAMES),
            "tools": list(MCP_TOOL_NAMES),
            "prefixed_tools": list(MCP_PREFIXED_TOOL_NAMES),
        },
        "skill": {
            "name": SKILL_NAME,
            "version": SKILL_VERSION,
            "reviewed": True,
            "enabled": True,
        },
        "extensions": {"live_tool_count": 0},
    }


def run_preflight(
    runner: CommandRunner,
    *,
    overlay_validator: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], int]:
    """Execute the read-only checks and return only a sanitized result."""

    try:
        _validate_runtime(runner)
        validator = _validate_live_runtime_overlay if overlay_validator is None else overlay_validator
        validator()
        _validate_configuration(runner)
        _validate_extension_isolation(runner)
        _validate_mcp(runner)
    except PreflightFailure as failure:
        exit_code = (
            EXIT_NOT_CONFIGURED
            if failure.status == "not_configured"
            else EXIT_FAILED
        )
        return _failure_payload(failure), exit_code
    except Exception:
        # Never let an implementation or OS detail escape into evidence/stdout.
        failure = PreflightFailure("failed", "internal_preflight_error")
        return _failure_payload(failure), EXIT_FAILED
    return _ready_payload(), EXIT_READY


def _find_executable(explicit: str = "") -> str | None:
    candidate = explicit.strip() or "ouroboros"
    found = shutil.which(candidate)
    if not found and ("/" in candidate or "\\" in candidate):
        found = candidate
    if not found:
        return None
    try:
        path = Path(found).resolve(strict=True)
    except OSError:
        return None
    if not path.is_file() or not os.access(path, os.X_OK):
        return None
    return str(path)


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ouroboros-bin", default="")
    parser.add_argument("--gateway-url", default="")
    args = parser.parse_args(argv)
    if args.gateway_url and not _safe_gateway_url(args.gateway_url):
        failure = PreflightFailure("not_configured", "gateway_not_isolated")
        _emit(_failure_payload(failure))
        return EXIT_NOT_CONFIGURED
    executable = _find_executable(args.ouroboros_bin)
    if executable is None:
        failure = PreflightFailure("not_configured", "runtime_not_installed")
        _emit(_failure_payload(failure))
        return EXIT_NOT_CONFIGURED
    runner = BoundedCommandRunner(executable, gateway_url=args.gateway_url)
    payload, exit_code = run_preflight(runner)
    _emit(payload)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
