# -*- coding: utf-8 -*-
"""Direct contract tests for tools.validation (no tools.aga dependency)."""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from tools.validation import (  # noqa: E402
    ValidationError,
    condition_matches,
    load_corpus,
    load_manifest,
    load_permissions,
    load_precedent,
    load_seaf_document,
    load_severity_policy,
    parse_frontmatter_strict,
    safe_artifact_path,
    safe_read_artifact,
    safe_read_bytes,
    strict_load_yaml,
    strict_load_yaml_text,
    validate_corpus,
    validate_exception,
    validate_exception_condition,
    validate_frontmatter,
    validate_manifest,
    validate_permissions,
    validate_rules_directory,
    validate_rules_document,
    validate_seaf,
    validate_severity_policy,
)


def _error(code: str):
    return pytest.raises(ValidationError, match=rf"\[{code}\]")


def _flow(**changes):
    value = {
        "kind": "integration_flow",
        "id": "IF-0001",
        "source": "AS-0001",
        "target": "AS-0002",
        "pattern": "mq",
        "zone": "internal",
        "data_categories": [],
        "approvals": [],
    }
    value.update(changes)
    return value


def _rule(rule_id="TEST-001", **changes):
    value = {
        "id": rule_id,
        "title": "Required owner",
        "statement": "Owner is required.",
        "severity": "major",
        "scope": ["system_passport"],
        "check_type": "deterministic",
        "detect": {"field_required": "owner"},
        "source_ref": "POLICY §1",
        "exceptions": [],
        "provenance": {"origin": "seed", "added_in": "1.0.0"},
        "status": "active",
    }
    value.update(changes)
    return value


def _rules(*rules):
    return {"schema": "aga.rules/v1", "domain": "principles", "rules": list(rules)}


def test_validation_error_is_typed_and_serialisable():
    error = ValidationError("bad input", path="meta.yaml", field="changed_files", code="invalid_type")
    assert error.path == "meta.yaml"
    assert error.field == "changed_files"
    assert error.code == "invalid_type"
    assert error.as_dict() == {
        "type": "input_error",
        "code": "invalid_type",
        "message": "bad input",
        "path": "meta.yaml",
        "field": "changed_files",
    }


@pytest.mark.parametrize(
    "yaml_text",
    [
        "cases: []\ncases: []\n",
        "outer:\n  key: one\n  key: two\n",
        "base: &base {key: one}\nmerged: {<<: *base, key: two}\n",
    ],
)
def test_duplicate_yaml_key_rejected(yaml_text):
    with _error("yaml_duplicate_key") as caught:
        strict_load_yaml_text(yaml_text, source="corpus.yaml")
    assert caught.value.path == "corpus.yaml"
    assert caught.value.field in {"cases", "key"}


def test_yaml_scalar_where_mapping_expected_rejected():
    with _error("yaml_root_type") as caught:
        strict_load_yaml_text("scalar\n", source="meta.yaml", expected_type=dict)
    assert caught.value.field == "$"


def test_malformed_yaml_is_not_empty_mapping():
    with _error("yaml_parse_error"):
        strict_load_yaml_text("a: [unterminated", source="meta.yaml")


def test_yaml_alias_limit():
    content = "base: &base [one]\na: *base\nb: *base\n"
    with _error("yaml_alias_limit"):
        strict_load_yaml_text(content, max_aliases=1)


def test_yaml_depth_and_recursive_alias_limits():
    with _error("yaml_depth_limit"):
        strict_load_yaml_text("a:\n  b:\n    c: 1\n", max_depth=2)
    with _error("yaml_recursive_alias"):
        strict_load_yaml_text("a: &a [*a]\n")


def test_alias_dag_depth_is_checked_without_expansion():
    lines = ["a0: &a0 [value]"]
    lines.extend(f"a{i}: &a{i} [*a{i - 1}, *a{i - 1}]" for i in range(1, 12))
    with _error("yaml_depth_limit"):
        strict_load_yaml_text("\n".join(lines), max_depth=8, max_aliases=30)


def test_oversized_yaml_rejected_before_parse(tmp_path):
    path = tmp_path / "large.yaml"
    path.write_text("key: " + "x" * 100, encoding="utf-8")
    with _error("file_too_large"):
        strict_load_yaml(path, max_bytes=32)


def test_changed_files_string_rejected():
    with _error("invalid_type") as caught:
        validate_manifest(
            {"id": "pr-1", "title": "test", "changed_files": "flows/a.md", "context_files": []}
        )
    assert caught.value.field == "changed_files"


