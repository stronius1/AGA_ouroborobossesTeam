# -*- coding: utf-8 -*-
"""Safe publication contracts for candidate-only evolution artifacts.

The implicit publisher remains side-effect-free.  The separately invoked
local connector can create one candidate commit and branch, but has no
network, push, pull-request, approval, or merge capability.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Protocol, runtime_checkable


FORBIDDEN_ACTIONS = frozenset(
    {
        "merge",
        "approve",
        "approve_pr",
        "push",
        "push_main",
        "push_to_main",
        "open_pull_request",
        "create_pull_request",
    }
)
MAX_LOCAL_TRANSACTION_BYTES = 64 * 1024 * 1024
_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_CYCLE_RE = re.compile(r"aga-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\Z")
_RULE_PATH_RE = re.compile(
    r"aga-skill/rules/(?:principles|seaf-checks|diagram-checks|adr-checks)\.yaml\Z"
)


class PublisherError(RuntimeError):
    """Base publisher failure."""


class PublisherPolicyError(PublisherError, PermissionError):
    """An action violates the immutable HITL/SoD policy."""


class PublisherValidationError(PublisherError, ValueError):
    """A publication request is malformed."""


@dataclass(frozen=True)
class PublishRequest:
    cycle_id: str
    artifacts: Mapping[str, str | Path]
    branch_name: str | None = None
    commit_message: str | None = None
    draft: bool = True
    requested_actions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_id, str) or not self.cycle_id.strip():
            raise PublisherValidationError("cycle_id must be a non-empty string")
        if not isinstance(self.artifacts, Mapping):
            raise PublisherValidationError("artifacts must be a mapping")
        for name, path in self.artifacts.items():
            if not isinstance(name, str) or not name.strip():
                raise PublisherValidationError("artifact names must be non-empty strings")
            if not isinstance(path, (str, Path)):
                raise PublisherValidationError(
                    f"artifact {name!r} path must be str or Path"
                )
        if not isinstance(self.requested_actions, tuple) or not all(
            isinstance(item, str) for item in self.requested_actions
        ):
            raise PublisherValidationError("requested_actions must be a tuple of strings")
        if not isinstance(self.metadata, Mapping):
            raise PublisherValidationError("metadata must be a mapping")


def _safe_relative_path(value: str, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise PublisherValidationError(f"{label} is not a safe repository path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PublisherValidationError(f"{label} is not a contained repository path")
    normalized = path.as_posix()
    if normalized != value:
        raise PublisherValidationError(f"{label} is not normalized")
    return normalized


@dataclass(frozen=True)
class LocalCandidateRequest:
    """Exact, pre-validated transaction accepted by the local VCS connector."""

    cycle_id: str
    base_commit: str
    branch_name: str
    commit_message: str
    files: Mapping[str, bytes]
    base_bindings: Mapping[str, bytes]
    changed_rule_paths: tuple[str, ...]
    precedent_path: str
    report_path: str
    manifest_path: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_id, str) or not _CYCLE_RE.fullmatch(self.cycle_id):
            raise PublisherValidationError("local candidate has an invalid cycle_id")
        if not isinstance(self.base_commit, str) or not _COMMIT_RE.fullmatch(
            self.base_commit
        ):
            raise PublisherValidationError("base_commit must be a full immutable Git SHA")
        if (
            not isinstance(self.branch_name, str)
            or not self.branch_name.startswith("skill/evolution-")
            or len(self.branch_name) > 200
            or any(ord(character) < 32 for character in self.branch_name)
        ):
            raise PublisherValidationError("candidate branch name is invalid")
        if (
            not isinstance(self.commit_message, str)
            or not self.commit_message.strip()
            or len(self.commit_message) > 500
            or any(ord(character) < 32 and character not in "\n\t" for character in self.commit_message)
        ):
            raise PublisherValidationError("candidate commit message is invalid")
        if (
            not isinstance(self.changed_rule_paths, tuple)
            or len(self.changed_rule_paths) != 1
            or not _RULE_PATH_RE.fullmatch(self.changed_rule_paths[0])
        ):
            raise PublisherValidationError(
                "local candidate must contain exactly one changed non-policy rule file"
            )
        precedent = _safe_relative_path(self.precedent_path, label="precedent_path")
        if not re.fullmatch(r"aga-skill/precedents/cases/[A-Za-z0-9._-]+\.md", precedent):
            raise PublisherValidationError("precedent_path is outside the precedent registry")
        expected_report = f"docs/evidence/evolution/{self.cycle_id}.md"
        expected_manifest = f"docs/evidence/evolution/{self.cycle_id}.json"
        if self.report_path != expected_report or self.manifest_path != expected_manifest:
            raise PublisherValidationError("candidate evidence paths are not cycle-bound")
        expected_files = {
            self.changed_rule_paths[0],
            "aga-skill/VERSION",
            "aga-skill/CHANGELOG.md",
            precedent,
            expected_report,
            expected_manifest,
        }
        if not isinstance(self.files, Mapping) or set(self.files) != expected_files:
            raise PublisherValidationError("candidate transaction has an invalid exact file set")
        if not isinstance(self.base_bindings, Mapping):
            raise PublisherValidationError("base_bindings must be a mapping")
        required_bindings = expected_files - {expected_report, expected_manifest}
        if not required_bindings.issubset(self.base_bindings):
            raise PublisherValidationError("candidate transaction is missing base bindings")
        total = 0
        for label, payloads in (("files", self.files), ("base_bindings", self.base_bindings)):
            for path, payload in payloads.items():
                _safe_relative_path(path, label=f"{label} path")
                if not isinstance(payload, bytes):
                    raise PublisherValidationError(f"{label} payloads must be bytes")
                total += len(payload)
                if total > MAX_LOCAL_TRANSACTION_BYTES:
                    raise PublisherValidationError("local candidate transaction is too large")
        if not isinstance(self.metadata, Mapping):
            raise PublisherValidationError("candidate metadata must be a mapping")


@dataclass(frozen=True)
class PublicationResult:
    publisher: str
    status: str
    cycle_id: str
    artifacts: tuple[str, ...]
    external_side_effects: bool
    branch_name: str | None = None
    commit: str | None = None
    draft_pr_url: str | None = None
    human_review_required: bool = True
    auto_merge: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "publisher": self.publisher,
            "status": self.status,
            "cycle_id": self.cycle_id,
            "artifacts": list(self.artifacts),
            "external_side_effects": self.external_side_effects,
            "branch_name": self.branch_name,
            "commit": self.commit,
            "draft_pr_url": self.draft_pr_url,
            "human_review_required": self.human_review_required,
            "auto_merge": self.auto_merge,
            "details": dict(self.details),
        }


@runtime_checkable
class EvolutionPublisher(Protocol):
    """Publication boundary used by the evolver."""

    requires_network: bool

    def publish(self, request: PublishRequest) -> PublicationResult:
        ...


def _normalise_action(action: str) -> str:
    return action.strip().lower().replace("-", "_").replace(" ", "_")


def validate_publish_request(request: PublishRequest) -> None:
    if not isinstance(request, PublishRequest):
        raise PublisherValidationError("publish expects a PublishRequest")
    forbidden = {
        action
        for action in (_normalise_action(item) for item in request.requested_actions)
        if action in FORBIDDEN_ACTIONS
    }
    if forbidden:
        raise PublisherPolicyError(
            f"publisher can never execute: {', '.join(sorted(forbidden))}"
        )
    if not request.draft and request.branch_name:
        raise PublisherPolicyError("publisher may open only a draft PR")


class DryRunPublisher:
    """Default publisher: reports candidate artifacts and changes nothing."""

    requires_network = False
    name = "dry-run"

    def publish(self, request: PublishRequest) -> PublicationResult:
        validate_publish_request(request)
        return PublicationResult(
            publisher=self.name,
            status="dry_run",
            cycle_id=request.cycle_id,
            # Persist stable logical names, not developer-specific absolute paths.
            artifacts=tuple(request.artifacts.keys()),
            external_side_effects=False,
            branch_name=None,
            draft_pr_url=None,
            details={
                "candidate_branch": request.branch_name,
                "draft_requested": request.draft,
                "message": "artifacts validated; no branch, commit, push, or PR created",
            },
        )

    def merge(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("merge is permanently forbidden for the evolver")

    def approve(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("approve is permanently forbidden for the evolver")

    def approve_pr(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("approve is permanently forbidden for the evolver")

    def push_to_main(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError(
            "direct push to the protected branch is permanently forbidden"
        )


def default_publisher() -> EvolutionPublisher:
    """Return the only safe implicit publisher."""

    return DryRunPublisher()


class LocalCandidatePublisher:
    """Create one local candidate commit without touching the caller worktree.

    The commit is built on a detached disposable worktree.  Only after that
    worktree is removed and the caller's HEAD/status are rechecked is the
    candidate branch ref created atomically.  No network-capable operation is
    present in this connector.
    """

    name = "local-candidate"
    requires_network = False

    def __init__(
        self,
        *,
        repository_root: str | Path,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self._repository_root = Path(repository_root).absolute()
        self._runner = runner or subprocess.run

    def _process(
        self,
        *arguments: str,
        repository: Path | None = None,
        check: bool = True,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess:
        root = repository or self._repository_root
        operation_index = 0
        while (
            operation_index + 1 < len(arguments)
            and arguments[operation_index] == "-c"
        ):
            operation_index += 2
        operation = (
            arguments[operation_index]
            if operation_index < len(arguments)
            else "command"
        )
        allowed_environment = (
            "PATH",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TMPDIR",
            "SYSTEMROOT",
            "WINDIR",
        )
        environment = {
            key: os.environ[key] for key in allowed_environment if key in os.environ
        }
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PAGER": "cat",
                "GIT_AUTHOR_NAME": "AGA Local Candidate",
                "GIT_AUTHOR_EMAIL": "aga-local@example.invalid",
                "GIT_COMMITTER_NAME": "AGA Local Candidate",
                "GIT_COMMITTER_EMAIL": "aga-local@example.invalid",
            }
        )
        try:
            completed = self._runner(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "commit.gpgSign=false",
                    *arguments,
                ],
                check=False,
                capture_output=True,
                text=False,
                timeout=timeout,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PublisherError(f"git {operation} could not be executed") from exc
        if not isinstance(completed, subprocess.CompletedProcess):
            raise PublisherError("git runner returned an invalid result")
        if check and completed.returncode != 0:
            raise PublisherError(
                f"git {operation} failed with exit code {completed.returncode}"
            )
        return completed

    def _git_bytes(
        self, *arguments: str, repository: Path | None = None
    ) -> bytes:
        output = self._process(*arguments, repository=repository).stdout
        if not isinstance(output, bytes):
            raise PublisherError("git returned non-byte output")
        return output

    def _git_text(
        self, *arguments: str, repository: Path | None = None
    ) -> str:
        try:
            return self._git_bytes(*arguments, repository=repository).decode(
                "utf-8", errors="strict"
            ).strip()
        except UnicodeDecodeError as exc:
            raise PublisherError("git returned non-UTF-8 metadata") from exc

    def resolve_head(self) -> str:
        top_level = self._git_text("rev-parse", "--show-toplevel")
        if Path(top_level).resolve() != self._repository_root.resolve():
            raise PublisherValidationError("repository must be its exact Git top-level")
        commit = self._git_text("rev-parse", "--verify", "HEAD^{commit}")
        if not _COMMIT_RE.fullmatch(commit):
            raise PublisherValidationError("repository HEAD is not a full commit SHA")
        return commit

    def _existing_ref(self, reference: str) -> str | None:
        completed = self._process(
            "show-ref", "--verify", "--quiet", reference, check=False
        )
        if completed.returncode == 1:
            return None
        if completed.returncode != 0:
            raise PublisherError("git show-ref failed")
        value = self._git_text("rev-parse", "--verify", reference)
        if not _COMMIT_RE.fullmatch(value):
            raise PublisherError("candidate ref does not point to a commit")
        return value

    def _assert_base_bindings(self, request: LocalCandidateRequest) -> None:
        for path, expected in request.base_bindings.items():
            actual = self._git_bytes("show", f"{request.base_commit}:{path}")
            if actual != expected:
                raise PublisherValidationError(
                    f"target base binding differs for {path}"
                )

    @staticmethod
    def _write_candidate_file(worktree: Path, relative: str, payload: bytes) -> None:
        path = PurePosixPath(_safe_relative_path(relative, label="candidate path"))
        target = worktree.joinpath(*path.parts)
        current = worktree
        for part in path.parts[:-1]:
            current = current / part
            # ``Path.exists()`` is false for a dangling symlink, so test the
            # link bit directly before any mkdir/write operation can follow it.
            if current.is_symlink():
                raise PublisherValidationError("candidate path contains a symlink")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise PublisherValidationError("candidate target is not a regular file")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    def publish(self, request: LocalCandidateRequest) -> PublicationResult:
        if not isinstance(request, LocalCandidateRequest):
            raise PublisherValidationError(
                "local publisher expects a LocalCandidateRequest"
            )
        self._git_text("check-ref-format", "--branch", request.branch_name)
        original_head = self.resolve_head()
        if original_head != request.base_commit:
            raise PublisherValidationError("repository HEAD changed after validation")
        original_status = self._git_bytes(
            "status", "--porcelain=v2", "-z", "--untracked-files=all"
        )
        self._assert_base_bindings(request)
        reference = f"refs/heads/{request.branch_name}"
        existing_commit = self._existing_ref(reference)

        commit_sha: str | None = None
        desired_tree: str | None = None
        operation_error: Exception | None = None
        worktree_added = False
        with tempfile.TemporaryDirectory(prefix="aga-local-candidate-") as temporary:
            worktree = Path(temporary) / "worktree"
            try:
                self._process(
                    "worktree",
                    "add",
                    "--detach",
                    "--quiet",
                    str(worktree),
                    request.base_commit,
                )
                worktree_added = True
                for path, payload in request.files.items():
                    self._write_candidate_file(worktree, path, payload)
                ordered_paths = tuple(sorted(request.files))
                filter_raw = self._git_bytes(
                    "check-attr", "-z", "filter", "--", *ordered_paths,
                    repository=worktree,
                )
                filter_parts = filter_raw.rstrip(b"\0").split(b"\0")
                if len(filter_parts) != len(ordered_paths) * 3:
                    raise PublisherValidationError(
                        "candidate filter attributes could not be verified"
                    )
                if any(
                    filter_parts[index] not in {b"unspecified", b"unset"}
                    for index in range(2, len(filter_parts), 3)
                ):
                    raise PublisherValidationError(
                        "candidate paths must not use executable Git filters"
                    )
                self._process("add", "--", *ordered_paths, repository=worktree)
                staged_raw = self._git_bytes(
                    "diff", "--cached", "--name-only", "-z", repository=worktree
                )
                staged = {
                    item.decode("utf-8", errors="strict")
                    for item in staged_raw.split(b"\0")
                    if item
                }
                if staged != set(ordered_paths):
                    raise PublisherValidationError(
                        "staged candidate paths differ from the validated transaction"
                    )
                source_paths = tuple(
                    sorted(
                        set(request.files)
                        - {request.report_path}
                    )
                )
                self._process(
                    "diff",
                    "--no-ext-diff",
                    "--cached",
                    "--check",
                    "--",
                    *source_paths,
                    repository=worktree,
                )
                desired_tree = self._git_text("write-tree", repository=worktree)

                if existing_commit is not None:
                    existing_tree = self._git_text(
                        "rev-parse", f"{existing_commit}^{{tree}}"
                    )
                    existing_parent = self._git_text(
                        "rev-parse", f"{existing_commit}^"
                    )
                    if (
                        existing_tree != desired_tree
                        or existing_parent != request.base_commit
                    ):
                        raise PublisherValidationError(
                            "candidate branch already exists with different content"
                        )
                    commit_sha = existing_commit
                else:
                    self._process(
                        "-c",
                        "core.hooksPath=/dev/null",
                        "commit",
                        "--quiet",
                        "-m",
                        request.commit_message,
                        repository=worktree,
                    )
                    commit_sha = self._git_text(
                        "rev-parse", "--verify", "HEAD^{commit}", repository=worktree
                    )
                    parent = self._git_text("rev-parse", "HEAD^", repository=worktree)
                    if parent != request.base_commit:
                        raise PublisherError("candidate commit has an unexpected parent")
            except Exception as exc:  # cleanup is handled before the error escapes
                operation_error = exc
            finally:
                if worktree_added:
                    cleanup = self._process(
                        "worktree", "remove", "--force", str(worktree), check=False
                    )
                    if cleanup.returncode != 0 and operation_error is None:
                        operation_error = PublisherError(
                            "temporary candidate worktree could not be removed"
                        )

        if operation_error is not None:
            raise operation_error
        if commit_sha is None or desired_tree is None:
            raise PublisherError("candidate commit was not produced")
        if self.resolve_head() != original_head or self._git_bytes(
            "status", "--porcelain=v2", "-z", "--untracked-files=all"
        ) != original_status:
            raise PublisherError("caller HEAD, index, or worktree changed during publication")

        idempotent = existing_commit is not None
        if not idempotent:
            zero_oid = "0" * len(request.base_commit)
            self._process("update-ref", reference, commit_sha, zero_oid)
        if self._git_text("rev-parse", "--verify", reference) != commit_sha:
            raise PublisherError("candidate branch ref verification failed")

        return PublicationResult(
            publisher=self.name,
            status="local_candidate_ready",
            cycle_id=request.cycle_id,
            artifacts=tuple(sorted(request.files)),
            external_side_effects=False,
            branch_name=request.branch_name,
            commit=commit_sha,
            draft_pr_url=None,
            human_review_required=True,
            auto_merge=False,
            details={
                "base_commit": request.base_commit,
                "idempotent": idempotent,
                "local_commit_created": not idempotent,
                "original_worktree_unchanged": True,
                "message": "local candidate branch and commit are ready for human review",
            },
        )

    def merge(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("merge is permanently forbidden")

    def approve(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("approval is permanently forbidden")

    def approve_pr(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("approval is permanently forbidden")

    def push(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("push is permanently forbidden")

    def push_to_main(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("direct push is permanently forbidden")

    def open_pull_request(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("opening pull requests is permanently forbidden")


__all__ = [
    "DryRunPublisher",
    "EvolutionPublisher",
    "FORBIDDEN_ACTIONS",
    "LocalCandidatePublisher",
    "LocalCandidateRequest",
    "PublicationResult",
    "PublishRequest",
    "PublisherError",
    "PublisherPolicyError",
    "PublisherValidationError",
    "default_publisher",
    "validate_publish_request",
]
