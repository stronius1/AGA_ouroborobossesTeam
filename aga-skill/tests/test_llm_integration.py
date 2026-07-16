# -*- coding: utf-8 -*-
"""Integration contracts for the optional, offline LLM review branch."""
from __future__ import annotations

import inspect
import shutil
import sys
from pathlib import Path

import yaml

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from scripts.run_review import _log_result, execute_review  # noqa: E402
from tools.aga import ManifestChangedFilesProvider, review_pr  # noqa: E402
from tools.feedback import read_jsonl  # noqa: E402
from tools.llm import FixtureLLMAdapter, merge_findings  # noqa: E402


FLOW = """---
kind: integration_flow
id: IF-9998
source: AS-0005
target: AS-0006
pattern: mq
zone: internal
data_categories: []
approvals: []
---
# Synthetic flow
"""


def _pr(tmp_path: Path, *, pattern: str = "mq") -> Path:
    pr = tmp_path / "pr"
    artifact = pr / "files" / "flows" / "IF-9998.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(FLOW.replace("pattern: mq", f"pattern: {pattern}"), encoding="utf-8")
    (pr / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "pr-llm-integration",
                "title": "LLM integration fixture",
                "changed_files": ["flows/IF-9998.md"],
                "context_files": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return pr


def _rules(
    tmp_path: Path,
    *,
    custom_source: str | None = None,
    hybrid: bool = False,
    prin_005_severity: str | None = None,
) -> Path:
    rules = tmp_path / "rules"
    shutil.copytree(PKG_ROOT / "rules", rules)
    path = rules / "principles.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for rule in document["rules"]:
        if custom_source is not None and rule["id"] == "PRIN-005":
            rule["source_ref"] = custom_source
        if prin_005_severity is not None and rule["id"] == "PRIN-005":
            rule["severity"] = prin_005_severity
        if hybrid and rule["id"] == "PRIN-002":
            rule["check_type"] = "hybrid"
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return rules


def _finding(rule_id: str, source_ref: str, *, severity: str = "major",
             location: str = "body:1", confidence: float = 0.95,
             artifact: str = "flows/IF-9998.md") -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "confidence": confidence,
        "artifact": artifact,
        "location": location,
        "evidence": "semantic issue found in the fixture",
        "source_ref": source_ref,
        "suggested_fix": "update the architecture description",
    }


