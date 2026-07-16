# -*- coding: utf-8 -*-
"""Append-only review feedback and pending-precedent generation.

Review decisions are represented as new JSONL events.  Existing lines are
never edited, which preserves the audit trail while still allowing an
architect to attach a later human action to a review.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import Any, Collection, Iterable, Mapping

import yaml

try:  # POSIX process lock; unsupported platforms fail closed at the I/O boundary.
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


ARCHITECT_ACTIONS = frozenset({"accept", "override", "edit", "missed"})
SEVERITIES = frozenset({"blocker", "major", "minor"})
REVIEW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
PRECEDENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "secret",
        "password",
        "llm_payload",
        "raw_prompt",
        "prompt",
    }
)
REQUIRED_REVIEW_FIELDS = frozenset(
    {
        "review_id",
        "timestamp",
        "skill_version",
        "rules_version",
        "input_revision",
        "findings",
        "suppressed_findings",
        "observations",
        "verdict",
        "escalation",
    }
)
REVIEW_EVENT_FIELDS = REQUIRED_REVIEW_FIELDS | frozenset(
    {
        "event_type",
        "architect_action",
        "pr",
        "title",
        "input_path_hash",
        "llm_result_classification",
        "llm_release_evidence",
    }
)
ARCHITECT_ACTION_EVENT_FIELDS = frozenset(
    {
        "event_type",
        "review_id",
        "timestamp",
        "action",
        "actor",
        "rationale",
        "severity",
        "rule_id",
    }
)
EVOLUTION_COMMON_FIELDS = frozenset(
    {
        "event_type",
        "cycle_id",
        "timestamp",
        "precedent",
        "attempt",
        "result",
        "gate_checks",
    }
)
EVOLUTION_FITNESS_FIELDS = frozenset(
    {
        "base_revision",
        "candidate_revision",
        "corpus_revision",
        "mutation",
        "metrics_before",
        "metrics_after",
    }
)
MAX_FEEDBACK_LOG_BYTES = 8 * 1_048_576
MAX_FEEDBACK_LOG_RECORDS = 10_000


class FeedbackError(RuntimeError):
    """Base class for feedback/audit failures."""


class FeedbackValidationError(FeedbackError, ValueError):
    """An event or precedent does not satisfy its schema."""


class FeedbackLogCorruptError(FeedbackError):
    """An existing JSONL line cannot be trusted."""


class ReviewNotFoundError(FeedbackError, LookupError):
    """An architect action references an unknown review."""


class DuplicateFeedbackError(FeedbackError):
    """A review/action/precedent would duplicate an immutable record."""


_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _path_lock(path: Path) -> threading.RLock:
    # Keep the key lexical: resolving an untrusted leaf would follow the very
    # symlink that the file-opening boundary below must reject.
    key = os.path.abspath(os.fspath(path))
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _assert_no_sensitive_data(value: Any, path: str = "event") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalised = str(key).strip().lower().replace("-", "_")
            if normalised in SENSITIVE_KEYS:
                raise FeedbackValidationError(
                    f"sensitive/full-payload field is forbidden: {path}.{key}"
                )
            _assert_no_sensitive_data(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_sensitive_data(item, f"{path}[{index}]")


def _unsafe_log(path: Path, message: str) -> FeedbackLogCorruptError:
    return FeedbackLogCorruptError(f"{path}: {message}")


LogHandle = tuple[int, int, str]


def _inspect_log_entry(
    path: Path, parent_descriptor: int, leaf: str
) -> os.stat_result | None:
    try:
        info = os.stat(
            leaf,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _unsafe_log(path, f"cannot inspect JSONL path: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise _unsafe_log(path, "symlink JSONL path is forbidden")
    if not stat.S_ISREG(info.st_mode):
        raise _unsafe_log(path, "JSONL path is not a regular file")
    if info.st_nlink != 1:
        raise _unsafe_log(path, "hardlinked JSONL path is forbidden")
    return info


def _assert_open_identity(
    path: Path,
    descriptor: int,
    parent_descriptor: int,
    leaf: str,
    expected: os.stat_result | None = None,
) -> os.stat_result:
    try:
        opened = os.fstat(descriptor)
    except OSError as exc:  # pragma: no cover - descriptor failure is defensive
        raise _unsafe_log(path, f"cannot inspect opened JSONL file: {exc}") from exc
    if not stat.S_ISREG(opened.st_mode):
        raise _unsafe_log(path, "opened JSONL path is not a regular file")
    if opened.st_nlink != 1:
        raise _unsafe_log(path, "opened JSONL path is hardlinked")
    current = _inspect_log_entry(path, parent_descriptor, leaf)
    if current is None:
        raise _unsafe_log(path, "JSONL path disappeared during safe open")
    opened_identity = (opened.st_dev, opened.st_ino)
    if opened_identity != (current.st_dev, current.st_ino):
        raise _unsafe_log(path, "JSONL path changed during safe open")
    if expected is not None and opened_identity != (expected.st_dev, expected.st_ino):
        raise _unsafe_log(path, "JSONL inode changed during validation")
    return opened


def _open_parent_directory(path: Path, *, create: bool) -> tuple[int, str] | None:
    """Open every parent component without following symlinks."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    leaf = absolute.name
    if not leaf:
        raise _unsafe_log(path, "JSONL path does not name a file")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None:
        raise FeedbackError("safe JSONL access requires O_NOFOLLOW support")
    if directory is None:
        raise FeedbackError("safe JSONL access requires O_DIRECTORY support")
    supports_dir_fd: Collection[Any] = getattr(
        os, "supports_dir_fd", frozenset()
    )
    supports_nofollow: Collection[Any] = getattr(
        os, "supports_follow_symlinks", frozenset()
    )
    if not all(
        operation in supports_dir_fd for operation in (os.open, os.stat, os.mkdir)
    ) or os.stat not in supports_nofollow:
        raise FeedbackError(
            "safe JSONL access requires descriptor-relative path operations"
        )

    flags = os.O_RDONLY | directory | nofollow | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(absolute.anchor, flags)
    except OSError as exc:  # pragma: no cover - filesystem root is platform-owned
        raise _unsafe_log(path, f"cannot open filesystem anchor safely: {exc}") from exc

    try:
        for component in absolute.parts[1:-1]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    os.close(descriptor)
                    return None
                try:
                    os.mkdir(component, 0o777, dir_fd=descriptor)
                except FileExistsError:
                    # Another process won the creation race.  The safe open
                    # below still rejects a symlink or non-directory winner.
                    pass
                except OSError as exc:
                    raise _unsafe_log(
                        path, f"cannot create JSONL parent directory safely: {exc}"
                    ) from exc
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise _unsafe_log(
                        path, f"unsafe JSONL parent directory was rejected: {exc}"
                    ) from exc
            except OSError as exc:
                raise _unsafe_log(
                    path, f"unsafe JSONL parent directory was rejected: {exc}"
                ) from exc
            os.close(descriptor)
            descriptor = child
    except Exception:
        os.close(descriptor)
        raise
    return descriptor, leaf


