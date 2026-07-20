#!/usr/bin/env python3
"""Run local Architecture-as-Code self-evolution through real Ouroboros tasks.

The default demo builds a persistent synthetic-public Git repository with an
immutable base/head pair.  The same command can bind an existing clean local
repository.  Review, remediation and re-review are paid OpenRouter tasks;
materialization is host-only in an isolated candidate worktree.  No remote,
push, approve, merge or protected-branch write exists in this workflow.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGA_SKILL_ROOT = REPOSITORY_ROOT / "aga-skill"
for _root in (REPOSITORY_ROOT, AGA_SKILL_ROOT):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from scripts import ouroboros_preflight as preflight  # noqa: E402
from scripts import run_ouroboros_e2e as e2e  # noqa: E402
from scripts.openrouter_budget import BudgetError, read_budget  # noqa: E402
from scripts.private_receipt_journal import (  # noqa: E402
    PrivateReceiptJournal,
    ReceiptJournalError,
)
from scripts.run_ouroboros_live_review import (  # noqa: E402
    LiveReviewError,
    bind_repository,
    run_live_review,
)
from tools.a2a import TaskStatus  # noqa: E402
from tools.mcp_server import MCPServer, MCPServerConfig  # noqa: E402
from tools.ouroboros_backend import (  # noqa: E402
    OuroborosBackendConfig,
    OuroborosBackendError,
    OuroborosIdempotencyConflict,
)
from tools.ouroboros_remediation_backend import (  # noqa: E402
    OuroborosRemediationBackend,
)
from tools.remediation_service import (  # noqa: E402
    RemediationService,
    canonical_sha256,
    finding_sha256,
)
from tools.repository_snapshot import (  # noqa: E402
    DEFAULT_ARCHTOOL_COMMIT,
    DEFAULT_ARCHTOOL_PATH,
    DEFAULT_SEAF_CORE_COMMIT,
    DEFAULT_SEAF_CORE_PATH,
)
from tools.review_service import ReviewService  # noqa: E402


SCHEMA = "aga.architecture-self-evolution/v1"
CLI_SCHEMA = "aga.architecture-self-evolution-cli/v1"
STATE_SCHEMA = "aga.architecture-self-evolution-state/v1"
PHASE_SCHEMA = "aga.architecture-self-evolution-phases/v1"
FAILURE_SCHEMA = "aga.architecture-self-evolution-failures/v1"
DEMO_SCHEMA = "aga.architecture-self-evolution-demo/v1"
DEFAULT_CORRELATION = "architecture-self-evolution-v2"
DEFAULT_STATE_ROOT = REPOSITORY_ROOT / ".aga-runs" / "architecture"
DEFAULT_EVIDENCE_OUT = (
    REPOSITORY_ROOT
    / "docs"
    / "evidence"
    / "ouroboros-self-evolution-v1.json"
)
REMEDIATION_PROMPT = (
    AGA_SKILL_ROOT / "prompts" / "ouroboros-remediation-v1.0.0.txt"
)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_GIT_OUTPUT = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 3 * 1024 * 1024
MAX_IMPLEMENTATION_SPEND_USD = 40.0
MINIMUM_BATCH_REMAINING_USD = 0.50


class ArchitectureEvolutionError(RuntimeError):
    """Typed, secret/path-free workflow error."""

    def __init__(self, code: str, *, status: str = "failed") -> None:
        if status not in {
            "failed",
            "not_configured",
            "incomplete",
            "budget_exhausted",
        }:
            raise ValueError("invalid architecture evolution status")
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class Scenario:
    repository: Path
    repository_id: str
    base: str
    head: str
    source_branch: str
    source_head: str
    source_status: str
    demo: bool


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _safe_environment(*, commit: bool = False) -> dict[str, str]:
    allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
        }
    )
    if commit:
        environment.update(
            {
                "GIT_AUTHOR_NAME": "AGA Local Candidate",
                "GIT_AUTHOR_EMAIL": "aga-local@example.invalid",
                "GIT_COMMITTER_NAME": "AGA Local Candidate",
                "GIT_COMMITTER_EMAIL": "aga-local@example.invalid",
            }
        )
    return environment


def _git(
    repository: Path,
    *arguments: str,
    input_bytes: bytes | None = None,
    commit: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            (
                "git",
                "-C",
                str(repository),
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "commit.gpgSign=false",
                *arguments,
            ),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30.0,
            check=False,
            env=_safe_environment(commit=commit),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ArchitectureEvolutionError("git_command_failed") from exc
    if (
        len(completed.stdout) > MAX_GIT_OUTPUT
        or len(completed.stderr) > MAX_GIT_OUTPUT
    ):
        raise ArchitectureEvolutionError("git_output_too_large")
    if check and completed.returncode != 0:
        raise ArchitectureEvolutionError("git_command_failed")
    return completed


def _git_text(repository: Path, *arguments: str, commit: bool = False) -> str:
    try:
        return _git(repository, *arguments, commit=commit).stdout.decode(
            "utf-8", errors="strict"
        ).strip()
    except UnicodeError as exc:
        raise ArchitectureEvolutionError("git_output_invalid") from exc


def _atomic_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ArchitectureEvolutionError("state_path_unsafe")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary: Path | None = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                value,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        path.chmod(0o600)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


def _atomic_public_json(path: Path, value: Mapping[str, Any]) -> None:
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except OSError:
        path.parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = path.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(REPOSITORY_ROOT.resolve(strict=True))
    except ValueError as exc:
        raise ArchitectureEvolutionError("evidence_path_outside_project") from exc
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ArchitectureEvolutionError("evidence_path_unsafe")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=resolved_parent)
    temporary: Path | None = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


def _validated_evidence_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else REPOSITORY_ROOT / path
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(REPOSITORY_ROOT.resolve(strict=True))
    except ValueError as exc:
        raise ArchitectureEvolutionError("evidence_path_outside_project") from exc
    if resolved.is_symlink() or (resolved.exists() and not resolved.is_file()):
        raise ArchitectureEvolutionError("evidence_path_unsafe")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    try:
        resolved.parent.resolve(strict=True).relative_to(
            REPOSITORY_ROOT.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise ArchitectureEvolutionError("evidence_path_unsafe") from exc
    return resolved


def _copy_text(source: Path, target: Path) -> None:
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArchitectureEvolutionError("demo_source_unavailable") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_text(root: Path, relative: str, text: str) -> None:
    path = root.joinpath(*PurePosixPath(relative).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _demo_documents(repository: Path) -> None:
    architecture = REPOSITORY_ROOT / "architecture"
    for relative in (
        "metamodel/aga-extension.yaml",
        "overrides/seaf-core-v1.4.0/entities/ta/presentation/components.yaml",
        "overrides/seaf-core-v1.4.0/entities/ta/presentation/templates/list.md",
    ):
        _copy_text(architecture / relative, repository / relative)
    try:
        overlay = (architecture / "seaf-core-v1.4.0-overlay.yaml").read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as exc:
        raise ArchitectureEvolutionError("demo_source_unavailable") from exc
    _write_text(
        repository,
        "seaf-core-v1.4.0-overlay.yaml",
        overlay.replace("vendor/seaf-core/", "architecture/vendor/seaf-core/"),
    )
    _write_text(
        repository,
        "dochub.yaml",
        """$package:
  aga-self-evolution:
    name: AGA self-evolution acceptance
    vendor: AGA
    description: Controlled synthetic-public Architecture-as-Code review.
    version: 1.0.0

