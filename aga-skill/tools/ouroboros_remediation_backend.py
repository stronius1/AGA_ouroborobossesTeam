# -*- coding: utf-8 -*-
"""Fail-closed Ouroboros v6.64.1 backend for one remediation stage.

The scheduling, immutable ledger reconciliation, terminal-axis validation and
provider cost accounting are inherited from the reviewed Ouroboros adapter.
This subclass seals a different worker tool envelope and validates the exact
two-call remediation MCP protocol and trusted in-process receipts.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

from tools.a2a import TaskResult, TaskStatus
from tools.mcp_server import SchemaViolation, validate_json_schema
from tools.ouroboros_backend import (
    DISABLED_WORKSPACE_TOOLS,
    EXPECTED_TOOLS,
    ID_RE,
    MANAGED_TASK_SCHEMA,
    MCP_TOOL_ERROR_MARKER,
    OuroborosBackendConfig,
    OuroborosContractError,
    OuroborosMCPServiceError,
    OuroborosMCPTransportError,
    OuroborosNotConfiguredError,
    OuroborosTaskBackend,
    REMEDIATION_MCP_TOOLS,
    REVISION_RE,
    SHA256_RE,
    TASK_ID_RE,
    _BackendTask,
    _canonical_bytes,
    _strict_final_json,
    _strict_json,
)
from tools.remediation_service import TOOL_DEFINITIONS_REMEDIATION


REMEDIATION_STAGE = "remediation"
REMEDIATION_TASK_NAME = "aga:remediate"
DIGEST_RE = re.compile(r"^(?:rvw|tsk)_[0-9a-f]{64}$")
REMEDIATION_DIGEST_RE = re.compile(r"^rmd_[0-9a-f]{64}$")


def _definition(name: str) -> Mapping[str, Any]:
    return next(item for item in TOOL_DEFINITIONS_REMEDIATION if item["name"] == name)


class OuroborosRemediationBackend(OuroborosTaskBackend):
    """Typed whole-remediation task backend with a two-tool sealed envelope."""

    def __init__(self, config: OuroborosBackendConfig, **kwargs: Any) -> None:
        super().__init__(config, **kwargs)
        # The review tools are present at gateway discovery but inaccessible to
        # this worker. Dynamic discovery/promotion and every native capability
        # remain disabled by the shared fail-closed policy.
        self._disabled_tools = DISABLED_WORKSPACE_TOOLS + tuple(
            f"mcp_{config.server_id}__{name}" for name in EXPECTED_TOOLS
        )

    def _logical_task_name(self) -> str:
        return REMEDIATION_TASK_NAME

    def _normalise_request(
        self, task_name: str, payload: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        if task_name != REMEDIATION_TASK_NAME:
            raise OuroborosContractError("only the whole AGA remediation task is supported")
        if not isinstance(payload, Mapping):
            raise OuroborosContractError("remediation payload must be an object")
        allowed = {
            "repository_id",
            "base",
            "head",
            "review_id",
            "review_digest",
            "task_digest",
            "remediation_id",
            "finding_sha256",
            "data_classification",
            "idempotency_key",
        }
        extra = sorted(set(payload) - allowed)
        if extra:
            raise OuroborosContractError(
                f"remediation payload has unknown fields: {', '.join(extra)}"
            )
        repository_id = payload.get("repository_id")
        if not isinstance(repository_id, str) or ID_RE.fullmatch(repository_id) is None:
            raise OuroborosContractError("repository_id is invalid")
        if repository_id not in self._workspaces:
            raise OuroborosNotConfiguredError("repository_id is not registered")
        identifiers: dict[str, str] = {}
        for field in ("review_id", "remediation_id"):
            value = payload.get(field)
            if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
                raise OuroborosContractError(f"{field} is invalid")
            identifiers[field] = value
        revisions: dict[str, str] = {}
        for field in ("base", "head"):
            value = payload.get(field)
            if not isinstance(value, str) or REVISION_RE.fullmatch(value) is None:
                raise OuroborosContractError(f"{field} must be a full Git SHA")
            revisions[field] = value.lower()
        digests: dict[str, str] = {}
        for field, prefix in (("review_digest", "rvw_"), ("task_digest", "tsk_")):
            value = payload.get(field)
            if (
                not isinstance(value, str)
                or DIGEST_RE.fullmatch(value) is None
                or not value.startswith(prefix)
            ):
                raise OuroborosContractError(f"{field} is invalid")
            digests[field] = value
        finding = payload.get("finding_sha256")
        if not isinstance(finding, str) or SHA256_RE.fullmatch(finding) is None:
            raise OuroborosContractError("finding_sha256 is invalid")
        if payload.get("data_classification") != "synthetic-public":
            raise OuroborosContractError(
                "only synthetic-public data is permitted for this backend"
            )
        idempotency = payload.get("idempotency_key", identifiers["remediation_id"])
        if (
            not isinstance(idempotency, str)
            or ID_RE.fullmatch(idempotency) is None
            or idempotency != identifiers["remediation_id"]
        ):
            raise OuroborosContractError(
                "idempotency_key must equal remediation_id"
            )
        return {
            "repository_id": repository_id,
            **revisions,
            **identifiers,
            **digests,
            "finding_sha256": finding,
            "data_classification": "synthetic-public",
            "idempotency_key": idempotency,
        }

    def _prompt(self, request: Mapping[str, Any]) -> str:
        replacements = {
            "{{REPOSITORY_ID}}": request["repository_id"],
            "{{BASE_REVISION}}": request["base"],
            "{{HEAD_REVISION}}": request["head"],
            "{{REVIEW_ID}}": request["review_id"],
            "{{REVIEW_DIGEST}}": request["review_digest"],
            "{{TASK_DIGEST}}": request["task_digest"],
            "{{REMEDIATION_ID}}": request["remediation_id"],
            "{{FINDING_SHA256}}": request["finding_sha256"],
            "{{DATA_CLASSIFICATION}}": request["data_classification"],
        }
        prompt = self._prompt_template
        for marker, value in replacements.items():
            if prompt.count(marker) != 1:
                raise OuroborosContractError(
                    "remediation prompt marker contract mismatch"
                )
            prompt = prompt.replace(marker, str(value))
        if "{{" in prompt or "}}" in prompt:
            raise OuroborosContractError("remediation prompt has unresolved markers")
        return prompt

    @staticmethod
    def _project_id(request: Mapping[str, Any]) -> str:
        return "aga-" + hashlib.sha256(_canonical_bytes(request)).hexdigest()[:32]

    def _managed_task_metadata(
        self, request: Mapping[str, Any], prompt_sha256: str
    ) -> dict[str, Any]:
        return {
            "aga_review_id": request["review_id"],
            "aga_review_digest": request["review_digest"],
            "aga_task_digest": request["task_digest"],
            "aga_remediation_id": request["remediation_id"],
            "aga_finding_sha256": request["finding_sha256"],
            "aga_idempotency_key": request["idempotency_key"],
            "aga_prompt_sha256": prompt_sha256,
            "aga_runtime_contract": MANAGED_TASK_SCHEMA,
            "aga_mcp_stage": REMEDIATION_STAGE,
            "aga_expected_mcp_tools": list(REMEDIATION_MCP_TOOLS),
            "data_classification": "synthetic-public",
            "expected_model_id": self.config.model_id,
            "allowed_resources": {"network": True, "web": False},
            "disabled_tools": list(self._disabled_tools),
        }

    def _canonical_tool(self, value: Any) -> str | None:
        text = str(value or "")
        for tool in REMEDIATION_MCP_TOOLS:
            if text == tool or text == f"mcp_{self.config.server_id}__{tool}":
                return tool
        return None

    def _tool_flow(
        self, record: _BackendTask, entries: Any
    ) -> tuple[list[str], Mapping[str, Any], list[Mapping[str, Any]]]:
        if not isinstance(entries, list) or len(entries) > 2000:
            raise OuroborosContractError("tool log entries are invalid or oversized")
        selected: list[tuple[int, str, Mapping[str, Any]]] = []
        seen: dict[tuple[str, str], Mapping[str, Any]] = {}
        for index, raw in enumerate(entries):
            if not isinstance(raw, Mapping):
                continue
            tool = self._canonical_tool(raw.get("tool"))
            if raw.get("tool") is not None and tool is None:
                raise OuroborosContractError("non-remediation tool invocation was recorded")
            if tool is None:
                continue
            preview = raw.get("result_preview")
            if isinstance(preview, str) and (
                preview.startswith("⚠️ MCP_TOOL_ERROR:")
                or MCP_TOOL_ERROR_MARKER in preview
            ):
                if "remediation_service_error" in preview:
                    raise OuroborosMCPServiceError(
                        f"{tool} returned an AGA remediation service error"
                    )
                raise OuroborosMCPTransportError(
                    f"{tool} returned an MCP transport error"
                )
            task_id = raw.get("task_id")
            call_id = raw.get("tool_call_id")
            if (
                not isinstance(task_id, str)
                or TASK_ID_RE.fullmatch(task_id) is None
                or not isinstance(call_id, str)
                or not call_id
                or len(call_id) > 256
            ):
                raise OuroborosContractError("tool log correlation identifiers are missing")
            projection = {
                key: value
                for key, value in raw.items()
                if key not in {"_source_root", "_line"}
            }
            identity = (task_id, call_id)
            if identity in seen:
                if seen[identity] != projection:
                    raise OuroborosContractError("mirrored tool log entries conflict")
                continue
            seen[identity] = projection
            selected.append((index, tool, raw))
        if [tool for _index, tool, _raw in selected] != list(REMEDIATION_MCP_TOOLS):
            raise OuroborosContractError(
                "tool flow must be exactly prepare-remediation then finalize-remediation"
            )
        if any(raw.get("task_id") != record.task_id for _index, _tool, raw in selected):
            raise OuroborosContractError("remediation tools must run in the root task")
        if any(
            raw.get("is_error") is not False
            or str(raw.get("status") or "").lower() != "ok"
            for _index, _tool, raw in selected
        ):
            raise OuroborosContractError("remediation tool receipt reports failure")
        prepare_args = selected[0][2].get("args")
        finalize_args = selected[1][2].get("args")
        if not isinstance(prepare_args, Mapping) or not isinstance(finalize_args, Mapping):
            raise OuroborosContractError("remediation tool arguments are missing")
        expected_prepare = {
            key: record.request[key]
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
        if any(prepare_args.get(key) != value for key, value in expected_prepare.items()):
            raise OuroborosContractError("prepare-remediation arguments do not match")
        if finalize_args.get("remediation_id") != record.request["remediation_id"]:
            raise OuroborosContractError("finalize-remediation id does not match")
        digest = finalize_args.get("remediation_digest")
        if not isinstance(digest, str) or REMEDIATION_DIGEST_RE.fullmatch(digest) is None:
            raise OuroborosContractError("finalize-remediation digest is missing")
        return list(REMEDIATION_MCP_TOOLS), prepare_args, [dict(finalize_args)]

    def _aga_receipts(
        self,
        record: _BackendTask,
        finalize_args: Sequence[Mapping[str, Any]],
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        source = self.config.receipt_source
        if source is None:
            raise OuroborosContractError("trusted AGA receipt source is not configured")
        try:
            receipts = source()
        except Exception as exc:
            raise OuroborosContractError("trusted AGA receipt source is unavailable") from exc
        if not isinstance(receipts, Sequence) or len(receipts) > 10_000:
            raise OuroborosContractError("trusted AGA receipts are invalid or oversized")
        identifier_hash = hashlib.sha256(
            record.request["remediation_id"].encode("utf-8")
        ).hexdigest()
        matching = [
            item
            for item in receipts
            if isinstance(item, Mapping)
            and item.get("remediation_id_sha256") == identifier_hash
        ]
        prepares = [
            (index, item)
            for index, item in enumerate(matching)
            if item.get("tool") == "aga_prepare_remediation"
        ]
        finalizes = [
            (index, item)
            for index, item in enumerate(matching)
            if item.get("tool") == "aga_finalize_remediation"
        ]
        if len(finalize_args) != 1 or len(prepares) != 1 or len(finalizes) not in {1, 2}:
            raise OuroborosContractError("trusted remediation receipts are missing")
        prepare_index, prepare = prepares[0]
        finalize_index, finalize = finalizes[0]
        if prepare_index >= finalize_index:
            raise OuroborosContractError("trusted remediation receipts are unordered")
        fields = (
            "args_sha256",
            "status",
            "output_status",
            "output_incomplete",
            "output_sha256",
            "remediation_digest",
            "candidate_sha256",
            "diff_sha256",
        )
        projection = {key: finalize.get(key) for key in fields}
        if any(
            {key: item.get(key) for key in fields} != projection
            for _index, item in finalizes[1:]
        ):
            raise OuroborosContractError("trusted finalize-remediation retry conflicts")
        expected_prepare = {
            key: record.request[key]
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
        if prepare.get("args_sha256") != hashlib.sha256(
            _canonical_bytes(expected_prepare)
        ).hexdigest():
            raise OuroborosContractError("trusted prepare-remediation arguments mismatch")
        if (
            prepare.get("status") != "ok"
            or prepare.get("output_status") != "ready"
            or prepare.get("output_incomplete") is not False
        ):
            raise OuroborosContractError("trusted prepare-remediation was incomplete")
        final_args = finalize_args[0]
        if (
            finalize.get("args_sha256")
            != hashlib.sha256(_canonical_bytes(dict(final_args))).hexdigest()
            or prepare.get("candidate_sha256")
            != finalize.get("candidate_sha256")
            or finalize.get("status") != "ok"
            or finalize.get("output_status") != "completed"
            or finalize.get("output_incomplete") is not False
            or finalize.get("remediation_digest")
            != final_args.get("remediation_digest")
            or prepare.get("remediation_digest")
            != final_args.get("remediation_digest")
            or not isinstance(finalize.get("output_sha256"), str)
            or SHA256_RE.fullmatch(str(finalize.get("output_sha256"))) is None
            or not isinstance(finalize.get("candidate_sha256"), str)
            or SHA256_RE.fullmatch(str(finalize.get("candidate_sha256"))) is None
            or not isinstance(finalize.get("diff_sha256"), str)
            or SHA256_RE.fullmatch(str(finalize.get("diff_sha256"))) is None
        ):
            raise OuroborosContractError("trusted finalize-remediation receipt is invalid")
        return prepare, finalize

    def _validate_final(
        self,
        record: _BackendTask,
        external: Mapping[str, Any],
        tool_names: list[str],
        prepare_receipt: Mapping[str, Any],
        finalize_receipt: Mapping[str, Any],
    ) -> TaskResult:
        raw_final = external.get("result")
        if not isinstance(raw_final, str):
            raise OuroborosContractError("task result has no final remediation JSON")
        if len(raw_final.encode("utf-8")) > self.config.max_json_bytes:
            raise OuroborosContractError("final remediation JSON exceeded its bound")
        parsed, envelope = _strict_final_json(raw_final)
        if not isinstance(parsed, Mapping):
            raise OuroborosContractError("final remediation answer must be an object")
        final = dict(parsed)
        final_hash = hashlib.sha256(_canonical_bytes(final)).hexdigest()
        projection_repair = "none"
        if final_hash != finalize_receipt.get("output_sha256") and "analysis_errors" not in final:
            candidate = {**final, "analysis_errors": []}
            candidate_hash = hashlib.sha256(_canonical_bytes(candidate)).hexdigest()
            if candidate_hash == finalize_receipt.get("output_sha256"):
                final = candidate
                final_hash = candidate_hash
                projection_repair = "attested_empty_analysis_errors"
        if final_hash != finalize_receipt.get("output_sha256"):
            raise OuroborosContractError(
                "task answer is not the exact AGA remediation finalize output"
            )
        try:
            validate_json_schema(
                final,
                _definition("aga_finalize_remediation")["outputSchema"],
                "$final",
            )
        except SchemaViolation as exc:
            raise OuroborosContractError(
                f"final remediation failed schema at {exc.path}"
            ) from exc
        expected = {
            key: record.request[key]
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
        if any(final.get(key) != value for key, value in expected.items()):
            raise OuroborosContractError("final remediation correlation mismatch")
        patch = final.get("patch")
        if (
            final.get("status") != "completed"
            or final.get("outcome") != "candidate_ready"
            or final.get("incomplete") is not False
            or final.get("human_review_required") is not True
            or final.get("auto_merge") is not False
            or not isinstance(patch, Mapping)
            or final.get("candidate_sha256") != finalize_receipt.get("candidate_sha256")
            or patch.get("diff_sha256") != finalize_receipt.get("diff_sha256")
            or final.get("remediation_digest")
            != finalize_receipt.get("remediation_digest")
        ):
            raise OuroborosContractError("final remediation candidate is not trusted")
        return TaskResult(
            task_id=record.task_id,
            task_name=REMEDIATION_TASK_NAME,
            status=TaskStatus.SUCCEEDED,
            metadata={
                "external_status": "completed",
                "review_id": final["review_id"],
                "review_digest": final["review_digest"],
                "task_digest": final["task_digest"],
                "remediation_id": final["remediation_id"],
                "remediation_digest": final["remediation_digest"],
                "finding_sha256": final["finding_sha256"],
                "candidate_sha256": final["candidate_sha256"],
                "diff_sha256": patch["diff_sha256"],
                "human_review_required": True,
                "auto_merge": False,
                "runtime": {"name": "ouroboros", "version": self.config.runtime_version},
                "provider": "openrouter",
                "model": {"name": self.config.model_id},
                "prompt_sha256": record.prompt_sha256,
                "tool_names": tool_names,
                "prepare_output_sha256": prepare_receipt.get("output_sha256"),
                "final_output_sha256": final_hash,
                "final_answer_envelope": envelope,
                "final_projection_repair": projection_repair,
                "aga_final": final,
            },
        )

    def _failure(
        self,
        record: _BackendTask,
        code: str,
        message: str,
        *,
        external_status: str = "",
    ) -> TaskResult:
        del message
        result = TaskResult(
            task_id=record.task_id,
            task_name=REMEDIATION_TASK_NAME,
            status=TaskStatus.FAILED,
            error=f"{code}: remediation did not produce a trusted candidate",
            metadata={
                "error_code": code,
                "external_status": external_status,
                "review_id": record.request["review_id"],
                "remediation_id": record.request["remediation_id"],
                "incomplete": True,
                "human_review_required": True,
                "auto_merge": False,
                "runtime": {"name": "ouroboros", "version": self.config.runtime_version},
                "expected_route": {
                    "provider": "openrouter",
                    "model": self.config.model_id,
                },
            },
        )
        with self._lock:
            record.frozen_result = result
        return result


__all__ = [
    "OuroborosRemediationBackend",
    "REMEDIATION_STAGE",
    "REMEDIATION_TASK_NAME",
]
