#!/usr/bin/env python3
"""Probe managed worker MCP discovery without starting a model task.

The caller supplies only the profile-owned pinned source checkout. The process
must already be running under the v4 ``sitecustomize`` overlay; it builds the
same initial ToolRegistry envelope a worker uses for both managed AGA stages.
Only a small path-free JSON attestation is written to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

try:
    from scripts.ouroboros_models import selected_model_id
except ModuleNotFoundError:  # direct ``python scripts/...`` entrypoint
    from ouroboros_models import selected_model_id


SCHEMA = "aga.ouroboros-worker-mcp-probe/v1"
OVERLAY_SCHEMA = "aga.ouroboros-runtime-overlay/v4"
MANAGED_TASK_SCHEMA = "aga.ouroboros-managed-task/v1"
PINNED_VERSION = "6.64.1"
PINNED_SOURCE_COMMIT = "554b3eeeca345298d6dcc5711195ea9acec450bd"
PINNED_MODEL = selected_model_id()
MCP_SERVER_ID = "aga"
MCP_REFRESH_TIMEOUT_SECONDS = 20
AGA_TOOL_RESULT_LIMIT_CHARS = 80_000
STAGE_TOOLS = {
    "review": (
        "aga_prepare_review",
        "aga_seaf_lookup",
        "aga_parse_diagram",
        "aga_finalize_review",
    ),
    "remediation": (
        "aga_prepare_remediation",
        "aga_finalize_remediation",
    ),
}
GATEWAY_TOOLS = STAGE_TOOLS["review"] + STAGE_TOOLS["remediation"]


class ProbeError(RuntimeError):
    """A secret- and path-free worker readiness error."""


def _emit(value: Mapping[str, Any]) -> None:
    print(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def _source_dir(raw: str) -> Path:
    environment_source = str(
        os.environ.get("AGA_OUROBOROS_PINNED_SOURCE_DIR") or ""
    ).strip()
    requested_path = Path(raw)
    expected_path = Path(environment_source)
    try:
        source = requested_path.resolve(strict=True)
        expected = expected_path.resolve(strict=True)
    except OSError as exc:
        raise ProbeError("worker_source_unavailable") from exc
    if (
        source != expected
        or requested_path.is_symlink()
        or expected_path.is_symlink()
        or not source.is_dir()
        or not (source / "ouroboros" / "mcp_client.py").is_file()
        or not (source / "ouroboros" / "tool_capabilities.py").is_file()
        or not (source / "ouroboros" / "tools" / "registry.py").is_file()
    ):
        raise ProbeError("worker_source_mismatch")
    return source


def _context_roots(source: Path) -> tuple[Path, Path]:
    raw_home = str(os.environ.get("HOME") or "").strip()
    raw_tmp = str(os.environ.get("TMPDIR") or "").strip()
    if not raw_home or not raw_tmp:
        raise ProbeError("worker_context_unavailable")
    try:
        drive = (Path(raw_home) / "Ouroboros" / "data").resolve(strict=True)
        workspace = Path(raw_tmp).resolve(strict=True)
    except OSError as exc:
        raise ProbeError("worker_context_unavailable") from exc
    if not drive.is_dir() or not workspace.is_dir():
        raise ProbeError("worker_context_unavailable")
    for child, parent in (
        (workspace, source),
        (source, workspace),
        (workspace, drive),
        (drive, workspace),
        (drive, source),
        (source, drive),
    ):
        try:
            child.relative_to(parent)
        except ValueError:
            continue
        raise ProbeError("worker_context_overlap")
    return drive, workspace


def _metadata(stage: str, disabled_tools: list[str]) -> dict[str, Any]:
    return {
        "aga_runtime_contract": MANAGED_TASK_SCHEMA,
        "aga_mcp_stage": stage,
        "aga_expected_mcp_tools": list(STAGE_TOOLS[stage]),
        "data_classification": "synthetic-public",
        "expected_model_id": PINNED_MODEL,
        "allowed_resources": {"network": True, "web": False},
        "disabled_tools": disabled_tools,
    }


def _schema_names(schemas: Any) -> tuple[str, ...]:
    if not isinstance(schemas, list):
        raise ProbeError("worker_envelope_invalid")
    names: list[str] = []
    for schema in schemas:
        if not isinstance(schema, dict):
            raise ProbeError("worker_envelope_invalid")
        function = schema.get("function")
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(name, str) or not name:
            raise ProbeError("worker_envelope_invalid")
        names.append(name)
    if len(names) != len(set(names)):
        raise ProbeError("worker_envelope_invalid")
    return tuple(names)


def _stage_probe(
    stage: str,
    *,
    source: Path,
    drive: Path,
    workspace: Path,
    registry_module: Any,
    initial_tool_schemas: Any,
) -> dict[str, Any]:
    other_tools = tuple(
        name
        for other_stage, names in STAGE_TOOLS.items()
        if other_stage != stage
        for name in names
    )
    native_disabled = sorted(registry_module._WORKSPACE_ALLOWED_TOOLS)
    disabled = native_disabled + [
        f"mcp_{MCP_SERVER_ID}__{name}" for name in other_tools
    ]
    registry = registry_module.ToolRegistry(source, drive)
    context = registry._ctx
    context.system_repo_dir = source
    context.workspace_root = workspace
    context.workspace_mode = "external"
    context.memory_mode = "empty"
    context.project_id = "aga-" + "0" * 32
    context.task_metadata = _metadata(stage, disabled)
    context.task_contract = {
        "allowed_resources": {"network": True, "web": False},
        "disabled_tools": disabled,
    }
    schemas = initial_tool_schemas(registry)
    actual = _schema_names(schemas)
    expected = tuple(
        f"mcp_{MCP_SERVER_ID}__{name}" for name in STAGE_TOOLS[stage]
    )
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise ProbeError("worker_envelope_mismatch")
    return {
        "expected_tools": list(STAGE_TOOLS[stage]),
        "active_tools": list(STAGE_TOOLS[stage]),
        "prefixed_tools": list(expected),
    }


def run(argv: Sequence[str]) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True)
    arguments = parser.parse_args(argv)
    source = _source_dir(arguments.source_dir)
    drive, workspace = _context_roots(source)

    import ouroboros.mcp_client as mcp_client
    import ouroboros.tool_capabilities as tool_capabilities
    import ouroboros.tools.registry as registry_module
    from ouroboros.tool_policy import initial_tool_schemas

    if (
        os.environ.get("AGA_OUROBOROS_RUNTIME_OVERLAY") != OVERLAY_SCHEMA
        or os.environ.get("AGA_OUROBOROS_OVERLAY_HOOK_INSTALLED")
        != OVERLAY_SCHEMA
        or os.environ.get("AGA_OUROBOROS_MCP_DISCOVERY_APPLIED")
        != OVERLAY_SCHEMA
        or os.environ.get("AGA_OUROBOROS_TOOL_REGISTRY_APPLIED")
        != OVERLAY_SCHEMA
        or os.environ.get("AGA_OUROBOROS_TOOL_RESULT_LIMIT_APPLIED")
        != OVERLAY_SCHEMA
        or getattr(
            mcp_client.ensure_configured_from_settings,
            "aga_worker_discovery_overlay",
            None,
        )
        != OVERLAY_SCHEMA
        or getattr(
            registry_module.ToolRegistry.schemas,
            "aga_worker_envelope_overlay",
            None,
        )
        != OVERLAY_SCHEMA
        or getattr(
            tool_capabilities,
            "aga_bounded_tool_result_overlay",
            None,
        )
        != OVERLAY_SCHEMA
    ):
        raise ProbeError("worker_overlay_not_active")

    result_limits = getattr(tool_capabilities, "TOOL_RESULT_LIMITS", None)
    bounded_names = GATEWAY_TOOLS + tuple(
        f"mcp_{MCP_SERVER_ID}__{name}" for name in GATEWAY_TOOLS
    )
    if not isinstance(result_limits, dict) or any(
        result_limits.get(name) != AGA_TOOL_RESULT_LIMIT_CHARS
        for name in bounded_names
    ):
        raise ProbeError("worker_tool_result_limit_mismatch")

    stages = {
        stage: _stage_probe(
            stage,
            source=source,
            drive=drive,
            workspace=workspace,
            registry_module=registry_module,
            initial_tool_schemas=initial_tool_schemas,
        )
        for stage in ("review", "remediation")
    }
    manager = mcp_client.get_manager()
    registered = manager.list_tools_for_registry()
    if (
        manager.server_ids() != [MCP_SERVER_ID]
        or manager.tool_timeout_sec() != MCP_REFRESH_TIMEOUT_SECONDS
        or not isinstance(registered, list)
    ):
        raise ProbeError("worker_gateway_contract_mismatch")
    raw_names = [
        item.get("raw_name") if isinstance(item, dict) else None
        for item in registered
    ]
    prefixed_names = [
        item.get("name") if isinstance(item, dict) else None
        for item in registered
    ]
    expected_prefixed = [
        f"mcp_{MCP_SERVER_ID}__{name}" for name in GATEWAY_TOOLS
    ]
    if (
        raw_names != list(GATEWAY_TOOLS)
        or prefixed_names != expected_prefixed
    ):
        raise ProbeError("worker_gateway_tools_mismatch")
    return {
        "schema": SCHEMA,
        "status": "ready",
        "runtime_version": PINNED_VERSION,
        "source_commit": PINNED_SOURCE_COMMIT,
        "overlay_schema": OVERLAY_SCHEMA,
        "managed_task_schema": MANAGED_TASK_SCHEMA,
        "refresh_timeout_seconds": MCP_REFRESH_TIMEOUT_SECONDS,
        "aga_tool_result_limit_chars": AGA_TOOL_RESULT_LIMIT_CHARS,
        "gateway_discovery": {
            "server_id": MCP_SERVER_ID,
            "tools": list(GATEWAY_TOOLS),
            "prefixed_tools": expected_prefixed,
        },
        "worker_ready": stages,
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        _emit(run(sys.argv[1:] if argv is None else argv))
        return 0
    except Exception:
        _emit({"schema": SCHEMA, "status": "failed", "code": "worker_mcp_not_ready"})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
