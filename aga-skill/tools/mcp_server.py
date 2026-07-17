# -*- coding: utf-8 -*-
"""Dependency-free MCP Streamable HTTP transport for AGA.

The implementation intentionally covers the narrow server contract consumed
by SEAF.ArchTool's pinned ``@modelcontextprotocol/sdk`` 1.29.0 client:
initialize, initialized notification, ping, tools/list and tools/call over a
non-root Streamable HTTP endpoint.  The server is stateless at the MCP session
layer; immutable review state lives in :mod:`tools.review_service` and is
addressed with opaque digests.

No request arguments or bearer values are logged.  The bounded trace records
only hashes, opaque review digests, bounded status fields and duration.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import queue
import re
import socket
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from tools.review_service import (
    ReviewInputError,
    ReviewService,
    ReviewServiceError,
    TOOL_DEFINITIONS,
)


JSONRPC_VERSION = "2.0"
SERVER_NAME = "aga-governance-mcp"
SERVER_VERSION = "2.0.0"
# Project-owned HTTP contract tests target the version expected by the pin.
# Unknown future versions are never echoed as if the server implemented them;
# MCP negotiation falls back to the latest version this server actually supports.
PROTOCOL_VERSION_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2025-11-25"})
LATEST_PROTOCOL_VERSION = "2025-11-25"


class JsonRpcError(RuntimeError):
    def __init__(
        self,
        code: int,
        message: str,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = int(code)
        self.message = message
        self.data = dict(data) if data is not None else None
        super().__init__(message)

    def response(self, request_id: Any) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


class SchemaViolation(ValueError):
    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    value = host.strip("[]")
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class MCPServerConfig:
    host: str = "127.0.0.1"
    port: int = 0
    endpoint: str = "/mcp"
    mode: str = "none"
    bearer_token: str | None = None
    tls_terminated: bool = False
    max_request_bytes: int = 1_048_576
    max_response_bytes: int = 1_048_576
    request_timeout_seconds: float = 20.0
    max_concurrency: int = 8
    max_trace_entries: int = 1_000
    allowed_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host:
            raise ValueError("host must be non-empty")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 0 <= self.port <= 65535:
            raise ValueError("port must be in [0, 65535]")
        if (
            not isinstance(self.endpoint, str)
            or not self.endpoint.startswith("/")
            or self.endpoint == "/"
            or "?" in self.endpoint
            or "#" in self.endpoint
            or self.endpoint.endswith("/")
        ):
            raise ValueError("endpoint must be a non-root absolute path without query or trailing slash")
        aliases = {"loopback": "none", "internal": "internal-network"}
        canonical_mode = aliases.get(self.mode, self.mode)
        if canonical_mode not in {"none", "internal-network", "bearer"}:
            raise ValueError("mode must be none, internal-network, or bearer")
        object.__setattr__(self, "mode", canonical_mode)
        loopback = _is_loopback_host(self.host)
        if canonical_mode == "none" and not loopback:
            raise ValueError(
                "non-loopback bind requires explicit internal-network or bearer mode"
            )
        if canonical_mode == "bearer" and not self.bearer_token:
            raise ValueError("bearer mode requires a bearer token")
        if canonical_mode == "bearer" and not loopback and self.tls_terminated is not True:
            raise ValueError(
                "non-loopback bearer mode requires trusted TLS termination"
            )
        if not isinstance(self.tls_terminated, bool):
            raise ValueError("tls_terminated must be boolean")
        if self.bearer_token is not None and (
            not isinstance(self.bearer_token, str) or not self.bearer_token
        ):
            raise ValueError("bearer_token must be a non-empty string or None")
        if self.max_request_bytes < 256 or self.max_response_bytes < 256:
            raise ValueError("request and response byte limits must be at least 256")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request timeout must be positive")
        if self.max_concurrency <= 0 or self.max_trace_entries <= 0:
            raise ValueError("concurrency and trace limits must be positive")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
                raise ValueError("allowed origins must be HTTP(S) origins without paths")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_json_loads(value: str) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    def invalid_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(
        value,
        object_pairs_hook=object_pairs,
        parse_constant=invalid_constant,
    )


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "number":
        return not isinstance(value, bool) and isinstance(value, (int, float))
    if expected == "integer":
        return not isinstance(value, bool) and isinstance(value, int)
    if expected == "null":
        return value is None
    return False


def validate_json_schema(value: Any, schema: Mapping[str, Any], path: str = "$arguments") -> None:
    """Validate the strict JSON-Schema subset used by the four MCP tools."""
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_json_type_matches(value, item) for item in expected):
            raise SchemaViolation(path, f"expected one of: {', '.join(expected)}")
    elif isinstance(expected, str) and not _json_type_matches(value, expected):
        raise SchemaViolation(path, f"expected {expected}")
    if "const" in schema and value != schema["const"]:
        raise SchemaViolation(path, "does not equal the required constant")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaViolation(path, "is outside the allowed enum")

    if isinstance(value, Mapping):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise SchemaViolation(path, f"missing required property: {key}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise SchemaViolation(path, f"unknown properties: {', '.join(extra)}")
        for key, child in value.items():
            if key in properties:
                validate_json_schema(child, properties[key], f"{path}.{key}")
    elif isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaViolation(path, "contains too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaViolation(path, "contains too many items")
        if schema.get("uniqueItems"):
            canonical = [_canonical_bytes(item) for item in value]
            if len(set(canonical)) != len(canonical):
                raise SchemaViolation(path, "items must be unique")
        child_schema = schema.get("items")
        if isinstance(child_schema, Mapping):
            for index, child in enumerate(value):
                validate_json_schema(child, child_schema, f"{path}[{index}]")
    elif isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaViolation(path, "is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaViolation(path, "is too long")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            raise SchemaViolation(path, "does not match the required pattern")
    elif not isinstance(value, bool) and isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise SchemaViolation(path, "must be a finite number")
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaViolation(path, "is below the minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaViolation(path, "is above the maximum")


class MCPApplication:
    """JSON-RPC dispatcher independent of the HTTP server."""

    def __init__(
        self,
        service: ReviewService,
        config: MCPServerConfig,
        *,
        trace_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.service = service
        self.config = config
        self._tool_definitions = {item["name"]: item for item in TOOL_DEFINITIONS}
        self._semaphore = threading.BoundedSemaphore(config.max_concurrency)
        self._trace: deque[dict[str, Any]] = deque(maxlen=config.max_trace_entries)
        self._trace_lock = threading.Lock()
        self._trace_sink = trace_sink
        self._closed = threading.Event()
        self._active_condition = threading.Condition()
        self._active_workers = 0

    @property
    def trace(self) -> tuple[dict[str, Any], ...]:
        with self._trace_lock:
            return tuple(dict(item) for item in self._trace)

    @property
    def accepting_requests(self) -> bool:
        return not self._closed.is_set()

    def begin_shutdown(self) -> None:
        self._closed.set()

    def wait_for_idle(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._active_condition:
            while self._active_workers:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._active_condition.wait(remaining)
            return True

    def close(self) -> None:
        self.begin_shutdown()
        self.service.close()

    def _record_trace(
        self,
        tool: str,
        arguments: Any,
        status: str,
        started: float,
        output: Any = None,
    ) -> None:
        try:
            args_hash = hashlib.sha256(_canonical_bytes(arguments)).hexdigest()
        except (TypeError, ValueError):
            args_hash = hashlib.sha256(b"<invalid-json>").hexdigest()
        event = {
            "tool": tool,
            "args_sha256": args_hash,
            "status": status,
            "duration_ms": round(max(0.0, (time.monotonic() - started) * 1000.0), 3),
        }
        if isinstance(output, Mapping):
            try:
                event["output_sha256"] = hashlib.sha256(
                    _canonical_bytes(output)
                ).hexdigest()
            except (TypeError, ValueError):
                event["output_sha256"] = hashlib.sha256(
                    b"<invalid-json>"
                ).hexdigest()
            # These bounded correlation/status fields are safe receipts.  Raw
            # findings, prompts, repository IDs/paths/revisions and provider
            # payloads never enter the trace; the full output remains
            # verifiable by hash.  The call-level ``status`` is deliberately
            # not overwritten by the structured output's own status.
            for key in (
                "schema",
                "review_digest",
                "task_digest",
            ):
                value = output.get(key)
                if isinstance(value, str):
                    event[key] = value
            review_id = output.get("review_id")
            if isinstance(review_id, str):
                event["review_id_sha256"] = hashlib.sha256(
                    review_id.encode("utf-8")
                ).hexdigest()
            for key in (
                "status",
                "verdict",
                "incomplete",
                "human_review_required",
                "auto_merge",
            ):
                value = output.get(key)
                if isinstance(value, (str, bool)):
                    event[f"output_{key}"] = value
        if "review_id_sha256" not in event and isinstance(arguments, Mapping):
            # Error tool results intentionally have no structuredContent, but
            # they must remain correlated to the immutable review so the
            # trusted runner can fail closed instead of silently dropping the
            # receipt from its review-scoped trace.
            review_id = arguments.get("review_id")
            if isinstance(review_id, str):
                event["review_id_sha256"] = hashlib.sha256(
                    review_id.encode("utf-8")
                ).hexdigest()
        with self._trace_lock:
            self._trace.append(event)
        if self._trace_sink is not None:
            try:
                self._trace_sink(dict(event))
            except Exception:
                # Observability must never influence the governance verdict.
                pass

    @staticmethod
    def _rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    @staticmethod
    def _validate_id(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise JsonRpcError(-32600, "Invalid Request")

    def _initialise(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, Mapping):
            raise JsonRpcError(-32602, "Invalid params")
        allowed = {"protocolVersion", "capabilities", "clientInfo", "_meta"}
        if set(params) - allowed:
            raise JsonRpcError(-32602, "Invalid initialize params")
        protocol = params.get("protocolVersion")
        if not isinstance(protocol, str) or PROTOCOL_VERSION_RE.fullmatch(protocol) is None:
            raise JsonRpcError(-32602, "Invalid protocolVersion")
        negotiated_protocol = (
            protocol if protocol in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        )
        if not isinstance(params.get("capabilities", {}), Mapping):
            raise JsonRpcError(-32602, "Invalid client capabilities")
        client_info = params.get("clientInfo")
        if not isinstance(client_info, Mapping) or not isinstance(client_info.get("name"), str):
            raise JsonRpcError(-32602, "Invalid clientInfo")
        return {
            "protocolVersion": negotiated_protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }

    @staticmethod
    def _empty_params(params: Any) -> None:
        if params is not None and (not isinstance(params, Mapping) or set(params) - {"_meta"}):
            raise JsonRpcError(-32602, "Invalid params")

    def _error_tool_result(self, error: ReviewServiceError | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(error, ReviewServiceError):
            payload = error.as_dict()
        else:
            payload = dict(error)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                }
            ],
            "isError": True,
        }

    def _execute_tool(self, name: str, arguments: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        operation_started = time.monotonic()
        definition = self._tool_definitions.get(name)
        if definition is None:
            raise JsonRpcError(-32602, "Unknown tool", data={"code": "unknown_tool"})
        try:
            validate_json_schema(arguments, definition["inputSchema"])
        except SchemaViolation as exc:
            raise JsonRpcError(
                -32602,
                "Invalid tool arguments",
                data={"code": "invalid_arguments", "field": exc.path, "message": exc.message},
            ) from exc

        acquired = self._semaphore.acquire(timeout=self.config.request_timeout_seconds)
        if not acquired:
            error = {
                "type": "mcp_tool_error",
                "code": "server_busy",
                "message": "tool concurrency limit reached",
                "retryable": True,
            }
            return "unavailable", self._error_tool_result(error)

        def operation() -> Any:
            if name == "aga_prepare_review":
                return self.service.prepare_review(**dict(arguments))
            if name == "aga_seaf_lookup":
                return self.service.seaf_lookup(**dict(arguments))
            if name == "aga_parse_diagram":
                return self.service.parse_diagram(**dict(arguments))
            if name == "aga_finalize_review":
                return self.service.finalize_review(**dict(arguments))
            raise ReviewServiceError("unknown_tool", "tool is not registered")

        def worker_finished() -> None:
            self._semaphore.release()
            with self._active_condition:
                self._active_workers -= 1
                self._active_condition.notify_all()

        with self._active_condition:
            self._active_workers += 1

        if name in {"aga_prepare_review", "aga_finalize_review"}:
            # These operations mutate immutable-review state.  Running them in
            # the request thread means the transport can never report a
            # timeout and then commit a late prepare/final result.  Prepare has
            # its own bounded trusted-hook timeout; finalize is size-bounded
            # and CPU-only.
            try:
                value = operation()
                succeeded = True
            except BaseException as exc:
                succeeded, value = False, exc
            finally:
                worker_finished()
        else:
            responses: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

            def invoke_read_only() -> None:
                try:
                    responses.put((True, operation()))
                except BaseException as exc:
                    responses.put((False, exc))
                finally:
                    worker_finished()

            worker = threading.Thread(
                target=invoke_read_only, name=f"aga-mcp-{name}", daemon=True
            )
            worker.start()
            remaining = max(
                0.0,
                self.config.request_timeout_seconds - (time.monotonic() - operation_started),
            )
            try:
                succeeded, value = responses.get(timeout=remaining)
            except queue.Empty:
                error = {
                    "type": "mcp_tool_error",
                    "code": "tool_timeout",
                    "message": "read-only tool execution timed out",
                    "retryable": True,
                }
                return "timeout", self._error_tool_result(error)

        if not succeeded:
            if isinstance(value, ReviewInputError):
                raise JsonRpcError(-32602, "Invalid tool arguments", data=value.as_dict())
            if isinstance(value, ReviewServiceError):
                return "error", self._error_tool_result(value)
            error = {
                "type": "mcp_tool_error",
                "code": "tool_internal_error",
                "message": "tool failed without exposing internal details",
                "retryable": False,
            }
            return "error", self._error_tool_result(error)

        try:
            validate_json_schema(value, definition["outputSchema"], "$result")
        except SchemaViolation:
            error = {
                "type": "mcp_tool_error",
                "code": "invalid_tool_output",
                "message": "tool output failed its strict schema",
                "retryable": False,
            }
            return "error", self._error_tool_result(error)
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(value, ensure_ascii=False, sort_keys=True),
                }
            ],
            "structuredContent": value,
            "isError": False,
        }
        status = "incomplete" if value.get("incomplete") is True else "ok"
        return status, result

    def _call_tool(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, Mapping):
            raise JsonRpcError(-32602, "Invalid params")
        allowed = {"name", "arguments", "_meta"}
        if set(params) - allowed or "name" not in params:
            raise JsonRpcError(-32602, "Invalid tools/call params")
        name = params["name"]
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, Mapping):
            raise JsonRpcError(-32602, "Invalid tools/call params")
        started = time.monotonic()
        status = "error"
        result: dict[str, Any] | None = None
        try:
            status, result = self._execute_tool(name, arguments)
            return result
        finally:
            structured = (
                result.get("structuredContent")
                if isinstance(result, Mapping)
                else None
            )
            self._record_trace(name, arguments, status, started, structured)

    def dispatch(self, request: Any) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC object; notifications return ``None``."""
        if self._closed.is_set():
            raise JsonRpcError(-32000, "Server shutting down", data={"code": "shutting_down"})
        if not isinstance(request, Mapping):
            raise JsonRpcError(-32600, "Invalid Request")
        request_id = request.get("id")
        is_notification = "id" not in request
        try:
            if set(request) - {"jsonrpc", "id", "method", "params"}:
                raise JsonRpcError(-32600, "Invalid Request")
            if request.get("jsonrpc") != JSONRPC_VERSION or not isinstance(request.get("method"), str):
                raise JsonRpcError(-32600, "Invalid Request")
            if not is_notification:
                self._validate_id(request_id)
            method = request["method"]
            params = request.get("params")

            if method == "initialize":
                result = self._initialise(params)
            elif method == "notifications/initialized":
                self._empty_params(params)
                return None
            elif method == "ping":
                self._empty_params(params)
                result = {}
            elif method == "tools/list":
                if params is not None:
                    if not isinstance(params, Mapping) or set(params) - {"cursor", "_meta"}:
                        raise JsonRpcError(-32602, "Invalid params")
                    cursor = params.get("cursor")
                    if cursor is not None and cursor != "":
                        raise JsonRpcError(-32602, "Pagination cursor is not supported")
                result = {"tools": [dict(item) for item in TOOL_DEFINITIONS]}
            elif method == "tools/call":
                result = self._call_tool(params)
            else:
                raise JsonRpcError(-32601, "Method not found")
            if is_notification:
                return None
            return self._rpc_result(request_id, result)
        except JsonRpcError:
            valid_notification = (
                is_notification
                and request.get("jsonrpc") == JSONRPC_VERSION
                and isinstance(request.get("method"), str)
            )
            if valid_notification:
                return None
            raise