def test_manifest_paths_are_normalised_and_deduplicated():
    manifest = validate_manifest(
        {
            "id": "pr-1",
            "title": "test",
            "changed_files": ["flows/a.md", "flows/a.md"],
            "context_files": ["flows/a.md", "diagrams/a.puml", "diagrams/a.puml"],
        }
    )
    assert manifest["changed_files"] == ["flows/a.md"]
    assert manifest["context_files"] == ["diagrams/a.puml"]


@pytest.mark.parametrize(
    ("artifact", "code"),
    [("/etc/passwd", "path_absolute"), ("../outside.md", "path_traversal")],
)
def test_untrusted_manifest_path_rejected(artifact, code):
    with _error(code):
        validate_manifest(
            {"id": "pr-1", "title": "test", "changed_files": [artifact], "context_files": []}
        )


def test_safe_artifact_path_accepts_regular_contained_file(tmp_path):
    root = tmp_path / "files"
    path = root / "flows" / "IF-0001.md"
    path.parent.mkdir(parents=True)
    path.write_text("safe", encoding="utf-8")
    assert safe_artifact_path(root, "flows/IF-0001.md") == path.resolve()
    assert safe_read_artifact(root, "flows/IF-0001.md") == "safe"


def test_absolute_changed_file_and_parent_traversal_rejected(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    with _error("path_absolute"):
        safe_artifact_path(root, str((tmp_path / "outside.md").resolve()))
    with _error("path_traversal"):
        safe_artifact_path(root, "../outside.md")


def test_symlink_artifact_and_symlink_parent_rejected(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (root / "link.md").symlink_to(outside)
    with _error("path_symlink"):
        safe_read_artifact(root, "link.md")

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "nested.md").write_text("secret", encoding="utf-8")
    (root / "linked-directory").symlink_to(outside_dir, target_is_directory=True)
    with _error("path_symlink"):
        safe_read_artifact(root, "linked-directory/nested.md")


def test_exact_byte_reader_rejects_symlinked_root(tmp_path):
    outside = tmp_path / "outside-root"
    outside.mkdir()
    (outside / "artifact.yaml").write_bytes(b"safe: true\n")
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(outside, target_is_directory=True)

    with _error("path_root_invalid"):
        safe_read_bytes(linked_root, "artifact.yaml")


def test_hardlink_escape_rejected(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    os.link(outside, root / "hardlink.md")
    with _error("path_hardlink"):
        safe_read_artifact(root, "hardlink.md")


def test_extension_non_regular_and_size_rejected(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    (root / "script.py").write_text("pass", encoding="utf-8")
    with _error("path_extension"):
        safe_artifact_path(root, "script.py")
    (root / "directory.md").mkdir()
    with _error("path_not_regular"):
        safe_artifact_path(root, "directory.md")
    (root / "large.md").write_text("x" * 20, encoding="utf-8")
    with _error("path_too_large"):
        safe_artifact_path(root, "large.md", max_bytes=10)


def test_unknown_kind_and_kind_opt_out_fail_closed():
    with _error("invalid_enum"):
        validate_frontmatter(_flow(kind="skip_all"), artifact_path="flows/IF-0001.md")
    with _error("kind_path_mismatch"):
        validate_frontmatter(_flow(kind="out_of_scope"), artifact_path="flows/IF-0001.md")


@pytest.mark.parametrize("missing", ["source", "target"])
def test_missing_flow_endpoint_fails_closed(missing):
    data = _flow()
    del data[missing]
    with _error("required_field") as caught:
        validate_frontmatter(data, artifact_path="flows/IF-0001.md")
    assert caught.value.field == missing


def test_frontmatter_parser_propagates_yaml_error_and_duplicates():
    with _error("yaml_duplicate_key"):
        parse_frontmatter_strict("---\nkind: adr\nkind: out_of_scope\n---\nbody")
    with _error("frontmatter_missing"):
        parse_frontmatter_strict("body only")


def test_valid_flow_frontmatter_schema():
    data = _flow(
        transfer_mode="batch",
        gateway_controlled=True,
        approvals=["security"],
    )
    assert validate_frontmatter(data, artifact_path="flows/IF-0001.md") == data


def test_exception_all_any_nested_and_contains_order_independent():
    condition = validate_exception_condition(
        {
            "all": [
                {"field": "zone", "equals": "dmz"},
                {"field": "approvals", "contains": ["dpo", "security"]},
                {"field": "security.gateway.controlled", "equals": True},
                {"any": [{"field": "mode", "in": ["batch", "streaming"]}]},
            ]
        }
    )
    data = {
        "zone": "dmz",
        "approvals": ["security", "dpo"],
        "security": {"gateway": {"controlled": True}},
        "mode": "batch",
    }
    assert condition_matches(condition, data)
    data["approvals"] = ["dpo", "security"]
    assert condition_matches(condition, data)


@pytest.mark.parametrize(
    "condition",
    [{}, {"all": []}, {"field": "zone"}, {"field": "zone", "equals": "dmz", "in": []}],
)
def test_malformed_exception_rejected(condition):
    with _error("invalid_condition"):
        validate_exception_condition(condition)


def test_tautological_exception_requires_waiver_and_positive_cases():
    exception = {
        "id": "EXC-TEST-001-001",
        "when": {"field": "pattern", "equals": "file"},
        "rationale": "disable",
        "provenance": "precedent:0001",
        "added_in": "1.1.0",
    }
    with _error("tautological_exception"):
        validate_exception(exception, detect={"field": "pattern", "banned": ["file"]})
    exception["committee_waiver"] = "committee:42"
    exception["positive_regression_cases"] = ["pr-16"]
    assert validate_exception(exception, detect={"field": "pattern", "banned": ["file"]})


def test_rules_reject_duplicate_ids_and_unknown_detector():
    with _error("duplicate_id"):
        validate_rules_document(_rules(_rule(), _rule()))
    with _error("unknown_detect_operator"):
        validate_rules_document(_rules(_rule(detect={"run_shell": True})))


@pytest.mark.parametrize("missing", ["source_ref", "provenance"])
def test_active_rule_requires_source_and_provenance(missing):
    rule = _rule()
    del rule[missing]
    with _error("required_field"):
        validate_rules_document(_rules(rule))


def test_seaf_validator_normalises_infra_and_rejects_duplicate_ids():
    system = {
        "id": "AS-0001",
        "name": "One",
        "owner": "Team",
        "criticality": "office",
        "target_status": "invest",
        "domain": "test",
    }
    document = {"schema": "aga.seaf-fixture/v1", "version": "1", "systems": [system]}
    assert validate_seaf(document)["systems"][0]["infra"] is False
    duplicate = copy.deepcopy(document)
    duplicate["systems"].append(copy.deepcopy(system))
    with _error("duplicate_id"):
        validate_seaf(duplicate)


def test_severity_policy_enforces_no_auto_merge():
    policy = load_severity_policy(PKG_ROOT / "rules" / "severity-policy.yaml")
    unsafe = copy.deepcopy(policy)
    unsafe["autonomy"]["auto_merge"] = True
    with _error("policy_invariant"):
        validate_severity_policy(unsafe)


def test_corpus_minimum_duplicate_and_expected_schema():
    corpus = load_corpus(PKG_ROOT / "golden" / "corpus.yaml", minimum_cases=15)
    with _error("corpus_too_small"):
        validate_corpus({"schema": "aga.golden-corpus/v1", "cases": []})
    duplicate = copy.deepcopy(corpus)
    duplicate["cases"].append(copy.deepcopy(duplicate["cases"][0]))
    with _error("duplicate_id"):
        validate_corpus(duplicate)


def test_precedents_and_permissions_in_repository_validate():
    for precedent in sorted((PKG_ROOT / "precedents" / "cases").glob("*.md")):
        metadata, body = load_precedent(precedent)
        assert metadata["id"]
        assert body.startswith("#")
    permissions = load_permissions(PKG_ROOT / "evolver" / "permissions.yaml")
    assert "merge" in permissions["deny"]["actions"]


def test_permissions_require_protected_denies():
    permissions = load_permissions(PKG_ROOT / "evolver" / "permissions.yaml")
    unsafe = copy.deepcopy(permissions)
    unsafe["deny"]["actions"].remove("merge")
    with _error("policy_invariant"):
        validate_permissions(unsafe)


def test_repository_validation_documents_pass():
    rules, policy = validate_rules_directory(PKG_ROOT / "rules")
    assert len(rules) >= 24
    assert policy["autonomy"]["auto_merge"] is False
    assert len(load_seaf_document(PKG_ROOT / "fixtures" / "seaf.yaml")["systems"]) == 15
    assert len(load_corpus(PKG_ROOT / "golden" / "corpus.yaml", minimum_cases=15)["cases"]) >= 15
    for manifest in sorted((PKG_ROOT / "golden" / "prs").glob("*/meta.yaml")):
        assert load_manifest(manifest)["id"] == manifest.parent.name
