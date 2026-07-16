# -*- coding: utf-8 -*-
"""Trusted, read-only Git snapshots for SEAF-native architecture reviews.

``RepositorySnapshotBuilder`` deliberately treats the Git object database as
the only source of repository content.  Neither the current checkout nor a
manifest-provided list of changed files participates in a review.  The
builder resolves explicit base/head revisions to commit object IDs, obtains
the changed paths from ``git diff base head``, and copies the root manifest's
local import/context closure from the head tree into an isolated temporary
directory.

The temporary directory is suitable as the repository root for
``tools.seaf_native.DocHubImportResolver``.  A snapshot owns that directory;
call :meth:`RepositorySnapshot.close` or use it as a context manager when the
review is complete.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import os
import re
import stat
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

from tools.git_cleanliness import CheckoutCleanlinessError, assert_clean_checkout
from tools.validation import (
    ValidationError,
    safe_artifact_path,
    safe_read_artifact,
    strict_load_yaml_text,
)

try:  # One canonical revision contract is shared with the SEAF adapter.
    from tools.seaf_native import ChangedArtifact, RepositoryRevision, SourceProvenance
except ImportError:  # pragma: no cover - permits isolated use during upgrades
    @dataclass(frozen=True)
    class RepositoryRevision:  # type: ignore[no-redef]
        """Provenance for one immutable architecture repository comparison."""

        base_commit: str
        head_commit: str
        manifest_sha256: str
        archtool_commit: str
        seaf_core_commit: str
        aga_version: str
        rules_sha256: str

        def as_dict(self) -> dict[str, str]:
            return asdict(self)

    @dataclass(frozen=True)
    class SourceProvenance:  # type: ignore[no-redef]
        file: str
        pointer: str
        commit: str | None = None
        line: int | None = None
        sha256: str | None = None

        def as_dict(self) -> dict[str, Any]:
            return asdict(self)

    @dataclass(frozen=True)
    class ChangedArtifact:  # type: ignore[no-redef]
        path: str
        status: str
        sha256: str | None
        source_ref: SourceProvenance
        changed_pointers: tuple[str, ...] = ()

        def as_dict(self) -> dict[str, Any]:
            return asdict(self)


DEFAULT_ARCHTOOL_COMMIT = "83c82ab1673f1245b499c26b82d507fa602a11d6"
DEFAULT_SEAF_CORE_COMMIT = "60ce335832d2734814c020306a85d1e8b12cf67b"
DEFAULT_ARCHTOOL_PATH = "seaf-archtool-core"
DEFAULT_SEAF_CORE_PATH = "architecture/vendor/seaf-core"
FIXTURE_COMMIT = "0" * 40
DEPENDENCY_MODES = frozenset({"verified", "fixture"})
DEFAULT_MAX_FILE_BYTES = 1_048_576
DEFAULT_MAX_TOTAL_BYTES = 16_777_216
DEFAULT_MAX_FILES = 512
DEFAULT_MAX_DEPTH = 40
DEFAULT_GIT_TIMEOUT_SECONDS = 30

_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_REVISION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@+~^/-]{0,255}\Z")
_REMOTE_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_YAML_EXTENSIONS = frozenset({".yaml", ".yml"})
_MATERIALIZED_EXTENSIONS = frozenset(
    {".yaml", ".yml", ".json", ".md", ".puml", ".plantuml", ".mmd", ".drawio", ".txt"}
)
_CLOSURE_REQUIRED_EXTENSIONS = _YAML_EXTENSIONS | frozenset(
    {".puml", ".plantuml", ".mmd", ".drawio"}
)
_CONTEXT_REFERENCE_KEYS = frozenset(
    {"artifact", "context_files", "file", "path", "source", "template", "uml", "$ref"}
)
_ENTITY_SECTIONS = (
    "components",
    "seaf.app.integrations",
    "seaf.change.adr",
    "contexts",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate_positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _sanitised_git_environment() -> dict[str, str]:
    """Build a deterministic Git environment without caller-controlled GIT_* state."""

    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update({
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
    })
    return environment


def rules_directory_sha256(
    root: str | os.PathLike[str],
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> str:
    """Hash one safe YAML rules tree using the snapshot provenance framing."""

    directory = Path(root)
    if directory.is_symlink() or not directory.is_dir():
        raise ValidationError(
            "rules directory must be a real directory",
            path=directory,
            code="unsafe_rules_directory",
        )
    files = sorted(
        path for path in directory.rglob("*") if path.suffix.lower() in _YAML_EXTENSIONS
    )
    if not files:
        raise ValidationError(
            "rules directory contains no YAML rules",
            path=directory,
            code="rules_unavailable",
        )
    digest = hashlib.sha256()
    total = 0
    for path in files:
        relative = path.relative_to(directory).as_posix()
        try:
            info = path.lstat()
        except OSError as exc:
            raise ValidationError(
                "cannot inspect rules file", path=path, code="rules_unavailable"
            ) from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or any(parent.is_symlink() for parent in path.parents if parent != directory.parent)
        ):
            raise ValidationError(
                "rules files must be regular, non-linked files",
                path=path,
                code="unsafe_rules_file",
            )
        if info.st_size > max_file_bytes:
            raise ValidationError(
                "rules file exceeds byte limit", path=path, code="rules_too_large"
            )
        raw = path.read_bytes()
        total += len(raw)
        if total > max_total_bytes:
            raise ValidationError(
                "rules directory exceeds byte limit", path=directory, code="rules_too_large"
            )
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _validate_commit_pin(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not _COMMIT_RE.fullmatch(value.lower()):
        raise ValidationError(
            f"{field_name} must be a full Git commit SHA",
            field=field_name,
            code="invalid_commit_pin",
        )
    return value.lower()


def _validate_revision(value: str, *, field_name: str) -> str:
    """Accept ordinary refs/revision expressions without option/path syntax."""

    if (
        not isinstance(value, str)
        or not _REVISION_RE.fullmatch(value)
        or value.startswith("-")
        or ".." in value
        or "@{" in value
        or "//" in value
        or value.endswith(("/", ".", ".lock"))
    ):
        raise ValidationError(
            f"Git {field_name} revision is unsafe",
            field=field_name,
            code="unsafe_revision",
        )
    return value


def _normalise_repository_path(value: str | os.PathLike[str], *, field_name: str) -> str:
    """Return one canonical repository-relative POSIX path."""

    if not isinstance(value, (str, os.PathLike)):
        raise ValidationError("repository path must be text", field=field_name, code="invalid_path")
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or len(raw) > 4096:
        raise ValidationError("repository path is empty or too long", field=field_name,
                              code="invalid_path")
    if raw != raw.strip() or any(character in raw for character in ("\x00", "\n", "\r", "\t")):
        raise ValidationError("repository path contains unsafe characters", path=raw,
                              field=field_name, code="invalid_path")
    if "\\" in raw:
        raise ValidationError("repository paths must use POSIX separators", path=raw,
                              field=field_name, code="invalid_path")
    windows = PureWindowsPath(raw)
    if raw.startswith("/") or windows.is_absolute() or windows.drive:
        raise ValidationError("absolute repository path is not allowed", path=raw,
                              field=field_name, code="path_absolute")
    parts = raw.split("/")
    if not parts or any(part in {"", "."} for part in parts):
        raise ValidationError("repository path is not canonical", path=raw,
                              field=field_name, code="invalid_path")
    if any(part == ".." for part in parts):
        raise ValidationError("parent traversal is not allowed", path=raw,
                              field=field_name, code="path_traversal")
    if any(part == ".git" for part in parts):
        raise ValidationError("Git administrative paths are not review artifacts", path=raw,
                              field=field_name, code="invalid_path")
    return PurePosixPath(*parts).as_posix()


def _normalise_reference(reference: str, *, parent: str, field_name: str) -> str:
    """Resolve a local manifest reference without permitting traversal."""

    if not isinstance(reference, str):
        raise ValidationError("manifest reference must be a string", field=field_name,
                              code="invalid_import")
    if _REMOTE_RE.match(reference):
        raise ValidationError(
            "remote imports are not materialized implicitly",
            path=reference,
            field=field_name,
            code="remote_import_requires_pin",
        )
    if "#" in reference or "?" in reference:
        raise ValidationError("URI fragments and queries are not local file references",
                              path=reference, field=field_name, code="invalid_import")
    # Reject ``..`` before joining even if it would remain inside the root.
    normalised = _normalise_repository_path(reference, field_name=field_name)
    base = PurePosixPath(parent).parent
    combined = normalised if str(base) == "." else (base / normalised).as_posix()
    return _normalise_repository_path(combined, field_name=field_name)


def _revision_dict(revision: RepositoryRevision) -> dict[str, Any]:
    method = getattr(revision, "as_dict", None)
    if callable(method):
        return dict(method())
    if is_dataclass(revision):  # pragma: no cover - compatibility with older adapters
        return asdict(revision)
    return {
        name: getattr(revision, name)
        for name in (
            "base_commit", "head_commit", "manifest_sha256", "archtool_commit",
            "seaf_core_commit", "aga_version", "rules_sha256",
        )
    }


@dataclass(frozen=True)
class _TreeEntry:
    path: str
    mode: str
    object_type: str
    object_id: str
    size: int


@dataclass(frozen=True)
class _GitChange:
    path: str
    status: str


@dataclass(frozen=True)
class _TrustedDependency:
    path: str
    checkout: Path
    commit: str
    checkout_identity: tuple[int, int]
    git_directory: Path
    git_directory_identity: tuple[int, int]


@dataclass(frozen=True)
class TrustedDependencyProvenance:
    """Pin and exact materialized-closure hash for one trusted Git dependency."""

    path: str
    commit: str
    closure_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "commit": self.commit,
            "closure_sha256": self.closure_sha256,
        }


@dataclass(frozen=True)
class RepositorySnapshot:
    """An isolated materialization of one deterministic head revision."""

    root: Path = field(compare=False)
    manifest_path: Path = field(compare=False)
    manifest_relative_path: str
    changed_paths: tuple[str, ...]
    changed_artifacts: tuple[ChangedArtifact, ...]
    context_paths: tuple[str, ...]
    materialized_paths: tuple[str, ...]
    review_scope: str
    ignored_out_of_scope_paths: tuple[str, ...]
    dependency_verification: str
    dependency_provenance: tuple[TrustedDependencyProvenance, ...]
    materialized_hashes: tuple[tuple[str, str], ...]
    revision: RepositoryRevision
    content_sha256: str
    _max_file_bytes: int = field(repr=False, compare=False)
    _temporary_directory: tempfile.TemporaryDirectory[str] = field(
        repr=False, compare=False
    )

    @property
    def staging_root(self) -> Path:
        return self.root

    @property
    def provenance(self) -> dict[str, Any]:
        result = _revision_dict(self.revision)
        result["trusted_dependencies"] = {
            dependency.path: {
                "commit": dependency.commit,
                "closure_sha256": dependency.closure_sha256,
            }
            for dependency in self.dependency_provenance
        }
        result["review_scope"] = self.review_scope
        result["ignored_out_of_scope_paths"] = list(self.ignored_out_of_scope_paths)
        result["dependency_verification"] = self.dependency_verification
        return result

    @property
    def review_provenance(self) -> dict[str, Any]:
        return self.provenance

    @property
    def base_commit(self) -> str:
        return self.revision.base_commit

    @property
    def head_commit(self) -> str:
        return self.revision.head_commit

    @property
    def manifest_sha256(self) -> str:
        return self.revision.manifest_sha256

    @property
    def rules_sha256(self) -> str:
        return self.revision.rules_sha256

    @property
    def changed_statuses(self) -> dict[str, str]:
        """Deterministic path-to-Git-status mapping used by canonical adaptation."""

        return {artifact.path: artifact.status for artifact in self.changed_artifacts}

    def as_dict(self) -> dict[str, Any]:
        """Return a deterministic description; the random staging path is omitted."""

        return {
            "manifest_path": self.manifest_relative_path,
            "changed_paths": list(self.changed_paths),
            "changed_artifacts": [artifact.as_dict() for artifact in self.changed_artifacts],
            "context_paths": list(self.context_paths),
            "materialized_paths": list(self.materialized_paths),
            "review_scope": self.review_scope,
            "ignored_out_of_scope_paths": list(self.ignored_out_of_scope_paths),
            "materialized_hashes": {path: digest for path, digest in self.materialized_hashes},
            "revision": self.provenance,
            "content_sha256": self.content_sha256,
        }

    def read_materialized_text(
        self,
        path: str,
        *,
        allowed_extensions: set[str] | frozenset[str] = _MATERIALIZED_EXTENSIONS,
    ) -> str:
        """Read one staged file only when it still matches the captured Git blob."""

        expected = dict(self.materialized_hashes).get(path)
        if expected is None:
            raise ValidationError(
                "path is not part of the captured snapshot",
                path=path,
                code="snapshot_file_not_found",
            )
        text = safe_read_artifact(
            self.root,
            path,
            allowed_extensions=allowed_extensions,
            max_bytes=self._max_file_bytes,
            reject_symlinks=True,
            reject_hardlinks=True,
        )
        if _sha256(text.encode("utf-8")) != expected:
            raise ValidationError(
                "materialized snapshot file changed after capture",
                path=path,
                code="snapshot_integrity_mismatch",
            )
        return text

    def assert_integrity(self) -> None:
        """Revalidate every materialized byte sequence against captured hashes."""

        for path, _digest in self.materialized_hashes:
            self.read_materialized_text(path)

    def resolve(self, **limits: Any) -> Any:
        """Resolve this staging tree with the canonical SEAF-native resolver."""

        try:
            from tools.seaf_native import DocHubImportResolver
        except ImportError as exc:  # pragma: no cover - only for partial installations
            raise RuntimeError("tools.seaf_native is unavailable") from exc
        self.assert_integrity()
        if "trusted_dependencies" in limits:
            raise TypeError("trusted_dependencies is derived from snapshot provenance")
        limits["trusted_dependencies"] = {
            dependency.path: dependency.commit for dependency in self.dependency_provenance
        }
        workspace = DocHubImportResolver(self.root, **limits).resolve(
            self.manifest_relative_path
        )
        self.assert_integrity()
        return workspace

    def close(self) -> None:
        self._temporary_directory.cleanup()

    def __enter__(self) -> "RepositorySnapshot":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


class RepositorySnapshotBuilder:
    """Build a bounded SEAF review snapshot from explicit Git commits.

    ``repository`` is canonicalised once and its directory identity is checked
    before every Git invocation.  ``base_revision`` and ``head_revision`` may
    be full SHAs or conservative local Git revision expressions; both are
    immediately resolved to commit object IDs during :meth:`build`.
    """

    def __init__(
        self,
        repository: str | os.PathLike[str],
        base_revision: str | None = None,
        head_revision: str | None = None,
        *,
        base: str | None = None,
        head: str | None = None,
        manifest_path: str = "dochub.yaml",
        scope_prefix: str | None = None,
        archtool_commit: str | None = None,
        seaf_core_commit: str | None = None,
        dependency_mode: str = "verified",
        trusted_dependencies: Mapping[str, Mapping[str, Any]] | None = None,
        aga_version: str | None = None,
        rules_dir: str | os.PathLike[str] | None = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
        max_depth: int = DEFAULT_MAX_DEPTH,
        git_timeout_seconds: int = DEFAULT_GIT_TIMEOUT_SECONDS,
    ) -> None:
        try:
            resolved_repository = Path(repository).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValidationError("repository does not exist or cannot be resolved",
                                  path=repository, code="repository_not_found") from exc
        info = resolved_repository.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValidationError("repository path must be a directory",
                                  path=resolved_repository, code="invalid_repository")

        self._repository = resolved_repository
        self._repository_identity = (info.st_dev, info.st_ino)
        self._git_directory: Path | None = None
        self._git_directory_identity: tuple[int, int] | None = None
        self._base_revision = _validate_revision(
            self._coalesce_revision(base_revision, base, name="base"), field_name="base"
        )
        self._head_revision = _validate_revision(
            self._coalesce_revision(head_revision, head, name="head"), field_name="head"
        )
        self._manifest_path = _normalise_repository_path(
            manifest_path, field_name="manifest_path"
        )
        if PurePosixPath(self._manifest_path).suffix.lower() not in _YAML_EXTENSIONS:
            raise ValidationError("root manifest must be YAML", path=self._manifest_path,
                                  field="manifest_path", code="invalid_manifest")
        manifest_parent = PurePosixPath(self._manifest_path).parent.as_posix()
        derived_scope = "" if manifest_parent == "." else f"{manifest_parent}/"
        if scope_prefix is None:
            self._scope_prefix = derived_scope
        elif scope_prefix == "":
            self._scope_prefix = ""
        else:
            normalised_scope = _normalise_repository_path(
                scope_prefix.rstrip("/"), field_name="scope_prefix"
            )
            self._scope_prefix = f"{normalised_scope}/"
        if self._scope_prefix and not self._manifest_path.startswith(self._scope_prefix):
            raise ValidationError(
                "root manifest must be inside the trusted review scope",
                path=self._manifest_path,
                field="scope_prefix",
                code="invalid_review_scope",
            )
        if not isinstance(dependency_mode, str) or dependency_mode not in DEPENDENCY_MODES:
            raise ValidationError(
                "dependency_mode must be verified or fixture",
                field="dependency_mode",
                code="invalid_dependency_mode",
            )
        self._dependency_mode = dependency_mode
        self._archtool_commit = _validate_commit_pin(
            archtool_commit
            or (DEFAULT_ARCHTOOL_COMMIT if dependency_mode == "verified" else FIXTURE_COMMIT),
            field_name="archtool_commit",
        )
        self._seaf_core_commit = _validate_commit_pin(
            seaf_core_commit
            or (DEFAULT_SEAF_CORE_COMMIT if dependency_mode == "verified" else FIXTURE_COMMIT),
            field_name="seaf_core_commit",
        )
        self._aga_version = self._load_aga_version(aga_version)
        self._rules_dir = Path(rules_dir).expanduser().resolve(strict=True) if rules_dir else (
            Path(__file__).resolve().parent.parent / "rules"
        )
        self._max_file_bytes = _validate_positive_limit("max_file_bytes", max_file_bytes)
        self._max_total_bytes = _validate_positive_limit("max_total_bytes", max_total_bytes)
        self._max_files = _validate_positive_limit("max_files", max_files)
        self._max_depth = _validate_positive_limit("max_depth", max_depth)
        self._git_timeout_seconds = _validate_positive_limit(
            "git_timeout_seconds", git_timeout_seconds
        )
        self._initialise_git_repository()
        self._trusted_dependencies = self._configure_dependencies(trusted_dependencies or {})
        self._validate_dependency_provenance_config()

    @staticmethod
    def _coalesce_revision(primary: str | None, alias: str | None, *, name: str) -> str:
        if primary is None and alias is None:
            raise ValidationError(f"explicit {name} revision is required", field=name,
                                  code="revision_required")
        if primary is not None and alias is not None and primary != alias:
            raise ValidationError(f"conflicting {name} revisions", field=name,
                                  code="conflicting_revision")
        value = primary if primary is not None else alias
        assert value is not None
        return value

    @staticmethod
    def _load_aga_version(configured: str | None) -> str:
        if configured is not None:
            if not isinstance(configured, str) or not configured.strip() or "\n" in configured:
                raise ValidationError("AGA version is unsafe", field="aga_version",
                                      code="invalid_version")
            return configured.strip()
        version_path = Path(__file__).resolve().parent.parent / "VERSION"
        try:
            value = version_path.read_text(encoding="utf-8").strip()
        except OSError as exc:  # pragma: no cover - broken package installation
            raise ValidationError("AGA VERSION is unavailable", path=version_path,
                                  code="version_unavailable") from exc
        if not value:
            raise ValidationError("AGA VERSION is empty", path=version_path,
                                  code="invalid_version")
        return value

    @property
    def repository(self) -> Path:
        return self._repository

    @property
    def base_revision(self) -> str:
        return self._base_revision

    @property
    def head_revision(self) -> str:
        return self._head_revision

    @property
    def manifest_path(self) -> str:
        return self._manifest_path

    @property
    def trusted_dependencies(self) -> Mapping[str, Mapping[str, Any]]:
        return {
            dependency.path: {
                "checkout": dependency.checkout,
                "commit": dependency.commit,
            }
            for dependency in self._trusted_dependencies
        }

    @property
    def dependency_mode(self) -> str:
        return self._dependency_mode

    def _validate_dependency_provenance_config(self) -> None:
        """Require both official gitlinks before production pins are asserted."""

        if self._dependency_mode == "fixture":
            return
        configured = {dependency.path: dependency.commit for dependency in self._trusted_dependencies}
        required = {
            DEFAULT_ARCHTOOL_PATH: self._archtool_commit,
            DEFAULT_SEAF_CORE_PATH: self._seaf_core_commit,
        }
        if any(configured.get(path) != commit for path, commit in required.items()):
            raise ValidationError(
                "verified dependency mode requires pinned ArchTool and seaf-core gitlinks",
                field="trusted_dependencies",
                code="dependency_provenance_unverified",
            )

    def _check_repository_identity(self) -> None:
        try:
            info = self._repository.lstat()
        except OSError as exc:
            raise ValidationError("repository path changed during snapshot",
                                  path=self._repository, code="repository_changed") from exc
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self._repository_identity:
            raise ValidationError("repository path changed during snapshot",
                                  path=self._repository, code="repository_changed")
        if self._git_directory is not None:
            try:
                git_info = self._git_directory.lstat()
            except OSError as exc:
                raise ValidationError("Git directory changed during snapshot",
                                      path=self._git_directory,
                                      code="repository_changed") from exc
            if ((git_info.st_dev, git_info.st_ino) != self._git_directory_identity
                    or not stat.S_ISDIR(git_info.st_mode)):
                raise ValidationError("Git directory changed during snapshot",
                                      path=self._git_directory,
                                      code="repository_changed")

    def _run_git(
        self,
        repository: Path,
        arguments: Sequence[str],
        *,
        max_stdout_bytes: int | None = None,
    ) -> bytes:
        command = [
            "git", "-c", f"safe.directory={repository}", "--no-pager",
            "-c", "core.fsmonitor=false", "--no-replace-objects",
            "-C", str(repository),
            *arguments,
        ]
        environment = _sanitised_git_environment()
        if max_stdout_bytes is not None:
            return self._run_git_streamed(
                command,
                environment,
                repository=repository,
                max_stdout_bytes=max_stdout_bytes,
            )
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=self._git_timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValidationError("Git operation timed out", path=repository,
                                  code="snapshot_git_timeout") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            stderr = getattr(exc, "stderr", b"") or b""
            detail = stderr.decode("utf-8", errors="replace").strip()[-300:]
            message = "Git operation failed" + (f": {detail}" if detail else "")
            raise ValidationError(message, path=repository,
                                  code="snapshot_git_error") from exc
        return completed.stdout

    def _run_git_streamed(
        self,
        command: Sequence[str],
        environment: Mapping[str, str],
        *,
        repository: Path,
        max_stdout_bytes: int,
    ) -> bytes:
        """Read Git output concurrently and kill it as soon as the cap is crossed."""

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=dict(environment),
            )
        except OSError as exc:
            raise ValidationError(
                "Git operation failed", path=repository, code="snapshot_git_error"
            ) from exc

        stdout = bytearray()
        stderr = bytearray()
        output_exceeded = threading.Event()
        stream_errors: list[BaseException] = []

        def read_stdout() -> None:
            try:
                assert process.stdout is not None
                while chunk := process.stdout.read(65_536):
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
                    if len(stderr) > 4_096:
                        del stderr[:-4_096]
            except BaseException as exc:  # pragma: no cover - defensive OS boundary
                stream_errors.append(exc)
                process.kill()

        readers = (
            threading.Thread(target=read_stdout, name="aga-git-stdout", daemon=True),
            threading.Thread(target=read_stderr, name="aga-git-stderr", daemon=True),
        )
        for reader in readers:
            reader.start()
        try:
            return_code = process.wait(timeout=self._git_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            for reader in readers:
                reader.join(timeout=1.0)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            raise ValidationError(
                "Git operation timed out", path=repository, code="snapshot_git_timeout"
            ) from exc
        for reader in readers:
            reader.join(timeout=1.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        if output_exceeded.is_set():
            raise ValidationError(
                "Git changed-path output exceeds snapshot limit",
                code="snapshot_too_large",
            )
        if any(reader.is_alive() for reader in readers) or stream_errors:
            process.kill()
            raise ValidationError(
                "Git output stream failed", path=repository, code="snapshot_git_error"
            )
        if return_code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[-300:]
            message = "Git operation failed" + (f": {detail}" if detail else "")
            raise ValidationError(
                message, path=repository, code="snapshot_git_error"
            )
        return bytes(stdout)

    def _git(self, arguments: Sequence[str]) -> bytes:
        self._check_repository_identity()
        return self._run_git(self._repository, arguments)

    def _git_bounded(
        self, arguments: Sequence[str], *, max_stdout_bytes: int
    ) -> bytes:
        self._check_repository_identity()
        return self._run_git(
            self._repository,
            arguments,
            max_stdout_bytes=max_stdout_bytes,
        )

    @staticmethod
    def _real_directory(value: str | os.PathLike[str], *, field_name: str) -> tuple[Path, tuple[int, int]]:
        if not isinstance(value, (str, os.PathLike)):
            raise ValidationError("dependency checkout must be a path", field=field_name,
                                  code="invalid_dependency_checkout")
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        # Inspect the lexical path before resolve: accepting a symlink and then
        # retaining only its target would make the configured checkout mutable.
        current = Path(candidate.anchor)
        try:
            for part in candidate.parts[1:]:
                current = current / part
                info = current.lstat()
                if stat.S_ISLNK(info.st_mode):
                    raise ValidationError("dependency checkout cannot contain symlinks",
                                          path=current, field=field_name,
                                          code="dependency_checkout_symlink")
            resolved = candidate.resolve(strict=True)
            info = resolved.lstat()
        except ValidationError:
            raise
        except (OSError, RuntimeError) as exc:
            raise ValidationError("dependency checkout is unavailable", path=candidate,
                                  field=field_name,
                                  code="invalid_dependency_checkout") from exc
        if not stat.S_ISDIR(info.st_mode):
            raise ValidationError("dependency checkout must be a real directory",
                                  path=resolved, field=field_name,
                                  code="invalid_dependency_checkout")
        return resolved, (info.st_dev, info.st_ino)

    def _configure_dependencies(
        self, configured: Mapping[str, Mapping[str, Any]]
    ) -> tuple[_TrustedDependency, ...]:
        if not isinstance(configured, Mapping):
            raise ValidationError("trusted_dependencies must be a mapping",
                                  field="trusted_dependencies", code="invalid_dependency")
        dependencies: list[_TrustedDependency] = []
        for raw_path, raw_config in configured.items():
            path = _normalise_repository_path(
                raw_path, field_name=f"trusted_dependencies[{raw_path!r}]"
            )
            if not isinstance(raw_config, Mapping) or set(raw_config) != {"checkout", "commit"}:
                raise ValidationError(
                    "dependency config requires exactly checkout and commit",
                    path=path,
                    field="trusted_dependencies",
                    code="invalid_dependency",
                )
            checkout, checkout_identity = self._real_directory(
                raw_config["checkout"], field_name=f"trusted_dependencies.{path}.checkout"
            )
            commit = _validate_commit_pin(
                raw_config["commit"], field_name=f"trusted_dependencies.{path}.commit"
            )
            try:
                git_directory = Path(self._run_git(
                    checkout, ["rev-parse", "--absolute-git-dir"]
                ).decode("utf-8", errors="strict").strip()).resolve(strict=True)
                top = Path(self._run_git(
                    checkout, ["rev-parse", "--show-toplevel"]
                ).decode("utf-8", errors="strict").strip()).resolve(strict=True)
            except (UnicodeDecodeError, OSError, RuntimeError) as exc:
                raise ValidationError("dependency checkout is not a Git worktree",
                                      path=checkout, code="invalid_dependency_checkout") from exc
            git_info = git_directory.lstat()
            if top != checkout or not stat.S_ISDIR(git_info.st_mode):
                raise ValidationError("dependency checkout must be its Git worktree root",
                                      path=checkout, code="invalid_dependency_checkout")
            dependencies.append(_TrustedDependency(
                path=path,
                checkout=checkout,
                commit=commit,
                checkout_identity=checkout_identity,
                git_directory=git_directory,
                git_directory_identity=(git_info.st_dev, git_info.st_ino),
            ))
        dependencies.sort(key=lambda dependency: dependency.path)
        for index, left in enumerate(dependencies):
            for right in dependencies[index + 1:]:
                if right.path.startswith(left.path + "/"):
                    raise ValidationError("trusted dependency paths cannot overlap",
                                          path=right.path, code="dependency_path_overlap")
        return tuple(dependencies)

    def _check_dependency_identity(self, dependency: _TrustedDependency) -> None:
        try:
            checkout_info = dependency.checkout.lstat()
            git_info = dependency.git_directory.lstat()
        except OSError as exc:
            raise ValidationError("dependency checkout changed during snapshot",
                                  path=dependency.checkout,
                                  code="dependency_checkout_changed") from exc
        if (
            not stat.S_ISDIR(checkout_info.st_mode)
            or (checkout_info.st_dev, checkout_info.st_ino) != dependency.checkout_identity
            or not stat.S_ISDIR(git_info.st_mode)
            or (git_info.st_dev, git_info.st_ino) != dependency.git_directory_identity
        ):
            raise ValidationError("dependency checkout changed during snapshot",
                                  path=dependency.checkout,
                                  code="dependency_checkout_changed")

    def _dependency_git(
        self,
        dependency: _TrustedDependency,
        arguments: Sequence[str],
        *,
        max_stdout_bytes: int | None = None,
    ) -> bytes:
        self._check_dependency_identity(dependency)
        return self._run_git(
            dependency.checkout,
            arguments,
            max_stdout_bytes=max_stdout_bytes,
        )

    def _initialise_git_repository(self) -> None:
        try:
            git_dir_text = self._git(["rev-parse", "--absolute-git-dir"]).decode(
                "utf-8", errors="strict"
            ).strip()
            bare = self._git(["rev-parse", "--is-bare-repository"]).decode(
                "ascii", errors="strict"
            ).strip()
        except UnicodeDecodeError as exc:
            raise ValidationError("Git returned a non-text repository path",
                                  path=self._repository, code="invalid_repository") from exc
        git_dir = Path(git_dir_text).resolve(strict=True)
        git_info = git_dir.lstat()
        if not stat.S_ISDIR(git_info.st_mode):
            raise ValidationError("Git directory is not a directory", path=git_dir,
                                  code="invalid_repository")
        if bare not in {"true", "false"}:
            raise ValidationError("Git repository type is unknown", path=self._repository,
                                  code="invalid_repository")
        if bare != "false":
            raise ValidationError("bare repositories are not review worktrees",
                                  path=self._repository, code="invalid_repository")
        try:
            top = Path(self._git(["rev-parse", "--show-toplevel"]).decode(
                "utf-8", errors="strict"
            ).strip()).resolve(strict=True)
        except UnicodeDecodeError as exc:
            raise ValidationError("Git worktree root is not UTF-8",
                                  path=self._repository,
                                  code="invalid_repository") from exc
        if top != self._repository:
            raise ValidationError("repository path must be the Git root", path=self._repository,
                                  code="repository_root_required")
        self._git_directory = git_dir
        self._git_directory_identity = (git_info.st_dev, git_info.st_ino)

    def _resolve_commit(self, revision: str, *, field_name: str) -> str:
        try:
            output = self._git([
                "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}",
            ]).decode("ascii", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise ValidationError("Git commit ID is not ASCII", field=field_name,
                                  code="invalid_revision") from exc
        if not _COMMIT_RE.fullmatch(output):
            raise ValidationError("revision did not resolve to a full commit SHA",
                                  field=field_name, code="invalid_revision")
        return output

    def _changes(self, base_commit: str, head_commit: str) -> tuple[_GitChange, ...]:
        output = self._git_bounded([
            "diff", "--name-status", "--no-renames", "--no-ext-diff", "--no-textconv",
            "-z", base_commit, head_commit, "--",
        ], max_stdout_bytes=self._max_total_bytes)
        tokens = output.split(b"\0")
        if tokens and tokens[-1] == b"":
            tokens.pop()
        changes: list[_GitChange] = []
        index = 0
        while index < len(tokens):
            status_token = tokens[index]
            index += 1
            if b"\t" in status_token:
                raw_status, raw_path = status_token.split(b"\t", 1)
            else:
                raw_status = status_token
                if index >= len(tokens):
                    raise ValidationError("malformed Git name-status output",
                                          field="changed_paths",
                                          code="invalid_diff_output")
                raw_path = tokens[index]
                index += 1
            try:
                status_code = raw_status.decode("ascii", errors="strict")
                decoded = raw_path.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValidationError("changed Git status/path is not valid text",
                                      field=f"changed_paths[{len(changes)}]",
                                      code="invalid_path") from exc
            status = {"A": "added", "M": "modified", "D": "deleted"}.get(status_code)
            if status is None:
                raise ValidationError(f"unsupported Git change status: {status_code!r}",
                                      field=f"changed_paths[{len(changes)}].status",
                                      code="unsupported_diff_status")
            changes.append(_GitChange(
                path=_normalise_repository_path(
                    decoded, field_name=f"changed_paths[{len(changes)}]"
                ),
                status=status,
            ))
        if len(changes) > self._max_files:
            raise ValidationError("Git diff contains too many changed paths",
                                  field="changed_paths", code="snapshot_file_limit")
        by_path: dict[str, _GitChange] = {}
        for change in changes:
            if change.path in by_path:
                raise ValidationError("Git diff returned duplicate changed path",
                                      path=change.path, code="invalid_diff_output")
            by_path[change.path] = change
        return tuple(by_path[path] for path in sorted(by_path))

    def _changed_paths(self, base_commit: str, head_commit: str) -> tuple[str, ...]:
        """Compatibility view over the trusted name/status diff."""

        return tuple(change.path for change in self._changes(base_commit, head_commit))

    @staticmethod
    def _parse_tree_entry(output: bytes, *, path: str) -> _TreeEntry | None:
        records = [record for record in output.split(b"\0") if record]
        if not records:
            return None
        if len(records) != 1:
            raise ValidationError("Git path did not resolve to one tree entry", path=path,
                                  code="ambiguous_tree_entry")
        try:
            metadata, raw_path = records[0].split(b"\t", 1)
            mode, object_type, object_id, raw_size = metadata.split()
            listed_path = raw_path.decode("utf-8", errors="strict")
            size = -1 if raw_size == b"-" else int(raw_size)
            entry = _TreeEntry(
                path=listed_path,
                mode=mode.decode("ascii", errors="strict"),
                object_type=object_type.decode("ascii", errors="strict"),
                object_id=object_id.decode("ascii", errors="strict"),
                size=size,
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError("malformed Git tree entry", path=path,
                                  code="invalid_tree_entry") from exc
        if entry.path != path:
            raise ValidationError("Git returned a different tree path", path=path,
                                  code="invalid_tree_entry")
        if not _COMMIT_RE.fullmatch(entry.object_id):
            raise ValidationError("invalid Git object metadata", path=path,
                                  code="invalid_tree_entry")
        return entry

    def _raw_tree_entry(self, head_commit: str, path: str) -> _TreeEntry | None:
        literal_pathspec = f":(literal){path}"
        output = self._git([
            "ls-tree", "-z", "-l", "--full-tree", head_commit, "--", literal_pathspec,
        ])
        return self._parse_tree_entry(output, path=path)

    def _tree_entry(self, head_commit: str, path: str) -> _TreeEntry | None:
        entry = self._raw_tree_entry(head_commit, path)
        if entry is None:
            return None
        if entry.object_type != "blob" or entry.mode != "100644":
            raise ValidationError(
                "snapshot files must be non-executable regular Git blobs",
                path=path,
                field="mode",
                code="unsafe_git_mode",
            )
        if entry.size < 0:
            raise ValidationError("invalid Git blob metadata", path=path,
                                  code="invalid_tree_entry")
        return entry

    def _dependency_tree_entry(
        self, dependency: _TrustedDependency, relative_path: str
    ) -> _TreeEntry | None:
        output = self._dependency_git(dependency, [
            "ls-tree", "-z", "-l", "--full-tree", dependency.commit, "--",
            f":(literal){relative_path}",
        ])
        entry = self._parse_tree_entry(output, path=relative_path)
        if entry is None:
            return None
        if entry.object_type != "blob" or entry.mode != "100644" or entry.size < 0:
            raise ValidationError(
                "dependency files must be non-executable regular Git blobs",
                path=f"{dependency.path}/{relative_path}",
                field="mode",
                code="unsafe_dependency_mode",
            )
        return entry

    def _dependency_for_path(
        self, path: str
    ) -> tuple[_TrustedDependency, str] | None:
        for dependency in self._trusted_dependencies:
            prefix = dependency.path + "/"
            if path.startswith(prefix):
                relative = _normalise_repository_path(
                    path[len(prefix):], field_name="dependency_artifact"
                )
                return dependency, relative
        return None

    def _verify_dependency_checkout(self, dependency: _TrustedDependency) -> None:
        try:
            assert_clean_checkout(
                dependency.checkout,
                dependency.commit,
                lambda arguments, cap: self._dependency_git(
                    dependency,
                    arguments,
                    max_stdout_bytes=cap,
                ),
            )
        except CheckoutCleanlinessError as exc:
            raise ValidationError(
                "dependency checkout must be clean",
                path=dependency.checkout,
                code="dependency_checkout_dirty",
            ) from exc
        except ValidationError as exc:
            if exc.code != "snapshot_too_large":
                raise
            raise ValidationError(
                "dependency checkout must be clean",
                path=dependency.checkout,
                code="dependency_checkout_dirty",
            ) from exc

    def _verify_dependencies(self, head_commit: str) -> None:
        for dependency in self._trusted_dependencies:
            entry = self._raw_tree_entry(head_commit, dependency.path)
            if entry is None or entry.mode != "160000" or entry.object_type != "commit":
                raise ValidationError("trusted dependency path is not a Git gitlink",
                                      path=dependency.path, field="mode",
                                      code="dependency_gitlink_missing")
            if entry.object_id != dependency.commit:
                raise ValidationError("Git gitlink does not match trusted dependency pin",
                                      path=dependency.path, field="commit",
                                      code="dependency_gitlink_mismatch")
            self._verify_dependency_checkout(dependency)

    def _read_dependency_file(
        self, dependency: _TrustedDependency, relative_path: str
    ) -> bytes:
        full_path = f"{dependency.path}/{relative_path}"
        entry = self._dependency_tree_entry(dependency, relative_path)
        if entry is None:
            raise ValidationError("dependency closure file is absent at pinned commit",
                                  path=full_path, code="snapshot_file_not_found")
        if entry.size > self._max_file_bytes:
            raise ValidationError(
                f"dependency file exceeds limit ({self._max_file_bytes} bytes)",
                path=full_path,
                code="snapshot_file_too_large",
            )
        resolved = safe_artifact_path(
            dependency.checkout,
            relative_path,
            allowed_extensions=_MATERIALIZED_EXTENSIONS,
            max_bytes=self._max_file_bytes,
            reject_symlinks=True,
            reject_hardlinks=True,
        )
        info = resolved.lstat()
        if stat.S_IMODE(info.st_mode) & 0o111:
            raise ValidationError("executable dependency artifacts are not allowed",
                                  path=full_path, field="mode",
                                  code="unsafe_dependency_mode")
        text = safe_read_artifact(
            dependency.checkout,
            relative_path,
            allowed_extensions=_MATERIALIZED_EXTENSIONS,
            max_bytes=self._max_file_bytes,
            reject_symlinks=True,
            reject_hardlinks=True,
            encoding="utf-8",
        )
        raw = text.encode("utf-8")
        expected = self._dependency_git(dependency, ["cat-file", "blob", entry.object_id])
        if len(raw) != entry.size or raw != expected:
            raise ValidationError("dependency checkout content differs from pinned commit",
                                  path=full_path,
                                  code="dependency_checkout_mismatch")
        return raw

    def _read_snapshot_file(self, head_commit: str, path: str) -> bytes:
        dependency_source = self._dependency_for_path(path)
        if dependency_source is not None:
            return self._read_dependency_file(*dependency_source)
        entry = self._tree_entry(head_commit, path)
        if entry is None:
            raise ValidationError("manifest closure file is absent at head", path=path,
                                  code="snapshot_file_not_found")
        return self._read_blob(entry)

    def _validate_changes(self, head_commit: str, changes: Sequence[_GitChange]) -> None:
        dependencies = {dependency.path: dependency for dependency in self._trusted_dependencies}
        for change in changes:
            if change.status == "deleted":
                continue
            if change.path in dependencies:
                entry = self._raw_tree_entry(head_commit, change.path)
                dependency = dependencies[change.path]
                if (
                    entry is None
                    or entry.mode != "160000"
                    or entry.object_type != "commit"
                    or entry.object_id != dependency.commit
                ):
                    raise ValidationError("changed dependency gitlink is not trusted",
                                          path=change.path,
                                          code="dependency_gitlink_mismatch")
                continue
            # This rejects executable blobs, symlinks, unconfigured gitlinks,
            # trees and all other unusual modes before any parsing.
            if self._tree_entry(head_commit, change.path) is None:
                raise ValidationError("changed path is absent from head", path=change.path,
                                      code="invalid_diff_output")

    def _read_blob(self, entry: _TreeEntry) -> bytes:
        if entry.size > self._max_file_bytes:
            raise ValidationError(
                f"snapshot file exceeds limit ({self._max_file_bytes} bytes)",
                path=entry.path,
                code="snapshot_file_too_large",
            )
        raw = self._git(["cat-file", "blob", entry.object_id])
        if len(raw) != entry.size:
            raise ValidationError("Git blob size changed while reading", path=entry.path,
                                  code="git_object_mismatch")
        # ``cat-file`` verifies the object framing; hashing here also protects
        # deterministic fingerprinting independently of worktree metadata.
        try:
            raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationError("snapshot artifact is not UTF-8", path=entry.path,
                                  code="invalid_encoding") from exc
        return raw

    @staticmethod
    def _imports(data: Mapping[str, Any], *, path: str) -> tuple[tuple[str, str | None], ...]:
        imports = data.get("imports", [])
        if imports is None:
            return ()
        if isinstance(imports, Mapping):
            # DocHub package catalogues contain version metadata, not paths.
            # The semantic resolver validates their closed shape later.
            return ()
        if not isinstance(imports, list):
            raise ValidationError("imports must be a list", path=path, field="imports",
                                  code="invalid_import")
        result: dict[str, str | None] = {}
        for index, value in enumerate(imports):
            field_name = f"imports[{index}]"
            if isinstance(value, str) and value:
                target = _normalise_reference(value, parent=path, field_name=field_name)
                result.setdefault(target, None)
                continue
            if not isinstance(value, Mapping):
                raise ValidationError("import must be a path or pinned import mapping",
                                      path=path, field=field_name, code="invalid_import")
            remote = value.get("url", value.get("uri"))
            local = value.get("path", value.get("local"))
            if not isinstance(local, str) or not local:
                raise ValidationError("import mapping requires a vendored local path",
                                      path=path, field=field_name, code="invalid_import")
            expected_hash: str | None = None
            if remote is not None:
                revision = value.get("revision", value.get("ref", value.get("pin")))
                checksum = value.get("sha256")
                if (
                    not isinstance(remote, str)
                    or not _REMOTE_RE.match(remote)
                    or not isinstance(revision, str)
                    or not _COMMIT_RE.fullmatch(revision.lower())
                    or not isinstance(checksum, str)
                    or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum)
                ):
                    raise ValidationError(
                        "remote import requires an exact revision, sha256 and vendored path",
                        path=path,
                        field=field_name,
                        code="remote_import_requires_pin",
                    )
                expected_hash = checksum.lower()
            target = _normalise_reference(
                local, parent=path, field_name=f"{field_name}.path"
            )
            previous = result.get(target)
            if previous is not None and expected_hash is not None and previous != expected_hash:
                raise ValidationError("conflicting vendored import checksums", path=target,
                                      field="sha256", code="import_checksum_mismatch")
            if expected_hash is not None or target not in result:
                result[target] = expected_hash
        return tuple(sorted(result.items(), key=lambda item: item[0]))

    @staticmethod
    def _context_references(data: Any, *, path: str) -> tuple[str, ...]:
        references: set[str] = set()

        def walk(value: Any, parent_key: str | None = None) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    walk(child, str(key))
                return
            if isinstance(value, list):
                for child in value:
                    walk(child, parent_key)
                return
            if parent_key not in _CONTEXT_REFERENCE_KEYS or not isinstance(value, str):
                return
            candidate = value.strip()
            suffix = PurePosixPath(candidate).suffix.lower()
            if suffix not in _MATERIALIZED_EXTENSIONS:
                return
            references.add(_normalise_reference(
                candidate, parent=path, field_name=parent_key
            ))

        walk(data)
        return tuple(sorted(references))

    def _collect_closure(
        self, head_commit: str
    ) -> tuple[dict[str, bytes], dict[str, str]]:
        blobs: dict[str, bytes] = {}
        blob_hashes: dict[str, str] = {}
        pending: list[tuple[int, str]] = [(0, self._manifest_path)]
        queued = {self._manifest_path}
        pinned_hashes: dict[str, set[str]] = {}
        total_bytes = 0

        while pending:
            depth, path = heapq.heappop(pending)
            if path in blobs:
                continue
            if depth > self._max_depth:
                raise ValidationError("manifest closure exceeds depth limit", path=path,
                                      code="snapshot_depth_limit")
            if len(blobs) >= self._max_files:
                raise ValidationError("manifest closure contains too many files",
                                      code="snapshot_file_limit")
            suffix = PurePosixPath(path).suffix.lower()
            if suffix not in _MATERIALIZED_EXTENSIONS:
                raise ValidationError("manifest references an unsupported artifact type",
                                      path=path, field="extension",
                                      code="unsupported_snapshot_artifact")
            raw = self._read_snapshot_file(head_commit, path)
            total_bytes += len(raw)
            if total_bytes > self._max_total_bytes:
                raise ValidationError("manifest closure exceeds total byte limit",
                                      code="snapshot_too_large")
            blobs[path] = raw
            blob_hashes[path] = _sha256(raw)

            if suffix not in _YAML_EXTENSIONS:
                continue
            data = strict_load_yaml_text(
                raw,
                source=f"{head_commit}:{path}",
                expected_type=dict,
                max_bytes=self._max_file_bytes,
            )
            imported = dict(self._imports(data, path=path))
            references = set(imported)
            references.update(self._context_references(data, path=path))
            for reference in sorted(references):
                expected_hash = imported.get(reference)
                if expected_hash is not None and reference in blob_hashes:
                    if blob_hashes[reference] != expected_hash:
                        raise ValidationError("vendored import checksum mismatch",
                                              path=reference, field="sha256",
                                              code="import_checksum_mismatch")
                if reference not in queued:
                    queued.add(reference)
                    heapq.heappush(pending, (depth + 1, reference))
                # Record checksums even when another branch queued the same
                # file first; verification is repeated after closure loading.
                if expected_hash is not None:
                    pinned_hashes.setdefault(reference, set()).add(expected_hash)
                    if len(pinned_hashes[reference]) > 1:
                        raise ValidationError("conflicting vendored import checksums",
                                              path=reference, field="sha256",
                                              code="import_checksum_mismatch")
        for path, expected_values in pinned_hashes.items():
            expected = next(iter(expected_values))
            if blob_hashes.get(path) != expected:
                raise ValidationError("vendored import checksum mismatch", path=path,
                                      field="sha256", code="import_checksum_mismatch")
        # A checkout that changed while files were being copied is never
        # accepted, even though every copied payload was also compared with
        # its pinned Git blob above.
        for dependency in self._trusted_dependencies:
            self._verify_dependency_checkout(dependency)
        return blobs, blob_hashes

    def _dependency_provenance(
        self, blob_hashes: Mapping[str, str]
    ) -> tuple[TrustedDependencyProvenance, ...]:
        result: list[TrustedDependencyProvenance] = []
        for dependency in self._trusted_dependencies:
            prefix = dependency.path + "/"
            files = [
                {"path": path, "sha256": blob_hashes[path]}
                for path in sorted(blob_hashes)
                if path.startswith(prefix)
            ]
            payload = json.dumps(
                {"path": dependency.path, "commit": dependency.commit, "files": files},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            result.append(TrustedDependencyProvenance(
                path=dependency.path,
                commit=dependency.commit,
                closure_sha256=_sha256(payload),
            ))
        return tuple(result)

    def _changed_artifacts(
        self,
        changes: Sequence[_GitChange],
        *,
        base_commit: str,
        head_commit: str,
        base_blobs: Mapping[str, bytes],
        head_blobs: Mapping[str, bytes],
        blob_hashes: Mapping[str, str],
    ) -> tuple[ChangedArtifact, ...]:
        artifacts: list[ChangedArtifact] = []
        for change in changes:
            source_commit = head_commit
            checksum = blob_hashes.get(change.path)
            if change.status == "deleted":
                base_raw = base_blobs.get(change.path)
                if base_raw is None:
                    raise ValidationError(
                        "deleted path payload is absent from the bounded base set",
                        path=change.path,
                        code="invalid_diff_output",
                    )
                checksum = _sha256(base_raw)
                source_commit = base_commit
            elif checksum is None:
                raise ValidationError(
                    "changed artifact was not materialized",
                    path=change.path,
                    code="snapshot_file_not_found",
                )
            source = SourceProvenance(
                file=change.path,
                pointer="",
                commit=source_commit,
                sha256=checksum,
            )
            artifacts.append(ChangedArtifact(
                path=change.path,
                status=change.status,
                sha256=checksum,
                source_ref=source,
                changed_pointers=self._changed_entity_pointers(
                    change,
                    base_commit=base_commit,
                    head_commit=head_commit,
                    base_raw=base_blobs.get(change.path),
                    head_raw=head_blobs.get(change.path),
                ),
            ))
        return tuple(artifacts)

    def _changed_entity_pointers(
        self,
        change: _GitChange,
        *,
        base_commit: str,
        head_commit: str,
        base_raw: bytes | None,
        head_raw: bytes | None,
    ) -> tuple[str, ...]:
        if PurePosixPath(change.path).suffix.lower() not in _YAML_EXTENSIONS:
            return ()

        def load(raw: bytes | None, revision: str) -> Mapping[str, Any]:
            if raw is None:
                return {}
            return strict_load_yaml_text(
                raw,
                source=f"{revision}:{change.path}",
                expected_type=dict,
                max_bytes=self._max_file_bytes,
            )

        if change.status != "added":
            if base_raw is None:
                raise ValidationError(
                    "changed path payload is absent from the bounded base set",
                    path=change.path,
                    code="invalid_diff_output",
                )
        before = load(base_raw, base_commit)
        after = load(head_raw, head_commit)
        pointers: list[str] = []
        for section in _ENTITY_SECTIONS:
            before_section = before.get(section, {})
            after_section = after.get(section, {})
            if not isinstance(before_section, Mapping) or not isinstance(after_section, Mapping):
                continue
            for entity_id in sorted(set(before_section) | set(after_section), key=str):
                if before_section.get(entity_id) == after_section.get(entity_id):
                    continue
                escaped_section = section.replace("~", "~0").replace("/", "~1")
                escaped_id = str(entity_id).replace("~", "~0").replace("/", "~1")
                entity_pointer = f"/{escaped_section}/{escaped_id}"
                pointers.append(entity_pointer)
                before_entity = before_section.get(entity_id)
                after_entity = after_section.get(entity_id)
                if isinstance(before_entity, Mapping) and isinstance(after_entity, Mapping):
                    for field_name in sorted(
                        set(before_entity) | set(after_entity), key=str
                    ):
                        if before_entity.get(field_name) == after_entity.get(field_name):
                            continue
                        escaped_field = str(field_name).replace("~", "~0").replace("/", "~1")
                        pointers.append(f"{entity_pointer}/{escaped_field}")
        return tuple(pointers)

    def _rules_sha256(self) -> str:
        return rules_directory_sha256(
            self._rules_dir,
            max_file_bytes=self._max_file_bytes,
            max_total_bytes=self._max_total_bytes,
        )

    @staticmethod
    def _write_isolated(root: Path, path: str, raw: bytes) -> None:
        destination = root.joinpath(*PurePosixPath(path).parts)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(destination, flags, 0o600)
        except OSError as exc:
            raise ValidationError("cannot create isolated snapshot file", path=path,
                                  code="staging_error") from exc
        try:
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:  # pragma: no cover - defensive OS boundary
                    raise OSError("short write")
                view = view[written:]
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValidationError("staged artifact is not an isolated regular file",
                                      path=path, code="unsafe_staging_file")
        finally:
            os.close(descriptor)

    @staticmethod
    def _content_fingerprint(
        revision: RepositoryRevision,
        changed_artifacts: Sequence[ChangedArtifact],
        blob_hashes: Mapping[str, str],
        dependency_provenance: Sequence[TrustedDependencyProvenance],
        dependency_verification: str,
    ) -> str:
        payload = {
            "revision": _revision_dict(revision),
            "dependency_verification": dependency_verification,
            "changed_artifacts": [artifact.as_dict() for artifact in changed_artifacts],
            "trusted_dependencies": [
                dependency.as_dict() for dependency in dependency_provenance
            ],
            "files": [{"path": path, "sha256": blob_hashes[path]}
                      for path in sorted(blob_hashes)],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        return _sha256(encoded)

    def build(self) -> RepositorySnapshot:
        """Create an isolated snapshot without reading or changing the worktree."""

        base_commit = self._resolve_commit(self._base_revision, field_name="base")
        head_commit = self._resolve_commit(self._head_revision, field_name="head")
        all_changes = self._changes(base_commit, head_commit)
        changes = tuple(
            change
            for change in all_changes
            if not self._scope_prefix or change.path.startswith(self._scope_prefix)
        )
        ignored_out_of_scope = tuple(
            change.path for change in all_changes if change not in changes
        )
        changed_paths = tuple(change.path for change in changes)
        self._verify_dependencies(head_commit)
        self._validate_changes(head_commit, changes)
        blobs, blob_hashes = self._collect_closure(head_commit)
        closure_paths = frozenset(blobs)

        dependency_paths = {dependency.path for dependency in self._trusted_dependencies}
        unsupported = tuple(
            change.path
            for change in changes
            if change.path not in dependency_paths
            and PurePosixPath(change.path).suffix.lower() not in _MATERIALIZED_EXTENSIONS
        )
        if unsupported:
            raise ValidationError(
                "Git diff contains unsupported architecture artifact(s): "
                + ", ".join(unsupported),
                field="changed_paths",
                code="unsupported_changed_artifact",
            )

        omitted = tuple(
            change.path for change in changes
            if change.status != "deleted"
            and change.path not in dependency_paths
            and PurePosixPath(change.path).suffix.lower() in _CLOSURE_REQUIRED_EXTENSIONS
            and change.path not in blobs
        )
        if omitted:
            raise ValidationError(
                "root manifest/context closure omits changed artifact: " + ", ".join(omitted),
                field="changed_paths",
                code="manifest_omits_changed_file",
            )

        total_bytes = sum(len(raw) for raw in blobs.values())
        for change in changes:
            if (
                change.status == "deleted"
                or change.path in dependency_paths
                or change.path in blobs
            ):
                continue
            if len(blobs) >= self._max_files:
                raise ValidationError(
                    "snapshot plus changed artifacts contains too many files",
                    field="changed_paths",
                    code="snapshot_file_limit",
                )
            raw = self._read_snapshot_file(head_commit, change.path)
            total_bytes += len(raw)
            if total_bytes > self._max_total_bytes:
                raise ValidationError(
                    "snapshot plus changed artifacts exceeds total byte limit",
                    field="changed_paths",
                    code="snapshot_too_large",
                )
            blobs[change.path] = raw
            blob_hashes[change.path] = _sha256(raw)

        # Deleted artifacts and the base side of YAML entity diffs are review
        # inputs too.  Read each exactly once and charge it to the same
        # aggregate limit before hashing or parsing it.
        base_change_blobs: dict[str, bytes] = {}
        for change in changes:
            needs_base = change.status == "deleted" or (
                change.status != "added"
                and PurePosixPath(change.path).suffix.lower() in _YAML_EXTENSIONS
            )
            if not needs_base:
                continue
            entry = self._tree_entry(base_commit, change.path)
            if entry is None:
                raise ValidationError(
                    "changed path is absent from base",
                    path=change.path,
                    code="invalid_diff_output",
                )
            raw = self._read_blob(entry)
            total_bytes += len(raw)
            if total_bytes > self._max_total_bytes:
                raise ValidationError(
                    "snapshot plus base-side changed artifacts exceeds total byte limit",
                    field="changed_paths",
                    code="snapshot_too_large",
                )
            base_change_blobs[change.path] = raw

        manifest_raw = blobs[self._manifest_path]
        revision = RepositoryRevision(
            base_commit=base_commit,
            head_commit=head_commit,
            manifest_sha256=_sha256(manifest_raw),
            archtool_commit=self._archtool_commit,
            seaf_core_commit=self._seaf_core_commit,
            aga_version=self._aga_version,
            rules_sha256=self._rules_sha256(),
        )
        changed_artifacts = self._changed_artifacts(
            changes,
            base_commit=base_commit,
            head_commit=head_commit,
            base_blobs=base_change_blobs,
            head_blobs=blobs,
            blob_hashes=blob_hashes,
        )
        dependency_provenance = self._dependency_provenance(blob_hashes)
        dependency_verification = (
            "verified-gitlinks" if self._dependency_mode == "verified"
            else "fixture-unverified"
        )
        fingerprint = self._content_fingerprint(
            revision,
            changed_artifacts,
            blob_hashes,
            dependency_provenance,
            dependency_verification,
        )

        temporary = tempfile.TemporaryDirectory(prefix="aga-repository-snapshot-")
        root = Path(temporary.name).resolve(strict=True)
        try:
            for path in sorted(blobs):
                self._write_isolated(root, path, blobs[path])
            manifest_path = root.joinpath(*PurePosixPath(self._manifest_path).parts)
            materialized = tuple(sorted(blobs))
            context = tuple(
                path for path in sorted(closure_paths) if path != self._manifest_path
            )
            return RepositorySnapshot(
                root=root,
                manifest_path=manifest_path,
                manifest_relative_path=self._manifest_path,
                changed_paths=changed_paths,
                changed_artifacts=changed_artifacts,
                context_paths=context,
                materialized_paths=materialized,
                review_scope=self._scope_prefix or ".",
                ignored_out_of_scope_paths=ignored_out_of_scope,
                dependency_verification=dependency_verification,
                dependency_provenance=dependency_provenance,
                materialized_hashes=tuple(
                    (path, blob_hashes[path]) for path in sorted(blob_hashes)
                ),
                revision=revision,
                content_sha256=fingerprint,
                _max_file_bytes=self._max_file_bytes,
                _temporary_directory=temporary,
            )
        except Exception:
            temporary.cleanup()
            raise


__all__ = [
    "DEFAULT_ARCHTOOL_COMMIT",
    "DEFAULT_ARCHTOOL_PATH",
    "DEFAULT_SEAF_CORE_COMMIT",
    "DEFAULT_SEAF_CORE_PATH",
    "DEPENDENCY_MODES",
    "RepositoryRevision",
    "RepositorySnapshot",
    "RepositorySnapshotBuilder",
    "TrustedDependencyProvenance",
    "rules_directory_sha256",
]
