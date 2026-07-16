# -*- coding: utf-8 -*-
"""Safe, offline-first LLM adapter contract for AGA findings.

This module contains no network implementation.  An external adapter must
declare that it requires network access, and callers must opt in explicitly.
Raw model text is accepted only after JSON/schema validation.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import time
from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable


SEVERITY_ORDER = {"minor": 1, "major": 2, "blocker": 3}
FINDING_FIELDS = frozenset(
    {
        "rule_id",
        "severity",
        "confidence",
        "artifact",
        "location",
        "evidence",
        "source_ref",
        "suggested_fix",
    }
)
RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]*-\d{3,}$")
DEFAULT_MAX_RESPONSE_BYTES = 256_000
DEFAULT_MAX_FINDINGS = 100
DEFAULT_MAX_TIMEOUT_SECONDS = 120.0
MAX_FIELD_CHARS = 16_000


class LLMError(RuntimeError):
    """Base class for safe LLM failures."""


class LLMTransportError(LLMError):
    """Network/adapter transport failed."""


class LLMTimeoutError(LLMTransportError):
    """The adapter timed out."""


class LLMHTTPError(LLMTransportError):
    """A network adapter received a non-success status."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}{': ' + message if message else ''}")


class LLMNetworkDisabledError(LLMTransportError):
    """A network adapter was invoked without explicit permission."""


class LLMResponseTooLargeError(LLMTransportError):
    """The response exceeded the configured byte limit."""


class LLMSchemaError(LLMError, ValueError):
    """Parsed JSON does not satisfy the strict findings schema."""


class LLMInvalidJSONError(LLMSchemaError):
    """The response is not valid UTF-8 JSON."""


@dataclass(frozen=True)
class LLMRequest:
    """Trusted instruction and untrusted artifact content remain separate."""

    system_instruction: str
    artifact_content: str
    timeout_seconds: float = 30.0
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.system_instruction, str) or not self.system_instruction:
            raise ValueError("system_instruction must be a non-empty string")
        if not isinstance(self.artifact_content, str):
            raise ValueError("artifact_content must be a string")
        invalid_timeout = (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not 0 < float(self.timeout_seconds) <= DEFAULT_MAX_TIMEOUT_SECONDS
        )
        if invalid_timeout:
            raise ValueError(
                "timeout_seconds must be finite and in "
                f"(0, {DEFAULT_MAX_TIMEOUT_SECONDS:g}]"
            )
        invalid_response_limit = (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or self.max_response_bytes <= 0
        )
        if invalid_response_limit:
            raise ValueError("max_response_bytes must be a positive integer")


