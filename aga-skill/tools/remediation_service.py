# -*- coding: utf-8 -*-
"""Stateful, fail-closed boundary for Ouroboros remediation tasks.

The public operations accept only opaque identifiers, immutable Git revisions
and digests.  Repository paths are registered by the trusted host and are
never accepted from, or returned to, the model.  A remediation can be prepared
only from a previously registered *trusted finalized* AGA review whose exact
canonical output hash was verified by the host/backend.

This service proposes and finalizes patch text but never writes a repository,
creates a branch, commits, pushes, approves or merges.  Materialization in an
isolated worktree is a separate host-only boundary.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import secrets
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from tools.remediation import (
    COMPONENT_ID_RE,
    INTEGRATION_ID_RE,
    RemediationNotAvailable,
    RemediationPatch,
    propose_remediation,
)
from tools.repository_snapshot import RepositorySnapshotBuilder
from tools.review_service import (
    DIGEST_RE,
    ID_RE,
    REVISION_RE,
    ReviewInputError,
    ReviewServiceError,
    SEMANTIC_RULE_IDS,
)
from tools.validation import ValidationError


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REMEDIATION_DIGEST_RE = re.compile(r"^rmd_[0-9a-f]{64}$")
MAX_FINAL_REVIEW_BYTES = 2_000_000
MAX_FINDINGS = 200
MAX_ARTIFACT_CHARS = 4_096
MAX_ERROR_CHARS = 1_000
MAX_REMEDIATION_ARTIFACTS = 16


class RemediationServiceError(ReviewServiceError):
    """Stable service error safe to expose through the MCP error envelope."""

    def as_dict(self) -> dict[str, Any]:
        result = super().as_dict()
        result["type"] = "remediation_service_error"
        return result


class RemediationInputError(ReviewInputError, RemediationServiceError):
    """A remediation MCP caller supplied an invalid public argument."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        suffix = f" ({field})" if field else ""
        RemediationServiceError.__init__(
            self, "invalid_arguments", f"{message}{suffix}"
        )

    def as_dict(self) -> dict[str, Any]:
        result = RemediationServiceError.as_dict(self)
        result["field"] = self.field
        return result


@dataclass(frozen=True)
class TrustedFinalizedReview:
    repository_id: str
    base: str
    head: str
    review_id: str
    review_digest: str
    task_digest: str
    output_sha256: str
    final: Mapping[str, Any]
    expires_at: float
    size_bytes: int


@dataclass
class _StoredRemediation:
    request_fingerprint: str
    expires_at: float
    prepared: dict[str, Any]
    patch: RemediationPatch | None
    size_bytes: int
    final_fingerprint: str | None = None
    final_result: dict[str, Any] | None = None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the lowercase SHA-256 of strict canonical JSON."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def finding_sha256(finding: Mapping[str, Any]) -> str:
    """Stable identity for one exact finding from ``aga.final-review/v1``."""

    if not isinstance(finding, Mapping):
        raise TypeError("finding must be a mapping")
    return canonical_sha256(finding)


def _finding_sha256(finding: Mapping[str, Any]) -> str:
    return canonical_sha256(finding)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise RemediationInputError("must be a non-path identifier", field=field)
    return value


def _revision(value: Any, field: str) -> str:
    if not isinstance(value, str) or REVISION_RE.fullmatch(value) is None:
        raise RemediationInputError("must be a full immutable Git SHA", field=field)
    return value.lower()


def _review_digest(value: Any, field: str, prefix: str) -> str:
    if (
        not isinstance(value, str)
        or DIGEST_RE.fullmatch(value) is None
        or not value.startswith(prefix + "_")
    ):
        raise RemediationInputError("must be an opaque review digest", field=field)
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise RemediationInputError("must be a lowercase SHA-256", field=field)
    return value


def _remediation_digest(value: Any) -> str:
    if not isinstance(value, str) or REMEDIATION_DIGEST_RE.fullmatch(value) is None:
        raise RemediationInputError(
            "must be an opaque remediation digest", field="remediation_digest"
        )
    return value


def _artifact_label(value: Any, field: str = "artifact") -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_ARTIFACT_CHARS
        or "\\" in value
        or any(character in value for character in ("\x00", "\n", "\r", "\t"))
    ):
        raise RemediationServiceError(
            "trusted_finding_invalid", "finding artifact is unsafe"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RemediationServiceError(
            "trusted_finding_invalid", f"{field} is not repository-relative"
        )
    return value


def _registry_artifact_label(value: Any, *, field: str) -> str:
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError(f"{field} must be a repository-relative path")
    raw = os.fspath(value)
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > MAX_ARTIFACT_CHARS
        or "\\" in raw
        or any(character in raw for character in ("\x00", "\n", "\r", "\t"))
    ):
        raise ValueError(f"{field} must be a safe repository-relative path")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or path.as_posix() != raw
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{field} must be a canonical repository-relative path")
    return raw


