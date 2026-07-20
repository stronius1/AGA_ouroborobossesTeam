#!/usr/bin/env python3
"""Materialize a validated Loop-A bundle as a local candidate commit.

This separately authorised entrypoint independently replays the mutation,
recomputes baseline/candidate fitness and the protected gate, binds those
results to the target repository's exact HEAD, and then delegates only an
exact local transaction to :class:`LocalCandidatePublisher`.  It has no
remote, push, pull-request, approval, or merge surface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from scripts.apply_candidate import validate_candidate  # noqa: E402
from tools.publisher import (  # noqa: E402
    LocalCandidatePublisher,
    LocalCandidateRequest,
    PublisherError,
)


def publish(
    *,
    build: Path,
    repository: Path,
    actor: str,
) -> dict:
    # This is the independent zero-trust replay.  It re-evaluates both rule
    # sets and reruns the fitness gate before any materialization occurs.
    validated = validate_candidate(build)
    manifest = validated["manifest"]
    publisher = LocalCandidatePublisher(repository_root=repository)
    base_commit = publisher.resolve_head()
    report_path = f"docs/evidence/evolution/{manifest['cycle_id']}.md"
    evidence_path = f"docs/evidence/evolution/{manifest['cycle_id']}.json"
    files = dict(validated["transaction_payloads"])
    files[report_path] = validated["pr_body"].encode("utf-8")
    evidence = {
        "schema": "aga.local-candidate-evidence/v1",
        "cycle_id": manifest["cycle_id"],
        "base_commit": base_commit,
        "branch_name": validated["branch"],
        "version_from": manifest["version_from"],
        "version_to": manifest["version_to"],
        "actor": actor,
        "mutation_type": validated["mutation"]["type"],
        "target_rule": validated["target_rule"],
        "precedent": validated["precedent"],
        "baseline_revision": validated["baseline_revision"],
        "candidate_revision": validated["candidate_revision"],
        "fixtures_revision": validated["fixtures_revision"],
        "gate_checks": validated["gate_checks"],
        "files": {
            path: hashlib.sha256(payload).hexdigest()
            for path, payload in sorted(files.items())
        },
        "human_review_required": True,
        "auto_merge": False,
        "external_side_effects": False,
        "draft_pr_url": None,
        "redaction": (
            "Contains no secrets, raw prompts, provider responses, or absolute paths."
        ),
    }
    files[evidence_path] = (
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    changed_rule_paths = tuple(
        f"aga-skill/rules/{name}" for name in validated["changed_rule_files"]
    )
    precedent_path = (
        f"aga-skill/precedents/cases/{manifest['precedent_artifact']}"
    )
    request = LocalCandidateRequest(
        cycle_id=manifest["cycle_id"],
        base_commit=base_commit,
        branch_name=validated["branch"],
        commit_message=(
            f"AGA candidate {manifest['version_from']} -> {manifest['version_to']}: "
            f"{validated['mutation']['type']} for {validated['target_rule']}"
        ),
        files=files,
        base_bindings=validated["base_binding_payloads"],
        changed_rule_paths=changed_rule_paths,
        precedent_path=precedent_path,
        report_path=report_path,
        manifest_path=evidence_path,
        metadata={"actor": actor},
    )
    result = publisher.publish(request)

    return {
        "status": result.status,
        "external_side_effects": result.external_side_effects,
        "branch_name": result.branch_name,
        "commit": result.commit,
        "draft_pr_url": result.draft_pr_url,
        "human_review_required": result.human_review_required,
        "auto_merge": result.auto_merge,
        "actor": actor,
        "cycle_id": manifest["cycle_id"],
        "base_commit": base_commit,
        "target_rule": validated["target_rule"],
        "changed_rule_ids": validated["changed_rule_ids"],
        "changed_rule_files": validated["changed_rule_files"],
        "gate_checks": validated["gate_checks"],
        "publication": result.as_dict(),
        "original_worktree_unchanged": result.details.get(
            "original_worktree_unchanged", False
        ),
        "candidate_sources_changed": True,
        "merge_performed": False,
        "approval_performed": False,
        "push_performed": False,
    }


def _parse_actor(value: str) -> str:
    if (
        not value.strip()
        or len(value) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("actor must be a printable non-empty identity up to 200 characters")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a reviewed local branch/commit for an AGA candidate"
    )
    parser.add_argument("--build", default=str(PKG_ROOT / "build"))
    parser.add_argument(
        "--repository",
        required=True,
        help="exact local Git top-level containing aga-skill/; its HEAD, index, "
        "and worktree are left unchanged",
    )
    parser.add_argument("--actor", required=True)
    args = parser.parse_args(argv)

    try:
        actor = _parse_actor(args.actor)
        result = publish(
            build=Path(args.build),
            repository=Path(args.repository),
            actor=actor,
        )
    except (OSError, ValueError, json.JSONDecodeError, PublisherError) as error:
        print(
            json.dumps(
                {"error": "publish_candidate_error", "message": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
