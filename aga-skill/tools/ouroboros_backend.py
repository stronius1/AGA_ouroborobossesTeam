# -*- coding: utf-8 -*-
"""Fail-closed adapter for the packaged Ouroboros v6.64.1 CLI.

The adapter intentionally imports no Ouroboros Python modules.  It treats the
packaged CLI/gateway as an external runtime, verifies its public task/tool-log
contract, and accepts a completed review only when the exact final JSON is
attested by a trusted AGA MCP receipt hash.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from tools.a2a import (
    TaskBackend,
    TaskResult,
    TaskStatus,
    UnknownTaskError,
)
from tools.mcp_server import SchemaViolation, validate_json_schema
from tools.review_service import TOOL_DEFINITIONS


TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
REVISION_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
SECRET_RE = re.compile(
    r"(?i)(?:sk-or-v1-|sk-|ghp_|github_pat_|Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"
)
EXPECTED_TOOLS = (
    "aga_prepare_review",
    "aga_seaf_lookup",
    "aga_parse_diagram",
    "aga_finalize_review",
)
# Pinned v6.64.1 ``_WORKSPACE_ALLOWED_TOOLS``.  The review obtains all evidence
# through AGA, so withholding every native workspace capability is both safer
# and simpler than trying to distinguish reads from command/write side effects.
DISABLED_WORKSPACE_TOOLS = (
    "read_file",
    "list_files",
    "write_file",
    "edit_text",
    "claude_code_edit",
    "search_code",
    "query_code",
    "run_command",
    "run_script",
    "verify_and_record",
    "start_service",
    "service_status",
    "service_logs",
    "stop_service",
    "vcs_status",
    "vcs_diff",
    "chat_history",
    "recent_tasks",
    "plan_task",
    "task_acceptance_review",
    "schedule_subagent",
    "wait_task",
    "wait_tasks",
    "get_task_result",
    "peek_task",
    "cancel_task",
    "discard_child_result",
    "override_delegation_constraint",
    "integrate_subagent_patch",
    "compare_subagent_patches",
    "knowledge_read",
    "knowledge_list",
    "knowledge_write",
    "journal_read",
    "journal_write",
    "workpad_read",
    "workpad_write",
    "tree_note",
    "tree_read",
    "web_search",
    "browse_page",
    "browser_action",
    "analyze_screenshot",
    "vlm_query",
    "view_image",
    "ocr_pdf",
    "youtube_transcript",
    "extract_video_frames",
    "list_available_tools",
    "enable_tools",
)
PENDING_STATUSES = frozenset({"requested", "scheduled", "running"})
FAILED_STATUSES = frozenset(
    {
        "failed",
        "cancelled",
        "cancel_requested",
        "rejected_duplicate",
        "interrupted",
    }
)
BAD_ARTIFACT_STATUSES = frozenset(
    {"failed", "pending", "finalizing", "missing"}
)


class OuroborosBackendError(RuntimeError):
    """Base error for configuration and external CLI contract failures."""


class OuroborosNotConfiguredError(OuroborosBackendError):
    """The pinned runtime or a required trusted input is unavailable."""


class OuroborosContractError(OuroborosBackendError, ValueError):
    """The runtime returned malformed, unknown or uncorrelated data."""


class OuroborosIdempotencyConflict(OuroborosContractError):
    """One logical review key was reused with different immutable inputs."""


class CommandTimeoutError(OuroborosBackendError):
    """A CLI subprocess exceeded its local command deadline."""


class CommandOutputTooLargeError(OuroborosBackendError):
    """A CLI subprocess exceeded the configured output bound."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class CommandRunner(Protocol):
    def run(self, argv: Sequence[str], *, timeout: float) -> CommandResult:
        ...


