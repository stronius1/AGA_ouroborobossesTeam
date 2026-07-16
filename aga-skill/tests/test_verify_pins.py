# -*- coding: utf-8 -*-
"""Offline supply-chain regressions for the root pin verifier."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import verify_pins  # noqa: E402
from tools.git_cleanliness import DEFAULT_CLEANLINESS_LIMITS  # noqa: E402


def _git(repository: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "AGA Synthetic Pins",
            "GIT_AUTHOR_EMAIL": "pins@example.invalid",
            "GIT_COMMITTER_NAME": "AGA Synthetic Pins",
            "GIT_COMMITTER_EMAIL": "pins@example.invalid",
            "GIT_AUTHOR_DATE": "2001-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z",
        }
    )
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _pinned_project(
    tmp_path: Path, *, filter_attributes: bool = False
) -> tuple[Path, verify_pins.Pin, Path]:
    source = tmp_path / "dependency-source"
    source.mkdir()
    _git(source, "init", "--quiet")
    (source / "model.yaml").write_text("components: {}\n", encoding="utf-8")
    if filter_attributes:
        (source / ".gitattributes").write_text(
            "*.txt filter=evil\n", encoding="utf-8"
        )
        (source / "filtered.txt").write_text(
            "synthetic clean content\n", encoding="utf-8"
        )
    pin_commit = _commit(source, "synthetic dependency")

    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "--quiet")
    dependency_path = "vendor/dependency"
    _git(
        root,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "--quiet",
        str(source),
        dependency_path,
    )
    _commit(root, "synthetic pinned project")
    pin = verify_pins.Pin(
        name=dependency_path,
        path=dependency_path,
        url=str(source),
        commit=pin_commit,
    )
    return root, pin, root / dependency_path


def test_verify_pins_ignores_hostile_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pin, _ = _pinned_project(tmp_path)
    hostile_source = tmp_path / "hostile-source"
    hostile_source.mkdir()
    _git(hostile_source, "init", "--quiet")
    (hostile_source / "README.md").write_text("hostile synthetic ODB\n", encoding="utf-8")
    _commit(hostile_source, "hostile synthetic commit")
    hostile_bare = tmp_path / "hostile.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(hostile_source), str(hostile_bare)],
        check=True,
        capture_output=True,
    )

    monkeypatch.setattr(verify_pins, "ROOT", root)
    monkeypatch.setattr(verify_pins, "PINS", (pin,))
    monkeypatch.setenv("GIT_DIR", str(hostile_bare))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    real_run_git = verify_pins.run_git
    head_resolutions: list[tuple[str, ...]] = []

    def recording_run_git(
        repository: Path,
        *arguments: str,
        max_stdout_bytes: int | None = None,
    ) -> bytes:
        if arguments[:2] == ("rev-parse", "--verify"):
            head_resolutions.append(arguments)
        return real_run_git(
            repository,
            *arguments,
            max_stdout_bytes=max_stdout_bytes,
        )

    monkeypatch.setattr(verify_pins, "run_git", recording_run_git)
    assert verify_pins.main() == 0
    assert len(head_resolutions) == 4
    assert set(head_resolutions) == {
        ("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"),
    }


def test_verify_pins_rejects_nested_repo_without_root_gitlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ordinary-project"
    root.mkdir()
    _git(root, "init", "--quiet")
    dependency_path = "vendor/dependency"
    checkout = root / dependency_path
    checkout.mkdir(parents=True)
    (checkout / "model.yaml").write_text("components: {}\n", encoding="utf-8")
    dependency_url = "synthetic://ordinary-nested-repository"
    (root / ".gitmodules").write_text(
        f"""[submodule \"{dependency_path}\"]
\tpath = {dependency_path}
\turl = {dependency_url}
""",
        encoding="utf-8",
    )
    _commit(root, "ordinary directory in root tree")
    _git(checkout, "init", "--quiet")
    pin_commit = _commit(checkout, "nested repository created after root commit")
    pin = verify_pins.Pin(
        name=dependency_path,
        path=dependency_path,
        url=dependency_url,
        commit=pin_commit,
    )

    monkeypatch.setattr(verify_pins, "ROOT", root)
    monkeypatch.setattr(verify_pins, "PINS", (pin,))
    assert verify_pins.main() == 1


def test_verify_pins_rejects_symlink_in_checkout_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pin, _ = _pinned_project(tmp_path)
    vendor = root / "vendor"
    redirected_vendor = root / "vendor-real"
    vendor.rename(redirected_vendor)
    vendor.symlink_to(redirected_vendor, target_is_directory=True)

    monkeypatch.setattr(verify_pins, "ROOT", root)
    monkeypatch.setattr(verify_pins, "PINS", (pin,))
    assert verify_pins.main() == 1


def test_verify_pins_dependency_untracked_check_is_bounded_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pin, checkout = _pinned_project(tmp_path)
    untracked = checkout / "untracked"
    untracked.mkdir()
    for index in range(80):
        (untracked / f"{index:03d}-{'x' * 80}.yaml").write_text(
            "synthetic untracked payload\n", encoding="utf-8"
        )

    monkeypatch.setattr(verify_pins, "ROOT", root)
    monkeypatch.setattr(verify_pins, "PINS", (pin,))
    real_run_git = verify_pins.run_git
    dependency_calls: list[tuple[tuple[str, ...], int | None]] = []

    def recording_run_git(
        repository: Path,
        *arguments: str,
        max_stdout_bytes: int | None = None,
    ) -> bytes:
        if repository == checkout:
            dependency_calls.append((arguments, max_stdout_bytes))
        return real_run_git(
            repository,
            *arguments,
            max_stdout_bytes=max_stdout_bytes,
        )

    monkeypatch.setattr(verify_pins, "run_git", recording_run_git)
    assert verify_pins.main() == 1
    assert all(arguments[0] != "status" for arguments, _ in dependency_calls)
    assert (
        ("ls-tree", "-r", "-z", "-l", "--full-tree", pin.commit),
        DEFAULT_CLEANLINESS_LIMITS.max_metadata_bytes,
    ) in dependency_calls


def test_verify_pins_clean_filter_is_never_executed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, pin, checkout = _pinned_project(tmp_path, filter_attributes=True)
    marker = tmp_path / "pins-filter-marker"
    filter_script = tmp_path / "evil-pins-filter.sh"
    filter_script.write_text(
        '#!/bin/sh\nprintf invoked > "$1"\ncat\n',
        encoding="utf-8",
    )
    filter_script.chmod(0o700)
    _git(
        checkout,
        "config",
        "filter.evil.clean",
        f"{shlex.quote(str(filter_script))} {shlex.quote(str(marker))}",
    )
    (checkout / "filtered.txt").write_text(
        "synthetic modified content\n", encoding="utf-8"
    )

    monkeypatch.setattr(verify_pins, "ROOT", root)
    monkeypatch.setattr(verify_pins, "PINS", (pin,))
    assert verify_pins.main() == 1
    assert not marker.exists()