def _registered_remediation_artifacts(config: Any) -> frozenset[str]:
    if isinstance(config, Mapping):
        manifest = config.get("manifest_path", "dochub.yaml")
        explicit = config.get("remediation_artifacts")
    else:
        manifest = "dochub.yaml"
        explicit = None
    if explicit is not None:
        if (
            not isinstance(explicit, Sequence)
            or isinstance(explicit, (str, bytes))
            or not explicit
            or len(explicit) > MAX_REMEDIATION_ARTIFACTS
        ):
            raise ValueError(
                "remediation_artifacts must be a non-empty bounded path array"
            )
        artifacts = frozenset(
            _registry_artifact_label(
                item, field=f"remediation_artifacts[{index}]"
            )
            for index, item in enumerate(explicit)
        )
        if len(artifacts) != len(explicit):
            raise ValueError("remediation_artifacts must be unique")
        if any(PurePosixPath(item).name != "integrations.yaml" for item in artifacts):
            raise ValueError(
                "remediation_artifacts may contain only integrations.yaml documents"
            )
        return artifacts

    manifest_path = PurePosixPath(
        _registry_artifact_label(manifest, field="manifest_path")
    )
    model_directory = (
        PurePosixPath("model")
        if str(manifest_path.parent) == "."
        else manifest_path.parent / "model"
    )
    return frozenset({(model_directory / "integrations.yaml").as_posix()})


def _clone(value: Any) -> Any:
    return deepcopy(value)


def _safe_error_message(value: Any) -> str:
    text = str(value or "remediation is not available")
    return text.replace("\x00", "")[:MAX_ERROR_CHARS]


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


