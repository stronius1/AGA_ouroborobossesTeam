#!/usr/bin/env python3
"""Trusted one-case Ouroboros -> AGA MCP end-to-end runner.

The command has no credential input.  It starts a loopback-only AGA MCP
server for one locked synthetic-public repository, executes the read-only
Ouroboros preflight, and only then schedules a paid task.  A capture is written
atomically after trusted receipts, the local scorer, and workspace-integrity
checks all pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
import urllib.error
import urllib.request
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGA_SKILL_ROOT = REPOSITORY_ROOT / "aga-skill"
for import_root in (REPOSITORY_ROOT, AGA_SKILL_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from evaluation.gigaagent import runner as evaluator  # noqa: E402
from scripts import materialize_ouroboros_cases as materializer  # noqa: E402
from scripts import ouroboros_preflight as preflight  # noqa: E402
from tools.a2a import TaskBackend, TaskResult, TaskStatus  # noqa: E402
from tools.mcp_server import (  # noqa: E402
    MCPServer,
    MCPServerConfig,
    SchemaViolation,
    validate_json_schema,
)
from tools.ouroboros_backend import (  # noqa: E402
    CommandOutputTooLargeError,
    CommandTimeoutError,
    OuroborosBackendConfig,
    OuroborosBackendError,
    OuroborosContractError,
    OuroborosIdempotencyConflict,
    OuroborosNotConfiguredError,
    OuroborosTaskBackend,
)
from tools.review_service import ReviewService, TOOL_DEFINITIONS  # noqa: E402


EVIDENCE_SCHEMA = "aga.ouroboros-run-sanitized/v1"
CLI_RESULT_SCHEMA = "aga.ouroboros-e2e-result/v1"
DEFAULT_CASE_ID = "ga-05-critical-eliminate"
PINNED_VERSION = preflight.PINNED_VERSION
PROVIDER = preflight.EXPECTED_PROVIDER
MODEL_ID = preflight.EXPECTED_MODEL
MCP_HOST = "127.0.0.1"
MCP_PORT = 8788
MCP_ENDPOINT = "/mcp"
GATEWAY_URL = "http://127.0.0.1:8765"
PROMPT_PATH = (
    REPOSITORY_ROOT
    / "aga-skill"
    / "prompts"
    / "ouroboros-orchestration-v1.1.0.txt"
)
DEFAULT_EVIDENCE_OUT = (
    REPOSITORY_ROOT / "docs" / "evidence" / "ouroboros" / "run-sanitized.json"
)
_PRIVATE_TMP = Path("/private/tmp")
_SAFE_TEMP_BASE = _PRIVATE_TMP if _PRIVATE_TMP.is_dir() else Path("/tmp")
DEFAULT_MATERIALIZED_ROOT = (
    _SAFE_TEMP_BASE / "aga-synthetic-public" / "ouroboros-cases"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9/])/(?!/)(?:\S+|$)"
)
POSIX_NETWORK_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9/:])/{2,}(?:[^/\s]+(?:/\S*)?|$)"
)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9/\\])[A-Za-z]:[\\/]"
)
WINDOWS_NETWORK_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9/\\])\\{2,}(?:[^\\/\s]+(?:[\\/]\S*)?|$)"
)
WINDOWS_ROOTED_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9/\\])\\(?!\\)(?:\S+|$)"
)
FILE_URI_RE = re.compile(r"(?i)(?<![A-Za-z0-9])file:/+")
JSON_POINTER_RE = re.compile(r"^(?:/(?:[^~/\s]|~[01])+)+$")
PROJECT_RELATIVE_PATH_RE = re.compile(
    r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+$"
)
SOURCE_REF_RE = re.compile(
    r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*#(?:/(?:[^~/\s]|~[01])+)+$"
)
CANONICAL_DEFECT_RULE_RE = re.compile(r"^[A-Z][A-Z0-9-]{1,31}$")
_JSON_POINTER_FIELDS = frozenset({"field", "location", "pointer"})
_JSON_POINTER_ROOTS = frozenset(
    {
        "aga",
        "agent",
        "components",
        "contexts",
        "docs",
        "entities",
        "rules",
        "seaf.app.integrations",
        "seaf.change.adr",
    }
)
MAX_CAPTURE_BYTES = 2_000_000
MAX_TASK_TIMEOUT_SECONDS = 3_000.0
# Ouroboros v6.64.1 exposes temperature as optional per-call intent, does not
# expose top_p/seed through the managed task contract, and its main loop omits
# all three.  Record that limitation in the secret-free configuration identity
# instead of claiming deterministic sampling.  Stability is therefore proven
# only by distinct repeated captures plus conservative aggregation.
INFERENCE_CONTROL = {
    "temperature": {"requested": False, "value": None},
    "top_p": {"requested": False, "value": None},
    "seed": {"supported": False, "value": None},
    "provider_sampling_determinism_claimed": False,
    "mitigation": "five_distinct_repeats_conservative_gate",
}


class E2ERunnerError(RuntimeError):
    """Sanitized typed failure returned by the command boundary."""

    def __init__(self, status: str, code: str) -> None:
        if status not in {"not_configured", "failed"}:
            raise ValueError("invalid E2E failure status")
        self.status = status
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PreflightReady:
    payload: Mapping[str, Any]
    executable: str


class ServerHandle(Protocol):
    trace: Sequence[Mapping[str, Any]]

    def __enter__(self) -> "ServerHandle": ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...


Materialize = Callable[..., Mapping[str, Any]]
ServerFactory = Callable[[str, Path], ServerHandle]
PreflightCheck = Callable[[], PreflightReady]
BackendFactory = Callable[[Path, ServerHandle, str, float, bool], TaskBackend]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _review_id() -> str:
    return f"aga-{uuid.uuid4().hex}"


def _default_server_factory(repository_id: str, workspace: Path) -> MCPServer:
    service = ReviewService(
        repositories={
            repository_id: {
                "repository": workspace,
                "manifest_path": "dochub.yaml",
                "dependency_mode": "fixture",
            }
        },
        ttl_seconds=900.0,
        prepare_timeout_seconds=15.0,
        max_prepare_workers=4,
    )
    config = MCPServerConfig(
        host=MCP_HOST,
        port=MCP_PORT,
        endpoint=MCP_ENDPOINT,
        mode="none",
        bearer_token=None,
        request_timeout_seconds=20.0,
        max_concurrency=4,
    )
    return MCPServer(service, config=config)


def _default_preflight() -> PreflightReady:
    executable = preflight._find_executable()  # project-owned, secret-safe lookup
    if executable is None:
        raise E2ERunnerError("not_configured", "runtime_not_installed")
    payload, exit_code = preflight.run_preflight(
        preflight.BoundedCommandRunner(executable)
    )
    if exit_code != preflight.EXIT_READY:
        status = payload.get("status") if isinstance(payload, Mapping) else None
        code = payload.get("code") if isinstance(payload, Mapping) else None
        safe_status = "not_configured" if status == "not_configured" else "failed"
        safe_code = code if isinstance(code, str) and code else "preflight_failed"
        raise E2ERunnerError(safe_status, safe_code)
    return PreflightReady(payload=dict(payload), executable=executable)


def _register_local_project(project_id: str) -> None:
    """Idempotently register an isolated hashed scope before task creation."""

    if re.fullmatch(r"aga-[0-9a-f]{32}", project_id) is None:
        raise OuroborosContractError("local project id is invalid")
    body = json.dumps(
        {"id": project_id, "name": "AGA synthetic-public review"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{GATEWAY_URL}/api/projects",
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5.0) as response:
            if response.status != 200:
                raise OuroborosNotConfiguredError(
                    "local project registration was rejected"
                )
            raw = response.read(65_537)
    except (OSError, urllib.error.URLError) as exc:
        raise OuroborosNotConfiguredError(
            "local project registration is unavailable"
        ) from exc
    if len(raw) > 65_536:
        raise OuroborosContractError(
            "local project registration response is oversized"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OuroborosContractError(
            "local project registration response is invalid"
        ) from exc
    project = payload.get("project") if isinstance(payload, Mapping) else None
    if not isinstance(project, Mapping) or project.get("id") != project_id:
        raise OuroborosContractError(
            "local project registration correlation failed"
        )


def _default_backend_factory(
    workspace: Path,
    server: ServerHandle,
    executable: str,
    timeout_seconds: float,
    all_model_routes_pinned: bool,
) -> OuroborosTaskBackend:
    return OuroborosTaskBackend(
        OuroborosBackendConfig(
            command_prefix=(executable,),
            gateway_url=GATEWAY_URL,
            runtime_version=PINNED_VERSION,
            model_id=MODEL_ID,
            workspaces={workspace.name: workspace},
            prompt_path=PROMPT_PATH,
            task_timeout_seconds=timeout_seconds,
            server_id=preflight.MCP_SERVER_ID,
            receipt_source=lambda: tuple(server.trace),
            project_registrar=_register_local_project,
            all_model_routes_pinned=all_model_routes_pinned,
            disable_diagram_tool=True,
        )
    )


@dataclass(frozen=True)
class _Dependencies:
    materialize: Materialize = materializer.materialize_cases
    server_factory: ServerFactory = _default_server_factory
    preflight_check: PreflightCheck = _default_preflight
    backend_factory: BackendFactory = _default_backend_factory
    materialized_root: Path = DEFAULT_MATERIALIZED_ROOT
    evidence_root: Path = REPOSITORY_ROOT
    review_id_factory: Callable[[], str] = _review_id
    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = _utc_now


@dataclass(frozen=True)
class TrustedCaseRun:
    case_id: str
    response: Mapping[str, Any]
    evidence: Mapping[str, Any]
    score: Mapping[str, Any]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise E2ERunnerError("failed", "clock_not_utc")
    utc = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _case_metadata(
    case_id: str,
    *,
    dependencies: _Dependencies,
) -> tuple[Mapping[str, Any], Path, str]:
    try:
        manifest = dependencies.materialize(
            output_root=dependencies.materialized_root,
            case_ids=(case_id,),
            split=None,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise E2ERunnerError("failed", "materialization_failed") from exc
    if not isinstance(manifest, Mapping):
        raise E2ERunnerError("failed", "materialization_contract_mismatch")
    expected_keys = {
        "schema",
        "corpus_hash",
        "data_classification",
        "path_base",
        "cases",
    }
    if set(manifest) != expected_keys:
        raise E2ERunnerError("failed", "materialization_contract_mismatch")
    try:
        locked_digest = evaluator.verify_lock(evaluator.corpus_files())
    except (OSError, TypeError, ValueError) as exc:
        raise E2ERunnerError("failed", "corpus_lock_failed") from exc
    records = manifest.get("cases")
    if (
        manifest.get("schema") != materializer.MANIFEST_SCHEMA
        or manifest.get("corpus_hash") != locked_digest
        or manifest.get("data_classification") != "synthetic-public"
        or manifest.get("path_base") != "manifest_directory"
        or not isinstance(records, list)
        or len(records) != 1
        or not isinstance(records[0], Mapping)
    ):
        raise E2ERunnerError("failed", "materialization_contract_mismatch")
    record = records[0]
    required = {
        "case_id",
        "split",
        "repository_id",
        "repository_path",
        "base_revision",
        "head_revision",
        "changed_files",
        "data_classification",
    }
    if set(record) != required:
        raise E2ERunnerError("failed", "materialization_contract_mismatch")
    if (
        record.get("case_id") != case_id
        or record.get("repository_id") != case_id
        or record.get("data_classification") != "synthetic-public"
        or record.get("split") not in {"development", "holdout"}
    ):
        raise E2ERunnerError("failed", "materialization_contract_mismatch")
    relative = record.get("repository_path")
    if not isinstance(relative, str):
        raise E2ERunnerError("failed", "materialization_contract_mismatch")
    portable = PurePosixPath(relative)
    if (
        portable.is_absolute()
        or portable.as_posix() != relative
        or not portable.parts
        or any(part in {"", ".", ".."} for part in portable.parts)
    ):
        raise E2ERunnerError("failed", "unsafe_materialized_path")
    try:
        root = Path(dependencies.materialized_root).resolve(strict=True)
        workspace = (root / Path(*portable.parts)).resolve(strict=True)
        workspace.relative_to(root)
    except (OSError, ValueError) as exc:
        raise E2ERunnerError("failed", "unsafe_materialized_path") from exc
    if workspace.is_symlink() or not workspace.is_dir() or workspace.name != case_id:
        raise E2ERunnerError("failed", "unsafe_materialized_path")
    return record, workspace, locked_digest


def _workspace_state(workspace: Path, expected_head: str) -> Mapping[str, str]:
    try:
        head = evaluator.git(workspace, "rev-parse", "--verify", "HEAD^{commit}")
        status = evaluator.git(
            workspace, "status", "--porcelain=v1", "--untracked-files=all"
        )
        refs = evaluator.git(
            workspace,
            "for-each-ref",
            "--format=%(refname)%00%(objectname)",
        )
    except (OSError, ValueError) as exc:
        raise E2ERunnerError("failed", "workspace_verification_failed") from exc
    if head != expected_head or status:
        raise E2ERunnerError("failed", "workspace_not_clean")
    return {"head": head, "status": status, "refs_sha256": hashlib.sha256(refs.encode()).hexdigest()}


def _prompt_template_sha256() -> str:
    try:
        text = PROMPT_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise E2ERunnerError("not_configured", "orchestration_prompt_missing") from exc
    markers = (
        "{{REPOSITORY_ID}}",
        "{{BASE_REVISION}}",
        "{{HEAD_REVISION}}",
        "{{REVIEW_ID}}",
        "{{DATA_CLASSIFICATION}}",
    )
    if any(text.count(marker) != 1 for marker in markers):
        raise E2ERunnerError("failed", "orchestration_prompt_contract_mismatch")
    try:
        case_ids = [
            str(case["id"])
            for case in evaluator._cases_from_paths(evaluator.corpus_files())
        ]
    except (OSError, TypeError, ValueError) as exc:
        raise E2ERunnerError("failed", "corpus_lock_failed") from exc
    if any(case_id in text for case_id in case_ids):
        raise E2ERunnerError("failed", "case_specific_prompt_forbidden")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _final_output_schema() -> Mapping[str, Any]:
    return next(
        tool["outputSchema"]
        for tool in TOOL_DEFINITIONS
        if tool["name"] == "aga_finalize_review"
    )


def _require_sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise E2ERunnerError("failed", code)
    return value


def _trusted_receipts(
    trace: Sequence[Mapping[str, Any]],
    *,
    review_id: str,
    metadata: Mapping[str, Any],
    final: Mapping[str, Any],
) -> Mapping[str, Any]:
    if isinstance(trace, (str, bytes)) or not isinstance(trace, Sequence):
        raise E2ERunnerError("failed", "trusted_receipts_missing")
    review_hash = hashlib.sha256(review_id.encode("utf-8")).hexdigest()
    all_matching = [
        dict(item)
        for item in trace
        if isinstance(item, Mapping) and item.get("review_id_sha256") == review_hash
    ]
    # Receipt journals are append-only and may contain an earlier failed model
    # attempt for the same logical review id.  Select the attempt whose latest
    # finalize is bound to the trusted final returned by this exact task, then
    # validate only the contiguous group beginning at its closest prepare.
    target_finalizes = [
        index
        for index, item in enumerate(all_matching)
        if item.get("tool") == "aga_finalize_review"
        and item.get("review_digest") == final.get("review_digest")
        and item.get("task_digest") == final.get("task_digest")
    ]
    if not target_finalizes:
        raise E2ERunnerError("failed", "trusted_receipts_missing")
    target_finalize_index = target_finalizes[-1]
    target_prepares = [
        index
        for index, item in enumerate(all_matching[:target_finalize_index])
        if item.get("tool") == "aga_prepare_review"
    ]
    if not target_prepares:
        raise E2ERunnerError("failed", "trusted_receipts_missing")
    attempt_start = target_prepares[-1]
    next_prepares = [
        index
        for index, item in enumerate(all_matching[attempt_start + 1 :], attempt_start + 1)
        if item.get("tool") == "aga_prepare_review"
    ]
    attempt_end = next_prepares[0] if next_prepares else len(all_matching)
    matching = all_matching[attempt_start:attempt_end]
    physical_names = [item.get("tool") for item in matching]
    allowed = set(preflight.MCP_TOOL_NAMES)
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
    if (
        not physical_names
        or any(name not in allowed for name in physical_names)
        or len(prepares) != 1
        or len(finalizes) not in {1, 2}
        or physical_names[0] != "aga_prepare_review"
    ):
        raise E2ERunnerError("failed", "trusted_receipts_missing")
    first_finalize_index, finalize = finalizes[0]
    if any(
        index > first_finalize_index
        and item.get("tool") != "aga_finalize_review"
        for index, item in enumerate(matching)
    ):
        raise E2ERunnerError("failed", "trusted_receipts_missing")
    digest_binding = metadata.get("final_digest_binding")
    repaired_binding = digest_binding == "trusted_prepare_once"
    if digest_binding not in {None, "none", "trusted_prepare_once"}:
        raise E2ERunnerError("failed", "tool_receipt_correlation_failed")
    finalize_fields = (
        "args_sha256",
        "status",
        "output_status",
        "output_incomplete",
        "output_sha256",
        "review_digest",
        "task_digest",
    )
    for _index, item in finalizes:
        _require_sha256(item.get("args_sha256"), "final_receipt_hash_missing")
    if repaired_binding:
        if (
            len(finalizes) != 2
            or finalize.get("status") != "error"
            or finalize.get("error_type") != "review_service_error"
            or finalize.get("error_code")
            not in {"review_digest_mismatch", "task_digest_mismatch"}
        ):
            raise E2ERunnerError("failed", "tool_receipt_correlation_failed")
        finalize = finalizes[1][1]
        if all(
            finalizes[0][1].get(key) == final.get(key)
            for key in ("review_digest", "task_digest")
        ):
            raise E2ERunnerError("failed", "tool_receipt_correlation_failed")
    else:
        finalize_projection = {
            key: finalize.get(key) for key in finalize_fields
        }
        if any(
            {key: item.get(key) for key in finalize_fields} != finalize_projection
            for _index, item in finalizes[1:]
        ):
            raise E2ERunnerError("failed", "tool_receipt_correlation_failed")
    logical = [
        item
        for index, item in enumerate(matching)
        if item.get("tool") != "aga_finalize_review"
        or index == first_finalize_index
    ]
    names = [item.get("tool") for item in logical]
    metadata_names = metadata.get("tool_names")
    if not isinstance(metadata_names, list) or names != metadata_names:
        raise E2ERunnerError("failed", "tool_receipt_correlation_failed")
    optional_receipts = [
        item
        for item in matching
        if item.get("tool") in {"aga_seaf_lookup", "aga_parse_diagram"}
    ]
    if any(item.get("status") != "ok" for item in optional_receipts):
        raise E2ERunnerError("failed", "trusted_optional_tool_failed")
    prepare = prepares[0][1]
    if (
        prepare.get("status") != "ok"
        or prepare.get("output_status") != "ready"
        or prepare.get("output_incomplete") is not False
    ):
        raise E2ERunnerError("failed", "trusted_prepare_incomplete")
    expected_finalize = (
        ("ok", "completed", False)
        if final.get("status") == "completed"
        else ("incomplete", "incomplete", True)
    )
    actual_finalize = (
        finalize.get("status"),
        finalize.get("output_status"),
        finalize.get("output_incomplete"),
    )
    if actual_finalize != expected_finalize:
        raise E2ERunnerError("failed", "trusted_finalize_status_mismatch")
    prepare_output = _require_sha256(
        metadata.get("prepare_output_sha256"), "prepare_receipt_hash_missing"
    )
    final_output = _require_sha256(
        metadata.get("final_output_sha256"), "final_receipt_hash_missing"
    )
    if (
        prepare.get("output_sha256") != prepare_output
        or finalize.get("output_sha256") != final_output
        or prepare.get("review_digest") != final.get("review_digest")
        or prepare.get("task_digest") != final.get("task_digest")
        or finalize.get("review_digest") != final.get("review_digest")
        or finalize.get("task_digest") != final.get("task_digest")
    ):
        raise E2ERunnerError("failed", "tool_receipt_correlation_failed")
    return {
        "review_id_sha256": review_hash,
        "tool_names": list(names),
        "final_digest_binding": digest_binding or "none",
        "prepare": {
            "args_sha256": _require_sha256(
                prepare.get("args_sha256"), "prepare_receipt_hash_missing"
            ),
            "output_sha256": prepare_output,
            "status": "ready",
        },
        "finalize": {
            "args_sha256": _require_sha256(
                finalize.get("args_sha256"), "final_receipt_hash_missing"
            ),
            "output_sha256": final_output,
            "status": str(final.get("status")),
        },
    }


def _normalise_final(final: Mapping[str, Any]) -> Mapping[str, Any]:
    findings = final.get("findings")
    if not isinstance(findings, list):
        raise E2ERunnerError("failed", "final_result_contract_mismatch")
    keys = (
        "rule_id",
        "severity",
        "confidence",
        "artifact",
        "location",
        "evidence",
        "source_ref",
        "suggested_fix",
    )
    normalized_findings: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, Mapping) or any(key not in finding for key in keys):
            raise E2ERunnerError("failed", "final_result_contract_mismatch")
        normalized_findings.append({key: finding[key] for key in keys})
    return {
        "status": "complete" if final.get("status") == "completed" else "incomplete",
        "verdict": final.get("verdict"),
        "findings": normalized_findings,
    }


def _task_response(
    result: TaskResult,
    *,
    record: Mapping[str, Any],
    review_id: str,
    trace: Sequence[Mapping[str, Any]],
    latency_ms: float,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    metadata = result.metadata
    if not isinstance(metadata, Mapping):
        raise E2ERunnerError("failed", "task_metadata_missing")
    trusted_incomplete = (
        result.status is TaskStatus.FAILED
        and metadata.get("error_code") == "aga_incomplete"
    )
    if result.status is not TaskStatus.SUCCEEDED and not trusted_incomplete:
        code = metadata.get("error_code")
        safe_code = code if isinstance(code, str) and code else "ouroboros_task_failed"
        raise E2ERunnerError("failed", safe_code)
    final = metadata.get("aga_final")
    if not isinstance(final, Mapping):
        raise E2ERunnerError("failed", "trusted_final_missing")
    try:
        validate_json_schema(final, _final_output_schema(), "$final")
    except SchemaViolation as exc:
        raise E2ERunnerError("failed", "final_result_contract_mismatch") from exc
    if final.get("review_id") != review_id or metadata.get("review_id") != review_id:
        raise E2ERunnerError("failed", "review_correlation_failed")
    if final.get("auto_merge") is not False or metadata.get("auto_merge") is not False:
        raise E2ERunnerError("failed", "auto_merge_not_forbidden")
    if trusted_incomplete:
        if (
            final.get("status") != "incomplete"
            or final.get("verdict") != "incomplete"
            or final.get("incomplete") is not True
            or final.get("human_review_required") is not True
        ):
            raise E2ERunnerError("failed", "incomplete_result_contract_mismatch")
    elif (
        final.get("status") != "completed"
        or final.get("incomplete") is not False
        or final.get("verdict") == "incomplete"
    ):
        raise E2ERunnerError("failed", "completed_result_contract_mismatch")
    if (
        final.get("verdict") == "request_changes_escalate"
        and final.get("human_review_required") is not True
    ):
        raise E2ERunnerError("failed", "hitl_not_required")
    if metadata.get("runtime") != {"name": "ouroboros", "version": PINNED_VERSION}:
        raise E2ERunnerError("failed", "runtime_attestation_mismatch")
    if metadata.get("provider") != PROVIDER or metadata.get("model") != {"name": MODEL_ID}:
        raise E2ERunnerError("failed", "provider_model_attestation_mismatch")
    usage = metadata.get("model_usage")
    if not isinstance(usage, Mapping):
        raise E2ERunnerError("failed", "model_usage_missing")
    call_count = usage.get("call_count")
    known_cost = usage.get("known_cost_usd")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    unresolved_cost = usage.get("unresolved_upper_bound_usd", 0.0)
    unknown_unmetered = usage.get("unknown_unmetered", 0)
    if (
        usage.get("provider") != PROVIDER
        or usage.get("model") != MODEL_ID
        or isinstance(call_count, bool)
        or not isinstance(call_count, int)
        or call_count < 1
        or isinstance(known_cost, bool)
        or not isinstance(known_cost, (int, float))
        or not math.isfinite(float(known_cost))
        or float(known_cost) < 0
        or usage.get("cost_complete") is not True
        or (
            prompt_tokens is not None
            and (
                isinstance(prompt_tokens, bool)
                or not isinstance(prompt_tokens, int)
                or prompt_tokens < 0
            )
        )
        or (
            completion_tokens is not None
            and (
                isinstance(completion_tokens, bool)
                or not isinstance(completion_tokens, int)
                or completion_tokens < 0
            )
        )
        or isinstance(unresolved_cost, bool)
        or not isinstance(unresolved_cost, (int, float))
        or not math.isfinite(float(unresolved_cost))
        or float(unresolved_cost) != 0.0
        or isinstance(unknown_unmetered, bool)
        or not isinstance(unknown_unmetered, int)
        or unknown_unmetered != 0
    ):
        raise E2ERunnerError("failed", "model_usage_contract_mismatch")
    prompt_sha256 = _require_sha256(
        metadata.get("prompt_sha256"), "rendered_prompt_hash_missing"
    )
    final_answer_envelope = metadata.get("final_answer_envelope")
    digest_binding = metadata.get("final_digest_binding", "none")
    expected_envelopes = {
        "none": {"strict_json", "single_json_fence"},
        "trusted_prepare_once": {"trusted_prepare_digest_binding"},
    }
    if (
        digest_binding not in expected_envelopes
        or final_answer_envelope not in expected_envelopes[digest_binding]
    ):
        raise E2ERunnerError("failed", "final_answer_envelope_missing")
    receipt_summary = _trusted_receipts(
        trace,
        review_id=review_id,
        metadata=metadata,
        final=final,
    )
    if not TASK_ID_RE.fullmatch(result.task_id):
        raise E2ERunnerError("failed", "task_id_contract_mismatch")
    normalized = _normalise_final(final)
    raw_sanitized = {
        "task_id": result.task_id,
        "task_status": result.status.value,
        "rendered_prompt_sha256": prompt_sha256,
        "final_answer_envelope": final_answer_envelope,
        "final_digest_binding": digest_binding,
        "receipts": receipt_summary,
        "model_usage": {
            "provider": PROVIDER,
            "model": MODEL_ID,
            "call_count": call_count,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "known_cost_usd": round(float(known_cost), 8),
            "cost_complete": usage["cost_complete"],
            "unresolved_upper_bound_usd": float(unresolved_cost),
            "unknown_unmetered": unknown_unmetered,
        },
    }
    response = {
        "case_id": record["case_id"],
        "base_revision": record["base_revision"],
        "head_revision": record["head_revision"],
        "latency_ms": round(latency_ms, 3),
        "raw_sanitized": raw_sanitized,
        "normalized": normalized,
    }
    return response, {
        "final_status": final["status"],
        "verdict": final["verdict"],
        "human_review_required": final["human_review_required"],
        "auto_merge": False,
        "task_digest": final["task_digest"],
        "review_digest": final["review_digest"],
    }


def _assert_sanitized(value: Any, *, forbidden_path: Path | None = None) -> None:
    evaluator._scan_sanitized(value, "capture")

    def allowed_slash_value(item: str, field: str | None) -> bool:
        if field == "endpoint" and item == MCP_ENDPOINT:
            return True
        if (
            field not in _JSON_POINTER_FIELDS
            or JSON_POINTER_RE.fullmatch(item) is None
        ):
            return False
        parts = item[1:].split("/")
        if not parts or parts[0] not in _JSON_POINTER_ROOTS:
            return False
        return all(part and part not in {".", ".."} for part in parts)

    def contains_absolute_path(item: str) -> bool:
        return bool(
            POSIX_ABSOLUTE_PATH_RE.search(item)
            or POSIX_NETWORK_PATH_RE.search(item)
            or WINDOWS_ABSOLUTE_PATH_RE.search(item)
            or WINDOWS_NETWORK_PATH_RE.search(item)
            or WINDOWS_ROOTED_PATH_RE.search(item)
            or FILE_URI_RE.search(item)
        )

    def semantic_slash_value_contains_path(item: str, field: str | None) -> bool:
        if field == "endpoint":
            return bool(
                WINDOWS_ABSOLUTE_PATH_RE.search(item)
                or WINDOWS_NETWORK_PATH_RE.search(item)
                or WINDOWS_ROOTED_PATH_RE.search(item)
                or FILE_URI_RE.search(item)
            )
        for token in item[1:].split("/"):
            decoded = token.replace("~1", "/").replace("~0", "~")
            if contains_absolute_path(decoded):
                return True
        return False

    def allowed_source_ref(item: str, field: str | None) -> bool:
        if field != "source_ref" or SOURCE_REF_RE.fullmatch(item) is None:
            return False
        relative, pointer = item.split("#", 1)
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or path.as_posix() != relative
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            return False
        parts = pointer[1:].split("/")
        if not parts or parts[0] not in _JSON_POINTER_ROOTS:
            return False
        for token in parts:
            decoded = token.replace("~1", "/").replace("~0", "~")
            if not token or contains_absolute_path(decoded):
                return False
        return True

    def allowed_artifact_path(item: str, field: str | None) -> bool:
        if field != "artifact" or PROJECT_RELATIVE_PATH_RE.fullmatch(item) is None:
            return False
        path = PurePosixPath(item)
        return (
            not path.is_absolute()
            and path.as_posix() == item
            and all(part not in {"", ".", ".."} for part in path.parts)
        )

    def allowed_canonical_defect(item: str, field: str | None) -> bool:
        if field != "canonical_defect" or ":" not in item:
            return False
        rule_id, pointer = item.split(":", 1)
        if (
            CANONICAL_DEFECT_RULE_RE.fullmatch(rule_id) is None
            or JSON_POINTER_RE.fullmatch(pointer) is None
        ):
            return False
        parts = pointer[1:].split("/")
        if not parts or parts[0] not in _JSON_POINTER_ROOTS:
            return False
        for token in parts:
            decoded = token.replace("~1", "/").replace("~0", "~")
            if not token or decoded in {".", ".."} or contains_absolute_path(decoded):
                return False
        return True

    trusted_pointers: set[str] = set()

    def collect_trusted_pointers(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if (
                    isinstance(key, str)
                    and isinstance(child, str)
                    and allowed_slash_value(child, key)
                ):
                    trusted_pointers.add(child)
                collect_trusted_pointers(child)
        elif isinstance(item, list):
            for child in item:
                collect_trusted_pointers(child)

    collect_trusted_pointers(value)

    def visit(item: Any, *, field: str | None = None) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise TypeError("capture mapping keys must be strings")
                visit(key)
                visit(child, field=key)
        elif isinstance(item, list):
            for child in item:
                visit(child, field=field)
        elif isinstance(item, str):
            if (
                allowed_source_ref(item, field)
                or allowed_artifact_path(item, field)
                or allowed_canonical_defect(item, field)
            ):
                return
            allowed_slash = allowed_slash_value(item, field)
            scanned_item = item
            if field in {"evidence", "suggested_fix"}:
                # Semantic evidence may quote the exact canonical JSON Pointer
                # already present in the structured location field.  Mask only
                # those pre-validated sibling pointers before looking for real
                # machine paths; arbitrary /tmp, /Users, file://, UNC, or
                # traversal strings remain forbidden.
                for pointer in sorted(trusted_pointers, key=len, reverse=True):
                    scanned_item = scanned_item.replace(pointer, "[json-pointer]")
            if (
                semantic_slash_value_contains_path(scanned_item, field)
                if allowed_slash
                else contains_absolute_path(scanned_item)
            ):
                raise ValueError("capture contains an absolute local path")
            if forbidden_path is not None and str(forbidden_path) in item:
                raise ValueError("capture contains the materialized repository path")

    visit(value)
    payload = _canonical_bytes(value)
    if len(payload) > MAX_CAPTURE_BYTES:
        raise ValueError("capture exceeds its byte bound")


def _atomic_write_json(path: Path, value: Mapping[str, Any], *, root: Path) -> None:
    root_resolved = root.resolve(strict=True)
    target = path if path.is_absolute() else root_resolved / path
    target = target.resolve(strict=False)
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise E2ERunnerError("failed", "evidence_path_outside_repository") from exc
    current = target.parent
    while current != root_resolved and not current.exists():
        current = current.parent
    if current.is_symlink():
        raise E2ERunnerError("failed", "unsafe_evidence_path")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise E2ERunnerError("failed", "unsafe_evidence_path")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(
                value,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def run_trusted_case(
    case_id: str = DEFAULT_CASE_ID,
    *,
    timeout_seconds: float = 600.0,
    evidence_out: Path | None = None,
    require_acceptance: bool = True,
    _dependencies: _Dependencies | None = None,
) -> TrustedCaseRun:
    """Execute one trusted frozen case; no model call occurs before preflight."""

    dependencies = _dependencies or _Dependencies()
    if (
        not isinstance(case_id, str)
        or not case_id
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= MAX_TASK_TIMEOUT_SECONDS
    ):
        raise E2ERunnerError("failed", "invalid_runner_arguments")
    record, workspace, corpus_hash = _case_metadata(
        case_id, dependencies=dependencies
    )
    before = _workspace_state(workspace, str(record["head_revision"]))
    prompt_template_hash = _prompt_template_sha256()
    review_id = dependencies.review_id_factory()
    if not isinstance(review_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", review_id
    ):
        raise E2ERunnerError("failed", "review_id_contract_mismatch")

    try:
        server = dependencies.server_factory(case_id, workspace)
    except OSError as exc:
        raise E2ERunnerError("not_configured", "mcp_port_unavailable") from exc
    except (TypeError, ValueError) as exc:
        raise E2ERunnerError("failed", "mcp_configuration_failed") from exc

    try:
        with server:
            ready = dependencies.preflight_check()
            if not isinstance(ready, PreflightReady):
                raise E2ERunnerError("failed", "preflight_contract_mismatch")
            if ready.payload.get("status") != "ready":
                raise E2ERunnerError("failed", "preflight_contract_mismatch")
            all_model_routes_pinned = ready.payload.get("all_model_routes_pinned")
            if all_model_routes_pinned is not True:
                raise E2ERunnerError("failed", "preflight_contract_mismatch")
            try:
                backend = dependencies.backend_factory(
                    workspace,
                    server,
                    ready.executable,
                    float(timeout_seconds),
                    all_model_routes_pinned,
                )
            except OuroborosNotConfiguredError as exc:
                raise E2ERunnerError("not_configured", "backend_not_configured") from exc
            except (OuroborosBackendError, OSError, TypeError, ValueError) as exc:
                raise E2ERunnerError("failed", "backend_configuration_failed") from exc
            payload = {
                "repository_id": case_id,
                "base": record["base_revision"],
                "head": record["head_revision"],
                "review_id": review_id,
                "data_classification": "synthetic-public",
                "idempotency_key": review_id,
            }
            started = dependencies.monotonic()
            try:
                task_id = backend.schedule_task("aga:review", payload)
            except OuroborosNotConfiguredError as exc:
                raise E2ERunnerError(
                    "not_configured", "runtime_schedule_not_configured"
                ) from exc
            except OuroborosIdempotencyConflict as exc:
                raise E2ERunnerError(
                    "failed", "runtime_schedule_idempotency_conflict"
                ) from exc
            except CommandTimeoutError as exc:
                raise E2ERunnerError("failed", "runtime_schedule_timeout") from exc
            except CommandOutputTooLargeError as exc:
                raise E2ERunnerError(
                    "failed", "runtime_schedule_output_too_large"
                ) from exc
            except OuroborosContractError as exc:
                raise E2ERunnerError(
                    "failed", "runtime_schedule_contract_mismatch"
                ) from exc
            except (OuroborosBackendError, OSError, TypeError, ValueError) as exc:
                raise E2ERunnerError("failed", "runtime_schedule_failed") from exc
            try:
                result = backend.wait_for_task(task_id)
            except OuroborosNotConfiguredError as exc:
                raise E2ERunnerError(
                    "not_configured", "runtime_wait_not_configured"
                ) from exc
            except CommandTimeoutError as exc:
                raise E2ERunnerError("failed", "runtime_wait_timeout") from exc
            except CommandOutputTooLargeError as exc:
                raise E2ERunnerError(
                    "failed", "runtime_wait_output_too_large"
                ) from exc
            except OuroborosContractError as exc:
                raise E2ERunnerError(
                    "failed", "runtime_wait_contract_mismatch"
                ) from exc
            except (OuroborosBackendError, OSError, TypeError, ValueError) as exc:
                raise E2ERunnerError("failed", "runtime_wait_failed") from exc
            latency_ms = max(0.0, (dependencies.monotonic() - started) * 1000.0)
            if latency_ms > 3_600_000:
                raise E2ERunnerError("failed", "task_latency_out_of_bounds")
            after = _workspace_state(workspace, str(record["head_revision"]))
            if after != before:
                raise E2ERunnerError("failed", "workspace_mutated")
            response, final_summary = _task_response(
                result,
                record=record,
                review_id=review_id,
                trace=tuple(server.trace),
                latency_ms=latency_ms,
            )
    except E2ERunnerError:
        raise
    except OSError as exc:
        raise E2ERunnerError("not_configured", "mcp_lifecycle_failed") from exc
    except Exception as exc:
        raise E2ERunnerError("failed", "internal_runner_error") from exc

    captured_at = _timestamp(dependencies.now())
    preflight_sha256 = _sha256_json(ready.payload)
    config_hash = _sha256_json(
        {
            "runtime_version": PINNED_VERSION,
            "provider": PROVIDER,
            "model": MODEL_ID,
            "review_mode": preflight.EXPECTED_REVIEW_MODE,
            "mcp_server_id": preflight.MCP_SERVER_ID,
            "mcp_tools": list(preflight.MCP_TOOL_NAMES),
            "gateway_url": GATEWAY_URL,
            "project_registration": "loopback_idempotent",
            "task_disabled_tools": [
                f"mcp_{preflight.MCP_SERVER_ID}__aga_parse_diagram"
            ],
            "memory_mode": "empty",
            "task_timeout_seconds": float(timeout_seconds),
            "data_classification": "synthetic-public",
            "inference_control": INFERENCE_CONTROL,
            "preflight_sha256": preflight_sha256,
        }
    )
    try:
        score = evaluator.score_trusted_ouroboros_responses(
            [response],
            captured_at=captured_at,
            runtime_version=PINNED_VERSION,
            provider=PROVIDER,
            model_name=MODEL_ID,
            prompt_hash=prompt_template_hash,
            config_hash=config_hash,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise E2ERunnerError("failed", "trusted_scoring_failed") from exc
    runs = score.get("runs")
    if not isinstance(runs, list) or len(runs) != 1:
        raise E2ERunnerError("failed", "trusted_scoring_contract_mismatch")
    accepted = runs[0].get("assessment") == "PASS"
    if require_acceptance and not accepted:
        raise E2ERunnerError("failed", "case_acceptance_failed")
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "status": "passed" if accepted else "failed_acceptance",
        "captured_at": captured_at,
        "runtime": {"name": "ouroboros", "version": PINNED_VERSION},
        "provider": PROVIDER,
        "model": {"name": MODEL_ID},
        "data_classification": "synthetic-public",
        "redaction": {
            "credentials_retained": False,
            "absolute_paths_retained": False,
            "raw_prompts_retained": False,
            "raw_provider_payloads_retained": False,
        },
        "corpus_hash": corpus_hash,
        "prompt_template_sha256": prompt_template_hash,
        "config_sha256": config_hash,
        "preflight": {
            "status": "ready",
            "attestation_sha256": preflight_sha256,
            "tool_count": len(preflight.MCP_TOOL_NAMES),
            "tools": list(preflight.MCP_TOOL_NAMES),
        },
        "run": {
            **dict(response),
            "review_id_sha256": response["raw_sanitized"]["receipts"][
                "review_id_sha256"
            ],
            "final": final_summary,
            "acceptance": {
                "assessment": runs[0]["assessment"],
                "schema_valid": runs[0]["schema_valid"],
                "unsafe_approve": runs[0]["unsafe_approve"],
            },
        },
    }
    try:
        _assert_sanitized(evidence, forbidden_path=workspace)
    except (TypeError, ValueError) as exc:
        raise E2ERunnerError("failed", "capture_sanitization_failed") from exc
    if evidence_out is not None:
        _atomic_write_json(
            Path(evidence_out), evidence, root=dependencies.evidence_root
        )
    return TrustedCaseRun(
        case_id=case_id,
        response=response,
        evidence=evidence,
        score=score,
    )


def _positive_timeout(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(result) or not 0 < result <= MAX_TASK_TIMEOUT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"must be in (0, {MAX_TASK_TIMEOUT_SECONDS:g}]"
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one trusted synthetic-public AGA review through Ouroboros"
    )
    parser.add_argument("--case", default=DEFAULT_CASE_ID, dest="case_id")
    parser.add_argument("--timeout", type=_positive_timeout, default=600.0)
    parser.add_argument(
        "--evidence-out",
        type=Path,
        default=DEFAULT_EVIDENCE_OUT,
        help="project-relative sanitized evidence destination",
    )
    return parser


def _emit(value: Mapping[str, Any]) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    # The public one-case command is the explicitly approved checkpoint smoke.
    # Other frozen cases are reachable only through the separately confirmed
    # complete-selection runner, which prevents an accidental holdout call or
    # an unapproved series of cherry-picked paid calls.
    if arguments.case_id != DEFAULT_CASE_ID:
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "status": "not_authorized",
                "code": "smoke_case_not_authorized",
                "case_id": arguments.case_id,
            }
        )
        return 2
    try:
        run = run_trusted_case(
            arguments.case_id,
            timeout_seconds=arguments.timeout,
            evidence_out=arguments.evidence_out,
        )
        evidence_path = Path(arguments.evidence_out).resolve(strict=False)
        try:
            evidence_label = evidence_path.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
        except ValueError:
            evidence_label = "sanitized-evidence.json"
        task_id = run.response["raw_sanitized"]["task_id"]
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "status": "passed",
                "code": "ok",
                "case_id": run.case_id,
                "task_id": task_id,
                "evidence": evidence_label,
            }
        )
        return 0
    except E2ERunnerError as exc:
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "status": exc.status,
                "code": exc.code,
                "case_id": arguments.case_id,
            }
        )
        return 2 if exc.status == "not_configured" else 3
    except Exception:
        _emit(
            {
                "schema": CLI_RESULT_SCHEMA,
                "status": "failed",
                "code": "internal_runner_error",
                "case_id": arguments.case_id,
            }
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
