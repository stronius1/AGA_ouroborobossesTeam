"""Install deferred runtime hooks in every managed Ouroboros Python child.

Python imports ``sitecustomize`` before ``multiprocessing.spawn`` restores the
parent interpreter's venv ``sys.path``.  Importing Ouroboros here would therefore
let optional dependencies appear permanently unavailable in a spawned worker.
This module uses the standard library only and merely registers an import hook.
The hook verifies and patches the known ``ouroboros.consolidator`` model
constant and the narrow AGA-finalize transport retry when those exact modules
are naturally imported later, after spawn preparation has completed.
"""

from __future__ import annotations

import copy
import importlib.abc
import importlib.machinery
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any, Sequence


_SCHEMA = "aga.ouroboros-runtime-overlay/v3"
_GUARD_KEY = "AGA_OUROBOROS_RUNTIME_OVERLAY"
_SOURCE_KEY = "AGA_OUROBOROS_PINNED_SOURCE_DIR"
_HOOK_KEY = "AGA_OUROBOROS_OVERLAY_HOOK_INSTALLED"
_APPLIED_KEY = "AGA_OUROBOROS_OVERLAY_APPLIED"
_MCP_APPLIED_KEY = "AGA_OUROBOROS_MCP_RETRY_APPLIED"
_POST_TASK_APPLIED_KEY = "AGA_OUROBOROS_POST_TASK_POLICY_APPLIED"
_CONSOLIDATOR_MODULE = "ouroboros.consolidator"
_MCP_CLIENT_MODULE = "ouroboros.mcp_client"
_AGENT_TASK_PIPELINE_MODULE = "ouroboros.agent_task_pipeline"
_TARGET_MODULES = frozenset(
    {
        _CONSOLIDATOR_MODULE,
        _MCP_CLIENT_MODULE,
        _AGENT_TASK_PIPELINE_MODULE,
    }
)
_PINNED_VERSION = "6.64.1"
_PINNED_SOURCE_COMMIT = "554b3eeeca345298d6dcc5711195ea9acec450bd"
_UPSTREAM_MODEL = "google/gemini-3.5-flash"
_PINNED_MODEL = "deepseek/deepseek-v4-pro"
_HOOK_MARKER = "aga_deferred_runtime_overlay_v3"
_FINALIZE_ARGUMENT_KEYS = frozenset(
    {"review_id", "review_digest", "task_digest", "semantic_result"}
)


def _fatal() -> None:
    try:
        os.write(2, b"ouroboros runtime overlay bootstrap failed\n")
    finally:
        os._exit(78)


