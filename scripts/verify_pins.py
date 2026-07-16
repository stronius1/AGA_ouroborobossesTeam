#!/usr/bin/env python3
"""Verify immutable upstream Git links without contacting a remote."""

from __future__ import annotations

import configparser
import os
import re
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aga-skill"))

from tools.git_cleanliness import (  # noqa: E402
    CheckoutCleanlinessError,
    assert_clean_checkout,
)


COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_GIT_STDERR_MAX_BYTES = 4_096
_GIT_TIMEOUT_SECONDS = 30


class GitOutputLimitExceeded(RuntimeError):
    """Git produced more stdout than this integrity check permits."""


@dataclass(frozen=True)
class Pin:
    name: str
    path: str
    url: str
    commit: str


PINS = (
    Pin(
        "seaf-archtool-core",
        "seaf-archtool-core",
        "https://gitverse.ru/seafteam/seaf-archtool-core.git",
        "83c82ab1673f1245b499c26b82d507fa602a11d6",
    ),
    Pin(
        "seaf-core",
        "architecture/vendor/seaf-core",
        "https://gitverse.ru/seafteam/seaf-core.git",
        "60ce335832d2734814c020306a85d1e8b12cf67b",
    ),
)


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


def run_git(
    repository: Path,
    *arguments: str,
    max_stdout_bytes: int | None = None,
) -> bytes:
    command = _git_command(repository, arguments)
    environment = _git_environment()
    if max_stdout_bytes is None:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=environment,
        )
        return completed.stdout

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
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
        threading.Thread(target=read_stdout, name="aga-pins-git-stdout", daemon=True),
        threading.Thread(target=read_stderr, name="aga-pins-git-stderr", daemon=True),
    )
    for reader in readers:
        reader.start()
    try:
        return_code = process.wait(timeout=_GIT_TIMEOUT_SECONDS)
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
        raise GitOutputLimitExceeded("Git output exceeds pin verification limit")
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


def _full_head(repository: Path) -> str:
    value = run_git(
        repository,
        "rev-parse",
        "--verify",
        "--end-of-options",
        "HEAD^{commit}",
    ).decode("ascii", errors="strict").strip()
    if COMMIT_RE.fullmatch(value) is None:
        raise ValueError("HEAD did not resolve to a full commit ID")
    return value


def _require_exact_worktree(repository: Path) -> None:
    bare = run_git(repository, "rev-parse", "--is-bare-repository").decode(
        "ascii", errors="strict"
    ).strip()
    if bare != "false":
        raise ValueError("bare repository is not a checkout")
    top = Path(
        run_git(repository, "rev-parse", "--show-toplevel")
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    git_directory = Path(
        run_git(repository, "rev-parse", "--absolute-git-dir")
        .decode("utf-8", errors="strict")
        .strip()
    ).resolve(strict=True)
    if top != repository.resolve(strict=True) or not stat.S_ISDIR(
        git_directory.lstat().st_mode
    ):
        raise ValueError("checkout path is not its exact Git worktree root")


def _real_checkout_path(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or relative != path.as_posix()
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("checkout path is not a safe relative POSIX path")
    current = root
    for part in path.parts:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("checkout path cannot contain symbolic links")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("checkout path component is not a real directory")
    return current


def _checkout_is_dirty(repository: Path, expected_commit: str) -> bool:
    try:
        assert_clean_checkout(
            repository,
            expected_commit,
            lambda arguments, cap: run_git(
                repository,
                *arguments,
                max_stdout_bytes=cap,
            ),
        )
    except (CheckoutCleanlinessError, GitOutputLimitExceeded):
        return True
    return False


def main() -> int:
    errors: list[str] = []
    modules_path = ROOT / ".gitmodules"
    parser = configparser.ConfigParser(interpolation=None)
    if not modules_path.is_file():
        errors.append(".gitmodules is missing")
    else:
        parser.read(modules_path, encoding="utf-8")

    root_head: str | None = None
    try:
        _require_exact_worktree(ROOT)
        root_head = _full_head(ROOT)
    except (
        OSError,
        UnicodeError,
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        errors.append(f"project root is not an exact committed Git worktree ({exc})")

    for pin in PINS:
        section = f'submodule "{pin.name}"'
        if not parser.has_section(section):
            errors.append(f"missing {section} in .gitmodules")
        else:
            if parser.get(section, "path", fallback="") != pin.path:
                errors.append(f"{pin.name}: unexpected path")
            if parser.get(section, "url", fallback="") != pin.url:
                errors.append(f"{pin.name}: unexpected URL")
            if parser.has_option(section, "branch"):
                errors.append(f"{pin.name}: branch tracking is forbidden")

        if root_head is not None:
            try:
                record = run_git(
                    ROOT,
                    "ls-tree",
                    "-z",
                    "--full-tree",
                    root_head,
                    "--",
                    f":(literal){pin.path}",
                )
            except (
                OSError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ) as exc:
                errors.append(f"{pin.path}: cannot read root gitlink ({exc})")
            else:
                expected = f"160000 commit {pin.commit}\t{pin.path}\0".encode("utf-8")
                if record != expected:
                    errors.append(f"{pin.path}: root tree does not contain the exact pinned gitlink")

        try:
            checkout = _real_checkout_path(ROOT, pin.path)
        except (OSError, ValueError) as exc:
            errors.append(f"{pin.path}: checkout path is unsafe or missing ({exc})")
            continue
        try:
            _require_exact_worktree(checkout)
            actual = _full_head(checkout)
        except (
            OSError,
            UnicodeError,
            ValueError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            errors.append(f"{pin.path}: not an initialized Git checkout ({exc})")
            continue
        if actual != pin.commit:
            errors.append(f"{pin.path}: expected {pin.commit}, got {actual}")

        try:
            dirty = _checkout_is_dirty(checkout, pin.commit)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{pin.path}: cannot read status ({exc})")
        else:
            if dirty:
                errors.append(f"{pin.path}: project-owned changes modified the upstream tree")

    if errors:
        for error in errors:
            print(f"PIN ERROR: {error}", file=sys.stderr)
        return 1
    for pin in PINS:
        print(f"PIN OK: {pin.path} @ {pin.commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