class BoundedCommandRunner:
    """Run argv without a shell while bounding both pipes during execution."""

    def __init__(
        self,
        *,
        max_stdout_bytes: int = 1_048_576,
        max_stderr_bytes: int = 262_144,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if max_stdout_bytes <= 0 or max_stderr_bytes <= 0:
            raise ValueError("command output limits must be positive")
        self.max_stdout_bytes = int(max_stdout_bytes)
        self.max_stderr_bytes = int(max_stderr_bytes)
        if environment is None:
            allowed = (
                "HOME",
                "PATH",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
                "TMPDIR",
                "XDG_CONFIG_HOME",
                "XDG_DATA_HOME",
            )
            environment = {
                key: os.environ[key] for key in allowed if key in os.environ
            }
        self.environment = dict(environment)

    def run(self, argv: Sequence[str], *, timeout: float) -> CommandResult:
        safe_argv = tuple(str(item) for item in argv)
        if not safe_argv or any("\x00" in item for item in safe_argv):
            raise ValueError("command argv must contain non-NUL strings")
        if timeout <= 0:
            raise ValueError("command timeout must be positive")
        started = time.monotonic()
        try:
            process = subprocess.Popen(  # noqa: S603 - trusted argv, shell disabled
                list(safe_argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=self.environment,
            )
        except FileNotFoundError as exc:
            raise OuroborosNotConfiguredError(
                "Ouroboros CLI binary is not installed"
            ) from exc
        except OSError as exc:
            raise OuroborosNotConfiguredError(
                "Ouroboros CLI could not be started"
            ) from exc

        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        overflow = threading.Event()

        def read_pipe(name: str, stream: Any, limit: int) -> None:
            try:
                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        return
                    remaining = limit - len(buffers[name])
                    if remaining > 0:
                        buffers[name].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        assert process.stdout is not None and process.stderr is not None
        threads = (
            threading.Thread(
                target=read_pipe,
                args=("stdout", process.stdout, self.max_stdout_bytes),
                daemon=True,
            ),
            threading.Thread(
                target=read_pipe,
                args=("stderr", process.stderr, self.max_stderr_bytes),
                daemon=True,
            ),
        )
        for thread in threads:
            thread.start()

        deadline = started + float(timeout)
        timed_out = False
        while process.poll() is None:
            if overflow.is_set():
                process.kill()
                break
            if time.monotonic() >= deadline:
                timed_out = True
                process.kill()
                break
            time.sleep(0.01)
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
        for thread in threads:
            thread.join(timeout=2.0)

        elapsed = time.monotonic() - started
        if timed_out:
            raise CommandTimeoutError(
                f"CLI command exceeded {timeout:g} seconds"
            )
        if overflow.is_set():
            raise CommandOutputTooLargeError("CLI command output exceeded its bound")
        return CommandResult(
            argv=safe_argv,
            returncode=int(process.returncode or 0),
            stdout=bytes(buffers["stdout"]).decode("utf-8", errors="replace"),
            stderr=bytes(buffers["stderr"]).decode("utf-8", errors="replace"),
            duration_seconds=elapsed,
        )


ReceiptSource = Callable[[], Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class OuroborosBackendConfig:
    command_prefix: tuple[str, ...] = ("ouroboros",)
    gateway_url: str = ""
    runtime_version: str = "6.64.1"
    model_id: str = ""
    workspaces: Mapping[str, Path | str] | None = None
    prompt_path: Path | str | None = None
    prompt_template: str = ""
    task_timeout_seconds: float = 600.0
    finalization_grace_seconds: float = 125.0
    command_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 1.0
    max_json_bytes: int = 1_048_576
    server_id: str = "aga"
    receipt_source: ReceiptSource | None = None


@dataclass
class _BackendTask:
    task_id: str
    request: dict[str, Any]
    fingerprint: str
    project_id: str
    prompt_sha256: str
    created_at: float
    frozen_result: TaskResult | None = None
    cancel_attempted: bool = False
    cancel_confirmed: bool = False


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_json(text: str, context: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON number: {value}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise OuroborosContractError(f"{context} is not strict JSON") from exc


def _redact(value: Any, *, limit: int = 1000) -> str:
    text = SECRET_RE.sub("***REDACTED***", str(value or ""))
    return text[:limit]


def _tool_definition(name: str) -> Mapping[str, Any]:
    return next(item for item in TOOL_DEFINITIONS if item["name"] == name)


class OuroborosTaskBackend(TaskBackend):
    """Typed whole-review task backend for Ouroboros v6.64.1."""

    def __init__(
        self,
        config: OuroborosBackendConfig,
        *,
        runner: CommandRunner | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not config.command_prefix or any(
            not isinstance(item, str) or not item for item in config.command_prefix
        ):
            raise ValueError("command_prefix must contain executable argv strings")
        if config.runtime_version != "6.64.1":
            raise ValueError("this dialect is pinned to Ouroboros 6.64.1")
        if config.gateway_url:
            parsed_gateway = urlsplit(config.gateway_url)
            hostname = parsed_gateway.hostname or ""
            try:
                loopback = hostname.lower() == "localhost" or ipaddress.ip_address(
                    hostname
                ).is_loopback
            except ValueError:
                loopback = False
            if (
                parsed_gateway.scheme not in {"http", "https"}
                or not loopback
                or parsed_gateway.username is not None
                or parsed_gateway.password is not None
                or parsed_gateway.query
                or parsed_gateway.fragment
                or parsed_gateway.path not in {"", "/"}
            ):
                raise OuroborosNotConfiguredError(
                    "Ouroboros gateway must be a credential-free loopback URL"
                )
        if not isinstance(config.model_id, str) or not config.model_id.strip():
            raise OuroborosNotConfiguredError("OpenRouter model ID is not configured")
        if not ID_RE.fullmatch(config.server_id):
            raise ValueError("server_id must be a non-path identifier")
        if (
            config.task_timeout_seconds <= 0
            or config.finalization_grace_seconds < 0
            or config.finalization_grace_seconds > 305
            or config.command_timeout_seconds <= 0
            or config.poll_interval_seconds <= 0
            or config.max_json_bytes <= 0
        ):
            raise ValueError(
                "timeouts/JSON bounds must be positive and finalization grace in [0, 305]"
            )
        raw_workspaces = dict(config.workspaces or {})
        if not raw_workspaces:
            raise OuroborosNotConfiguredError("no trusted workspaces are registered")
        workspaces: dict[str, Path] = {}
        for repository_id, raw_path in raw_workspaces.items():
            if not isinstance(repository_id, str) or not ID_RE.fullmatch(repository_id):
                raise ValueError("workspace keys must be non-path repository IDs")
            path = Path(raw_path).expanduser().resolve(strict=True)
            if not path.is_dir():
                raise ValueError("registered workspace must be a directory")
            workspaces[repository_id] = path

        if config.prompt_template and config.prompt_path is not None:
            raise ValueError("configure prompt_template or prompt_path, not both")
        if config.prompt_path is not None:
            prompt_template = Path(config.prompt_path).read_text(encoding="utf-8")
        else:
            prompt_template = config.prompt_template
        if not prompt_template.strip():
            raise OuroborosNotConfiguredError("versioned orchestration prompt is absent")

        self.config = config
        self._workspaces = workspaces
        self._prompt_template = prompt_template
        self._runner = runner or BoundedCommandRunner()
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.RLock()
        self._schedule_lock = threading.Lock()
        self._tasks: dict[str, _BackendTask] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._ambiguous_idempotency: dict[str, str] = {}

    def _argv(self, *parts: str) -> list[str]:
        argv = list(self.config.command_prefix)
        if self.config.gateway_url:
            argv.extend(("--url", self.config.gateway_url))
        argv.extend(parts)
        return argv

    def _run(self, *parts: str, timeout: float | None = None) -> CommandResult:
        return self._runner.run(
            self._argv(*parts),
            timeout=float(
                self.config.command_timeout_seconds if timeout is None else timeout
            ),
        )

    def _normalise_request(
        self, task_name: str, payload: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        if task_name != "aga:review":
            raise OuroborosContractError("only the whole AGA review task is supported")
        if not isinstance(payload, Mapping):
            raise OuroborosContractError("review payload must be an object")
        allowed = {
            "repository_id",
            "base",
            "head",
            "review_id",
            "data_classification",
            "idempotency_key",
        }
        extra = sorted(set(payload) - allowed)
        if extra:
            raise OuroborosContractError(
                f"review payload has unknown fields: {', '.join(extra)}"
            )
        repository_id = payload.get("repository_id")
        review_id = payload.get("review_id")
        if not isinstance(repository_id, str) or not ID_RE.fullmatch(repository_id):
            raise OuroborosContractError("repository_id is invalid")
        if repository_id not in self._workspaces:
            raise OuroborosNotConfiguredError("repository_id is not registered")
        if not isinstance(review_id, str) or not ID_RE.fullmatch(review_id):
            raise OuroborosContractError("review_id is invalid")
        revisions: dict[str, str] = {}
        for field in ("base", "head"):
            value = payload.get(field)
            if not isinstance(value, str) or not REVISION_RE.fullmatch(value):
                raise OuroborosContractError(f"{field} must be a full Git SHA")
            revisions[field] = value.lower()
        if payload.get("data_classification") != "synthetic-public":
            raise OuroborosContractError(
                "only synthetic-public data is permitted for this backend"
            )
        idempotency = payload.get("idempotency_key", review_id)
        if not isinstance(idempotency, str) or not ID_RE.fullmatch(idempotency):
            raise OuroborosContractError("idempotency_key is invalid")
        if idempotency != review_id:
            raise OuroborosContractError(
                "idempotency_key must equal review_id for one logical finalize"
            )
        return {
            "repository_id": repository_id,
            "base": revisions["base"],
            "head": revisions["head"],
            "review_id": review_id,
            "data_classification": "synthetic-public",
            "idempotency_key": idempotency,
        }

    def _prompt(self, request: Mapping[str, Any]) -> str:
        replacements = {
            "{{REPOSITORY_ID}}": request["repository_id"],
            "{{BASE_REVISION}}": request["base"],
            "{{HEAD_REVISION}}": request["head"],
            "{{REVIEW_ID}}": request["review_id"],
            "{{DATA_CLASSIFICATION}}": request["data_classification"],
        }
        prompt = self._prompt_template
        for marker, value in replacements.items():
            prompt = prompt.replace(marker, str(value))
        if any(marker in prompt for marker in replacements):
            raise OuroborosContractError("orchestration prompt has unresolved markers")
        return prompt

    @staticmethod
    def _project_id(request: Mapping[str, Any]) -> str:
        # Ouroboros explicit project IDs are lowercase filesystem identifiers
        # of at most 64 chars.  A per-review digest avoids both invalid AGA IDs
        # and cross-review project-facts contamination.
        return "aga-" + hashlib.sha256(_canonical_bytes(request)).hexdigest()[:32]

    def schedule_task(
        self, task_name: str, payload: Mapping[str, Any] | None = None
    ) -> str:
        # Serialize creation so concurrent retries cannot spend two provider
        # tasks before the idempotency binding becomes visible.
        with self._schedule_lock:
            return self._schedule_task_locked(task_name, payload)

    def _schedule_task_locked(
        self, task_name: str, payload: Mapping[str, Any] | None = None
    ) -> str:
        request = self._normalise_request(task_name, payload)
        fingerprint = hashlib.sha256(_canonical_bytes(request)).hexdigest()
        idem = request["idempotency_key"]
        with self._lock:
            ambiguous = self._ambiguous_idempotency.get(idem)
            if ambiguous is not None:
                if ambiguous != fingerprint:
                    raise OuroborosIdempotencyConflict(
                        "ambiguous idempotency key is bound to different inputs"
                    )
                raise OuroborosContractError(
                    "previous schedule outcome is ambiguous; blind retry is blocked"
                )
            existing = self._idempotency.get(idem)
            if existing is not None:
                existing_fingerprint, task_id = existing
                if existing_fingerprint != fingerprint:
                    raise OuroborosIdempotencyConflict(
                        "idempotency key is bound to different immutable inputs"
                    )
                return task_id

        prompt = self._prompt(request)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        metadata_values = {
            "aga_review_id": request["review_id"],
            "aga_idempotency_key": idem,
            "aga_prompt_sha256": prompt_sha256,
            "data_classification": "synthetic-public",
            "expected_model_id": self.config.model_id,
            "allowed_resources": {"network": True, "web": False},
            "disabled_tools": list(DISABLED_WORKSPACE_TOOLS),
        }
        metadata = json.dumps(
            metadata_values,
            sort_keys=True,
            separators=(",", ":"),
        )
        workspace = self._workspaces[request["repository_id"]]
        project_id = self._project_id(request)
        # Reconcile before spending anything.  This is required after a caller
        # restart, where the in-memory binding is gone but a task with the same
        # immutable review key may already exist in the runtime ledger.
        reconciled = self._reconcile_schedule(
            request=request,
            fingerprint=fingerprint,
            project_id=project_id,
            prompt_sha256=prompt_sha256,
            allow_absent=True,
        )
        if reconciled is not None:
            return reconciled
        try:
            completed = self._run(
                "run",
                "--detach",
                "--workspace",
                str(workspace),
                "--project-id",
                project_id,
                "--memory-mode",
                "empty",
                "--timeout",
                f"{self.config.task_timeout_seconds:g}",
                "--task-metadata-json",
                metadata,
                "--disable-tools",
                ",".join(DISABLED_WORKSPACE_TOOLS),
                prompt,
            )
        except OuroborosBackendError as exc:
            reconciled = self._reconcile_schedule(
                request=request,
                fingerprint=fingerprint,
                project_id=project_id,
                prompt_sha256=prompt_sha256,
                allow_absent=False,
            )
            if reconciled is not None:
                return reconciled
            raise exc
        if completed.returncode != 0:
            reconciled = self._reconcile_schedule(
                request=request,
                fingerprint=fingerprint,
                project_id=project_id,
                prompt_sha256=prompt_sha256,
                allow_absent=False,
            )
            if reconciled is not None:
                return reconciled
            raise OuroborosNotConfiguredError(
                "Ouroboros task could not be scheduled: "
                + _redact(completed.stderr or completed.stdout)
            )
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if len(lines) != 1 or TASK_ID_RE.fullmatch(lines[0]) is None:
            reconciled = self._reconcile_schedule(
                request=request,
                fingerprint=fingerprint,
                project_id=project_id,
                prompt_sha256=prompt_sha256,
                allow_absent=False,
            )
            if reconciled is not None:
                return reconciled
            raise AssertionError("unreachable reconciliation result")
        task_id = lines[0]
        record = _BackendTask(
            task_id=task_id,
            request=request,
            fingerprint=fingerprint,
            project_id=project_id,
            prompt_sha256=prompt_sha256,
            created_at=self._clock(),
        )
        with self._lock:
            if task_id in self._tasks:
                raise OuroborosContractError("runtime returned a duplicate task ID")
            self._tasks[task_id] = record
            self._idempotency[idem] = (fingerprint, task_id)
        return task_id

    def _reconcile_schedule(
        self,
        *,
        request: Mapping[str, Any],
        fingerprint: str,
        project_id: str,
        prompt_sha256: str,
        allow_absent: bool,
    ) -> str | None:
        idem = str(request["idempotency_key"])
        try:
            completed = self._run("tasks", "list", "--limit", "500")
            if completed.returncode != 0:
                raise OuroborosContractError("task reconciliation command failed")
            parsed = _strict_json(completed.stdout, "task reconciliation output")
            tasks = parsed.get("tasks") if isinstance(parsed, Mapping) else None
            if not isinstance(tasks, list) or len(tasks) > 500:
                raise OuroborosContractError("task reconciliation output is invalid")
            matches: list[Mapping[str, Any]] = []
            for item in tasks:
                if not isinstance(item, Mapping):
                    continue
                metadata = item.get("metadata")
                if not isinstance(metadata, Mapping):
                    continue
                if (
                    item.get("project_id") == project_id
                    and metadata.get("aga_review_id") == request["review_id"]
                    and metadata.get("aga_idempotency_key") == idem
                    and metadata.get("aga_prompt_sha256") == prompt_sha256
                    and metadata.get("data_classification") == "synthetic-public"
                    and metadata.get("expected_model_id") == self.config.model_id
                    and metadata.get("allowed_resources")
                    == {"network": True, "web": False}
                    and metadata.get("disabled_tools")
                    == list(DISABLED_WORKSPACE_TOOLS)
                ):
                    matches.append(item)
            if not matches:
                if allow_absent:
                    return None
                raise OuroborosContractError(
                    "task creation outcome is ambiguous and no exact ledger match was found"
                )
            task_ids = [str(item.get("task_id") or "") for item in matches]
            if any(TASK_ID_RE.fullmatch(task_id) is None for task_id in task_ids):
                raise OuroborosContractError(
                    "reconciled task has an invalid task ID"
                )
            if len(task_ids) != 1:
                for task_id in task_ids:
                    try:
                        self._run("tasks", "cancel", task_id)
                    except OuroborosBackendError:
                        pass
                raise OuroborosIdempotencyConflict(
                    "multiple external tasks match one logical review"
                )
            task_id = task_ids[0]
            record = _BackendTask(
                task_id=task_id,
                request=dict(request),
                fingerprint=fingerprint,
                project_id=project_id,
                prompt_sha256=prompt_sha256,
                created_at=self._clock(),
            )
            with self._lock:
                if task_id in self._tasks:
                    raise OuroborosContractError(
                        "reconciled runtime task ID is already bound"
                    )
                self._tasks[task_id] = record
                self._idempotency[idem] = (fingerprint, task_id)
            return task_id
        except OuroborosBackendError:
            with self._lock:
                self._ambiguous_idempotency[idem] = fingerprint
            raise

    def _record(self, task_id: str) -> _BackendTask:
        if not isinstance(task_id, str) or TASK_ID_RE.fullmatch(task_id) is None:
            raise UnknownTaskError("unknown task id")
        with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as exc:
                raise UnknownTaskError(f"unknown task id: {task_id}") from exc

    def _failure(
        self,
        record: _BackendTask,
        code: str,
        message: str,
        *,
        external_status: str = "",
    ) -> TaskResult:
        del message  # External/provider text is never part of a trusted result.
        result = TaskResult(
            task_id=record.task_id,
            task_name="aga:review",
            status=TaskStatus.FAILED,
            error=f"{code}: review did not produce a trusted result",
            metadata={
                "error_code": code,
                "external_status": external_status,
                "review_id": record.request["review_id"],
                "verdict": "incomplete",
                "incomplete": True,
                "human_review_required": True,
                "auto_merge": False,
                "runtime": {"name": "ouroboros", "version": self.config.runtime_version},
                "expected_route": {
                    "provider": "openrouter",
                    "model": self.config.model_id,
                },
            },
        )
        with self._lock:
            record.frozen_result = result
        return result

    def _json_command(
        self,
        record: _BackendTask,
        *parts: str,
        deadline: float | None = None,
    ) -> Mapping[str, Any]:
        timeout: float | None = None
        if deadline is not None:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise CommandTimeoutError("task wait deadline was exhausted")
            timeout = min(self.config.command_timeout_seconds, remaining)
        completed = self._run(*parts, timeout=timeout)
        if completed.returncode != 0:
            raise OuroborosContractError(
                "CLI command failed: " + _redact(completed.stderr or completed.stdout)
            )
        raw = completed.stdout.encode("utf-8")
        if len(raw) > self.config.max_json_bytes:
            raise OuroborosContractError("CLI JSON exceeded its bound")
        parsed = _strict_json(completed.stdout, "CLI output")
        if not isinstance(parsed, Mapping):
            raise OuroborosContractError("CLI output must be a JSON object")
        return parsed

    def _validate_external_correlation(
        self, record: _BackendTask, external: Mapping[str, Any]
    ) -> None:
        if external.get("task_id") != record.task_id:
            raise OuroborosContractError("task result task_id does not match")
        if external.get("project_id") != record.project_id:
            raise OuroborosContractError("task result project_id does not match")
        metadata = external.get("metadata")
        if not isinstance(metadata, Mapping):
            raise OuroborosContractError("task result metadata is missing")
        expected = {
            "aga_review_id": record.request["review_id"],
            "aga_idempotency_key": record.request["idempotency_key"],
            "data_classification": "synthetic-public",
            "expected_model_id": self.config.model_id,
            "aga_prompt_sha256": record.prompt_sha256,
            "allowed_resources": {"network": True, "web": False},
            "disabled_tools": list(DISABLED_WORKSPACE_TOOLS),
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise OuroborosContractError("task result metadata correlation mismatch")
        contract = external.get("task_contract")
        if not isinstance(contract, Mapping):
            raise OuroborosContractError("task result contract is missing")
        disabled = contract.get("disabled_tools")
        if (
            contract.get("allowed_resources") != {"network": True, "web": False}
            or not isinstance(disabled, list)
            or disabled != list(DISABLED_WORKSPACE_TOOLS)
        ):
            raise OuroborosContractError("task result policy correlation mismatch")

    @staticmethod
    def _external_success(result: Mapping[str, Any]) -> bool:
        if str(result.get("status") or "").lower() != "completed":
            return False
        artifact = str(result.get("artifact_status") or "").lower()
        bundle = result.get("artifact_bundle")
        bundle_status = (
            str(bundle.get("status") or "").lower()
            if isinstance(bundle, Mapping)
            else ""
        )
        if not isinstance(bundle, Mapping):
            return False
        effective_artifact = bundle_status or artifact
        if (
            artifact in BAD_ARTIFACT_STATUSES
            or bundle_status in BAD_ARTIFACT_STATUSES
            or artifact != "ready_no_changes"
            or bundle_status != "ready_no_changes"
            or effective_artifact != "ready_no_changes"
        ):
            return False
        axes = result.get("outcome_axes")
        if not isinstance(axes, Mapping):
            return False
        lifecycle = axes.get("lifecycle")
        execution = axes.get("execution")
        artifacts = axes.get("artifacts")
        objective = axes.get("objective")
        if (
            not isinstance(lifecycle, Mapping)
            or str(lifecycle.get("status") or "").lower() != "completed"
            or not isinstance(execution, Mapping)
            or str(execution.get("status") or "").lower() != "ok"
            or not isinstance(artifacts, Mapping)
            or str(artifacts.get("status") or "").lower() != "ready_no_changes"
            or not isinstance(objective, Mapping)
            or str(objective.get("status") or "").lower() != "not_evaluated"
        ):
            return False
        return True

    @staticmethod
    def _external_artifact_pending(result: Mapping[str, Any]) -> bool:
        bundle = result.get("artifact_bundle")
        bundle_status = (
            str(bundle.get("status") or "").lower()
            if isinstance(bundle, Mapping)
            else ""
        )
        effective = bundle_status or str(result.get("artifact_status") or "").lower()
        return effective in {"pending", "finalizing"}

    def _canonical_tool(self, value: Any) -> str | None:
        text = str(value or "")
        for tool in EXPECTED_TOOLS:
            if text == tool or text == f"mcp_{self.config.server_id}__{tool}":
                return tool
        return None

    def _tool_flow(
        self, record: _BackendTask, entries: Any
    ) -> tuple[list[str], Mapping[str, Any], Mapping[str, Any]]:
        if not isinstance(entries, list) or len(entries) > 2000:
            raise OuroborosContractError("tool log entries are invalid or oversized")
        selected: list[tuple[int, str, Mapping[str, Any]]] = []
        seen_calls: dict[tuple[str, str], Mapping[str, Any]] = {}
        for index, raw in enumerate(entries):
            if not isinstance(raw, Mapping):
                continue
            tool = self._canonical_tool(raw.get("tool"))
            if raw.get("tool") is not None and tool is None:
                raise OuroborosContractError(
                    "non-AGA tool invocation was recorded"
                )
            if tool is not None:
                logged_task_id = raw.get("task_id")
                call_id = raw.get("tool_call_id")
                if (
                    not isinstance(logged_task_id, str)
                    or TASK_ID_RE.fullmatch(logged_task_id) is None
                    or not isinstance(call_id, str)
                    or not call_id
                    or len(call_id) > 256
                ):
                    raise OuroborosContractError(
                        "tool log correlation identifiers are missing"
                    )
                key = (logged_task_id, call_id)
                projection = {
                    "tool": tool,
                    "task_id": logged_task_id,
                    "args": raw.get("args"),
                    "status": raw.get("status"),
                    "is_error": raw.get("is_error"),
                }
                prior = seen_calls.get(key)
                if prior is not None:
                    if prior != projection:
                        raise OuroborosContractError(
                            "mirrored tool log entries conflict"
                        )
                    continue
                seen_calls[key] = projection
                selected.append((index, tool, raw))
        prepares = [item for item in selected if item[1] == "aga_prepare_review"]
        finalizes = [item for item in selected if item[1] == "aga_finalize_review"]
        names = [tool for _, tool, _ in selected]
        if (
            len(prepares) != 1
            or len(finalizes) != 1
            or not names
            or names[0] != "aga_prepare_review"
            or names[-1] != "aga_finalize_review"
        ):
            raise OuroborosContractError(
                "tool flow must contain one ordered prepare and one final finalize"
            )
        for _, _, entry in (prepares[0], finalizes[0]):
            if entry.get("task_id") != record.task_id:
                raise OuroborosContractError(
                    "prepare/finalize must be executed by the root review task"
                )
        for _, tool, entry in selected:
            status = str(entry.get("status") or "").lower()
            if entry.get("is_error") is not False or status != "ok":
                raise OuroborosContractError(f"{tool} receipt reports failure")
            if (
                entry.get("task_id") != record.task_id
                and entry.get("root_task_id") != record.task_id
            ):
                raise OuroborosContractError(
                    f"{tool} receipt is outside the root task lineage"
                )

        prepare_args = prepares[0][2].get("args")
        finalize_args = finalizes[-1][2].get("args")
        if not isinstance(prepare_args, Mapping) or not isinstance(finalize_args, Mapping):
            raise OuroborosContractError("tool log correlation arguments are missing")
        expected_prepare = {
            "repository_id": record.request["repository_id"],
            "base": record.request["base"],
            "head": record.request["head"],
            "review_id": record.request["review_id"],
        }
        if any(prepare_args.get(key) != value for key, value in expected_prepare.items()):
            raise OuroborosContractError("prepare arguments do not match immutable request")
        if finalize_args.get("review_id") != record.request["review_id"]:
            raise OuroborosContractError("finalize review_id does not match")
        for key in ("review_digest", "task_digest"):
            if not isinstance(finalize_args.get(key), str):
                raise OuroborosContractError(f"finalize {key} is missing")
        for _, tool, entry in selected:
            if tool not in {"aga_seaf_lookup", "aga_parse_diagram"}:
                continue
            args = entry.get("args")
            if (
                not isinstance(args, Mapping)
                or args.get("review_id") != record.request["review_id"]
                or args.get("review_digest") != finalize_args["review_digest"]
                or not isinstance(args.get("entity_id"), str)
            ):
                raise OuroborosContractError(
                    f"{tool} receipt correlation mismatch"
                )
        return names, prepare_args, finalize_args

    def _aga_receipts(
        self,
        record: _BackendTask,
        finalize_args: Mapping[str, Any],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        source = self.config.receipt_source
        if source is None:
            raise OuroborosContractError("trusted AGA receipt source is not configured")
        try:
            receipts = source()
        except Exception as exc:
            raise OuroborosContractError(
                "trusted AGA receipt source is unavailable"
            ) from exc
        if not isinstance(receipts, Sequence) or len(receipts) > 10_000:
            raise OuroborosContractError("trusted AGA receipts are invalid or oversized")
        matching = [
            item
            for item in receipts
            if isinstance(item, Mapping)
            and item.get("review_id_sha256")
            == hashlib.sha256(
                record.request["review_id"].encode("utf-8")
            ).hexdigest()
        ]
        prepares = [
            (index, item)
            for index, item in enumerate(matching)
            if item.get("tool") == "aga_prepare_review"
        ]
        finalizes = [
            (index, item)
            for index, item in enumerate(matching)
            if item.get("tool") == "aga_finalize_review"
        ]
        if len(prepares) != 1 or len(finalizes) != 1:
            raise OuroborosContractError("trusted AGA prepare/finalize receipt is missing")
        prepare_index, prepare = prepares[0]
        finalize_index, finalize = finalizes[0]
        if prepare_index >= finalize_index:
            raise OuroborosContractError("trusted AGA receipts are unordered")
        if prepare.get("status") not in {"ok", "incomplete"}:
            raise OuroborosContractError("trusted prepare receipt failed")
        if (
            prepare.get("output_incomplete") is True
            or prepare.get("status") == "incomplete"
            or prepare.get("output_status") != "ready"
        ):
            raise OuroborosContractError("AGA prepare was incomplete")
        expected_prepare_args = {
            "repository_id": record.request["repository_id"],
            "base": record.request["base"],
            "head": record.request["head"],
            "review_id": record.request["review_id"],
        }
        if prepare.get("args_sha256") != hashlib.sha256(
            _canonical_bytes(expected_prepare_args)
        ).hexdigest():
            raise OuroborosContractError("trusted prepare arguments mismatch")
        for key in ("review_digest", "task_digest"):
            if prepare.get(key) != finalize_args.get(key):
                raise OuroborosContractError(f"trusted prepare {key} mismatch")
            if finalize.get(key) != finalize_args.get(key):
                raise OuroborosContractError(f"trusted finalize {key} mismatch")
        if not isinstance(finalize.get("output_sha256"), str):
            raise OuroborosContractError("trusted finalize output hash is missing")
        finalize_state = (
            finalize.get("status"),
            finalize.get("output_status"),
            finalize.get("output_incomplete"),
        )
        if finalize_state not in {
            ("ok", "completed", False),
            ("incomplete", "incomplete", True),
        }:
            raise OuroborosContractError("trusted finalize receipt status is invalid")
        return prepare, finalize

    def _validate_final(
        self,
        record: _BackendTask,
        external: Mapping[str, Any],
        tool_names: list[str],
        prepare_receipt: Mapping[str, Any],
        finalize_receipt: Mapping[str, Any],
    ) -> TaskResult:
        raw_final = external.get("result")
        if isinstance(raw_final, str):
            if len(raw_final.encode("utf-8")) > self.config.max_json_bytes:
                raise OuroborosContractError("final AGA JSON exceeded its bound")
            parsed = _strict_json(raw_final, "final task answer")
            if not isinstance(parsed, Mapping):
                raise OuroborosContractError("final task answer must be a JSON object")
            final = dict(parsed)
        else:
            raise OuroborosContractError("task result does not contain final AGA JSON")
        try:
            validate_json_schema(
                final,
                _tool_definition("aga_finalize_review")["outputSchema"],
                "$final",
            )
        except SchemaViolation as exc:
            raise OuroborosContractError(
                f"final AGA result failed schema at {exc.path}"
            ) from exc
        expected_hash = hashlib.sha256(_canonical_bytes(final)).hexdigest()
        if expected_hash != finalize_receipt.get("output_sha256"):
            raise OuroborosContractError(
                "task answer is not the exact AGA finalize output"
            )
        if final.get("review_id") != record.request["review_id"]:
            raise OuroborosContractError("final AGA review_id mismatch")
        for key in ("review_digest", "task_digest"):
            if final.get(key) != finalize_receipt.get(key):
                raise OuroborosContractError(f"final AGA {key} mismatch")
        if final.get("auto_merge") is not False:
            raise OuroborosContractError("AGA finalize did not forbid auto-merge")
        is_completed = (
            final.get("status") == "completed"
            and final.get("incomplete") is False
            and final.get("verdict") != "incomplete"
            and finalize_receipt.get("status") == "ok"
            and finalize_receipt.get("output_status") == "completed"
            and finalize_receipt.get("output_incomplete") is False
        )
        is_incomplete = (
            final.get("status") == "incomplete"
            and final.get("incomplete") is True
            and final.get("verdict") == "incomplete"
            and final.get("human_review_required") is True
            and final.get("escalate") is True
            and finalize_receipt.get("status") == "incomplete"
            and finalize_receipt.get("output_status") == "incomplete"
            and finalize_receipt.get("output_incomplete") is True
        )
        if not is_completed and not is_incomplete:
            raise OuroborosContractError("AGA finalize status fields are inconsistent")
        if is_completed and final.get("verdict") == "request_changes_escalate" and final.get(
            "human_review_required"
        ) is not True:
            raise OuroborosContractError("blocker/major result does not require HITL")

        metadata = {
            "external_status": "completed",
            "review_id": final["review_id"],
            "review_digest": final["review_digest"],
            "task_digest": final["task_digest"],
            "aga_status": final["status"],
            "verdict": final["verdict"],
            "human_review_required": final["human_review_required"],
            "auto_merge": False,
            "runtime": {"name": "ouroboros", "version": self.config.runtime_version},
            "provider": "openrouter",
            "model": {"name": self.config.model_id},
            "prompt_sha256": record.prompt_sha256,
            "tool_names": tool_names,
            "prepare_output_sha256": prepare_receipt.get("output_sha256"),
            "final_output_sha256": expected_hash,
            "aga_final": final,
        }
        if is_incomplete:
            metadata["error_code"] = "aga_incomplete"
            return TaskResult(
                task_id=record.task_id,
                task_name="aga:review",
                status=TaskStatus.FAILED,
                findings=tuple(dict(item) for item in final["findings"]),
                observations=tuple(dict(item) for item in final["observations"]),
                error="aga_incomplete: trusted AGA final is incomplete",
                metadata=metadata,
            )
        return TaskResult(
            task_id=record.task_id,
            task_name="aga:review",
            status=TaskStatus.SUCCEEDED,
            findings=tuple(dict(item) for item in final["findings"]),
            observations=tuple(dict(item) for item in final["observations"]),
            metadata=metadata,
        )

    def _validated_model_usage(
        self,
        record: _BackendTask,
        terminal: Mapping[str, Any],
        *,
        deadline: float | None = None,
    ) -> Mapping[str, Any]:
        payload = self._json_command(
            record,
            "logs",
            "tail",
            "events",
            "--task-id",
            record.task_id,
            "--limit",
            "2000",
            "--json",
            deadline=deadline,
        )
        if payload.get("name") != "events":
            raise OuroborosContractError("CLI returned the wrong event stream")
        entries = payload.get("entries")
        if not isinstance(entries, list) or len(entries) > 2000:
            raise OuroborosContractError("event log entries are invalid or oversized")
        usage_rows: list[Mapping[str, Any]] = []
        attempt_projections: dict[str, bytes] = {}
        for raw in entries:
            if not isinstance(raw, Mapping) or raw.get("type") != "llm_usage":
                continue
            if raw.get("task_id") != record.task_id:
                continue
            required_strings = (
                "task_id",
                "root_task_id",
                "parent_task_id",
                "requested_model_lane",
                "effective_model_lane",
                "category",
                "model",
                "api_key_type",
                "model_category",
                "provider",
                "source",
                "accounting_authority",
            )
            if any(not isinstance(raw.get(key), str) for key in required_strings):
                raise OuroborosContractError("LLM usage event shape is incomplete")
            if (
                raw.get("root_task_id") not in {"", record.task_id}
                or raw.get("parent_task_id") != ""
                or raw.get("provider") != "openrouter"
                or raw.get("api_key_type") != "openrouter"
                or raw.get("model") != self.config.model_id
                or not raw.get("source")
                or raw.get("accounting_authority") != "physical_attempt_ledger"
            ):
                raise OuroborosContractError(
                    "actual provider/model/accounting route differs from the approved route"
                )
            attempt_ids = raw.get("ledger_attempt_ids")
            if (
                not isinstance(attempt_ids, list)
                or not attempt_ids
                or len(attempt_ids) > 64
                or any(
                    not isinstance(value, str)
                    or not value
                    or len(value) > 256
                    for value in attempt_ids
                )
                or len(set(attempt_ids)) != len(attempt_ids)
            ):
                raise OuroborosContractError("LLM physical-attempt IDs are invalid")
            projection = {
                key: raw.get(key)
                for key in (
                    *required_strings,
                    "ledger_attempt_ids",
                )
            }
            try:
                fingerprint = _canonical_bytes(projection)
            except (TypeError, ValueError) as exc:
                raise OuroborosContractError(
                    "LLM usage event is not canonical JSON"
                ) from exc
            prior_fingerprints = {
                attempt_projections[value]
                for value in attempt_ids
                if value in attempt_projections
            }
            if prior_fingerprints:
                if len(prior_fingerprints) != 1 or fingerprint not in prior_fingerprints:
                    raise OuroborosContractError(
                        "LLM physical-attempt accounting entries conflict"
                    )
                if any(value not in attempt_projections for value in attempt_ids):
                    raise OuroborosContractError(
                        "LLM physical-attempt accounting entries overlap"
                    )
                continue
            for value in attempt_ids:
                attempt_projections[value] = fingerprint
            usage_rows.append(raw)
        if not usage_rows:
            raise OuroborosContractError("no correlated LLM usage event was recorded")

        if terminal.get("cost_accounting_status") != "available":
            raise OuroborosContractError(
                "terminal task cost accounting is unavailable"
            )
        if terminal.get("cost_final") is not True:
            raise OuroborosContractError(
                "terminal task cost accounting is not final"
            )
        if terminal.get("ledger_integrity_degraded") is not False:
            raise OuroborosContractError("terminal task ledger integrity is degraded")

        unresolved = terminal.get("unresolved_upper_bound_usd")
        if (
            isinstance(unresolved, bool)
            or not isinstance(unresolved, (int, float))
            or not math.isfinite(float(unresolved))
            or float(unresolved) != 0.0
        ):
            raise OuroborosContractError(
                "terminal task ledger has unresolved spend"
            )
        unknown_unmetered = terminal.get("unknown_unmetered")
        if (
            isinstance(unknown_unmetered, bool)
            or not isinstance(unknown_unmetered, int)
            or unknown_unmetered != 0
        ):
            raise OuroborosContractError(
                "terminal task ledger has unknown unmetered attempts"
            )

        cost = terminal.get("cost_usd")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or float(cost) < 0
        ):
            raise OuroborosContractError("terminal task ledger cost is invalid")
        total_rounds = terminal.get("total_rounds")
        if (
            isinstance(total_rounds, bool)
            or not isinstance(total_rounds, int)
            or total_rounds < 1
        ):
            raise OuroborosContractError(
                "terminal task ledger physical-call count is invalid"
            )
        if total_rounds != len(attempt_projections):
            raise OuroborosContractError(
                "terminal task ledger physical-call count does not match usage events"
            )
        terminal_tokens: dict[str, int] = {}
        for key in ("prompt_tokens", "completion_tokens"):
            value = terminal.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise OuroborosContractError(
                    "terminal task ledger token accounting is invalid"
                )
            terminal_tokens[key] = value

        return {
            "provider": "openrouter",
            "model": self.config.model_id,
            "accounting_authority": "terminal_task_ledger",
            "call_count": total_rounds,
            "usage_event_count": len(usage_rows),
            "known_cost_usd": float(cost),
            "cost_complete": True,
            "cost_accounting_status": "available",
            "cost_final": True,
            "ledger_integrity_degraded": False,
            "unresolved_upper_bound_usd": 0.0,
            "unknown_unmetered": 0,
            "prompt_tokens": terminal_tokens["prompt_tokens"],
            "completion_tokens": terminal_tokens["completion_tokens"],
        }

    def get_task_result(self, task_id: str) -> TaskResult:
        return self._get_task_result(task_id)

    def _cancel_timed_out_task(self, record: _BackendTask) -> bool:
        """Request cancellation and trust only the official correlated CLI ack."""

        record.cancel_attempted = True
        try:
            completed = self._run(
                "tasks",
                "cancel",
                record.task_id,
                # Cancellation starts a fresh, bounded control-plane operation
                # after the task wait deadline.  The old 50 ms allowance was too
                # short to start the packaged Python CLI and complete its
                # loopback POST, which could leave a paid task running.
                timeout=self.config.command_timeout_seconds,
            )
        except OuroborosBackendError:
            return False
        if completed.returncode != 0:
            return False
        raw = completed.stdout.encode("utf-8")
        if len(raw) > self.config.max_json_bytes:
            return False
        try:
            payload = _strict_json(completed.stdout, "task cancellation output")
        except OuroborosContractError:
            return False
        confirmed = (
            isinstance(payload, Mapping)
            and payload.get("ok") is True
            and payload.get("task_id") == record.task_id
        )
        record.cancel_confirmed = confirmed
        return confirmed

    def _get_task_result(
        self, task_id: str, *, deadline: float | None = None
    ) -> TaskResult:
        record = self._record(task_id)
        with self._lock:
            if record.frozen_result is not None:
                return record.frozen_result
        try:
            external = self._json_command(
                record, "tasks", "show", task_id, deadline=deadline
            )
            self._validate_external_correlation(record, external)
        except CommandTimeoutError:
            if deadline is not None:
                raise
            return self._failure(record, "cli_error", "command timeout")
        except OuroborosBackendError as exc:
            return self._failure(record, "cli_error", str(exc))
        status = str(external.get("status") or "").strip().lower()
        if status in PENDING_STATUSES:
            return TaskResult(
                task_id=task_id,
                task_name="aga:review",
                status=TaskStatus.PENDING,
                metadata={"external_status": status},
            )
        if status in FAILED_STATUSES:
            return self._failure(
                record,
                f"external_{status}",
                external.get("result") or external.get("error") or status,
                external_status=status,
            )
        if status != "completed":
            return self._failure(
                record,
                "unknown_external_status",
                status or "missing status",
                external_status=status,
            )
        if self._external_artifact_pending(external):
            return TaskResult(
                task_id=task_id,
                task_name="aga:review",
                status=TaskStatus.PENDING,
                metadata={"external_status": "artifact_finalizing"},
            )
        if not self._external_success(external):
            return self._failure(
                record,
                "external_objective_failed",
                "terminal task axes/artifacts are not successful",
                external_status=status,
            )
        try:
            log_payload = self._json_command(
                record,
                "logs",
                "tail",
                "tools",
                "--task-id",
                task_id,
                "--limit",
                "2000",
                "--json",
                deadline=deadline,
            )
            if log_payload.get("name") != "tools":
                raise OuroborosContractError("CLI returned the wrong log stream")
            tool_names, _prepare_args, finalize_args = self._tool_flow(
                record, log_payload.get("entries")
            )
            prepare_receipt, finalize_receipt = self._aga_receipts(
                record, finalize_args
            )
            result = self._validate_final(
                record,
                external,
                tool_names,
                prepare_receipt,
                finalize_receipt,
            )
            model_usage = self._validated_model_usage(
                record, external, deadline=deadline
            )
            result = TaskResult(
                task_id=result.task_id,
                task_name=result.task_name,
                status=result.status,
                findings=result.findings,
                observations=result.observations,
                error=result.error,
                metadata={**dict(result.metadata), "model_usage": dict(model_usage)},
            )
        except CommandTimeoutError:
            if deadline is not None:
                raise
            return self._failure(record, "invalid_aga_receipt", "command timeout")
        except OuroborosBackendError as exc:
            return self._failure(
                record,
                "invalid_aga_receipt",
                str(exc),
                external_status=status,
            )
        with self._lock:
            record.frozen_result = result
        return result

    def wait_for_task(self, task_id: str, timeout: float | None = None) -> TaskResult:
        record = self._record(task_id)
        if timeout is None:
            budget = (
                self.config.task_timeout_seconds
                + self.config.finalization_grace_seconds
            )
            deadline = record.created_at + budget
        else:
            budget = float(timeout)
            deadline = self._clock() + budget
        if budget < 0:
            raise ValueError("timeout cannot be negative")
        while True:
            if self._clock() >= deadline:
                break
            try:
                result = self._get_task_result(task_id, deadline=deadline)
            except CommandTimeoutError:
                break
            if result.complete:
                return result
            if self._clock() >= deadline:
                break
            self._sleeper(
                max(
                    0.0,
                    min(self.config.poll_interval_seconds, deadline - self._clock()),
                )
            )
        with self._lock:
            if not record.cancel_attempted:
                self._cancel_timed_out_task(record)
            result = TaskResult(
                task_id=task_id,
                task_name="aga:review",
                status=TaskStatus.TIMED_OUT,
                error=f"task exceeded timeout of {budget:g} seconds",
                metadata={
                    "error_code": "task_timeout",
                    "external_status": "timed_out",
                    "review_id": record.request["review_id"],
                    "verdict": "incomplete",
                    "incomplete": True,
                    "human_review_required": True,
                    "auto_merge": False,
                    "cancel_attempted": record.cancel_attempted,
                    "cancel_confirmed": record.cancel_confirmed,
                    "runtime": {
                        "name": "ouroboros",
                        "version": self.config.runtime_version,
                    },
                    "expected_route": {
                        "provider": "openrouter",
                        "model": self.config.model_id,
                    },
                },
            )
            record.frozen_result = result
            return result


__all__ = [
    "BoundedCommandRunner",
    "CommandOutputTooLargeError",
    "CommandResult",
    "CommandRunner",
    "CommandTimeoutError",
    "DISABLED_WORKSPACE_TOOLS",
    "OuroborosBackendConfig",
    "OuroborosBackendError",
    "OuroborosContractError",
    "OuroborosIdempotencyConflict",
    "OuroborosNotConfiguredError",
    "OuroborosTaskBackend",
]