def _git_environment() -> dict[str, str]:
    environment = {"PATH": os.environ.get("PATH", os.defpath)}
    for key in ("LANG", "LC_ALL", "LC_CTYPE"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _bounded_git(source_dir: Path, arguments: Sequence[str]) -> str:
    result = subprocess.run(
        ("git", "-C", str(source_dir), *arguments),
        cwd=str(source_dir),
        env=_git_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15.0,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 64 * 1024:
        raise RuntimeError("source_verification_failed")
    return result.stdout.strip()


def _verified_source_dir() -> Path:
    raw = str(os.environ.get(_SOURCE_KEY) or "").strip()
    if not raw:
        raise RuntimeError("overlay_source_missing")
    source_dir = Path(raw).resolve(strict=True)
    if (
        not source_dir.is_dir()
        or not (source_dir / ".git").exists()
        or not (source_dir / "server.py").is_file()
        or not (source_dir / "ouroboros" / "consolidator.py").is_file()
        or not (source_dir / "ouroboros" / "mcp_client.py").is_file()
        or not (source_dir / "ouroboros" / "agent_task_pipeline.py").is_file()
    ):
        raise RuntimeError("source_unavailable")
    if _bounded_git(source_dir, ("rev-parse", "HEAD")) != _PINNED_SOURCE_COMMIT:
        raise RuntimeError("source_commit_mismatch")
    if _bounded_git(source_dir, ("status", "--porcelain")):
        raise RuntimeError("source_dirty")
    if importlib.metadata.version("ouroboros") != _PINNED_VERSION:
        raise RuntimeError("runtime_version_mismatch")
    return source_dir


def _verify_and_pin(module: ModuleType) -> None:
    source_dir = _verified_source_dir()
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise RuntimeError("source_import_mismatch")
    if Path(raw_path).resolve(strict=True) != (
        source_dir / "ouroboros" / "consolidator.py"
    ).resolve(strict=True):
        raise RuntimeError("source_import_mismatch")
    if getattr(module, "CONSOLIDATION_MODEL", None) != _UPSTREAM_MODEL:
        raise RuntimeError("consolidation_contract_mismatch")
    setattr(module, "CONSOLIDATION_MODEL", _PINNED_MODEL)
    if getattr(module, "CONSOLIDATION_MODEL", None) != _PINNED_MODEL:
        raise RuntimeError("consolidation_overlay_failed")
    os.environ[_APPLIED_KEY] = _SCHEMA


def _verify_and_patch_mcp_client(module: ModuleType) -> None:
    """Retry one idempotent AGA finalize after the pinned SDK TaskGroup race."""

    source_dir = _verified_source_dir()
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise RuntimeError("source_import_mismatch")
    if Path(raw_path).resolve(strict=True) != (
        source_dir / "ouroboros" / "mcp_client.py"
    ).resolve(strict=True):
        raise RuntimeError("source_import_mismatch")
    original = getattr(module, "_call_tool_async", None)
    if not callable(original):
        raise RuntimeError("mcp_client_contract_mismatch")
    if getattr(original, "aga_finalize_retry_overlay", None) == _SCHEMA:
        os.environ[_MCP_APPLIED_KEY] = _SCHEMA
        return

    async def _bounded_finalize_retry(
        cfg: Any,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_sec: int,
    ) -> str:
        retry_candidate = (
            getattr(cfg, "id", None) == "aga"
            and tool_name == "aga_finalize_review"
            and isinstance(arguments, dict)
            and frozenset(arguments) == _FINALIZE_ARGUMENT_KEYS
        )
        # Preserve a value-identical JSON argument tree for both physical
        # attempts.  A successful first finalize is immutable/idempotent at the
        # AGA service boundary; the second call can only return that result or
        # a finalization conflict, never silently replace it.
        attempt_arguments = (
            copy.deepcopy(arguments) if retry_candidate else arguments
        )
        try:
            return await original(
                cfg, tool_name, attempt_arguments, timeout_sec=timeout_sec
            )
        except Exception as exc:
            if type(exc) is not ExceptionGroup or not retry_candidate:
                raise
            return await original(
                cfg,
                tool_name,
                copy.deepcopy(attempt_arguments),
                timeout_sec=timeout_sec,
            )

    setattr(_bounded_finalize_retry, "aga_finalize_retry_overlay", _SCHEMA)
    setattr(_bounded_finalize_retry, "aga_finalize_retry_original", original)
    setattr(module, "_call_tool_async", _bounded_finalize_retry)
    if (
        getattr(
            getattr(module, "_call_tool_async", None),
            "aga_finalize_retry_overlay",
            None,
        )
        != _SCHEMA
    ):
        raise RuntimeError("mcp_retry_overlay_failed")
    os.environ[_MCP_APPLIED_KEY] = _SCHEMA


def _is_managed_aga_synthetic_task(task: Any) -> bool:
    if not isinstance(task, dict):
        return False
    metadata = task.get("metadata")
    if not isinstance(metadata, dict):
        return False
    review_id = metadata.get("aga_review_id")
    prompt_sha256 = metadata.get("aga_prompt_sha256")
    project_id = task.get("project_id")
    disabled = metadata.get("disabled_tools")
    workspace = str(task.get("workspace_root") or "")
    description = str(task.get("description") or "")
    return (
        task.get("type") == "task"
        and task.get("delegation_role") == "root"
        and task.get("workspace_mode") == "external"
        and task.get("memory_mode") == "empty"
        and isinstance(review_id, str)
        and review_id.startswith("aga-")
        and 5 <= len(review_id) <= 128
        and metadata.get("aga_idempotency_key") == review_id
        and metadata.get("data_classification") == "synthetic-public"
        and metadata.get("expected_model_id") == _PINNED_MODEL
        and metadata.get("allowed_resources") == {"network": True, "web": False}
        and isinstance(prompt_sha256, str)
        and len(prompt_sha256) == 64
        and all(character in "0123456789abcdef" for character in prompt_sha256)
        and isinstance(project_id, str)
        and project_id.startswith("aga-")
        and len(project_id) == 36
        and all(character in "0123456789abcdef" for character in project_id[4:])
        and isinstance(disabled, list)
        and all(
            name in disabled
            for name in (
                "write_file",
                "run_command",
                "web_search",
                "mcp_aga__aga_parse_diagram",
            )
        )
        and "/aga-synthetic-public/ouroboros-cases/" in workspace
        and description.startswith("AGA orchestration prompt v1.0.")
        and "data_classification: synthetic-public" in description
    )


def _verify_and_patch_agent_task_pipeline(module: ModuleType) -> None:
    """Skip only irrelevant paid memory synthesis for managed AGA evaluations."""

    source_dir = _verified_source_dir()
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise RuntimeError("source_import_mismatch")
    if Path(raw_path).resolve(strict=True) != (
        source_dir / "ouroboros" / "agent_task_pipeline.py"
    ).resolve(strict=True):
        raise RuntimeError("source_import_mismatch")
    original = getattr(module, "_run_post_task_processing_async", None)
    checkpoint = getattr(module, "_set_root_post_task_checkpoint", None)
    is_root = getattr(module, "_is_root_post_task", None)
    if not callable(original) or not callable(checkpoint) or not callable(is_root):
        raise RuntimeError("post_task_contract_mismatch")
    if getattr(original, "aga_post_task_policy_overlay", None) == _SCHEMA:
        os.environ[_POST_TASK_APPLIED_KEY] = _SCHEMA
        return

    def _managed_post_task_policy(
        env: Any,
        task: dict[str, Any],
        usage: dict[str, Any],
        llm_trace: dict[str, Any],
        review_evidence: dict[str, Any],
        drive_logs: Path,
        *,
        blocking: bool = False,
        on_reflection: Any = None,
    ) -> dict[str, Any] | None:
        if not _is_managed_aga_synthetic_task(task):
            return original(
                env,
                task,
                usage,
                llm_trace,
                review_evidence,
                drive_logs,
                blocking=blocking,
                on_reflection=on_reflection,
            )
        if not is_root(task):
            raise RuntimeError("aga_post_task_root_contract_mismatch")
        checkpoint(env, task, "completed")
        return None

    setattr(_managed_post_task_policy, "aga_post_task_policy_overlay", _SCHEMA)
    setattr(_managed_post_task_policy, "aga_post_task_policy_original", original)
    setattr(module, "_run_post_task_processing_async", _managed_post_task_policy)
    if (
        getattr(
            getattr(module, "_run_post_task_processing_async", None),
            "aga_post_task_policy_overlay",
            None,
        )
        != _SCHEMA
    ):
        raise RuntimeError("post_task_policy_overlay_failed")
    os.environ[_POST_TASK_APPLIED_KEY] = _SCHEMA


class _DeferredRuntimeLoader(importlib.abc.Loader):
    def __init__(self, delegate: Any, fullname: str) -> None:
        self._delegate = delegate
        self._fullname = fullname

    def create_module(self, spec: Any) -> ModuleType | None:
        create = getattr(self._delegate, "create_module", None)
        return create(spec) if callable(create) else None

    def exec_module(self, module: ModuleType) -> None:
        try:
            execute = getattr(self._delegate, "exec_module", None)
            if not callable(execute):
                raise RuntimeError("runtime_loader_contract_mismatch")
            execute(module)
            if self._fullname == _CONSOLIDATOR_MODULE:
                _verify_and_pin(module)
            elif self._fullname == _MCP_CLIENT_MODULE:
                _verify_and_patch_mcp_client(module)
            elif self._fullname == _AGENT_TASK_PIPELINE_MODULE:
                _verify_and_patch_agent_task_pipeline(module)
            else:
                raise RuntimeError("runtime_overlay_target_mismatch")
        except BaseException:
            _fatal()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


class _DeferredRuntimeFinder(importlib.abc.MetaPathFinder):
    aga_overlay_marker = _HOOK_MARKER

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> Any:
        if fullname not in _TARGET_MODULES:
            return None
        try:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec is None or spec.loader is None:
                raise RuntimeError("consolidator_spec_unavailable")
            if not isinstance(spec.loader, _DeferredRuntimeLoader):
                spec.loader = _DeferredRuntimeLoader(spec.loader, fullname)
            return spec
        except BaseException:
            _fatal()


def _install_hook() -> None:
    if any(
        getattr(finder, "aga_overlay_marker", "") == _HOOK_MARKER
        for finder in sys.meta_path
    ):
        os.environ[_HOOK_KEY] = _SCHEMA
        return
    sys.meta_path.insert(0, _DeferredRuntimeFinder())
    os.environ[_HOOK_KEY] = _SCHEMA


if os.environ.get(_GUARD_KEY) == _SCHEMA:
    try:
        _install_hook()
    except BaseException:
        _fatal()
