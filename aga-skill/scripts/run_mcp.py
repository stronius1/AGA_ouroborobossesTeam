#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the local AGA Streamable HTTP MCP server.

Repository paths are startup-only trusted configuration.  MCP clients see and
send only the registry key plus commit/review/entity identifiers.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
from typing import Any, Sequence


PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from tools.mcp_server import MCPServer, MCPServerConfig  # noqa: E402
from tools.review_service import ReviewService  # noqa: E402


def _positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def _positive_float(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def _environment_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if value in {"", "0", "false", "no"}:
        return False
    if value in {"1", "true", "yes"}:
        return True
    raise argparse.ArgumentTypeError(f"{name} must be true/false")


def _repository(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("use REPOSITORY_ID=/trusted/local/root")
    repository_id, raw_path = value.split("=", 1)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", repository_id) is None:
        raise argparse.ArgumentTypeError("repository ID must be a non-path registry key")
    path = Path(raw_path)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise argparse.ArgumentTypeError("repository root does not exist") from exc
    if path.is_symlink() or not resolved.is_dir():
        raise argparse.ArgumentTypeError("repository root must be a real directory")
    return repository_id, resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AGA MCP Streamable HTTP service")
    auth_mode = os.environ.get("AGA_MCP_AUTH_MODE", "none")
    auth_mode = {"loopback": "none", "internal": "internal-network"}.get(
        auth_mode, auth_mode
    )
    parser.add_argument("--host", default=os.environ.get("AGA_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=os.environ.get("AGA_MCP_PORT", "8788"), type=int)
    parser.add_argument("--endpoint", default=os.environ.get("AGA_MCP_PATH", "/mcp"))
    parser.add_argument(
        "--mode",
        choices=("none", "internal-network", "bearer"),
        default=auth_mode,
        help=(
            "none is loopback-only; internal-network trusts explicit network isolation; "
            "bearer requires the configured token"
        ),
    )
    parser.add_argument(
        "--bearer-token-env",
        default="AGA_MCP_BEARER_TOKEN",
        help="environment variable containing the bearer token; the token is never printed",
    )
    parser.add_argument(
        "--tls-terminated",
        action="store_true",
        default=_environment_flag("AGA_MCP_TLS_TERMINATED"),
        help="assert that a trusted TLS reverse proxy protects this non-loopback bearer endpoint",
    )
    parser.add_argument(
        "--digest-secret-env",
        default="AGA_REVIEW_DIGEST_SECRET",
        help="optional environment variable used to make review/task digests restart-stable",
    )
    parser.add_argument(
        "--repository",
        action="append",
        default=[],
        type=_repository,
        metavar="ID=ROOT",
        help="trusted server-side repository registry entry (repeatable)",
    )
    parser.add_argument(
        "--synthetic-fixture-repository",
        action="append",
        default=[],
        type=_repository,
        metavar="ID=ROOT",
        help=(
            "synthetic-public frozen fixture registry entry; enables fixture "
            "dependency mode and must never be used for real/private repositories"
        ),
    )
    parser.add_argument(
        "--max-request-bytes",
        type=_positive_int,
        default=os.environ.get("AGA_MAX_REQUEST_BYTES", "1048576"),
    )
    parser.add_argument(
        "--max-response-bytes",
        type=_positive_int,
        default=os.environ.get("AGA_MAX_RESPONSE_BYTES", "1048576"),
    )
    parser.add_argument(
        "--request-timeout",
        type=_positive_float,
        default=os.environ.get("AGA_MCP_TIMEOUT_SECONDS", "20.0"),
    )
    parser.add_argument(
        "--prepare-timeout",
        type=_positive_float,
        default=os.environ.get("AGA_PREPARE_TIMEOUT_SECONDS", "15.0"),
    )
    parser.add_argument(
        "--max-concurrency",
        type=_positive_int,
        default=os.environ.get("AGA_MAX_CONCURRENCY", "8"),
    )
    parser.add_argument(
        "--max-reviews",
        type=_positive_int,
        default=os.environ.get("AGA_MAX_REVIEWS", "128"),
    )
    parser.add_argument(
        "--max-review-bytes",
        type=_positive_int,
        default=os.environ.get("AGA_MAX_REVIEW_BYTES", "16777216"),
    )
    parser.add_argument(
        "--max-store-bytes",
        type=_positive_int,
        default=os.environ.get("AGA_MAX_STORE_BYTES", "67108864"),
    )
    parser.add_argument(
        "--review-ttl",
        type=_positive_float,
        default=os.environ.get("AGA_REVIEW_TTL_SECONDS", "900.0"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.prepare_timeout > args.request_timeout:
        parser.error("--prepare-timeout must not exceed --request-timeout")
    repositories: dict[str, Any] = {}
    environment_root = os.environ.get("AGA_REPOSITORY_ROOT")
    if environment_root:
        try:
            environment_id, resolved_root = _repository(
                f"{os.environ.get('AGA_REPOSITORY_ID', 'architecture')}={environment_root}"
            )
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        environment_config: dict[str, Any] = {
            "repository": resolved_root,
            "manifest_path": os.environ.get("AGA_ARCHITECTURE_MANIFEST", "dochub.yaml"),
            "dependency_mode": os.environ.get("AGA_DEPENDENCY_MODE", "verified"),
        }
        raw_dependencies = os.environ.get("AGA_TRUSTED_DEPENDENCIES_JSON")
        if raw_dependencies:
            try:
                dependencies = json.loads(raw_dependencies)
            except json.JSONDecodeError as exc:
                parser.error(f"AGA_TRUSTED_DEPENDENCIES_JSON is invalid JSON: {exc.msg}")
            if not isinstance(dependencies, dict):
                parser.error("AGA_TRUSTED_DEPENDENCIES_JSON must be an object")
            environment_config["trusted_dependencies"] = dependencies
        repositories[environment_id] = environment_config
    for repository_id, root in args.repository:
        # An explicit CLI registry entry intentionally overrides the matching
        # environment entry.
        repositories[repository_id] = root
    for repository_id, root in args.synthetic_fixture_repository:
        if repository_id in repositories:
            parser.error(f"duplicate repository registry ID: {repository_id}")
        repositories[repository_id] = {
            "repository": root,
            "manifest_path": "dochub.yaml",
            "dependency_mode": "fixture",
        }

    bearer = os.environ.get(args.bearer_token_env) or None
    digest_secret = os.environ.get(args.digest_secret_env) or None
    try:
        config = MCPServerConfig(
            host=args.host,
            port=args.port,
            endpoint=args.endpoint,
            mode=args.mode,
            bearer_token=bearer,
            tls_terminated=args.tls_terminated,
            max_request_bytes=args.max_request_bytes,
            max_response_bytes=args.max_response_bytes,
            request_timeout_seconds=args.request_timeout,
            max_concurrency=args.max_concurrency,
        )
        service = ReviewService(
            repositories=repositories,
            ttl_seconds=args.review_ttl,
            max_reviews=args.max_reviews,
            prepare_timeout_seconds=args.prepare_timeout,
            max_prepare_workers=args.max_concurrency,
            max_review_bytes=args.max_review_bytes,
            max_store_bytes=args.max_store_bytes,
            digest_secret=digest_secret,
        )
        server = MCPServer(service, config=config)
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))

    stopping = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stopping.set()

    previous_handlers: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, request_stop)

    try:
        server.start()
        # Machine-readable startup line contains no token, repository path or
        # request material and is safe for a local process supervisor.
        print(
            json.dumps(
                {
                    "status": "ready",
                    "service": "aga-governance-mcp",
                    "url": server.url,
                    "mode": config.mode,
                    "auth": (
                        "bearer"
                        if config.mode == "bearer" or bearer
                        else "trusted-internal-network"
                        if config.mode == "internal-network"
                        else "loopback-only"
                    ),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        while not stopping.wait(0.5):
            pass
    finally:
        server.shutdown()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