def _open_log(path: Path, *, create: bool, writable: bool) -> LogHandle | None:
    if fcntl is None:
        raise FeedbackError(
            "safe JSONL access requires an interprocess file-lock implementation"
        )
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise FeedbackError("safe JSONL access requires O_NOFOLLOW support")

    parent = _open_parent_directory(path, create=create)
    if parent is None:
        return None
    parent_descriptor, leaf = parent

    access_flags = os.O_RDWR | os.O_APPEND if writable else os.O_RDONLY
    flags = access_flags | getattr(os, "O_CLOEXEC", 0) | nofollow
    # O_EXCL makes first creation race-safe.  If another process wins, retry
    # through the existing-file branch and verify its inode after opening.
    try:
        for _attempt in range(4):
            expected = _inspect_log_entry(path, parent_descriptor, leaf)
            if expected is None:
                if not create:
                    os.close(parent_descriptor)
                    return None
                try:
                    descriptor = os.open(
                        leaf,
                        flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=parent_descriptor,
                    )
                except FileExistsError:
                    continue
                except OSError as exc:
                    raise _unsafe_log(
                        path, f"cannot create JSONL file safely: {exc}"
                    ) from exc
            else:
                try:
                    descriptor = os.open(leaf, flags, dir_fd=parent_descriptor)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.EMLINK}:
                        raise _unsafe_log(
                            path, "unsafe linked JSONL path was rejected"
                        ) from exc
                    raise _unsafe_log(
                        path, f"cannot open JSONL file safely: {exc}"
                    ) from exc
            try:
                _assert_open_identity(
                    path,
                    descriptor,
                    parent_descriptor,
                    leaf,
                    expected,
                )
            except Exception:
                os.close(descriptor)
                raise
            return descriptor, parent_descriptor, leaf
        raise _unsafe_log(path, "JSONL path changed repeatedly during safe open")
    except Exception:
        os.close(parent_descriptor)
        raise