aga:
  schema: seaf-core/v1.4.0
  extensions:
    - aga.project/v1
  data_classification: synthetic-public

imports:
  - seaf-core-v1.4.0-overlay.yaml
  - metamodel/aga-extension.yaml
  - model/components.yaml
  - model/integrations.yaml
  - model/adrs.yaml
  - model/contexts.yaml
""",
    )
    _write_demo_models(repository)


def _write_demo_models(repository: Path) -> None:
    _write_text(
        repository,
        "model/components.yaml",
        """components:
  demo.checkout:
    title: Synthetic Checkout
    entity: component
    description: Controlled synthetic checkout component.
    owner: Synthetic Commerce Team
    criticality: mission_critical
    target_status: strategic

  demo.legacy_scoring:
    title: Synthetic Legacy Scoring
    entity: component
    description: Controlled scorer scheduled for retirement.
    owner: Synthetic Risk Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.scoring_v2

  demo.scoring_v2:
    title: Synthetic Scoring v2
    entity: component
    description: Approved strategic successor for the retiring scorer.
    owner: Synthetic Risk Team
    criticality: high
    target_status: strategic
""",
    )
    _write_text(repository, "model/integrations.yaml", "seaf.app.integrations: {}\n")
    _write_text(repository, "model/adrs.yaml", "seaf.change.adr: {}\n")
    _write_text(
        repository,
        "model/contexts.yaml",
        """contexts:
  demo.self_evolution:
    title: Controlled self-evolution landscape
    location: AGA/Self Evolution
    presentation: integration
    extra-links: false
    components:
      - demo.checkout
      - demo.legacy_scoring
      - demo.scoring_v2
""",
    )


def _ensure_gitlink_placeholders(repository: Path) -> None:
    # An uninitialised Git link with no directory is reported as a deleted
    # worktree entry. Empty directories are ignored by Git but preserve a clean
    # status; dependency bytes are read only from separately verified pinned
    # checkouts registered with RepositorySnapshotBuilder.
    for relative in (DEFAULT_ARCHTOOL_PATH, DEFAULT_SEAF_CORE_PATH):
        (repository / relative).mkdir(parents=True, exist_ok=True)


def _materialize_demo(run_root: Path, repository_id: str) -> Scenario:
    repository = run_root / "repository"
    metadata_path = run_root / "demo.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArchitectureEvolutionError("demo_state_invalid") from exc
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("schema") != DEMO_SCHEMA
            or metadata.get("repository_id") != repository_id
        ):
            raise ArchitectureEvolutionError("demo_state_conflict")
        _ensure_gitlink_placeholders(repository)
        binding = bind_repository(
            repository,
            repository_id,
            str(metadata.get("base")),
            str(metadata.get("head")),
        )
        return Scenario(
            repository=binding.repository,
            repository_id=repository_id,
            base=binding.base,
            head=binding.head,
            source_branch=_git_text(repository, "branch", "--show-current"),
            source_head=_git_text(repository, "rev-parse", "HEAD"),
            source_status=_git_text(repository, "status", "--porcelain=v1"),
            demo=True,
        )
    if repository.exists():
        raise ArchitectureEvolutionError("demo_state_conflict")
    repository.mkdir(mode=0o700, parents=True)
    _git(repository, "init", "--initial-branch=main", "--object-format=sha1")
    _git(repository, "config", "user.name", "AGA Local Candidate")
    _git(repository, "config", "user.email", "aga-local@example.invalid")
    _demo_documents(repository)
    _git(repository, "add", "--all")
    for dependency_path, commit_sha in (
        (DEFAULT_ARCHTOOL_PATH, DEFAULT_ARCHTOOL_COMMIT),
        (DEFAULT_SEAF_CORE_PATH, DEFAULT_SEAF_CORE_COMMIT),
    ):
        _git(
            repository,
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{commit_sha},{dependency_path}",
        )
    _git(
        repository,
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-m",
        "AGA controlled architecture base",
        commit=True,
    )
    base = _git_text(repository, "rev-parse", "HEAD")
    _write_text(
        repository,
        "model/integrations.yaml",
        """seaf.app.integrations:
  demo.checkout_to_legacy_scoring:
    title: Checkout to retiring scorer
    description: Checkout scoring invocation.
    from: demo.checkout
    to: demo.legacy_scoring