class RemediationService:
    """Prepare and finalize one exact architecture remediation candidate."""

    def __init__(
        self,
        *,
        repositories: Mapping[str, Any],
        ttl_seconds: float = 900.0,
        max_reviews: int = 128,
        max_remediations: int = 128,
        max_store_bytes: int = 67_108_864,
        prepare_timeout_seconds: float = 30.0,
        max_prepare_workers: int = 4,
        digest_secret: bytes | str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            ttl_seconds <= 0
            or max_reviews <= 0
            or max_remediations <= 0
            or max_store_bytes <= 0
            or isinstance(prepare_timeout_seconds, bool)
            or prepare_timeout_seconds <= 0
            or isinstance(max_prepare_workers, bool)
            or not isinstance(max_prepare_workers, int)
            or max_prepare_workers <= 0
        ):
            raise ValueError(
                "TTL, remediation store limits and prepare bounds must be positive"
            )
        if not isinstance(repositories, Mapping) or not repositories:
            raise ValueError("at least one trusted repository must be registered")
        registered: dict[str, Any] = {}
        remediation_artifacts: dict[str, frozenset[str]] = {}
        for repository_id, config in repositories.items():
            if not isinstance(repository_id, str) or ID_RE.fullmatch(repository_id) is None:
                raise ValueError("repository keys must be non-path identifiers")
            if not isinstance(config, (str, os.PathLike, Mapping)):
                raise ValueError("registered repository config is invalid")
            copied_config = deepcopy(dict(config)) if isinstance(config, Mapping) else config
            registered[repository_id] = copied_config
            remediation_artifacts[repository_id] = _registered_remediation_artifacts(
                copied_config
            )
        if digest_secret is None:
            secret = secrets.token_bytes(32)
        elif isinstance(digest_secret, str):
            secret = digest_secret.encode("utf-8")
        elif isinstance(digest_secret, bytes):
            secret = digest_secret
        else:
            raise TypeError("digest_secret must be bytes, str, or None")
        if not secret:
            raise ValueError("digest_secret must not be empty")

        self._repositories = registered
        self._remediation_artifacts = remediation_artifacts
        self._secret = secret
        self._ttl_seconds = float(ttl_seconds)
        self._max_reviews = int(max_reviews)
        self._max_remediations = int(max_remediations)
        self._max_store_bytes = int(max_store_bytes)
        self._prepare_timeout_seconds = float(prepare_timeout_seconds)
        self._prepare_slots = threading.BoundedSemaphore(max_prepare_workers)
        self._clock = clock
        self._lock = threading.RLock()
        self._closed = False
        self._reviews: OrderedDict[str, TrustedFinalizedReview] = OrderedDict()
        self._remediations: OrderedDict[str, _StoredRemediation] = OrderedDict()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._reviews.clear()
            self._remediations.clear()

    @property
    def trusted_review_count(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._reviews)

    @property
    def remediation_count(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._remediations)

    def _require_open(self) -> None:
        if self._closed:
            raise RemediationServiceError(
                "service_stopped", "remediation service is stopped"
            )

    def _purge_expired_locked(self) -> None:
        now = self._clock()
        for key in [
            key for key, value in self._reviews.items() if value.expires_at <= now
        ]:
            self._reviews.pop(key, None)
        for key in [
            key
            for key, value in self._remediations.items()
            if value.expires_at <= now
        ]:
            self._remediations.pop(key, None)

    def _stored_bytes_locked(self) -> int:
        return sum(item.size_bytes for item in self._reviews.values()) + sum(
            item.size_bytes for item in self._remediations.values()
        )

    def _trim_locked(self, *, protected_kind: str, protected_id: str) -> None:
        while (
            len(self._reviews) > self._max_reviews
            or len(self._remediations) > self._max_remediations
            or self._stored_bytes_locked() > self._max_store_bytes
        ):
            victim: tuple[str, str] | None = None
            if self._reviews:
                candidate = next(iter(self._reviews))
                if not (protected_kind == "review" and candidate == protected_id):
                    victim = ("review", candidate)
            if victim is None and self._remediations:
                candidate = next(iter(self._remediations))
                if not (
                    protected_kind == "remediation" and candidate == protected_id
                ):
                    victim = ("remediation", candidate)
            if victim is None:
                raise RemediationServiceError(
                    "remediation_store_limit",
                    "trusted state cannot fit in the bounded remediation store",
                )
            collection = self._reviews if victim[0] == "review" else self._remediations
            collection.pop(victim[1], None)

    @staticmethod
    def _validate_final_review_shape(value: Mapping[str, Any]) -> None:
        required = {
            "schema",
            "status",
            "review_id",
            "review_digest",
            "task_digest",
            "review_provenance_json",
            "findings",
            "observations",
            "completed_rule_ids",
            "missing_rule_ids",
            "analysis_errors",
            "verdict",
            "escalate",
            "human_review_required",
            "auto_merge",
            "incomplete",
        }
        if set(value) != required:
            raise RemediationServiceError(
                "trusted_review_invalid",
                "trusted final review does not have the exact final schema",
            )
        findings = value.get("findings")
        if (
            value.get("schema") != "aga.final-review/v1"
            or value.get("status") != "completed"
            or value.get("incomplete") is not False
            or value.get("verdict") == "incomplete"
            or value.get("auto_merge") is not False
            or not isinstance(findings, list)
            or len(findings) > MAX_FINDINGS
            or any(not isinstance(item, Mapping) for item in findings)
            or not isinstance(value.get("review_provenance_json"), str)
            or not isinstance(value.get("observations"), list)
            or value.get("completed_rule_ids") != list(SEMANTIC_RULE_IDS)
            or value.get("missing_rule_ids") != []
            or value.get("analysis_errors") != []
            or not isinstance(value.get("escalate"), bool)
            or not isinstance(value.get("human_review_required"), bool)
        ):
            raise RemediationServiceError(
                "trusted_review_invalid",
                "only a complete trusted AGA final review can be registered",
            )

    def register_trusted_review(
        self,
        *,
        repository_id: Any,
        base: Any,
        head: Any,
        final_review: Mapping[str, Any],
        final_output_sha256: Any,
    ) -> str:
        """Register a final already validated against a trusted MCP receipt.

        This is a host-only operation, deliberately absent from
        :data:`TOOL_DEFINITIONS_REMEDIATION`.  ``final_output_sha256`` must be
        the output hash from the trusted ``aga_finalize_review`` receipt.
        """

        self._require_open()
        repository_id = _identifier(repository_id, "repository_id")
        if repository_id not in self._repositories:
            raise RemediationServiceError(
                "repository_unavailable", "repository_id is not registered"
            )
        base = _revision(base, "base")
        head = _revision(head, "head")
        final_output_sha256 = _sha256(
            final_output_sha256, "final_output_sha256"
        )
        if not isinstance(final_review, Mapping):
            raise RemediationServiceError(
                "trusted_review_invalid", "final review must be an object"
            )
        final = _clone(dict(final_review))
        try:
            raw = _canonical_bytes(final)
        except (TypeError, ValueError) as exc:
            raise RemediationServiceError(
                "trusted_review_invalid", "final review is not strict JSON"
            ) from exc
        if len(raw) > MAX_FINAL_REVIEW_BYTES:
            raise RemediationServiceError(
                "trusted_review_invalid", "final review exceeds its byte limit"
            )
        if hashlib.sha256(raw).hexdigest() != final_output_sha256:
            raise RemediationServiceError(
                "trusted_review_hash_mismatch",
                "final review does not match its trusted receipt hash",
            )
        self._validate_final_review_shape(final)
        review_id = _identifier(final.get("review_id"), "review_id")
        review_digest = _review_digest(
            final.get("review_digest"), "review_digest", "rvw"
        )
        task_digest = _review_digest(final.get("task_digest"), "task_digest", "tsk")
        for finding in final["findings"]:
            finding_base = finding.get("base_revision")
            finding_head = finding.get("head_revision")
            if finding_base != base or finding_head != head:
                raise RemediationServiceError(
                    "trusted_review_invalid",
                    "finding revision provenance does not match the trusted review",
                )

        if len(raw) > self._max_store_bytes:
            raise RemediationServiceError(
                "remediation_store_limit",
                "trusted final review cannot fit in the bounded remediation store",
            )

        fingerprint = canonical_sha256(
            {
                "repository_id": repository_id,
                "base": base,
                "head": head,
                "output_sha256": final_output_sha256,
            }
        )
        stored = TrustedFinalizedReview(
            repository_id=repository_id,
            base=base,
            head=head,
            review_id=review_id,
            review_digest=review_digest,
            task_digest=task_digest,
            output_sha256=final_output_sha256,
            final=final,
            expires_at=self._clock() + self._ttl_seconds,
            size_bytes=len(raw),
        )
        with self._lock:
            self._require_open()
            self._purge_expired_locked()
            existing = self._reviews.get(review_id)
            if existing is not None:
                existing_fingerprint = canonical_sha256(
                    {
                        "repository_id": existing.repository_id,
                        "base": existing.base,
                        "head": existing.head,
                        "output_sha256": existing.output_sha256,
                    }
                )
                if not hmac.compare_digest(existing_fingerprint, fingerprint):
                    raise RemediationServiceError(
                        "trusted_review_conflict",
                        "review_id is already bound to a different trusted final",
                    )
                self._reviews.move_to_end(review_id)
                return review_id
            self._reviews[review_id] = stored
            self._reviews.move_to_end(review_id)
            self._trim_locked(protected_kind="review", protected_id=review_id)
        return review_id

    def _repository_builder(
        self, repository_id: str, base: str, head: str
    ) -> RepositorySnapshotBuilder:
        raw = self._repositories[repository_id]
        if isinstance(raw, Mapping):
            repository = raw.get("repository") or raw.get("root")
            options = {
                key: raw[key]
                for key in (
                    "manifest_path",
                    "scope_prefix",
                    "archtool_commit",
                    "seaf_core_commit",
                    "dependency_mode",
                    "trusted_dependencies",
                    "aga_version",
                    "rules_dir",
                )
                if key in raw and raw[key] is not None
            }
        else:
            repository = raw
            options = {}
        if not isinstance(repository, (str, os.PathLike)):
            raise RemediationServiceError(
                "repository_unavailable", "registered repository config is invalid"
            )
        try:
            return RepositorySnapshotBuilder(
                repository=Path(repository),
                base_revision=base,
                head_revision=head,
                **options,
            )
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            raise RemediationServiceError(
                "repository_snapshot_invalid",
                "immutable repository snapshot could not be configured",
            ) from exc

    @staticmethod
    def _validate_supported_finding(
        finding: Mapping[str, Any], *, base: str, head: str
    ) -> None:
        entity_id = finding.get("entity_id")
        artifact = _artifact_label(finding.get("artifact"))
        location = finding.get("location")
        canonical_defect = finding.get("canonical_defect")
        confidence = finding.get("confidence")
        if (
            finding.get("rule_id") != "SEAF-004"
            or finding.get("origin") != "deterministic"
            or finding.get("severity") != "blocker"
            or isinstance(confidence, bool)
            or confidence != 1.0
            or not isinstance(entity_id, str)
            or INTEGRATION_ID_RE.fullmatch(entity_id) is None
            or not isinstance(location, str)
            or finding.get("base_revision") != base
            or finding.get("head_revision") != head
            or canonical_defect != f"SEAF-004:{location}"
        ):
            raise RemediationServiceError(
                "finding_not_remediable",
                "selected finding is not a supported trusted SEAF-004 blocker",
            )
        endpoint = location.rsplit("/", 1)[-1]
        expected_location = (
            f"/seaf.app.integrations/{_json_pointer_token(entity_id)}/{endpoint}"
        )
        provenance = finding.get("source_provenance")
        if (
            endpoint not in {"from", "to"}
            or location != expected_location
            or not isinstance(provenance, Mapping)
            or set(provenance) != {"file", "pointer", "commit", "line", "sha256"}
            or provenance.get("file") != artifact
            or provenance.get("commit") != head
            or not isinstance(provenance.get("pointer"), str)
            or location != f"{provenance['pointer']}/{endpoint}"
            or SHA256_RE.fullmatch(str(provenance.get("sha256") or "")) is None
        ):
            raise RemediationServiceError(
                "trusted_finding_invalid",
                "selected finding is not bound to immutable endpoint evidence",
            )

    def _compute_patch(
        self,
        *,
        repository_id: str,
        base: str,
        head: str,
        finding: Mapping[str, Any],
        artifact: str,
    ) -> tuple[RemediationPatch | None, str | None, str | None]:
        """Compute against Git objects only; this worker never mutates service state."""

        builder = self._repository_builder(repository_id, base, head)
        try:
            with builder.build() as snapshot:
                if (
                    snapshot.revision.base_commit != base
                    or snapshot.revision.head_commit != head
                ):
                    raise RemediationServiceError(
                        "repository_snapshot_mismatch",
                        "snapshot revisions do not match remediation correlation",
                    )
                materialized_hashes = dict(snapshot.materialized_hashes)
                provenance = finding["source_provenance"]
                if materialized_hashes.get(artifact) != provenance.get("sha256"):
                    raise RemediationServiceError(
                        "trusted_finding_mismatch",
                        "finding artifact hash does not match immutable Git head",
                    )
                try:
                    patch = propose_remediation(finding, snapshot.root)
                except RemediationNotAvailable as exc:
                    return None, exc.code, _safe_error_message(exc.reason)
                return patch, None, None
        except RemediationServiceError:
            raise
        except (OSError, TypeError, ValueError, ValidationError) as exc:
            raise RemediationServiceError(
                "repository_snapshot_invalid",
                "immutable repository snapshot could not be prepared",
            ) from exc

    def _bounded_compute_patch(
        self,
        *,
        repository_id: str,
        base: str,
        head: str,
        finding: Mapping[str, Any],
        artifact: str,
    ) -> tuple[RemediationPatch | None, str | None, str | None]:
        if not self._prepare_slots.acquire(blocking=False):
            raise RemediationServiceError(
                "remediation_busy",
                "bounded remediation prepare workers are exhausted",
                retryable=True,
            )
        responses: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                responses.put(
                    (
                        True,
                        self._compute_patch(
                            repository_id=repository_id,
                            base=base,
                            head=head,
                            finding=finding,
                            artifact=artifact,
                        ),
                    )
                )
            except BaseException as exc:
                responses.put((False, exc))
            finally:
                self._prepare_slots.release()

        worker = threading.Thread(
            target=invoke,
            name="aga-remediation-prepare",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError as exc:
            self._prepare_slots.release()
            raise RemediationServiceError(
                "remediation_unavailable",
                "bounded remediation prepare worker could not start",
                retryable=True,
            ) from exc
        try:
            succeeded, value = responses.get(timeout=self._prepare_timeout_seconds)
        except queue.Empty as exc:
            raise RemediationServiceError(
                "remediation_timeout",
                "immutable remediation preparation timed out",
                retryable=True,
            ) from exc
        if succeeded:
            return value
        if isinstance(value, RemediationServiceError):
            raise value
        raise RemediationServiceError(
            "remediation_unavailable",
            "immutable remediation preparation failed",
        ) from value

    def _get_trusted_review(
        self,
        *,
        repository_id: str,
        base: str,
        head: str,
        review_id: str,
        review_digest: str,
        task_digest: str,
    ) -> TrustedFinalizedReview:
        with self._lock:
            self._require_open()
            self._purge_expired_locked()
            stored = self._reviews.get(review_id)
            if stored is None:
                raise RemediationServiceError(
                    "trusted_review_not_found",
                    "trusted finalized review is absent or expired",
                )
            if (
                stored.repository_id != repository_id
                or stored.base != base
                or stored.head != head
                or not hmac.compare_digest(stored.review_digest, review_digest)
                or not hmac.compare_digest(stored.task_digest, task_digest)
            ):
                raise RemediationServiceError(
                    "trusted_review_mismatch",
                    "remediation correlation does not match the trusted final review",
                )
            self._reviews.move_to_end(review_id)
            return stored

    def _opaque(self, value: Any) -> str:
        digest = hmac.new(self._secret, _canonical_bytes(value), hashlib.sha256).hexdigest()
        return f"rmd_{digest}"

    def prepare_remediation(
        self,
        *,
        repository_id: Any,
        base: Any,
        head: Any,
        review_id: Any,
        review_digest: Any,
        task_digest: Any,
        remediation_id: Any,
        finding_sha256: Any,
    ) -> dict[str, Any]:
        """Prepare one candidate from an exact trusted finding and Git head."""

        self._require_open()
        repository_id = _identifier(repository_id, "repository_id")
        if repository_id not in self._repositories:
            raise RemediationServiceError(
                "repository_unavailable", "repository_id is not registered"
            )
        base = _revision(base, "base")
        head = _revision(head, "head")
        review_id = _identifier(review_id, "review_id")
        review_digest = _review_digest(review_digest, "review_digest", "rvw")
        task_digest = _review_digest(task_digest, "task_digest", "tsk")
        remediation_id = _identifier(remediation_id, "remediation_id")
        selected_finding_sha256 = _sha256(finding_sha256, "finding_sha256")
        request = {
            "repository_id": repository_id,
            "base": base,
            "head": head,
            "review_id": review_id,
            "review_digest": review_digest,
            "task_digest": task_digest,
            "remediation_id": remediation_id,
            "finding_sha256": selected_finding_sha256,
        }
        request_fingerprint = canonical_sha256(request)
        with self._lock:
            self._purge_expired_locked()
            existing = self._remediations.get(remediation_id)
            if existing is not None:
                if not hmac.compare_digest(
                    existing.request_fingerprint, request_fingerprint
                ):
                    raise RemediationServiceError(
                        "remediation_conflict",
                        "remediation_id is already bound to different inputs",
                    )
                self._remediations.move_to_end(remediation_id)
                return _clone(existing.prepared)

        trusted = self._get_trusted_review(
            repository_id=repository_id,
            base=base,
            head=head,
            review_id=review_id,
            review_digest=review_digest,
            task_digest=task_digest,
        )
        matches = [
            dict(item)
            for item in trusted.final["findings"]
            if _finding_sha256(item) == selected_finding_sha256
        ]
        if not matches:
            raise RemediationServiceError(
                "finding_not_found",
                "finding digest is absent from the trusted finalized review",
            )
        if len(matches) != 1:
            raise RemediationServiceError(
                "finding_ambiguous",
                "finding digest is not unique in the trusted finalized review",
            )
        finding = matches[0]
        self._validate_supported_finding(finding, base=base, head=head)
        if (
            trusted.final.get("verdict") != "request_changes_escalate"
            or trusted.final.get("escalate") is not True
            or trusted.final.get("human_review_required") is not True
        ):
            raise RemediationServiceError(
                "trusted_review_invalid",
                "a remediable blocker requires an escalated human-review verdict",
            )
        artifact = _artifact_label(finding.get("artifact"))
        if artifact not in self._remediation_artifacts[repository_id]:
            raise RemediationServiceError(
                "finding_not_remediable",
                "selected finding is outside the host-registered remediation scope",
            )

        patch, reason_code, reason_message = self._bounded_compute_patch(
            repository_id=repository_id,
            base=base,
            head=head,
            finding=finding,
            artifact=artifact,
        )

        material = {
            "request": request,
            "review_output_sha256": trusted.output_sha256,
            "candidate": patch.candidate_dict() if patch is not None else None,
            "reason_code": reason_code,
        }
        remediation_digest = self._opaque(material)
        prepared: dict[str, Any] = {
            "schema": "aga.prepare-remediation/v1",
            "status": "ready" if patch is not None else "remediation_not_available",
            **request,
            "review_output_sha256": trusted.output_sha256,
            "remediation_digest": remediation_digest,
            "analysis_errors": [],
            "human_review_required": True,
            "auto_merge": False,
            "incomplete": patch is None,
        }
        if patch is not None:
            prepared["candidate"] = patch.candidate_dict()
            prepared["candidate_sha256"] = patch.candidate_sha256()
        else:
            prepared["reason_code"] = reason_code or "remediation_not_available"
            prepared["analysis_errors"] = [
                {
                    "code": prepared["reason_code"],
                    "message": reason_message or "remediation requires human input",
                }
            ]
        size_bytes = len(_canonical_bytes(prepared))
        if patch is not None:
            size_bytes += len(patch.before_text.encode("utf-8")) + len(
                patch.after_text.encode("utf-8")
            )
        if size_bytes > self._max_store_bytes:
            raise RemediationServiceError(
                "remediation_store_limit",
                "prepared remediation cannot fit in the bounded state store",
            )
        stored_remediation = _StoredRemediation(
            request_fingerprint=request_fingerprint,
            expires_at=self._clock() + self._ttl_seconds,
            prepared=_clone(prepared),
            patch=patch,
            size_bytes=size_bytes,
        )
        with self._lock:
            self._require_open()
            self._purge_expired_locked()
            existing = self._remediations.get(remediation_id)
            if existing is not None:
                if not hmac.compare_digest(
                    existing.request_fingerprint, request_fingerprint
                ):
                    raise RemediationServiceError(
                        "remediation_conflict",
                        "remediation_id was concurrently bound to different inputs",
                    )
                return _clone(existing.prepared)
            if self._reviews.get(review_id) is not trusted:
                raise RemediationServiceError(
                    "trusted_review_not_found",
                    "trusted finalized review expired during remediation preparation",
                )
            self._remediations[remediation_id] = stored_remediation
            self._remediations.move_to_end(remediation_id)
            self._trim_locked(
                protected_kind="remediation", protected_id=remediation_id
            )
        return _clone(prepared)

    def finalize_remediation(
        self,
        *,
        remediation_id: Any,
        remediation_digest: Any,
        candidate: Any = None,
    ) -> dict[str, Any]:
        """First-write finalize of the exact candidate returned by prepare."""

        self._require_open()
        remediation_id = _identifier(remediation_id, "remediation_id")
        remediation_digest = _remediation_digest(remediation_digest)
        try:
            final_fingerprint = canonical_sha256({"candidate": candidate})
        except (TypeError, ValueError) as exc:
            raise RemediationInputError(
                "must be strict JSON", field="candidate"
            ) from exc
        with self._lock:
            self._purge_expired_locked()
            stored = self._remediations.get(remediation_id)
            if stored is None:
                raise RemediationServiceError(
                    "remediation_not_found", "remediation is absent or expired"
                )
            expected_digest = stored.prepared["remediation_digest"]
            if not hmac.compare_digest(expected_digest, remediation_digest):
                raise RemediationServiceError(
                    "remediation_digest_mismatch",
                    "remediation digest does not match prepared state",
                )
            if stored.final_result is not None:
                if not hmac.compare_digest(
                    stored.final_fingerprint or "", final_fingerprint
                ):
                    raise RemediationServiceError(
                        "remediation_finalization_conflict",
                        "remediation was already finalized with a different candidate",
                    )
                return _clone(stored.final_result)

            prepared = stored.prepared
            result: dict[str, Any] = {
                "schema": "aga.final-remediation/v1",
                "status": "completed",
                "outcome": "candidate_ready",
                "repository_id": prepared["repository_id"],
                "base": prepared["base"],
                "head": prepared["head"],
                "review_id": prepared["review_id"],
                "review_digest": prepared["review_digest"],
                "task_digest": prepared["task_digest"],
                "review_output_sha256": prepared["review_output_sha256"],
                "remediation_id": remediation_id,
                "remediation_digest": remediation_digest,
                "finding_sha256": prepared["finding_sha256"],
                "analysis_errors": [],
                "human_review_required": True,
                "auto_merge": False,
                "incomplete": False,
            }
            if stored.patch is not None:
                expected_candidate = stored.patch.candidate_dict()
                if not isinstance(candidate, Mapping) or dict(candidate) != expected_candidate:
                    raise RemediationServiceError(
                        "candidate_mismatch",
                        "finalize candidate differs from the exact prepared candidate",
                    )
                result["candidate_sha256"] = stored.patch.candidate_sha256()
                result["patch"] = stored.patch.as_dict()
            else:
                if candidate is not None:
                    raise RemediationServiceError(
                        "candidate_unavailable",
                        "no candidate may be supplied when remediation is unavailable",
                    )
                result.update(
                    {
                        "status": "remediation_not_available",
                        "outcome": "hitl_required",
                        "reason_code": prepared["reason_code"],
                        "analysis_errors": _clone(prepared["analysis_errors"]),
                        "incomplete": True,
                    }
                )
            final_result = _clone(result)
            final_size = len(_canonical_bytes(final_result))
            combined_size = stored.size_bytes + final_size
            if combined_size > self._max_store_bytes:
                raise RemediationServiceError(
                    "remediation_store_limit",
                    "prepared and final remediation exceed the bounded state store",
                )
            stored.final_fingerprint = final_fingerprint
            stored.final_result = final_result
            stored.size_bytes = combined_size
            self._remediations.move_to_end(remediation_id)
            self._trim_locked(
                protected_kind="remediation", protected_id=remediation_id
            )
            return _clone(final_result)


def _object_schema(
    properties: Mapping[str, Any], required: Sequence[str]
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": dict(properties),
        "required": list(required),
    }


ANALYSIS_ERROR_SCHEMA: dict[str, Any] = _object_schema(
    {"code": {"type": "string"}, "message": {"type": "string"}},
    ["code", "message"],
)

CANDIDATE_SCHEMA: dict[str, Any] = _object_schema(
    {
        "rule_id": {"type": "string", "const": "SEAF-004"},
        "entity_id": {"type": "string", "pattern": INTEGRATION_ID_RE.pattern},
        "artifact": {"type": "string"},
        "mutation_kind": {"type": "string", "const": "reroute_target"},
        "endpoint": {"type": "string", "enum": ["from", "to"]},
        "eliminated_component": {
            "type": "string",
            "pattern": COMPONENT_ID_RE.pattern,
        },
        "replacement_component": {
            "type": "string",
            "pattern": COMPONENT_ID_RE.pattern,
        },
        "summary": {"type": "string"},
        "before_sha256": {"type": "string", "pattern": SHA256_RE.pattern},
        "after_sha256": {"type": "string", "pattern": SHA256_RE.pattern},
        "diff_sha256": {"type": "string", "pattern": SHA256_RE.pattern},
    },
    [
        "rule_id",
        "entity_id",
        "artifact",
        "mutation_kind",
        "endpoint",
        "eliminated_component",
        "replacement_component",
        "summary",
        "before_sha256",
        "after_sha256",
        "diff_sha256",
    ],
)

PATCH_SCHEMA: dict[str, Any] = _object_schema(
    {**CANDIDATE_SCHEMA["properties"], "diff": {"type": "string"}},
    [*CANDIDATE_SCHEMA["required"], "diff"],
)

_CORRELATION_PROPERTIES: dict[str, Any] = {
    "repository_id": {"type": "string", "pattern": ID_RE.pattern},
    "base": {"type": "string", "pattern": REVISION_RE.pattern},
    "head": {"type": "string", "pattern": REVISION_RE.pattern},
    "review_id": {"type": "string", "pattern": ID_RE.pattern},
    "review_digest": {"type": "string", "pattern": r"^rvw_[0-9a-f]{64}$"},
    "task_digest": {"type": "string", "pattern": r"^tsk_[0-9a-f]{64}$"},
    "remediation_id": {"type": "string", "pattern": ID_RE.pattern},
    "finding_sha256": {"type": "string", "pattern": SHA256_RE.pattern},
}

_CORRELATION_REQUIRED = list(_CORRELATION_PROPERTIES)

TOOL_DEFINITIONS_REMEDIATION: tuple[dict[str, Any], ...] = (
    {
        "name": "aga_prepare_remediation",
        "description": (
            "Prepare one deterministic SEAF-004 candidate from an exact trusted "
            "finalized review and immutable registered Git revision. Filesystem "
            "paths are never accepted."
        ),
        "inputSchema": _object_schema(
            _CORRELATION_PROPERTIES,
            _CORRELATION_REQUIRED,
        ),
        "outputSchema": _object_schema(
            {
                "schema": {
                    "type": "string",
                    "const": "aga.prepare-remediation/v1",
                },
                "status": {
                    "type": "string",
                    "enum": ["ready", "remediation_not_available"],
                },
                **_CORRELATION_PROPERTIES,
                "review_output_sha256": {
                    "type": "string",
                    "pattern": SHA256_RE.pattern,
                },
                "remediation_digest": {
                    "type": "string",
                    "pattern": REMEDIATION_DIGEST_RE.pattern,
                },
                "candidate": CANDIDATE_SCHEMA,
                "candidate_sha256": {
                    "type": "string",
                    "pattern": SHA256_RE.pattern,
                },
                "reason_code": {"type": "string"},
                "analysis_errors": {
                    "type": "array",
                    "items": ANALYSIS_ERROR_SCHEMA,
                },
                "human_review_required": {"type": "boolean", "const": True},
                "auto_merge": {"type": "boolean", "const": False},
                "incomplete": {"type": "boolean"},
            },
            [
                "schema",
                "status",
                *_CORRELATION_REQUIRED,
                "review_output_sha256",
                "remediation_digest",
                "analysis_errors",
                "human_review_required",
                "auto_merge",
                "incomplete",
            ],
        ),
    },
    {
        "name": "aga_finalize_remediation",
        "description": (
            "First-write finalize of the exact candidate returned by "
            "aga_prepare_remediation. Returns a trusted minimal diff but never "
            "writes, commits, pushes, approves or merges."
        ),
        "inputSchema": _object_schema(
            {
                "remediation_id": {
                    "type": "string",
                    "pattern": ID_RE.pattern,
                },
                "remediation_digest": {
                    "type": "string",
                    "pattern": REMEDIATION_DIGEST_RE.pattern,
                },
                "candidate": CANDIDATE_SCHEMA,
            },
            ["remediation_id", "remediation_digest"],
        ),
        "outputSchema": _object_schema(
            {
                "schema": {
                    "type": "string",
                    "const": "aga.final-remediation/v1",
                },
                "status": {
                    "type": "string",
                    "enum": ["completed", "remediation_not_available", "incomplete"],
                },
                "outcome": {
                    "type": "string",
                    "enum": ["candidate_ready", "hitl_required"],
                },
                **_CORRELATION_PROPERTIES,
                "review_output_sha256": {
                    "type": "string",
                    "pattern": SHA256_RE.pattern,
                },
                "remediation_digest": {
                    "type": "string",
                    "pattern": REMEDIATION_DIGEST_RE.pattern,
                },
                "candidate_sha256": {
                    "type": "string",
                    "pattern": SHA256_RE.pattern,
                },
                "patch": PATCH_SCHEMA,
                "reason_code": {"type": "string"},
                "analysis_errors": {
                    "type": "array",
                    "items": ANALYSIS_ERROR_SCHEMA,
                },
                "human_review_required": {"type": "boolean", "const": True},
                "auto_merge": {"type": "boolean", "const": False},
                "incomplete": {"type": "boolean"},
            },
            [
                "schema",
                "status",
                "outcome",
                *_CORRELATION_REQUIRED,
                "review_output_sha256",
                "remediation_digest",
                "analysis_errors",
                "human_review_required",
                "auto_merge",
                "incomplete",
            ],
        ),
    },
)

# Compatibility alias matching the integration task's requested export name.
TOOL_DEFINITIONS_REMediation = TOOL_DEFINITIONS_REMEDIATION


__all__ = [
    "ANALYSIS_ERROR_SCHEMA",
    "CANDIDATE_SCHEMA",
    "PATCH_SCHEMA",
    "REMEDIATION_DIGEST_RE",
    "RemediationInputError",
    "RemediationService",
    "RemediationServiceError",
    "TOOL_DEFINITIONS_REMEDIATION",
    "TOOL_DEFINITIONS_REMediation",
    "TrustedFinalizedReview",
    "canonical_sha256",
    "finding_sha256",
]
