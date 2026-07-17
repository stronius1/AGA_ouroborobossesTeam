# -*- coding: utf-8 -*-
"""Stateful, fail-closed review boundary used by the AGA MCP transport.

The service deliberately accepts repository and entity identifiers, never a
client supplied filesystem path.  A trusted server-side callback resolves a
repository identifier and materialises the SEAF snapshot.  Prepared evidence
is copied into a small, expiring store so later agent calls cannot silently
switch revisions.

There is no model or network adapter in this module.  Semantic output is
accepted only as strict JSON and is checked against the evidence and rule
catalog captured by :meth:`ReviewService.prepare_review`.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
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
from typing import Any

from tools.aga import deduplicate_findings, load_rules, verdict_from
from tools.llm import LLMSchemaError, merge_findings, validate_finding


SEMANTIC_RULE_IDS = ("PRIN-004", "PRIN-005", "PRIN-006", "PRIN-007")
SEMANTIC_STATUSES = frozenset(
    {"completed", "incomplete", "error", "timeout", "unavailable"}
)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
REVISION_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
DIGEST_RE = re.compile(r"^(?:rvw|tsk|ev)_[0-9a-f]{64}$")
JSON_POINTER_RE = re.compile(r"^(?:/(?:[^~/]|~[01])*)*$")
SCOPE_KIND_ALIASES = {
    "system_passport": {"system", "system_passport", "seaf.app.system"},
    "integration_flow": {"integration", "integration_flow", "seaf.app.integration"},
    "adr": {"adr", "decision"},
    "diagram": {"diagram"},
}
MAX_TEXT_CHARS = 16_000


class ReviewServiceError(RuntimeError):
    """Stable error suitable for an MCP structured error response."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "review_service_error",
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


