# -*- coding: utf-8 -*-
"""Offline A2A contracts and a fail-closed local task backend.

The real Ouroboros API is deliberately not guessed here.  Integrators can
implement :class:`TaskBackend`; tests and local demo code can use
``LocalTaskBackend`` with explicitly registered handlers.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from enum import Enum
import threading
import uuid
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence, runtime_checkable


class A2AError(RuntimeError):
    """Base class for orchestration errors."""


class A2AConfigurationError(A2AError):
    """A requested task has no configured local handler."""


class UnknownTaskError(A2AError):
    """A task id is not known by this backend."""


class TaskStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


TERMINAL_STATUSES = frozenset(
    {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.TIMED_OUT}
)
SEVERITY_ORDER = {"minor": 1, "major": 2, "blocker": 3}
FINDING_PRECEDENCE = {"SEAF-004": {"PRIN-006"}}


def _same_finding_defect(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("artifact") != right.get("artifact"):
        return False
    left_canonical = left.get("canonical_defect")
    right_canonical = right.get("canonical_defect")
    if left_canonical and right_canonical and left_canonical == right_canonical:
        return True
    left_location = left.get("location")
    right_location = right.get("location")
    if left_location and right_location and left_location == right_location:
        return True
    return (not left_location and not right_location
            and left.get("evidence") == right.get("evidence"))


@dataclass(frozen=True)
class TaskResult:
    """Structured task result; failures are data and cannot look like success."""

    task_id: str
    task_name: str
    status: TaskStatus
    findings: tuple[Mapping[str, Any], ...] = ()
    observations: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status is TaskStatus.SUCCEEDED


@dataclass(frozen=True)
class AggregatedTaskResult:
    """Parent-level result after common deduplication and verdict calculation."""

    findings: tuple[Mapping[str, Any], ...]
    observations: tuple[Mapping[str, Any], ...]
    task_statuses: Mapping[str, str]
    errors: tuple[str, ...]
    complete: bool
    verdict: str
    escalate: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "findings": [dict(item) for item in self.findings],
            "observations": [dict(item) for item in self.observations],
            "task_statuses": dict(self.task_statuses),
            "errors": list(self.errors),
            "complete": self.complete,
            "verdict": self.verdict,
            "escalate": self.escalate,
        }


@runtime_checkable
class TaskBackend(Protocol):
    """Executable A2A interface without assuming an Ouroboros signature."""

    def schedule_task(
        self, task_name: str, payload: Mapping[str, Any] | None = None
    ) -> str:
        ...

    def wait_for_task(self, task_id: str, timeout: float | None = None) -> TaskResult:
        ...

    def get_task_result(self, task_id: str) -> TaskResult:
        ...


TaskHandler = Callable[[Mapping[str, Any]], Mapping[str, Any] | TaskResult]


@dataclass
class _TaskRecord:
    task_id: str
    task_name: str
    future: Future[Any]
    result: TaskResult | None = None


class LocalTaskBackend:
    """Thread-backed offline implementation used by tests and local runs.

    Handlers must be registered explicitly.  A missing handler is a
    configuration error, not an empty successful result.
    """

    def __init__(
        self,
        handlers: Mapping[str, TaskHandler] | None = None,
        *,
        max_workers: int = 4,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._handlers: dict[str, TaskHandler] = dict(handlers or {})
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="aga-a2a"
        )
        self._tasks: dict[str, _TaskRecord] = {}
        self._lock = threading.RLock()
        self._closed = False

    def register_handler(self, task_name: str, handler: TaskHandler) -> None:
        if not task_name or not callable(handler):
            raise ValueError("task_name and callable handler are required")
        with self._lock:
            if self._closed:
                raise A2AConfigurationError("backend is closed")
            self._handlers[task_name] = handler

    def schedule_task(
        self, task_name: str, payload: Mapping[str, Any] | None = None
    ) -> str:
        with self._lock:
            if self._closed:
                raise A2AConfigurationError("backend is closed")
            handler = self._handlers.get(task_name)
            if handler is None:
                raise A2AConfigurationError(
                    f"no local handler configured for task {task_name!r}"
                )
            task_id = uuid.uuid4().hex
            safe_payload = dict(payload or {})
            future = self._executor.submit(handler, safe_payload)
            record = _TaskRecord(task_id, task_name, future)
            self._tasks[task_id] = record
            future.add_done_callback(lambda done, tid=task_id: self._complete(tid, done))
            return task_id

    def _record(self, task_id: str) -> _TaskRecord:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise UnknownTaskError(f"unknown task id: {task_id}") from exc

    def _complete(self, task_id: str, future: Future[Any]) -> TaskResult:
        with self._lock:
            record = self._record(task_id)
            if record.result is not None:
                return record.result
            if future.cancelled():
                result = TaskResult(
                    task_id=record.task_id,
                    task_name=record.task_name,
                    status=TaskStatus.FAILED,
                    error="task was cancelled before completion",
                )
            elif (task_error := future.exception()) is not None:
                result = TaskResult(
                    task_id=record.task_id,
                    task_name=record.task_name,
                    status=TaskStatus.FAILED,
                    error=f"{type(task_error).__name__}: {task_error}",
                )
            else:
                raw = future.result()
                try:
                    result = self._normalise_success(record, raw)
                except (ValueError, TypeError, KeyError) as exc:
                    result = TaskResult(
                        task_id=record.task_id,
                        task_name=record.task_name,
                        status=TaskStatus.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                    )
            record.result = result
            return result

    @staticmethod
    def _normalise_success(record: _TaskRecord, raw: Any) -> TaskResult:
        if isinstance(raw, TaskResult):
            if raw.status is not TaskStatus.SUCCEEDED:
                return TaskResult(
                    task_id=record.task_id,
                    task_name=record.task_name,
                    status=raw.status,
                    findings=raw.findings,
                    observations=raw.observations,
                    error=raw.error,
                    metadata=raw.metadata,
                )
            payload: Mapping[str, Any] = {
                "findings": raw.findings,
                "observations": raw.observations,
                "metadata": raw.metadata,
            }
        elif isinstance(raw, Mapping):
            payload = raw
        else:
            raise TypeError("task handler must return a mapping or TaskResult")

        findings = _validate_findings(payload.get("findings", ()))
        observations = _validate_mapping_sequence(
            payload.get("observations", ()), "observations"
        )
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise TypeError("task result metadata must be a mapping")
        return TaskResult(
            task_id=record.task_id,
            task_name=record.task_name,
            status=TaskStatus.SUCCEEDED,
            findings=findings,
            observations=observations,
            metadata=dict(metadata),
        )

    def wait_for_task(self, task_id: str, timeout: float | None = None) -> TaskResult:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        with self._lock:
            record = self._record(task_id)
            if record.result is not None:
                return record.result
            future = record.future
        try:
            # Wait without re-raising an arbitrary handler exception here;
            # ``_complete`` converts the returned exception into failed data.
            future.exception(timeout=timeout)
        except FutureTimeout:
            with self._lock:
                record = self._record(task_id)
                if record.result is None:
                    future.cancel()
                    record.result = TaskResult(
                        task_id=record.task_id,
                        task_name=record.task_name,
                        status=TaskStatus.TIMED_OUT,
                        error=f"task exceeded timeout of {timeout} seconds",
                    )
                return record.result
        return self._complete(task_id, future)

    def get_task_result(self, task_id: str) -> TaskResult:
        with self._lock:
            record = self._record(task_id)
            if record.result is not None:
                return record.result
            future = record.future
            if not future.done():
                return TaskResult(
                    task_id=record.task_id,
                    task_name=record.task_name,
                    status=TaskStatus.PENDING,
                )
        return self._complete(task_id, future)

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def __enter__(self) -> "LocalTaskBackend":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.shutdown()


def _validate_mapping_sequence(value: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} must be a sequence of mappings")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError(f"every {name} item must be a mapping")
        result.append(dict(item))
    return tuple(result)


def _validate_findings(value: Any) -> tuple[Mapping[str, Any], ...]:
    findings = _validate_mapping_sequence(value, "findings")
    for finding in findings:
        if not isinstance(finding.get("rule_id"), str) or not finding["rule_id"]:
            raise ValueError("finding.rule_id must be a non-empty string")
        if finding.get("severity") not in SEVERITY_ORDER:
            raise ValueError("finding.severity must be blocker, major, or minor")
        if not isinstance(finding.get("source_ref"), str) or not finding["source_ref"]:
            raise ValueError("finding.source_ref must be a non-empty string")
    return findings


def _dedup_key(finding: Mapping[str, Any]) -> tuple[str, str, str, str]:
    canonical = str(finding.get("canonical_defect") or "").strip()
    location = str(finding.get("location") or "").strip()
    if location:
        locator_type, locator = "location", location
    elif canonical:
        locator_type, locator = "defect", canonical
    else:
        locator_type, locator = "evidence", str(finding.get("evidence") or "").strip()
    return (
        str(finding.get("rule_id", "")),
        str(finding.get("artifact", "")),
        locator_type,
        locator,
    )


def deduplicate_findings(
    findings: Iterable[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Canonical dedup: one rule/artifact pair, safest finding wins."""

    selected: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    order: list[tuple[str, str, str, str]] = []
    for raw in findings:
        finding = dict(raw)
        _validate_findings((finding,))
        key = _dedup_key(finding)
        previous = selected.get(key)
        if previous is None:
            selected[key] = finding
            order.append(key)
            continue
        previous_rank = (
            SEVERITY_ORDER[previous["severity"]],
            1 if previous.get("origin") == "deterministic" else 0,
            float(previous.get("confidence", 0.0)),
        )
        candidate_rank = (
            SEVERITY_ORDER[finding["severity"]],
            1 if finding.get("origin") == "deterministic" else 0,
            float(finding.get("confidence", 0.0)),
        )
        if candidate_rank > previous_rank:
            selected[key] = finding
    merged = [selected[key] for key in order]
    for winner, losers in FINDING_PRECEDENCE.items():
        winners = [item for item in merged if item.get("rule_id") == winner]
        merged = [
            item for item in merged
            if not (
                item.get("rule_id") in losers
                and any(_same_finding_defect(specific, item) for specific in winners)
            )
        ]
    return tuple(merged)