@contextmanager
def _locked_log(path: Path, *, create: bool, exclusive: bool):
    """Yield one verified descriptor under one thread and process lock."""

    with _path_lock(path):
        handle = _open_log(path, create=create, writable=exclusive)
        if handle is None:
            yield None
            return
        descriptor, parent_descriptor, leaf = handle
        lock_operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        locked = False
        try:
            try:
                fcntl.flock(descriptor, lock_operation)
                locked = True
            except OSError as exc:
                raise FeedbackError(
                    f"{path}: cannot acquire interprocess JSONL lock: {exc}"
                ) from exc
            # Revalidate after waiting: another actor may have replaced the
            # directory entry while this process was blocked on the old inode.
            _assert_open_identity(path, descriptor, parent_descriptor, leaf)
            yield handle
            _assert_open_identity(path, descriptor, parent_descriptor, leaf)
        finally:
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)
            os.close(parent_descriptor)


def _encode_jsonl_record(record: Mapping[str, Any]) -> bytes:
    if not isinstance(record, Mapping):
        raise FeedbackValidationError("JSONL record must be a mapping")
    _validate_event_record(record)
    _assert_no_sensitive_data(record)
    try:
        return (
            json.dumps(
                dict(record),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FeedbackValidationError(
            f"record is not JSON serialisable: {exc}"
        ) from exc


def _read_jsonl_descriptor(
    path: Path,
    descriptor: int,
    parent_descriptor: int,
    leaf: str,
) -> list[dict[str, Any]]:
    info = _assert_open_identity(path, descriptor, parent_descriptor, leaf)
    if info.st_size > MAX_FEEDBACK_LOG_BYTES:
        raise _unsafe_log(path, f"JSONL byte limit exceeded ({MAX_FEEDBACK_LOG_BYTES})")
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = MAX_FEEDBACK_LOG_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError as exc:
        raise _unsafe_log(path, f"cannot read JSONL file: {exc}") from exc
    raw = b"".join(chunks)
    if len(raw) > MAX_FEEDBACK_LOG_BYTES:
        raise _unsafe_log(path, f"JSONL byte limit exceeded ({MAX_FEEDBACK_LOG_BYTES})")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _unsafe_log(
            path, f"JSONL is not valid UTF-8 at byte {exc.start}"
        ) from exc

    if text and not text.endswith("\n"):
        line_number = text.count("\n") + 1
        raise _unsafe_log(path, f"line {line_number}: truncated JSONL record")
    lines = text[:-1].split("\n") if text else []
    if len(lines) > MAX_FEEDBACK_LOG_RECORDS:
        raise _unsafe_log(
            path, f"JSONL record limit exceeded ({MAX_FEEDBACK_LOG_RECORDS})"
        )
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        def reject_constant(value: str) -> Any:
            raise ValueError(f"non-finite JSON number: {value}")

        try:
            value = json.loads(
                line,
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise _unsafe_log(
                path, f"line {line_number}: invalid JSON: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise _unsafe_log(
                path, f"line {line_number}: JSONL record is not an object"
            )
        try:
            _validate_event_record(value)
        except FeedbackValidationError as exc:
            raise _unsafe_log(
                path, f"line {line_number}: invalid event schema: {exc}"
            ) from exc
        events.append(value)
    return events


def _append_encoded_descriptor(
    path: Path,
    descriptor: int,
    parent_descriptor: int,
    leaf: str,
    encoded: bytes,
    *,
    existing_records: int,
) -> None:
    info = _assert_open_identity(path, descriptor, parent_descriptor, leaf)
    if existing_records >= MAX_FEEDBACK_LOG_RECORDS:
        raise _unsafe_log(
            path, f"JSONL record limit exceeded ({MAX_FEEDBACK_LOG_RECORDS})"
        )
    if len(encoded) > MAX_FEEDBACK_LOG_BYTES - info.st_size:
        raise _unsafe_log(path, f"JSONL byte limit exceeded ({MAX_FEEDBACK_LOG_BYTES})")
    view = memoryview(encoded)
    try:
        while view:
            written = os.write(descriptor, view)
            if written <= 0:  # pragma: no cover - defensive OS boundary
                raise OSError("short JSONL append")
            view = view[written:]
        os.fsync(descriptor)
    except OSError as exc:
        raise FeedbackError(f"{path}: cannot append JSONL record: {exc}") from exc
    final = _assert_open_identity(path, descriptor, parent_descriptor, leaf)
    if final.st_size > MAX_FEEDBACK_LOG_BYTES:
        raise _unsafe_log(path, f"JSONL byte limit exceeded ({MAX_FEEDBACK_LOG_BYTES})")


def append_jsonl_atomic(path: str | Path, record: Mapping[str, Any]) -> None:
    """Append exactly one compact, fsynced JSON object under a file lock."""

    encoded = _encode_jsonl_record(record)
    destination = Path(path)
    with _locked_log(destination, create=True, exclusive=True) as handle:
        assert handle is not None
        descriptor, parent_descriptor, leaf = handle
        existing = _read_jsonl_descriptor(
            destination, descriptor, parent_descriptor, leaf
        )
        _append_encoded_descriptor(
            destination,
            descriptor,
            parent_descriptor,
            leaf,
            encoded,
            existing_records=len(existing),
        )


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read an audit log fail-closed; malformed/truncated lines are errors."""

    source = Path(path)
    with _locked_log(source, create=False, exclusive=False) as handle:
        if handle is None:
            return []
        descriptor, parent_descriptor, leaf = handle
        return _read_jsonl_descriptor(
            source, descriptor, parent_descriptor, leaf
        )


def _validate_review(review: Mapping[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_REVIEW_FIELDS - set(review))
    if missing:
        raise FeedbackValidationError(
            f"review is missing required fields: {', '.join(missing)}"
        )
    review_id = review.get("review_id")
    if not isinstance(review_id, str) or not REVIEW_ID_RE.fullmatch(review_id):
        raise FeedbackValidationError("review_id has an invalid format")
    for field in ("timestamp", "skill_version", "rules_version", "input_revision"):
        if not isinstance(review.get(field), str) or not review[field].strip():
            raise FeedbackValidationError(f"{field} must be a non-empty string")
    for field in ("findings", "suppressed_findings", "observations"):
        value = review.get(field)
        if isinstance(value, (str, bytes)) or not isinstance(value, list):
            raise FeedbackValidationError(f"{field} must be a list")
        if not all(isinstance(item, Mapping) for item in value):
            raise FeedbackValidationError(f"every {field} item must be an object")
    if not isinstance(review.get("verdict"), str) or not review["verdict"]:
        raise FeedbackValidationError("verdict must be a non-empty string")
    if not isinstance(review.get("escalation"), bool):
        raise FeedbackValidationError("escalation must be a boolean")
    if review.get("architect_action") is not None:
        raise FeedbackValidationError(
            "initial review architect_action must be null; append a human action event"
        )
    event = dict(review)
    event["event_type"] = "review"
    event.setdefault("architect_action", None)
    _assert_no_sensitive_data(event)
    return event


def _require_event_fields(
    event: Mapping[str, Any],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
    event_type: str,
) -> None:
    if any(not isinstance(key, str) for key in event):
        raise FeedbackValidationError(f"{event_type} event keys must be strings")
    keys = set(event)
    missing = sorted(required - keys)
    extra = sorted(keys - allowed)
    if missing:
        raise FeedbackValidationError(
            f"{event_type} event is missing fields: {', '.join(missing)}"
        )
    if extra:
        raise FeedbackValidationError(
            f"{event_type} event has unknown fields: {', '.join(extra)}"
        )


def _nonempty_event_text(event: Mapping[str, Any], field: str) -> str:
    value = event.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FeedbackValidationError(f"{field} must be a non-empty string")
    return value


def _validate_review_event(event: Mapping[str, Any]) -> None:
    _require_event_fields(
        event,
        required=REQUIRED_REVIEW_FIELDS | {"event_type", "architect_action"},
        allowed=REVIEW_EVENT_FIELDS,
        event_type="review",
    )
    if event.get("event_type") != "review":
        raise FeedbackValidationError("review event_type must be review")
    # Reuse the public intake contract for all nested list/type invariants.
    _validate_review({key: value for key, value in event.items() if key != "event_type"})
    for field in ("pr", "title"):
        value = event.get(field)
        if value is not None and not isinstance(value, str):
            raise FeedbackValidationError(f"review {field} must be a string or null")
    input_path_hash = event.get("input_path_hash")
    if input_path_hash is not None and (
        not isinstance(input_path_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", input_path_hash) is None
    ):
        raise FeedbackValidationError(
            "review input_path_hash must be a lowercase SHA-256"
        )
    has_classification = "llm_result_classification" in event
    has_release_marker = "llm_release_evidence" in event
    if has_classification != has_release_marker:
        raise FeedbackValidationError(
            "review LLM classification and release marker must be supplied together"
        )
    if has_classification and (
        event.get("llm_result_classification") != "synthetic_fixture_non_release"
        or event.get("llm_release_evidence") is not False
    ):
        raise FeedbackValidationError(
            "review fixture classification must remain synthetic/non-release"
        )


def _validate_architect_action_event(event: Mapping[str, Any]) -> None:
    _require_event_fields(
        event,
        required=ARCHITECT_ACTION_EVENT_FIELDS,
        allowed=ARCHITECT_ACTION_EVENT_FIELDS,
        event_type="architect_action",
    )
    if event.get("event_type") != "architect_action":
        raise FeedbackValidationError(
            "architect action event_type must be architect_action"
        )
    review_id = _nonempty_event_text(event, "review_id")
    if REVIEW_ID_RE.fullmatch(review_id) is None:
        raise FeedbackValidationError("architect action review_id has an invalid format")
    _nonempty_event_text(event, "timestamp")
    action = event.get("action")
    if action not in ARCHITECT_ACTIONS:
        raise FeedbackValidationError(
            f"architect action must be one of {sorted(ARCHITECT_ACTIONS)}"
        )
    _nonempty_event_text(event, "actor")
    rationale = event.get("rationale")
    if rationale is not None and (
        not isinstance(rationale, str) or not rationale.strip()
    ):
        raise FeedbackValidationError(
            "architect action rationale must be non-empty text or null"
        )
    if action in {"override", "missed"} and rationale is None:
        raise FeedbackValidationError(f"{action} requires a rationale")
    severity = event.get("severity")
    if severity is not None and severity not in SEVERITIES:
        raise FeedbackValidationError("architect action severity is invalid")
    if action == "missed" and severity is None:
        raise FeedbackValidationError("missed action requires severity")
    rule_id = event.get("rule_id")
    if rule_id is not None and (
        not isinstance(rule_id, str) or not rule_id.strip()
    ):
        raise FeedbackValidationError(
            "architect action rule_id must be non-empty text or null"
        )


def _validate_evolution_event(event: Mapping[str, Any]) -> None:
    result = event.get("result")
    if result not in {"passed", "failed_gate", "validation_error"}:
        raise FeedbackValidationError("evolution result has an invalid value")
    if result == "validation_error":
        required = EVOLUTION_COMMON_FIELDS | {"error"}
        allowed = required
    else:
        required = EVOLUTION_COMMON_FIELDS | EVOLUTION_FITNESS_FIELDS
        allowed = required
        if result == "passed":
            allowed |= {"generated_artifacts", "publisher_result"}
    _require_event_fields(
        event,
        required=required,
        allowed=allowed,
        event_type="evolution_attempt",
    )
    if event.get("event_type") != "evolution_attempt":
        raise FeedbackValidationError(
            "evolution event_type must be evolution_attempt"
        )
    for field in ("cycle_id", "timestamp", "precedent"):
        _nonempty_event_text(event, field)
    attempt = event.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise FeedbackValidationError("evolution attempt must be a positive integer")
    gate_checks = event.get("gate_checks")
    if not isinstance(gate_checks, list) or any(
        not isinstance(check, Mapping) for check in gate_checks
    ):
        raise FeedbackValidationError("evolution gate_checks must be an object array")
    for index, check in enumerate(gate_checks):
        if set(check) != {"id", "description", "passed", "before", "after"}:
            raise FeedbackValidationError(
                f"evolution gate_checks[{index}] has an invalid exact schema"
            )
        if (
            not isinstance(check["id"], str)
            or not check["id"]
            or not isinstance(check["description"], str)
            or not check["description"]
            or not isinstance(check["passed"], bool)
        ):
            raise FeedbackValidationError(
                f"evolution gate_checks[{index}] has invalid field types"
            )
    if result == "validation_error":
        _nonempty_event_text(event, "error")
        return
    for field in ("base_revision", "candidate_revision", "corpus_revision"):
        _nonempty_event_text(event, field)
    for field in ("mutation", "metrics_before", "metrics_after"):
        if not isinstance(event.get(field), Mapping):
            raise FeedbackValidationError(f"evolution {field} must be an object")
    has_artifacts = "generated_artifacts" in event
    has_publisher = "publisher_result" in event
    if has_artifacts != has_publisher:
        raise FeedbackValidationError(
            "evolution generated artifacts and publisher result must be supplied together"
        )
    if has_artifacts and (
        not isinstance(event["generated_artifacts"], Mapping)
        or not isinstance(event["publisher_result"], Mapping)
    ):
        raise FeedbackValidationError(
            "evolution generated artifacts and publisher result must be objects"
        )


def _validate_event_record(event: Mapping[str, Any]) -> None:
    if not isinstance(event, Mapping):
        raise FeedbackValidationError("JSONL event must be an object")
    event_type = event.get("event_type")
    if event_type == "review":
        _validate_review_event(event)
    elif event_type == "architect_action":
        _validate_architect_action_event(event)
    elif event_type == "evolution_attempt":
        _validate_evolution_event(event)
    else:
        raise FeedbackValidationError(
            "event_type must be review, architect_action, or evolution_attempt"
        )
    _assert_no_sensitive_data(event)


def log_review(path: str | Path, review: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and append a review exactly once."""

    event = _validate_review(review)
    destination = Path(path)
    encoded = _encode_jsonl_record(event)
    with _locked_log(destination, create=True, exclusive=True) as handle:
        assert handle is not None
        descriptor, parent_descriptor, leaf = handle
        existing = _read_jsonl_descriptor(
            destination, descriptor, parent_descriptor, leaf
        )
        if any(
            item.get("event_type") == "review"
            and item.get("review_id") == event["review_id"]
            for item in existing
        ):
            raise DuplicateFeedbackError(f"duplicate review_id: {event['review_id']}")
        _append_encoded_descriptor(
            destination,
            descriptor,
            parent_descriptor,
            leaf,
            encoded,
            existing_records=len(existing),
        )
    return event


def _find_review(
    events: Iterable[Mapping[str, Any]], review_id: str
) -> Mapping[str, Any]:
    for event in events:
        if event.get("event_type") == "review" and event.get("review_id") == review_id:
            return event
    raise ReviewNotFoundError(f"unknown review_id: {review_id}")


def record_architect_action(
    path: str | Path,
    *,
    review_id: str,
    action: str,
    actor: str,
    rationale: str | None = None,
    severity: str | None = None,
    rule_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Append one validated human action referencing an existing review."""

    if action not in ARCHITECT_ACTIONS:
        raise FeedbackValidationError(
            f"action must be one of {sorted(ARCHITECT_ACTIONS)}"
        )
    if not isinstance(actor, str) or not actor.strip():
        raise FeedbackValidationError("actor identity is required")
    if action in {"override", "missed"} and (
        not isinstance(rationale, str) or not rationale.strip()
    ):
        raise FeedbackValidationError(f"{action} requires a rationale")
    if severity is not None and severity not in SEVERITIES:
        raise FeedbackValidationError("severity must be blocker, major, or minor")
    if action == "missed" and severity is None:
        raise FeedbackValidationError("missed action requires the missed severity")
    if rule_id is not None and (not isinstance(rule_id, str) or not rule_id.strip()):
        raise FeedbackValidationError("rule_id must be a non-empty string or null")
    destination = Path(path)
    with _locked_log(destination, create=True, exclusive=True) as handle:
        assert handle is not None
        descriptor, parent_descriptor, leaf = handle
        events = _read_jsonl_descriptor(
            destination, descriptor, parent_descriptor, leaf
        )
        _find_review(events, review_id)
        if any(
            item.get("event_type") == "architect_action"
            and item.get("review_id") == review_id
            for item in events
        ):
            raise DuplicateFeedbackError(
                f"architect action already recorded for review {review_id}"
            )
        event = {
            "event_type": "architect_action",
            "review_id": review_id,
            "timestamp": timestamp or _utc_now(),
            "action": action,
            "actor": actor.strip(),
            "rationale": rationale.strip() if isinstance(rationale, str) else None,
            "severity": severity,
            "rule_id": rule_id,
        }
        encoded = _encode_jsonl_record(event)
        _append_encoded_descriptor(
            destination,
            descriptor,
            parent_descriptor,
            leaf,
            encoded,
            existing_records=len(events),
        )
    return event


def _action_for_review(
    events: Iterable[Mapping[str, Any]], review_id: str
) -> Mapping[str, Any]:
    for event in events:
        if (
            event.get("event_type") == "architect_action"
            and event.get("review_id") == review_id
        ):
            return event
    raise FeedbackValidationError(
        f"review {review_id} has no approved architect action"
    )


def _select_agent_finding(
    review: Mapping[str, Any], action: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    findings = review.get("findings", [])
    rule_id = action.get("rule_id")
    if rule_id:
        matches = [item for item in findings if item.get("rule_id") == rule_id]
        if len(matches) != 1:
            raise FeedbackValidationError(
                f"expected one finding for rule {rule_id}, got {len(matches)}"
            )
        return dict(matches[0])
    if action.get("action") == "override":
        if len(findings) != 1:
            raise FeedbackValidationError(
                "override with multiple findings requires an explicit rule_id"
            )
        return dict(findings[0])
    return None


def precedent_priority(precedent: Mapping[str, Any]) -> int:
    """Required ordering: missed blocker, false blocker, missed major, minor."""

    category = precedent.get("priority_category")
    if category:
        priorities = {
            "missed_blocker": 0,
            "false_blocker": 1,
            "missed_major": 2,
            "noisy_minor": 3,
        }
        return priorities.get(str(category), 4)
    action = precedent.get("architect_action")
    severity = precedent.get("severity")
    if action == "missed" and severity == "blocker":
        return 0
    if action == "override" and severity == "blocker":
        return 1
    if action == "missed" and severity == "major":
        return 2
    if severity == "minor":
        return 3
    return 4


def sort_pending_precedents(
    precedents: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    pending = [item for item in precedents if item.get("status") == "pending"]
    return sorted(
        pending,
        key=lambda item: (
            precedent_priority(item),
            str(item.get("timestamp", item.get("date", ""))),
            str(item.get("id", "")),
        ),
    )


def validate_precedent_schema(precedent: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "id",
        "review_id",
        "architect_action",
        "architect",
        "rationale",
        "severity",
        "status",
        "distilled_in",
    }
    missing = sorted(required - set(precedent))
    if missing:
        raise FeedbackValidationError(
            f"precedent is missing fields: {', '.join(missing)}"
        )
    if precedent.get("architect_action") not in {"override", "missed"}:
        raise FeedbackValidationError("only override/missed can produce a precedent")
    status = precedent.get("status")
    if status not in {"pending", "distilled", "rejected", "backlog"}:
        raise FeedbackValidationError("invalid precedent status")
    distilled_in = precedent.get("distilled_in")
    if status == "distilled" and (
        not isinstance(distilled_in, str) or not distilled_in.strip()
    ):
        raise FeedbackValidationError("distilled precedent requires distilled_in")
    if status != "distilled" and distilled_in is not None:
        raise FeedbackValidationError(
            "distilled_in must be null unless status is distilled"
        )
    if precedent.get("severity") not in SEVERITIES:
        raise FeedbackValidationError("precedent severity is invalid")
    _assert_no_sensitive_data(precedent, "precedent")
    return dict(precedent)


def generate_pending_precedent(
    log_path: str | Path,
    precedents_dir: str | Path,
    *,
    review_id: str,
    precedent_id: str,
    golden_case: str | None = None,
    proposed_mutation: Mapping[str, Any] | None = None,
) -> Path:
    """Create, never overwrite, a pending Markdown/YAML precedent."""

    if not PRECEDENT_ID_RE.fullmatch(precedent_id):
        raise FeedbackValidationError("precedent_id has an invalid format")
    if (golden_case is None) != (proposed_mutation is None):
        raise FeedbackValidationError(
            "golden_case and proposed_mutation must be supplied together"
        )
    if golden_case is not None and not re.fullmatch(r"pr-\d{2,}", golden_case):
        raise FeedbackValidationError("golden_case must use the pr-NN format")
    if proposed_mutation is not None and not isinstance(proposed_mutation, Mapping):
        raise FeedbackValidationError("proposed_mutation must be a mapping")
    events = read_jsonl(log_path)
    review = _find_review(events, review_id)
    action = _action_for_review(events, review_id)
    if action.get("action") not in {"override", "missed"}:
        raise FeedbackValidationError(
            "only approved override/missed actions create pending precedents"
        )
    finding = _select_agent_finding(review, action)
    severity = action.get("severity") or (finding or {}).get("severity")
    rule_id = action.get("rule_id") or (finding or {}).get("rule_id")
    category = "other"
    if action["action"] == "missed" and severity == "blocker":
        category = "missed_blocker"
    elif action["action"] == "override" and severity == "blocker":
        category = "false_blocker"
    elif action["action"] == "missed" and severity == "major":
        category = "missed_major"
    elif severity == "minor":
        category = "noisy_minor"
    precedent = validate_precedent_schema(
        {
            "schema": "aga.precedent/v1",
            "id": precedent_id,
            "date": str(action["timestamp"])[:10],
            "timestamp": action["timestamp"],
            "review_id": review_id,
            "pr": review.get("pr"),
            "input_revision": review.get("input_revision"),
            "rule_id": rule_id,
            "golden_case": golden_case,
            "proposed_mutation": (
                dict(proposed_mutation) if proposed_mutation is not None else None
            ),
            "agent_finding": finding,
            "architect_action": action["action"],
            "architect": action["actor"],
            "rationale": action["rationale"],
            "severity": severity,
            "priority_category": category,
            "status": "pending",
            "distilled_in": None,
        }
    )
    frontmatter = yaml.safe_dump(
        precedent, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip()
    body = (
        f"---\n{frontmatter}\n---\n"
        f"# Pending precedent {precedent_id}\n\n"
        f"Generated from append-only review `{review_id}`; human validation is "
        "required before distillation.\n"
    ).encode("utf-8")
    directory = Path(precedents_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{precedent_id}.md"
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise DuplicateFeedbackError(
            f"precedent already exists: {destination}"
        ) from exc
    try:
        written = os.write(fd, body)
        if written != len(body):
            raise OSError(f"short precedent write: {written}/{len(body)} bytes")
        os.fsync(fd)
    except OSError:
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(fd)
    return destination


class ReviewLog:
    """Small OO facade over the append-only functional API."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append_review(self, review: Mapping[str, Any]) -> dict[str, Any]:
        return log_review(self.path, review)

    def record_architect_action(self, **kwargs: Any) -> dict[str, Any]:
        return record_architect_action(self.path, **kwargs)

    def events(self) -> list[dict[str, Any]]:
        return read_jsonl(self.path)


__all__ = [
    "ARCHITECT_ACTIONS",
    "DuplicateFeedbackError",
    "FeedbackError",
    "FeedbackLogCorruptError",
    "FeedbackValidationError",
    "ReviewLog",
    "ReviewNotFoundError",
    "append_jsonl_atomic",
    "generate_pending_precedent",
    "log_review",
    "precedent_priority",
    "read_jsonl",
    "record_architect_action",
    "sort_pending_precedents",
    "validate_precedent_schema",
]
