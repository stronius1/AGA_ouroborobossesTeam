#!/usr/bin/env python3
"""Fail-closed Compose readiness for the Git-backed MCP registry."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import threading
from typing import Any, Mapping
import urllib.request


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from tools.git_cleanliness import (  # noqa: E402
    CheckoutCleanlinessError,
    assert_clean_checkout,
)
from tools.repository_snapshot import (  # noqa: E402
    DEFAULT_ARCHTOOL_COMMIT,
    DEFAULT_ARCHTOOL_PATH,
    DEFAULT_SEAF_CORE_COMMIT,
    DEFAULT_SEAF_CORE_PATH,
)


COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_GIT_STDERR_MAX_BYTES = 4_096


class _GitOutputLimitExceeded(ValueError):
    """A Git command crossed its configured stdout allocation boundary."""


def _safe_relative(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(character in value for character in ("\x00", "\n", "\r", "\t"))
    ):
        raise ValueError(f"{field} must be a repository-relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{field} must be a repository-relative POSIX path")
    return path.as_posix()


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        {
            "HOME": os.devnull,
            "XDG_CONFIG_HOME": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def _git_command(repository: Path, arguments: tuple[str, ...]) -> list[str]:
    return [
        "git",
        "-c",
        f"safe.directory={repository}",
        "-c",
        "core.fsmonitor=false",
        "--no-pager",
        "--no-replace-objects",
        "-C",
        str(repository),
        *arguments,
    ]


def _git(repository: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        _git_command(repository, arguments),
        check=True,
        capture_output=True,
        timeout=10,
        env=_git_environment(),
    )
    return completed.stdout


def _git_bounded(
    repository: Path, *arguments: str, max_stdout_bytes: int
) -> bytes:
    """Run Git with bounded stdout/stderr and terminate immediately on overflow."""

    process = subprocess.Popen(
        _git_command(repository, arguments),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_environment(),
    )
    stdout = bytearray()
    stderr = bytearray()
    output_exceeded = threading.Event()
    stream_errors: list[BaseException] = []

    def read_stdout() -> None:
        try:
            assert process.stdout is not None
            while chunk := process.stdout.read(4_096):
                if len(stdout) + len(chunk) > max_stdout_bytes:
                    output_exceeded.set()
                    process.kill()
                    return
                stdout.extend(chunk)
        except BaseException as exc:  # pragma: no cover - defensive OS boundary
            stream_errors.append(exc)
            process.kill()

    def read_stderr() -> None:
        try:
            assert process.stderr is not None
            while chunk := process.stderr.read(4_096):
                stderr.extend(chunk)
                if len(stderr) > _GIT_STDERR_MAX_BYTES:
                    del stderr[:-_GIT_STDERR_MAX_BYTES]
        except BaseException as exc:  # pragma: no cover - defensive OS boundary
            stream_errors.append(exc)
            process.kill()

    readers = (
        threading.Thread(target=read_stdout, name="aga-readiness-git-stdout", daemon=True),
        threading.Thread(target=read_stderr, name="aga-readiness-git-stderr", daemon=True),
    )
    for reader in readers:
        reader.start()
    try:
        return_code = process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        for reader in readers:
            reader.join(timeout=1.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        raise
    for reader in readers:
        reader.join(timeout=1.0)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    if output_exceeded.is_set():
        raise _GitOutputLimitExceeded("Git output exceeds readiness limit")
    if any(reader.is_alive() for reader in readers) or stream_errors:
        process.kill()
        raise OSError("Git output stream failed")
    if return_code != 0:
        raise subprocess.CalledProcessError(
            return_code,
            process.args,
            output=bytes(stdout),
            stderr=bytes(stderr),
        )
    return bytes(stdout)


def _commit(repository: Path) -> str:
    value = _git(
        repository, "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"
    ).decode("ascii", errors="strict").strip()
    if COMMIT_RE.fullmatch(value) is None:
        raise ValueError("HEAD did not resolve to a full commit ID")
    return value


def _repository_worktree_root(value: str) -> Path:
    try:
        repository = Path(value).expanduser().resolve(strict=True)
        repository_info = repository.lstat()
    except (OSError, RuntimeError) as exc:
        raise ValueError("repository root is unavailable") from exc
    if not stat.S_ISDIR(repository_info.st_mode):
        raise ValueError("repository root must be a directory")

    try:
        git_directory = Path(
            _git(repository, "rev-parse", "--absolute-git-dir")
            .decode("utf-8", errors="strict")
            .strip()
        ).resolve(strict=True)
        bare = _git(repository, "rev-parse", "--is-bare-repository").decode(
            "ascii", errors="strict"
        ).strip()
        if bare != "false":
            raise ValueError("repository root must be a non-bare Git worktree")
        top = Path(
            _git(repository, "rev-parse", "--show-toplevel")
            .decode("utf-8", errors="strict")
            .strip()
        ).resolve(strict=True)
        git_directory_info = git_directory.lstat()
    except ValueError:
        raise
    except (UnicodeDecodeError, OSError, RuntimeError) as exc:
        raise ValueError("repository root is not a Git worktree") from exc
    if top != repository or not stat.S_ISDIR(git_directory_info.st_mode):
        raise ValueError("repository path must be its exact Git worktree root")
    return repository


def _dependency_worktree_root(value: str) -> Path:
    """Return a real, exact Git worktree root without hiding lexical symlinks."""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    # Inspect every lexical component before resolve(). Otherwise a configured
    # symlink would be silently replaced by its target and could later be
    # redirected without changing the trusted-dependency configuration.
    current = Path(candidate.anchor)
    try:
        for part in candidate.parts[1:]:
            current = current / part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise ValueError("dependency checkout cannot contain symlinks")
        checkout = candidate.resolve(strict=True)
        checkout_info = checkout.lstat()
    except ValueError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ValueError("dependency checkout is unavailable") from exc
    if not stat.S_ISDIR(checkout_info.st_mode):
        raise ValueError("dependency checkout must be a real directory")

    try:
        git_directory = Path(
            _git(checkout, "rev-parse", "--absolute-git-dir")
            .decode("utf-8", errors="strict")
            .strip()
        ).resolve(strict=True)
        top = Path(
            _git(checkout, "rev-parse", "--show-toplevel")
            .decode("utf-8", errors="strict")
            .strip()
        ).resolve(strict=True)
        git_directory_info = git_directory.lstat()
    except (UnicodeDecodeError, OSError, RuntimeError) as exc:
        raise ValueError("dependency checkout is not a Git worktree") from exc
    if top != checkout or not stat.S_ISDIR(git_directory_info.st_mode):
        raise ValueError("dependency checkout must be its Git worktree root")
    return checkout


def _dependencies(value: str) -> dict[str, Mapping[str, Any]]:
    parsed = json.loads(value)
    if not isinstance(parsed, Mapping):
        raise ValueError("trusted dependency config must be an object")
    result: dict[str, Mapping[str, Any]] = {}
    for raw_path, config in parsed.items():
        path = _safe_relative(raw_path, "dependency path")
        if not isinstance(config, Mapping) or set(config) != {"checkout", "commit"}:
            raise ValueError("dependency config requires checkout and commit")
        result[path] = config
    return result


def check_readiness(environment: Mapping[str, str] = os.environ) -> None:
    raw_root = environment.get("AGA_REPOSITORY_ROOT", "")
    if not raw_root:
        raise ValueError("AGA_REPOSITORY_ROOT is required")
    repository = _repository_worktree_root(raw_root)
    manifest = _safe_relative(
        environment.get("AGA_ARCHITECTURE_MANIFEST", "dochub.yaml"),
        "AGA_ARCHITECTURE_MANIFEST",
    )
    head = _commit(repository)
    _git(repository, "cat-file", "-e", f"{head}:{manifest}")

    mode = environment.get("AGA_DEPENDENCY_MODE", "verified")
    if mode not in {"verified", "fixture"}:
        raise ValueError("AGA_DEPENDENCY_MODE must be verified or fixture")
    configured = _dependencies(environment.get("AGA_TRUSTED_DEPENDENCIES_JSON", "{}"))
    if mode == "verified":
        expected = {
            DEFAULT_ARCHTOOL_PATH: DEFAULT_ARCHTOOL_COMMIT,
            DEFAULT_SEAF_CORE_PATH: DEFAULT_SEAF_CORE_COMMIT,
        }
        if {
            path: config.get("commit") for path, config in configured.items()
        } != expected:
            raise ValueError("verified mode requires the two exact dependency pins")

    for path, config in configured.items():
        pin = config["commit"]
        if not isinstance(pin, str) or COMMIT_RE.fullmatch(pin) is None:
            raise ValueError("dependency pin must be a full commit ID")
        if not isinstance(config["checkout"], str) or not config["checkout"]:
            raise ValueError("dependency checkout must be a path string")
        checkout = _dependency_worktree_root(config["checkout"])
        if _commit(checkout) != pin:
            raise ValueError("dependency checkout does not match its pin")
        try:
            assert_clean_checkout(
                checkout,
                pin,
                lambda arguments, cap: _git_bounded(
                    checkout,
                    *arguments,
                    max_stdout_bytes=cap,
                ),
            )
        except (CheckoutCleanlinessError, _GitOutputLimitExceeded) as exc:
            raise ValueError("dependency checkout is dirty") from exc
        record = _git(
            repository,
            "ls-tree",
            "-z",
            "--full-tree",
            head,
            "--",
            f":(literal){path}",
        )
        expected_record = f"160000 commit {pin}\t{path}\0".encode("utf-8")
        if record != expected_record:
            raise ValueError("repository gitlink does not match its dependency pin")


def main() -> int:
    try:
        check_readiness()
        port = int(os.environ.get("AGA_MCP_PORT", "8000"))
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=2
        ) as response:
            if response.status != 200:
                raise ValueError("MCP liveness endpoint is unhealthy")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"MCP NOT READY: {error}", file=sys.stderr)
        return 1
    print("MCP READY: Git manifest and dependency pins are available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