class _MCPHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        application: MCPApplication,
        config: MCPServerConfig,
    ) -> None:
        self.application = application
        self.mcp_config = config
        self._request_slots = threading.BoundedSemaphore(config.max_concurrency)
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, _MCPRequestHandler)

    def process_request(self, request: Any, client_address: Any) -> None:
        """Bound request threads as well as tool workers."""

        if not self._request_slots.acquire(blocking=False):
            payload = b'{"error":{"code":"server_busy","message":"request concurrency limit reached"}}'
            response = (
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode("ascii")
                + b"Cache-Control: no-store\r\nConnection: close\r\n\r\n"
                + payload
            )
            try:
                request.sendall(response)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class _MCPRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AGA-MCP"
    sys_version = ""

    def handle(self) -> None:
        # Clients may intentionally close after an auth/limit response without
        # consuming the body.  Treat that as an ordinary disconnect instead
        # of letting socketserver print an unsanitized traceback to stderr.
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            return

    @property
    def _config(self) -> MCPServerConfig:
        return self.server.mcp_config  # type: ignore[attr-defined]

    @property
    def _application(self) -> MCPApplication:
        return self.server.application  # type: ignore[attr-defined]

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self._config.request_timeout_seconds)

    def log_message(self, _format: str, *_args: Any) -> None:
        # Default BaseHTTPRequestHandler logging can include the raw URL and
        # is intentionally disabled.  Sanitized tool traces are explicit.
        return

    def _headers(self, content_type: str, content_length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if self.close_connection:
            self.send_header("Connection", "close")

    def _send_bytes(
        self,
        status: int,
        payload: bytes,
        *,
        content_type: str,
    ) -> None:
        if len(payload) > self._config.max_response_bytes:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            payload = b'{"error":{"code":"response_too_large","message":"response limit exceeded"}}'
            content_type = "application/json; charset=utf-8"
        self.send_response(status)
        self._headers(content_type, len(payload))
        self.end_headers()
        if self.command != "HEAD" and payload:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _send_json(self, status: int, value: Any) -> None:
        try:
            payload = _canonical_bytes(value)
        except (TypeError, ValueError):
            payload = b'{"error":{"code":"serialization_error","message":"response serialization failed"}}'
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        if len(payload) > self._config.max_response_bytes:
            request_id = value.get("id") if isinstance(value, Mapping) else None
            payload = _canonical_bytes(
                JsonRpcError(
                    -32003,
                    "Response too large",
                    data={"code": "response_too_large"},
                ).response(request_id)
            )
            status = HTTPStatus.OK
        self._send_bytes(
            status,
            payload,
            content_type="application/json; charset=utf-8",
        )

    def _send_http_error(self, status: int, code: str, message: str) -> None:
        self._send_json(status, {"error": {"code": code, "message": message}})

    def _target_path(self) -> str | None:
        try:
            target = urlsplit(self.path)
        except ValueError:
            return None
        if target.scheme or target.netloc or target.query or target.fragment:
            return None
        return target.path

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin in self._config.allowed_origins:
            return True
        try:
            parsed = urlsplit(origin)
            return parsed.scheme in {"http", "https"} and _is_loopback_host(parsed.hostname or "")
        except ValueError:
            return False

    def _authorized(self) -> bool:
        token = self._config.bearer_token
        # ``internal-network`` is an explicit deployment assertion that the
        # endpoint is reachable only on an isolated network (for example a
        # Compose ``internal: true`` network with no published MCP port).
        if self._config.mode == "internal-network" and token is None:
            return True
        if self._config.mode == "none" and token is None:
            return True
        if token is None:
            return False
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return hmac.compare_digest(header[len(prefix) :], token)

    def _check_mcp_boundary(self) -> bool:
        if self._target_path() != self._config.endpoint:
            self.close_connection = True
            self._send_http_error(HTTPStatus.NOT_FOUND, "not_found", "endpoint not found")
            return False
        if not self._origin_allowed():
            self.close_connection = True
            self._send_http_error(HTTPStatus.FORBIDDEN, "origin_forbidden", "origin is not allowed")
            return False
        if not self._authorized():
            self.close_connection = True
            self._send_http_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "bearer authentication required")
            return False
        if not self._application.accepting_requests:
            self.close_connection = True
            self._send_http_error(HTTPStatus.SERVICE_UNAVAILABLE, "shutting_down", "server is shutting down")
            return False
        return True

    def _protocol_header_valid(self) -> bool:
        return self.headers.get("MCP-Protocol-Version", "") in SUPPORTED_PROTOCOL_VERSIONS

    def _require_protocol_header(self) -> bool:
        if self._protocol_header_valid():
            return True
        self.close_connection = True
        self._send_http_error(
            HTTPStatus.BAD_REQUEST,
            "invalid_protocol_version",
            "MCP-Protocol-Version must match the negotiated supported version",
        )
        return False

    def do_HEAD(self) -> None:  # noqa: N802
        if self._target_path() == "/healthz":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok" if self._application.accepting_requests else "stopping",
                    "service": SERVER_NAME,
                },
            )
            return
        self._send_http_error(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", "HEAD is not supported")

    def do_GET(self) -> None:  # noqa: N802
        if self._target_path() == "/healthz":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok" if self._application.accepting_requests else "stopping",
                    "service": SERVER_NAME,
                },
            )
            return
        if not self._check_mcp_boundary():
            return
        if not self._require_protocol_header():
            return
        accept = self.headers.get("Accept", "*/*").lower()
        if "text/event-stream" not in accept and "*/*" not in accept:
            self._send_http_error(HTTPStatus.NOT_ACCEPTABLE, "not_acceptable", "GET requires text/event-stream")
            return
        # Stateless servers have no unsolicited messages.  A finite SSE
        # comment is nevertheless a bounded GET response on the configured
        # Streamable HTTP path. Actual SDK compatibility is a separate check.
        payload = b": aga-mcp stateless stream\n\n"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._check_mcp_boundary():
            return
        if not self._require_protocol_header():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _read_json_body(self) -> Any:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise JsonRpcError(-32700, "Content-Type must be application/json")
        transfer_encoding = self.headers.get("Transfer-Encoding", "").strip().lower()
        if transfer_encoding:
            raise JsonRpcError(-32700, "Chunked request bodies are not accepted")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise JsonRpcError(-32700, "Content-Length is required")
        try:
            length = int(raw_length, 10)
        except ValueError as exc:
            raise JsonRpcError(-32700, "Invalid Content-Length") from exc
        if length <= 0:
            raise JsonRpcError(-32700, "Empty request body")
        if length > self._config.max_request_bytes:
            raise JsonRpcError(-32001, "Request body too large", data={"code": "request_too_large"})
        try:
            payload = self.rfile.read(length)
        except socket.timeout as exc:
            raise JsonRpcError(-32002, "Request body timed out", data={"code": "request_timeout"}) from exc
        if len(payload) != length:
            raise JsonRpcError(-32700, "Incomplete request body")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JsonRpcError(-32700, "Parse error") from exc
        try:
            return _strict_json_loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise JsonRpcError(-32700, "Parse error") from exc

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_mcp_boundary():
            return
        accept = self.headers.get("Accept", "*/*").lower()
        if "*/*" not in accept and not (
            "application/json" in accept and "text/event-stream" in accept
        ):
            self._send_http_error(
                HTTPStatus.NOT_ACCEPTABLE,
                "not_acceptable",
                "POST Accept must advertise application/json and text/event-stream",
            )
            return
        try:
            payload = self._read_json_body()
        except JsonRpcError as exc:
            self.close_connection = True
            response = exc.response(None)
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if exc.code == -32001 else HTTPStatus.BAD_REQUEST
            self._send_json(status, response)
            return

        # The pinned ArchTool Streamable HTTP contract sends one JSON-RPC
        # request or notification per POST.  Reject every batch array before
        # protocol negotiation and dispatch: otherwise one HTTP request can
        # retain its handler for N independent tool timeouts.
        if isinstance(payload, list):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                JsonRpcError(
                    -32600,
                    "JSON-RPC batch requests are not supported",
                    data={"code": "batch_not_supported"},
                ).response(None),
            )
            return
        requests = [payload]
        methods = [
            request.get("method") for request in requests if isinstance(request, Mapping)
        ]
        initialising = methods == ["initialize"]
        if not initialising and not self._require_protocol_header():
            return
        responses: list[dict[str, Any]] = []
        for request in requests:
            request_id = request.get("id") if isinstance(request, Mapping) else None
            try:
                response = self._application.dispatch(request)
            except JsonRpcError as exc:
                response = exc.response(request_id)
            except Exception:
                response = JsonRpcError(
                    -32603,
                    "Internal error",
                    data={"code": "internal_error"},
                ).response(request_id)
            if response is not None:
                responses.append(response)
        if not responses:
            self.send_response(HTTPStatus.ACCEPTED)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self._send_json(HTTPStatus.OK, responses[0])


