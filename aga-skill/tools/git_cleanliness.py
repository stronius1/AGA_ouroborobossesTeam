# -*- coding: utf-8 -*-
"""Filter-safe, bounded verification of a Git-clean pinned checkout.

The original repository is queried only for immutable tree/index metadata and
its object directory. Worktree comparison runs with a temporary, configless
Git directory and index, so repository-local clean/smudge filters, hooks and
fsmonitor commands cannot execute. Untracked files covered by standard Git
ignore rules are permitted, matching ordinary ``git status`` semantics.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from typing import Callable, Sequence


GitMetadataReader = Callable[[Sequence[str], int], bytes]


@dataclass(frozen=True)
class CheckoutCleanlinessLimits:
    max_metadata_bytes: int = 16_777_216
    max_status_bytes: int = 4_096
    max_files: int = 20_000
    max_file_bytes: int = 67_108_864
    max_total_bytes: int = 1_073_741_824
    max_path_bytes: int = 4_096
    max_depth: int = 64
    git_timeout_seconds: int = 30


DEFAULT_CLEANLINESS_LIMITS = CheckoutCleanlinessLimits()
_STDERR_MAX_BYTES = 4_096


class CheckoutCleanlinessError(RuntimeError):
    """The checkout cannot be proven clean without executing repository config."""


class CheckoutDirtyError(CheckoutCleanlinessError):
    """The pinned tree, index, or worktree differ."""


def _safe_path(raw: bytes, limits: CheckoutCleanlinessLimits) -> str:
    if not raw or len(raw) > limits.max_path_bytes:
        raise CheckoutCleanlinessError("Git path is empty or exceeds the path limit")
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CheckoutCleanlinessError("Git path is not UTF-8") from exc
    path = PurePosixPath(decoded)
    if (
        path.is_absolute()
        or decoded != path.as_posix()
        or "\\" in decoded
        or any(character in decoded for character in ("\x00", "\n", "\r", "\t"))
        or any(part in {"", ".", ".."} or part.casefold() == ".git" for part in path.parts)
        or len(path.parts) > limits.max_depth
    ):
        raise CheckoutCleanlinessError("Git path is unsafe")
    return decoded


def _nul_records(raw: bytes) -> list[bytes]:
    records = raw.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    if any(not record for record in records):
        raise CheckoutCleanlinessError("Git emitted an empty metadata record")
    return records


def _tree_entries(
    raw: bytes, expected_oid_bytes: int, limits: CheckoutCleanlinessLimits
) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    total_bytes = 0
    for record in _nul_records(raw):
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id, raw_size = metadata.split()
        except ValueError as exc:
            raise CheckoutCleanlinessError("Git emitted malformed tree metadata") from exc
        path = _safe_path(raw_path, limits)
        if path in entries:
            raise CheckoutCleanlinessError("Git tree contains a duplicate path")
        if mode == b"160000" or object_type == b"commit":
            raise CheckoutCleanlinessError("nested Git gitlinks are not supported")
        if mode not in {b"100644", b"100755", b"120000"} or object_type != b"blob":
            raise CheckoutCleanlinessError("Git tree contains an unsafe entry mode")
        try:
            object_id_text = object_id.decode("ascii", errors="strict")
            size = int(raw_size.decode("ascii", errors="strict"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise CheckoutCleanlinessError("Git tree metadata is not canonical") from exc
        if (
            len(object_id_text) != expected_oid_bytes
            or any(character not in "0123456789abcdef" for character in object_id_text)
            or size < 0
            or size > limits.max_file_bytes
        ):
            raise CheckoutCleanlinessError("Git blob metadata exceeds integrity limits")
        total_bytes += size
        if total_bytes > limits.max_total_bytes:
            raise CheckoutCleanlinessError("Git tree exceeds the aggregate byte limit")
        entries[path] = (mode.decode("ascii"), object_id_text)
        if len(entries) > limits.max_files:
            raise CheckoutCleanlinessError("Git tree exceeds the file-count limit")
    return entries


def _index_entries(
    raw: bytes, expected_oid_bytes: int, limits: CheckoutCleanlinessLimits
) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    for record in _nul_records(raw):
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_id, stage = metadata.split()
        except ValueError as exc:
            raise CheckoutCleanlinessError("Git emitted malformed index metadata") from exc
        path = _safe_path(raw_path, limits)
        try:
            mode_text = mode.decode("ascii", errors="strict")
            object_id_text = object_id.decode("ascii", errors="strict")
            stage_text = stage.decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise CheckoutCleanlinessError("Git index metadata is not ASCII") from exc
        if (
            stage_text != "0"
            or mode_text not in {"100644", "100755", "120000"}
            or len(object_id_text) != expected_oid_bytes
            or any(character not in "0123456789abcdef" for character in object_id_text)
            or path in entries
        ):
            raise CheckoutDirtyError("Git index is not the exact pinned tree")
        entries[path] = (mode_text, object_id_text)
        if len(entries) > limits.max_files:
            raise CheckoutCleanlinessError("Git index exceeds the file-count limit")
    return entries


def _validate_worktree_shapes(
    checkout: Path,
    entries: dict[str, tuple[str, str]],
    limits: CheckoutCleanlinessLimits,
) -> None:
    total_bytes = 0
    verified_directories: set[tuple[str, ...]] = {()}
    for path, (mode, _) in entries.items():
        parts = PurePosixPath(path).parts
        current = checkout
        prefix: tuple[str, ...] = ()
        try:
            for part in parts[:-1]:
                current = current / part
                prefix += (part,)
                if prefix in verified_directories:
                    continue
                info = current.lstat()
                if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    raise CheckoutDirtyError("tracked path has a non-directory parent")
                verified_directories.add(prefix)
            target = current / parts[-1]
            info = target.lstat()
        except FileNotFoundError as exc:
            raise CheckoutDirtyError("tracked path is deleted from the worktree") from exc
        except OSError as exc:
            raise CheckoutCleanlinessError("worktree metadata cannot be read safely") from exc

        if mode in {"100644", "100755"}:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise CheckoutDirtyError("tracked regular file changed type or is hard-linked")
            executable = bool(info.st_mode & 0o111)
            if executable != (mode == "100755"):
                raise CheckoutDirtyError("tracked regular file changed executable mode")
            size = info.st_size
        else:
            if not stat.S_ISLNK(info.st_mode):
                raise CheckoutDirtyError("tracked symbolic link changed type")
            try:
                size = len(os.fsencode(os.readlink(target)))
            except OSError as exc:
                raise CheckoutCleanlinessError("tracked symbolic link cannot be read") from exc
        if size < 0 or size > limits.max_file_bytes:
            raise CheckoutCleanlinessError("worktree file exceeds the per-file byte limit")
        total_bytes += size
        if total_bytes > limits.max_total_bytes:
            raise CheckoutCleanlinessError("worktree exceeds the aggregate byte limit")


def _base_git_environment() -> dict[str, str]:
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


def _run_bounded(
    command: Sequence[str],
    environment: dict[str, str],
    *,
    max_stdout_bytes: int,
    timeout_seconds: int,
) -> bytes:
    try:
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
    except OSError as exc:
        raise CheckoutCleanlinessError("configless Git process cannot start") from exc

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
                if len(stderr) > _STDERR_MAX_BYTES:
                    del stderr[:-_STDERR_MAX_BYTES]
        except BaseException as exc:  # pragma: no cover - defensive OS boundary
            stream_errors.append(exc)
            process.kill()

    readers = (
        threading.Thread(target=read_stdout, name="aga-clean-git-stdout", daemon=True),
        threading.Thread(target=read_stderr, name="aga-clean-git-stderr", daemon=True),
    )
    for reader in readers:
        reader.start()
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        for reader in readers:
            reader.join(timeout=1.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        raise CheckoutCleanlinessError("configless Git operation timed out") from exc
    for reader in readers:
        reader.join(timeout=1.0)
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    if output_exceeded.is_set():
        raise CheckoutDirtyError("configless Git output exceeds the cleanliness limit")
    if any(reader.is_alive() for reader in readers) or stream_errors:
        process.kill()
        raise CheckoutCleanlinessError("configless Git output stream failed")
    if return_code != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[-300:]
        raise CheckoutCleanlinessError(
            "configless Git operation failed" + (f": {detail}" if detail else "")
        )
    return bytes(stdout)


def _configless_worktree_status(
    checkout: Path,
    expected_commit: str,
    object_directory: Path,
    object_format: str,
    limits: CheckoutCleanlinessLimits,
) -> None:
    with tempfile.TemporaryDirectory(prefix="aga-clean-") as temporary:
        temporary_root = Path(temporary)
        shadow = temporary_root / "git"
        empty_template = temporary_root / "empty-template"
        empty_template.mkdir()
        base_environment = _base_git_environment()
        init_command = [
            "git",
            "-c",
            "core.fsmonitor=false",
            "--no-pager",
            "--no-replace-objects",
            "init",
            "--quiet",
            "--bare",
            f"--template={empty_template}",
            f"--object-format={object_format}",
            str(shadow),
        ]
        _run_bounded(
            init_command,
            base_environment,
            max_stdout_bytes=limits.max_status_bytes,
            timeout_seconds=limits.git_timeout_seconds,
        )
        environment = _base_git_environment()
        environment.update(
            {
                "GIT_DIR": str(shadow),
                "GIT_INDEX_FILE": str(temporary_root / "index"),
                "GIT_WORK_TREE": str(checkout),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(object_directory),
            }
        )
        command_prefix = [
            "git",
            "-c",
            "core.bare=false",
            "-c",
            "core.fsmonitor=false",
            "--no-pager",
            "--no-replace-objects",
        ]
        _run_bounded(
            [*command_prefix, "update-ref", "HEAD", expected_commit],
            environment,
            max_stdout_bytes=limits.max_status_bytes,
            timeout_seconds=limits.git_timeout_seconds,
        )
        _run_bounded(
            [*command_prefix, "read-tree", expected_commit],
            environment,
            max_stdout_bytes=limits.max_status_bytes,
            timeout_seconds=limits.git_timeout_seconds,
        )
        untracked = _run_bounded(
            [*command_prefix, "ls-files", "--others", "--exclude-standard", "-z"],
            environment,
            max_stdout_bytes=limits.max_status_bytes,
            timeout_seconds=limits.git_timeout_seconds,
        )
        if untracked:
            raise CheckoutDirtyError("worktree contains untracked files")
        status = _run_bounded(
            [
                *command_prefix,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=no",
                "--ignore-submodules=none",
            ],
            environment,
            max_stdout_bytes=limits.max_status_bytes,
            timeout_seconds=limits.git_timeout_seconds,
        )
        if status:
            raise CheckoutDirtyError("worktree differs from the pinned tree")


def assert_clean_checkout(
    checkout: Path,
    expected_commit: str,
    read_git_metadata: GitMetadataReader,
    *,
    limits: CheckoutCleanlinessLimits = DEFAULT_CLEANLINESS_LIMITS,
) -> None:
    """Fail unless tracked state matches ``expected_commit`` and is Git-clean.

    ``read_git_metadata`` must execute only the supplied read-only Git command
    with the supplied stdout cap. The worktree comparison itself never reads
    configuration from the checkout's Git directory. Standard ignored
    untracked files are intentionally outside this cleanliness predicate.
    """

    if any(character not in "0123456789abcdef" for character in expected_commit):
        raise CheckoutCleanlinessError("expected commit is not a full object ID")
    if len(expected_commit) == 40:
        object_format = "sha1"
    elif len(expected_commit) == 64:
        object_format = "sha256"
    else:
        raise CheckoutCleanlinessError("expected commit is not a full object ID")

    head_arguments = [
        "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}",
    ]
    try:
        head_before = read_git_metadata(head_arguments, 128).decode(
            "ascii", errors="strict"
        ).strip()
    except UnicodeDecodeError as exc:
        raise CheckoutCleanlinessError("checkout HEAD is not ASCII") from exc
    if head_before != expected_commit:
        raise CheckoutDirtyError("checkout HEAD differs from the pinned commit")
    tree_raw = read_git_metadata(
        ["ls-tree", "-r", "-z", "-l", "--full-tree", expected_commit],
        limits.max_metadata_bytes,
    )
    index_raw = read_git_metadata(
        ["ls-files", "--stage", "-z"], limits.max_metadata_bytes
    )
    tree = _tree_entries(tree_raw, len(expected_commit), limits)
    index = _index_entries(index_raw, len(expected_commit), limits)
    if index != tree:
        raise CheckoutDirtyError("Git index differs from the pinned tree")
    _validate_worktree_shapes(checkout, tree, limits)

    object_path_raw = read_git_metadata(
        ["rev-parse", "--path-format=absolute", "--git-path", "objects"],
        limits.max_path_bytes,
    )
    try:
        object_path_text = object_path_raw.decode("utf-8", errors="strict").strip()
        if (
            "\x00" in object_path_text
            or "\n" in object_path_text
            or "\r" in object_path_text
            or os.pathsep in object_path_text
        ):
            raise CheckoutCleanlinessError(
                "Git object directory is ambiguous in the alternates environment"
            )
        object_candidate = Path(object_path_text)
        if not object_candidate.is_absolute():
            raise CheckoutCleanlinessError(
                "Git object directory must be an absolute path"
            )
        object_info = object_candidate.lstat()
        object_directory = object_candidate.resolve(strict=True)
    except CheckoutCleanlinessError:
        raise
    except (UnicodeDecodeError, OSError, RuntimeError) as exc:
        raise CheckoutCleanlinessError("Git object directory is unavailable") from exc
    if not stat.S_ISDIR(object_info.st_mode):
        raise CheckoutCleanlinessError("Git object directory must be a real directory")

    _configless_worktree_status(
        checkout,
        expected_commit,
        object_directory,
        object_format,
        limits,
    )
    index_after = read_git_metadata(
        ["ls-files", "--stage", "-z"], limits.max_metadata_bytes
    )
    try:
        head_after = read_git_metadata(head_arguments, 128).decode(
            "ascii", errors="strict"
        ).strip()
    except UnicodeDecodeError as exc:
        raise CheckoutCleanlinessError("checkout HEAD is not ASCII") from exc
    if index_after != index_raw or head_after != expected_commit:
        raise CheckoutDirtyError("checkout changed during cleanliness verification")