@dataclass(frozen=True)
class ValidatedLLMResult:
    findings: tuple[Mapping[str, Any], ...]
    observations: tuple[Mapping[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "findings": [dict(item) for item in self.findings],
            "observations": [dict(item) for item in self.observations],
        }


@runtime_checkable
class LLMAdapter(Protocol):
    """Synchronous adapter contract with an explicit network declaration.

    ``complete`` must honour ``request.timeout_seconds`` itself.  The caller
    deliberately does not detach adapter work into a background thread: a
    timed-out review must never return while adapter code can still perform
    late side effects.
    """

    requires_network: bool

    def complete(self, request: LLMRequest) -> str | bytes | Mapping[str, Any] | Sequence[Any]:
        ...


class FixtureLLMAdapter:
    """Deterministic adapter for unit tests and offline evaluation."""

    requires_network = False

    def __init__(
        self,
        response: str | bytes | Mapping[str, Any] | Sequence[Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        if response is not None and error is not None:
            raise ValueError("configure either response or error, not both")
        self._response = {"findings": []} if response is None else response
        self._error = error
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> str | bytes | Mapping[str, Any] | Sequence[Any]:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        return self._response


def _response_bytes(raw: Any) -> bytes:
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        return raw.encode("utf-8")
    if isinstance(raw, (Mapping, Sequence)) and not isinstance(raw, (str, bytes)):
        try:
            return json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        except RecursionError as exc:
            raise LLMSchemaError(
                "fixture/adapter result exceeds the JSON nesting limit"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise LLMSchemaError(f"fixture/adapter result is not JSON serialisable: {exc}") from exc
    raise LLMSchemaError("adapter must return JSON text/bytes or a JSON-compatible value")


def _parse_response(raw: Any, max_response_bytes: int) -> Any:
    payload = _response_bytes(raw)
    if len(payload) > max_response_bytes:
        raise LLMResponseTooLargeError(
            f"LLM response is {len(payload)} bytes; limit is {max_response_bytes}"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LLMInvalidJSONError("LLM response is not valid UTF-8") from exc
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise LLMInvalidJSONError(
            "LLM JSON exceeds the nesting limit"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LLMInvalidJSONError(
            f"invalid LLM JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc


def validate_finding(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one finding against the exact SKILL.md section 5 schema."""

    if not isinstance(raw, Mapping):
        raise LLMSchemaError("each finding must be an object")
    keys = set(raw)
    missing = sorted(FINDING_FIELDS - keys)
    extra = sorted(keys - FINDING_FIELDS)
    if missing:
        raise LLMSchemaError(f"finding is missing fields: {', '.join(missing)}")
    if extra:
        raise LLMSchemaError(f"finding has unknown fields: {', '.join(extra)}")
    rule_id = raw.get("rule_id")
    if not isinstance(rule_id, str) or not RULE_ID_RE.fullmatch(rule_id):
        raise LLMSchemaError("finding.rule_id has an invalid format")
    if raw.get("severity") not in SEVERITY_ORDER:
        raise LLMSchemaError("finding.severity must be blocker, major, or minor")
    confidence = raw.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise LLMSchemaError("finding.confidence must be a number")
    if not 0.0 <= float(confidence) <= 1.0:
        raise LLMSchemaError("finding.confidence must be in [0, 1]")
    for field in (
        "artifact",
        "location",
        "evidence",
        "source_ref",
        "suggested_fix",
    ):
        value = raw.get(field)
        if not isinstance(value, str):
            raise LLMSchemaError(f"finding.{field} must be a string")
        if len(value) > MAX_FIELD_CHARS:
            raise LLMSchemaError(f"finding.{field} exceeds {MAX_FIELD_CHARS} chars")
    if not raw["artifact"].strip():
        raise LLMSchemaError("finding.artifact must not be empty")
    if not raw["evidence"].strip():
        raise LLMSchemaError("finding.evidence must not be empty")
    if not raw["source_ref"].strip():
        raise LLMSchemaError("finding.source_ref must not be empty")
    finding = dict(raw)
    finding["confidence"] = float(confidence)
    return finding


def apply_confidence_policy(
    findings: Iterable[Mapping[str, Any]],
) -> ValidatedLLMResult:
    """Apply SKILL policy: <.40 observation; low-confidence blocker -> major."""

    accepted: list[Mapping[str, Any]] = []
    observations: list[Mapping[str, Any]] = []
    for raw in findings:
        finding = validate_finding(raw)
        confidence = finding["confidence"]
        if confidence < 0.40:
            observation = dict(finding)
            observation["original_severity"] = observation.pop("severity")
            observation["low_confidence"] = True
            observation["observation_type"] = "low_confidence"
            observations.append(observation)
            continue
        if finding["severity"] == "blocker" and confidence < 0.70:
            finding["severity"] = "major"
            finding["low_confidence"] = True
            finding["original_severity"] = "blocker"
        accepted.append(finding)
    return ValidatedLLMResult(tuple(accepted), tuple(observations))


def validate_llm_response(
    raw: Any,
    *,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_findings: int = DEFAULT_MAX_FINDINGS,
) -> ValidatedLLMResult:
    """Parse JSON, enforce schema, then apply the confidence policy."""

    if max_response_bytes <= 0 or max_findings <= 0:
        raise ValueError("response limits must be positive")
    parsed = _parse_response(raw, max_response_bytes)
    if isinstance(parsed, list):
        findings = parsed
    elif isinstance(parsed, dict):
        if set(parsed) != {"findings"}:
            raise LLMSchemaError("root object must contain only the findings field")
        findings = parsed["findings"]
    else:
        raise LLMSchemaError("LLM JSON root must be an object or findings array")
    if not isinstance(findings, list):
        raise LLMSchemaError("findings must be an array")
    if len(findings) > max_findings:
        raise LLMSchemaError(
            f"too many findings: {len(findings)}; limit is {max_findings}"
        )
    return apply_confidence_policy(findings)


def invoke_llm(
    adapter: LLMAdapter,
    request: LLMRequest,
    *,
    network_enabled: bool = False,
) -> ValidatedLLMResult:
    """Run a synchronous adapter with explicit permission and typed failures.

    Python cannot safely cancel arbitrary in-process adapter code.  Running it
    synchronously is therefore intentional: if an adapter violates its own
    deadline, the review waits for it to finish and then fails with a typed
    timeout instead of leaving an unbounded daemon worker behind.
    """

    try:
        requires_network = getattr(adapter, "requires_network", None)
    except Exception as exc:
        raise LLMTransportError(
            "LLM adapter network declaration failed "
            f"({exc.__class__.__name__})"
        ) from exc
    if not isinstance(requires_network, bool):
        raise LLMTransportError("adapter must declare boolean requires_network")
    if not isinstance(network_enabled, bool):
        raise LLMTransportError("network_enabled must be an explicit boolean")
    if requires_network and not network_enabled:
        raise LLMNetworkDisabledError(
            "network adapter is disabled; pass network_enabled=True explicitly"
        )
    started = time.monotonic()
    try:
        raw = adapter.complete(request)
    except LLMError:
        raise
    except TimeoutError as exc:
        raise LLMTimeoutError("LLM request timed out (adapter deadline)") from exc
    except Exception as exc:
        raise LLMTransportError(
            f"LLM adapter failed ({exc.__class__.__name__})"
        ) from exc
    elapsed = time.monotonic() - started
    if elapsed > request.timeout_seconds:
        raise LLMTimeoutError(
            "LLM adapter exceeded its synchronous deadline "
            f"({elapsed:.3f}s > {request.timeout_seconds:.3f}s)"
        )
    return validate_llm_response(
        raw, max_response_bytes=request.max_response_bytes
    )


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


def merge_findings(
    deterministic_findings: Iterable[Mapping[str, Any]],
    llm_findings: Iterable[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Merge channels; deterministic evidence wins equal-severity duplicates."""

    chosen: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    order: list[tuple[str, str, str, str]] = []
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    candidates.extend(("deterministic", item) for item in deterministic_findings)
    candidates.extend(("llm", item) for item in llm_findings)
    for origin, raw in candidates:
        if not isinstance(raw, Mapping):
            raise LLMSchemaError("merged finding must be an object")
        severity = raw.get("severity")
        if severity not in SEVERITY_ORDER:
            raise LLMSchemaError("merged finding has invalid severity")
        if not raw.get("rule_id") or not raw.get("artifact") or not raw.get("source_ref"):
            raise LLMSchemaError(
                "merged finding requires rule_id, artifact, and source_ref"
            )
        finding = dict(raw)
        finding.setdefault("origin", origin)
        key = _dedup_key(finding)
        current = chosen.get(key)
        if current is None:
            chosen[key] = finding
            order.append(key)
            continue
        current_rank = (
            SEVERITY_ORDER[current["severity"]],
            1 if current.get("origin") == "deterministic" else 0,
            float(current.get("confidence", 0.0)),
        )
        candidate_rank = (
            SEVERITY_ORDER[finding["severity"]],
            1 if origin == "deterministic" else 0,
            float(finding.get("confidence", 0.0)),
        )
        if candidate_rank > current_rank:
            chosen[key] = finding
    return tuple(chosen[key] for key in order)


__all__ = [
    "FixtureLLMAdapter",
    "LLMAdapter",
    "LLMError",
    "LLMHTTPError",
    "LLMInvalidJSONError",
    "LLMNetworkDisabledError",
    "LLMRequest",
    "LLMResponseTooLargeError",
    "LLMSchemaError",
    "LLMTimeoutError",
    "LLMTransportError",
    "ValidatedLLMResult",
    "apply_confidence_policy",
    "invoke_llm",
    "merge_findings",
    "validate_finding",
    "validate_llm_response",
]
