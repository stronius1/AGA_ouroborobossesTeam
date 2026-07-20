#!/usr/bin/env python3
"""Manage the isolated, persistent Ouroboros profile used by AGA.

The OpenRouter credential is accepted only by the interactive ``configure-key``
command.  It is never accepted as an argument or copied from the process
environment.  Runtime commands receive a small allowlisted environment whose
``HOME`` points at the dedicated profile; Ouroboros reads the credential from
its owner-only settings file.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Sequence
import urllib.request
import uuid

try:
    from scripts.ouroboros_models import MODEL_ENV, selected_model_id
except ModuleNotFoundError:  # direct ``python scripts/...`` entrypoint
    from ouroboros_models import MODEL_ENV, selected_model_id


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PINNED_VERSION = "6.64.1"
PINNED_SOURCE_COMMIT = "554b3eeeca345298d6dcc5711195ea9acec450bd"
MODEL_ID = selected_model_id()
PROFILE_SCHEMA = "aga.ouroboros-profile/v1"
PID_SCHEMA = "aga.ouroboros-profile-pid/v1"
OVERLAY_ATTESTATION_SCHEMA = "aga.ouroboros-runtime-overlay/v4"
DEFAULT_GATEWAY_PORT = 8765
DEFAULT_PROFILE_RELATIVE = Path(".local/share/aga-ouroboros-v6.64.1/home")
SKILL_SOURCE = REPOSITORY_ROOT / "ouroboros-skill" / "aga-review-v1.1"
RUNTIME_OVERLAY_SCRIPT = REPOSITORY_ROOT / "scripts" / "ouroboros_runtime_overlay.py"
RUNTIME_OVERLAY_BOOTSTRAP = (
    REPOSITORY_ROOT / "scripts" / "ouroboros_overlay_bootstrap" / "sitecustomize.py"
)
OVERLAY_ATTESTATION_FILENAME = "aga-runtime-overlay.json"
OVERLAY_GUARD_ENV = "AGA_OUROBOROS_RUNTIME_OVERLAY"
OVERLAY_SOURCE_ENV = "AGA_OUROBOROS_PINNED_SOURCE_DIR"
SKILL_NAME = "aga_review"
MCP_TOOL_NAMES = (
    "aga_prepare_review",
    "aga_seaf_lookup",
    "aga_parse_diagram",
    "aga_finalize_review",
    "aga_prepare_remediation",
    "aga_finalize_remediation",
)
MANAGED_TASK_SCHEMA = "aga.ouroboros-managed-task/v1"
MCP_REFRESH_TIMEOUT_SECONDS = 20
WORKER_PYTHON_ENV = "AGA_OUROBOROS_WORKER_PYTHON"
SECRET_PATTERN = re.compile(
    r"sk-or-v1-[A-Za-z0-9_-]{20,}"
)
KEY_PATTERN = re.compile(r"sk-or-v1-[A-Za-z0-9_-]{20,4096}")


class ProfileError(RuntimeError):
    """A typed, secret-free operator error."""

    def __init__(self, code: str, *, status: str = "failed") -> None:
        if status not in {"failed", "not_configured"}:
            raise ValueError("invalid profile error status")
        self.code = code
        self.status = status
        super().__init__(code)


def _home_from_environment(environment: Mapping[str, str]) -> Path:
    raw = str(environment.get("HOME") or "").strip()
    return Path(raw) if raw else Path.home()


def _expand_path(raw: str, *, home: Path) -> Path:
    text = str(raw).strip()
    if text == "~":
        return home
    if text.startswith("~/") or text.startswith("~\\"):
        return home / text[2:]
    return Path(text)


def _absolute_path_preserving_symlinks(path: Path) -> Path:
    """Normalize dot segments without resolving a venv interpreter symlink."""

    return Path(os.path.abspath(os.fspath(path)))


@dataclass(frozen=True)
class ProfilePaths:
    profile_home: Path
    profile_root: Path
    data_dir: Path
    settings_path: Path
    skill_dir: Path
    venv_dir: Path
    source_dir: Path
    executable: Path
    python_executable: Path
    runtime_tmp: Path
    runtime_log: Path
    pid_path: Path
    overlay_attestation_path: Path

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "ProfilePaths":
        env = os.environ if environment is None else environment
        owner_home = _home_from_environment(env)
        default_home = owner_home / DEFAULT_PROFILE_RELATIVE
        profile_home = _expand_path(
            env.get("AGA_OUROBOROS_PROFILE_HOME", str(default_home)),
            home=owner_home,
        ).resolve(strict=False)
        profile_root = profile_home.parent
        venv_dir = _expand_path(
            env.get("AGA_OUROBOROS_VENV_DIR", str(profile_root / "venv")),
            home=owner_home,
        ).resolve(strict=False)
        source_dir = _expand_path(
            env.get("AGA_OUROBOROS_SOURCE_DIR", str(profile_root / "source")),
            home=owner_home,
        ).resolve(strict=False)
        executable_name = "ouroboros.exe" if os.name == "nt" else "ouroboros"
        python_name = "python.exe" if os.name == "nt" else "python"
        scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
        executable = _absolute_path_preserving_symlinks(
            _expand_path(
                env.get("AGA_OUROBOROS_BIN", str(scripts_dir / executable_name)),
                home=owner_home,
            )
        )
        python_executable = _absolute_path_preserving_symlinks(
            _expand_path(
                env.get("AGA_OUROBOROS_PYTHON", str(scripts_dir / python_name)),
                home=owner_home,
            )
        )
        data_dir = profile_home / "Ouroboros" / "data"
        state_dir = data_dir / "state"
        return cls(
            profile_home=profile_home,
            profile_root=profile_root,
            data_dir=data_dir,
            settings_path=data_dir / "settings.json",
            skill_dir=data_dir / "skills" / "external" / SKILL_NAME,
            venv_dir=venv_dir,
            source_dir=source_dir,
            executable=executable,
            python_executable=python_executable,
            runtime_tmp=profile_root / "tmp",
            runtime_log=data_dir / "logs" / "profile-server.log",
            pid_path=state_dir / "aga-profile-runtime.json",
            overlay_attestation_path=state_dir / OVERLAY_ATTESTATION_FILENAME,
        )


def _ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ProfileError("unsafe_profile_symlink")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.is_dir() or path.is_symlink():
            raise ProfileError("unsafe_profile_directory")
        path.chmod(0o700)
    except OSError as exc:
        raise ProfileError("profile_directory_unavailable") from exc


def _ensure_profile_directories(paths: ProfilePaths) -> None:
    for path in (
        paths.profile_root,
        paths.profile_home,
        paths.profile_home / "Ouroboros",
        paths.data_dir,
        paths.data_dir / "logs",
        paths.data_dir / "state",
        paths.data_dir / "skills",
        paths.data_dir / "skills" / "external",
        paths.runtime_tmp,
        paths.profile_home / ".cache",
        paths.profile_home / ".config",
        paths.profile_home / ".local" / "share",
    ):
        _ensure_private_directory(path)


def _load_json_object(path: Path, *, missing_ok: bool = True) -> dict[str, Any]:
    if not path.exists():
        if missing_ok:
            return {}
        raise ProfileError("profile_file_missing", status="not_configured")
    if path.is_symlink() or not path.is_file():
        raise ProfileError("unsafe_profile_file")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError("profile_file_invalid") from exc
    if not isinstance(raw, dict):
        raise ProfileError("profile_file_invalid")
    return raw


def _atomic_write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    _ensure_private_directory(path.parent)
    temporary: Path | None = None
    descriptor = -1
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.tmp.", dir=str(path.parent)
        )
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(
                dict(value),
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        path.chmod(0o600)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = -1
        if directory_fd >= 0:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except (OSError, TypeError, ValueError) as exc:
        raise ProfileError("profile_write_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _mcp_server_settings() -> list[dict[str, Any]]:
    return [
        {
            "id": "aga",
            "name": "AGA Governance",
            "enabled": True,
            "transport": "streamable_http",
            "url": "http://127.0.0.1:8788/mcp",
            "auth_header": "Authorization",
            "auth_token": "",
            "allowed_tools": list(MCP_TOOL_NAMES),
        }
    ]


def _managed_settings() -> dict[str, Any]:
    """Return the public, reproducible part of the dedicated profile."""

    return {
        "OPENAI_API_KEY": "",
        "OPENAI_COMPATIBLE_API_KEY": "",
        "CLOUDRU_FOUNDATION_MODELS_API_KEY": "",
        "GIGACHAT_CREDENTIALS": "",
        "GIGACHAT_USER": "",
        "GIGACHAT_PASSWORD": "",
        "ANTHROPIC_API_KEY": "",
        "GITHUB_TOKEN": "",
        "OUROBOROS_SERVER_HOST": "127.0.0.1",
        "OUROBOROS_MODEL": MODEL_ID,
        "OUROBOROS_MODEL_HEAVY": MODEL_ID,
        "OUROBOROS_MODEL_LIGHT": MODEL_ID,
        "OUROBOROS_MODEL_VISION": MODEL_ID,
        "OUROBOROS_MODEL_CONSCIOUSNESS": MODEL_ID,
        "OUROBOROS_MODEL_FALLBACKS": "",
        "OUROBOROS_MODEL_DEEP_SELF_REVIEW": MODEL_ID,
        "OUROBOROS_WEBSEARCH_MODEL": MODEL_ID,
        "OUROBOROS_WEBSEARCH_BACKEND": "ddgs",
        "OUROBOROS_SCOPE_REVIEW_MODEL": MODEL_ID,
        "OUROBOROS_REVIEW_MODELS": MODEL_ID,
        "OUROBOROS_SCOPE_REVIEW_MODELS": MODEL_ID,
        "USE_LOCAL_MAIN": False,
        "USE_LOCAL_HEAVY": False,
        "USE_LOCAL_LIGHT": False,
        "USE_LOCAL_CONSCIOUSNESS": False,
        "USE_LOCAL_FALLBACK": False,
        "TOTAL_BUDGET": 50.0,
        "OUROBOROS_PER_TASK_COST_USD": 50.0,
        "OUROBOROS_REVIEW_ENFORCEMENT": "advisory",
        "OUROBOROS_TASK_REVIEW_MODE": "off",
        "OUROBOROS_SAFETY_MODE": "full",
        "OUROBOROS_OR_PROVIDER": "repro",
        "OUROBOROS_GENERATIVE_PROBE": 0,
        "OUROBOROS_MAIN_WEB_SEARCH": False,
        "OUROBOROS_POST_TASK_EVOLUTION": False,
        "OUROBOROS_EVOLUTION_PERSISTENT_OBJECTIVE": "",
        "OUROBOROS_MAX_WORKERS": 1,
        "OUROBOROS_MODEL_MAX_CONCURRENCY": 1,
        "MCP_ENABLED": True,
        "MCP_TOOL_TIMEOUT_SEC": MCP_REFRESH_TIMEOUT_SECONDS,
        "MCP_SERVERS": _mcp_server_settings(),
    }


def configure_public_settings(paths: ProfilePaths) -> bool:
    """Merge pinned public settings while preserving the credential and state."""

    _ensure_profile_directories(paths)
    existing = _load_json_object(paths.settings_path)
    credential = existing.get("OPENROUTER_API_KEY", "")
    if not isinstance(credential, str):
        raise ProfileError("credential_field_invalid")
    merged = dict(existing)
    merged.update(_managed_settings())
    merged["OPENROUTER_API_KEY"] = credential
    _atomic_write_private_json(paths.settings_path, merged)
    return bool(credential.strip())


def _make_tree_private(root: Path) -> None:
    for directory, names, files in os.walk(root):
        current = Path(directory)
        current.chmod(0o700)
        for name in names:
            candidate = current / name
            if candidate.is_symlink():
                raise ProfileError("unsafe_skill_symlink")
        for name in files:
            candidate = current / name
            if candidate.is_symlink() or not candidate.is_file():
                raise ProfileError("unsafe_skill_file")
            candidate.chmod(0o600)


def sync_skill(paths: ProfilePaths, *, source: Path = SKILL_SOURCE) -> str:
    """Atomically replace the external AGA instruction skill with repo bytes."""

    _ensure_profile_directories(paths)
    source = source.resolve(strict=False)
    if (
        not source.is_dir()
        or source.is_symlink()
        or not (source / "SKILL.md").is_file()
    ):
        raise ProfileError("skill_source_unavailable")
    parent = paths.skill_dir.parent
    try:
        paths.skill_dir.resolve(strict=False).relative_to(parent.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ProfileError("unsafe_skill_destination") from exc
    nonce = uuid.uuid4().hex
    staging = parent / f".{SKILL_NAME}.staging.{nonce}"
    backup = parent / f".{SKILL_NAME}.backup.{nonce}"
    moved_existing = False
    try:
        shutil.copytree(source, staging, symlinks=False)
        _make_tree_private(staging)
        if paths.skill_dir.exists() or paths.skill_dir.is_symlink():
            if paths.skill_dir.is_symlink() or not paths.skill_dir.is_dir():
                raise ProfileError("unsafe_skill_destination")
            os.replace(paths.skill_dir, backup)
            moved_existing = True
        os.replace(staging, paths.skill_dir)
        if moved_existing:
            shutil.rmtree(backup)
    except ProfileError:
        if moved_existing and not paths.skill_dir.exists() and backup.exists():
            os.replace(backup, paths.skill_dir)
        raise
    except OSError as exc:
        if moved_existing and not paths.skill_dir.exists() and backup.exists():
            os.replace(backup, paths.skill_dir)
        raise ProfileError("skill_sync_failed") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and paths.skill_dir.exists():
            shutil.rmtree(backup, ignore_errors=True)
    skill_bytes = (paths.skill_dir / "SKILL.md").read_bytes()
    return hashlib.sha256(skill_bytes).hexdigest()


def initialize_profile(paths: ProfilePaths) -> Mapping[str, Any]:
    credential_present = configure_public_settings(paths)
    skill_hash = sync_skill(paths)
    return {
        "schema": PROFILE_SCHEMA,
        "status": "initialized",
        "credential_present": credential_present,
        "skill": {"name": SKILL_NAME, "synced": True, "sha256": skill_hash},
        "permissions": {"profile": "0700", "settings": "0600"},
    }


def synchronize_profile(paths: ProfilePaths) -> Mapping[str, Any]:
    """Refresh managed settings and skill bytes without replacing the key."""

    credential_present = configure_public_settings(paths)
    skill_hash = sync_skill(paths)
    return {
        "schema": PROFILE_SCHEMA,
        "status": "synced",
        "credential_present": credential_present,
        "skill": {"name": SKILL_NAME, "sha256": skill_hash},
    }


def _default_key_reader() -> str:
    return getpass.getpass("OpenRouter API key (input hidden): ")


def configure_key(
    paths: ProfilePaths,
    *,
    key_reader: Callable[[], str] = _default_key_reader,
) -> Mapping[str, Any]:
    """Read a credential from the controlling terminal and persist it privately."""

    configure_public_settings(paths)
    try:
        credential = key_reader()
    except (EOFError, KeyboardInterrupt) as exc:
        raise ProfileError("credential_input_cancelled", status="not_configured") from exc
    if not isinstance(credential, str) or KEY_PATTERN.fullmatch(credential) is None:
        raise ProfileError("credential_format_invalid", status="not_configured")
    settings = _load_json_object(paths.settings_path, missing_ok=False)
    settings["OPENROUTER_API_KEY"] = credential
    _atomic_write_private_json(paths.settings_path, settings)
    credential = ""  # best-effort release of the caller-owned reference
    return {
        "schema": PROFILE_SCHEMA,
        "status": "configured",
        "credential_present": True,
    }


def runtime_environment(
    paths: ProfilePaths,
    parent: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the credential-free environment inherited by project commands."""

    source = os.environ if parent is None else parent
    environment: dict[str, str] = {}
    for key in (
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "SYSTEMROOT",
        "WINDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    ):
        value = source.get(key)
        if value:
            environment[key] = value
    bin_dir = paths.executable.parent
    environment.update(
        {
            "HOME": str(paths.profile_home),
            "PATH": os.pathsep.join((str(bin_dir), os.defpath)),
            "TMPDIR": str(paths.runtime_tmp),
            "XDG_CACHE_HOME": str(paths.profile_home / ".cache"),
            "XDG_CONFIG_HOME": str(paths.profile_home / ".config"),
            "XDG_DATA_HOME": str(paths.profile_home / ".local" / "share"),
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
            "PYTHONUNBUFFERED": "1",
            "AGA_OUROBOROS_PROFILE_HOME": str(paths.profile_home),
            "AGA_OUROBOROS_VENV_DIR": str(paths.venv_dir),
            "AGA_OUROBOROS_SOURCE_DIR": str(paths.source_dir),
            "AGA_OUROBOROS_BIN": str(paths.executable),
            "AGA_OUROBOROS_PYTHON": str(paths.python_executable),
            WORKER_PYTHON_ENV: str(paths.python_executable),
            OVERLAY_SOURCE_ENV: str(paths.source_dir),
            MODEL_ENV: MODEL_ID,
        }
    )
    return environment


def _bounded_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout: float = 20.0,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfileError("runtime_verification_failed", status="not_configured") from exc


def verify_runtime(paths: ProfilePaths) -> None:
    if (
        not paths.executable.is_file()
        or not os.access(paths.executable, os.X_OK)
        or not paths.python_executable.is_file()
        or not paths.source_dir.is_dir()
        or not (paths.source_dir / "server.py").is_file()
        or not (paths.source_dir / "ouroboros").is_dir()
        or not (paths.source_dir / ".git").exists()
        or not RUNTIME_OVERLAY_SCRIPT.is_file()
        or not RUNTIME_OVERLAY_BOOTSTRAP.is_file()
    ):
        raise ProfileError("runtime_not_installed", status="not_configured")
    environment = runtime_environment(paths)
    version = _bounded_command(
        (
            str(paths.python_executable),
            "-c",
            "import importlib.metadata as m; print(m.version('ouroboros'))",
        ),
        cwd=paths.source_dir,
        environment=environment,
    )
    if version.returncode != 0 or version.stdout.strip() != PINNED_VERSION:
        raise ProfileError("runtime_version_mismatch", status="not_configured")
    commit = _bounded_command(
        ("git", "-C", str(paths.source_dir), "rev-parse", "HEAD"),
        cwd=paths.source_dir,
        environment=environment,
    )
    if commit.returncode != 0 or commit.stdout.strip() != PINNED_SOURCE_COMMIT:
        raise ProfileError("runtime_source_mismatch", status="not_configured")
    dirty = _bounded_command(
        ("git", "-C", str(paths.source_dir), "status", "--porcelain"),
        cwd=paths.source_dir,
        environment=environment,
    )
    if dirty.returncode != 0 or dirty.stdout.strip():
        raise ProfileError("runtime_source_dirty", status="not_configured")


def _read_pid(paths: ProfilePaths) -> int | None:
    if not paths.pid_path.exists():
        return None
    record = _load_json_object(paths.pid_path, missing_ok=False)
    pid = record.get("pid")
    if (
        record.get("schema") != PID_SCHEMA
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 1
        or record.get("executable") != str(paths.executable)
    ):
        raise ProfileError("runtime_pid_invalid")
    return pid


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_command(pid: int) -> str:
    if os.name != "posix":
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
    return result.stdout.strip() if result.returncode == 0 else ""


def _owned_runtime_process(paths: ProfilePaths, pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    command = _process_command(pid)
    if not command:
        return False
    overlay_command = (
        str(RUNTIME_OVERLAY_SCRIPT) in command
        and str(paths.source_dir) in command
        and "--source-dir" in command
        and "server" in command
    )
    return overlay_command


def _remove_overlay_attestation(paths: ProfilePaths) -> None:
    path = paths.overlay_attestation_path
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ProfileError("unsafe_runtime_overlay_attestation")
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise ProfileError("runtime_overlay_cleanup_failed") from exc


def _validate_overlay_attestation(paths: ProfilePaths, pid: int) -> None:
    path = paths.overlay_attestation_path
    if not path.exists():
        raise ProfileError("runtime_overlay_not_active", status="not_configured")
    if path.is_symlink() or not path.is_file():
        raise ProfileError("unsafe_runtime_overlay_attestation")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600 or path.stat().st_size > 16 * 1024:
            raise ProfileError("runtime_overlay_attestation_invalid")
        record = _load_json_object(path, missing_ok=False)
        launcher_sha256 = hashlib.sha256(RUNTIME_OVERLAY_SCRIPT.read_bytes()).hexdigest()
        bootstrap_sha256 = hashlib.sha256(
            RUNTIME_OVERLAY_BOOTSTRAP.read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise ProfileError("runtime_overlay_attestation_invalid") from exc
    expected = {
        "schema": OVERLAY_ATTESTATION_SCHEMA,
        "pid": pid,
        "runtime_version": PINNED_VERSION,
        "source_commit": PINNED_SOURCE_COMMIT,
        "source_clean": True,
        "model": MODEL_ID,
        "consolidation_model": MODEL_ID,
        "launcher_sha256": launcher_sha256,
        "spawn_bootstrap": True,
        "bootstrap_mode": "deferred_runtime_import_hooks",
        "bootstrap_sha256": bootstrap_sha256,
        "finalize_transport_retry": "exception_group_once",
        "worker_discovery_contract": "synchronous_exact_stage_fail_closed",
        "managed_task_schema": MANAGED_TASK_SCHEMA,
        "mcp_refresh_timeout_seconds": MCP_REFRESH_TIMEOUT_SECONDS,
        "gateway_mcp_tool_count": len(MCP_TOOL_NAMES),
        "aga_post_task_policy": "skip_synthetic_public_memory_synthesis",
    }
    if record != expected or not _owned_runtime_process(paths, pid):
        raise ProfileError("runtime_overlay_attestation_invalid")


def _gateway_port(paths: ProfilePaths) -> int:
    port_file = paths.data_dir / "state" / "server_port"
    try:
        value = int(port_file.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError, ValueError):
        return DEFAULT_GATEWAY_PORT
    return value if 1 <= value <= 65535 else DEFAULT_GATEWAY_PORT


def _http_json(url: str, *, timeout: float = 2.0) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(1_048_577).decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProfileError("runtime_unavailable", status="not_configured") from exc
    if not isinstance(payload, Mapping):
        raise ProfileError("runtime_contract_mismatch")
    return payload


def gateway_status(paths: ProfilePaths) -> Mapping[str, Any]:
    port = _gateway_port(paths)
    base = f"http://127.0.0.1:{port}"
    health = _http_json(f"{base}/api/health")
    state_payload = _http_json(f"{base}/api/state")
    versions = (
        health.get("version"),
        health.get("runtime_version"),
        health.get("app_version"),
    )
    if health.get("status") != "ok" or any(
        value != PINNED_VERSION for value in versions
    ):
        raise ProfileError("runtime_version_mismatch")
    if state_payload.get("supervisor_ready") is not True:
        raise ProfileError("runtime_not_ready", status="not_configured")
    return {"version": PINNED_VERSION, "supervisor_ready": True, "port": port}


def _wait_ready(
    paths: ProfilePaths,
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ProfileError("runtime_exited_during_start", status="not_configured")
        try:
            return gateway_status(paths)
        except ProfileError:
            time.sleep(0.25)
    raise ProfileError("runtime_start_timeout", status="not_configured")


def _redact_log_if_needed(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if SECRET_PATTERN.search(text) is None:
        return False
    sanitized = SECRET_PATTERN.sub("[REDACTED_OPENROUTER_KEY]", text)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.redact.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(sanitized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _terminate_process(paths: ProfilePaths, pid: int, *, timeout: float = 20.0) -> None:
    if not _owned_runtime_process(paths, pid):
        if _pid_alive(pid):
            raise ProfileError("runtime_pid_identity_mismatch")
        paths.pid_path.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        paths.pid_path.unlink(missing_ok=True)
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            paths.pid_path.unlink(missing_ok=True)
            return
        time.sleep(0.1)
    try:
        if os.name == "posix" and os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    paths.pid_path.unlink(missing_ok=True)


def start_runtime(paths: ProfilePaths, *, ready_timeout: float = 90.0) -> Mapping[str, Any]:
    _ensure_profile_directories(paths)
    verify_runtime(paths)
    settings = _load_json_object(paths.settings_path, missing_ok=False)
    credential = settings.get("OPENROUTER_API_KEY")
    if not isinstance(credential, str) or KEY_PATTERN.fullmatch(credential) is None:
        raise ProfileError("openrouter_not_configured", status="not_configured")
    if not (paths.skill_dir / "SKILL.md").is_file():
        raise ProfileError("aga_skill_not_synced", status="not_configured")
    existing_pid = _read_pid(paths)
    if existing_pid is not None:
        if _owned_runtime_process(paths, existing_pid):
            status = gateway_status(paths)
            _validate_overlay_attestation(paths, existing_pid)
            return {
                "schema": PROFILE_SCHEMA,
                "status": "already_running",
                "pid": existing_pid,
                "runtime": status,
                "runtime_overlay": {
                    "active": True,
                    "model": MODEL_ID,
                    "source_commit": PINNED_SOURCE_COMMIT,
                },
            }
        if _pid_alive(existing_pid):
            raise ProfileError("runtime_pid_identity_mismatch")
        paths.pid_path.unlink(missing_ok=True)
    _remove_overlay_attestation(paths)

    log_fd = os.open(
        paths.runtime_log,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    os.fchmod(log_fd, 0o600)
    command = (
        str(paths.python_executable),
        str(RUNTIME_OVERLAY_SCRIPT),
        "--source-dir",
        str(paths.source_dir),
        "--",
        "server",
        "--host",
        "127.0.0.1",
        "--port",
        str(DEFAULT_GATEWAY_PORT),
        "--no-ui",
    )
    environment = runtime_environment(paths)
    # The v6.64.1 wheel omits repository-owned review assets such as
    # ``docs/CHECKLISTS.md`` even though the skill-review runtime loads them.
    # Run the executable against the separately verified, clean source checkout
    # so the packaged CLI surface and its required assets resolve together.
    # This is a fixed local path, not caller-controlled Python import state.
    environment["PYTHONPATH"] = os.pathsep.join(
        (
            str(RUNTIME_OVERLAY_BOOTSTRAP.parent),
            str(RUNTIME_OVERLAY_SCRIPT.parent),
            str(paths.source_dir),
        )
    )
    environment[OVERLAY_GUARD_ENV] = OVERLAY_ATTESTATION_SCHEMA
    environment[OVERLAY_SOURCE_ENV] = str(paths.source_dir)
    environment["PIP_NO_INDEX"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPYCACHEPREFIX"] = str(
        paths.data_dir / "state" / "pycache"
    )
    try:
        process = subprocess.Popen(
            list(command),
            cwd=str(paths.source_dir),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=log_fd,
            shell=False,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        raise ProfileError("runtime_start_failed", status="not_configured") from exc
    finally:
        os.close(log_fd)
    _atomic_write_private_json(
        paths.pid_path,
        {
            "schema": PID_SCHEMA,
            "pid": process.pid,
            "executable": str(paths.executable),
            "started_at_unix": int(time.time()),
        },
    )
    try:
        status = _wait_ready(paths, process, timeout=ready_timeout)
        _validate_overlay_attestation(paths, process.pid)
        paths.settings_path.chmod(0o600)
        paths.runtime_log.chmod(0o600)
        if _redact_log_if_needed(paths.runtime_log):
            _terminate_process(paths, process.pid)
            raise ProfileError("runtime_log_secret_redacted")
    except Exception:
        try:
            _terminate_process(paths, process.pid)
        except ProfileError:
            pass
        try:
            _remove_overlay_attestation(paths)
        except ProfileError:
            pass
        _redact_log_if_needed(paths.runtime_log)
        raise
    return {
        "schema": PROFILE_SCHEMA,
        "status": "started",
        "pid": process.pid,
        "runtime": status,
        "runtime_overlay": {
            "active": True,
            "model": MODEL_ID,
            "source_commit": PINNED_SOURCE_COMMIT,
        },
    }


def stop_runtime(paths: ProfilePaths) -> Mapping[str, Any]:
    pid = _read_pid(paths)
    if pid is None:
        _remove_overlay_attestation(paths)
        redacted = _redact_log_if_needed(paths.runtime_log)
        return {
            "schema": PROFILE_SCHEMA,
            "status": "stopped",
            "already": True,
            "runtime_log_redacted": redacted,
        }
    _terminate_process(paths, pid)
    _remove_overlay_attestation(paths)
    redacted = _redact_log_if_needed(paths.runtime_log)
    return {
        "schema": PROFILE_SCHEMA,
        "status": "stopped",
        "already": False,
        "runtime_log_redacted": redacted,
    }


def profile_status(paths: ProfilePaths) -> Mapping[str, Any]:
    settings = _load_json_object(paths.settings_path) if paths.settings_path.exists() else {}
    credential_present = isinstance(settings.get("OPENROUTER_API_KEY"), str) and bool(
        str(settings.get("OPENROUTER_API_KEY")).strip()
    )
    pid: int | None
    try:
        pid = _read_pid(paths)
    except ProfileError:
        pid = None
    running = pid is not None and _owned_runtime_process(paths, pid)
    overlay_active = False
    if running and pid is not None:
        try:
            _validate_overlay_attestation(paths, pid)
            overlay_active = True
        except ProfileError:
            overlay_active = False
    runtime: Mapping[str, Any] | None = None
    if running:
        try:
            runtime = gateway_status(paths)
        except ProfileError:
            runtime = {"version": PINNED_VERSION, "supervisor_ready": False}
    settings_mode = None
    if paths.settings_path.is_file():
        settings_mode = stat.S_IMODE(paths.settings_path.stat().st_mode)
    runtime_log_redacted = _redact_log_if_needed(paths.runtime_log)
    return {
        "schema": PROFILE_SCHEMA,
        "status": "running" if running else "stopped",
        "credential_present": credential_present,
        "settings_private": settings_mode == 0o600,
        "skill_synced": (paths.skill_dir / "SKILL.md").is_file(),
        "runtime_installed": paths.executable.is_file() and paths.source_dir.is_dir(),
        "runtime_log_redacted": runtime_log_redacted,
        "runtime_overlay_active": overlay_active,
        "runtime": runtime,
    }


def run_preflight(paths: ProfilePaths) -> tuple[Mapping[str, Any], int]:
    """Run the read-only preflight with an ephemeral synthetic AGA MCP server."""

    verify_runtime(paths)
    gateway_status(paths)
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    try:
        from scripts import run_ouroboros_e2e as e2e
    except Exception as exc:
        raise ProfileError("preflight_dependencies_unavailable", status="not_configured") from exc
    dependencies = e2e._Dependencies()
    record, workspace, _corpus_hash = e2e._case_metadata(
        e2e.DEFAULT_CASE_ID,
        dependencies=dependencies,
    )
    try:
        server = e2e._default_server_factory(str(record["repository_id"]), workspace)
        with server:
            result = subprocess.run(
                (
                    sys.executable,
                    str(REPOSITORY_ROOT / "scripts" / "ouroboros_preflight.py"),
                    "--ouroboros-bin",
                    str(paths.executable),
                ),
                cwd=str(REPOSITORY_ROOT),
                env=runtime_environment(paths),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180.0,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise ProfileError("preflight_timeout") from exc
    except OSError as exc:
        raise ProfileError("preflight_failed") from exc
    try:
        payload = json.loads(result.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError("preflight_output_invalid") from exc
    if not isinstance(payload, Mapping) or SECRET_PATTERN.search(result.stdout):
        raise ProfileError("preflight_output_invalid")
    return dict(payload), int(result.returncode)


def exec_in_profile(paths: ProfilePaths, command: Sequence[str]) -> None:
    if not command:
        raise ProfileError("profile_command_missing")
    _ensure_profile_directories(paths)
    environment = runtime_environment(paths)
    try:
        os.execvpe(command[0], list(command), environment)
    except OSError as exc:
        raise ProfileError("profile_command_unavailable", status="not_configured") from exc


def _emit(payload: Mapping[str, Any]) -> None:
    print(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "sync", "configure-key", "start", "stop", "status", "preflight"):
        subparsers.add_parser(name)
    execute = subparsers.add_parser("exec", help="run a project command in the profile")
    execute.add_argument("profile_command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)
    arguments = build_parser().parse_args(argv)
    paths = ProfilePaths.from_environment()
    try:
        if arguments.command == "init":
            _emit(initialize_profile(paths))
        elif arguments.command == "sync":
            _emit(synchronize_profile(paths))
        elif arguments.command == "configure-key":
            _emit(configure_key(paths))
        elif arguments.command == "start":
            _emit(start_runtime(paths))
        elif arguments.command == "stop":
            _emit(stop_runtime(paths))
        elif arguments.command == "status":
            _emit(profile_status(paths))
        elif arguments.command == "preflight":
            payload, exit_code = run_preflight(paths)
            _emit(payload)
            return exit_code
        elif arguments.command == "exec":
            command = list(arguments.profile_command)
            if command and command[0] == "--":
                command.pop(0)
            exec_in_profile(paths, command)
            raise AssertionError("unreachable")
        else:  # pragma: no cover - argparse enforces the command set
            raise ProfileError("unknown_profile_command")
        return 0
    except ProfileError as exc:
        _emit({"schema": PROFILE_SCHEMA, "status": exc.status, "code": exc.code})
        return 2 if exc.status == "not_configured" else 3
    except Exception:
        _emit({"schema": PROFILE_SCHEMA, "status": "failed", "code": "internal_profile_error"})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
