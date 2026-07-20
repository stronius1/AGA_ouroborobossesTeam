"""Install deferred runtime hooks in every managed Ouroboros Python child.

Python imports ``sitecustomize`` before ``multiprocessing.spawn`` restores the
parent interpreter's venv ``sys.path``.  Importing Ouroboros here would therefore
let optional dependencies appear permanently unavailable in a spawned worker.
This module uses the standard library only and merely registers an import hook.
The hook verifies and patches the known ``ouroboros.consolidator`` model
constant, the narrow AGA-finalize transport retry, the bounded AGA MCP result
limit, and the managed-task MCP discovery lifecycle when those exact modules
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


_SCHEMA = "aga.ouroboros-runtime-overlay/v4"
_GUARD_KEY = "AGA_OUROBOROS_RUNTIME_OVERLAY"
_SOURCE_KEY = "AGA_OUROBOROS_PINNED_SOURCE_DIR"
_HOOK_KEY = "AGA_OUROBOROS_OVERLAY_HOOK_INSTALLED"
_APPLIED_KEY = "AGA_OUROBOROS_OVERLAY_APPLIED"
_MCP_APPLIED_KEY = "AGA_OUROBOROS_MCP_RETRY_APPLIED"
_MCP_DISCOVERY_APPLIED_KEY = "AGA_OUROBOROS_MCP_DISCOVERY_APPLIED"
_TOOL_REGISTRY_APPLIED_KEY = "AGA_OUROBOROS_TOOL_REGISTRY_APPLIED"
_TOOL_RESULT_LIMIT_APPLIED_KEY = "AGA_OUROBOROS_TOOL_RESULT_LIMIT_APPLIED"
_POST_TASK_APPLIED_KEY = "AGA_OUROBOROS_POST_TASK_POLICY_APPLIED"
_CONSOLIDATOR_MODULE = "ouroboros.consolidator"
_MCP_CLIENT_MODULE = "ouroboros.mcp_client"
_TOOL_CAPABILITIES_MODULE = "ouroboros.tool_capabilities"
_TOOL_REGISTRY_MODULE = "ouroboros.tools.registry"
_AGENT_TASK_PIPELINE_MODULE = "ouroboros.agent_task_pipeline"
_TARGET_MODULES = frozenset(
    {
        _CONSOLIDATOR_MODULE,
        _MCP_CLIENT_MODULE,
        _TOOL_CAPABILITIES_MODULE,
        _TOOL_REGISTRY_MODULE,
        _AGENT_TASK_PIPELINE_MODULE,
    }
)
_PINNED_VERSION = "6.64.1"
_PINNED_SOURCE_COMMIT = "554b3eeeca345298d6dcc5711195ea9acec450bd"
_UPSTREAM_MODEL = "google/gemini-3.5-flash"
_SUPPORTED_MODELS = frozenset(
    {
        "deepseek/deepseek-v4-pro",
        "moonshotai/kimi-k3",
    }
)
_PINNED_MODEL = str(
    os.environ.get("AGA_OUROBOROS_MODEL_ID") or "deepseek/deepseek-v4-pro"
).strip()
_HOOK_MARKER = "aga_deferred_runtime_overlay_v4"
_MANAGED_TASK_SCHEMA = "aga.ouroboros-managed-task/v1"
_MCP_REFRESH_TIMEOUT_SECONDS = 20
_MCP_SERVER_ID = "aga"
_REVIEW_MCP_TOOLS = (
    "aga_prepare_review",
    "aga_seaf_lookup",
    "aga_parse_diagram",
    "aga_finalize_review",
)
_REMEDIATION_MCP_TOOLS = (
    "aga_prepare_remediation",
    "aga_finalize_remediation",
)
_STAGE_MCP_TOOLS = {
    "review": _REVIEW_MCP_TOOLS,
    "remediation": _REMEDIATION_MCP_TOOLS,
}
_GATEWAY_MCP_TOOLS = _REVIEW_MCP_TOOLS + _REMEDIATION_MCP_TOOLS
_GATEWAY_PREFIXED_MCP_TOOLS = tuple(
    f"mcp_{_MCP_SERVER_ID}__{name}" for name in _GATEWAY_MCP_TOOLS
)
_AGA_TOOL_RESULT_LIMIT = 80_000
_TOOL_RESULT_LIMIT_MARKER = "aga_bounded_tool_result_overlay"
_FINALIZE_ARGUMENT_KEYS = frozenset(
    {"review_id", "review_digest", "task_digest", "semantic_result"}
)


def _fatal() -> None:
    try:
        os.write(2, b"ouroboros runtime overlay bootstrap failed\n")
    finally:
        os._exit(78)


if _PINNED_MODEL not in _SUPPORTED_MODELS:
    _fatal()


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
        or not (source_dir / "ouroboros" / "tool_capabilities.py").is_file()
        or not (source_dir / "ouroboros" / "tools" / "registry.py").is_file()
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


def _tool_names_from_manager(manager: Any) -> tuple[str, ...]:
    tools = manager.list_tools_for_registry()
    if not isinstance(tools, list):
        raise RuntimeError("mcp_registry_contract_mismatch")
    names: list[str] = []
    for item in tools:
        if not isinstance(item, dict):
            raise RuntimeError("mcp_registry_contract_mismatch")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise RuntimeError("mcp_registry_contract_mismatch")
        names.append(name)
    if len(names) != len(set(names)):
        raise RuntimeError("mcp_registry_contract_mismatch")
    return tuple(names)


def _verify_and_patch_mcp_client(module: ModuleType) -> None:
    """Install bounded initial discovery and the idempotent finalize retry."""

    source_dir = _verified_source_dir()
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise RuntimeError("source_import_mismatch")
    if Path(raw_path).resolve(strict=True) != (
        source_dir / "ouroboros" / "mcp_client.py"
    ).resolve(strict=True):
        raise RuntimeError("source_import_mismatch")

    original_call = getattr(module, "_call_tool_async", None)
    original_ensure = getattr(module, "ensure_configured_from_settings", None)
    get_manager = getattr(module, "get_manager", None)
    if not callable(original_call) or not callable(original_ensure) or not callable(
        get_manager
    ):
        raise RuntimeError("mcp_client_contract_mismatch")

    if getattr(original_call, "aga_finalize_retry_overlay", None) != _SCHEMA:

        async def _bounded_finalize_retry(
            cfg: Any,
            tool_name: str,
            arguments: dict[str, Any],
            *,
            timeout_sec: int,
        ) -> str:
            retry_candidate = (
                getattr(cfg, "id", None) == _MCP_SERVER_ID
                and tool_name == "aga_finalize_review"
                and isinstance(arguments, dict)
                and frozenset(arguments) == _FINALIZE_ARGUMENT_KEYS
            )
            # Preserve a value-identical JSON argument tree for both physical
            # attempts. A successful first finalize is immutable/idempotent at
            # the AGA service boundary.
            attempt_arguments = (
                copy.deepcopy(arguments) if retry_candidate else arguments
            )
            try:
                return await original_call(
                    cfg, tool_name, attempt_arguments, timeout_sec=timeout_sec
                )
            except Exception as exc:
                if type(exc) is not ExceptionGroup or not retry_candidate:
                    raise
                return await original_call(
                    cfg,
                    tool_name,
                    copy.deepcopy(attempt_arguments),
                    timeout_sec=timeout_sec,
                )

        setattr(_bounded_finalize_retry, "aga_finalize_retry_overlay", _SCHEMA)
        setattr(_bounded_finalize_retry, "aga_finalize_retry_original", original_call)
        setattr(module, "_call_tool_async", _bounded_finalize_retry)

    if getattr(original_ensure, "aga_worker_discovery_overlay", None) != _SCHEMA:

        def _bounded_initial_discovery(*, refresh: bool = False) -> None:
            # The pinned function returns early for a configured manager even
            # when it has no tools. Configure without its refresh branch, then
            # make exactly one bounded refresh decision from observable state.
            original_ensure(refresh=False)
            if not refresh:
                return
            manager = get_manager()
            required = (
                "is_configured",
                "is_enabled",
                "server_ids",
                "tool_timeout_sec",
                "enabled_servers_without_tools",
                "list_tools_for_registry",
                "refresh_all",
            )
            if any(not callable(getattr(manager, name, None)) for name in required):
                raise RuntimeError("mcp_manager_contract_mismatch")
            if not manager.is_configured() or not manager.is_enabled():
                return
            server_ids = manager.server_ids()
            if not isinstance(server_ids, list) or any(
                not isinstance(server_id, str) for server_id in server_ids
            ):
                raise RuntimeError("mcp_manager_contract_mismatch")
            names = _tool_names_from_manager(manager)
            missing_tools = bool(manager.enabled_servers_without_tools())
            isolated_aga = server_ids == [_MCP_SERVER_ID]
            aga_toolset_drift = isolated_aga and (
                len(names) != len(_GATEWAY_PREFIXED_MCP_TOOLS)
                or set(names) != set(_GATEWAY_PREFIXED_MCP_TOOLS)
            )
            if not missing_tools and not aga_toolset_drift:
                return
            timeout = manager.tool_timeout_sec()
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, int)
                or timeout < 1
                or timeout > _MCP_REFRESH_TIMEOUT_SECONDS
            ):
                raise RuntimeError("mcp_refresh_timeout_contract_mismatch")
            manager.refresh_all()

        setattr(
            _bounded_initial_discovery,
            "aga_worker_discovery_overlay",
            _SCHEMA,
        )
        setattr(
            _bounded_initial_discovery,
            "aga_worker_discovery_original",
            original_ensure,
        )
        setattr(module, "ensure_configured_from_settings", _bounded_initial_discovery)

    if (
        getattr(
            getattr(module, "_call_tool_async", None),
            "aga_finalize_retry_overlay",
            None,
        )
        != _SCHEMA
    ):
        raise RuntimeError("mcp_retry_overlay_failed")
    if (
        getattr(
            getattr(module, "ensure_configured_from_settings", None),
            "aga_worker_discovery_overlay",
            None,
        )
        != _SCHEMA
    ):
        raise RuntimeError("mcp_discovery_overlay_failed")
    os.environ[_MCP_APPLIED_KEY] = _SCHEMA
    os.environ[_MCP_DISCOVERY_APPLIED_KEY] = _SCHEMA


def _verify_and_patch_tool_capabilities(module: ModuleType) -> None:
    """Raise only the isolated AGA MCP result cap to a bounded 80k."""

    source_dir = _verified_source_dir()
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise RuntimeError("source_import_mismatch")
    if Path(raw_path).resolve(strict=True) != (
        source_dir / "ouroboros" / "tool_capabilities.py"
    ).resolve(strict=True):
        raise RuntimeError("source_import_mismatch")
    limits = getattr(module, "TOOL_RESULT_LIMITS", None)
    default_limit = getattr(module, "DEFAULT_TOOL_RESULT_LIMIT", None)
    if not isinstance(limits, dict) or default_limit != 15_000:
        raise RuntimeError("tool_result_limit_contract_mismatch")
    names = _GATEWAY_MCP_TOOLS + _GATEWAY_PREFIXED_MCP_TOOLS
    for name in names:
        current = limits.get(name)
        if current not in {None, _AGA_TOOL_RESULT_LIMIT}:
            raise RuntimeError("tool_result_limit_contract_mismatch")
    for name in names:
        limits[name] = _AGA_TOOL_RESULT_LIMIT
    if any(limits.get(name) != _AGA_TOOL_RESULT_LIMIT for name in names):
        raise RuntimeError("tool_result_limit_overlay_failed")
    setattr(module, _TOOL_RESULT_LIMIT_MARKER, _SCHEMA)
    os.environ[_TOOL_RESULT_LIMIT_APPLIED_KEY] = _SCHEMA


def _managed_stage_contract(metadata: Any) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(metadata, dict):
        return None
    marker = metadata.get("aga_runtime_contract")
    if marker is None:
        return None
    if marker != _MANAGED_TASK_SCHEMA:
        raise RuntimeError("aga_managed_task_contract_mismatch")
    stage = metadata.get("aga_mcp_stage")
    expected = metadata.get("aga_expected_mcp_tools")
    canonical = _STAGE_MCP_TOOLS.get(stage) if isinstance(stage, str) else None
    disabled = metadata.get("disabled_tools")
    if (
        canonical is None
        or not isinstance(expected, list)
        or expected != list(canonical)
        or metadata.get("data_classification") != "synthetic-public"
        or metadata.get("expected_model_id") != _PINNED_MODEL
        or metadata.get("allowed_resources") != {"network": True, "web": False}
        or not isinstance(disabled, list)
        or any(not isinstance(name, str) or not name for name in disabled)
        or len(disabled) != len(set(disabled))
        or "list_available_tools" not in disabled
        or "enable_tools" not in disabled
    ):
        raise RuntimeError("aga_managed_task_contract_mismatch")
    other_stage_tools = tuple(
        name
        for other_stage, names in _STAGE_MCP_TOOLS.items()
        if other_stage != stage
        for name in names
    )
    if any(
        f"mcp_{_MCP_SERVER_ID}__{name}" not in disabled
        for name in other_stage_tools
    ):
        raise RuntimeError("aga_managed_task_contract_mismatch")
    active = tuple(
        name
        for name in canonical
        if f"mcp_{_MCP_SERVER_ID}__{name}" not in disabled
    )
    if not active:
        raise RuntimeError("aga_managed_task_contract_mismatch")
    return stage, active


def _schema_tool_names(schemas: Any) -> tuple[str, ...]:
    if not isinstance(schemas, list):
        raise RuntimeError("aga_worker_tool_envelope_mismatch")
    names: list[str] = []
    for schema in schemas:
        if not isinstance(schema, dict):
            raise RuntimeError("aga_worker_tool_envelope_mismatch")
        function = schema.get("function")
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(name, str) or not name:
            raise RuntimeError("aga_worker_tool_envelope_mismatch")
        names.append(name)
    if len(names) != len(set(names)):
        raise RuntimeError("aga_worker_tool_envelope_mismatch")
    return tuple(names)


def _verify_and_patch_tool_registry(module: ModuleType) -> None:
    """Reject a managed task before any model call unless its envelope is exact."""

    source_dir = _verified_source_dir()
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise RuntimeError("source_import_mismatch")
    if Path(raw_path).resolve(strict=True) != (
        source_dir / "ouroboros" / "tools" / "registry.py"
    ).resolve(strict=True):
        raise RuntimeError("source_import_mismatch")
    registry_class = getattr(module, "ToolRegistry", None)
    original = getattr(registry_class, "schemas", None)
    if not isinstance(registry_class, type) or not callable(original):
        raise RuntimeError("tool_registry_contract_mismatch")
    if getattr(original, "aga_worker_envelope_overlay", None) == _SCHEMA:
        os.environ[_TOOL_REGISTRY_APPLIED_KEY] = _SCHEMA
        return

    def _managed_schemas(self: Any, core_only: bool = False) -> list[dict[str, Any]]:
        schemas = original(self, core_only=core_only)
        metadata = getattr(getattr(self, "_ctx", None), "task_metadata", None)
        contract = _managed_stage_contract(metadata)
        if contract is None or core_only:
            return schemas
        _stage, active_raw_tools = contract
        expected = tuple(
            f"mcp_{_MCP_SERVER_ID}__{name}" for name in active_raw_tools
        )
        actual = _schema_tool_names(schemas)
        if len(actual) != len(expected) or set(actual) != set(expected):
            # This exception is outside pinned ToolRegistry.schemas(), whose
            # internal discovery try/except would otherwise downgrade the error
            # to a capability omission and continue into a paid model call.
            raise RuntimeError("aga_mcp_worker_not_ready")
        return schemas

    setattr(_managed_schemas, "aga_worker_envelope_overlay", _SCHEMA)
    setattr(_managed_schemas, "aga_worker_envelope_original", original)
    setattr(registry_class, "schemas", _managed_schemas)
    if (
        getattr(
            getattr(registry_class, "schemas", None),
            "aga_worker_envelope_overlay",
            None,
        )
        != _SCHEMA
    ):
        raise RuntimeError("tool_registry_overlay_failed")
    os.environ[_TOOL_REGISTRY_APPLIED_KEY] = _SCHEMA


def _is_managed_aga_synthetic_task(task: Any) -> bool:
    if not isinstance(task, dict):
        return False
    metadata = task.get("metadata")
    if not isinstance(metadata, dict):
        return False
    contract = _managed_stage_contract(metadata)
    if contract is None:
        return False
    stage, _active_tools = contract
    project_id = task.get("project_id")
    workspace = str(task.get("workspace_root") or "")
    valid_project_id = isinstance(project_id, str) and (
        (
            project_id.startswith("aga-")
            and len(project_id) == 36
            and all(character in "0123456789abcdef" for character in project_id[4:])
        )
        or (
            project_id.startswith("aga-rmd-")
            and len(project_id) == 36
            and all(character in "0123456789abcdef" for character in project_id[8:])
        )
    )
    common = (
        task.get("type") == "task"
        and task.get("delegation_role") == "root"
        and task.get("workspace_mode") == "external"
        and task.get("memory_mode") == "empty"
        and valid_project_id
        and bool(workspace)
        and "\x00" not in workspace
    )
    if not common or stage != "review":
        return common
    review_id = metadata.get("aga_review_id")
    prompt_sha256 = metadata.get("aga_prompt_sha256")
    return (
        isinstance(review_id, str)
        and review_id.startswith("aga-")
        and 5 <= len(review_id) <= 128
        and metadata.get("aga_idempotency_key") == review_id
        and isinstance(prompt_sha256, str)
        and len(prompt_sha256) == 64
        and all(character in "0123456789abcdef" for character in prompt_sha256)
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
            elif self._fullname == _TOOL_CAPABILITIES_MODULE:
                _verify_and_patch_tool_capabilities(module)
            elif self._fullname == _TOOL_REGISTRY_MODULE:
                _verify_and_patch_tool_registry(module)
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