def aggregate_task_results(
    results: Iterable[TaskResult],
    *,
    deterministic_findings: Iterable[Mapping[str, Any]] = (),
) -> AggregatedTaskResult:
    """Aggregate task outputs and calculate a fail-closed parent verdict."""

    all_findings = [dict(item) for item in deterministic_findings]
    observations: list[Mapping[str, Any]] = []
    errors: list[str] = []
    statuses: dict[str, str] = {}
    for result in results:
        if not isinstance(result, TaskResult):
            raise TypeError("results must contain TaskResult instances")
        statuses[result.task_id] = result.status.value
        if not result.succeeded:
            errors.append(
                f"{result.task_name} ({result.task_id}): "
                f"{result.error or result.status.value}"
            )
            continue
        all_findings.extend(dict(item) for item in result.findings)
        observations.extend(dict(item) for item in result.observations)

    findings = deduplicate_findings(all_findings)
    if errors:
        # A partial task set is never equivalent to a clean review.
        verdict = "incomplete_error"
        complete = False
        escalate = True
    else:
        severities = {item["severity"] for item in findings}
        if severities & {"blocker", "major"}:
            verdict, escalate = "request_changes_escalate", True
        elif "minor" in severities:
            verdict, escalate = "approve_with_warnings", False
        else:
            verdict, escalate = "approve", False
        complete = True
    return AggregatedTaskResult(
        findings=findings,
        observations=tuple(observations),
        task_statuses=statuses,
        errors=tuple(errors),
        complete=complete,
        verdict=verdict,
        escalate=escalate,
    )


def run_task_group(
    backend: TaskBackend,
    tasks: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    timeout_per_task: float | None = None,
    deterministic_findings: Iterable[Mapping[str, Any]] = (),
) -> AggregatedTaskResult:
    """Schedule, wait and aggregate a group through the protocol surface."""

    task_ids = [backend.schedule_task(name, payload) for name, payload in tasks]
    results = [backend.wait_for_task(task_id, timeout_per_task) for task_id in task_ids]
    return aggregate_task_results(
        results, deterministic_findings=deterministic_findings
    )


__all__ = [
    "A2AConfigurationError",
    "A2AError",
    "AggregatedTaskResult",
    "LocalTaskBackend",
    "TaskBackend",
    "TaskResult",
    "TaskStatus",
    "UnknownTaskError",
    "aggregate_task_results",
    "deduplicate_findings",
    "run_task_group",
]
