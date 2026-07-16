# -*- coding: utf-8 -*-
"""Contract tests for the local SEAF-native submission demo."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_seaf_review.py"


def _run(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--case",
            "demo-critical-dependency",
            "--mode",
            mode,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_offline_seaf_demo_uses_real_git_diff_and_stays_incomplete() -> None:
    completed = _run("offline")
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["data_classification"] == "synthetic-public"
    assert result["base_revision"] != result["head_revision"]
    assert result["status"] == "incomplete"
    assert result["agent_status"] == "not_run"
    assert result["verdict"] == "incomplete"
    assert result["provisional_verdict"] == "request_changes_escalate"
    assert {finding["rule_id"] for finding in result["deterministic_findings"]} == {
        "SEAF-004"
    }
    assert result["semantic_task_ids"] == [
        "PRIN-004",
        "PRIN-005",
        "PRIN-006",
        "PRIN-007",
    ]
    assert result["hitl_required"] is True
    assert result["auto_merge"] is False


def test_real_agent_demo_fails_closed_without_verified_adapter() -> None:
    completed = _run("gigaagent")
    assert completed.returncode == 2
    result = json.loads(completed.stdout)
    assert result["status"] == "incomplete"
    assert result["verdict"] == "incomplete"
    assert result["agent_status"] == "not_configured"
    assert result["hitl_required"] is True


def test_demo_ignores_hostile_git_configuration_and_keeps_reproducible_sha1(
    tmp_path: Path,
    monkeypatch,
) -> None:
    marker = tmp_path / "hostile-git-code-executed"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    pre_commit = hooks / "pre-commit"
    pre_commit.write_text(
        "#!/bin/sh\nprintf 'hook\\n' >> \"$HOSTILE_GIT_MARKER\"\nexit 97\n",
        encoding="utf-8",
    )
    pre_commit.chmod(0o755)

    filter_script = tmp_path / "hostile-filter.sh"
    filter_script.write_text(
        "#!/bin/sh\nprintf 'filter\\n' >> \"$HOSTILE_GIT_MARKER\"\ncat\n",
        encoding="utf-8",
    )
    filter_script.chmod(0o755)
    attributes = tmp_path / "hostile-attributes"
    attributes.write_text("* filter=hostile\n", encoding="utf-8")

    hostile_config = tmp_path / "hostile.gitconfig"
    hostile_config.write_text(
        "\n".join(
            (
                "[init]",
                "\tdefaultObjectFormat = sha256",
                "[commit]",
                "\tgpgSign = true",
                "[core]",
                f"\thooksPath = {hooks.as_posix()}",
                f"\tattributesFile = {attributes.as_posix()}",
                '[filter "hostile"]',
                f"\tclean = {filter_script.as_posix()}",
                f"\tsmudge = {filter_script.as_posix()}",
                "\trequired = true",
                "",
            )
        ),
        encoding="utf-8",
    )
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    (hostile_home / ".gitconfig").write_bytes(hostile_config.read_bytes())

    monkeypatch.setenv("HOME", str(hostile_home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile_config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(hostile_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "0")
    monkeypatch.setenv("GIT_DEFAULT_HASH", "sha256")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hooks))
    monkeypatch.setenv("HOSTILE_GIT_MARKER", str(marker))

    first = _run("offline")
    second = _run("offline")
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_result = json.loads(first.stdout)
    second_result = json.loads(second.stdout)

    for revision in (first_result["base_revision"], first_result["head_revision"]):
        assert re.fullmatch(r"[0-9a-f]{40}", revision)
    assert first_result["base_revision"] == second_result["base_revision"]
    assert first_result["head_revision"] == second_result["head_revision"]
    assert not marker.exists()
