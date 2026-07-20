#!/usr/bin/env python3
"""Loop-B remediation demo: turn one SEAF-004 finding into a validated
architecture patch, and optionally a draft PR.

This is the architecture-remediation counterpart to
``scripts/run_seaf_review.py``'s deterministic ``demo-critical-dependency``
smoke. It intentionally materializes its own small synthetic base/head
Git repository rather than touching the frozen ``demo-critical-dependency``
fixture or the project's real ``architecture/`` directory, so it has zero
blast radius on anything already frozen as release evidence.

Default behaviour is dry-run only:

1. materialize a synthetic SEAF change that introduces a SEAF-004 blocker;
2. propose a patch with ``tools.remediation.propose_remediation``;
3. apply the patch as a scratch commit and re-run the SEAF-native review;
4. gate: the target finding must be closed and zero new findings may appear;
5. print a PR-shaped report.

``--open-draft-pr`` additionally calls the configured publisher
(``tools.publisher``). Whichever publisher is configured, it can never
merge, approve, or push to a protected branch -- that boundary lives in
``tools/publisher.py``, not here. A human architect always does the merge.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from scripts.run_seaf_review import _commit, _git, _write  # noqa: E402
from tools.publisher import PublishRequest, default_publisher  # noqa: E402
from tools.remediation import RemediationNotAvailable, propose_remediation  # noqa: E402
from tools.repository_snapshot import RepositorySnapshotBuilder  # noqa: E402
from tools.seaf_review import prepare_seaf_review  # noqa: E402


PROJECT_EXTENSION_TEXT = (
    PACKAGE_ROOT.parent / "architecture" / "metamodel" / "aga-extension.yaml"
).read_text(encoding="utf-8")


CASE_ID = "demo-remediation-critical-dependency"


BASE_DOCUMENTS = {
    "dochub.yaml": """aga:
  schema: seaf-core/v1.4.0
  extensions: [aga.project/v1]
  data_classification: synthetic-public
imports:
  - aga-extension.yaml
  - model/components.yaml
  - model/integrations.yaml
  - model/adrs.yaml
""",
    "aga-extension.yaml": PROJECT_EXTENSION_TEXT,
    # ``demo.legacy_scoring`` declares its own approved successor via
    # ``replaced_by``. That field is the only thing that makes a deterministic,
    # non-hallucinated remediation possible: the target is not guessed by the
    # agent, it is a fact the architecture's own owner already recorded.
    "model/components.yaml": """components:
  demo.checkout:
    title: Synthetic Checkout
    entity: component
    description: Synthetic customer checkout component.
    owner: Synthetic Commerce Team
    criticality: mission_critical
    target_status: strategic
  demo.legacy_scoring:
    title: Synthetic Legacy Scoring
    entity: component
    description: Synthetic scoring component scheduled for retirement.
    owner: Synthetic Legacy Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.scoring_v2
  demo.scoring_v2:
    title: Synthetic Scoring v2
    entity: component
    description: Synthetic approved strategic replacement for the retiring scorer.
    owner: Synthetic Legacy Team
    criticality: high
    target_status: strategic
""",
    "model/integrations.yaml": "seaf.app.integrations: {}\n",
    "model/adrs.yaml": "seaf.change.adr: {}\n",
}


HEAD_INTEGRATIONS = """seaf.app.integrations:
  demo.checkout_to_legacy_scoring:
    title: Checkout to retiring scoring
    description: Synthetic synchronous lookup during checkout.
    from: demo.checkout
    to: demo.legacy_scoring