class MCPServer:
    """Small lifecycle wrapper around ``ThreadingHTTPServer``."""

    def __init__(
        self,
        service: ReviewService | None = None,
        *,
        config: MCPServerConfig | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        bearer_token: str | None = None,
        trace_sink: Callable[[Mapping[str, Any]], None] | None = None,
        **config_overrides: Any,
    ) -> None:
        if config is not None and config_overrides:
            raise ValueError("pass either config or config overrides")
        if config is None:
            config = MCPServerConfig(
                host=host,
                port=port,
                bearer_token=bearer_token,
                **config_overrides,
            )
        self.config = config
        self.application = MCPApplication(service or ReviewService(), config, trace_sink=trace_sink)
        self._httpd = _MCPHTTPServer((config.host, config.port), self.application, config)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._lifecycle_lock = threading.Lock()

    @property
    def server_address(self) -> tuple[str, int]:
        host, port = self._httpd.server_address[:2]
        return str(host), int(port)

    @property
    def url(self) -> str:
        host, port = self.server_address
        display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"http://{display_host}:{port}{self.config.endpoint}"

    @property
    def trace(self) -> tuple[dict[str, Any], ...]:
        return self.application.trace

    def serve_forever(self) -> None:
        self._running.set()
        try:
            self._httpd.serve_forever(poll_interval=0.1)
        finally:
            self._running.clear()

    def start(self) -> "MCPServer":
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            self._thread = threading.Thread(
                target=self.serve_forever,
                name="aga-mcp-http",
                daemon=True,
            )
            self._thread.start()
        if not self._running.wait(timeout=2.0):
            raise RuntimeError("MCP server did not start")
        return self

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            running = self._running.is_set()
        self.application.begin_shutdown()
        if running:
            self._httpd.shutdown()
        self._httpd.server_close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(2.0, self.config.request_timeout_seconds + 0.5))
        self.application.wait_for_idle(self.config.request_timeout_seconds)
        self.application.close()

    def __enter__(self) -> "MCPServer":
        return self.start()

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.shutdown()


def create_server(
    service: ReviewService | None = None,
    *,
    config: MCPServerConfig | None = None,
    **kwargs: Any,
) -> MCPServer:
    """Compatibility factory for embedding and contract tests."""
    return MCPServer(service, config=config, **kwargs)


__all__ = [
    "JSONRPC_VERSION",
    "MCPApplication",
    "MCPServer",
    "MCPServerConfig",
    "SERVER_NAME",
    "SchemaViolation",
    "create_server",
    "validate_json_schema",
]