""",
    )
    _git(repository, "add", "model/integrations.yaml")
    _git(
        repository,
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-m",
        "Introduce controlled SEAF-004 flow",
        commit=True,
    )
    head = _git_text(repository, "rev-parse", "HEAD")
    _ensure_gitlink_placeholders(repository)
    binding = bind_repository(repository, repository_id, base, head)
    _atomic_private_json(
        metadata_path,
        {
            "schema": DEMO_SCHEMA,
            "repository_id": repository_id,
            "base": binding.base,
            "head": binding.head,
        },
    )
    return Scenario(
        repository=binding.repository,
        repository_id=repository_id,
        base=binding.base,
        head=binding.head,
        source_branch="main",
        source_head=binding.head,
        source_status="",
        demo=True,
    )


def _existing_scenario(
    repository: Path,
    repository_id: str,
    base: str,
    head: str,
) -> Scenario:
    binding = bind_repository(repository, repository_id, base, head)
    return Scenario(
        repository=binding.repository,
        repository_id=binding.repository_id,
        base=binding.base,
        head=binding.head,
        source_branch=_git_text(binding.repository, "branch", "--show-current"),
        source_head=_git_text(binding.repository, "rev-parse", "HEAD"),
        source_status=_git_text(
            binding.repository, "status", "--porcelain=v1", "--untracked-files=all"
        ),
        demo=False,
    )


def _budget_checkpoint(initial_usage: float | None) -> Mapping[str, Any]:
    try:
        checkpoint = dict(
            read_budget(minimum_remaining_usd=MINIMUM_BATCH_REMAINING_USD)
        )
    except BudgetError as exc:
        raise ArchitectureEvolutionError(exc.code, status=exc.status) from exc
    usage = float(checkpoint["usage_usd"])
    implementation_delta = 0.0 if initial_usage is None else max(0.0, usage - initial_usage)
    if implementation_delta >= MAX_IMPLEMENTATION_SPEND_USD:
        raise ArchitectureEvolutionError(
            "implementation_spend_stop_reached", status="budget_exhausted"
        )
    checkpoint["implementation_delta_usd"] = round(implementation_delta, 8)
    return checkpoint


def _transport_or_tool_failure(code: str) -> bool:
    return any(
        marker in code
        for marker in ("transport", "tool", "mcp", "provider", "worker_mcp")
    )


def _load_failure_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
        raise ArchitectureEvolutionError("failure_state_invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchitectureEvolutionError("failure_state_invalid") from exc
    counts = value.get("counts") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != FAILURE_SCHEMA
        or not isinstance(counts, Mapping)
        or any(
            not isinstance(key, str)
            or ID_RE.fullmatch(key) is None
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
            or count > 100
            for key, count in counts.items()
        )
    ):
        raise ArchitectureEvolutionError("failure_state_invalid")
    return {str(key): int(count) for key, count in counts.items()}


def _failure_guard(path: Path) -> None:
    repeated = sorted(
        code for code, count in _load_failure_counts(path).items() if count >= 2
    )
    if repeated:
        raise ArchitectureEvolutionError(
            "repeated_transport_tool_failure_stop", status="incomplete"
        )


def _record_failed_batch(
    *,
    path: Path,
    evidence_out: Path,
    code: str,
    stage: str,
    initial_usage: float,
    correlation_digest: str,
) -> None:
    counts = _load_failure_counts(path)
    if _transport_or_tool_failure(code):
        counts[code] = counts.get(code, 0) + 1
    try:
        after = _budget_checkpoint(initial_usage)
        delta: float | None = round(
            max(0.0, float(after["usage_usd"]) - initial_usage), 8
        )
        budget_status: Mapping[str, Any] = after
    except ArchitectureEvolutionError:
        delta = None
        budget_status = {
            "schema": "aga.openrouter-budget/v1",
            "status": "unavailable",
        }
    failure = {
        "schema": FAILURE_SCHEMA,
        "status": "failed",
        "correlation_sha256": correlation_digest,
        "stage": stage,
        "code": code,
        "counts": counts,
        "budget_after_failure": budget_status,
        "aggregate_usage_delta_usd": delta,
        "redaction": {
            "credentials_retained": False,
            "absolute_paths_retained": False,
            "raw_provider_payloads_retained": False,
        },
    }
    _atomic_private_json(path, failure)
    _atomic_public_json(evidence_out, failure)


def _trusted_dependencies() -> Mapping[str, Mapping[str, Any]]:
    return {
        DEFAULT_ARCHTOOL_PATH: {
            "checkout": REPOSITORY_ROOT / DEFAULT_ARCHTOOL_PATH,
            "commit": DEFAULT_ARCHTOOL_COMMIT,
        },
        DEFAULT_SEAF_CORE_PATH: {
            "checkout": REPOSITORY_ROOT / DEFAULT_SEAF_CORE_PATH,
            "commit": DEFAULT_SEAF_CORE_COMMIT,
        },
    }


def _review_receipt_output_hash(review: Mapping[str, Any]) -> str:
    receipts = review.get("receipts")
    finalize = receipts.get("finalize") if isinstance(receipts, Mapping) else None
    value = finalize.get("output_sha256") if isinstance(finalize, Mapping) else None
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ArchitectureEvolutionError("review_final_receipt_missing")
    final = review.get("final")
    if not isinstance(final, Mapping) or canonical_sha256(final) != value:
        raise ArchitectureEvolutionError("review_final_receipt_mismatch")
    return value


def _select_finding(review: Mapping[str, Any]) -> Mapping[str, Any]:
    final = review.get("final")
    findings = final.get("findings") if isinstance(final, Mapping) else None
    if not isinstance(findings, list):
        raise ArchitectureEvolutionError("trusted_findings_missing")
    candidates = [
        dict(item)
        for item in findings
        if isinstance(item, Mapping)
        and item.get("rule_id") == "SEAF-004"
        and item.get("severity") == "blocker"
        and item.get("origin") == "deterministic"
        and isinstance(item.get("canonical_defect"), str)
    ]
    if len(candidates) != 1:
        raise ArchitectureEvolutionError("supported_finding_not_unique")
    return candidates[0]


def _remediation_receipts(
    trace: Sequence[Mapping[str, Any]], remediation_id: str
) -> list[dict[str, Any]]:
    identifier_hash = _sha256(remediation_id)
    allowed = {"aga_prepare_remediation", "aga_finalize_remediation"}
    result: list[dict[str, Any]] = []
    for item in trace:
        if (
            not isinstance(item, Mapping)
            or item.get("remediation_id_sha256") != identifier_hash
            or item.get("tool") not in allowed
        ):
            continue
        projection: dict[str, Any] = {
            "tool": item["tool"],
            "args_sha256": item.get("args_sha256"),
            "output_sha256": item.get("output_sha256"),
            "status": item.get("status"),
            "output_status": item.get("output_status"),
            "output_incomplete": item.get("output_incomplete"),
        }
        for key in ("remediation_digest", "candidate_sha256", "diff_sha256"):
            value = item.get(key)
            if isinstance(value, str):
                projection[key] = value
        if any(
            not isinstance(projection.get(key), str)
            or SHA256_RE.fullmatch(str(projection[key])) is None
            for key in ("args_sha256", "output_sha256")
        ):
            raise ArchitectureEvolutionError("remediation_receipt_invalid")
        result.append(projection)
    names = [item["tool"] for item in result]
    if (
        not names
        or names[0] != "aga_prepare_remediation"
        or names.count("aga_prepare_remediation") != 1
        or names.count("aga_finalize_remediation") not in {1, 2}
        or any(name not in allowed for name in names)
    ):
        raise ArchitectureEvolutionError("remediation_receipt_order_invalid")
    return result


def _run_remediation_task(
    *,
    scenario: Scenario,
    review: Mapping[str, Any],
    finding: Mapping[str, Any],
    remediation_id: str,
    timeout_seconds: float,
    receipt_journal_path: Path,
) -> Mapping[str, Any]:
    final_review = review.get("final")
    if not isinstance(final_review, Mapping):
        raise ArchitectureEvolutionError("trusted_final_missing")
    repository_config = {
        scenario.repository_id: {
            "repository": scenario.repository,
            "manifest_path": "dochub.yaml",
            "dependency_mode": "verified",
            "trusted_dependencies": _trusted_dependencies(),
        }
    }
    remediation_service = RemediationService(
        repositories=repository_config,
        ttl_seconds=max(900.0, timeout_seconds + 300.0),
        prepare_timeout_seconds=30.0,
        max_prepare_workers=2,
    )
    final_output_sha256 = _review_receipt_output_hash(review)
    try:
        remediation_service.register_trusted_review(
            repository_id=scenario.repository_id,
            base=scenario.base,
            head=scenario.head,
            final_review=final_review,
            final_output_sha256=final_output_sha256,
        )
    except Exception as exc:
        remediation_service.close()
        raise ArchitectureEvolutionError("trusted_review_registration_failed") from exc
    try:
        receipt_journal = PrivateReceiptJournal(receipt_journal_path)
    except ReceiptJournalError as exc:
        remediation_service.close()
        raise ArchitectureEvolutionError("receipt_journal_invalid") from exc
    server = MCPServer(
        ReviewService(),
        remediation_service=remediation_service,
        config=MCPServerConfig(
            host=e2e.MCP_HOST,
            port=e2e.MCP_PORT,
            endpoint=e2e.MCP_ENDPOINT,
            mode="none",
            request_timeout_seconds=30.0,
            max_concurrency=4,
        ),
        trace_sink=receipt_journal.append,
    )
    payload = {
        "repository_id": scenario.repository_id,
        "base": scenario.base,
        "head": scenario.head,
        "review_id": final_review["review_id"],
        "review_digest": final_review["review_digest"],
        "task_digest": final_review["task_digest"],
        "remediation_id": remediation_id,
        "finding_sha256": finding_sha256(finding),
        "data_classification": "synthetic-public",
        "idempotency_key": remediation_id,
    }
    started = time.monotonic()
    try:
        with server:
            ready = e2e._default_preflight()
            mcp_attestation = ready.payload.get("mcp")
            worker_attestation = (
                mcp_attestation.get("worker_ready_discovery")
                if isinstance(mcp_attestation, Mapping)
                else None
            )
            stages = (
                worker_attestation.get("stages")
                if isinstance(worker_attestation, Mapping)
                else None
            )
            if (
                ready.payload.get("status") != "ready"
                or ready.payload.get("all_model_routes_pinned") is not True
                or not isinstance(stages, Mapping)
                or stages.get("remediation", {}).get("active_tools")
                != list(preflight.REMEDIATION_MCP_TOOL_NAMES)
            ):
                raise ArchitectureEvolutionError(
                    "preflight_not_worker_ready", status="not_configured"
                )
            backend = OuroborosRemediationBackend(
                OuroborosBackendConfig(
                    command_prefix=(ready.executable,),
                    gateway_url=e2e.GATEWAY_URL,
                    runtime_version=e2e.PINNED_VERSION,
                    model_id=e2e.MODEL_ID,
                    workspaces={scenario.repository_id: scenario.repository},
                    prompt_path=REMEDIATION_PROMPT,
                    task_timeout_seconds=timeout_seconds,
                    finalization_grace_seconds=180.0,
                    server_id=preflight.MCP_SERVER_ID,
                    receipt_source=receipt_journal.read,
                    project_registrar=e2e._register_local_project,
                    all_model_routes_pinned=True,
                    disable_diagram_tool=False,
                )
            )
            try:
                task_id = backend.schedule_task("aga:remediate", payload)
                task_result = backend.wait_for_task(task_id)
            except OuroborosIdempotencyConflict as exc:
                raise ArchitectureEvolutionError("remediation_idempotency_conflict") from exc
            except OuroborosBackendError as exc:
                raise ArchitectureEvolutionError("remediation_transport_failed") from exc
            if task_result.status is not TaskStatus.SUCCEEDED:
                code = task_result.metadata.get("error_code")
                safe_code = code if isinstance(code, str) and ID_RE.fullmatch(code) else "remediation_incomplete"
                raise ArchitectureEvolutionError(safe_code, status="incomplete")
            metadata = task_result.metadata
            final = metadata.get("aga_final")
            usage = metadata.get("model_usage")
            if (
                not isinstance(final, Mapping)
                or not isinstance(usage, Mapping)
                or metadata.get("runtime")
                != {"name": "ouroboros", "version": e2e.PINNED_VERSION}
                or metadata.get("provider") != e2e.PROVIDER
                or metadata.get("model") != {"name": e2e.MODEL_ID}
                or metadata.get("tool_names")
                != ["aga_prepare_remediation", "aga_finalize_remediation"]
                or usage.get("cost_complete") is not True
            ):
                raise ArchitectureEvolutionError("remediation_result_contract_mismatch")
            receipts = _remediation_receipts(receipt_journal.read(), remediation_id)
    except ArchitectureEvolutionError:
        raise
    except e2e.E2ERunnerError as exc:
        raise ArchitectureEvolutionError(exc.code, status=exc.status) from exc
    except Exception as exc:
        raise ArchitectureEvolutionError("remediation_task_failed") from exc
    result = {
        "status": "completed",
        "task_id": task_result.task_id,
        "runtime": {
            "name": "ouroboros",
            "version": e2e.PINNED_VERSION,
            "source_commit": preflight.PINNED_SOURCE_COMMIT,
        },
        "provider": e2e.PROVIDER,
        "model": e2e.MODEL_ID,
        "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
        "receipts": receipts,
        "model_usage": dict(usage),
        "final": dict(final),
        "redaction": {
            "credentials_retained": False,
            "absolute_paths_retained": False,
            "raw_prompts_retained": False,
            "raw_provider_payloads_retained": False,
        },
    }
    try:
        e2e._assert_sanitized(result, forbidden_path=scenario.repository)
    except (TypeError, ValueError) as exc:
        raise ArchitectureEvolutionError("remediation_sanitization_failed") from exc
    return result


def _materialize_candidate(
    *,
    scenario: Scenario,
    remediation: Mapping[str, Any],
    run_root: Path,
    correlation_digest: str,
) -> Mapping[str, Any]:
    final = remediation.get("final")
    patch = final.get("patch") if isinstance(final, Mapping) else None
    if not isinstance(patch, Mapping):
        raise ArchitectureEvolutionError("trusted_patch_missing")
    artifact = patch.get("artifact")
    unified_diff = patch.get("diff")
    before_sha = patch.get("before_sha256")
    after_sha = patch.get("after_sha256")
    diff_sha = patch.get("diff_sha256")
    if (
        artifact != "model/integrations.yaml"
        or not isinstance(unified_diff, str)
        or not isinstance(before_sha, str)
        or not isinstance(after_sha, str)
        or not isinstance(diff_sha, str)
        or any(SHA256_RE.fullmatch(value) is None for value in (before_sha, after_sha, diff_sha))
        or _sha256(unified_diff) != diff_sha
    ):
        raise ArchitectureEvolutionError("trusted_patch_contract_mismatch")
    branch_name = f"aga/architecture-{correlation_digest[:16]}"
    worktree = run_root / "candidate-worktree"
    adr_artifact = "model/adrs.yaml"
    try:
        baseline_adr_bytes = _git(
            scenario.repository,
            "show",
            f"{scenario.head}:{adr_artifact}",
        ).stdout
        adr_document = yaml.safe_load(baseline_adr_bytes.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ArchitectureEvolutionError("candidate_adr_unavailable") from exc
    if not isinstance(adr_document, Mapping):
        raise ArchitectureEvolutionError("candidate_adr_invalid")
    adr_collection = adr_document.get("seaf.change.adr")
    if not isinstance(adr_collection, Mapping):
        raise ArchitectureEvolutionError("candidate_adr_invalid")
    adr_id = f"aga.reroute_{diff_sha[:16]}"
    adr_entry = {
        "title": "Reroute scoring traffic away from the retiring service",
        "moment": _git_text(
            scenario.repository, "show", "-s", "--format=%cs", scenario.head
        ),
        "status": "proposed",
        "issue": (
            f"Integration {patch.get('entity_id')} targets retiring component "
            f"{patch.get('eliminated_component')}."
        ),
        "decision": (
            f"Reroute the integration to strategic successor "
            f"{patch.get('replacement_component')} using the existing REST contract."
        ),
        "context": [
            {
                "area": "technology",
                "vector": "positive",
                "content": "The successor removes a new dependency on an eliminate-status component.",
            },
            {
                "area": "time",
                "vector": "unknown",
                "content": "The candidate remains subject to re-review and human approval before publication.",
            },
            {
                "area": "technology",
                "vector": "negative",
                "content": (
                    f"Alternative considered: retain {patch.get('eliminated_component')}; "
                    "rejected because its target_status is eliminate."
                ),
            },
            {
                "area": "technology",
                "vector": "unknown",
                "content": (
                    "Constraint: preserve the existing REST contract and verify "
                    "compatibility before switching traffic."
                ),
            },
        ],
        "consequences": [
            {
                "area": "technology",
                "vector": "positive",
                "content": "New traffic uses the declared strategic scoring successor.",
            },
            {
                "area": "time",
                "vector": "negative",
                "content": "Compatibility and migration checks are required before rollout.",
            },
        ],
        "deciders": ["AGA synthetic architecture review"],
    }
    updated_adr_document = dict(adr_document)
    updated_adr_collection = dict(adr_collection)
    existing_adr = updated_adr_collection.get(adr_id)
    if existing_adr is not None and existing_adr != adr_entry:
        raise ArchitectureEvolutionError("candidate_adr_conflict")
    updated_adr_collection[adr_id] = adr_entry
    updated_adr_document["seaf.change.adr"] = updated_adr_collection
    expected_adr_text = yaml.safe_dump(
        updated_adr_document,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    expected_paths = sorted((artifact, adr_artifact))
    branch_exists = _git(
        scenario.repository,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{branch_name}",
        check=False,
    ).returncode == 0
    if branch_exists:
        patched_head = _git_text(scenario.repository, "rev-parse", branch_name)
        changed_paths = [
            line
            for line in _git_text(
                scenario.repository,
                "diff",
                "--name-only",
                scenario.head,
                branch_name,
            ).splitlines()
            if line
        ]
        after_bytes = _git(
            scenario.repository,
            "show",
            f"{branch_name}:{artifact}",
        ).stdout
        if changed_paths not in ([artifact], expected_paths) or _sha256(after_bytes) != after_sha:
            raise ArchitectureEvolutionError("candidate_branch_conflict")
        if worktree.exists():
            if (
                _git_text(worktree, "rev-parse", "HEAD") != patched_head
                or _git_text(worktree, "status", "--porcelain=v1", "--untracked-files=all")
            ):
                raise ArchitectureEvolutionError("candidate_worktree_conflict")
        else:
            _git(
                scenario.repository,
                "worktree",
                "add",
                "--detach",
                str(worktree),
                patched_head,
            )
            _ensure_gitlink_placeholders(worktree)
        if changed_paths == [artifact]:
            if _git_text(scenario.repository, "rev-parse", f"{branch_name}^") != scenario.head:
                raise ArchitectureEvolutionError("candidate_branch_conflict")
            (worktree / adr_artifact).write_text(expected_adr_text, encoding="utf-8")
            _git(worktree, "add", "--", adr_artifact)
            _git(
                worktree,
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-m",
                "AGA candidate: record reroute ADR",
                commit=True,
            )
            patched_head = _git_text(worktree, "rev-parse", "HEAD")
            changed_paths = expected_paths
        try:
            actual_adr_text = (worktree / adr_artifact).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ArchitectureEvolutionError("candidate_adr_unavailable") from exc
        if changed_paths != expected_paths or actual_adr_text != expected_adr_text:
            raise ArchitectureEvolutionError("candidate_branch_conflict")
        return {
            "branch_name": branch_name,
            "worktree": worktree,
            "patched_head": patched_head,
            "artifact": artifact,
            "diff": unified_diff,
            "diff_sha256": diff_sha,
            "after_sha256": after_sha,
            "adr_artifact": adr_artifact,
            "adr_id": adr_id,
            "idempotent": True,
        }
    if worktree.exists():
        raise ArchitectureEvolutionError("candidate_worktree_conflict")
    _git(
        scenario.repository,
        "worktree",
        "add",
        "-b",
        branch_name,
        str(worktree),
        scenario.head,
    )
    _ensure_gitlink_placeholders(worktree)
    artifact_path = worktree / "model" / "integrations.yaml"
    try:
        before_bytes = artifact_path.read_bytes()
    except OSError as exc:
        raise ArchitectureEvolutionError("candidate_artifact_unavailable") from exc
    if _sha256(before_bytes) != before_sha:
        raise ArchitectureEvolutionError("candidate_before_hash_mismatch")
    diff_bytes = unified_diff.encode("utf-8")
    _git(worktree, "apply", "--check", "--whitespace=nowarn", "-", input_bytes=diff_bytes)
    _git(
        worktree,
        "apply",
        "--index",
        "--whitespace=nowarn",
        "-",
        input_bytes=diff_bytes,
    )
    try:
        after_bytes = artifact_path.read_bytes()
    except OSError as exc:
        raise ArchitectureEvolutionError("candidate_artifact_unavailable") from exc
    if _sha256(after_bytes) != after_sha:
        raise ArchitectureEvolutionError("candidate_after_hash_mismatch")
    (worktree / adr_artifact).write_text(expected_adr_text, encoding="utf-8")
    _git(worktree, "add", "--", adr_artifact)
    staged_paths = [
        line.strip()
        for line in _git_text(worktree, "diff", "--cached", "--name-only").splitlines()
        if line.strip()
    ]
    if staged_paths != expected_paths:
        raise ArchitectureEvolutionError("candidate_scope_violation")
    _git(
        worktree,
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-m",
        "AGA candidate: reroute SEAF-004 dependency",
        commit=True,
    )
    patched_head = _git_text(worktree, "rev-parse", "HEAD")
    if REVISION_RE.fullmatch(patched_head) is None:
        raise ArchitectureEvolutionError("candidate_commit_invalid")
    if _git_text(worktree, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ArchitectureEvolutionError("candidate_worktree_not_clean")
    if _git_text(scenario.repository, "status", "--porcelain=v1", "--untracked-files=all") != scenario.source_status:
        raise ArchitectureEvolutionError("source_worktree_changed")
    if _git_text(scenario.repository, "branch", "--show-current") != scenario.source_branch:
        raise ArchitectureEvolutionError("source_branch_changed")
    if _git_text(scenario.repository, "rev-parse", "HEAD") != scenario.source_head:
        raise ArchitectureEvolutionError("source_head_changed")
    return {
        "branch_name": branch_name,
        "worktree": worktree,
        "patched_head": patched_head,
        "artifact": artifact,
        "diff": unified_diff,
        "diff_sha256": diff_sha,
        "after_sha256": after_sha,
        "adr_artifact": adr_artifact,
        "adr_id": adr_id,
        "idempotent": False,
    }


def _gate(
    *,
    initial_finding: Mapping[str, Any],
    re_review: Mapping[str, Any],
) -> Mapping[str, Any]:
    final = re_review.get("final")
    if not isinstance(final, Mapping):
        raise ArchitectureEvolutionError("rereview_final_missing")
    findings = final.get("findings")
    if not isinstance(findings, list) or any(not isinstance(item, Mapping) for item in findings):
        raise ArchitectureEvolutionError("rereview_findings_invalid")
    target_identity = (
        initial_finding.get("rule_id"),
        initial_finding.get("canonical_defect"),
    )
    target_closed = not any(
        (item.get("rule_id"), item.get("canonical_defect")) == target_identity
        for item in findings
    )
    blocking = [
        {
            "rule_id": item.get("rule_id"),
            "severity": item.get("severity"),
            "canonical_defect": item.get("canonical_defect"),
        }
        for item in findings
        if item.get("severity") in {"blocker", "major"}
    ]
    checks = {
        "target_finding_closed": target_closed,
        "no_blocker_or_major": not blocking,
        "review_completed": final.get("status") == "completed"
        and final.get("incomplete") is False,
        "auto_merge_forbidden": final.get("auto_merge") is False,
        "publication_human_review_required": True,
        "candidate_only": True,
    }
    passed = all(checks.values())
    result = {
        **checks,
        "blocking_findings": blocking,
        "passed": passed,
        "human_review_required": True,
        "auto_merge": False,
    }
    if not passed:
        raise ArchitectureEvolutionError("remediation_gate_failed", status="incomplete")
    return result


def _review_cost(review: Mapping[str, Any]) -> float:
    usage = review.get("model_usage")
    value = usage.get("known_cost_usd") if isinstance(usage, Mapping) else None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise ArchitectureEvolutionError("review_cost_invalid")
    return float(value)


def _write_report(
    *,
    path: Path,
    scenario: Scenario,
    finding: Mapping[str, Any],
    candidate: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    report = (
        "# Local architecture candidate\n\n"
        f"Status: candidate-only; human review required; auto-merge disabled.\n\n"
        f"Base: `{scenario.base}`\n\n"
        f"Reviewed head: `{scenario.head}`\n\n"
        f"Candidate head: `{candidate['patched_head']}`\n\n"
        f"Candidate branch: `{candidate['branch_name']}`\n\n"
        f"Finding: `{finding['rule_id']}` / `{finding['canonical_defect']}`.\n\n"
        f"Gate passed: `{str(gate['passed']).lower()}`.\n\n"
        "```diff\n"
        f"{candidate['diff']}"
        "```\n"
    )
    path.write_text(report, encoding="utf-8")
    path.chmod(0o600)


def _cached_result(
    state_path: Path,
    *,
    scenario: Scenario,
    correlation_digest: str,
) -> Mapping[str, Any] | None:
    if not state_path.exists():
        return None
    if state_path.is_symlink() or not state_path.is_file() or state_path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ArchitectureEvolutionError("state_invalid")
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchitectureEvolutionError("state_invalid") from exc
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != STATE_SCHEMA
        or value.get("correlation_sha256") != correlation_digest
        or value.get("repository_id") != scenario.repository_id
        or value.get("base") != scenario.base
        or value.get("head") != scenario.head
        or not isinstance(value.get("result"), Mapping)
    ):
        raise ArchitectureEvolutionError("state_conflict")
    result = dict(value["result"])
    try:
        e2e._assert_sanitized(result, forbidden_path=scenario.repository)
    except (TypeError, ValueError) as exc:
        raise ArchitectureEvolutionError("state_sanitization_failed") from exc
    if (
        len(_canonical_bytes(result)) > MAX_EVIDENCE_BYTES
        or result.get("schema") != SCHEMA
        or result.get("status") != "local_candidate_ready"
        or result.get("correlation_sha256") != correlation_digest
        or result.get("repository_id") != scenario.repository_id
        or result.get("base") != scenario.base
        or result.get("head") != scenario.head
        or not isinstance(result.get("gate"), Mapping)
        or result["gate"].get("passed") is not True
        or not isinstance(result.get("source_unchanged"), Mapping)
        or result["source_unchanged"].get("branch") != scenario.source_branch
        or result["source_unchanged"].get("head") != scenario.source_head
    ):
        raise ArchitectureEvolutionError("state_invalid")
    candidate = result.get("candidate")
    branch = candidate.get("branch_name") if isinstance(candidate, Mapping) else None
    patched = candidate.get("patched_head") if isinstance(candidate, Mapping) else None
    if (
        not isinstance(branch, str)
        or not isinstance(patched, str)
        or _git(
            scenario.repository,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        ).returncode
        != 0
        or _git_text(scenario.repository, "rev-parse", branch) != patched
    ):
        raise ArchitectureEvolutionError("cached_candidate_missing")
    return {**result, "reused": True}


def _load_phases(
    path: Path,
    *,
    scenario: Scenario,
    correlation_digest: str,
) -> dict[str, Mapping[str, Any]]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ArchitectureEvolutionError("phase_state_invalid")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchitectureEvolutionError("phase_state_invalid") from exc
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != PHASE_SCHEMA
        or value.get("correlation_sha256") != correlation_digest
        or value.get("repository_id") != scenario.repository_id
        or value.get("base") != scenario.base
        or value.get("head") != scenario.head
        or not isinstance(value.get("phases"), Mapping)
        or set(value["phases"]) - {"review_before", "remediation"}
    ):
        raise ArchitectureEvolutionError("phase_state_conflict")
    phases: dict[str, Mapping[str, Any]] = {}
    for name, item in value["phases"].items():
        if not isinstance(item, Mapping):
            raise ArchitectureEvolutionError("phase_state_invalid")
        try:
            e2e._assert_sanitized(item, forbidden_path=scenario.repository)
        except (TypeError, ValueError) as exc:
            raise ArchitectureEvolutionError("phase_state_sanitization_failed") from exc
        phases[str(name)] = dict(item)
    review = phases.get("review_before")
    if review is not None and (
        review.get("status") != "completed"
        or review.get("repository_id") != scenario.repository_id
        or review.get("base") != scenario.base
        or review.get("head") != scenario.head
    ):
        raise ArchitectureEvolutionError("phase_state_invalid")
    remediation = phases.get("remediation")
    if remediation is not None and review is None:
        raise ArchitectureEvolutionError("phase_state_invalid")
    if remediation is not None and remediation.get("status") != "completed":
        raise ArchitectureEvolutionError("phase_state_invalid")
    return phases


def _save_phases(
    path: Path,
    *,
    scenario: Scenario,
    correlation_digest: str,
    phases: Mapping[str, Mapping[str, Any]],
) -> None:
    _atomic_private_json(
        path,
        {
            "schema": PHASE_SCHEMA,
            "correlation_sha256": correlation_digest,
            "repository_id": scenario.repository_id,
            "base": scenario.base,
            "head": scenario.head,
            "phases": dict(phases),
        },
    )


def run_architecture_evolution(
    *,
    correlation_key: str,
    state_root: Path = DEFAULT_STATE_ROOT,
    evidence_out: Path = DEFAULT_EVIDENCE_OUT,
    timeout_seconds: float = 1200.0,
    demo: bool = True,
    repository: Path | None = None,
    repository_id: str | None = None,
    base: str | None = None,
    head: str | None = None,
) -> Mapping[str, Any]:
    if not isinstance(correlation_key, str) or ID_RE.fullmatch(correlation_key) is None:
        raise ArchitectureEvolutionError("correlation_key_invalid")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= e2e.MAX_TASK_TIMEOUT_SECONDS
    ):
        raise ArchitectureEvolutionError("timeout_invalid")
    selected_evidence_out = _validated_evidence_path(Path(evidence_out))
    correlation_digest = _sha256(correlation_key)
    run_root = Path(state_root) / correlation_digest[:16]
    run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    run_root.chmod(0o700)
    if demo:
        if any(value is not None for value in (repository, base, head)):
            raise ArchitectureEvolutionError("demo_and_repository_conflict")
        selected_repository_id = repository_id or f"aga-architecture-{correlation_digest[:16]}"
        scenario = _materialize_demo(run_root, selected_repository_id)
    else:
        if (
            repository is None
            or repository_id is None
            or base is None
            or head is None
        ):
            raise ArchitectureEvolutionError("repository_arguments_required")
        scenario = _existing_scenario(repository, repository_id, base, head)
    cached = _cached_result(
        run_root / "state.json",
        scenario=scenario,
        correlation_digest=correlation_digest,
    )
    if cached is not None:
        _atomic_public_json(selected_evidence_out, cached)
        return cached
    phase_path = run_root / "phases.json"
    phases = _load_phases(
        phase_path,
        scenario=scenario,
        correlation_digest=correlation_digest,
    )
    failure_path = run_root / "failures.json"
    _failure_guard(failure_path)

    stage = "budget_before_review"
    initial_budget = _budget_checkpoint(None)
    initial_usage = float(initial_budget["usage_usd"])
    try:
        stage = "review_before"
        budget_before_review = _budget_checkpoint(initial_usage)
        review_before = phases.get("review_before")
        if review_before is None:
            review_before = run_live_review(
                repository=scenario.repository,
                repository_id=scenario.repository_id,
                base=scenario.base,
                head=scenario.head,
                idempotency_key=f"review-before-{correlation_digest[:24]}",
                timeout_seconds=timeout_seconds,
                state_root=run_root / "review-state",
            )
            phases["review_before"] = dict(review_before)
            _save_phases(
                phase_path,
                scenario=scenario,
                correlation_digest=correlation_digest,
                phases=phases,
            )
        if review_before.get("status") != "completed":
            raise ArchitectureEvolutionError("initial_review_incomplete", status="incomplete")
        finding = _select_finding(review_before)

        stage = "remediation"
        budget_before_remediation = _budget_checkpoint(initial_usage)
        remediation_id = f"aga-remediation-{correlation_digest[:24]}"
        remediation = phases.get("remediation")
        if remediation is None:
            remediation = _run_remediation_task(
                scenario=scenario,
                review=review_before,
                finding=finding,
                remediation_id=remediation_id,
                timeout_seconds=timeout_seconds,
                receipt_journal_path=run_root / "remediation.receipts.jsonl",
            )
            phases["remediation"] = dict(remediation)
            _save_phases(
                phase_path,
                scenario=scenario,
                correlation_digest=correlation_digest,
                phases=phases,
            )

        stage = "materialize"
        candidate_private = _materialize_candidate(
            scenario=scenario,
            remediation=remediation,
            run_root=run_root,
            correlation_digest=correlation_digest,
        )

        stage = "review_after"
        budget_before_rereview = _budget_checkpoint(initial_usage)
        re_review_id = f"aga-patched-{correlation_digest[:16]}"
        review_after = run_live_review(
            repository=candidate_private["worktree"],
            repository_id=re_review_id,
            base=scenario.head,
            head=candidate_private["patched_head"],
            idempotency_key=f"review-after-{correlation_digest[:24]}",
            timeout_seconds=timeout_seconds,
            state_root=run_root / "review-state",
        )
        if review_after.get("status") != "completed":
            raise ArchitectureEvolutionError("rereview_incomplete", status="incomplete")
        gate = _gate(initial_finding=finding, re_review=review_after)
        final_budget = _budget_checkpoint(initial_usage)
    except LiveReviewError as exc:
        _record_failed_batch(
            path=failure_path,
            evidence_out=selected_evidence_out,
            code=exc.code,
            stage=stage,
            initial_usage=initial_usage,
            correlation_digest=correlation_digest,
        )
        raise ArchitectureEvolutionError(exc.code, status=exc.status) from exc
    except ArchitectureEvolutionError as exc:
        _record_failed_batch(
            path=failure_path,
            evidence_out=selected_evidence_out,
            code=exc.code,
            stage=stage,
            initial_usage=initial_usage,
            correlation_digest=correlation_digest,
        )
        raise
    except Exception as exc:
        code = f"{stage}_failed"
        _record_failed_batch(
            path=failure_path,
            evidence_out=selected_evidence_out,
            code=code,
            stage=stage,
            initial_usage=initial_usage,
            correlation_digest=correlation_digest,
        )
        raise ArchitectureEvolutionError(code) from exc

    remediation_usage = remediation.get("model_usage")
    remediation_cost = (
        remediation_usage.get("known_cost_usd")
        if isinstance(remediation_usage, Mapping)
        else None
    )
    if (
        isinstance(remediation_cost, bool)
        or not isinstance(remediation_cost, (int, float))
        or not math.isfinite(float(remediation_cost))
        or float(remediation_cost) < 0.0
    ):
        raise ArchitectureEvolutionError("remediation_cost_invalid")
    task_cost = round(
        _review_cost(review_before)
        + float(remediation_cost)
        + _review_cost(review_after),
        8,
    )
    budget_delta = round(
        max(0.0, float(final_budget["usage_usd"]) - initial_usage), 8
    )
    candidate = {
        "branch_name": candidate_private["branch_name"],
        "patched_head": candidate_private["patched_head"],
        "artifact": candidate_private["artifact"],
        "diff_sha256": candidate_private["diff_sha256"],
        "after_sha256": candidate_private["after_sha256"],
        "idempotent": candidate_private["idempotent"],
        "local_candidate_ready": True,
        "external_side_effects": False,
        "draft_pr_url": None,
        "human_review_required": True,
        "auto_merge": False,
        "worktree_retained": True,
    }
    result = {
        "schema": SCHEMA,
        "status": "local_candidate_ready",
        "reused": False,
        "correlation_sha256": correlation_digest,
        "repository_id": scenario.repository_id,
        "data_classification": "synthetic-public",
        "base": scenario.base,
        "head": scenario.head,
        "patched_head": candidate_private["patched_head"],
        "runtime": {
            "name": "ouroboros",
            "version": e2e.PINNED_VERSION,
            "source_commit": preflight.PINNED_SOURCE_COMMIT,
        },
        "provider": e2e.PROVIDER,
        "model": e2e.MODEL_ID,
        "review_before": review_before,
        "initial_finding": finding,
        "initial_finding_sha256": finding_sha256(finding),
        "remediation": remediation,
        "candidate": candidate,
        "review_after": review_after,
        "gate": gate,
        "budget": {
            "initial": initial_budget,
            "before_review": budget_before_review,
            "before_remediation": budget_before_remediation,
            "before_rereview": budget_before_rereview,
            "final": final_budget,
            "task_reported_cost_usd": task_cost,
            "aggregate_usage_delta_usd": budget_delta,
            "stop_threshold_usd": MAX_IMPLEMENTATION_SPEND_USD,
        },
        "publication": {
            "status": "local_candidate_ready",
            "external_side_effects": False,
            "branch_name": candidate_private["branch_name"],
            "commit": candidate_private["patched_head"],
            "draft_pr_url": None,
            "human_review_required": True,
            "auto_merge": False,
        },
        "source_unchanged": {
            "branch": scenario.source_branch,
            "head": scenario.source_head,
            "status_unchanged": True,
        },
        "redaction": {
            "credentials_retained": False,
            "absolute_paths_retained": False,
            "raw_prompts_retained": False,
            "raw_provider_payloads_retained": False,
        },
    }
    try:
        e2e._assert_sanitized(result, forbidden_path=scenario.repository)
    except (TypeError, ValueError) as exc:
        raise ArchitectureEvolutionError("evidence_sanitization_failed") from exc
    if len(_canonical_bytes(result)) > MAX_EVIDENCE_BYTES:
        raise ArchitectureEvolutionError("evidence_too_large")
    _write_report(
        path=run_root / "candidate-report.md",
        scenario=scenario,
        finding=finding,
        candidate=candidate_private,
        gate=gate,
    )
    _atomic_private_json(
        run_root / "state.json",
        {
            "schema": STATE_SCHEMA,
            "correlation_sha256": correlation_digest,
            "repository_id": scenario.repository_id,
            "base": scenario.base,
            "head": scenario.head,
            "result": result,
        },
    )
    _atomic_public_json(selected_evidence_out, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="create/reuse the controlled demo")
    mode.add_argument("--repository", type=Path, help="existing clean local Git root")
    parser.add_argument("--repository-id")
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--correlation-key", default=DEFAULT_CORRELATION)
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--evidence-out", type=Path, default=DEFAULT_EVIDENCE_OUT)
    return parser


def _emit(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    use_demo = arguments.demo or arguments.repository is None
    try:
        result = run_architecture_evolution(
            correlation_key=arguments.correlation_key,
            state_root=arguments.state_root,
            evidence_out=arguments.evidence_out,
            timeout_seconds=arguments.timeout,
            demo=use_demo,
            repository=arguments.repository,
            repository_id=arguments.repository_id,
            base=arguments.base,
            head=arguments.head,
        )
        evidence_path = (
            arguments.evidence_out
            if arguments.evidence_out.is_absolute()
            else REPOSITORY_ROOT / arguments.evidence_out
        ).resolve(strict=False)
        _emit(
            {
                "schema": CLI_SCHEMA,
                "status": result["status"],
                "base": result["base"],
                "head": result["head"],
                "patched_head": result["patched_head"],
                "branch_name": result["candidate"]["branch_name"],
                "reused": result["reused"],
                "evidence": evidence_path.relative_to(
                    REPOSITORY_ROOT.resolve(strict=True)
                ).as_posix(),
            }
        )
        return 0
    except ArchitectureEvolutionError as exc:
        _emit({"schema": CLI_SCHEMA, "status": exc.status, "code": exc.code})
        if exc.status == "not_configured":
            return 2
        if exc.status in {"incomplete", "budget_exhausted"}:
            return 4
        return 3
    except Exception:
        _emit({"schema": CLI_SCHEMA, "status": "failed", "code": "internal_architecture_evolution_error"})
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
