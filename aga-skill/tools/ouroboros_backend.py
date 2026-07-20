# -*- coding: utf-8 -*-
"""Fail-closed adapter for the packaged Ouroboros v6.64.1 CLI.

The adapter intentionally imports no Ouroboros Python modules.  It treats the
packaged CLI/gateway as an external runtime, verifies its public task/tool-log
contract, and accepts a completed review only when the exact final JSON is
attested by a trusted AGA MCP receipt hash.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MCP_TOOL_ERROR_MARKER = "\n\n⚠️ MCP_TOOL_ERROR:"
SECRET_RE = re.compile(
    r"(?i)(?:sk-or-v1-|sk-|ghp_|github_pat_|Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"
)
EXPECTED_TOOLS = (
    "aga_prepare_review",
    "aga_seaf_lookup",
    "aga_parse_diagram",
    "aga_finalize_review",
)
REMEDIATION_MCP_TOOLS = (
    "aga_prepare_remediation",
    "aga_finalize_remediation",
)
MANAGED_TASK_SCHEMA = "aga.ouroboros-managed-task/v1"
REVIEW_MCP_STAGE = "review"
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
TASK_RECONCILIATION_LIMIT = 10
# ``tasks list --limit 500`` returns the full public task projection.  A small
# dedicated AGA history can therefore exceed one MiB even though every
# individual trusted result remains bounded separately.  Eight MiB keeps the
# local CLI pipe bounded while covering the frozen basket and its reconciliation
# history without weakening the one-MiB JSON/result contract below.
DEFAULT_CLI_STDOUT_BYTES = 8_388_608


class OuroborosBackendError(RuntimeError):
    """Base error for configuration and external CLI contract failures."""


class OuroborosNotConfiguredError(OuroborosBackendError):
    """The pinned runtime or a required trusted input is unavailable."""


class OuroborosContractError(OuroborosBackendError, ValueError):
    """The runtime returned malformed, unknown or uncorrelated data."""


class OuroborosIdempotencyConflict(OuroborosContractError):
    """One logical review key was reused with different immutable inputs."""


class OuroborosMCPTransportError(OuroborosContractError):
    """A model-facing MCP transport failure was hidden by the public log."""


class OuroborosMCPServiceError(OuroborosContractError):
    """AGA returned a structured fail-closed service error."""


class CommandTimeoutError(OuroborosBackendError):
    """A CLI subprocess exceeded its local command deadline."""


class CommandOutputTooLargeError(OuroborosBackendError):
    """A CLI subprocess exceeded the configured output bound."""


class _CostAccountingPending(OuroborosBackendError):
    """The root task is terminal but its durable cost checkpoint is not visible yet."""


class _CostAccountingError(OuroborosBackendError):
    """A terminal cost projection is contradictory or permanently non-authoritative."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


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
        max_stdout_bytes: int = DEFAULT_CLI_STDOUT_BYTES,
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
ProjectRegistrar = Callable[[str], None]
FinalizeDigestRepair = Callable[..., Mapping[str, Any]]
FinalizeTransportRepair = Callable[..., Mapping[str, Any]]


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
    # Trusted, in-process recovery for a model that copied one opaque prepare
    # digest incorrectly.  The callback is never exposed as an MCP tool and
    # may only reuse the semantic payload retained by the local MCP server.
    finalize_digest_repair: FinalizeDigestRepair | None = None
    # Trusted recovery for a schema-valid finalize whose MCP HTTP response was
    # cancelled ambiguously. The callback reuses only the exact in-process
    # payload whose complete hash appears in the private receipt journal.
    finalize_transport_repair: FinalizeTransportRepair | None = None
    # The v6.64.1 worker waits for its periodic 300-second project-registry
    # reconcile when an explicit isolated project id has not been registered
    # before task creation.  A trusted loopback-only runner may supply this
    # idempotent registrar so the normal task-done/artifact path is immediate.
    project_registrar: ProjectRegistrar | None = None
    # The frozen 16-case semantic basket contains no diagram artifacts.  Its
    # trusted runner withholds the optional diagram tool at the task-contract
    # layer while preflight still verifies that the MCP server exposes all
    # six gateway tools and the review worker receives only its stage subset.
    disable_diagram_tool: bool = False
    # Controlled review scenarios carry all semantic evidence in prepare.
    # Withholding lookup prevents an unnecessary model-generated correlation
    # argument from turning an otherwise valid review into a service error.
    disable_lookup_tool: bool = False
    # This must only be enabled from a successful trusted preflight that has
    # verified every runtime model route, including post-task synthesis.  The
    # public v6.64.1 event stream can omit those auxiliary physical attempts.
    all_model_routes_pinned: bool = False


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
    terminal_completed: bool = False
    cost_finalization_pending: bool = False


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


