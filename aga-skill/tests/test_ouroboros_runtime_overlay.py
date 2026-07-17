# -*- coding: utf-8 -*-
"""Offline tests for the project-owned Ouroboros runtime overlay."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap
from types import ModuleType
from types import SimpleNamespace

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import ouroboros_runtime_overlay as overlay  # noqa: E402


def _load_bootstrap_for_unit_test() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "aga_overlay_bootstrap_unit_test",
        overlay.BOOTSTRAP_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_mcp_module(
    tmp_path: Path,
    original: object,
) -> tuple[ModuleType, Path]:
    source_dir = tmp_path / "source"
    module_path = source_dir / "ouroboros" / "mcp_client.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# synthetic-public\n", encoding="utf-8")
    module = ModuleType("synthetic_mcp_client")
    module.__file__ = str(module_path)
    module._call_tool_async = original  # type: ignore[attr-defined]
    return module, source_dir


def _managed_aga_task() -> dict[str, object]:
    review_id = "aga-synthetic-review"
    return {
        "type": "task",
        "delegation_role": "root",
        "workspace_mode": "external",
        "memory_mode": "empty",
        "workspace_root": (
            "/private/tmp/aga-synthetic-public/ouroboros-cases/ga-01"
        ),
        "project_id": "aga-" + "a" * 32,
        "description": (
            "AGA orchestration prompt v1.0.3\n"
            "data_classification: synthetic-public"
        ),
        "metadata": {
            "aga_review_id": review_id,
            "aga_idempotency_key": review_id,
            "aga_prompt_sha256": "b" * 64,
            "data_classification": "synthetic-public",
            "expected_model_id": overlay.PINNED_MODEL,
            "allowed_resources": {"network": True, "web": False},
            "disabled_tools": [
                "write_file",
                "run_command",
                "web_search",
                "mcp_aga__aga_parse_diagram",
            ],
        },
    }


def test_known_v6641_consolidation_constant_is_pinned_in_memory() -> None:
    module = ModuleType("synthetic_consolidator")
    module.CONSOLIDATION_MODEL = overlay.UPSTREAM_CONSOLIDATION_MODEL

    overlay._pin_consolidation_model(module)

    assert module.CONSOLIDATION_MODEL == overlay.PINNED_MODEL

    # Multiprocessing spawn bootstraps and the explicit launcher may both
    # validate the same interpreter; the known pinned value is idempotent.
    overlay._pin_consolidation_model(module)
    assert module.CONSOLIDATION_MODEL == overlay.PINNED_MODEL


def test_unknown_upstream_consolidation_contract_is_rejected() -> None:
    module = ModuleType("synthetic_consolidator")
    module.CONSOLIDATION_MODEL = "changed/upstream-model"

    with pytest.raises(overlay.OverlayError) as caught:
        overlay._pin_consolidation_model(module)

    assert str(caught.value) == "consolidation_contract_mismatch"


def test_finalize_exception_group_is_retried_once_with_identical_arguments(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def original(
        _cfg: object,
        _tool_name: str,
        arguments: dict[str, object],
        *,
        timeout_sec: int,
    ) -> str:
        calls.append(json.loads(json.dumps(arguments)))
        if len(calls) == 1:
            raise ExceptionGroup("synthetic-public", [RuntimeError("teardown")])
        assert timeout_sec == 17
        return "stored-finalize-result"

    bootstrap = _load_bootstrap_for_unit_test()
    module, source_dir = _synthetic_mcp_module(tmp_path, original)
    bootstrap._verified_source_dir = lambda: source_dir
    bootstrap._verify_and_patch_mcp_client(module)
    arguments = {
        "review_id": "synthetic-review",
        "review_digest": "rvw_" + "a" * 64,
        "task_digest": "tsk_" + "b" * 64,
        "semantic_result": {"status": "completed", "findings": []},
    }

    result = asyncio.run(
        module._call_tool_async(  # type: ignore[attr-defined]
            SimpleNamespace(id="aga"),
            "aga_finalize_review",
            arguments,
            timeout_sec=17,
        )
    )

    assert result == "stored-finalize-result"
    assert calls == [arguments, arguments]
    assert module._call_tool_async.aga_finalize_retry_overlay == (  # type: ignore[attr-defined]
        overlay.ATTESTATION_SCHEMA
    )


@pytest.mark.parametrize(
    ("server_id", "tool_name", "raised"),
    [
        ("other", "aga_finalize_review", ExceptionGroup("x", [RuntimeError("x")])),
        ("aga", "aga_prepare_review", ExceptionGroup("x", [RuntimeError("x")])),
        ("aga", "aga_finalize_review", RuntimeError("x")),
    ],
)
def test_retry_overlay_rejects_every_other_failure_shape(
    tmp_path: Path,
    server_id: str,
    tool_name: str,
    raised: Exception,
) -> None:
    calls = 0

    async def original(
        _cfg: object,
        _tool_name: str,
        _arguments: dict[str, object],
        *,
        timeout_sec: int,
    ) -> str:
        nonlocal calls
        calls += 1
        assert timeout_sec == 5
        raise raised

    bootstrap = _load_bootstrap_for_unit_test()
    module, source_dir = _synthetic_mcp_module(tmp_path, original)
    bootstrap._verified_source_dir = lambda: source_dir
    bootstrap._verify_and_patch_mcp_client(module)
    arguments = {
        "review_id": "synthetic-review",
        "review_digest": "rvw_" + "a" * 64,
        "task_digest": "tsk_" + "b" * 64,
        "semantic_result": {},
    }

    with pytest.raises(type(raised)):
        asyncio.run(
            module._call_tool_async(  # type: ignore[attr-defined]
                SimpleNamespace(id=server_id),
                tool_name,
                arguments,
                timeout_sec=5,
            )
        )

    assert calls == 1


def test_second_finalize_exception_group_is_not_retried_again(
    tmp_path: Path,
) -> None:
    calls = 0

    async def original(
        _cfg: object,
        _tool_name: str,
        _arguments: dict[str, object],
        *,
        timeout_sec: int,
    ) -> str:
        nonlocal calls
        calls += 1
        assert timeout_sec == 5
        raise ExceptionGroup("synthetic-public", [RuntimeError("teardown")])

    bootstrap = _load_bootstrap_for_unit_test()
    module, source_dir = _synthetic_mcp_module(tmp_path, original)
    bootstrap._verified_source_dir = lambda: source_dir
    bootstrap._verify_and_patch_mcp_client(module)
    arguments = {
        "review_id": "synthetic-review",
        "review_digest": "rvw_" + "a" * 64,
        "task_digest": "tsk_" + "b" * 64,
        "semantic_result": {},
    }

    with pytest.raises(ExceptionGroup):
        asyncio.run(
            module._call_tool_async(  # type: ignore[attr-defined]
                SimpleNamespace(id="aga"),
                "aga_finalize_review",
                arguments,
                timeout_sec=5,
            )
        )

    assert calls == 2


def test_managed_aga_post_task_policy_skips_only_memory_synthesis(
    tmp_path: Path,
) -> None:
    original_calls: list[dict[str, object]] = []
    checkpoints: list[tuple[dict[str, object], str]] = []

    def original(
        _env: object,
        task: dict[str, object],
        _usage: dict[str, object],
        _trace: dict[str, object],
        _evidence: dict[str, object],
        _logs: Path,
        *,
        blocking: bool = False,
        on_reflection: object = None,
    ) -> dict[str, object]:
        original_calls.append(task)
        return {"blocking": blocking, "callback": on_reflection}

    source_dir = tmp_path / "source"
    module_path = source_dir / "ouroboros" / "agent_task_pipeline.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# synthetic-public\n", encoding="utf-8")
    module = ModuleType("synthetic_agent_task_pipeline")
    module.__file__ = str(module_path)
    module._run_post_task_processing_async = original  # type: ignore[attr-defined]
    module._is_root_post_task = lambda _task: True  # type: ignore[attr-defined]
    module._set_root_post_task_checkpoint = (  # type: ignore[attr-defined]
        lambda _env, task, status: checkpoints.append((task, status))
    )
    bootstrap = _load_bootstrap_for_unit_test()
    bootstrap._verified_source_dir = lambda: source_dir
    bootstrap._verify_and_patch_agent_task_pipeline(module)
    managed = _managed_aga_task()

    result = module._run_post_task_processing_async(  # type: ignore[attr-defined]
        object(), managed, {}, {}, {}, tmp_path, blocking=True
    )

    assert result is None
    assert original_calls == []
    assert checkpoints == [(managed, "completed")]

    ordinary = _managed_aga_task()
    ordinary["metadata"] = {
        **ordinary["metadata"],  # type: ignore[dict-item]
        "data_classification": "private",
    }
    passthrough = module._run_post_task_processing_async(  # type: ignore[attr-defined]
        object(), ordinary, {}, {}, {}, tmp_path, blocking=True
    )
    assert passthrough == {"blocking": True, "callback": None}
    assert original_calls == [ordinary]
    assert checkpoints == [(managed, "completed")]


def test_attestation_write_is_atomic_private_and_secret_free(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    path = state_dir / overlay.ATTESTATION_FILENAME
    value = {
        "schema": overlay.ATTESTATION_SCHEMA,
        "pid": 424242,
        "runtime_version": overlay.PINNED_VERSION,
        "source_commit": overlay.PINNED_SOURCE_COMMIT,
        "source_clean": True,
        "model": overlay.PINNED_MODEL,
        "consolidation_model": overlay.PINNED_MODEL,
        "launcher_sha256": "a" * 64,
        "spawn_bootstrap": True,
        "bootstrap_mode": "deferred_runtime_import_hooks",
        "bootstrap_sha256": "b" * 64,
        "finalize_transport_retry": "exception_group_once",
        "aga_post_task_policy": "skip_synthetic_public_memory_synthesis",
    }

    overlay._atomic_write_attestation(path, value)

    assert json.loads(path.read_text(encoding="utf-8")) == value
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "OPENROUTER" not in path.read_text(encoding="utf-8")
    assert not list(state_dir.glob(f".{path.name}.tmp.*"))


def test_launcher_accepts_only_the_exact_managed_server_shape(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = overlay.main(
        [
            "--source-dir",
            "/synthetic/source",
            "--",
            "run",
            "synthetic-public prompt",
        ]
    )

    assert result == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == (
        "ouroboros runtime overlay: unsupported_runtime_arguments"
    )
    assert "/synthetic/source" not in captured.err


def _bootstrap_environment(
    tmp_path: Path,
    *,
    python_path: tuple[Path, ...],
    source_dir: Path,
) -> dict[str, str]:
    environment = {
        "HOME": str(tmp_path),
        "PATH": os.defpath,
        "PYTHONPATH": os.pathsep.join(str(path) for path in python_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(tmp_path / "pycache"),
        "PIP_NO_INDEX": "1",
        overlay.OVERLAY_GUARD_ENV: overlay.ATTESTATION_SCHEMA,
        overlay.OVERLAY_SOURCE_ENV: str(source_dir),
    }
    for key in ("LANG", "LC_ALL", "LC_CTYPE"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def test_sitecustomize_defers_all_ouroboros_imports(
    tmp_path: Path,
) -> None:
    environment = _bootstrap_environment(
        tmp_path,
        python_path=(overlay.BOOTSTRAP_PATH.parent,),
        source_dir=tmp_path / "source-not-needed-until-import",
    )
    probe = (
        "import os,sys; "
        "assert os.environ.get('AGA_OUROBOROS_OVERLAY_HOOK_INSTALLED') == "
        "'aga.ouroboros-runtime-overlay/v3'; "
        "assert not any(n == 'ouroboros' or n.startswith('ouroboros.') "
        "for n in sys.modules); "
        "assert any(getattr(f, 'aga_overlay_marker', '') == "
        "'aga_deferred_runtime_overlay_v3' for f in sys.meta_path); "
        "print('deferred-hook-ok')"
    )

    result = subprocess.run(
        (sys.executable, "-c", probe),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10.0,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "deferred-hook-ok\n"
    assert result.stderr == ""


def test_sitecustomize_failure_terminates_managed_child_fail_closed(
    tmp_path: Path,
) -> None:
    synthetic_import_root = tmp_path / "synthetic-import-root"
    package = synthetic_import_root / "ouroboros"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "consolidator.py").write_text(
        "CONSOLIDATION_MODEL = 'synthetic/model'\n",
        encoding="utf-8",
    )
    environment = _bootstrap_environment(
        tmp_path,
        python_path=(overlay.BOOTSTRAP_PATH.parent, synthetic_import_root),
        source_dir=tmp_path / "missing-source",
    )

    result = subprocess.run(
        (sys.executable, "-c", "import ouroboros.consolidator; print('must-not-run')"),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5.0,
        check=False,
    )

    assert result.returncode == 78
    assert result.stdout == ""
    assert result.stderr == "ouroboros runtime overlay bootstrap failed\n"
    assert str(tmp_path) not in result.stderr


def test_live_style_base_python_spawn_restores_mcp_before_overlay_import(
    tmp_path: Path,
) -> None:
    runtime_root = Path.home() / ".local/share/aga-ouroboros-v6.64.1"
    runtime_python = runtime_root / "venv/bin/python"
    source_dir = runtime_root / "source"
    if not runtime_python.is_file() or not source_dir.is_dir():
        pytest.skip("isolated Ouroboros runtime is not installed")

    metadata = subprocess.run(
        (
            str(runtime_python),
            "-c",
            "import json,sys; print(json.dumps({'base': sys._base_executable}))",
        ),
        env={"HOME": str(tmp_path), "PATH": os.defpath},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10.0,
        check=False,
    )
    assert metadata.returncode == 0, metadata.stderr
    base_executable = json.loads(metadata.stdout)["base"]
    assert Path(base_executable).is_file()

    probe_path = tmp_path / "spawn_overlay_probe.py"
    probe_path.write_text(
        textwrap.dedent(
            """
            import importlib.util
            import json
            import multiprocessing as mp
            import os
            import sys

            def probe(queue):
                early_modules = sorted(
                    name for name in sys.modules
                    if name == "ouroboros" or name.startswith("ouroboros.")
                )
                mcp_spec_before = importlib.util.find_spec("mcp") is not None
                import ouroboros.consolidator as consolidator
                import ouroboros.mcp_client as mcp_client
                import ouroboros.agent_task_pipeline as agent_task_pipeline
                queue.put({
                    "base_executable": sys._base_executable,
                    "early_modules": early_modules,
                    "mcp_spec_before": mcp_spec_before,
                    "mcp_sdk_available": mcp_client._MCP_SDK_AVAILABLE,
                    "model": consolidator.CONSOLIDATION_MODEL,
                    "hook": os.environ.get(
                        "AGA_OUROBOROS_OVERLAY_HOOK_INSTALLED", ""
                    ),
                    "applied": os.environ.get(
                        "AGA_OUROBOROS_OVERLAY_APPLIED", ""
                    ),
                    "mcp_retry_applied": os.environ.get(
                        "AGA_OUROBOROS_MCP_RETRY_APPLIED", ""
                    ),
                    "mcp_retry_marker": getattr(
                        mcp_client._call_tool_async,
                        "aga_finalize_retry_overlay",
                        "",
                    ),
                    "post_task_policy_applied": os.environ.get(
                        "AGA_OUROBOROS_POST_TASK_POLICY_APPLIED", ""
                    ),
                    "post_task_policy_marker": getattr(
                        agent_task_pipeline._run_post_task_processing_async,
                        "aga_post_task_policy_overlay",
                        "",
                    ),
                })

            if __name__ == "__main__":
                context = mp.get_context("spawn")
                queue = context.Queue()
                process = context.Process(target=probe, args=(queue,))
                process.start()
                process.join(30)
                if process.exitcode != 0:
                    raise SystemExit(20 + int(process.exitcode or 0))
                print(json.dumps(queue.get(timeout=5), sort_keys=True))
            """
        ).lstrip(),
        encoding="utf-8",
    )
    environment = _bootstrap_environment(
        tmp_path,
        python_path=(
            overlay.BOOTSTRAP_PATH.parent,
            overlay.BOOTSTRAP_PATH.parent.parent,
            source_dir,
        ),
        source_dir=source_dir,
    )
    environment["PATH"] = os.pathsep.join(
        (str(runtime_python.parent), os.defpath)
    )

    result = subprocess.run(
        (str(runtime_python), str(probe_path)),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45.0,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["base_executable"] == base_executable
    assert payload["early_modules"] == []
    assert payload["mcp_spec_before"] is True
    assert payload["mcp_sdk_available"] is True
    assert payload["model"] == overlay.PINNED_MODEL
    assert payload["hook"] == overlay.ATTESTATION_SCHEMA
    assert payload["applied"] == overlay.ATTESTATION_SCHEMA
    assert payload["mcp_retry_applied"] == overlay.ATTESTATION_SCHEMA
    assert payload["mcp_retry_marker"] == overlay.ATTESTATION_SCHEMA
    assert payload["post_task_policy_applied"] == overlay.ATTESTATION_SCHEMA
    assert payload["post_task_policy_marker"] == overlay.ATTESTATION_SCHEMA
