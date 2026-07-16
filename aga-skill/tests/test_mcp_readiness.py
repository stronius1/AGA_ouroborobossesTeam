# -*- coding: utf-8 -*-
"""Offline checks for the Git-backed Compose readiness probe."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from scripts import mcp_readiness  # noqa: E402
from scripts.mcp_readiness import check_readiness  # noqa: E402
from tools.git_cleanliness import DEFAULT_CLEANLINESS_LIMITS  # noqa: E402


def _git(repository: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_NAME": "AGA Synthetic Readiness",
            "GIT_AUTHOR_EMAIL": "readiness@example.invalid",
            "GIT_COMMITTER_NAME": "AGA Synthetic Readiness",
            "GIT_COMMITTER_EMAIL": "readiness@example.invalid",
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


def _repository(tmp_path: Path, *, commit: bool = True) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    manifest = repository / "architecture" / "dochub.yaml"
    manifest.parent.mkdir()
    manifest.write_text("imports: []\n", encoding="utf-8")
    if commit:
        _git(repository, "add", ".")
        _git(repository, "commit", "--quiet", "-m", "synthetic readiness")
    return repository


def _environment(repository: Path, mode: str = "fixture") -> dict[str, str]:
    return {
        "AGA_REPOSITORY_ROOT": str(repository),
        "AGA_ARCHITECTURE_MANIFEST": "architecture/dochub.yaml",
        "AGA_DEPENDENCY_MODE": mode,
        "AGA_TRUSTED_DEPENDENCIES_JSON": "{}",
    }


def _repository_with_dependency(
    tmp_path: Path, *, filter_attributes: bool = False,
) -> tuple[Path, Path, str, str]:
    dependency = tmp_path / "dependency"
    dependency.mkdir()
    _git(dependency, "init", "--quiet")
    nested = dependency / "nested"
    nested.mkdir()
    (nested / "model.yaml").write_text("components: {}\n", encoding="utf-8")
    if filter_attributes:
        (dependency / ".gitattributes").write_text(
            "*.txt filter=evil\n", encoding="utf-8"
        )
        (dependency / "filtered.txt").write_text(
            "synthetic clean content\n", encoding="utf-8"
        )
    _git(dependency, "add", ".")
    _git(dependency, "commit", "--quiet", "-m", "synthetic dependency")
    pin = _git(dependency, "rev-parse", "HEAD")

    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    dependency_path = "architecture/vendor/seaf-core"
    _git(
        repository,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "--quiet",
        str(dependency),
        dependency_path,
    )
    manifest = repository / "architecture" / "dochub.yaml"
    manifest.write_text("imports: []\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "synthetic superproject")
    return repository, repository / dependency_path, dependency_path, pin


def _dependency_environment(
    repository: Path, checkout: Path, dependency_path: str, pin: str
) -> dict[str, str]:
    environment = _environment(repository)
    environment["AGA_TRUSTED_DEPENDENCIES_JSON"] = json.dumps(
        {
            dependency_path: {
                "checkout": str(checkout),
                "commit": pin,
            }
        }
    )
    return environment


def test_fixture_readiness_requires_a_committed_manifest(tmp_path: Path) -> None:
    check_readiness(_environment(_repository(tmp_path)))


def test_readiness_rejects_repository_without_head(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        check_readiness(_environment(_repository(tmp_path, commit=False)))


def test_verified_readiness_requires_both_official_gitlinks(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="two exact dependency pins"):
        check_readiness(_environment(_repository(tmp_path), mode="verified"))


def test_readiness_rejects_nested_dependency_checkout(tmp_path: Path) -> None:
    repository, checkout, dependency_path, pin = _repository_with_dependency(tmp_path)
    check_readiness(
        _dependency_environment(repository, checkout, dependency_path, pin)
    )

    with pytest.raises(ValueError, match="must be its Git worktree root"):
        check_readiness(
            _dependency_environment(
                repository, checkout / "nested", dependency_path, pin
            )
        )


def test_readiness_rejects_lexical_dependency_symlink(tmp_path: Path) -> None:
    repository, checkout, dependency_path, pin = _repository_with_dependency(tmp_path)
    checkout_link = tmp_path / "dependency-link"
    checkout_link.symlink_to(checkout, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot contain symlinks"):
        check_readiness(
            _dependency_environment(repository, checkout_link, dependency_path, pin)
        )


def test_readiness_rejects_non_directory_absolute_git_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    not_a_directory = tmp_path / "gitdir-file"
    not_a_directory.write_text("synthetic non-directory gitdir\n", encoding="utf-8")
    real_git = mcp_readiness._git

    def synthetic_git(checkout: Path, *arguments: str) -> bytes:
        if arguments == ("rev-parse", "--absolute-git-dir"):
            return f"{not_a_directory}\n".encode("utf-8")
        return real_git(checkout, *arguments)

    monkeypatch.setattr(mcp_readiness, "_git", synthetic_git)
    with pytest.raises(ValueError, match="must be its Git worktree root"):
        mcp_readiness._dependency_worktree_root(str(repository))


def test_readiness_dependency_untracked_check_is_bounded_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, checkout, dependency_path, pin = _repository_with_dependency(tmp_path)
    untracked = checkout / "untracked"
    untracked.mkdir()
    for index in range(80):
        (untracked / f"{index:03d}-{'x' * 80}.yaml").write_text(
            "synthetic untracked payload\n", encoding="utf-8"
        )
    real_git_bounded = mcp_readiness._git_bounded
    dependency_calls: list[tuple[tuple[str, ...], int]] = []

    def recording_git_bounded(
        git_repository: Path,
        *arguments: str,
        max_stdout_bytes: int,
    ) -> bytes:
        if git_repository == checkout:
            dependency_calls.append((arguments, max_stdout_bytes))
        return real_git_bounded(
            git_repository,
            *arguments,
            max_stdout_bytes=max_stdout_bytes,
        )

    monkeypatch.setattr(mcp_readiness, "_git_bounded", recording_git_bounded)
    with pytest.raises(ValueError, match="dependency checkout is dirty"):
        check_readiness(
            _dependency_environment(repository, checkout, dependency_path, pin)
        )
    assert all(arguments[0] != "status" for arguments, _ in dependency_calls)
    assert (
        ("ls-tree", "-r", "-z", "-l", "--full-tree", pin),
        DEFAULT_CLEANLINESS_LIMITS.max_metadata_bytes,
    ) in dependency_calls


def test_readiness_clean_filter_is_never_executed(tmp_path: Path) -> None:
    repository, checkout, dependency_path, pin = _repository_with_dependency(
        tmp_path, filter_attributes=True
    )
    marker = tmp_path / "readiness-filter-marker"
    filter_script = tmp_path / "evil-readiness-filter.sh"
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

    with pytest.raises(ValueError, match="dependency checkout is dirty"):
        check_readiness(
            _dependency_environment(repository, checkout, dependency_path, pin)
        )
    assert not marker.exists()


def test_readiness_git_environment_ignores_hostile_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    hostile_source = tmp_path / "hostile-source"
    hostile_source.mkdir()
    _git(hostile_source, "init", "--quiet")
    (hostile_source / "README.md").write_text("hostile synthetic ODB\n", encoding="utf-8")
    _git(hostile_source, "add", ".")
    _git(hostile_source, "commit", "--quiet", "-m", "hostile synthetic commit")
    hostile_bare = tmp_path / "hostile.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(hostile_source), str(hostile_bare)],
        check=True,
        capture_output=True,
    )

    monkeypatch.setenv("GIT_DIR", str(hostile_bare))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")

    check_readiness(_environment(repository))


def test_readiness_rejects_nested_repository_root(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(ValueError, match="exact Git worktree root"):
        check_readiness(_environment(repository / "architecture"))


def test_readiness_rejects_bare_repository_root(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(repository), str(bare)],
        check=True,
        capture_output=True,
    )

    with pytest.raises(ValueError, match="non-bare Git worktree"):
        check_readiness(_environment(bare))
