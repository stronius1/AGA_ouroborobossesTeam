# -*- coding: utf-8 -*-
"""Offline contracts for the persistent, isolated Ouroboros profile."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import ouroboros_profile as profile  # noqa: E402


def _paths(tmp_path: Path) -> profile.ProfilePaths:
    owner = tmp_path / "owner"
    return profile.ProfilePaths.from_environment(
        {
            "HOME": str(owner),
            "AGA_OUROBOROS_PROFILE_HOME": str(tmp_path / "profile" / "home"),
            "AGA_OUROBOROS_VENV_DIR": str(tmp_path / "runtime" / "venv"),
            "AGA_OUROBOROS_SOURCE_DIR": str(tmp_path / "runtime" / "source"),
        }
    )


def _synthetic_key(character: str = "a") -> str:
    # Keep credential-like literals out of project-owned source bytes.
    return "sk-or-" + "v1-" + character * 32


def test_default_profile_is_a_dedicated_home_outside_the_project(tmp_path: Path) -> None:
    paths = profile.ProfilePaths.from_environment({"HOME": str(tmp_path)})

    assert paths.profile_home == (
        tmp_path / ".local/share/aga-ouroboros-v6.64.1/home"
    ).resolve()
    assert paths.settings_path == paths.profile_home / "Ouroboros/data/settings.json"
    assert paths.venv_dir == paths.profile_home.parent / "venv"
    assert paths.source_dir == paths.profile_home.parent / "source"


def test_profile_preserves_the_venv_python_symlink_path(tmp_path: Path) -> None:
    venv_dir = tmp_path / "runtime" / "venv"
    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    scripts_dir.mkdir(parents=True)
    target = tmp_path / "base-python"
    target.write_text("synthetic executable", encoding="utf-8")
    python_name = "python.exe" if os.name == "nt" else "python"
    interpreter = scripts_dir / python_name
    try:
        interpreter.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")

    paths = profile.ProfilePaths.from_environment(
        {
            "HOME": str(tmp_path / "owner"),
            "AGA_OUROBOROS_PROFILE_HOME": str(tmp_path / "profile" / "home"),
            "AGA_OUROBOROS_VENV_DIR": str(venv_dir),
            "AGA_OUROBOROS_SOURCE_DIR": str(tmp_path / "runtime" / "source"),
        }
    )

    assert paths.python_executable == interpreter.absolute()
    assert paths.python_executable != target.resolve()


def test_initialize_writes_private_public_config_and_syncs_skill(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    result = profile.initialize_profile(paths)
    settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))

    assert result["status"] == "initialized"
    assert result["credential_present"] is False
    assert settings["OPENROUTER_API_KEY"] == ""
    assert settings["OUROBOROS_MODEL"] == profile.MODEL_ID
    assert settings["TOTAL_BUDGET"] == 50.0
    assert settings["OUROBOROS_OR_PROVIDER"] == "repro"
    assert settings["OUROBOROS_GENERATIVE_PROBE"] == 0
    assert settings["OUROBOROS_WEBSEARCH_BACKEND"] == "ddgs"
    assert settings["OUROBOROS_POST_TASK_EVOLUTION"] is False
    assert settings["MCP_SERVERS"] == profile._mcp_server_settings()
    assert (paths.skill_dir / "SKILL.md").read_bytes() == (
        profile.SKILL_SOURCE / "SKILL.md"
    ).read_bytes()
    assert stat.S_IMODE(paths.profile_home.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.settings_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((paths.skill_dir / "SKILL.md").stat().st_mode) == 0o600


def test_reinitialize_preserves_only_the_openrouter_credential_and_unknown_state(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    profile._ensure_profile_directories(paths)
    credential = _synthetic_key()
    profile._atomic_write_private_json(
        paths.settings_path,
        {
            "OPENROUTER_API_KEY": credential,
            "OPENAI_API_KEY": "must-be-cleared",
            "OWNER_LOCAL_NOTE": "preserved",
        },
    )

    result = profile.initialize_profile(paths)
    settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))

    assert result["credential_present"] is True
    assert settings["OPENROUTER_API_KEY"] == credential
    assert settings["OPENAI_API_KEY"] == ""
    assert settings["OWNER_LOCAL_NOTE"] == "preserved"


def test_configure_key_uses_injected_hidden_reader_and_never_returns_secret(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    credential = _synthetic_key("b")
    calls = 0

    def reader() -> str:
        nonlocal calls
        calls += 1
        return credential

    result = profile.configure_key(paths, key_reader=reader)
    settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))

    assert calls == 1
    assert result == {
        "schema": profile.PROFILE_SCHEMA,
        "status": "configured",
        "credential_present": True,
    }
    assert credential not in json.dumps(result)
    assert settings["OPENROUTER_API_KEY"] == credential
    assert stat.S_IMODE(paths.settings_path.stat().st_mode) == 0o600


def test_invalid_interactive_key_does_not_replace_existing_key(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    original = _synthetic_key("c")
    profile.configure_key(paths, key_reader=lambda: original)

    with pytest.raises(profile.ProfileError) as caught:
        profile.configure_key(paths, key_reader=lambda: "invalid")

    settings = json.loads(paths.settings_path.read_text(encoding="utf-8"))
    assert caught.value.code == "credential_format_invalid"
    assert settings["OPENROUTER_API_KEY"] == original


def test_configure_key_parser_has_no_credential_argument() -> None:
    with pytest.raises(SystemExit):
        profile.build_parser().parse_args(["configure-key", _synthetic_key("d")])


def test_runtime_environment_is_allowlisted_and_contains_no_provider_secret(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    credential = _synthetic_key("e")
    environment = profile.runtime_environment(
        paths,
        {
            "HOME": "/real-owner-home",
            "PATH": "/untrusted/bin",
            "OPENROUTER_API_KEY": credential,
            "HTTPS_PROXY": "http://proxy-with-credentials.invalid",
            "LANG": "en_US.UTF-8",
        },
    )

    assert environment["HOME"] == str(paths.profile_home)
    assert environment["PATH"].split(os.pathsep)[0] == str(paths.executable.parent)
    assert environment["LANG"] == "en_US.UTF-8"
    assert "OPENROUTER_API_KEY" not in environment
    assert "HTTPS_PROXY" not in environment
    assert credential not in json.dumps(environment)


def test_sync_atomically_removes_stale_payload_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    profile.sync_skill(paths)
    stale = paths.skill_dir / "stale.txt"
    stale.write_text("stale", encoding="utf-8")

    digest = profile.sync_skill(paths)

    assert len(digest) == 64
    assert not stale.exists()
    assert (paths.skill_dir / "prompts/orchestration-v1.0.0.txt").is_file()


def test_verify_runtime_requires_exact_installed_version_and_source_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    paths.executable.parent.mkdir(parents=True)
    paths.executable.write_text("#!/bin/sh\n", encoding="utf-8")
    paths.executable.chmod(0o700)
    paths.python_executable.write_text("#!/bin/sh\n", encoding="utf-8")
    paths.python_executable.chmod(0o700)
    (paths.source_dir / ".git").mkdir(parents=True)
    (paths.source_dir / "ouroboros").mkdir()
    (paths.source_dir / "server.py").write_text("", encoding="utf-8")
    results = iter(
        (
            subprocess.CompletedProcess([], 0, profile.PINNED_VERSION + "\n", ""),
            subprocess.CompletedProcess([], 0, profile.PINNED_SOURCE_COMMIT + "\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        )
    )
    monkeypatch.setattr(profile, "_bounded_command", lambda *a, **k: next(results))

    profile.verify_runtime(paths)


def test_start_passes_no_key_in_argv_or_launch_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    credential = _synthetic_key("f")
    profile.initialize_profile(paths)
    profile.configure_key(paths, key_reader=lambda: credential)
    captured: dict[str, object] = {}

    class FakeProcess:
        pid = 424242

        @staticmethod
        def poll() -> None:
            return None

    def fake_popen(argv: list[str], **kwargs: object) -> FakeProcess:
        captured["argv"] = argv
        captured["environment"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(profile, "verify_runtime", lambda paths: None)
    monkeypatch.setattr(
        profile,
        "_validate_overlay_attestation",
        lambda paths, pid: None,
    )
    monkeypatch.setattr(profile.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        profile,
        "_wait_ready",
        lambda paths, process, timeout: {
            "version": profile.PINNED_VERSION,
            "supervisor_ready": True,
            "port": profile.DEFAULT_GATEWAY_PORT,
        },
    )

    result = profile.start_runtime(paths)

    assert result["status"] == "started"
    assert credential not in json.dumps(captured)
    assert "OPENROUTER_API_KEY" not in captured["environment"]
    assert captured["environment"]["PYTHONPATH"] == os.pathsep.join(
        (
            str(profile.RUNTIME_OVERLAY_BOOTSTRAP.parent),
            str(profile.RUNTIME_OVERLAY_SCRIPT.parent),
            str(paths.source_dir),
        )
    )
    assert captured["environment"][profile.OVERLAY_GUARD_ENV] == (
        profile.OVERLAY_ATTESTATION_SCHEMA
    )
    assert captured["environment"][profile.OVERLAY_SOURCE_ENV] == str(
        paths.source_dir
    )
    assert captured["environment"]["PIP_NO_INDEX"] == "1"
    assert captured["environment"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert captured["argv"] == [
        str(paths.python_executable),
        str(profile.RUNTIME_OVERLAY_SCRIPT),
        "--source-dir",
        str(paths.source_dir),
        "--",
        "server",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--no-ui",
    ]


def test_profile_validates_exact_live_overlay_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    profile._ensure_profile_directories(paths)
    launcher_hash = hashlib.sha256(
        profile.RUNTIME_OVERLAY_SCRIPT.read_bytes()
    ).hexdigest()
    bootstrap_hash = hashlib.sha256(
        profile.RUNTIME_OVERLAY_BOOTSTRAP.read_bytes()
    ).hexdigest()
    profile._atomic_write_private_json(
        paths.overlay_attestation_path,
        {
            "schema": profile.OVERLAY_ATTESTATION_SCHEMA,
            "pid": 424242,
            "runtime_version": profile.PINNED_VERSION,
            "source_commit": profile.PINNED_SOURCE_COMMIT,
            "source_clean": True,
            "model": profile.MODEL_ID,
            "consolidation_model": profile.MODEL_ID,
            "launcher_sha256": launcher_hash,
            "spawn_bootstrap": True,
            "bootstrap_mode": "deferred_runtime_import_hooks",
            "bootstrap_sha256": bootstrap_hash,
            "finalize_transport_retry": "exception_group_once",
            "aga_post_task_policy": "skip_synthetic_public_memory_synthesis",
        },
    )
    monkeypatch.setattr(profile, "_owned_runtime_process", lambda paths, pid: True)

    profile._validate_overlay_attestation(paths, 424242)


def test_profile_recognizes_project_overlay_process_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setattr(profile, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(
        profile,
        "_process_command",
        lambda pid: (
            f"{paths.python_executable} {profile.RUNTIME_OVERLAY_SCRIPT} "
            f"--source-dir {paths.source_dir} -- server --host 127.0.0.1"
        ),
    )

    assert profile._owned_runtime_process(paths, 424242) is True


def test_stop_removes_a_stale_owned_pid_without_signalling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _paths(tmp_path)
    profile._ensure_profile_directories(paths)
    profile._atomic_write_private_json(
        paths.pid_path,
        {
            "schema": profile.PID_SCHEMA,
            "pid": 424242,
            "executable": str(paths.executable),
            "started_at_unix": 1,
        },
    )
    monkeypatch.setattr(profile, "_pid_alive", lambda pid: False)

    result = profile.stop_runtime(paths)

    assert result == {
        "schema": profile.PROFILE_SCHEMA,
        "status": "stopped",
        "already": False,
        "runtime_log_redacted": False,
    }
    assert not paths.pid_path.exists()


def test_status_reports_only_credential_presence(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    credential = _synthetic_key("g")
    profile.initialize_profile(paths)
    profile.configure_key(paths, key_reader=lambda: credential)

    result = profile.profile_status(paths)

    assert result["credential_present"] is True
    assert credential not in json.dumps(result)


def test_status_sanitizes_a_runtime_log_without_returning_the_match(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    profile.initialize_profile(paths)
    credential = _synthetic_key("h")
    paths.runtime_log.write_text(f"provider failure: {credential}\n", encoding="utf-8")

    result = profile.profile_status(paths)
    sanitized = paths.runtime_log.read_text(encoding="utf-8")

    assert result["runtime_log_redacted"] is True
    assert credential not in json.dumps(result)
    assert credential not in sanitized
    assert "[REDACTED_OPENROUTER_KEY]" in sanitized
    assert stat.S_IMODE(paths.runtime_log.stat().st_mode) == 0o600
