#!/usr/bin/env python3
"""Launch the pinned Ouroboros server with project-owned runtime overlays.

Ouroboros v6.64.1 hard-codes its post-task consolidation/summary lane to a
different model, can skip initial MCP refresh in an already-configured worker
with no tools, and caps otherwise unknown tool results at 15k characters. The
AGA profile applies narrow in-memory patches for those exact pinned contracts,
including an 80k cap only for the six isolated AGA MCP tools, before importing
the official CLI. It never edits the verified upstream checkout.

The launcher is intentionally server-only and fail-closed.  A successful
process writes a small, owner-only attestation under the dedicated Ouroboros
HOME.  The project preflight independently verifies that attestation, the
profile PID record, and this live process before any paid task can start.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any, Mapping, Sequence

try:
    from scripts.ouroboros_models import selected_model_id
except ModuleNotFoundError:  # direct ``python scripts/...`` entrypoint
    from ouroboros_models import selected_model_id


PINNED_VERSION = "6.64.1"
PINNED_SOURCE_COMMIT = "554b3eeeca345298d6dcc5711195ea9acec450bd"
PINNED_MODEL = selected_model_id()
UPSTREAM_CONSOLIDATION_MODEL = "google/gemini-3.5-flash"
ATTESTATION_SCHEMA = "aga.ouroboros-runtime-overlay/v4"
ATTESTATION_FILENAME = "aga-runtime-overlay.json"
OVERLAY_GUARD_ENV = "AGA_OUROBOROS_RUNTIME_OVERLAY"
OVERLAY_SOURCE_ENV = "AGA_OUROBOROS_PINNED_SOURCE_DIR"
OVERLAY_HOOK_ENV = "AGA_OUROBOROS_OVERLAY_HOOK_INSTALLED"
OVERLAY_APPLIED_ENV = "AGA_OUROBOROS_OVERLAY_APPLIED"
DEFERRED_HOOK_MARKER = "aga_deferred_runtime_overlay_v4"
MCP_RETRY_APPLIED_ENV = "AGA_OUROBOROS_MCP_RETRY_APPLIED"
MCP_RETRY_MARKER = "aga_finalize_retry_overlay"
MCP_DISCOVERY_APPLIED_ENV = "AGA_OUROBOROS_MCP_DISCOVERY_APPLIED"
MCP_DISCOVERY_MARKER = "aga_worker_discovery_overlay"
TOOL_REGISTRY_APPLIED_ENV = "AGA_OUROBOROS_TOOL_REGISTRY_APPLIED"
TOOL_REGISTRY_MARKER = "aga_worker_envelope_overlay"
TOOL_RESULT_LIMIT_APPLIED_ENV = "AGA_OUROBOROS_TOOL_RESULT_LIMIT_APPLIED"
TOOL_RESULT_LIMIT_MARKER = "aga_bounded_tool_result_overlay"
POST_TASK_POLICY_APPLIED_ENV = "AGA_OUROBOROS_POST_TASK_POLICY_APPLIED"
POST_TASK_POLICY_MARKER = "aga_post_task_policy_overlay"
MANAGED_TASK_SCHEMA = "aga.ouroboros-managed-task/v1"
MCP_REFRESH_TIMEOUT_SECONDS = 20
GATEWAY_MCP_TOOLS = (
    "aga_prepare_review",
    "aga_seaf_lookup",
    "aga_parse_diagram",
    "aga_finalize_review",
    "aga_prepare_remediation",
    "aga_finalize_remediation",
)
BOOTSTRAP_PATH = Path(__file__).resolve().parent / (
    "ouroboros_overlay_bootstrap/sitecustomize.py"
)
EXPECTED_SERVER_ARGUMENTS = (
    "server",
    "--host",
    "127.0.0.1",
    "--port",
    "8765",
    "--no-ui",
)


class OverlayError(RuntimeError):
    """A typed launcher error whose code contains no private path or payload."""


def _bounded_git(source_dir: Path, arguments: Sequence[str]) -> str:
    environment = {"PATH": os.environ.get("PATH", os.defpath)}
    try:
        result = subprocess.run(
            ("git", "-C", str(source_dir), *arguments),
            cwd=str(source_dir),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OverlayError("source_verification_failed") from exc
    if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 64 * 1024:
        raise OverlayError("source_verification_failed")
    return result.stdout.strip()


def _verified_source_dir(raw: str) -> Path:
    try:
        source_dir = Path(raw).resolve(strict=True)
    except OSError as exc:
        raise OverlayError("source_unavailable") from exc
    if (
        not source_dir.is_dir()
        or not (source_dir / ".git").exists()
        or not (source_dir / "server.py").is_file()
        or not (source_dir / "ouroboros" / "consolidator.py").is_file()
        or not (source_dir / "ouroboros" / "mcp_client.py").is_file()
        or not (source_dir / "ouroboros" / "tool_capabilities.py").is_file()
        or not (source_dir / "ouroboros" / "tools" / "registry.py").is_file()
        or not (source_dir / "ouroboros" / "agent_task_pipeline.py").is_file()
        or not (source_dir / "ouroboros" / "cli.py").is_file()
    ):
        raise OverlayError("source_unavailable")
    if _bounded_git(source_dir, ("rev-parse", "HEAD")) != PINNED_SOURCE_COMMIT:
        raise OverlayError("source_commit_mismatch")
    if _bounded_git(source_dir, ("status", "--porcelain")):
        raise OverlayError("source_dirty")
    try:
        installed_version = importlib.metadata.version("ouroboros")
    except importlib.metadata.PackageNotFoundError as exc:
        raise OverlayError("runtime_not_installed") from exc
    if installed_version != PINNED_VERSION:
        raise OverlayError("runtime_version_mismatch")
    return source_dir


def _require_module_from_source(
    module: ModuleType,
    *,
    expected_path: Path,
) -> None:
    raw_path = getattr(module, "__file__", None)
    if not isinstance(raw_path, str):
        raise OverlayError("source_import_mismatch")
    try:
        module_path = Path(raw_path).resolve(strict=True)
        expected = expected_path.resolve(strict=True)
    except OSError as exc:
        raise OverlayError("source_import_mismatch") from exc
    if module_path != expected:
        raise OverlayError("source_import_mismatch")


def _pin_consolidation_model(module: ModuleType) -> None:
    """Pin only the known v6.64.1 constant and reject upstream drift."""

    current = getattr(module, "CONSOLIDATION_MODEL", None)
    if current == PINNED_MODEL:
        return
    if current != UPSTREAM_CONSOLIDATION_MODEL:
        raise OverlayError("consolidation_contract_mismatch")
    setattr(module, "CONSOLIDATION_MODEL", PINNED_MODEL)
    if getattr(module, "CONSOLIDATION_MODEL", None) != PINNED_MODEL:
        raise OverlayError("consolidation_overlay_failed")


def _attestation_path() -> Path:
    home = str(os.environ.get("HOME") or "").strip()
    if not home:
        raise OverlayError("profile_home_missing")
    profile_home = Path(home)
    if not profile_home.is_absolute():
        raise OverlayError("profile_home_invalid")
    state_dir = profile_home / "Ouroboros" / "data" / "state"
    if (
        not state_dir.is_dir()
        or state_dir.is_symlink()
        or stat_mode(state_dir) != 0o700
    ):
        raise OverlayError("profile_state_not_private")
    return state_dir / ATTESTATION_FILENAME


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _launcher_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise OverlayError("launcher_integrity_unavailable") from exc


def _bootstrap_sha256() -> str:
    try:
        return hashlib.sha256(BOOTSTRAP_PATH.read_bytes()).hexdigest()
    except OSError as exc:
        raise OverlayError("bootstrap_integrity_unavailable") from exc


def apply_runtime_overlay(source_dir: Path) -> ModuleType:
    """Verify source and pin the consolidator lane in the current interpreter."""

    verified_source = _verified_source_dir(str(source_dir))
    source_text = str(verified_source)
    sys.path[:] = [
        source_text,
        *[
            entry
            for entry in sys.path
            if entry and Path(entry).resolve(strict=False) != verified_source
        ],
    ]
    importlib.invalidate_caches()
    consolidator = importlib.import_module("ouroboros.consolidator")
    _require_module_from_source(
        consolidator,
        expected_path=verified_source / "ouroboros" / "consolidator.py",
    )
    _pin_consolidation_model(consolidator)
    return consolidator


def _atomic_write_attestation(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise OverlayError("unsafe_attestation_path")
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=path.parent)
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(
                dict(value),
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        path.chmod(0o600)
    except (OSError, TypeError, ValueError) as exc:
        raise OverlayError("attestation_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _remove_own_attestation(path: Path) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            return
        if path.stat().st_size > 16 * 1024:
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping) and payload.get("pid") == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("runtime_arguments", nargs=argparse.REMAINDER)
    return parser


def run(argv: Sequence[str]) -> int:
    arguments = _build_parser().parse_args(argv)
    runtime_arguments = list(arguments.runtime_arguments)
    if runtime_arguments and runtime_arguments[0] == "--":
        runtime_arguments.pop(0)
    if tuple(runtime_arguments) != EXPECTED_SERVER_ARGUMENTS:
        raise OverlayError("unsupported_runtime_arguments")

    try:
        requested_source = Path(arguments.source_dir).resolve(strict=True)
        environment_source = Path(
            str(os.environ.get(OVERLAY_SOURCE_ENV) or "")
        ).resolve(strict=True)
    except OSError as exc:
        raise OverlayError("overlay_source_mismatch") from exc
    if (
        os.environ.get(OVERLAY_GUARD_ENV) != ATTESTATION_SCHEMA
        or requested_source != environment_source
        or os.environ.get(OVERLAY_HOOK_ENV) != ATTESTATION_SCHEMA
        or not any(
            getattr(finder, "aga_overlay_marker", "") == DEFERRED_HOOK_MARKER
            for finder in sys.meta_path
        )
    ):
        raise OverlayError("overlay_bootstrap_not_active")
    bootstrap_module = sys.modules.get("sitecustomize")
    if not isinstance(bootstrap_module, ModuleType):
        raise OverlayError("overlay_bootstrap_not_active")
    _require_module_from_source(
        bootstrap_module,
        expected_path=BOOTSTRAP_PATH,
    )
    source_dir = _verified_source_dir(str(requested_source))
    consolidator = apply_runtime_overlay(source_dir)
    if os.environ.get(OVERLAY_APPLIED_ENV) != ATTESTATION_SCHEMA:
        raise OverlayError("overlay_hook_not_applied")
    cli = importlib.import_module("ouroboros.cli")
    _require_module_from_source(cli, expected_path=source_dir / "ouroboros" / "cli.py")
    mcp_client = importlib.import_module("ouroboros.mcp_client")
    _require_module_from_source(
        mcp_client,
        expected_path=source_dir / "ouroboros" / "mcp_client.py",
    )
    tool_capabilities = importlib.import_module("ouroboros.tool_capabilities")
    _require_module_from_source(
        tool_capabilities,
        expected_path=source_dir / "ouroboros" / "tool_capabilities.py",
    )
    tool_registry = importlib.import_module("ouroboros.tools.registry")
    _require_module_from_source(
        tool_registry,
        expected_path=source_dir / "ouroboros" / "tools" / "registry.py",
    )
    agent_task_pipeline = importlib.import_module("ouroboros.agent_task_pipeline")
    _require_module_from_source(
        agent_task_pipeline,
        expected_path=source_dir / "ouroboros" / "agent_task_pipeline.py",
    )
    if getattr(consolidator, "CONSOLIDATION_MODEL", None) != PINNED_MODEL:
        raise OverlayError("consolidation_overlay_lost")
    if (
        os.environ.get(MCP_RETRY_APPLIED_ENV) != ATTESTATION_SCHEMA
        or getattr(
            getattr(mcp_client, "_call_tool_async", None),
            MCP_RETRY_MARKER,
            None,
        )
        != ATTESTATION_SCHEMA
    ):
        raise OverlayError("mcp_retry_overlay_lost")
    if (
        os.environ.get(MCP_DISCOVERY_APPLIED_ENV) != ATTESTATION_SCHEMA
        or getattr(
            getattr(mcp_client, "ensure_configured_from_settings", None),
            MCP_DISCOVERY_MARKER,
            None,
        )
        != ATTESTATION_SCHEMA
    ):
        raise OverlayError("mcp_discovery_overlay_lost")
    if (
        os.environ.get(TOOL_RESULT_LIMIT_APPLIED_ENV) != ATTESTATION_SCHEMA
        or getattr(tool_capabilities, TOOL_RESULT_LIMIT_MARKER, None)
        != ATTESTATION_SCHEMA
    ):
        raise OverlayError("tool_result_limit_overlay_lost")
    registry_class = getattr(tool_registry, "ToolRegistry", None)
    if (
        os.environ.get(TOOL_REGISTRY_APPLIED_ENV) != ATTESTATION_SCHEMA
        or getattr(
            getattr(registry_class, "schemas", None),
            TOOL_REGISTRY_MARKER,
            None,
        )
        != ATTESTATION_SCHEMA
    ):
        raise OverlayError("tool_registry_overlay_lost")
    if (
        os.environ.get(POST_TASK_POLICY_APPLIED_ENV) != ATTESTATION_SCHEMA
        or getattr(
            getattr(agent_task_pipeline, "_run_post_task_processing_async", None),
            POST_TASK_POLICY_MARKER,
            None,
        )
        != ATTESTATION_SCHEMA
    ):
        raise OverlayError("post_task_policy_overlay_lost")

    attestation_path = _attestation_path()
    _atomic_write_attestation(
        attestation_path,
        {
            "schema": ATTESTATION_SCHEMA,
            "pid": os.getpid(),
            "runtime_version": PINNED_VERSION,
            "source_commit": PINNED_SOURCE_COMMIT,
            "source_clean": True,
            "model": PINNED_MODEL,
            "consolidation_model": PINNED_MODEL,
            "launcher_sha256": _launcher_sha256(),
            "spawn_bootstrap": True,
            "bootstrap_mode": "deferred_runtime_import_hooks",
            "bootstrap_sha256": _bootstrap_sha256(),
            "finalize_transport_retry": "exception_group_once",
            "worker_discovery_contract": "synchronous_exact_stage_fail_closed",
            "managed_task_schema": MANAGED_TASK_SCHEMA,
            "mcp_refresh_timeout_seconds": MCP_REFRESH_TIMEOUT_SECONDS,
            "gateway_mcp_tool_count": len(GATEWAY_MCP_TOOLS),
            "aga_post_task_policy": "skip_synthetic_public_memory_synthesis",
        },
    )
    try:
        main = getattr(cli, "main", None)
        if not callable(main):
            raise OverlayError("cli_contract_mismatch")
        return int(main(runtime_arguments))
    finally:
        _remove_own_attestation(attestation_path)


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except OverlayError as exc:
        print(f"ouroboros runtime overlay: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print("ouroboros runtime overlay: internal_overlay_error", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
