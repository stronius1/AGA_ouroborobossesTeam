# -*- coding: utf-8 -*-
"""Sealed correlation and tool-flow tests for the remediation adapter."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence

import pytest


PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from tools.ouroboros_backend import (  # noqa: E402
    EXPECTED_TOOLS,
    REMEDIATION_MCP_TOOLS,
    OuroborosBackendConfig,
    OuroborosContractError,
    _BackendTask,
)
from tools.ouroboros_remediation_backend import (  # noqa: E402
    REMEDIATION_STAGE,
    REMEDIATION_TASK_NAME,
    OuroborosRemediationBackend,
)


BASE = "a" * 40
HEAD = "b" * 40
REVIEW_DIGEST = "rvw_" + "c" * 64
TASK_DIGEST = "tsk_" + "d" * 64
FINDING_SHA256 = "e" * 64
REMEDIATION_DIGEST = "rmd_" + "f" * 64
CANDIDATE_SHA256 = "1" * 64
DIFF_SHA256 = "2" * 64
TASK_ID = "task-remediation-1"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _payload() -> dict[str, str]:
    return {
        "repository_id": "ga-case",
        "base": BASE,
        "head": HEAD,
        "review_id": "review-1",
        "review_digest": REVIEW_DIGEST,
        "task_digest": TASK_DIGEST,
        "remediation_id": "remediation-1",
        "finding_sha256": FINDING_SHA256,
        "data_classification": "synthetic-public",
        "idempotency_key": "remediation-1",
    }


def _backend(
    workspace: Path,
    receipts: Sequence[dict[str, Any]] = (),
) -> OuroborosRemediationBackend:
    prompt = "\n".join(
        (
            "{{REPOSITORY_ID}}",
            "{{BASE_REVISION}}",
            "{{HEAD_REVISION}}",
            "{{REVIEW_ID}}",
            "{{REVIEW_DIGEST}}",
            "{{TASK_DIGEST}}",
            "{{REMEDIATION_ID}}",
            "{{FINDING_SHA256}}",
            "{{DATA_CLASSIFICATION}}",
        )
    )
    return OuroborosRemediationBackend(
        OuroborosBackendConfig(
            model_id="deepseek/deepseek-v4-pro",
            workspaces={"ga-case": workspace},
            prompt_template=prompt,
            receipt_source=lambda: receipts,
        )
    )


def _record(backend: OuroborosRemediationBackend) -> _BackendTask:
    request = backend._normalise_request(REMEDIATION_TASK_NAME, _payload())
    return _BackendTask(
        task_id=TASK_ID,
        request=request,
        fingerprint="3" * 64,
        project_id=backend._project_id(request),
        prompt_sha256="4" * 64,
        created_at=0.0,
    )


def _prepare_args() -> dict[str, str]:
    payload = _payload()
    return {
        key: payload[key]
        for key in (
            "repository_id",
            "base",
            "head",
            "review_id",
            "review_digest",
            "task_digest",
            "remediation_id",
            "finding_sha256",
        )
    }


def _finalize_args() -> dict[str, Any]:
    return {
        "remediation_id": "remediation-1",
        "remediation_digest": REMEDIATION_DIGEST,
        "candidate": {
            "kind": "replace_eliminated_target",
            "candidate_sha256": CANDIDATE_SHA256,
        },
    }


def _tool_entries() -> list[dict[str, Any]]:
    return [
        {
            "tool": "mcp_aga__aga_prepare_remediation",
            "task_id": TASK_ID,
            "tool_call_id": "call-prepare",
            "args": _prepare_args(),
            "status": "ok",
            "is_error": False,
        },
        {
            "tool": "mcp_aga__aga_finalize_remediation",
            "task_id": TASK_ID,
            "tool_call_id": "call-finalize",
            "args": _finalize_args(),
            "status": "ok",
            "is_error": False,
        },
    ]


def _receipts() -> list[dict[str, Any]]:
    identifier_hash = hashlib.sha256(b"remediation-1").hexdigest()
    return [
        {
            "tool": "aga_prepare_remediation",
            "remediation_id_sha256": identifier_hash,
            "args_sha256": hashlib.sha256(_canonical(_prepare_args())).hexdigest(),
            "status": "ok",
            "output_status": "ready",
            "output_incomplete": False,
            "output_sha256": "5" * 64,
            "remediation_digest": REMEDIATION_DIGEST,
            "candidate_sha256": CANDIDATE_SHA256,
        },
        {
            "tool": "aga_finalize_remediation",
            "remediation_id_sha256": identifier_hash,
            "args_sha256": hashlib.sha256(_canonical(_finalize_args())).hexdigest(),
            "status": "ok",
            "output_status": "completed",
            "output_incomplete": False,
            "output_sha256": "6" * 64,
            "remediation_digest": REMEDIATION_DIGEST,
            "candidate_sha256": CANDIDATE_SHA256,
            "diff_sha256": DIFF_SHA256,
        },
    ]


def test_request_and_worker_metadata_are_exactly_remediation_scoped(
    tmp_path: Path,
) -> None:
    backend = _backend(tmp_path)
    request = backend._normalise_request(REMEDIATION_TASK_NAME, _payload())
    metadata = backend._managed_task_metadata(request, "4" * 64)

    assert request == _payload()
    assert metadata["aga_mcp_stage"] == REMEDIATION_STAGE
    assert metadata["aga_expected_mcp_tools"] == list(REMEDIATION_MCP_TOOLS)
    assert all(
        f"mcp_aga__{tool}" in metadata["disabled_tools"]
        for tool in EXPECTED_TOOLS
    )
    assert not any(
        f"mcp_aga__{tool}" in metadata["disabled_tools"]
        for tool in REMEDIATION_MCP_TOOLS
    )
    with pytest.raises(OuroborosContractError, match="whole AGA remediation"):
        backend._normalise_request("aga:review", _payload())
    mismatched = {**_payload(), "idempotency_key": "different"}
    with pytest.raises(OuroborosContractError, match="must equal remediation_id"):
        backend._normalise_request(REMEDIATION_TASK_NAME, mismatched)


def test_tool_flow_accepts_only_prepare_then_finalize_in_the_root_task(
    tmp_path: Path,
) -> None:
    backend = _backend(tmp_path)
    record = _record(backend)

    names, prepare, finalizes = backend._tool_flow(record, _tool_entries())

    assert names == list(REMEDIATION_MCP_TOOLS)
    assert prepare == _prepare_args()
    assert finalizes == [_finalize_args()]


@pytest.mark.parametrize("mutation", ["order", "review_tool", "child", "args", "error"])
def test_tool_flow_fails_closed_on_scope_or_correlation_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    backend = _backend(tmp_path)
    record = _record(backend)
    entries = deepcopy(_tool_entries())
    if mutation == "order":
        entries.reverse()
    elif mutation == "review_tool":
        entries.insert(
            1,
            {
                "tool": "mcp_aga__aga_prepare_review",
                "task_id": TASK_ID,
                "tool_call_id": "call-review",
                "args": {},
                "status": "ok",
                "is_error": False,
            },
        )
    elif mutation == "child":
        entries[1]["task_id"] = "child-task"
    elif mutation == "args":
        entries[0]["args"]["finding_sha256"] = "9" * 64
    elif mutation == "error":
        entries[1]["is_error"] = True

    with pytest.raises(OuroborosContractError):
        backend._tool_flow(record, entries)


def test_receipts_are_ordered_and_hash_bound(tmp_path: Path) -> None:
    receipts = _receipts()
    backend = _backend(tmp_path, receipts)
    record = _record(backend)

    prepare, finalize = backend._aga_receipts(record, [_finalize_args()])

    assert prepare["candidate_sha256"] == CANDIDATE_SHA256
    assert finalize["diff_sha256"] == DIFF_SHA256


@pytest.mark.parametrize("mutation", ["order", "prepare_hash", "retry_conflict"])
def test_receipts_fail_closed_on_tamper_or_ambiguous_retry(
    tmp_path: Path,
    mutation: str,
) -> None:
    receipts = deepcopy(_receipts())
    if mutation == "order":
        receipts.reverse()
    elif mutation == "prepare_hash":
        receipts[0]["args_sha256"] = "9" * 64
    elif mutation == "retry_conflict":
        retry = deepcopy(receipts[1])
        retry["diff_sha256"] = "9" * 64
        receipts.append(retry)
    backend = _backend(tmp_path, receipts)

    with pytest.raises(OuroborosContractError):
        backend._aga_receipts(_record(backend), [_finalize_args()])