def _strict_final_json(text: str) -> tuple[Any, str]:
    """Decode the terminal answer with one narrowly bounded presentation repair.

    Some providers wrap an otherwise exact tool result in a single JSON
    Markdown fence despite an explicit bare-JSON instruction.  The wrapper is
    accepted only as the entire document.  The caller still validates the
    strict schema and requires the canonical object hash to equal the trusted
    AGA finalize receipt, so this cannot change or invent a verdict.
    """

    if text.startswith("```json\n") and text.endswith("\n```"):
        body = text[len("```json\n") : -len("\n```")]
        if body.startswith("{") and body.endswith("}"):
            return _strict_json(body, "fenced final task answer"), "single_json_fence"
    return _strict_json(text, "final task answer"), "strict_json"


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
        if config.project_registrar is not None and not callable(
            config.project_registrar
        ):
            raise ValueError("project_registrar must be callable")
        if config.finalize_digest_repair is not None and not callable(
            config.finalize_digest_repair
        ):
            raise ValueError("finalize_digest_repair must be callable")
        if config.finalize_transport_repair is not None and not callable(
            config.finalize_transport_repair
        ):
            raise ValueError("finalize_transport_repair must be callable")
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
        if not isinstance(config.all_model_routes_pinned, bool):
            raise ValueError("all_model_routes_pinned must be a boolean attestation")
        if not isinstance(config.disable_diagram_tool, bool):
            raise ValueError("disable_diagram_tool must be a boolean")
        if not isinstance(config.disable_lookup_tool, bool):
            raise ValueError("disable_lookup_tool must be a boolean")
        if not ID_RE.fullmatch(config.server_id):
            raise ValueError("server_id must be a non-path identifier")
        self._disabled_tools = (
            DISABLED_WORKSPACE_TOOLS
            + tuple(
                f"mcp_{config.server_id}__{name}"
                for name in REMEDIATION_MCP_TOOLS
            )
            + (
                (f"mcp_{config.server_id}__aga_parse_diagram",)
                if config.disable_diagram_tool
                else ()
            )
            + (
                (f"mcp_{config.server_id}__aga_seaf_lookup",)
                if config.disable_lookup_tool
                else ()
            )
        )
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
        self._trusted_final_overrides: dict[str, dict[str, Any]] = {}
        self._transport_finalize_repairs: set[str] = set()

    def _argv(self, *parts: str) -> list[str]:
        argv = list(self.config.command_prefix)
        if self.config.gateway_url:
            argv.extend(("--url", self.config.gateway_url))
        argv.extend(parts)
        return argv

    def _logical_task_name(self) -> str:
        """Return the sealed logical task name for result projections."""

        return "aga:review"

    def _run(self, *parts: str, timeout: float | None = None) -> CommandResult:
        command_timeout = float(
            self.config.command_timeout_seconds if timeout is None else timeout
        )
        argv = self._argv(*parts)
        try:
            return self._runner.run(
                argv,
                timeout=command_timeout,
            )
        except OuroborosBackendError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise OuroborosContractError(
                "CLI command runner raised an unchecked exception"
            ) from exc

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

    def _managed_task_metadata(
        self,
        request: Mapping[str, Any],
        prompt_sha256: str,
    ) -> dict[str, Any]:
        """Return the sealed review-stage worker contract.

        Stage-specific backends may override this protected projection, while
        the public payload and caller configuration remain unable to widen the
        tool allowlist.
        """

        return {
            "aga_review_id": request["review_id"],
            "aga_idempotency_key": request["idempotency_key"],
            "aga_prompt_sha256": prompt_sha256,
            "aga_runtime_contract": MANAGED_TASK_SCHEMA,
            "aga_mcp_stage": REVIEW_MCP_STAGE,
            "aga_expected_mcp_tools": list(EXPECTED_TOOLS),
            "data_classification": "synthetic-public",
            "expected_model_id": self.config.model_id,
            "allowed_resources": {"network": True, "web": False},
            "disabled_tools": list(self._disabled_tools),
        }

    def _managed_task_projection_matches(
        self,
        metadata: Mapping[str, Any],
        request: Mapping[str, Any],
        prompt_sha256: str,
    ) -> bool:
        expected = self._managed_task_metadata(request, prompt_sha256)
        return all(metadata.get(key) == value for key, value in expected.items())

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
        metadata_values = self._managed_task_metadata(request, prompt_sha256)
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
        if self.config.project_registrar is not None:
            try:
                self.config.project_registrar(project_id)
            except OuroborosBackendError:
                raise
            except Exception as exc:
                raise OuroborosNotConfiguredError(
                    "trusted local project registration failed"
                ) from exc
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
                ",".join(self._disabled_tools),
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
            # A newly scheduled task must be at the head of the runtime ledger.
            # Keeping this window small is important: task projections include
            # full logs and 500 historical tasks can exceed the bounded CLI
            # pipe before a paid remediation task is even created.
            completed = self._run(
                "tasks", "list", "--limit", str(TASK_RECONCILIATION_LIMIT)
            )
            if completed.returncode != 0:
                raise OuroborosContractError("task reconciliation command failed")
            parsed = _strict_json(completed.stdout, "task reconciliation output")
            tasks = parsed.get("tasks") if isinstance(parsed, Mapping) else None
            if (
                not isinstance(tasks, list)
                or len(tasks) > TASK_RECONCILIATION_LIMIT
            ):
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
                    and self._managed_task_projection_matches(
                        metadata,
                        request,
                        prompt_sha256,
                    )
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
            task_name=self._logical_task_name(),
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
        if not self._managed_task_projection_matches(
            metadata,
            record.request,
            record.prompt_sha256,
        ):
            raise OuroborosContractError("task result metadata correlation mismatch")
        contract = external.get("task_contract")
        if not isinstance(contract, Mapping):
            raise OuroborosContractError("task result contract is missing")
        disabled = contract.get("disabled_tools")
        if (
            contract.get("allowed_resources") != {"network": True, "web": False}
            or not isinstance(disabled, list)
            or disabled != list(self._disabled_tools)
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
    def _external_finalize_recovery_candidate(result: Mapping[str, Any]) -> bool:
        """Allow only a provider failure after an already-issued finalize.

        The trusted tool/receipt path still has to prove and replay the exact
        schema-valid finalize before this candidate can become successful.
        """

        if str(result.get("status") or "").lower() != "completed":
            return False
        bundle = result.get("artifact_bundle")
        axes = result.get("outcome_axes")
        if not isinstance(bundle, Mapping) or not isinstance(axes, Mapping):
            return False
        lifecycle = axes.get("lifecycle")
        execution = axes.get("execution")
        artifacts = axes.get("artifacts")
        objective = axes.get("objective")
        return (
            str(result.get("artifact_status") or "").lower() == "ready_no_changes"
            and str(bundle.get("status") or "").lower() == "ready_no_changes"
            and isinstance(lifecycle, Mapping)
            and str(lifecycle.get("status") or "").lower() == "completed"
            and isinstance(execution, Mapping)
            and str(execution.get("status") or "").lower() == "best_effort"
            and execution.get("reason_code") == "provider_unavailable"
            and execution.get("failure") is None
            and execution.get("policy_denials") in (None, [])
            and isinstance(artifacts, Mapping)
            and str(artifacts.get("status") or "").lower() == "ready_no_changes"
            and isinstance(objective, Mapping)
            and str(objective.get("status") or "").lower() == "not_evaluated"
        )

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
    ) -> tuple[list[str], Mapping[str, Any], list[Mapping[str, Any]]]:
        if not isinstance(entries, list) or len(entries) > 2000:
            raise OuroborosContractError("tool log entries are invalid or oversized")
        selected: list[tuple[int, str, Mapping[str, Any]]] = []
        seen_calls: dict[tuple[str, str], Mapping[str, Any]] = {}
        recoverable_finalize_indexes: set[int] = set()
        for index, raw in enumerate(entries):
            if not isinstance(raw, Mapping):
                continue
            tool = self._canonical_tool(raw.get("tool"))
            if raw.get("tool") is not None and tool is None:
                raise OuroborosContractError(
                    "non-AGA tool invocation was recorded"
                )
            if tool is not None:
                preview = raw.get("result_preview")
                if isinstance(preview, str) and (
                    preview.startswith("⚠️ MCP_TOOL_ERROR:")
                    or MCP_TOOL_ERROR_MARKER in preview
                ):
                    marker = "⚠️ MCP_TOOL_ERROR:"
                    body = preview.split(marker, 1)[1].strip()
                    service_error: Mapping[str, Any] | None = None
                    if body.startswith("{") and body.endswith("}"):
                        try:
                            service_error = _strict_json(body, "MCP service error")
                        except OuroborosContractError:
                            service_error = None
                        if (
                            isinstance(service_error, Mapping)
                            and service_error.get("type") == "review_service_error"
                            and isinstance(service_error.get("code"), str)
                            and ID_RE.fullmatch(service_error["code"]) is not None
                        ):
                            if (
                                tool == "aga_finalize_review"
                                and service_error["code"]
                                in {"review_digest_mismatch", "task_digest_mismatch"}
                                and self.config.finalize_digest_repair is not None
                            ):
                                recoverable_finalize_indexes.add(index)
                            else:
                                raise OuroborosMCPServiceError(
                                    f"{tool} returned AGA service error "
                                    f"{service_error['code']}"
                                )
                    if index not in recoverable_finalize_indexes:
                        if (
                            tool == "aga_finalize_review"
                            and service_error is None
                            and self.config.finalize_transport_repair is not None
                        ):
                            recoverable_finalize_indexes.add(index)
                            self._transport_finalize_repairs.add(record.task_id)
                        else:
                            raise OuroborosMCPTransportError(
                                f"{tool} returned an MCP transport error"
                            )
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
                # The gateway adds only these two origin markers while merging
                # the byte-identical root and headless-child log rows.  Every
                # other public field is part of the mirrored projection and
                # must agree before the duplicate can be collapsed.
                projection = {
                    item_key: item_value
                    for item_key, item_value in raw.items()
                    if item_key not in {"_source_root", "_line"}
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
        if (
            len(prepares) != 1
            or len(finalizes) != 1
            or not selected
            or selected[0][1] != "aga_prepare_review"
        ):
            raise OuroborosContractError(
                "tool flow must contain one ordered prepare and one final finalize"
            )
        first_finalize_index = finalizes[0][0]
        if any(
            index > first_finalize_index and tool != "aga_finalize_review"
            for index, tool, _entry in selected
        ):
            raise OuroborosContractError(
                "the single public finalize must be the final tool call"
            )
        for _, _, entry in (prepares[0], finalizes[0]):
            if entry.get("task_id") != record.task_id:
                raise OuroborosContractError(
                    "prepare/finalize must be executed by the root review task"
                )
        for index, tool, entry in selected:
            if index in recoverable_finalize_indexes:
                if tool != "aga_finalize_review":
                    raise OuroborosContractError(
                        "only a final finalize failure can be repaired"
                    )
                continue
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
        finalize_args = [item[2].get("args") for item in finalizes]
        if (
            not isinstance(prepare_args, Mapping)
            or any(not isinstance(args, Mapping) for args in finalize_args)
        ):
            raise OuroborosContractError("tool log correlation arguments are missing")
        finalize_args = [dict(args) for args in finalize_args]
        expected_prepare = {
            "repository_id": record.request["repository_id"],
            "base": record.request["base"],
            "head": record.request["head"],
            "review_id": record.request["review_id"],
        }
        if any(prepare_args.get(key) != value for key, value in expected_prepare.items()):
            raise OuroborosContractError("prepare arguments do not match immutable request")
        for args in finalize_args:
            if args.get("review_id") != record.request["review_id"]:
                raise OuroborosContractError("finalize review_id does not match")
            for key in ("review_digest", "task_digest"):
                if not isinstance(args.get(key), str):
                    raise OuroborosContractError(f"finalize {key} is missing")
                if args.get(key) != finalize_args[0].get(key):
                    raise OuroborosContractError(
                        f"finalize retry {key} conflicts with the logical finalize"
                    )
        for _, tool, entry in selected:
            if tool not in {"aga_seaf_lookup", "aga_parse_diagram"}:
                continue
            args = entry.get("args")
            if (
                not isinstance(args, Mapping)
                or args.get("review_id") != record.request["review_id"]
                or (
                    not recoverable_finalize_indexes
                    and args.get("review_digest")
                    != finalize_args[0]["review_digest"]
                )
                or not isinstance(args.get("entity_id"), str)
            ):
                raise OuroborosContractError(
                    f"{tool} receipt correlation mismatch"
                )
        logical_names = [
            tool
            for index, tool, _entry in selected
            if tool != "aga_finalize_review" or index == first_finalize_index
        ]
        return logical_names, prepare_args, finalize_args

    def _aga_receipts(
        self,
        record: _BackendTask,
        finalize_args: Sequence[Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if len(finalize_args) != 1:
            raise OuroborosContractError(
                "trusted AGA prepare/finalize receipt is missing"
            )
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
        expected_prepare_args = {
            "repository_id": record.request["repository_id"],
            "base": record.request["base"],
            "head": record.request["head"],
            "review_id": record.request["review_id"],
        }
        expected_prepare_hash = hashlib.sha256(
            _canonical_bytes(expected_prepare_args)
        ).hexdigest()
        # One review id may retain receipts from an earlier failed attempt.
        # Bind this validation to the finalize digests in the current task log,
        # then select only the closest preceding prepare receipt.  This keeps
        # the append-only audit trail without mixing independent model tasks.
        finalizes = [
            (index, item)
            for index, item in enumerate(matching)
            if item.get("tool") == "aga_finalize_review"
            and item.get("review_digest") == finalize_args[0].get("review_digest")
            and item.get("task_digest") == finalize_args[0].get("task_digest")
        ]
        first_finalize_index = finalizes[0][0] if finalizes else -1
        prepare_candidates = [
            (index, item)
            for index, item in enumerate(matching)
            if item.get("tool") == "aga_prepare_review"
            and item.get("args_sha256") == expected_prepare_hash
            and index < first_finalize_index
        ]
        prepares = prepare_candidates[-1:]
        if (
            len(prepares) != 1
            or len(finalizes) not in {1, 2}
        ):
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
        if prepare.get("args_sha256") != expected_prepare_hash:
            raise OuroborosContractError("trusted prepare arguments mismatch")

        transport_repaired = record.task_id in self._transport_finalize_repairs
        if transport_repaired:
            repair = self.config.finalize_transport_repair
            if repair is None or len(finalizes) not in {1, 2}:
                raise OuroborosContractError(
                    "trusted finalize transport repair is not configured"
                )
            first_hash = finalize.get("args_sha256")
            if SHA256_RE.fullmatch(str(first_hash or "")) is None:
                raise OuroborosContractError(
                    "trusted transport-error finalize input hash is missing"
                )
            for _index, receipt in finalizes:
                receipt_status = receipt.get("status")
                transport_error = (
                    receipt_status == "error"
                    and receipt.get("error_type") is None
                    and receipt.get("error_code") is None
                )
                response_lost_after_commit = (
                    receipt_status in {"ok", "incomplete"}
                    and SHA256_RE.fullmatch(
                        str(receipt.get("output_sha256") or "")
                    )
                    is not None
                )
                if (
                    not (transport_error or response_lost_after_commit)
                    or receipt.get("args_sha256") != first_hash
                    or receipt.get("review_digest") != finalize_args[0].get("review_digest")
                    or receipt.get("task_digest") != finalize_args[0].get("task_digest")
                ):
                    raise OuroborosContractError(
                        "trusted finalize transport-error receipts conflict"
                    )
            try:
                repaired_final = repair(
                    review_id=record.request["review_id"],
                    review_digest=finalize_args[0]["review_digest"],
                    task_digest=finalize_args[0]["task_digest"],
                    args_sha256=first_hash,
                )
            except Exception as exc:
                raise OuroborosContractError(
                    "trusted finalize transport repair failed"
                ) from exc
            if not isinstance(repaired_final, Mapping):
                raise OuroborosContractError(
                    "trusted finalize transport repair returned invalid output"
                )
            self._trusted_final_overrides[record.task_id] = dict(repaired_final)
            try:
                refreshed = source()
            except Exception as exc:
                raise OuroborosContractError(
                    "trusted AGA receipt source is unavailable after transport repair"
                ) from exc
            matching = [
                item
                for item in refreshed
                if isinstance(item, Mapping)
                and item.get("review_id_sha256")
                == hashlib.sha256(
                    record.request["review_id"].encode("utf-8")
                ).hexdigest()
            ]
            refreshed_finalizes = [
                (index, item)
                for index, item in enumerate(matching)
                if item.get("tool") == "aga_finalize_review"
            ]
            if len(refreshed_finalizes) != len(finalizes) + 1:
                raise OuroborosContractError(
                    "trusted finalize transport repair receipt is missing"
                )
            repaired_index, repaired_receipt = refreshed_finalizes[-1]
            if repaired_index <= finalizes[-1][0]:
                raise OuroborosContractError(
                    "trusted finalize transport repair receipts are unordered"
                )
            override_hash = hashlib.sha256(
                _canonical_bytes(self._trusted_final_overrides[record.task_id])
            ).hexdigest()
            if repaired_receipt.get("output_sha256") != override_hash:
                raise OuroborosContractError(
                    "trusted finalize transport repair output hash mismatch"
                )
            finalizes = refreshed_finalizes
            finalize = repaired_receipt

        repaired = finalize.get("status") == "error" and not transport_repaired
        if repaired:
            if (
                finalize.get("error_type") != "review_service_error"
                or finalize.get("error_code")
                not in {"review_digest_mismatch", "task_digest_mismatch"}
            ):
                raise OuroborosContractError(
                    "trusted finalize receipt contains a non-repairable error"
                )
            for key in ("review_digest", "task_digest"):
                if finalize.get(key) != finalize_args[0].get(key):
                    raise OuroborosContractError(
                        f"rejected finalize {key} does not match the public call"
                    )
            if all(
                prepare.get(key) == finalize_args[0].get(key)
                for key in ("review_digest", "task_digest")
            ):
                raise OuroborosContractError(
                    "digest repair was requested without a digest mismatch"
                )
            if len(finalizes) == 1:
                repair = self.config.finalize_digest_repair
                if repair is None:
                    raise OuroborosContractError(
                        "trusted finalize digest repair is not configured"
                    )
                try:
                    repaired_final = repair(
                        review_id=record.request["review_id"],
                        review_digest=prepare.get("review_digest"),
                        task_digest=prepare.get("task_digest"),
                    )
                except Exception as exc:
                    raise OuroborosContractError(
                        "trusted finalize digest repair failed"
                    ) from exc
                if not isinstance(repaired_final, Mapping):
                    raise OuroborosContractError(
                        "trusted finalize digest repair returned invalid output"
                    )
                self._trusted_final_overrides[record.task_id] = dict(repaired_final)
                try:
                    refreshed = source()
                except Exception as exc:
                    raise OuroborosContractError(
                        "trusted AGA receipt source is unavailable after repair"
                    ) from exc
                matching = [
                    item
                    for item in refreshed
                    if isinstance(item, Mapping)
                    and item.get("review_id_sha256")
                    == hashlib.sha256(
                        record.request["review_id"].encode("utf-8")
                    ).hexdigest()
                ]
                finalizes = [
                    (index, item)
                    for index, item in enumerate(matching)
                    if item.get("tool") == "aga_finalize_review"
                ]
            if len(finalizes) != 2 or record.task_id not in self._trusted_final_overrides:
                raise OuroborosContractError(
                    "trusted digest repair receipt is missing"
                )
            repaired_index, repaired_receipt = finalizes[1]
            if repaired_index <= finalize_index:
                raise OuroborosContractError("trusted digest repair receipts are unordered")
            finalize = repaired_receipt
            for key in ("review_digest", "task_digest"):
                if finalize.get(key) != prepare.get(key):
                    raise OuroborosContractError(
                        f"trusted repaired finalize {key} mismatch"
                    )
            override_hash = hashlib.sha256(
                _canonical_bytes(self._trusted_final_overrides[record.task_id])
            ).hexdigest()
            if finalize.get("output_sha256") != override_hash:
                raise OuroborosContractError(
                    "trusted digest repair output hash mismatch"
                )
        elif not transport_repaired:
            # MCP 1.28.1 may replay one byte-identical idempotent finalize
            # after a post-success transport ExceptionGroup.
            finalize_fields = (
                "args_sha256",
                "status",
                "output_status",
                "output_incomplete",
                "output_sha256",
                "review_digest",
                "task_digest",
            )
            finalize_projection = {
                key: finalize.get(key) for key in finalize_fields
            }
            if any(
                {key: item.get(key) for key in finalize_fields} != finalize_projection
                for _index, item in finalizes[1:]
            ):
                raise OuroborosContractError(
                    "trusted finalize retry conflicts with the logical finalize"
                )
            for _index, receipt in finalizes:
                for key in ("review_digest", "task_digest"):
                    if receipt.get(key) != finalize_args[0].get(key):
                        raise OuroborosContractError(
                            f"trusted finalize {key} mismatch"
                        )
        # The packaged CLI deliberately sanitizes deeply nested tool arguments
        # in tools.jsonl (for example, evidence_refs become ``_depth_limit``
        # markers).  Therefore a hash recomputed from the public log projection
        # is not the hash of the request received by AGA.  Correlate each
        # physical call through the unique review id, ordered call count and the
        # unredacted top-level digests instead.  The trusted MCP receipt must
        # still contain the same well-formed hash of its complete input on both
        # physical attempts, and the exact trusted output hash is checked
        # against the terminal answer below.
        receipts_to_validate = (
            [finalize]
            if repaired or transport_repaired
            else [item for _index, item in finalizes]
        )
        for receipt in receipts_to_validate:
            if SHA256_RE.fullmatch(str(receipt.get("args_sha256") or "")) is None:
                raise OuroborosContractError(
                    "trusted finalize input hash is missing"
                )
        for key in ("review_digest", "task_digest"):
            if not repaired and prepare.get(key) != finalize_args[0].get(key):
                raise OuroborosContractError(f"trusted prepare {key} mismatch")
            if not repaired and finalize.get(key) != finalize_args[0].get(key):
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
        trusted_override = self._trusted_final_overrides.get(record.task_id)
        if trusted_override is not None:
            final = dict(trusted_override)
            final_answer_envelope = "trusted_prepare_digest_binding"
        else:
            raw_final = external.get("result")
        if trusted_override is None and isinstance(raw_final, str):
            if len(raw_final.encode("utf-8")) > self.config.max_json_bytes:
                raise OuroborosContractError("final AGA JSON exceeded its bound")
            parsed, final_answer_envelope = _strict_final_json(raw_final)
            if not isinstance(parsed, Mapping):
                raise OuroborosContractError("final task answer must be a JSON object")
            final = dict(parsed)
        elif trusted_override is None:
            raise OuroborosContractError("task result does not contain final AGA JSON")
        expected_receipt_hash = finalize_receipt.get("output_sha256")
        projection_repair = "none"
        expected_hash = hashlib.sha256(_canonical_bytes(final)).hexdigest()
        if expected_hash != expected_receipt_hash:
            # The pinned runtime can project the model's terminal JSON without
            # the empty ``analysis_errors`` member even though the immediately
            # preceding AGA tool result contained it.  Restore exactly this one
            # schema-required empty field only when the resulting canonical
            # object is cryptographically identical to the trusted in-process
            # finalize receipt.  This cannot bless any untrusted finding or
            # non-empty value and every other projection difference still
            # fails closed below.
            if "analysis_errors" not in final:
                candidate = {**final, "analysis_errors": []}
                candidate_hash = hashlib.sha256(
                    _canonical_bytes(candidate)
                ).hexdigest()
                if candidate_hash == expected_receipt_hash:
                    final = candidate
                    expected_hash = candidate_hash
                    projection_repair = "attested_empty_analysis_errors"
            if expected_hash != expected_receipt_hash:
                raise OuroborosContractError(
                    "task answer is not the exact AGA finalize output"
                )
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
            "final_answer_envelope": final_answer_envelope,
            "final_projection_repair": projection_repair,
            "final_digest_binding": (
                "trusted_prepare_once" if trusted_override is not None else "none"
            ),
            "aga_final": final,
        }
        if is_incomplete:
            metadata["error_code"] = "aga_incomplete"
            return TaskResult(
                task_id=record.task_id,
                task_name=self._logical_task_name(),
                status=TaskStatus.FAILED,
                findings=tuple(dict(item) for item in final["findings"]),
                observations=tuple(dict(item) for item in final["observations"]),
                error="aga_incomplete: trusted AGA final is incomplete",
                metadata=metadata,
            )
        return TaskResult(
            task_id=record.task_id,
            task_name=self._logical_task_name(),
            status=TaskStatus.SUCCEEDED,
            findings=tuple(dict(item) for item in final["findings"]),
            observations=tuple(dict(item) for item in final["observations"]),
            metadata=metadata,
        )

    @staticmethod
    def _terminal_accounting_is_final(terminal: Mapping[str, Any]) -> bool:
        """Validate the public terminal uncertainty fields.

        Ouroboros may temporarily expose a split-drive child projection whose
        accounting still has ``cost_final=false`` and may contain nonnegative
        unresolved or unmetered attempts.  That transitional state can only be
        superseded by the strict durable root ``task_cost_finalized`` event
        below.  Malformed fields, unavailable accounting, and degraded ledger
        integrity remain terminal typed failures.
        """

        status = terminal.get("cost_accounting_status")
        if status == "unavailable":
            raise _CostAccountingError(
                "cost_accounting_unavailable",
                "terminal task cost accounting is unavailable",
            )
        if status != "available":
            raise _CostAccountingError(
                "cost_accounting_invalid",
                "terminal task cost accounting status is invalid",
            )
        degraded = terminal.get("ledger_integrity_degraded")
        if degraded is True:
            raise _CostAccountingError(
                "cost_accounting_degraded",
                "terminal task ledger integrity is degraded",
            )
        if degraded is not False:
            raise _CostAccountingError(
                "cost_accounting_invalid",
                "terminal task ledger integrity flag is invalid",
            )

        cost_final = terminal.get("cost_final")
        if cost_final is not True and cost_final is not False:
            raise _CostAccountingError(
                "cost_accounting_invalid",
                "terminal task cost-final flag is invalid",
            )

        unresolved = terminal.get("unresolved_upper_bound_usd")
        if (
            isinstance(unresolved, bool)
            or not isinstance(unresolved, (int, float))
            or not math.isfinite(float(unresolved))
            or float(unresolved) < 0.0
        ):
            raise _CostAccountingError(
                "cost_accounting_invalid",
                "terminal task unresolved-spend field is invalid",
            )
        unknown_unmetered = terminal.get("unknown_unmetered")
        if (
            isinstance(unknown_unmetered, bool)
            or not isinstance(unknown_unmetered, int)
            or unknown_unmetered < 0
        ):
            raise _CostAccountingError(
                "cost_accounting_invalid",
                "terminal task unmetered-attempt field is invalid",
            )
        if cost_final is True and (
            float(unresolved) != 0.0 or unknown_unmetered != 0
        ):
            raise _CostAccountingError(
                "cost_accounting_unresolved",
                "final terminal task ledger contains unresolved spend",
            )

        cost = terminal.get("cost_usd")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or float(cost) < 0.0
        ):
            raise _CostAccountingError(
                "cost_accounting_invalid",
                "terminal task ledger cost is invalid",
            )
        for key in ("total_rounds", "prompt_tokens", "completion_tokens"):
            value = terminal.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (1 if key == "total_rounds" else 0)
            ):
                raise _CostAccountingError(
                    "cost_accounting_invalid",
                    "terminal task ledger counters are invalid",
                )

        return cost_final is True

    @staticmethod
    def _validated_finalized_cost_event(
        record: _BackendTask, entries: Sequence[Any]
    ) -> Mapping[str, Any] | None:
        """Return the latest exact durable root-cost checkpoint, if final.

        The gateway returns entries in durable order and includes child-drive
        logs.  A root can also emit a provisional checkpoint before a late
        naming attempt settles, followed by a superseding ``refresh`` event.
        Only the latest exact-root projection is therefore authoritative.
        """

        root_events = [
            item
            for item in entries
            if isinstance(item, Mapping)
            and item.get("type") == "task_cost_finalized"
            and item.get("task_id") == record.task_id
            and item.get("root_task_id") == record.task_id
        ]
        if not root_events:
            return None

        item = root_events[-1]
        if (
            item.get("post_task_status") not in {"completed", "degraded"}
            or item.get("cost_accounting_status") != "available"
            or item.get("ledger_integrity_degraded") is not False
            or not isinstance(item.get("cost_final"), bool)
            or not isinstance(item.get("cost_with_children_partial"), bool)
        ):
            raise _CostAccountingError(
                "cost_finalized_event_invalid",
                "root task cost-finalized event is malformed",
            )
        for key in (
            "cost_usd",
            "cost_usd_with_children",
            "reserved_usd",
            "unresolved_upper_bound_usd",
        ):
            value = item.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0.0
            ):
                raise _CostAccountingError(
                    "cost_finalized_event_invalid",
                    "root task cost-finalized totals are invalid",
                )
        for key in ("total_rounds", "prompt_tokens", "completion_tokens"):
            value = item.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (1 if key == "total_rounds" else 0)
            ):
                raise _CostAccountingError(
                    "cost_finalized_event_invalid",
                    "root task cost-finalized counters are invalid",
                )
        unknown = item.get("unknown_unmetered")
        if (
            isinstance(unknown, bool)
            or not isinstance(unknown, int)
            or unknown < 0
            or float(item["cost_usd_with_children"]) < float(item["cost_usd"])
        ):
            raise _CostAccountingError(
                "cost_finalized_event_invalid",
                "root task cost-finalized event has invalid uncertainty fields",
            )
        if (
            item.get("cost_final") is not True
            or item.get("cost_with_children_partial") is not False
            or float(item["reserved_usd"]) != 0.0
            or float(item["unresolved_upper_bound_usd"]) != 0.0
            or unknown != 0
        ):
            raise _CostAccountingPending(
                "latest root task cost-finalized event is still provisional"
            )
        return item

    def _validated_model_usage(
        self,
        record: _BackendTask,
        terminal: Mapping[str, Any],
        *,
        deadline: float | None = None,
    ) -> Mapping[str, Any]:
        terminal_cost_final = self._terminal_accounting_is_final(terminal)
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
        observed_cost = Decimal("0")
        observed_prompt_tokens = 0
        observed_completion_tokens = 0
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
            raw_cost = raw.get("cost")
            if (
                raw.get("cost_known") is not True
                or isinstance(raw_cost, bool)
                or not isinstance(raw_cost, (int, float))
                or not math.isfinite(float(raw_cost))
                or float(raw_cost) < 0.0
            ):
                raise OuroborosContractError(
                    "LLM physical-attempt cost projection is invalid"
                )
            raw_tokens: dict[str, int] = {}
            for key in ("prompt_tokens", "completion_tokens"):
                value = raw.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise OuroborosContractError(
                        "LLM physical-attempt token projection is invalid"
                    )
                raw_tokens[key] = value
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
                    "cost_known",
                    "cost",
                    "prompt_tokens",
                    "completion_tokens",
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
            observed_cost += Decimal(str(raw_cost))
            observed_prompt_tokens += raw_tokens["prompt_tokens"]
            observed_completion_tokens += raw_tokens["completion_tokens"]
        accounting = terminal
        accounting_authority = "terminal_task_ledger"
        if not terminal_cost_final:
            finalized = self._validated_finalized_cost_event(record, entries)
            if finalized is None:
                raise _CostAccountingPending(
                    "root task cost-finalized event is not visible yet"
                )
            accounting = finalized
            accounting_authority = "root_task_cost_finalized_event"

        if not usage_rows:
            raise OuroborosContractError("no correlated LLM usage event was recorded")

        cost = accounting.get("cost_usd")
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or float(cost) < 0
        ):
            raise _CostAccountingError(
                "cost_accounting_invalid", "authoritative task ledger cost is invalid"
            )
        total_rounds = accounting.get("total_rounds")
        if (
            isinstance(total_rounds, bool)
            or not isinstance(total_rounds, int)
            or total_rounds < 1
        ):
            raise _CostAccountingError(
                "cost_accounting_invalid",
                "authoritative task ledger physical-call count is invalid",
            )
        observed_call_count = len(attempt_projections)
        unobserved_call_count = total_rounds - observed_call_count
        if unobserved_call_count < 0 or (
            unobserved_call_count > 0
            and self.config.all_model_routes_pinned is not True
        ):
            raise _CostAccountingError(
                "cost_accounting_totals_mismatch",
                "authoritative task ledger call count does not match physical attempts",
            )
        terminal_tokens: dict[str, int] = {}
        for key in ("prompt_tokens", "completion_tokens"):
            value = accounting.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise _CostAccountingError(
                    "cost_accounting_invalid",
                    "authoritative task ledger token accounting is invalid",
                )
            terminal_tokens[key] = value

        # Ouroboros' authoritative projection is deliberately rounded to six
        # decimal USD while each physical-attempt event retains more precision.
        # When every call is visible, require equality modulo only that maximum
        # half-unit cost rounding delta and exact token totals.  An attested
        # hidden-call gap retains one-sided lower-bound validation because its
        # per-attempt projections are, by definition, unavailable here.
        authoritative_cost = Decimal(str(cost))
        if unobserved_call_count == 0:
            totals_mismatch = (
                abs(authoritative_cost - observed_cost) > Decimal("0.0000005")
                or terminal_tokens["prompt_tokens"] != observed_prompt_tokens
                or terminal_tokens["completion_tokens"]
                != observed_completion_tokens
            )
        else:
            totals_mismatch = (
                authoritative_cost + Decimal("0.0000005") < observed_cost
                or terminal_tokens["prompt_tokens"] < observed_prompt_tokens
                or terminal_tokens["completion_tokens"]
                < observed_completion_tokens
            )
        if totals_mismatch:
            raise _CostAccountingError(
                "cost_accounting_totals_mismatch",
                "authoritative task ledger totals do not match observed attempts",
            )

        return {
            "provider": "openrouter",
            "model": self.config.model_id,
            "accounting_authority": accounting_authority,
            "call_count": total_rounds,
            "usage_event_count": len(usage_rows),
            "observed_call_count": observed_call_count,
            "unobserved_call_count": unobserved_call_count,
            "all_model_routes_pinned": self.config.all_model_routes_pinned,
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
        except (OuroborosBackendError, OSError, TypeError, ValueError):
            return False
        if completed.returncode != 0:
            return False
        try:
            raw = completed.stdout.encode("utf-8")
            if len(raw) > self.config.max_json_bytes:
                return False
            payload = _strict_json(completed.stdout, "task cancellation output")
        except (OuroborosBackendError, OSError, TypeError, ValueError):
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
        except (OSError, TypeError, ValueError) as exc:
            return self._failure(record, "cli_error", str(exc))
        status = str(external.get("status") or "").strip().lower()
        if status in PENDING_STATUSES:
            return TaskResult(
                task_id=task_id,
                task_name=self._logical_task_name(),
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
        with self._lock:
            record.terminal_completed = True
            if external.get("cost_final") is False:
                record.cost_finalization_pending = True
        if self._external_artifact_pending(external):
            return TaskResult(
                task_id=task_id,
                task_name=self._logical_task_name(),
                status=TaskStatus.PENDING,
                metadata={"external_status": "artifact_finalizing"},
            )
        external_success = self._external_success(external)
        finalize_recovery_candidate = (
            self.config.finalize_transport_repair is not None
            and self._external_finalize_recovery_candidate(external)
        )
        if not external_success and not finalize_recovery_candidate:
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
            if (
                not external_success
                and record.task_id not in self._transport_finalize_repairs
            ):
                return self._failure(
                    record,
                    "external_objective_failed",
                    "provider failure was not preceded by a recoverable exact finalize",
                    external_status=status,
                )
        except CommandTimeoutError:
            if deadline is not None:
                raise
            return self._failure(record, "invalid_aga_receipt", "command timeout")
        except OuroborosMCPTransportError as exc:
            return self._failure(
                record,
                "mcp_tool_transport_error",
                str(exc),
                external_status=status,
            )
        except OuroborosMCPServiceError as exc:
            return self._failure(
                record,
                "mcp_tool_service_error",
                str(exc),
                external_status=status,
            )
        except OuroborosBackendError as exc:
            return self._failure(
                record,
                "invalid_aga_receipt",
                str(exc),
                external_status=status,
            )
        except (OSError, TypeError, ValueError) as exc:
            return self._failure(
                record,
                "invalid_aga_receipt",
                str(exc),
                external_status=status,
            )
        try:
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
        except _CostAccountingPending:
            with self._lock:
                record.cost_finalization_pending = True
            return TaskResult(
                task_id=task_id,
                task_name=self._logical_task_name(),
                status=TaskStatus.PENDING,
                metadata={
                    "external_status": "cost_finalizing",
                    "review_id": record.request["review_id"],
                },
            )
        except _CostAccountingError as exc:
            return self._failure(
                record,
                exc.code,
                str(exc),
                external_status=status,
            )
        except CommandTimeoutError:
            if deadline is not None:
                raise
            return self._failure(record, "provider_usage_invalid", "command timeout")
        except OuroborosBackendError as exc:
            return self._failure(
                record,
                "provider_usage_invalid",
                str(exc),
                external_status=status,
            )
        except (OSError, TypeError, ValueError) as exc:
            return self._failure(
                record,
                "provider_usage_invalid",
                str(exc),
                external_status=status,
            )
        with self._lock:
            record.cost_finalization_pending = False
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
            cost_finalization_timeout = record.cost_finalization_pending
            terminal_validation_timeout = (
                record.terminal_completed and not cost_finalization_timeout
            )
            if not record.cancel_attempted:
                self._cancel_timed_out_task(record)
            error_code = (
                "cost_finalization_timeout"
                if cost_finalization_timeout
                else "terminal_validation_timeout"
                if terminal_validation_timeout
                else "task_timeout"
            )
            external_status = (
                "cost_finalizing"
                if cost_finalization_timeout
                else "completed"
                if terminal_validation_timeout
                else "timed_out"
            )
            error = (
                "cost_finalization_timeout: terminal review cost did not finalize "
                f"within the {budget:g} second wait budget"
                if cost_finalization_timeout
                else "terminal_validation_timeout: completed review did not finish "
                f"trusted validation within the {budget:g} second wait budget"
                if terminal_validation_timeout
                else f"task exceeded timeout of {budget:g} seconds"
            )
            result = TaskResult(
                task_id=task_id,
                task_name=self._logical_task_name(),
                status=TaskStatus.TIMED_OUT,
                error=error,
                metadata={
                    "error_code": error_code,
                    "external_status": external_status,
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
    "EXPECTED_TOOLS",
    "MANAGED_TASK_SCHEMA",
    "REMEDIATION_MCP_TOOLS",
    "REVIEW_MCP_STAGE",
    "OuroborosBackendConfig",
    "OuroborosBackendError",
    "OuroborosContractError",
    "OuroborosIdempotencyConflict",
    "OuroborosNotConfiguredError",
    "OuroborosTaskBackend",
]