"""


def _materialize(repository: Path) -> tuple[str, str]:
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main", "--object-format=sha1")
    for relative, content in BASE_DOCUMENTS.items():
        _write(repository, relative, content)
    base = _commit(repository, "synthetic SEAF base (remediation demo)", "2026-07-18T08:00:00Z")
    _write(repository, "model/integrations.yaml", HEAD_INTEGRATIONS)
    head = _commit(
        repository, "add synthetic retiring dependency", "2026-07-18T08:01:00Z"
    )
    return base, head


def _defect_keys(findings) -> set[tuple[str, str]]:
    return {(finding["rule_id"], finding["canonical_defect"]) for finding in findings}


def run_case(*, open_draft_pr: bool) -> tuple[dict, int]:
    with tempfile.TemporaryDirectory(prefix="aga-remediation-") as temporary:
        repository = Path(temporary) / "architecture"
        base, head = _materialize(repository)

        with RepositorySnapshotBuilder(
            repository, base, head, dependency_mode="fixture"
        ).build() as snapshot:
            prepared = prepare_seaf_review(snapshot)

        target_findings = [
            finding
            for finding in prepared["deterministic_findings"]
            if finding["rule_id"] == "SEAF-004"
        ]
        if not target_findings:
            return (
                {
                    "status": "no_remediation_needed",
                    "case_id": CASE_ID,
                    "reason": "no SEAF-004 finding was produced by the prepared review",
                },
                0,
            )
        finding = target_findings[0]

        try:
            patch = propose_remediation(finding, repository)
        except RemediationNotAvailable as exc:
            return (
                {
                    "status": "remediation_not_available",
                    "case_id": CASE_ID,
                    "finding": finding,
                    "reason": exc.reason,
                    "code": exc.code,
                    "hitl_required": True,
                    "auto_merge": False,
                },
                3,
            )

        # Apply the patch as a scratch commit in this ephemeral repository.
        # Nothing outside this temporary directory is ever touched, and this
        # commit is never pushed anywhere by this script.
        _write(repository, patch.artifact, patch.after_text)
        patched_head = _commit(
            repository,
            f"AGA remediation candidate: {patch.summary}",
            "2026-07-18T08:02:00Z",
        )

        with RepositorySnapshotBuilder(
            repository, head, patched_head, dependency_mode="fixture"
        ).build() as patched_snapshot:
            re_prepared = prepare_seaf_review(patched_snapshot)

        before_keys = _defect_keys(prepared["deterministic_findings"])
        after_keys = _defect_keys(re_prepared["deterministic_findings"])
        target_key = (finding["rule_id"], finding["canonical_defect"])
        target_closed = target_key not in after_keys
        new_findings = sorted(after_keys - before_keys)
        gate_passed = target_closed and not new_findings

        result: dict = {
            "status": "remediation_ready" if gate_passed else "remediation_gate_failed",
            "case_id": CASE_ID,
            "rule_id": finding["rule_id"],
            "finding": finding,
            "patch": patch.as_dict(),
            "gate": {
                "target_finding_closed": target_closed,
                "new_findings": [
                    {"rule_id": rule_id, "canonical_defect": defect}
                    for rule_id, defect in new_findings
                ],
                "passed": gate_passed,
            },
            "remaining_deterministic_findings": re_prepared["deterministic_findings"],
            "hitl_required": True,
            "auto_merge": False,
        }
        if not gate_passed:
            return result, 4

        pr_body = (
            "## AGA architecture remediation\n\n"
            f"**Finding:** `{finding['rule_id']}` (blocker) on `{finding['entity_id']}`\n\n"
            f"**Evidence:** {finding['evidence']}\n\n"
            f"**Proposed fix:** {patch.summary}\n\n"
            f"```diff\n{patch.unified_diff()}```\n\n"
            "This patch was validated by re-running the AGA SEAF-native review "
            "against the patched revision: the target finding is closed and no "
            "new finding was introduced. This PR was opened by AGA as a draft "
            "only; auto-merge is disabled. A human architect must review and "
            "merge it.\n"
        )
        result["pr_body"] = pr_body

        if open_draft_pr:
            publisher = default_publisher()
            request = PublishRequest(
                cycle_id=f"remediation-{finding['entity_id']}",
                artifacts={"patch.diff": patch.artifact, "pr_body.md": "pr_body.md"},
                branch_name=f"aga/remediation-{finding['entity_id']}",
                commit_message=patch.summary,
                draft=True,
                metadata={"rule_id": finding["rule_id"], "case_id": CASE_ID},
            )
            # Whichever publisher is configured, tools/publisher.py forbids
            # merge/approve/push regardless; it can only ever open a draft.
            publication = publisher.publish(request)
            result["publication"] = publication.as_dict()

        return result, 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=(CASE_ID,), required=True)
    parser.add_argument(
        "--open-draft-pr",
        action="store_true",
        help="Publish the validated patch through the configured publisher "
        "(draft only; never merges, approves, or pushes to a protected branch).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    result, exit_code = run_case(open_draft_pr=arguments.open_draft_pr)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