def test_llm_branch_uses_the_same_custom_rules_for_prompt_and_validation(tmp_path: Path) -> None:
    custom_source = "CUSTOM-POLICY section 3.4"
    rules = _rules(tmp_path, custom_source=custom_source)
    adapter = FixtureLLMAdapter({"findings": [_finding("PRIN-005", custom_source)]})
    result = execute_review(
        _pr(tmp_path),
        rules_dir=rules,
        mode="llm",
        adapter=adapter,
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["analysis_errors"] == []
    assert [finding["rule_id"] for finding in result["findings"]] == ["PRIN-005"]
    assert result["findings"][0]["artifact_role"] == "changed"
    assert len(result["findings"][0]["artifact_sha256"]) == 64
    assert result["llm_result_classification"] == "synthetic_fixture_non_release"
    assert result["llm_release_evidence"] is False
    assert custom_source in adapter.calls[0].system_instruction


def test_llm_rule_scope_and_trusted_severity_are_enforced(tmp_path: Path) -> None:
    rules = _rules(tmp_path)
    for finding in (
        _finding("PRIN-004", "aga-skill/rules/principles.yaml#/rules/3"),
        _finding("PRIN-005", "aga-skill/rules/principles.yaml#/rules/4", severity="minor"),
    ):
        result = execute_review(
            _pr(tmp_path),
            rules_dir=rules,
            mode="llm",
            adapter=FixtureLLMAdapter({"findings": [finding]}),
            changed_files_provider=ManifestChangedFilesProvider(),
        )
        assert result["verdict"] == "incomplete"
        assert result["analysis_errors"][0]["code"] == "LLMSchemaError"


def test_execute_review_deduplicates_same_hybrid_defect(tmp_path: Path) -> None:
    rules = _rules(tmp_path, hybrid=True)
    source_ref = "aga-skill/rules/principles.yaml#/rules/1"
    duplicate = _finding(
        "PRIN-002", source_ref, location="frontmatter: pattern")
    result = execute_review(
        _pr(tmp_path, pattern="file"),
        rules_dir=rules,
        mode="llm",
        adapter=FixtureLLMAdapter({"findings": [duplicate]}),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    matching = [finding for finding in result["findings"] if finding["rule_id"] == "PRIN-002"]
    assert len(matching) == 1
    assert matching[0]["execution_mode"] == "deterministic"


def test_merge_keeps_independent_locations_for_the_same_rule_and_artifact() -> None:
    first = _finding("PRIN-005", "policy", location="body:10")
    second = _finding("PRIN-005", "policy", location="body:20")
    assert len(merge_findings([first], [second])) == 2


def test_low_confidence_major_is_machine_readable_incomplete_hitl(tmp_path: Path) -> None:
    rules = _rules(tmp_path)
    source_ref = "aga-skill/rules/principles.yaml#/rules/4"
    result = execute_review(
        _pr(tmp_path),
        rules_dir=rules,
        mode="llm",
        adapter=FixtureLLMAdapter({"findings": [
            _finding("PRIN-005", source_ref, confidence=0.20)
        ]}),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["verdict"] == "incomplete"
    assert result["incomplete"] is True
    assert result["escalate"] is True
    assert result["hitl_required"] is True
    assert result["analysis_errors"][0]["code"] == "llm_low_confidence"
    assert result["hitl_reasons"] == result["analysis_errors"][0]["signals"]
    assert result["hitl_reasons"][0]["trusted_severity"] == "major"
    assert result["findings"] == []
    assert result["observations"][0]["original_severity"] == "major"


def test_low_confidence_trusted_blocker_is_incomplete_after_downgrade(tmp_path: Path) -> None:
    rules = _rules(tmp_path, prin_005_severity="blocker")
    source_ref = "aga-skill/rules/principles.yaml#/rules/4"
    result = execute_review(
        _pr(tmp_path),
        rules_dir=rules,
        mode="llm",
        adapter=FixtureLLMAdapter({"findings": [
            _finding(
                "PRIN-005", source_ref, severity="blocker", confidence=0.60
            )
        ]}),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["verdict"] == "incomplete"
    assert result["hitl_required"] is True
    assert result["findings"][0]["severity"] == "major"
    assert result["findings"][0]["original_severity"] == "blocker"
    assert result["hitl_reasons"][0]["trusted_severity"] == "blocker"
    assert result["hitl_reasons"][0]["required_confidence"] == 0.70


def test_llm_finding_cannot_target_context_only_artifact(tmp_path: Path) -> None:
    rules = _rules(tmp_path)
    pr = _pr(tmp_path)
    context_relative = "flows/IF-9997.md"
    context = pr / "files" / context_relative
    context.write_text(FLOW.replace("IF-9998", "IF-9997"), encoding="utf-8")
    manifest_path = pr / "meta.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["context_files"] = [context_relative]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    result = execute_review(
        pr,
        rules_dir=rules,
        mode="llm",
        adapter=FixtureLLMAdapter({"findings": [
            _finding(
                "PRIN-005", "aga-skill/rules/principles.yaml#/rules/4",
                artifact=context_relative,
            )
        ]}),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["verdict"] == "incomplete"
    assert result["analysis_errors"][0]["code"] == "LLMSchemaError"
    assert "not context" in result["analysis_errors"][0]["message"]


def test_llm_location_must_resolve_in_changed_artifact(tmp_path: Path) -> None:
    rules = _rules(tmp_path)
    result = execute_review(
        _pr(tmp_path),
        rules_dir=rules,
        mode="llm",
        adapter=FixtureLLMAdapter({"findings": [
            _finding(
                "PRIN-005", "aga-skill/rules/principles.yaml#/rules/4",
                location="body:999",
            )
        ]}),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["verdict"] == "incomplete"
    assert result["analysis_errors"][0]["code"] == "LLMSchemaError"
    assert "does not resolve" in result["analysis_errors"][0]["message"]


def test_arbitrary_adapter_error_fails_closed_as_transport_error(tmp_path: Path) -> None:
    class BrokenAdapter:
        requires_network = False

        def complete(self, _request):
            raise RuntimeError("synthetic adapter failure")

    result = execute_review(
        _pr(tmp_path),
        rules_dir=_rules(tmp_path),
        mode="llm",
        adapter=BrokenAdapter(),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["verdict"] == "incomplete"
    assert result["hitl_required"] is True
    assert result["analysis_errors"][0]["code"] == "LLMTransportError"


def test_deep_mapping_adapter_response_is_incomplete_hitl(tmp_path: Path) -> None:
    response: dict[str, object] = {}
    cursor = response
    for _ in range(10_000):
        nested: dict[str, object] = {}
        cursor["nested"] = nested
        cursor = nested
    result = execute_review(
        _pr(tmp_path),
        rules_dir=_rules(tmp_path),
        mode="llm",
        adapter=FixtureLLMAdapter(response),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["verdict"] == "incomplete"
    assert result["incomplete"] is True
    assert result["hitl_required"] is True
    assert result["analysis_errors"][0]["code"] == "LLMSchemaError"
    assert "nesting limit" in result["analysis_errors"][0]["message"]


def test_deep_json_text_adapter_response_is_incomplete_hitl(tmp_path: Path) -> None:
    deeply_nested_json = "[" * 10_000 + "0" + "]" * 10_000
    result = execute_review(
        _pr(tmp_path),
        rules_dir=_rules(tmp_path),
        mode="llm",
        adapter=FixtureLLMAdapter(deeply_nested_json),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["verdict"] == "incomplete"
    assert result["incomplete"] is True
    assert result["hitl_required"] is True
    assert result["analysis_errors"][0]["code"] == "LLMInvalidJSONError"
    assert "nesting limit" in result["analysis_errors"][0]["message"]


def test_artifact_change_during_adapter_call_fails_closed(tmp_path: Path) -> None:
    pr = _pr(tmp_path)
    artifact = pr / "files" / "flows" / "IF-9998.md"

    class MutatingAdapter:
        requires_network = False

        def complete(self, _request):
            artifact.write_text(FLOW + "\n# Mutated after request snapshot\n", encoding="utf-8")
            return {"findings": [
                _finding(
                    "PRIN-005", "aga-skill/rules/principles.yaml#/rules/4"
                )
            ]}

    result = execute_review(
        pr,
        rules_dir=_rules(tmp_path),
        mode="llm",
        adapter=MutatingAdapter(),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    assert result["verdict"] == "incomplete"
    assert result["hitl_required"] is True
    assert result["analysis_errors"][0]["code"] == "LLMSchemaError"
    assert "snapshot changed" in result["analysis_errors"][0]["message"]


def test_deterministic_review_entry_point_has_no_llm_injection_parameters() -> None:
    parameters = inspect.signature(review_pr).parameters
    assert "llm_findings" not in parameters
    assert "require_llm" not in parameters


def test_synthetic_fixture_marker_is_preserved_in_audit_log(tmp_path: Path) -> None:
    rules = _rules(tmp_path)
    pr = _pr(tmp_path)
    result = execute_review(
        pr,
        rules_dir=rules,
        mode="llm",
        adapter=FixtureLLMAdapter({"findings": []}),
        changed_files_provider=ManifestChangedFilesProvider(),
    )
    log = tmp_path / "reviews.jsonl"
    _log_result(result, pr, "2.0.0", log)
    event = read_jsonl(log)[0]
    assert event["llm_result_classification"] == "synthetic_fixture_non_release"
    assert event["llm_release_evidence"] is False
