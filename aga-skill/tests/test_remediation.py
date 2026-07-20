# -*- coding: utf-8 -*-
"""Loop-B remediation: propose_remediation unit tests and the run_remediation
end-to-end gate (patch -> re-review -> zero new findings -> never merges)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from scripts.run_remediation import run_case  # noqa: E402
from tools.publisher import PublisherPolicyError  # noqa: E402
from tools.remediation import RemediationNotAvailable, propose_remediation  # noqa: E402

INTEGRATIONS_YAML = """seaf.app.integrations:
  demo.checkout_to_legacy_scoring:
    title: Checkout to retiring scoring
    from: demo.checkout
    to: demo.legacy_scoring
"""

FINDING = {
    "rule_id": "SEAF-004",
    "artifact": "model/integrations.yaml",
    "entity_id": "demo.checkout_to_legacy_scoring",
    "location": "/seaf.app.integrations/demo.checkout_to_legacy_scoring/to",
}


def _write_fixture(root: Path, components_yaml: str) -> None:
    (root / "model").mkdir(parents=True, exist_ok=True)
    (root / "model" / "integrations.yaml").write_text(INTEGRATIONS_YAML, encoding="utf-8")
    (root / "model" / "components.yaml").write_text(components_yaml, encoding="utf-8")


# --- tools.remediation.propose_remediation -----------------------------------


def test_propose_remediation_reroutes_to_declared_successor(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.scoring_v2
  demo.scoring_v2:
    owner: Team
    criticality: high
    target_status: strategic
""",
    )
    patch = propose_remediation(FINDING, tmp_path)
    assert patch.mutation_kind == "reroute_target"
    assert patch.replacement_component == "demo.scoring_v2"
    assert patch.eliminated_component == "demo.legacy_scoring"
    # The patch must touch exactly one line: only the flagged endpoint value.
    before_lines = patch.before_text.splitlines()
    after_lines = patch.after_text.splitlines()
    assert len(before_lines) == len(after_lines)
    changed = [i for i, (b, a) in enumerate(zip(before_lines, after_lines)) if b != a]
    assert len(changed) == 1
    assert after_lines[changed[0]].strip() == "to: demo.scoring_v2"
    assert before_lines[changed[0]].strip() == "to: demo.legacy_scoring"
    assert patch.before_sha256 == hashlib.sha256(
        patch.before_text.encode("utf-8")
    ).hexdigest()
    assert patch.after_sha256 == hashlib.sha256(
        patch.after_text.encode("utf-8")
    ).hexdigest()
    assert patch.diff_sha256 == hashlib.sha256(
        patch.unified_diff().encode("utf-8")
    ).hexdigest()
    expected_candidate_sha256 = hashlib.sha256(
        json.dumps(
            patch.candidate_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert patch.candidate_sha256() == expected_candidate_sha256
    assert patch.as_dict() == {
        **patch.candidate_dict(),
        "diff": patch.unified_diff(),
    }


def test_propose_remediation_refuses_without_declared_successor(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
""",
    )
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(FINDING, tmp_path)
    assert excinfo.value.code == "no_declared_successor"


def test_propose_remediation_refuses_when_successor_is_undefined(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.ghost
""",
    )
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(FINDING, tmp_path)
    assert excinfo.value.code == "successor_not_found"


def test_propose_remediation_refuses_when_successor_is_also_eliminated(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.also_retiring
  demo.also_retiring:
    owner: Team
    criticality: high
    target_status: eliminate
""",
    )
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(FINDING, tmp_path)
    assert excinfo.value.code == "successor_also_eliminated"


def test_propose_remediation_refuses_successor_without_safe_explicit_status(
    tmp_path: Path,
) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.scoring_v2
  demo.scoring_v2:
    owner: Team
    criticality: high
""",
    )
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(FINDING, tmp_path)
    assert excinfo.value.code == "successor_status_invalid"


def test_propose_remediation_refuses_invalid_successor_component_id(
    tmp_path: Path,
) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
    replaced_by: ../unsafe
""",
    )
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(FINDING, tmp_path)
    assert excinfo.value.code == "invalid_declared_successor"


def test_propose_remediation_refuses_unsupported_rule(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.scoring_v2
  demo.scoring_v2:
    owner: Team
    criticality: high
    target_status: strategic
""",
    )
    other_rule_finding = dict(FINDING, rule_id="PRIN-006")
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(other_rule_finding, tmp_path)
    assert excinfo.value.code == "unsupported_rule"


def test_propose_remediation_refuses_unknown_flow(tmp_path: Path) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.scoring_v2
  demo.scoring_v2:
    owner: Team
    criticality: high
    target_status: strategic
""",
    )
    missing_flow_finding = dict(
        FINDING,
        entity_id="demo.nonexistent_flow",
        location="/seaf.app.integrations/demo.nonexistent_flow/to",
    )
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(missing_flow_finding, tmp_path)
    assert excinfo.value.code == "entity_not_found"


def test_propose_remediation_refuses_noncanonical_finding_location(
    tmp_path: Path,
) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: eliminate
    replaced_by: demo.scoring_v2
  demo.scoring_v2:
    owner: Team
    criticality: high
    target_status: strategic
""",
    )
    finding = dict(
        FINDING,
        location="/seaf.app.integrations/another.integration/to",
    )
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(finding, tmp_path)
    assert excinfo.value.code == "unsupported_location"


def test_propose_remediation_refuses_when_target_is_not_actually_eliminated(
    tmp_path: Path,
) -> None:
    _write_fixture(
        tmp_path,
        """components:
  demo.checkout:
    owner: Team
    criticality: high
    target_status: strategic
  demo.legacy_scoring:
    owner: Team
    criticality: high
    target_status: strategic
""",
    )
    with pytest.raises(RemediationNotAvailable) as excinfo:
        propose_remediation(FINDING, tmp_path)
    assert excinfo.value.code == "precondition_failed"


# --- scripts.run_remediation.run_case (end-to-end gate) -----------------------


def test_run_case_gate_passes_and_closes_the_finding() -> None:
    result, exit_code = run_case(open_draft_pr=False)
    assert exit_code == 0
    assert result["status"] == "remediation_ready"
    assert result["gate"]["target_finding_closed"] is True
    assert result["gate"]["new_findings"] == []
    assert result["remaining_deterministic_findings"] == []
    # Safety invariants must hold regardless of gate outcome.
    assert result["hitl_required"] is True
    assert result["auto_merge"] is False


def test_run_case_pr_body_declares_draft_and_no_auto_merge() -> None:
    result, _ = run_case(open_draft_pr=False)
    assert "auto-merge is disabled" in result["pr_body"]
    assert "human architect must review and merge" in result["pr_body"]
    assert "SEAF-004" in result["pr_body"]


def test_run_case_open_draft_pr_never_produces_a_live_url_or_side_effects() -> None:
    result, exit_code = run_case(open_draft_pr=True)
    assert exit_code == 0
    publication = result["publication"]
    assert publication["external_side_effects"] is False
    assert publication["draft_pr_url"] is None
    assert publication["status"] == "dry_run"


def test_publisher_used_by_remediation_can_never_merge_or_push() -> None:
    # Whatever publisher scripts.run_remediation ends up configured with, the
    # merge/approve/push_to_main boundary must reject those actions -- this is
    # the same object exercised by --open-draft-pr above.
    from tools.publisher import default_publisher

    publisher = default_publisher()
    with pytest.raises(PublisherPolicyError):
        publisher.merge()
    with pytest.raises(PublisherPolicyError):
        publisher.approve()
    with pytest.raises(PublisherPolicyError):
        publisher.push_to_main()