class ReviewInputError(ReviewServiceError, ValueError):
    """A caller supplied value does not satisfy the public contract."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        suffix = f" ({field})" if field else ""
        super().__init__("invalid_arguments", f"{message}{suffix}")

    def as_dict(self) -> dict[str, Any]:
        result = super().as_dict()
        result["field"] = self.field
        return result


class _SemanticEvidenceError(ReviewInputError):
    """A schema-valid semantic location is not bound to prepared evidence."""


@dataclass
class _StoredReview:
    request_fingerprint: str
    expires_at: float
    prepared: dict[str, Any]
    artifacts: dict[str, dict[str, Any]]
    evidence: dict[str, str]
    catalog: dict[str, dict[str, Any]]
    policy: dict[str, Any]
    size_bytes: int
    final_fingerprint: str | None = None
    final_result: dict[str, Any] | None = None


PrepareCallback = Callable[..., Mapping[str, Any]]


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReviewServiceError(
            "prepare_schema_error", "prepare callback returned non-JSON data"
        ) from exc


def _strict_json_loads(value: str | bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    def invalid_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(
        value,
        object_pairs_hook=object_pairs,
        parse_constant=invalid_constant,
    )


def _clone(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewInputError("must be an object", field=field)
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ReviewInputError(
            "must be a non-path identifier containing only letters, digits, '.', ':', '@', '_' or '-'",
            field=field,
        )
    return value


def _revision(value: Any, field: str) -> str:
    if not isinstance(value, str) or not REVISION_RE.fullmatch(value):
        raise ReviewInputError(
            "must be a full 40- or 64-character hexadecimal commit id", field=field
        )
    return value.lower()


def _bounded_text(value: Any, field: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ReviewInputError("must be a string", field=field)
    if not allow_empty and not value.strip():
        raise ReviewInputError("must not be empty", field=field)
    if len(value) > MAX_TEXT_CHARS:
        raise ReviewInputError(f"exceeds {MAX_TEXT_CHARS} characters", field=field)
    if "\x00" in value:
        raise ReviewInputError("contains a NUL character", field=field)
    return value


def _artifact_label(value: Any, field: str) -> str:
    text = _bounded_text(value, field, allow_empty=False).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or text.startswith("~"):
        raise ReviewServiceError(
            "prepare_schema_error", "trusted callback returned a non-relative artifact label"
        )
    return path.as_posix()


def _json_pointer_tokens(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, tuple[str, ...]]:
    """Return a canonical RFC 6901 pointer and its decoded tokens."""

    pointer = _bounded_text(value, field, allow_empty=allow_empty)
    if (not pointer and not allow_empty) or JSON_POINTER_RE.fullmatch(pointer) is None:
        raise ReviewInputError("must be a canonical RFC 6901 JSON Pointer", field=field)
    if not pointer:
        return pointer, ()
    tokens = tuple(
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer.split("/")[1:]
    )
    return pointer, tokens


def _pointer_suffix_resolves(value: Any, tokens: Sequence[str]) -> bool:
    """Resolve JSON Pointer suffix tokens against already parsed JSON data."""

    current = value
    for token in tokens:
        if isinstance(current, Mapping):
            if token not in current:
                return False
            current = current[token]
            continue
        if isinstance(current, list):
            if re.fullmatch(r"(?:0|[1-9][0-9]*)", token) is None:
                return False
            index = int(token)
            if index >= len(current):
                return False
            current = current[index]
            continue
        return False
    return True


def _scope_kinds(scope: Sequence[str]) -> set[str]:
    """Expand trusted catalog scope names to normalized prepared artifact kinds."""

    accepted: set[str] = set()
    for value in scope:
        accepted.update(SCOPE_KIND_ALIASES.get(value, {value}))
    return accepted


def _pointer_is_equal_or_descendant(pointer: Any, root: Any) -> bool:
    """Compare JSON Pointer token prefixes without string-prefix ambiguity."""

    try:
        _, pointer_tokens = _json_pointer_tokens(pointer, "pointer")
        _, root_tokens = _json_pointer_tokens(root, "root_pointer")
    except ReviewServiceError:
        return False
    return (
        len(pointer_tokens) >= len(root_tokens)
        and pointer_tokens[: len(root_tokens)] == root_tokens
    )


def _materialized_path_commit(
    path: str,
    head: str,
    dependency_commits: Sequence[tuple[str, str]],
) -> str:
    """Resolve an exact materialized path by the longest dependency prefix."""

    matches = [
        (prefix, commit)
        for prefix, commit in dependency_commits
        if path == prefix or path.startswith(f"{prefix}/")
    ]
    if not matches:
        return head
    return max(matches, key=lambda item: len(PurePosixPath(item[0]).parts))[1]


def _location_resolves_in_artifact(location: Any, artifact: Mapping[str, Any]) -> bool:
    """Return whether a canonical location is bound to one prepared entity."""

    try:
        _, location_tokens = _json_pointer_tokens(location, "finding.location")
        provenance = _require_mapping(
            artifact.get("source_provenance"), "artifact.source_provenance"
        )
        _, entity_tokens = _json_pointer_tokens(
            provenance.get("pointer"), "artifact.source_provenance.pointer"
        )
        prepared_data = json.loads(artifact["data_json"])
    except (ReviewServiceError, json.JSONDecodeError, TypeError, KeyError):
        return False
    if (
        len(location_tokens) < len(entity_tokens)
        or location_tokens[: len(entity_tokens)] != entity_tokens
    ):
        return False
    return _pointer_suffix_resolves(
        prepared_data, location_tokens[len(entity_tokens) :]
    )


def _provenance_for_location(
    artifact: Mapping[str, Any], location: Any
) -> Mapping[str, Any]:
    """Select entity or materialized-content provenance for one location."""

    content = artifact.get("content_provenance")
    if isinstance(content, Mapping) and _pointer_is_equal_or_descendant(
        location, content.get("pointer")
    ):
        return content
    return _require_mapping(
        artifact.get("source_provenance"), "artifact.source_provenance"
    )


def _strict_keys(
    value: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    field: str,
) -> None:
    keys = set(value)
    missing = sorted(required - keys)
    extra = sorted((str(key) for key in keys - allowed))
    if missing:
        raise ReviewInputError(f"missing fields: {', '.join(missing)}", field=field)
    if extra:
        raise ReviewInputError(f"unknown fields: {', '.join(extra)}", field=field)


class ReviewService:
    """Prepare, retrieve and finalize immutable SEAF review evidence.

    ``prepare_callback`` is a trusted integration hook.  It is called with
    keyword arguments ``repository_id``, ``base``, ``head``, ``review_id`` and
    ``entity_ids``.  Its mapping result may contain ``artifacts`` (or
    ``entities``), ``deterministic_findings``, ``analysis_errors`` and
    ``incomplete``.  Artifact entries use entity IDs and repository-relative
    labels; no local path is returned to the MCP caller.

    If no callback is supplied, ``repositories`` is a server-side registry
    used by the conservative SEAF-native default hook.  Registry values may
    also be callables, which is convenient for embedding the service.
    """

    def __init__(
        self,
        prepare_callback: PrepareCallback | None = None,
        *,
        repositories: Mapping[str, Any] | None = None,
        ttl_seconds: float = 900.0,
        max_reviews: int = 128,
        max_artifacts: int = 512,
        max_findings: int = 200,
        max_artifact_bytes: int = 256_000,
        prepare_timeout_seconds: float = 15.0,
        max_prepare_workers: int = 4,
        max_review_bytes: int = 16_777_216,
        max_store_bytes: int = 67_108_864,
        digest_secret: bytes | str | None = None,
        clock: Callable[[], float] = time.monotonic,
        rule_catalog: Mapping[str, Mapping[str, Any]] | None = None,
        verdict_policy: Mapping[str, Any] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or max_reviews <= 0 or max_artifacts <= 0:
            raise ValueError("TTL and store limits must be positive")
        if (
            max_findings <= 0
            or max_artifact_bytes <= 0
            or prepare_timeout_seconds <= 0
            or max_prepare_workers <= 0
            or max_review_bytes <= 0
            or max_store_bytes <= 0
        ):
            raise ValueError("review limits and timeouts must be positive")
        if max_review_bytes > max_store_bytes:
            raise ValueError("max_review_bytes must not exceed max_store_bytes")
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

        self._secret = secret
        self._prepare_callback = prepare_callback or self._default_prepare_callback
        self._repositories = dict(repositories or {})
        self._ttl_seconds = float(ttl_seconds)
        self._max_reviews = int(max_reviews)
        self._max_artifacts = int(max_artifacts)
        self._max_findings = int(max_findings)
        self._max_artifact_bytes = int(max_artifact_bytes)
        self._prepare_timeout_seconds = float(prepare_timeout_seconds)
        self._prepare_slots = threading.BoundedSemaphore(int(max_prepare_workers))
        self._max_review_bytes = int(max_review_bytes)
        self._max_store_bytes = int(max_store_bytes)
        self._clock = clock
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._reviews: OrderedDict[str, _StoredReview] = OrderedDict()

        if rule_catalog is None or verdict_policy is None:
            rules, loaded_policy = load_rules()
        else:
            rules, loaded_policy = [], dict(verdict_policy)
        if rule_catalog is None:
            catalog = {rule["id"]: dict(rule) for rule in rules if rule["id"] in SEMANTIC_RULE_IDS}
        else:
            catalog = {key: dict(value) for key, value in rule_catalog.items()}
        if set(catalog) != set(SEMANTIC_RULE_IDS):
            raise ValueError("semantic rule catalog must contain exactly PRIN-004..PRIN-007")
        for rule_id in SEMANTIC_RULE_IDS:
            rule = catalog[rule_id]
            for key in ("source_ref", "statement", "severity", "scope"):
                if key not in rule:
                    raise ValueError(f"semantic rule {rule_id} is missing {key}")
        self._catalog = catalog
        self._policy = dict(verdict_policy or loaded_policy)
        initial_verdicts = self._policy.get("verdict_policy")
        if (
            not isinstance(initial_verdicts, Mapping)
            or initial_verdicts.get("has_blocker") != "request_changes_escalate"
            or initial_verdicts.get("has_major") != "request_changes_escalate"
            or not isinstance(self._policy.get("autonomy"), Mapping)
            or self._policy["autonomy"].get("auto_merge") is not False
        ):
            raise ValueError("verdict policy must escalate blocker/major and forbid auto-merge")

    # -- lifecycle and store -------------------------------------------------

    def close(self) -> None:
        """Forget all prepared payloads during graceful shutdown."""
        self._closed.set()
        with self._lock:
            self._reviews.clear()

    @property
    def review_count(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._reviews)

    @property
    def stored_bytes(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return sum(item.size_bytes for item in self._reviews.values())

    @property
    def prepare_timeout_seconds(self) -> float:
        """Maximum time the trusted prepare hook may run before fail-closed output."""

        return self._prepare_timeout_seconds

    def _purge_expired_locked(self) -> None:
        now = self._clock()
        expired = [key for key, item in self._reviews.items() if item.expires_at <= now]
        for key in expired:
            self._reviews.pop(key, None)

    def _put_review(self, review_id: str, stored: _StoredReview) -> None:
        with self._lock:
            self._purge_expired_locked()
            self._reviews[review_id] = stored
            self._reviews.move_to_end(review_id)
            self._trim_store_locked(protected_review_id=review_id)

    def _trim_store_locked(self, *, protected_review_id: str) -> None:
        while (
            len(self._reviews) > self._max_reviews
            or sum(item.size_bytes for item in self._reviews.values()) > self._max_store_bytes
        ):
            victim = next(
                (key for key in self._reviews if key != protected_review_id), None
            )
            if victim is None:
                raise ReviewServiceError(
                    "review_store_limit", "review cannot fit in the bounded store"
                )
            self._reviews.pop(victim, None)

    def _get_review(
        self,
        review_id: Any,
        review_digest: Any,
        task_digest: Any | None = None,
    ) -> _StoredReview:
        if self._closed.is_set():
            raise ReviewServiceError("service_stopped", "review service is stopped")
        safe_id = _identifier(review_id, "review_id")
        if not isinstance(review_digest, str) or not DIGEST_RE.fullmatch(review_digest):
            raise ReviewInputError("has an invalid opaque digest", field="review_digest")
        if task_digest is not None and (
            not isinstance(task_digest, str) or not DIGEST_RE.fullmatch(task_digest)
        ):
            raise ReviewInputError("has an invalid opaque digest", field="task_digest")
        with self._lock:
            self._purge_expired_locked()
            stored = self._reviews.get(safe_id)
            if stored is None:
                raise ReviewServiceError("review_not_found", "review is absent or expired")
            if not hmac.compare_digest(stored.prepared["review_digest"], review_digest):
                raise ReviewServiceError("review_digest_mismatch", "review digest does not match")
            if task_digest is not None and not hmac.compare_digest(
                stored.prepared["task_digest"], task_digest
            ):
                raise ReviewServiceError("task_digest_mismatch", "semantic task digest does not match")
            self._reviews.move_to_end(safe_id)
            return stored

    def _opaque(self, prefix: str, value: Any) -> str:
        digest = hmac.new(
            self._secret, _canonical_json(value).encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"{prefix}_{digest}"

    # -- trusted prepare hook -----------------------------------------------

    def _default_prepare_callback(self, **request: Any) -> Mapping[str, Any]:
        """Resolve a repository only through trusted server-side config.

        The default hook materialises and validates the canonical SEAF data.
        Deployments can inject a richer callback that also invokes the full
        deterministic AGA rule engine; callback failures remain fail closed.
        """
        repository_id = request["repository_id"]
        configured = self._repositories.get(repository_id)
        if configured is None:
            raise ReviewServiceError(
                "repository_unavailable",
                "repository_id is not present in the server-side registry",
            )
        if callable(configured):
            return configured(**request)

        if isinstance(configured, Mapping):
            repository = configured.get("repository") or configured.get("root")
            manifest_path = configured.get("manifest_path", "dochub.yaml")
            trusted_dependencies = configured.get("trusted_dependencies")
            dependency_mode = configured.get("dependency_mode", "verified")
            rules_dir = configured.get("rules_dir")
        else:
            repository = configured
            manifest_path = "dochub.yaml"
            trusted_dependencies = None
            dependency_mode = "verified"
            rules_dir = None
        if not isinstance(repository, (str, os.PathLike)):
            raise ReviewServiceError("repository_unavailable", "invalid server repository config")

        # Imports stay inside the hook so the MCP boundary can be unit-tested
        # independently and failures in an optional SEAF integration are
        # represented as an incomplete prepare result.
        from tools.repository_snapshot import RepositorySnapshotBuilder
        from tools.seaf_review import prepare_seaf_review

        builder = RepositorySnapshotBuilder(
            repository=Path(repository),
            base_revision=request["base"],
            head_revision=request["head"],
            manifest_path=str(manifest_path),
            dependency_mode=str(dependency_mode),
            trusted_dependencies=trusted_dependencies,
            rules_dir=rules_dir,
        )
        with builder.build() as snapshot:
            native_result = prepare_seaf_review(snapshot, rules_dir=rules_dir)
            data = native_result["canonical_snapshot"]
            materialized_hashes = dict(snapshot.materialized_hashes)
            dependency_commits = tuple(
                (dependency.path, dependency.commit)
                for dependency in snapshot.dependency_provenance
            )
            changed_by_path = {
                item["path"]: tuple(item.get("changed_pointers", ()))
                for item in data.get("changed_artifacts", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("path"), str)
                and isinstance(item.get("changed_pointers", []), list)
            }
            diagram_texts: dict[str, str] = {}
            for diagram in data.get("diagrams", []):
                if not isinstance(diagram, Mapping):
                    continue
                artifact = diagram.get("artifact")
                if not isinstance(artifact, str) or not artifact:
                    continue
                suffix = PurePosixPath(artifact).suffix.lower()
                if suffix not in {".puml", ".plantuml", ".mmd"}:
                    continue
                diagram_texts[artifact] = snapshot.read_materialized_text(
                    artifact,
                    allowed_extensions={".puml", ".plantuml", ".mmd"},
                )

        artifacts: list[dict[str, Any]] = []
        kind_by_collection = {
            "systems": "system_passport",
            "integrations": "integration_flow",
            "adrs": "adr",
            "diagrams": "diagram",
        }
        for collection, kind in kind_by_collection.items():
            for raw in data.get(collection, []):
                if not isinstance(raw, Mapping) or not raw.get("id"):
                    continue
                source = raw.get("source_ref") if isinstance(raw.get("source_ref"), Mapping) else {}
                diagram_artifact = raw.get("artifact") if kind == "diagram" else None
                label = diagram_artifact or source.get("file") or f"entities/{raw['id']}"
                source_pointer = source.get("pointer", "")
                changed_pointers = sorted(
                    {
                        changed_pointer
                        for changed_pointer in changed_by_path.get(source.get("file"), ())
                        if _pointer_is_equal_or_descendant(
                            changed_pointer, source_pointer
                        )
                    }
                )
                if (
                    not changed_pointers
                    and kind == "diagram"
                    and isinstance(diagram_artifact, str)
                    and diagram_artifact in changed_by_path
                    and source_pointer
                ):
                    # A non-YAML diagram diff has no field-level pointer. The
                    # owning context entity is the smallest available target.
                    changed_pointers = [source_pointer]
                change_status = "changed" if changed_pointers else "context"
                artifact_data: Any = dict(raw)
                content_source_ref: dict[str, Any] | None = None
                if kind == "integration_flow":
                    # Canonical SEAF uses source/target internally while
                    # deterministic locations intentionally point to the
                    # native document keys `from`/`to`. Preserve those native
                    # keys in the prepared evidence so the stored JSON Pointer
                    # suffix can be resolved exactly.
                    if "source" in raw:
                        artifact_data.setdefault("from", raw["source"])
                    if "target" in raw:
                        artifact_data.setdefault("to", raw["target"])
                if isinstance(diagram_artifact, str) and diagram_artifact in diagram_texts:
                    # Keep canonical entity fields at the JSON root so a
                    # location suffix under source_ref.pointer resolves
                    # directly; the materialized diagram text is additional
                    # prepared evidence for aga_parse_diagram.
                    artifact_data["text"] = diagram_texts[diagram_artifact]
                    content_source_ref = {
                        "file": diagram_artifact,
                        "pointer": f"{source_pointer}/text",
                        "commit": _materialized_path_commit(
                            diagram_artifact,
                            request["head"],
                            dependency_commits,
                        ),
                        "line": None,
                        "sha256": materialized_hashes[diagram_artifact],
                    }
                artifacts.append(
                    {
                        "entity_id": raw["id"],
                        "artifact": label,
                        "kind": kind,
                        "data": artifact_data,
                        "source_ref": source,
                        "content_source_ref": content_source_ref,
                        "change_status": change_status,
                        "changed_pointers": changed_pointers,
                    }
                )
        return {
            "artifacts": artifacts,
            "deterministic_findings": native_result["deterministic_findings"],
            "review_provenance": native_result["review_provenance"],
            "semantic_rule_catalog": native_result["semantic_rule_catalog"],
            "verdict_policy": native_result["verdict_policy"],
            "analysis_errors": [],
            # ``prepare_seaf_review`` is deliberately incomplete until a
            # semantic result exists.  This service owns that later boundary,
            # so successful native preparation itself is complete here.
            "incomplete": False,
        }

    def _invoke_prepare_callback(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self._prepare_slots.acquire(blocking=False):
            return {
                "artifacts": [],
                "deterministic_findings": [],
                "analysis_errors": [
                    {
                        "code": "prepare_busy",
                        "message": "trusted prepare worker limit is exhausted",
                    }
                ],
                "incomplete": True,
            }
        responses: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                value = self._prepare_callback(**dict(request))
                responses.put((True, value))
            except BaseException as exc:  # propagated as a bounded, sanitized failure
                responses.put((False, exc))
            finally:
                self._prepare_slots.release()

        worker = threading.Thread(target=invoke, name="aga-prepare-hook", daemon=True)
        try:
            worker.start()
        except RuntimeError:
            self._prepare_slots.release()
            return {
                "artifacts": [],
                "deterministic_findings": [],
                "analysis_errors": [
                    {
                        "code": "prepare_unavailable",
                        "message": "trusted prepare worker could not start",
                    }
                ],
                "incomplete": True,
            }
        try:
            succeeded, value = responses.get(timeout=self._prepare_timeout_seconds)
        except queue.Empty:
            return {
                "artifacts": [],
                "deterministic_findings": [],
                "analysis_errors": [
                    {"code": "prepare_timeout", "message": "trusted prepare hook timed out"}
                ],
                "incomplete": True,
            }
        if not succeeded:
            if isinstance(value, TimeoutError):
                code, message = "prepare_timeout", "trusted prepare hook timed out"
            elif isinstance(value, ReviewServiceError):
                code, message = value.code, value.message
            elif isinstance(getattr(value, "code", None), str) and isinstance(
                getattr(value, "message", None), str
            ):
                # ValidationError from the trusted snapshot/SEAF adapters has
                # a stable code and message.  Deliberately omit its local path.
                code = value.code
                message = value.message
            else:
                code, message = "prepare_unavailable", "trusted prepare hook is unavailable"
            return {
                "artifacts": [],
                "deterministic_findings": [],
                "analysis_errors": [{"code": code, "message": message}],
                "incomplete": True,
            }
        if not isinstance(value, Mapping):
            return {
                "artifacts": [],
                "deterministic_findings": [],
                "analysis_errors": [
                    {
                        "code": "prepare_schema_error",
                        "message": "trusted prepare hook returned a non-object result",
                    }
                ],
                "incomplete": True,
            }
        return _clone(value)

    # -- normalization -------------------------------------------------------

    def _normalise_artifacts(
        self, callback_result: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        raw_artifacts = callback_result.get("artifacts", callback_result.get("entities", []))
        if isinstance(raw_artifacts, Mapping):
            expanded = []
            for key, value in raw_artifacts.items():
                if isinstance(value, Mapping):
                    item = dict(value)
                    item.setdefault("entity_id", key)
                else:
                    item = {"entity_id": key, "data": value}
                expanded.append(item)
            raw_artifacts = expanded
        if not isinstance(raw_artifacts, Sequence) or isinstance(raw_artifacts, (str, bytes)):
            raise ReviewServiceError("prepare_schema_error", "artifacts must be an array")
        if len(raw_artifacts) > self._max_artifacts:
            raise ReviewServiceError("prepare_limit", "too many prepared artifacts")

        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw in enumerate(raw_artifacts):
            if not isinstance(raw, Mapping):
                raise ReviewServiceError("prepare_schema_error", "artifact entry must be an object")
            entity_id = raw.get("entity_id", raw.get("id"))
            try:
                entity_id = _identifier(entity_id, f"artifacts[{index}].entity_id")
            except ReviewInputError as exc:
                raise ReviewServiceError("prepare_schema_error", exc.message) from exc
            if entity_id in seen:
                raise ReviewServiceError("prepare_schema_error", "duplicate prepared entity_id")
            seen.add(entity_id)

            source_ref = _require_mapping(
                raw.get("source_ref"), f"artifacts[{index}].source_ref"
            )
            _strict_keys(
                source_ref,
                allowed={"file", "pointer", "commit", "line", "sha256"},
                required={"file", "pointer", "commit", "line", "sha256"},
                field=f"artifacts[{index}].source_ref",
            )
            provenance_file = _artifact_label(
                source_ref["file"], f"artifacts[{index}].source_ref.file"
            )
            provenance_pointer, _ = _json_pointer_tokens(
                source_ref["pointer"], f"artifacts[{index}].source_ref.pointer"
            )
            provenance_commit = _revision(
                source_ref["commit"], f"artifacts[{index}].source_ref.commit"
            )
            provenance_line = source_ref["line"]
            if provenance_line is not None and (
                isinstance(provenance_line, bool)
                or not isinstance(provenance_line, int)
                or provenance_line < 1
            ):
                raise ReviewInputError(
                    "must be null or a positive integer",
                    field=f"artifacts[{index}].source_ref.line",
                )
            provenance_sha256 = source_ref["sha256"]
            if not isinstance(provenance_sha256, str) or re.fullmatch(
                r"[0-9a-f]{64}", provenance_sha256
            ) is None:
                raise ReviewInputError(
                    "must be a lowercase SHA-256 digest",
                    field=f"artifacts[{index}].source_ref.sha256",
                )
            source_provenance = {
                "file": provenance_file,
                "pointer": provenance_pointer,
                # This can intentionally be an exact trusted dependency
                # commit rather than the architecture repository head.
                "commit": provenance_commit,
                "line": provenance_line,
                "sha256": provenance_sha256,
            }
            change_status = raw.get("change_status")
            if change_status not in {"changed", "context"}:
                raise ReviewInputError(
                    "must be changed or context",
                    field=f"artifacts[{index}].change_status",
                )
            raw_changed_pointers = raw.get("changed_pointers")
            if not isinstance(raw_changed_pointers, list):
                raise ReviewInputError(
                    "must be an array",
                    field=f"artifacts[{index}].changed_pointers",
                )
            if len(raw_changed_pointers) > self._max_findings:
                raise ReviewServiceError(
                    "prepare_limit", "artifact has too many changed pointers"
                )
            changed_pointers: list[str] = []
            for pointer_index, pointer_value in enumerate(raw_changed_pointers):
                pointer, pointer_tokens = _json_pointer_tokens(
                    pointer_value,
                    f"artifacts[{index}].changed_pointers[{pointer_index}]",
                )
                _, entity_tokens = _json_pointer_tokens(
                    provenance_pointer,
                    f"artifacts[{index}].source_ref.pointer",
                )
                if (
                    len(pointer_tokens) < len(entity_tokens)
                    or pointer_tokens[: len(entity_tokens)] != entity_tokens
                ):
                    raise ReviewInputError(
                        "must equal or descend from the artifact source pointer",
                        field=f"artifacts[{index}].changed_pointers[{pointer_index}]",
                    )
                changed_pointers.append(pointer)
            if len(set(changed_pointers)) != len(changed_pointers):
                raise ReviewInputError(
                    "must contain unique pointers",
                    field=f"artifacts[{index}].changed_pointers",
                )
            changed_pointers.sort()
            if change_status == "changed" and not changed_pointers:
                raise ReviewInputError(
                    "must be non-empty for a changed artifact",
                    field=f"artifacts[{index}].changed_pointers",
                )
            if change_status == "context" and changed_pointers:
                raise ReviewInputError(
                    "must be empty for a context artifact",
                    field=f"artifacts[{index}].changed_pointers",
                )
            artifact_value = raw.get("artifact") or raw.get("file") or source_ref.get("file")
            if artifact_value is None:
                artifact_value = f"entities/{entity_id}"
            artifact = _artifact_label(artifact_value, f"artifacts[{index}].artifact")
            kind = raw.get("kind", "entity")
            try:
                kind = _identifier(kind, f"artifacts[{index}].kind")
            except ReviewInputError as exc:
                raise ReviewServiceError("prepare_schema_error", exc.message) from exc

            if "data" in raw:
                data = raw["data"]
            elif "content" in raw:
                data = raw["content"]
            else:
                data = {
                    key: value
                    for key, value in raw.items()
                    if key
                    not in {
                        "entity_id",
                        "id",
                        "artifact",
                        "file",
                        "kind",
                        "source_ref",
                        "content_source_ref",
                        "change_status",
                        "changed_pointers",
                        "diagram_format",
                    }
                }
            content_provenance: dict[str, Any] | None = None
            has_materialized_text = (
                kind == "diagram"
                and isinstance(data, Mapping)
                and isinstance(data.get("text"), str)
            )
            raw_content_ref = raw.get("content_source_ref")
            if has_materialized_text:
                content_ref = _require_mapping(
                    raw_content_ref, f"artifacts[{index}].content_source_ref"
                )
                _strict_keys(
                    content_ref,
                    allowed={"file", "pointer", "commit", "line", "sha256"},
                    required={"file", "pointer", "commit", "line", "sha256"},
                    field=f"artifacts[{index}].content_source_ref",
                )
                content_file = _artifact_label(
                    content_ref["file"],
                    f"artifacts[{index}].content_source_ref.file",
                )
                if content_file != artifact:
                    raise ReviewInputError(
                        "must identify the materialized diagram artifact",
                        field=f"artifacts[{index}].content_source_ref.file",
                    )
                content_pointer, content_tokens = _json_pointer_tokens(
                    content_ref["pointer"],
                    f"artifacts[{index}].content_source_ref.pointer",
                )
                _, entity_tokens = _json_pointer_tokens(
                    provenance_pointer,
                    f"artifacts[{index}].source_ref.pointer",
                )
                if content_tokens != entity_tokens + ("text",):
                    raise ReviewInputError(
                        "must identify the prepared entity text field",
                        field=f"artifacts[{index}].content_source_ref.pointer",
                    )
                content_commit = _revision(
                    content_ref["commit"],
                    f"artifacts[{index}].content_source_ref.commit",
                )
                content_line = content_ref["line"]
                if content_line is not None and (
                    isinstance(content_line, bool)
                    or not isinstance(content_line, int)
                    or content_line < 1
                ):
                    raise ReviewInputError(
                        "must be null or a positive integer",
                        field=f"artifacts[{index}].content_source_ref.line",
                    )
                content_sha256 = content_ref["sha256"]
                expected_content_sha256 = hashlib.sha256(
                    data["text"].encode("utf-8")
                ).hexdigest()
                if (
                    not isinstance(content_sha256, str)
                    or not hmac.compare_digest(
                        content_sha256, expected_content_sha256
                    )
                ):
                    raise ReviewInputError(
                        "must equal the materialized diagram text SHA-256",
                        field=f"artifacts[{index}].content_source_ref.sha256",
                    )
                content_provenance = {
                    "file": content_file,
                    "pointer": content_pointer,
                    "commit": content_commit,
                    "line": content_line,
                    "sha256": content_sha256,
                }
            elif raw_content_ref is not None:
                raise ReviewInputError(
                    "is only allowed for a materialized diagram text field",
                    field=f"artifacts[{index}].content_source_ref",
                )
            data_json = _canonical_json(data)
            if len(data_json.encode("utf-8")) > self._max_artifact_bytes:
                raise ReviewServiceError("prepare_limit", "prepared artifact exceeds byte limit")
            provenance_json = _canonical_json(source_provenance)
            if len(provenance_json.encode("utf-8")) > self._max_artifact_bytes:
                raise ReviewServiceError("prepare_limit", "artifact provenance exceeds byte limit")
            diagram_format = raw.get("diagram_format", "")
            if not diagram_format:
                suffix = PurePosixPath(artifact).suffix.lower()
                diagram_format = (
                    "plantuml"
                    if suffix in {".puml", ".plantuml"}
                    else "mermaid"
                    if suffix == ".mmd"
                    else ""
                )
            if diagram_format not in {"", "plantuml", "mermaid", "canonical"}:
                raise ReviewServiceError("prepare_schema_error", "unsupported diagram format")
            result.append(
                {
                    "entity_id": entity_id,
                    "artifact": artifact,
                    "kind": kind,
                    "digest": _sha256_text(data_json),
                    "evidence_ref": "",  # assigned after the review digest is known
                    "data_json": data_json,
                    "provenance_json": provenance_json,
                    "source_provenance": source_provenance,
                    "content_provenance": content_provenance,
                    "change_status": change_status,
                    "changed_pointers": changed_pointers,
                    "diagram_format": diagram_format,
                }
            )
        result.sort(key=lambda item: (item["entity_id"], item["artifact"]))
        return result

    def _normalise_deterministic(
        self,
        callback_result: Mapping[str, Any],
        *,
        base: str,
        head: str,
    ) -> list[dict[str, Any]]:
        raw_findings = callback_result.get("deterministic_findings")
        if raw_findings is None:
            raw_findings = callback_result.get("findings", [])
        if not isinstance(raw_findings, Sequence) or isinstance(raw_findings, (str, bytes)):
            raise ReviewServiceError("prepare_schema_error", "deterministic_findings must be an array")
        if len(raw_findings) > self._max_findings:
            raise ReviewServiceError("prepare_limit", "too many deterministic findings")
        result: list[dict[str, Any]] = []
        for raw in raw_findings:
            if not isinstance(raw, Mapping):
                raise ReviewServiceError("prepare_schema_error", "deterministic finding must be an object")
            exact = {
                key: raw.get(key)
                for key in (
                    "rule_id",
                    "severity",
                    "confidence",
                    "artifact",
                    "location",
                    "evidence",
                    "source_ref",
                    "suggested_fix",
                )
            }
            try:
                valid = validate_finding(exact)
            except LLMSchemaError as exc:
                raise ReviewServiceError(
                    "prepare_schema_error", "invalid deterministic finding from trusted hook"
                ) from exc
            valid["artifact"] = _artifact_label(valid["artifact"], "finding.artifact")
            valid["origin"] = "deterministic"
            raw_entity_id = raw.get("entity_id", "")
            valid["entity_id"] = (
                _identifier(raw_entity_id, "deterministic_findings.entity_id")
                if raw_entity_id
                else ""
            )
            valid["evidence_refs"] = []
            canonical_defect = raw.get("canonical_defect")
            if canonical_defect is not None:
                canonical_defect = _bounded_text(
                    canonical_defect,
                    "deterministic_findings.canonical_defect",
                    allow_empty=False,
                )
                if canonical_defect != f"{valid['rule_id']}:{valid['location']}":
                    raise ReviewInputError(
                        "must match rule_id and location",
                        field="deterministic_findings.canonical_defect",
                    )
                valid["canonical_defect"] = canonical_defect

            provenance_fields = ("base_revision", "head_revision", "source_provenance")
            if any(field in raw for field in provenance_fields):
                if not all(field in raw for field in provenance_fields):
                    raise ReviewInputError(
                        "commit provenance fields must be supplied together",
                        field="deterministic_findings.source_provenance",
                    )
                finding_base = _revision(
                    raw["base_revision"], "deterministic_findings.base_revision"
                )
                finding_head = _revision(
                    raw["head_revision"], "deterministic_findings.head_revision"
                )
                if finding_base != base or finding_head != head:
                    raise ReviewInputError(
                        "does not match the prepared revision pair",
                        field="deterministic_findings.base_revision",
                    )
                provenance = _require_mapping(
                    raw["source_provenance"],
                    "deterministic_findings.source_provenance",
                )
                _strict_keys(
                    provenance,
                    allowed={"file", "pointer", "commit", "line", "sha256"},
                    required={"file", "pointer", "commit", "line", "sha256"},
                    field="deterministic_findings.source_provenance",
                )
                provenance_file = _artifact_label(
                    provenance["file"], "deterministic_findings.source_provenance.file"
                )
                pointer, _ = _json_pointer_tokens(
                    provenance["pointer"],
                    "deterministic_findings.source_provenance.pointer",
                )
                commit = _revision(
                    provenance["commit"],
                    "deterministic_findings.source_provenance.commit",
                )
                line = provenance["line"]
                checksum = provenance["sha256"]
                # The blob can belong either to the superproject head or to an
                # exact trusted gitlink commit.  The later evidence-binding
                # step requires this complete provenance object to equal the
                # prepared artifact provenance byte-for-byte.
                if line is not None and (
                    isinstance(line, bool) or not isinstance(line, int) or line < 1
                ):
                    raise ReviewInputError(
                        "line must be null or a positive integer",
                        field="deterministic_findings.source_provenance.line",
                    )
                if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
                    raise ReviewInputError(
                        "sha256 must be a lowercase digest",
                        field="deterministic_findings.source_provenance.sha256",
                    )
                valid.update(
                    {
                        "base_revision": finding_base,
                        "head_revision": finding_head,
                        "source_provenance": {
                            "file": provenance_file,
                            "pointer": pointer,
                            "commit": commit,
                            "line": line,
                            "sha256": checksum,
                        },
                    }
                )
            result.append(valid)
        return result

    def _analysis_errors(self, callback_result: Mapping[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for source_field in ("input_errors", "analysis_errors"):
            raw_errors = callback_result.get(source_field, [])
            if not isinstance(raw_errors, Sequence) or isinstance(raw_errors, (str, bytes)):
                raise ReviewServiceError(
                    "prepare_schema_error", f"{source_field} must be an array"
                )
            for raw in raw_errors[: self._max_findings]:
                if not isinstance(raw, Mapping):
                    raise ReviewServiceError(
                        "prepare_schema_error", f"{source_field} entry must be an object"
                    )
                code = _bounded_text(
                    raw.get("code", "prepare_error"),
                    f"{source_field}.code",
                    allow_empty=False,
                )
                message = _bounded_text(
                    raw.get("message", "prepare failed"),
                    f"{source_field}.message",
                    allow_empty=False,
                )
                errors.append({"code": code, "message": message})
        callback_status = callback_result.get("status")
        if callback_status in {"error", "timeout", "unavailable", "incomplete", "input_error"} and not errors:
            errors.append(
                {
                    "code": f"prepare_{callback_status}",
                    "message": "trusted prepare hook did not complete successfully",
                }
            )
        return errors

    def _normalise_review_context(
        self,
        callback_result: Mapping[str, Any],
    ) -> tuple[str, dict[str, dict[str, Any]], dict[str, Any]]:
        """Freeze snapshot provenance and the exact rules/policy used by prepare."""

        raw_provenance = callback_result.get("review_provenance", {})
        if not isinstance(raw_provenance, Mapping):
            raise ReviewServiceError(
                "prepare_schema_error", "review_provenance must be an object"
            )
        provenance_json = _canonical_json(raw_provenance)
        if len(provenance_json.encode("utf-8")) > self._max_artifact_bytes:
            raise ReviewServiceError(
                "prepare_limit", "review provenance exceeds byte limit"
            )

        raw_catalog = callback_result.get("semantic_rule_catalog")
        raw_policy = callback_result.get("verdict_policy")
        if raw_catalog is None and raw_policy is None:
            return provenance_json, _clone(self._catalog), _clone(self._policy)
        if raw_catalog is None or raw_policy is None:
            raise ReviewServiceError(
                "prepare_schema_error",
                "semantic_rule_catalog and verdict_policy must be supplied together",
            )
        if not isinstance(raw_catalog, Mapping) or not isinstance(raw_policy, Mapping):
            raise ReviewServiceError(
                "prepare_schema_error", "rule catalog and verdict policy must be objects"
            )
        if set(raw_catalog) != set(SEMANTIC_RULE_IDS):
            raise ReviewServiceError(
                "prepare_schema_error",
                "semantic rule catalog must contain exactly PRIN-004..PRIN-007",
            )

        catalog: dict[str, dict[str, Any]] = {}
        for rule_id in SEMANTIC_RULE_IDS:
            raw_rule = raw_catalog[rule_id]
            if not isinstance(raw_rule, Mapping):
                raise ReviewServiceError(
                    "prepare_schema_error", f"semantic rule {rule_id} must be an object"
                )
            missing = {
                "source_ref", "statement", "severity", "scope"
            } - set(raw_rule)
            if missing:
                raise ReviewServiceError(
                    "prepare_schema_error",
                    f"semantic rule {rule_id} is missing {', '.join(sorted(missing))}",
                )
            source_ref = raw_rule["source_ref"]
            statement = raw_rule["statement"]
            severity = raw_rule["severity"]
            scope = raw_rule["scope"]
            if (
                not isinstance(source_ref, str)
                or not source_ref
                or not isinstance(statement, str)
                or not statement
                or severity not in {"blocker", "major", "minor"}
                or not isinstance(scope, list)
                or not scope
                or any(not isinstance(item, str) or not item for item in scope)
            ):
                raise ReviewServiceError(
                    "prepare_schema_error", f"semantic rule {rule_id} is invalid"
                )
            catalog[rule_id] = {
                "source_ref": _bounded_text(
                    source_ref, f"semantic_rule_catalog.{rule_id}.source_ref", allow_empty=False
                ),
                "statement": _bounded_text(
                    statement, f"semantic_rule_catalog.{rule_id}.statement", allow_empty=False
                ),
                "severity": severity,
                "scope": [
                    _identifier(item, f"semantic_rule_catalog.{rule_id}.scope")
                    for item in scope
                ],
            }

        policy = _clone(raw_policy)
        verdict_policy = policy.get("verdict_policy")
        required_verdicts = {"has_blocker", "has_major", "minor_only", "none"}
        allowed_verdicts = {
            "approve", "approve_with_warnings", "request_changes_escalate"
        }
        if (
            not isinstance(verdict_policy, Mapping)
            or not required_verdicts.issubset(verdict_policy)
            or any(verdict_policy[key] not in allowed_verdicts for key in required_verdicts)
            or verdict_policy["has_blocker"] != "request_changes_escalate"
            or verdict_policy["has_major"] != "request_changes_escalate"
            or not isinstance(policy.get("autonomy"), Mapping)
            or policy["autonomy"].get("auto_merge") is not False
        ):
            raise ReviewServiceError(
                "prepare_schema_error", "verdict policy violates the fail-closed contract"
            )
        if len(_canonical_json({"catalog": catalog, "policy": policy}).encode("utf-8")) > (
            self._max_artifact_bytes
        ):
            raise ReviewServiceError(
                "prepare_limit", "rule catalog and verdict policy exceed byte limit"
            )
        return provenance_json, catalog, policy

    # -- public tool operations ---------------------------------------------

    def prepare_review(
        self,
        *,
        repository_id: Any,
        base: Any,
        head: Any,
        review_id: Any,
        entity_ids: Any = (),
    ) -> dict[str, Any]:
        if self._closed.is_set():
            raise ReviewServiceError("service_stopped", "review service is stopped")
        repository_id = _identifier(repository_id, "repository_id")
        review_id = _identifier(review_id, "review_id")
        base = _revision(base, "base")
        head = _revision(head, "head")
        if not isinstance(entity_ids, Sequence) or isinstance(entity_ids, (str, bytes)):
            raise ReviewInputError("must be an array", field="entity_ids")
        if len(entity_ids) > self._max_artifacts:
            raise ReviewInputError("contains too many IDs", field="entity_ids")
        safe_entities = tuple(_identifier(value, f"entity_ids[{index}]") for index, value in enumerate(entity_ids))
        if len(set(safe_entities)) != len(safe_entities):
            raise ReviewInputError("must contain unique IDs", field="entity_ids")

        request = {
            "repository_id": repository_id,
            "base": base,
            "head": head,
            "review_id": review_id,
            "entity_ids": safe_entities,
        }
        fingerprint = _sha256_text(_canonical_json(request))
        with self._lock:
            if self._closed.is_set():
                raise ReviewServiceError("service_stopped", "review service is stopped")
            self._purge_expired_locked()
            existing = self._reviews.get(review_id)
            if existing is not None:
                if not hmac.compare_digest(existing.request_fingerprint, fingerprint):
                    raise ReviewServiceError(
                        "review_conflict", "review_id is already bound to different inputs"
                    )
                self._reviews.move_to_end(review_id)
                return _clone(existing.prepared)

        callback_result = self._invoke_prepare_callback(request)
        try:
            artifacts = self._normalise_artifacts(callback_result)
            deterministic = self._normalise_deterministic(
                callback_result, base=base, head=head
            )
            errors = self._analysis_errors(callback_result)
            provenance_json, catalog, policy = self._normalise_review_context(
                callback_result
            )
        except ReviewInputError as exc:
            artifacts, deterministic = [], []
            errors = [{"code": "prepare_schema_error", "message": exc.message}]
            callback_result = {"incomplete": True}
            provenance_json, catalog, policy = "{}", _clone(self._catalog), _clone(
                self._policy
            )

        known_entities = {item["entity_id"] for item in artifacts}
        missing_requested = sorted(set(safe_entities) - known_entities)
        if missing_requested:
            errors.append(
                {
                    "code": "requested_entities_missing",
                    "message": "one or more requested entity IDs were not prepared",
                }
            )

        review_material = {
            "repository_id": repository_id,
            "base": base,
            "head": head,
            "review_id": review_id,
            "requested_entity_ids": safe_entities,
            "artifacts": [
                {
                    "entity_id": item["entity_id"],
                    "artifact": item["artifact"],
                    "kind": item["kind"],
                    "digest": item["digest"],
                    "provenance_json": item["provenance_json"],
                    "source_provenance": item["source_provenance"],
                    "content_provenance": item["content_provenance"],
                    "change_status": item["change_status"],
                    "changed_pointers": item["changed_pointers"],
                }
                for item in artifacts
            ],
            "deterministic_findings": deterministic,
            "review_provenance_json": provenance_json,
            "semantic_rule_catalog": catalog,
            "verdict_policy": policy,
        }
        review_digest = self._opaque("rvw", review_material)
        for artifact in artifacts:
            artifact["evidence_ref"] = self._opaque(
                "ev",
                {
                    "review_digest": review_digest,
                    "entity_id": artifact["entity_id"],
                    "digest": artifact["digest"],
                },
            )

        by_artifact: dict[str, list[dict[str, Any]]] = {}
        for artifact in artifacts:
            by_artifact.setdefault(artifact["artifact"], []).append(artifact)
        bound_deterministic: list[dict[str, Any]] = []
        for finding in deterministic:
            candidates = by_artifact.get(finding["artifact"], [])
            exact_context_binding = bool(
                finding.get("entity_id") and finding.get("source_provenance")
            )
            candidates = [
                item
                for item in candidates
                if item["change_status"] == "changed" or exact_context_binding
            ]
            explicit_entity = finding.get("entity_id")
            if explicit_entity:
                candidates = [item for item in candidates if item["entity_id"] == explicit_entity]
            if finding.get("source_provenance") is not None:
                provenance_matches: list[dict[str, Any]] = []
                for candidate in candidates:
                    artifact_provenance = _provenance_for_location(
                        candidate, finding["location"]
                    )
                    if artifact_provenance == finding["source_provenance"]:
                        provenance_matches.append(candidate)
                candidates = provenance_matches
            candidates = [
                item
                for item in candidates
                if _location_resolves_in_artifact(finding["location"], item)
            ]
            if len(candidates) == 1:
                artifact = candidates[0]
                finding["entity_id"] = artifact["entity_id"]
                finding["evidence_refs"] = [artifact["evidence_ref"]]
                # Publish only server-bound immutable provenance, even when a
                # trusted callback omitted it. Callback provenance, when
                # supplied, was used solely to narrow/equality-check binding.
                finding["base_revision"] = base
                finding["head_revision"] = head
                finding["source_provenance"] = _clone(
                    _provenance_for_location(artifact, finding["location"])
                )
                bound_deterministic.append(finding)
            else:
                errors.append(
                    {
                        "code": "deterministic_evidence_unbound",
                        "message": (
                            "deterministic finding must identify exactly one prepared entity"
                        ),
                    }
                )
        deterministic = bound_deterministic

        tasks: list[dict[str, Any]] = []
        for rule_id in SEMANTIC_RULE_IDS:
            rule = catalog[rule_id]
            accepted_kinds = _scope_kinds(rule["scope"])
            relevant = [item for item in artifacts if item["kind"] in accepted_kinds]
            changed = [
                item for item in relevant if item["change_status"] == "changed"
            ]
            context = [
                item for item in relevant if item["change_status"] == "context"
            ]
            task_material = {
                "review_digest": review_digest,
                "rule_id": rule_id,
                "source_ref": rule["source_ref"],
                "entity_ids": [item["entity_id"] for item in changed],
                "context_entity_ids": [item["entity_id"] for item in context],
                "evidence_refs": [item["evidence_ref"] for item in relevant],
            }
            digest = self._opaque("tsk", task_material)
            tasks.append(
                {
                    "task_id": f"semantic-{rule_id.lower()}",
                    "digest": digest,
                    "rule_id": rule_id,
                    "severity": rule["severity"],
                    "source_ref": rule["source_ref"],
                    "instruction": rule["statement"],
                    "entity_ids": task_material["entity_ids"],
                    "context_entity_ids": task_material["context_entity_ids"],
                    "evidence_refs": task_material["evidence_refs"],
                }
            )
        task_digest = self._opaque(
            "tsk", {"review_digest": review_digest, "tasks": [item["digest"] for item in tasks]}
        )

        incomplete = bool(callback_result.get("incomplete", False) or errors or missing_requested)
        prepared = {
            "schema": "aga.prepare-review/v1",
            "status": "incomplete" if incomplete else "ready",
            "review_id": review_id,
            "review_digest": review_digest,
            "task_digest": task_digest,
            "repository_id": repository_id,
            "base": base,
            "head": head,
            "deterministic_findings": deterministic,
            "semantic_tasks": tasks,
            "artifacts": artifacts,
            "analysis_errors": errors,
            "review_provenance_json": provenance_json,
            "incomplete": incomplete,
        }
        # Assert the stored value is JSON and keep a defensive copy.  This also
        # prevents a callback from mutating evidence after the digest is made.
        prepared = _clone(prepared)
        stored_catalog = _clone(catalog)
        stored_policy = _clone(policy)
        prepared_size = len(
            _canonical_json(
                {
                    "prepared": prepared,
                    "catalog": stored_catalog,
                    "policy": stored_policy,
                }
            ).encode("utf-8")
        )
        if prepared_size > self._max_review_bytes:
            raise ReviewServiceError(
                "prepare_limit", "prepared review exceeds aggregate byte limit"
            )
        stored = _StoredReview(
            request_fingerprint=fingerprint,
            expires_at=self._clock() + self._ttl_seconds,
            prepared=prepared,
            artifacts={item["entity_id"]: item for item in prepared["artifacts"]},
            evidence={item["evidence_ref"]: item["entity_id"] for item in prepared["artifacts"]},
            catalog=stored_catalog,
            policy=stored_policy,
            size_bytes=prepared_size,
        )
        # A second conflict check closes the race between two simultaneous
        # prepare calls without serialising slow trusted callbacks globally.
        with self._lock:
            if self._closed.is_set():
                raise ReviewServiceError("service_stopped", "review service is stopped")
            self._purge_expired_locked()
            raced = self._reviews.get(review_id)
            if raced is not None:
                if not hmac.compare_digest(raced.request_fingerprint, fingerprint):
                    raise ReviewServiceError(
                        "review_conflict", "review_id is already bound to different inputs"
                    )
                self._reviews.move_to_end(review_id)
                return _clone(raced.prepared)
            self._put_review(review_id, stored)
        return _clone(prepared)

    def seaf_lookup(
        self, *, review_id: Any, review_digest: Any, entity_id: Any
    ) -> dict[str, Any]:
        stored = self._get_review(review_id, review_digest)
        safe_entity = _identifier(entity_id, "entity_id")
        entity = stored.artifacts.get(safe_entity)
        if entity is None:
            raise ReviewServiceError("entity_not_found", "entity is not in prepared evidence")
        return {
            "schema": "aga.seaf-lookup/v1",
            "status": "ready",
            "review_id": review_id,
            "review_digest": review_digest,
            "entity": _clone(entity),
        }

    def parse_diagram(
        self, *, review_id: Any, review_digest: Any, entity_id: Any
    ) -> dict[str, Any]:
        stored = self._get_review(review_id, review_digest)
        safe_entity = _identifier(entity_id, "entity_id")
        entity = stored.artifacts.get(safe_entity)
        if entity is None:
            raise ReviewServiceError("entity_not_found", "entity is not in prepared evidence")
        if entity["kind"] != "diagram" and not entity["diagram_format"]:
            raise ReviewServiceError("not_a_diagram", "prepared entity is not a diagram")
        data = json.loads(entity["data_json"])
        parsed: Any = data
        if isinstance(data, Mapping) and isinstance(data.get("text"), str):
            from tools.aga import parse_diagram as parse_diagram_text

            suffix = ".puml" if entity["diagram_format"] == "plantuml" else ".mmd"
            parsed = parse_diagram_text(data["text"], suffix)
            if parsed is None:
                raise ReviewServiceError("diagram_parse_failed", "prepared diagram is invalid")
        diagram_json = _canonical_json(parsed)
        if len(diagram_json.encode("utf-8")) > self._max_artifact_bytes:
            raise ReviewServiceError("response_limit", "parsed diagram exceeds byte limit")
        return {
            "schema": "aga.parse-diagram/v1",
            "status": "ready",
            "review_id": review_id,
            "review_digest": review_digest,
            "entity_id": safe_entity,
            "evidence_ref": entity["evidence_ref"],
            "diagram_format": entity["diagram_format"] or "canonical",
            "source_provenance": _clone(
                entity["content_provenance"] or entity["source_provenance"]
            ),
            "diagram_json": diagram_json,
        }

    def _validate_semantic_result(
        self,
        semantic_result: Any,
        stored: _StoredReview,
    ) -> tuple[str, list[str], list[dict[str, Any]], list[dict[str, Any]], str]:
        if semantic_result is None:
            return "unavailable", [], [], [], "semantic result was not supplied"
        if isinstance(semantic_result, (str, bytes)):
            try:
                semantic_result = _strict_json_loads(semantic_result)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                raise ReviewInputError("must be valid JSON", field="semantic_result") from exc
        result = _require_mapping(semantic_result, "semantic_result")
        _strict_keys(
            result,
            allowed={"status", "completed_rule_ids", "findings", "error"},
            required={"status"},
            field="semantic_result",
        )
        status = result["status"]
        if not isinstance(status, str) or status not in SEMANTIC_STATUSES:
            raise ReviewInputError("has an unknown status", field="semantic_result.status")
        raw_completed = result.get("completed_rule_ids", [])
        if not isinstance(raw_completed, list):
            raise ReviewInputError("must be an array", field="semantic_result.completed_rule_ids")
        completed = [
            _identifier(item, f"semantic_result.completed_rule_ids[{index}]")
            for index, item in enumerate(raw_completed)
        ]
        if len(set(completed)) != len(completed):
            raise ReviewInputError(
                "must contain unique rule IDs", field="semantic_result.completed_rule_ids"
            )
        unknown_rules = sorted(set(completed) - set(SEMANTIC_RULE_IDS))
        if unknown_rules:
            raise ReviewInputError(
                "contains a rule outside the prepared semantic tasks",
                field="semantic_result.completed_rule_ids",
            )
        completed = [rule_id for rule_id in SEMANTIC_RULE_IDS if rule_id in completed]

        raw_findings = result.get("findings", [])
        if not isinstance(raw_findings, list):
            raise ReviewInputError("must be an array", field="semantic_result.findings")
        if len(raw_findings) > self._max_findings:
            raise ReviewInputError("contains too many findings", field="semantic_result.findings")
        if status in {"error", "timeout", "unavailable"} and (completed or raw_findings):
            raise ReviewInputError(
                "failed agent status cannot claim completed rules or findings",
                field="semantic_result",
            )
        error_message = _bounded_text(result.get("error", ""), "semantic_result.error")
        if status == "completed" and error_message:
            raise ReviewInputError(
                "completed status cannot include an error",
                field="semantic_result.error",
            )

        accepted: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        expected_fields = {
            "rule_id",
            "severity",
            "confidence",
            "entity_id",
            "location",
            "evidence",
            "evidence_refs",
            "source_ref",
            "suggested_fix",
        }
        for index, raw in enumerate(raw_findings):
            finding = _require_mapping(raw, f"semantic_result.findings[{index}]")
            _strict_keys(
                finding,
                allowed=expected_fields,
                required=expected_fields,
                field=f"semantic_result.findings[{index}]",
            )
            rule_id = _identifier(finding["rule_id"], f"semantic_result.findings[{index}].rule_id")
            if rule_id not in SEMANTIC_RULE_IDS or rule_id not in completed:
                raise ReviewInputError(
                    "rule was not completed in this semantic result",
                    field=f"semantic_result.findings[{index}].rule_id",
                )
            source_ref = _bounded_text(
                finding["source_ref"],
                f"semantic_result.findings[{index}].source_ref",
                allow_empty=False,
            )
            if source_ref != stored.catalog[rule_id]["source_ref"]:
                raise ReviewInputError(
                    "does not match the trusted rule catalog",
                    field=f"semantic_result.findings[{index}].source_ref",
                )
            if finding["severity"] != stored.catalog[rule_id]["severity"]:
                raise ReviewInputError(
                    "does not match the trusted rule catalog",
                    field=f"semantic_result.findings[{index}].severity",
                )
            entity_id = _identifier(
                finding["entity_id"], f"semantic_result.findings[{index}].entity_id"
            )
            entity = stored.artifacts.get(entity_id)
            if entity is None:
                raise ReviewInputError(
                    "does not reference prepared data",
                    field=f"semantic_result.findings[{index}].entity_id",
                )
            prepared_task = next(
                task
                for task in stored.prepared["semantic_tasks"]
                if task["rule_id"] == rule_id
            )
            if entity["kind"] not in _scope_kinds(stored.catalog[rule_id]["scope"]):
                raise _SemanticEvidenceError(
                    "artifact kind is outside the trusted catalog scope for this rule",
                    field=f"semantic_result.findings[{index}].entity_id",
                )
            if entity["change_status"] != "changed":
                raise _SemanticEvidenceError(
                    "finding entity must be a changed artifact, not context",
                    field=f"semantic_result.findings[{index}].entity_id",
                )
            if entity_id not in prepared_task["entity_ids"]:
                raise _SemanticEvidenceError(
                    "is outside the artifacts allowed for this semantic rule",
                    field=f"semantic_result.findings[{index}].entity_id",
                )
            refs = finding["evidence_refs"]
            if not isinstance(refs, list) or not refs:
                raise ReviewInputError(
                    "must be a non-empty array",
                    field=f"semantic_result.findings[{index}].evidence_refs",
                )
            if any(not isinstance(ref, str) for ref in refs):
                raise ReviewInputError(
                    "must contain evidence reference strings",
                    field=f"semantic_result.findings[{index}].evidence_refs",
                )
            if len(set(refs)) != len(refs) or any(ref not in stored.evidence for ref in refs):
                raise ReviewInputError(
                    "contains an unknown or duplicate prepared evidence reference",
                    field=f"semantic_result.findings[{index}].evidence_refs",
                )
            if any(ref not in prepared_task["evidence_refs"] for ref in refs):
                raise ReviewInputError(
                    "contains evidence outside this semantic task",
                    field=f"semantic_result.findings[{index}].evidence_refs",
                )
            if entity_id not in {stored.evidence[ref] for ref in refs}:
                raise ReviewInputError(
                    "must include evidence for finding.entity_id",
                    field=f"semantic_result.findings[{index}].evidence_refs",
                )

            location_field = f"semantic_result.findings[{index}].location"
            try:
                location, location_tokens = _json_pointer_tokens(
                    finding["location"], location_field
                )
            except ReviewInputError as exc:
                raise _SemanticEvidenceError(
                    "must be a canonical RFC 6901 JSON Pointer bound to prepared data",
                    field=location_field,
                ) from exc
            entity_provenance = entity["source_provenance"]
            _, entity_tokens = _json_pointer_tokens(
                entity_provenance["pointer"], "prepared.source_provenance.pointer"
            )
            if (
                len(location_tokens) < len(entity_tokens)
                or location_tokens[: len(entity_tokens)] != entity_tokens
            ):
                raise _SemanticEvidenceError(
                    "must equal the prepared entity pointer or one of its descendants",
                    field=location_field,
                )
            try:
                prepared_data = json.loads(entity["data_json"])
            except (json.JSONDecodeError, TypeError) as exc:  # defensive store invariant
                raise ReviewServiceError(
                    "prepared_evidence_corrupt", "prepared artifact JSON cannot be read"
                ) from exc
            suffix = location_tokens[len(entity_tokens) :]
            if not _pointer_suffix_resolves(prepared_data, suffix):
                raise _SemanticEvidenceError(
                    "JSON Pointer suffix does not resolve in prepared entity data",
                    field=location_field,
                )
            finding_provenance = _provenance_for_location(entity, location)

            validator_input = {
                "rule_id": rule_id,
                "severity": finding["severity"],
                "confidence": finding["confidence"],
                "artifact": entity["artifact"],
                "location": location,
                "evidence": finding["evidence"],
                "source_ref": source_ref,
                "suggested_fix": finding["suggested_fix"],
            }
            try:
                valid = validate_finding(validator_input)
            except LLMSchemaError as exc:
                raise ReviewInputError(
                    "does not satisfy the strict finding schema",
                    field=f"semantic_result.findings[{index}]",
                ) from exc
            valid.update(
                {
                    "entity_id": entity_id,
                    "evidence_refs": list(refs),
                    "origin": "semantic",
                    "base_revision": stored.prepared["base"],
                    "head_revision": stored.prepared["head"],
                    "source_provenance": _clone(finding_provenance),
                }
            )
            confidence = valid["confidence"]
            if confidence < 0.40:
                observation = dict(valid)
                observation.pop("severity")
                observation["observation_type"] = "low_confidence"
                observations.append(observation)
            else:
                if valid["severity"] == "blocker" and confidence < 0.70:
                    valid["original_severity"] = "blocker"
                    valid["low_confidence"] = True
                    valid["severity"] = "major"
                accepted.append(valid)
        return status, completed, accepted, observations, error_message

    def finalize_review(
        self,
        *,
        review_id: Any,
        review_digest: Any,
        task_digest: Any,
        semantic_result: Any = None,
    ) -> dict[str, Any]:
        stored = self._get_review(review_id, review_digest, task_digest)
        semantic_validation_error: dict[str, str] | None = None
        try:
            status, completed, semantic, observations, agent_error = self._validate_semantic_result(
                semantic_result, stored
            )
        except _SemanticEvidenceError as exc:
            # A syntactically valid agent response with an unbound location is
            # a completed transport call but an incomplete governance review.
            # Do not accept any semantic finding from that response.
            status, completed, semantic, observations = "incomplete", [], [], []
            agent_error = "semantic finding location is not bound to prepared evidence"
            semantic_validation_error = {
                "code": "semantic_validation_error",
                "message": agent_error,
            }
            try:
                invalid_material = _strict_json_loads(semantic_result) if isinstance(
                    semantic_result, (str, bytes)
                ) else semantic_result
                final_fingerprint = _sha256_text(
                    _canonical_json(
                        {
                            "semantic_result": invalid_material,
                            "validation_field": exc.field,
                        }
                    )
                )
            except (ReviewServiceError, ValueError, UnicodeError):
                final_fingerprint = _sha256_text(
                    _canonical_json({"semantic_validation_error": exc.field})
                )
        else:
            final_fingerprint = _sha256_text(
                _canonical_json(
                    {
                        "status": status,
                        "completed_rule_ids": completed,
                        "findings": semantic,
                        "observations": observations,
                        "error": agent_error,
                    }
                )
            )
        with self._lock:
            if stored.final_result is not None:
                if not hmac.compare_digest(stored.final_fingerprint or "", final_fingerprint):
                    raise ReviewServiceError(
                        "finalization_conflict",
                        "review was already finalized with a different semantic result",
                    )
                return _clone(stored.final_result)
        expected = list(SEMANTIC_RULE_IDS)
        missing = [rule_id for rule_id in expected if rule_id not in completed]

        analysis_errors = list(stored.prepared["analysis_errors"])
        low_confidence_risk = any(
            stored.catalog.get(observation.get("rule_id"), {}).get("severity")
            in {"blocker", "major"}
            for observation in observations
        )
        semantic_complete = (
            status == "completed" and not missing and not low_confidence_risk
        )
        if semantic_validation_error is not None:
            analysis_errors.append(semantic_validation_error)
        elif low_confidence_risk:
            analysis_errors.append(
                {
                    "code": "semantic_low_confidence",
                    "message": (
                        "low-confidence blocker/major semantic signal requires human review"
                    ),
                }
            )
        elif not semantic_complete:
            code = {
                "timeout": "semantic_timeout",
                "error": "semantic_error",
                "unavailable": "semantic_unavailable",
                "incomplete": "semantic_rules_incomplete",
                "completed": "semantic_rules_incomplete",
            }[status]
            message = agent_error or (
                "semantic agent did not complete every prepared rule"
                if missing
                else "semantic agent did not complete"
            )
            analysis_errors.append({"code": code, "message": message})

        try:
            merged = list(
                merge_findings(stored.prepared["deterministic_findings"], semantic)
            )
            merged = deduplicate_findings(merged)
        except LLMSchemaError as exc:
            raise ReviewServiceError("merge_error", "finding merge failed closed") from exc

        incomplete = bool(stored.prepared["incomplete"] or not semantic_complete)
        verdict = "incomplete" if incomplete else verdict_from(merged, stored.policy)
        escalate = incomplete or verdict == "request_changes_escalate"
        result = {
            "schema": "aga.final-review/v1",
            "status": "incomplete" if incomplete else "completed",
            "review_id": review_id,
            "review_digest": review_digest,
            "task_digest": task_digest,
            "review_provenance_json": stored.prepared["review_provenance_json"],
            "findings": _clone(merged),
            "observations": _clone(observations),
            "completed_rule_ids": completed,
            "missing_rule_ids": missing,
            "analysis_errors": analysis_errors,
            "verdict": verdict,
            "escalate": escalate,
            "human_review_required": escalate,
            "auto_merge": False,
            "incomplete": incomplete,
        }
        final_result = _clone(result)
        final_size = len(_canonical_json(final_result).encode("utf-8"))
        with self._lock:
            # First write wins. A concurrent equivalent retry is idempotent;
            # a different semantic result cannot rewrite the governance verdict.
            if stored.final_result is not None:
                if not hmac.compare_digest(stored.final_fingerprint or "", final_fingerprint):
                    raise ReviewServiceError(
                        "finalization_conflict",
                        "review was already finalized with a different semantic result",
                    )
                return _clone(stored.final_result)
            if self._reviews.get(review_id) is not stored:
                raise ReviewServiceError(
                    "review_not_found", "review was evicted before finalization completed"
                )
            combined_size = stored.size_bytes + final_size
            if combined_size > self._max_review_bytes:
                raise ReviewServiceError(
                    "review_store_limit", "prepared and final review exceed byte limit"
                )
            stored.final_fingerprint = final_fingerprint
            stored.final_result = final_result
            stored.size_bytes = combined_size
            self._trim_store_locked(protected_review_id=review_id)
        return _clone(final_result)


# JSON Schemas are intentionally explicit.  Dynamic SEAF content is carried as
# canonical JSON text, which lets every object boundary keep
# ``additionalProperties: false`` without pretending to own the SEAF schema.
ANALYSIS_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"code": {"type": "string"}, "message": {"type": "string"}},
    "required": ["code", "message"],
}
SOURCE_PROVENANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "file": {"type": "string"},
        "pointer": {
            "type": "string",
            "minLength": 1,
            "pattern": JSON_POINTER_RE.pattern,
        },
        "commit": {"type": "string", "pattern": REVISION_RE.pattern},
        "line": {"type": ["integer", "null"], "minimum": 1},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "required": ["file", "pointer", "commit", "line", "sha256"],
}
CONTENT_PROVENANCE_SCHEMA: dict[str, Any] = {
    **SOURCE_PROVENANCE_SCHEMA,
    "type": ["object", "null"],
}
ARTIFACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "entity_id": {"type": "string", "pattern": ID_RE.pattern},
        "artifact": {"type": "string"},
        "kind": {"type": "string", "pattern": ID_RE.pattern},
        "digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "evidence_ref": {"type": "string", "pattern": DIGEST_RE.pattern},
        "data_json": {"type": "string"},
        "provenance_json": {"type": "string"},
        "source_provenance": SOURCE_PROVENANCE_SCHEMA,
        "content_provenance": CONTENT_PROVENANCE_SCHEMA,
        "change_status": {"type": "string", "enum": ["changed", "context"]},
        "changed_pointers": {
            "type": "array",
            "items": {
                "type": "string",
                "minLength": 1,
                "pattern": JSON_POINTER_RE.pattern,
            },
            "uniqueItems": True,
        },
        "diagram_format": {
            "type": "string",
            "enum": ["", "plantuml", "mermaid", "canonical"],
        },
    },
    "required": [
        "entity_id",
        "artifact",
        "kind",
        "digest",
        "evidence_ref",
        "data_json",
        "provenance_json",
        "source_provenance",
        "content_provenance",
        "change_status",
        "changed_pointers",
        "diagram_format",
    ],
}
FINDING_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "rule_id": {"type": "string"},
        "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "entity_id": {"type": "string"},
        "artifact": {"type": "string"},
        "location": {
            "type": "string",
            "minLength": 1,
            "pattern": JSON_POINTER_RE.pattern,
        },
        "evidence": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "source_ref": {"type": "string"},
        "suggested_fix": {"type": "string"},
        "origin": {"type": "string", "enum": ["deterministic", "semantic"]},
        "canonical_defect": {"type": "string"},
        "base_revision": {"type": "string", "pattern": REVISION_RE.pattern},
        "head_revision": {"type": "string", "pattern": REVISION_RE.pattern},
        "source_provenance": SOURCE_PROVENANCE_SCHEMA,
        "low_confidence": {"type": "boolean", "const": True},
        "original_severity": {"type": "string", "const": "blocker"},
    },
    "required": [
        "rule_id",
        "severity",
        "confidence",
        "entity_id",
        "artifact",
        "location",
        "evidence",
        "evidence_refs",
        "source_ref",
        "suggested_fix",
        "origin",
        "base_revision",
        "head_revision",
        "source_provenance",
    ],
}
OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        key: value
        for key, value in FINDING_OUTPUT_SCHEMA["properties"].items()
        if key != "severity"
    }
    | {"observation_type": {"type": "string", "enum": ["low_confidence"]}},
    "required": [
        key for key in FINDING_OUTPUT_SCHEMA["required"] if key != "severity"
    ]
    + ["observation_type"],
}
TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "task_id": {"type": "string"},
        "digest": {"type": "string", "pattern": DIGEST_RE.pattern},
        "rule_id": {"type": "string", "enum": list(SEMANTIC_RULE_IDS)},
        "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
        "source_ref": {"type": "string"},
        "instruction": {"type": "string"},
        "entity_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "context_entity_ids": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "evidence_refs": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
    },
    "required": [
        "task_id",
        "digest",
        "rule_id",
        "severity",
        "source_ref",
        "instruction",
        "entity_ids",
        "context_entity_ids",
        "evidence_refs",
    ],
}


def _object_schema(properties: Mapping[str, Any], required: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": dict(properties),
        "required": list(required),
    }


SEMANTIC_FINDING_INPUT_SCHEMA = _object_schema(
    {
        "rule_id": {"type": "string", "enum": list(SEMANTIC_RULE_IDS)},
        "severity": {
            "type": "string",
            "enum": ["blocker", "major", "minor"],
            "description": (
                "Copy byte-for-byte from the prepared semantic task with the "
                "same rule_id."
            ),
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "entity_id": {"type": "string", "pattern": ID_RE.pattern},
        "location": {
            "type": "string",
            "minLength": 1,
            "pattern": JSON_POINTER_RE.pattern,
        },
        "evidence": {
            "type": "string",
            "description": (
                "Ground the defect in the prepared artifacts named by "
                "evidence_refs. Preserve verbatim the shortest supporting "
                "clause or clauses that cover every fact used to classify the "
                "breach, including decisive identifiers and risk or control "
                "wording; do not use a synonym-only paraphrase."
            ),
        },
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "uniqueItems": True,
            "description": (
                "A non-empty subset of evidence_refs from the prepared semantic "
                "task with the same rule_id."
            ),
        },
        "source_ref": {
            "type": "string",
            "description": (
                "Copy byte-for-byte from semantic_tasks[].source_ref for the same "
                "rule_id. Never use an artifact or aga_seaf_lookup source_ref."
            ),
        },
        "suggested_fix": {"type": "string"},
    },
    [
        "rule_id",
        "severity",
        "confidence",
        "entity_id",
        "location",
        "evidence",
        "evidence_refs",
        "source_ref",
        "suggested_fix",
    ],
)
SEMANTIC_RESULT_SCHEMA = _object_schema(
    {
        "status": {"type": "string", "enum": sorted(SEMANTIC_STATUSES)},
        "completed_rule_ids": {
            "type": "array",
            "items": {"type": "string", "enum": list(SEMANTIC_RULE_IDS)},
            "uniqueItems": True,
        },
        "findings": {
            "type": "array",
            "items": SEMANTIC_FINDING_INPUT_SCHEMA,
        },
        "error": {"type": "string"},
    },
    ["status"],
)


TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "aga_prepare_review",
        "description": "Prepare immutable deterministic AGA findings and PRIN-004..007 semantic tasks for a trusted SEAF repository revision pair.",
        "inputSchema": _object_schema(
            {
                "repository_id": {"type": "string", "pattern": ID_RE.pattern},
                "base": {"type": "string", "pattern": REVISION_RE.pattern},
                "head": {"type": "string", "pattern": REVISION_RE.pattern},
                "review_id": {"type": "string", "pattern": ID_RE.pattern},
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string", "pattern": ID_RE.pattern},
                    "uniqueItems": True,
                },
            },
            ["repository_id", "base", "head", "review_id"],
        ),
        "outputSchema": _object_schema(
            {
                "schema": {"type": "string", "const": "aga.prepare-review/v1"},
                "status": {"type": "string", "enum": ["ready", "incomplete"]},
                "review_id": {"type": "string"},
                "review_digest": {"type": "string", "pattern": DIGEST_RE.pattern},
                "task_digest": {"type": "string", "pattern": DIGEST_RE.pattern},
                "repository_id": {"type": "string"},
                "base": {"type": "string"},
                "head": {"type": "string"},
                "review_provenance_json": {"type": "string"},
                "deterministic_findings": {"type": "array", "items": FINDING_OUTPUT_SCHEMA},
                "semantic_tasks": {"type": "array", "items": TASK_SCHEMA},
                "artifacts": {"type": "array", "items": ARTIFACT_SCHEMA},
                "analysis_errors": {"type": "array", "items": ANALYSIS_ERROR_SCHEMA},
                "incomplete": {"type": "boolean"},
            },
            [
                "schema",
                "status",
                "review_id",
                "review_digest",
                "task_digest",
                "repository_id",
                "base",
                "head",
                "review_provenance_json",
                "deterministic_findings",
                "semantic_tasks",
                "artifacts",
                "analysis_errors",
                "incomplete",
            ],
        ),
    },
    {
        "name": "aga_seaf_lookup",
        "description": "Return one entity from the immutable prepared SEAF evidence store by entity ID.",
        "inputSchema": _object_schema(
            {
                "review_id": {"type": "string", "pattern": ID_RE.pattern},
                "review_digest": {"type": "string", "pattern": DIGEST_RE.pattern},
                "entity_id": {"type": "string", "pattern": ID_RE.pattern},
            },
            ["review_id", "review_digest", "entity_id"],
        ),
        "outputSchema": _object_schema(
            {
                "schema": {"type": "string", "const": "aga.seaf-lookup/v1"},
                "status": {"type": "string", "const": "ready"},
                "review_id": {"type": "string"},
                "review_digest": {"type": "string"},
                "entity": ARTIFACT_SCHEMA,
            },
            ["schema", "status", "review_id", "review_digest", "entity"],
        ),
    },
    {
        "name": "aga_parse_diagram",
        "description": (
            "Parse or return one prepared diagram by entity ID. Call only when "
            "the prepared artifact has a non-empty diagram_format and diagram "
            "kind; non-diagram entity IDs and filesystem paths are invalid."
        ),
        "inputSchema": _object_schema(
            {
                "review_id": {"type": "string", "pattern": ID_RE.pattern},
                "review_digest": {"type": "string", "pattern": DIGEST_RE.pattern},
                "entity_id": {"type": "string", "pattern": ID_RE.pattern},
            },
            ["review_id", "review_digest", "entity_id"],
        ),
        "outputSchema": _object_schema(
            {
                "schema": {"type": "string", "const": "aga.parse-diagram/v1"},
                "status": {"type": "string", "const": "ready"},
                "review_id": {"type": "string"},
                "review_digest": {"type": "string"},
                "entity_id": {"type": "string"},
                "evidence_ref": {"type": "string"},
                "diagram_format": {"type": "string"},
                "source_provenance": SOURCE_PROVENANCE_SCHEMA,
                "diagram_json": {"type": "string"},
            },
            [
                "schema",
                "status",
                "review_id",
                "review_digest",
                "entity_id",
                "evidence_ref",
                "diagram_format",
                "source_provenance",
                "diagram_json",
            ],
        ),
    },
    {
        "name": "aga_finalize_review",
        "description": (
            "Validate semantic PRIN-004..007 JSON against prepared evidence, "
            "merge by precedence and compute a fail-closed verdict. Before this "
            "call, copy every finding severity/source_ref exactly from its "
            "prepared semantic task; artifact source_ref values are invalid."
        ),
        "inputSchema": _object_schema(
            {
                "review_id": {"type": "string", "pattern": ID_RE.pattern},
                "review_digest": {"type": "string", "pattern": DIGEST_RE.pattern},
                "task_digest": {"type": "string", "pattern": DIGEST_RE.pattern},
                "semantic_result": SEMANTIC_RESULT_SCHEMA,
            },
            ["review_id", "review_digest", "task_digest"],
        ),
        "outputSchema": _object_schema(
            {
                "schema": {"type": "string", "const": "aga.final-review/v1"},
                "status": {"type": "string", "enum": ["completed", "incomplete"]},
                "review_id": {"type": "string"},
                "review_digest": {"type": "string"},
                "task_digest": {"type": "string"},
                "review_provenance_json": {"type": "string"},
                "findings": {"type": "array", "items": FINDING_OUTPUT_SCHEMA},
                "observations": {"type": "array", "items": OBSERVATION_SCHEMA},
                "completed_rule_ids": {"type": "array", "items": {"type": "string"}},
                "missing_rule_ids": {"type": "array", "items": {"type": "string"}},
                "analysis_errors": {"type": "array", "items": ANALYSIS_ERROR_SCHEMA},
                "verdict": {
                    "type": "string",
                    "enum": [
                        "approve",
                        "approve_with_warnings",
                        "request_changes_escalate",
                        "incomplete",
                    ],
                },
                "escalate": {"type": "boolean"},
                "human_review_required": {"type": "boolean"},
                "auto_merge": {"type": "boolean", "const": False},
                "incomplete": {"type": "boolean"},
            },
            [
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
            ],
        ),
    },
)


__all__ = [
    "ANALYSIS_ERROR_SCHEMA",
    "ARTIFACT_SCHEMA",
    "FINDING_OUTPUT_SCHEMA",
    "OBSERVATION_SCHEMA",
    "ReviewInputError",
    "ReviewService",
    "ReviewServiceError",
    "SEMANTIC_RULE_IDS",
    "TOOL_DEFINITIONS",
]
