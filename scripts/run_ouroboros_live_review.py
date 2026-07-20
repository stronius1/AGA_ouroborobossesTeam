#!/usr/bin/env python3
"""Run one production-like AGA review for immutable local Git revisions.

The command accepts a real local repository and two full commit IDs.  It never
passes a caller-controlled path to the model or MCP tools: the path is bound to
the non-path ``repository_id`` inside the loopback ReviewService registry.
Output and optional evidence are bounded, sanitized, and contain only hashes,
relative artifact labels, immutable revisions, trusted receipts, and cost.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGA_SKILL_ROOT = REPOSITORY_ROOT / "aga-skill"
for _root in (REPOSITORY_ROOT, AGA_SKILL_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from scripts import ouroboros_preflight as preflight  # noqa: E402
from scripts import run_ouroboros_e2e as e2e  # noqa: E402
from scripts.openrouter_budget import BudgetError, read_budget  # noqa: E402
from scripts.private_receipt_journal import (  # noqa: E402
    PrivateReceiptJournal,
    ReceiptJournalError,
)
from tools.mcp_server import (  # noqa: E402
    MCPServer,
    MCPServerConfig,
    SchemaViolation,
    validate_json_schema,
)
from tools.ouroboros_backend import (  # noqa: E402
    BoundedCommandRunner,
    OuroborosBackendConfig,
    OuroborosBackendError,
    OuroborosIdempotencyConflict,
    OuroborosTaskBackend,
)
from tools.review_service import ReviewService, ReviewServiceError  # noqa: E402
from tools.repository_snapshot import (  # noqa: E402
    DEFAULT_ARCHTOOL_COMMIT,
    DEFAULT_ARCHTOOL_PATH,
    DEFAULT_SEAF_CORE_COMMIT,
    DEFAULT_SEAF_CORE_PATH,
)
from tools.validation import strict_load_yaml_text  # noqa: E402


SCHEMA = "aga.ouroboros-live-review/v1"
CLI_SCHEMA = "aga.ouroboros-live-review-cli/v1"
STATE_SCHEMA = "aga.ouroboros-live-review-state/v1"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MAX_GIT_OUTPUT = 2 * 1024 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
DEFAULT_STATE_ROOT = REPOSITORY_ROOT / ".aga-runs" / "live-review"


class LiveReviewError(RuntimeError):
    """Typed, path-free error for the public command boundary."""

    def __init__(self, code: str, *, status: str = "failed") -> None:
        if status not in {"failed", "not_configured", "incomplete"}:
            raise ValueError("invalid live-review status")
        self.code = code
        self.status = status
        self.failure_budget: Mapping[str, Any] | None = None
        super().__init__(code)


@dataclass(frozen=True)
class RepositoryBinding:
    repository: Path
    repository_id: str
    base: str
    head: str
    data_classification: str


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _git(repository: Path, *arguments: str, limit: int = MAX_GIT_OUTPUT) -> bytes:
    runner = BoundedCommandRunner(
        max_stdout_bytes=limit,
        max_stderr_bytes=64 * 1024,
    )
    try:
        completed = runner.run(
            ("git", "-C", str(repository), *arguments), timeout=20.0
        )
    except Exception as exc:
        raise LiveReviewError("git_command_failed") from exc
    if completed.returncode != 0:
        raise LiveReviewError("git_command_failed")
    return completed.stdout.encode("utf-8")


def _git_text(repository: Path, *arguments: str, limit: int = MAX_GIT_OUTPUT) -> str:
    try:
        return _git(repository, *arguments, limit=limit).decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise LiveReviewError("git_output_invalid") from exc


def _exact_commit(repository: Path, revision: str, field: str) -> str:
    if not isinstance(revision, str) or REVISION_RE.fullmatch(revision) is None:
        raise LiveReviewError(f"{field}_not_full_sha")
    resolved = _git_text(
        repository,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{revision}^{{commit}}",
        limit=128,
    ).lower()
    if resolved != revision.lower():
        raise LiveReviewError(f"{field}_not_immutable_commit")
    return resolved


def _classification_at(repository: Path, head: str) -> str:
    if _git_text(repository, "cat-file", "-t", f"{head}:dochub.yaml", limit=64) != "blob":
        raise LiveReviewError("architecture_manifest_missing")
    manifest_payload = _git(repository, "show", f"{head}:dochub.yaml", limit=1024 * 1024)
    try:
        manifest = strict_load_yaml_text(
            manifest_payload,
            source="dochub.yaml",
            expected_type=dict,
        )
    except Exception as exc:
        raise LiveReviewError("architecture_manifest_invalid") from exc
    aga = manifest.get("aga")
    classification = aga.get("data_classification") if isinstance(aga, Mapping) else None
    if classification != "synthetic-public":
        raise LiveReviewError("data_classification_not_permitted")
    return "synthetic-public"


def bind_repository(
    repository: Path | str,
    repository_id: str,
    base: str,
    head: str,
) -> RepositoryBinding:
    if not isinstance(repository_id, str) or ID_RE.fullmatch(repository_id) is None:
        raise LiveReviewError("repository_id_invalid")
    try:
        raw = Path(repository)
        if raw.is_symlink():
            raise LiveReviewError("repository_symlink_forbidden")
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise LiveReviewError("repository_unavailable") from exc
    if not resolved.is_dir():
        raise LiveReviewError("repository_unavailable")
    root_text = _git_text(resolved, "rev-parse", "--show-toplevel")
    try:
        git_root = Path(root_text).resolve(strict=True)
    except OSError as exc:
        raise LiveReviewError("repository_root_invalid") from exc
    if git_root != resolved:
        raise LiveReviewError("repository_must_be_git_root")
    status = _git_text(
        resolved,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status:
        raise LiveReviewError("repository_not_clean")
    exact_base = _exact_commit(resolved, base, "base")
    exact_head = _exact_commit(resolved, head, "head")
    ancestor = subprocess.run(
        (
            "git",
            "-C",
            str(resolved),
            "merge-base",
            "--is-ancestor",
            exact_base,
            exact_head,
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20.0,
        check=False,
        env={"PATH": os.environ.get("PATH", os.defpath)},
    )
    if ancestor.returncode != 0:
        raise LiveReviewError("base_not_ancestor_of_head")
    return RepositoryBinding(
        repository=resolved,
        repository_id=repository_id,
        base=exact_base,
        head=exact_head,
        data_classification=_classification_at(resolved, exact_head),
    )


def _correlation(binding: RepositoryBinding, idempotency_key: str) -> tuple[str, str]:
    if not isinstance(idempotency_key, str) or ID_RE.fullmatch(idempotency_key) is None:
        raise LiveReviewError("idempotency_key_invalid")
    material = {
        "repository_id": binding.repository_id,
        "base": binding.base,
        "head": binding.head,
        "idempotency_key": idempotency_key,
        "model": e2e.MODEL_ID,
    }
    digest = hashlib.sha256(_canonical_bytes(material)).hexdigest()
    return f"aga-review-{digest[:32]}", digest


def _state_path(state_root: Path, binding_digest: str) -> Path:
    return state_root / binding_digest[:2] / f"{binding_digest}.json"


def _read_cached_state(path: Path, expected_binding: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_RESULT_BYTES:
        raise LiveReviewError("state_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LiveReviewError("state_invalid") from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != STATE_SCHEMA
        or payload.get("binding") != dict(expected_binding)
        or not isinstance(payload.get("result"), Mapping)
    ):
        raise LiveReviewError("state_conflict")
    result = dict(payload["result"])
    if result.get("schema") != SCHEMA or result.get("status") not in {"completed", "incomplete"}:
        raise LiveReviewError("state_invalid")
    return result


def _atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise LiveReviewError("state_path_unsafe")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary: Path | None = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        path.chmod(0o600)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


def _review_service(binding: RepositoryBinding) -> ReviewService:
    trusted_dependencies = {
        DEFAULT_ARCHTOOL_PATH: {
            "checkout": REPOSITORY_ROOT / DEFAULT_ARCHTOOL_PATH,
            "commit": DEFAULT_ARCHTOOL_COMMIT,
        },
        DEFAULT_SEAF_CORE_PATH: {
            "checkout": REPOSITORY_ROOT / DEFAULT_SEAF_CORE_PATH,
            "commit": DEFAULT_SEAF_CORE_COMMIT,
        },
    }
    return ReviewService(
        repositories={
            binding.repository_id: {
                "repository": binding.repository,
                "manifest_path": "dochub.yaml",
                "dependency_mode": "verified",
                "trusted_dependencies": trusted_dependencies,
            }
        },
        ttl_seconds=1200.0,
        prepare_timeout_seconds=30.0,
        max_prepare_workers=2,
    )


def _server(
    binding: RepositoryBinding,
    *,
    trace_sink: Any = None,
    service: ReviewService | None = None,
) -> MCPServer:
    return MCPServer(
        service or _review_service(binding),
        config=MCPServerConfig(
            host=e2e.MCP_HOST,
            port=e2e.MCP_PORT,
            endpoint=e2e.MCP_ENDPOINT,
            mode="none",
            request_timeout_seconds=30.0,
            max_concurrency=4,
        ),
        trace_sink=trace_sink,
    )


def _failure_budget(before: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(before, Mapping):
        return None
    usage = before.get("usage_usd")
    if isinstance(usage, bool) or not isinstance(usage, (int, float)):
        return None
    try:
        after = read_budget(minimum_remaining_usd=0.0)
    except BudgetError:
        return {
            "schema": "aga.openrouter-failed-batch-budget/v1",
            "status": "after_checkpoint_unavailable",
            "before_usage_usd": float(usage),
            "aggregate_usage_delta_usd": None,
        }
    return {
        "schema": "aga.openrouter-failed-batch-budget/v1",
        "status": "recorded",
        "before_usage_usd": float(usage),
        "after_usage_usd": float(after["usage_usd"]),
        "aggregate_usage_delta_usd": round(
            max(0.0, float(after["usage_usd"]) - float(usage)), 8
        ),
        "credentials_retained": False,
        "raw_provider_payloads_retained": False,
    }


def _host_prepare_incomplete_result(
    *, binding: RepositoryBinding, binding_digest: str, review_id: str,
    prepared: Mapping[str, Any], final: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        prepared.get("schema") != "aga.prepare-review/v1"
        or prepared.get("status") != "incomplete"
        or prepared.get("incomplete") is not True
        or prepared.get("review_id") != review_id
        or prepared.get("repository_id") != binding.repository_id
        or prepared.get("base") != binding.base
        or prepared.get("head") != binding.head
        or not isinstance(prepared.get("review_digest"), str)
        or not isinstance(prepared.get("task_digest"), str)
        or not isinstance(prepared.get("semantic_tasks"), list)
        or not isinstance(prepared.get("analysis_errors"), list)
        or not isinstance(prepared.get("referenced_entity_ids"), list)
        or not isinstance(prepared.get("unresolved_reference_ids"), list)
    ):
        raise LiveReviewError("trusted_prepare_contract_mismatch")
    try:
        validate_json_schema(final, e2e._final_output_schema(), "$host_final")
    except SchemaViolation as exc:
        raise LiveReviewError("trusted_host_final_contract_mismatch") from exc
    if (
        final.get("status") != "incomplete"
        or final.get("verdict") != "incomplete"
        or final.get("incomplete") is not True
        or final.get("human_review_required") is not True
        or final.get("auto_merge") is not False
        or final.get("review_id") != review_id
        or final.get("review_digest") != prepared["review_digest"]
        or final.get("task_digest") != prepared["task_digest"]
        or not isinstance(final.get("findings"), list)
    ):
        raise LiveReviewError("trusted_host_final_contract_mismatch")
    prepare_analysis_error_codes = []
    for error in prepared["analysis_errors"]:
        code = error.get("code") if isinstance(error, Mapping) else None
        if not isinstance(code, str) or not code:
            raise LiveReviewError("trusted_prepare_contract_mismatch")
        prepare_analysis_error_codes.append(code)
    referenced_entity_ids = prepared["referenced_entity_ids"]
    unresolved_reference_ids = prepared["unresolved_reference_ids"]
    if any(not isinstance(value, str) for value in referenced_entity_ids) or any(
        not isinstance(value, str) for value in unresolved_reference_ids
    ):
        raise LiveReviewError("trusted_prepare_contract_mismatch")
    analysis_error_codes = []
    for error in final["analysis_errors"]:
        code = error.get("code") if isinstance(error, Mapping) else None
        if not isinstance(code, str) or not code:
            raise LiveReviewError("trusted_host_final_contract_mismatch")
        analysis_error_codes.append(code)
    deterministic_finding_rule_ids = []
    for finding in final["findings"]:
        rule_id = finding.get("rule_id") if isinstance(finding, Mapping) else None
        if not isinstance(rule_id, str) or not rule_id:
            raise LiveReviewError("trusted_host_final_contract_mismatch")
        deterministic_finding_rule_ids.append(rule_id)
    service_final_output_sha256 = hashlib.sha256(_canonical_bytes(final)).hexdigest()
    projected_final = {**dict(final), "findings": []}
    try:
        validate_json_schema(projected_final, e2e._final_output_schema(), "$host_projection")
    except SchemaViolation as exc:
        raise LiveReviewError("trusted_host_final_contract_mismatch") from exc
    prepare_arguments = {
        "repository_id": binding.repository_id,
        "base": binding.base,
        "head": binding.head,
        "review_id": review_id,
        "entity_ids": [],
    }
    prepare_output_sha256 = hashlib.sha256(_canonical_bytes(prepared)).hexdigest()
    projection_output_sha256 = hashlib.sha256(
        _canonical_bytes(projected_final)
    ).hexdigest()
    review_id_sha256 = hashlib.sha256(review_id.encode("utf-8")).hexdigest()
    return {
        "schema": SCHEMA,
        "status": "incomplete",
        "reused": False,
        "repository_id": binding.repository_id,
        "data_classification": binding.data_classification,
        "base": binding.base,
        "head": binding.head,
        "runtime": {
            "name": "ouroboros",
            "version": e2e.PINNED_VERSION,
            "source_commit": preflight.PINNED_SOURCE_COMMIT,
        },
        "provider": e2e.PROVIDER,
        "model": e2e.MODEL_ID,
        "task_id": f"aga-host-prepare-{binding_digest[:32]}",
        "review_id_sha256": review_id_sha256,
        "review_digest": prepared["review_digest"],
        "task_digest": prepared["task_digest"],
        "receipts": None,
        "host_attestation": {
            "kind": "trusted_host_prepare_attestation",
            "mcp_tool_invoked": False,
            "review_id_sha256": review_id_sha256,
            "prepare_args_sha256": hashlib.sha256(
                _canonical_bytes(prepare_arguments)
            ).hexdigest(),
            "prepare_output_sha256": prepare_output_sha256,
            "service_final_output_sha256": service_final_output_sha256,
            "projection_output_sha256": projection_output_sha256,
            "prepare_analysis_error_codes": prepare_analysis_error_codes,
            "analysis_error_codes": analysis_error_codes,
            "deterministic_finding_rule_ids": deterministic_finding_rule_ids,
            "auxiliary_deterministic_findings": [dict(item) for item in final["findings"]],
            "referenced_entity_ids": list(referenced_entity_ids),
            "unresolved_reference_ids": list(unresolved_reference_ids),
        },
        "model_usage": {
            "provider": e2e.PROVIDER,
            "model": e2e.MODEL_ID,
            "call_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "known_cost_usd": 0.0,
            "cost_complete": True,
            "unresolved_upper_bound_usd": 0.0,
            "unknown_unmetered": 0,
        },
        "execution": {
            "kind": "trusted_host_prepare_incomplete",
            "model_task_scheduled": False,
        },
        "budget_before_task": None,
        "final": dict(final),
        "redaction": {
            "credentials_retained": False,
            "absolute_paths_retained": False,
            "raw_prompts_retained": False,
            "raw_provider_payloads_retained": False,
        },
    }


def _persist_result(
    result: Mapping[str, Any], *, state_path: Path,
    binding_public: Mapping[str, Any], repository: Path,
) -> Mapping[str, Any]:
    try:
        e2e._assert_sanitized(result, forbidden_path=repository)
    except (TypeError, ValueError) as exc:
        raise LiveReviewError("result_sanitization_failed") from exc
    if len(_canonical_bytes(result)) > MAX_RESULT_BYTES:
        raise LiveReviewError("result_too_large")
    _atomic_private_json(
        state_path,
        {"schema": STATE_SCHEMA, "binding": dict(binding_public), "result": dict(result)},
    )
    return result


def run_live_review(
    *,
    repository: Path | str,
    repository_id: str,
    base: str,
    head: str,
    idempotency_key: str,
    timeout_seconds: float = 900.0,
    state_root: Path = DEFAULT_STATE_ROOT,
) -> Mapping[str, Any]:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= e2e.MAX_TASK_TIMEOUT_SECONDS
    ):
        raise LiveReviewError("timeout_invalid")
    binding = bind_repository(repository, repository_id, base, head)
    review_id, binding_digest = _correlation(binding, idempotency_key)
    binding_public = {
        "repository_id": binding.repository_id,
        "base": binding.base,
        "head": binding.head,
        "idempotency_sha256": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
        "model": e2e.MODEL_ID,
    }
    state_path = _state_path(Path(state_root), binding_digest)
    cached = _read_cached_state(state_path, binding_public)
    if cached is not None:
        try:
            e2e._assert_sanitized(cached, forbidden_path=binding.repository)
        except (TypeError, ValueError) as exc:
            raise LiveReviewError("state_sanitization_failed") from exc
        if (
            len(_canonical_bytes(cached)) > MAX_RESULT_BYTES
            or cached.get("repository_id") != binding.repository_id
            or cached.get("base") != binding.base
            or cached.get("head") != binding.head
            or cached.get("runtime")
            != {
                "name": "ouroboros",
                "version": e2e.PINNED_VERSION,
                "source_commit": preflight.PINNED_SOURCE_COMMIT,
            }
            or cached.get("provider") != e2e.PROVIDER
            or cached.get("model") != e2e.MODEL_ID
        ):
            raise LiveReviewError("state_invalid")
        return {**dict(cached), "reused": True}

    try:
        service = _review_service(binding)
        prepared = service.prepare_review(
            repository_id=binding.repository_id,
            base=binding.base,
            head=binding.head,
            review_id=review_id,
            entity_ids=[],
        )
    except (OSError, TypeError, ValueError, ReviewServiceError) as exc:
        if "service" in locals():
            service.close()
        raise LiveReviewError("trusted_prepare_failed") from exc
    if prepared.get("status") == "incomplete":
        try:
            host_final = service.finalize_review(
                review_id=review_id,
                review_digest=prepared["review_digest"],
                task_digest=prepared["task_digest"],
                semantic_result={
                    "status": "unavailable",
                    "error": "Trusted preparation was incomplete; model task was not scheduled.",
                },
            )
            projected = _host_prepare_incomplete_result(
                binding=binding,
                binding_digest=binding_digest,
                review_id=review_id,
                prepared=prepared,
                final=host_final,
            )
            return _persist_result(
                projected,
                state_path=state_path,
                binding_public=binding_public,
                repository=binding.repository,
            )
        except (OSError, TypeError, ValueError, ReviewServiceError) as exc:
            raise LiveReviewError("trusted_host_finalize_failed") from exc
        finally:
            service.close()
    if prepared.get("status") != "ready" or prepared.get("incomplete") is not False:
        service.close()
        raise LiveReviewError("trusted_prepare_contract_mismatch")
    try:
        receipt_journal = PrivateReceiptJournal(
            state_path.with_suffix(".receipts.jsonl")
        )
    except ReceiptJournalError as exc:
        service.close()
        raise LiveReviewError("receipt_journal_invalid") from exc
    try:
        server = _server(
            binding, trace_sink=receipt_journal.append, service=service
        )
    except (OSError, TypeError, ValueError) as exc:
        service.close()
        raise LiveReviewError("mcp_server_unavailable", status="not_configured") from exc
    try:
        with server:
            ready = e2e._default_preflight()
            mcp_attestation = ready.payload.get("mcp")
            worker_attestation = (
                mcp_attestation.get("worker_ready_discovery")
                if isinstance(mcp_attestation, Mapping)
                else None
            )
            stages = (
                worker_attestation.get("stages")
                if isinstance(worker_attestation, Mapping)
                else None
            )
            if (
                ready.payload.get("status") != "ready"
                or ready.payload.get("all_model_routes_pinned") is not True
                or not isinstance(stages, Mapping)
                or stages.get("review", {}).get("active_tools")
                != list(preflight.REVIEW_MCP_TOOL_NAMES)
            ):
                raise LiveReviewError("preflight_not_ready", status="not_configured")
            try:
                budget_before_task = read_budget(minimum_remaining_usd=0.50)
            except BudgetError as exc:
                status = (
                    "not_configured"
                    if exc.status == "not_configured"
                    else "incomplete"
                )
                raise LiveReviewError(exc.code, status=status) from exc
            backend = OuroborosTaskBackend(
                OuroborosBackendConfig(
                    command_prefix=(ready.executable,),
                    gateway_url=e2e.GATEWAY_URL,
                    runtime_version=e2e.PINNED_VERSION,
                    model_id=e2e.MODEL_ID,
                    workspaces={binding.repository_id: binding.repository},
                    prompt_path=e2e.PROMPT_PATH,
                    task_timeout_seconds=float(timeout_seconds),
                    finalization_grace_seconds=180.0,
                    server_id=preflight.MCP_SERVER_ID,
                    receipt_source=receipt_journal.read,
                    finalize_digest_repair=server.repair_finalize_digest_mismatch,
                    finalize_transport_repair=server.repair_finalize_transport_error,
                    project_registrar=e2e._register_local_project,
                    all_model_routes_pinned=True,
                    disable_diagram_tool=False,
                    disable_lookup_tool=True,
                )
            )
            payload = {
                "repository_id": binding.repository_id,
                "base": binding.base,
                "head": binding.head,
                "review_id": review_id,
                "data_classification": binding.data_classification,
                "idempotency_key": review_id,
            }
            started = time.monotonic()
            try:
                task_id = backend.schedule_task("aga:review", payload)
                task_result = backend.wait_for_task(task_id)
            except OuroborosIdempotencyConflict as exc:
                raise LiveReviewError("idempotency_conflict") from exc
            except OuroborosBackendError as exc:
                raise LiveReviewError("ouroboros_transport_failed") from exc
            response, final_summary = e2e._task_response(
                task_result,
                record={
                    "case_id": binding.repository_id,
                    "base_revision": binding.base,
                    "head_revision": binding.head,
                },
                review_id=review_id,
                trace=receipt_journal.read(),
                latency_ms=max(0.0, (time.monotonic() - started) * 1000.0),
            )
            trusted_final = task_result.metadata.get("aga_final")
            if not isinstance(trusted_final, Mapping):
                raise LiveReviewError("trusted_final_missing")
            trusted_findings = trusted_final.get("findings")
            if not isinstance(trusted_findings, list):
                raise LiveReviewError("trusted_final_missing")
    except LiveReviewError as exc:
        exc.failure_budget = _failure_budget(locals().get("budget_before_task"))
        raise
    except e2e.E2ERunnerError as exc:
        status = "incomplete" if exc.code == "aga_incomplete" else exc.status
        converted = LiveReviewError(exc.code, status=status)
        converted.failure_budget = _failure_budget(locals().get("budget_before_task"))
        raise converted from exc
    except Exception as exc:
        converted = LiveReviewError("live_review_failed")
        converted.failure_budget = _failure_budget(locals().get("budget_before_task"))
        raise converted from exc

    final_status = str(final_summary["final_status"])
    result = {
        "schema": SCHEMA,
        "status": "completed" if final_status == "completed" else "incomplete",
        "reused": False,
        "repository_id": binding.repository_id,
        "data_classification": binding.data_classification,
        "base": binding.base,
        "head": binding.head,
        "runtime": {
            "name": "ouroboros",
            "version": e2e.PINNED_VERSION,
            "source_commit": preflight.PINNED_SOURCE_COMMIT,
        },
        "provider": e2e.PROVIDER,
        "model": e2e.MODEL_ID,
        "task_id": response["raw_sanitized"]["task_id"],
        "review_id_sha256": response["raw_sanitized"]["receipts"]["review_id_sha256"],
        "review_digest": final_summary["review_digest"],
        "task_digest": final_summary["task_digest"],
        "receipts": response["raw_sanitized"]["receipts"],
        "host_attestation": None,
        "model_usage": response["raw_sanitized"]["model_usage"],
        "execution": {
            "kind": "ouroboros_model_review",
            "model_task_scheduled": True,
        },
        "budget_before_task": dict(budget_before_task),
        # Preserve the complete schema-validated finalize object.  Its exact
        # canonical hash is already bound to the trusted in-process MCP
        # receipt; the remediation host must register that exact object rather
        # than a lossy display projection.
        "final": dict(trusted_final),
        "redaction": {
            "credentials_retained": False,
            "absolute_paths_retained": False,
            "raw_prompts_retained": False,
            "raw_provider_payloads_retained": False,
        },
    }
    return _persist_result(
        result,
        state_path=state_path,
        binding_public=binding_public,
        repository=binding.repository,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    return parser


def _emit(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = run_live_review(
            repository=arguments.repository,
            repository_id=arguments.repository_id,
            base=arguments.base,
            head=arguments.head,
            idempotency_key=arguments.idempotency_key,
            timeout_seconds=arguments.timeout,
            state_root=arguments.state_root,
        )
        _emit(result)
        return 0 if result["status"] == "completed" else 4
    except LiveReviewError as exc:
        failure = {"schema": CLI_SCHEMA, "status": exc.status, "code": exc.code}
        if exc.failure_budget is not None:
            failure["failed_batch_budget"] = dict(exc.failure_budget)
        _emit(failure)
        return 2 if exc.status == "not_configured" else 4 if exc.status == "incomplete" else 3
    except Exception:
        _emit({"schema": CLI_SCHEMA, "status": "failed", "code": "internal_live_review_error"})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
