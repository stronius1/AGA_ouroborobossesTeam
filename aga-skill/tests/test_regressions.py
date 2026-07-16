# -*- coding: utf-8 -*-
"""Parser, graph, rules-engine and exception regression contracts.

Repository configuration is copied before every mutation; PR artifacts are
created only below ``tmp_path`` and no test uses the network.
"""
from __future__ import annotations

import copy
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from tools.aga import (  # noqa: E402
    ManifestChangedFilesProvider,
    condition_matches,
    effective_edges,
    load_rules,
    parse_diagram,
    review_pr,
)
from tools.validation import ValidationError  # noqa: E402


@pytest.fixture
def isolated_config(tmp_path: Path) -> tuple[Path, Path]:
    rules = tmp_path / "rules"
    shutil.copytree(PKG_ROOT / "rules", rules)
    seaf = tmp_path / "seaf.yaml"
    shutil.copy2(PKG_ROOT / "fixtures" / "seaf.yaml", seaf)
    return rules, seaf


def _flow_text(**overrides: Any) -> str:
    metadata: dict[str, Any] = {
        "kind": "integration_flow",
        "id": "IF-9998",
        "source": "AS-0006",
        "target": "AS-0013",
        "pattern": "file",
        "zone": "dmz",
        "transfer_mode": "interactive",
        "gateway_controlled": False,
        "data_categories": ["documents"],
        "approvals": [],
    }
    metadata.update(overrides)
    return "---\n" + yaml.safe_dump(
        metadata, allow_unicode=True, sort_keys=False
    ) + "---\n# Synthetic flow\n"


def _markdown_artifact(metadata: Mapping[str, Any], body: str = "# Synthetic artifact\n") -> str:
    return "---\n" + yaml.safe_dump(
        dict(metadata), allow_unicode=True, sort_keys=False
    ) + "---\n" + body


def _write_pr(
    root: Path,
    *,
    changed: list[str],
    files: Mapping[str, str],
    context: list[str] | None = None,
) -> Path:
    pr = root / "pr"
    (pr / "files").mkdir(parents=True)
    manifest = {
        "id": "pr-regression",
        "title": "Synthetic regression fixture",
        "changed_files": changed,
        "context_files": context or [],
    }
    (pr / "meta.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for relative, content in files.items():
        artifact = pr / "files" / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(content, encoding="utf-8")
    return pr


def _review(pr: Path, config: tuple[Path, Path], **kwargs: Any) -> dict[str, Any]:
    rules, seaf = config
    kwargs.setdefault("changed_files_provider", ManifestChangedFilesProvider())
    return review_pr(pr, rules_dir=rules, seaf_path=seaf, **kwargs)


def _mutate_rule(
    rules_dir: Path,
    rule_id: str,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    for path in sorted(rules_dir.glob("*.yaml")):
        if path.name == "severity-policy.yaml":
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for rule in document.get("rules", []):
            if rule.get("id") == rule_id:
                mutation(rule)
                path.write_text(
                    yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
                return
    raise AssertionError(f"rule not found in fixture: {rule_id}")


def _append_rule(rules_dir: Path, rule: Mapping[str, Any]) -> None:
    path = rules_dir / "principles.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["rules"].append(dict(rule))
    path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _test_rule(
    *,
    rule_id: str = "TEST-901",
    status: str = "active",
    scope: list[str] | None = None,
    check_type: str = "deterministic",
    detect: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rule = {
        "id": rule_id,
        "title": "Synthetic configurable rule",
        "statement": "Synthetic rule for dispatcher contract tests.",
        "severity": "major",
        "scope": scope or ["integration_flow"],
        "check_type": check_type,
        "source_ref": "TEST-POLICY §1",
        "exceptions": [],
        "provenance": {"origin": "seed", "added_in": "1.0.0"},
        "status": status,
    }
    if detect is not None:
        rule["detect"] = dict(detect)
    return rule


def test_puml_note_content_and_skinparam_do_not_create_edges() -> None:
    diagram = parse_diagram(
        """@startuml
' c4: context
skinparam componentStyle rectangle
rectangle "AS-0001" as A
rectangle "AS-0002" as B
note right of A
  Fake --> Ghost : prose only
end note
skinparam ArrowColor red
A --> B : IF-0001
@enduml
""",
        ".puml",
    )
    assert diagram is not None
    assert diagram["nodes"] == {"A": "AS-0001", "B": "AS-0002"}
    assert diagram["edges"] == [("A", "B", "IF-0001")]


def test_puml_single_line_note_does_not_hide_following_edge() -> None:
    diagram = parse_diagram(
        """@startuml
rectangle "AS-0001" as A
rectangle "AS-0002" as B
note right of A: Fake --> Ghost is prose
A --> B : real
@enduml
""",
        ".puml",
    )
    assert diagram is not None
    assert diagram["edges"] == [("A", "B", "real")]


def test_mermaid_standalone_nodes_are_parsed() -> None:
    diagram = parse_diagram(
        """flowchart LR
%% c4: context
A[AS-0001]
B(AS-0002)
C{AS-0003}
""",
        ".mmd",
    )
    assert diagram is not None
    assert diagram["nodes"] == {
        "A": "AS-0001",
        "B": "AS-0002",
        "C": "AS-0003",
    }
    assert diagram["edges"] == []


def test_mermaid_chained_edges_are_all_parsed() -> None:
    diagram = parse_diagram(
        "flowchart LR\nA[AS-0001] -->|one| B(AS-0002) --> C{AS-0003}\n",
        ".mmd",
    )
    assert diagram is not None
    assert diagram["edges"] == [("A", "B", "one"), ("B", "C", "")]


def test_mermaid_arrow_variants_and_labels() -> None:
    diagram = parse_diagram(
        """flowchart LR
A[AS-0001] -->|sync| B(AS-0002)
B -.->|async| C{AS-0003}
C ==>|batch| D[AS-0004]
""",
        ".mmd",
    )
    assert diagram is not None
    assert diagram["edges"] == [
        ("A", "B", "sync"),
        ("B", "C", "async"),
        ("C", "D", "batch"),
    ]


def test_nonempty_unparsed_diagram_fails_closed_in_review(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    text = "@startuml\nskinparam componentStyle rectangle\n@enduml\n"
    assert parse_diagram(text, ".puml") is None
    pr = _write_pr(
        tmp_path,
        changed=["diagrams/empty.puml"],
        files={"diagrams/empty.puml": text},
    )
    result = _review(pr, isolated_config)
    assert result["input_errors"] == []
    assert [(item["rule_id"], item["severity"]) for item in result["findings"]] == [
        ("DIAG-001", "major")
    ]
    assert result["verdict"] == "request_changes_escalate"


def _long_infrastructure_graph(
    *,
    length: int = 50,
    with_target: bool = True,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    nodes = {"source": "AS-0001", "target": "AS-0002"}
    seaf: dict[str, dict[str, Any]] = {
        "AS-0001": {"infra": False},
        "AS-0002": {"infra": False},
    }
    edges: list[tuple[str, str, str]] = []
    previous = "source"
    for index in range(length):
        alias = f"infra_{index}"
        code = f"AS-{index + 100:04d}"
        nodes[alias] = code
        seaf[code] = {"infra": True}
        edges.append((previous, alias, ""))
        previous = alias
    if with_target:
        edges.append((previous, "target", ""))
    return {"nodes": nodes, "edges": edges}, seaf


def test_effective_edges_cross_fifty_infrastructure_nodes() -> None:
    diagram, seaf = _long_infrastructure_graph()
    assert effective_edges(diagram, seaf) == {("AS-0001", "AS-0002")}


def test_effective_edges_infrastructure_cycle_terminates() -> None:
    diagram, seaf = _long_infrastructure_graph(with_target=False)
    diagram["edges"].append(("infra_49", "infra_0", ""))
    assert effective_edges(diagram, seaf) == set()


def test_missing_infra_flag_is_rejected() -> None:
    diagram = {
        "nodes": {"source": "AS-0001", "middle": "AS-0003", "target": "AS-0002"},
        "edges": [("source", "middle", ""), ("middle", "target", "")],
    }
    seaf = {
        "AS-0001": {"infra": False},
        "AS-0002": {"infra": False},
        "AS-0003": {},
    }
    with pytest.raises(ValidationError) as caught:
        effective_edges(diagram, seaf)
    assert caught.value.code == "schema_type"


def test_exception_all_contains_and_nested_field() -> None:
    condition = {
        "all": [
            {"field": "zone", "equals": "dmz"},
            {"field": "approvals", "contains": "security"},
            {"field": "controls.gateway.enabled", "equals": True},
            {"field": "transfer_mode", "in": ["batch", "streaming"]},
        ]
    }
    metadata = {
        "zone": "dmz",
        "approvals": ["dpo", "security"],
        "controls": {"gateway": {"enabled": True}},
        "transfer_mode": "batch",
    }
    assert condition_matches(condition, metadata)
    metadata["approvals"] = ["security", "dpo"]
    assert condition_matches(condition, metadata)
    metadata["controls"]["gateway"]["enabled"] = False
    assert not condition_matches(condition, metadata)


def test_malformed_exception_is_rejected_while_loading_rules(
    isolated_config: tuple[Path, Path],
) -> None:
    rules, _ = isolated_config

    def add_bad_exception(rule: dict[str, Any]) -> None:
        rule["exceptions"] = [{
            "id": "EXC-PRIN-002-999",
            "when": {"all": []},
            "rationale": "invalid empty condition",
            "provenance": "precedent:9999",
            "added_in": "1.1.0",
        }]

    _mutate_rule(rules, "PRIN-002", add_bad_exception)
    with pytest.raises(ValidationError) as caught:
        load_rules(rules)
    assert caught.value.code == "invalid_condition"


def test_uncontrolled_dmz_file_flow_is_not_suppressed_by_narrow_exception(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    rules, _ = isolated_config

    def add_narrow_exception(rule: dict[str, Any]) -> None:
        rule["exceptions"] = [{
            "id": "EXC-PRIN-002-001",
            "when": {"all": [
                {"field": "zone", "equals": "dmz"},
                {"field": "pattern", "equals": "file"},
                {"field": "transfer_mode", "equals": "batch"},
                {"field": "gateway_controlled", "equals": True},
                {"field": "approvals", "contains": "security"},
            ]},
            "rationale": "controlled batch transfer only",
            "provenance": "precedent:0001",
            "added_in": "1.1.0",
        }]

    _mutate_rule(rules, "PRIN-002", add_narrow_exception)
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text()},
    )
    result = _review(pr, isolated_config)
    assert [item["rule_id"] for item in result["findings"]].count("PRIN-002") == 1
    assert not any(item["rule_id"] == "PRIN-002" for item in result["suppressed_by_exception"])


def test_changed_files_are_deduplicated_before_dispatch(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md", "flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text()},
    )
    result = _review(pr, isolated_config)
    assert [item["rule_id"] for item in result["findings"]].count("PRIN-002") == 1


def test_changing_detect_changes_behavior_without_python_change(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    rules, _ = isolated_config
    _mutate_rule(
        rules,
        "PRIN-002",
        lambda rule: rule.update({"detect": {"field": "pattern", "banned": ["mq"]}}),
    )
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text(pattern="file")},
    )
    result = _review(pr, isolated_config)
    assert "PRIN-002" not in {item["rule_id"] for item in result["findings"]}


def test_rule_scope_is_enforced(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    rules, _ = isolated_config
    _append_rule(
        rules,
        _test_rule(scope=["adr"], detect={"field": "pattern", "banned": ["file"]}),
    )
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text()},
    )
    result = _review(pr, isolated_config)
    assert "TEST-901" not in {item["rule_id"] for item in result["findings"]}


def test_llm_rule_is_not_run_by_deterministic_dispatcher(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    rules, _ = isolated_config
    _append_rule(
        rules,
        _test_rule(
            check_type="llm",
            detect={"field": "pattern", "banned": ["file"]},
        ),
    )
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text()},
    )
    result = _review(pr, isolated_config)
    assert "TEST-901" not in {item["rule_id"] for item in result["findings"]}
    assert "TEST-901" in result["skipped_llm_rules"]


def test_candidate_rule_requires_explicit_opt_in(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    rules, _ = isolated_config
    _append_rule(
        rules,
        _test_rule(
            status="candidate",
            detect={"field": "pattern", "banned": ["file"]},
        ),
    )
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text()},
    )
    production = _review(pr, isolated_config)
    candidate = _review(pr, isolated_config, include_candidates=True)
    assert "TEST-901" not in {item["rule_id"] for item in production["findings"]}
    assert "TEST-901" in {item["rule_id"] for item in candidate["findings"]}


def test_unknown_detect_operator_fails_closed(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    rules, _ = isolated_config
    _mutate_rule(
        rules,
        "PRIN-002",
        lambda rule: rule.update({"detect": {"execute_shell": True}}),
    )
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text()},
    )
    result = _review(pr, isolated_config)
    assert result["verdict"] == "input_error"
    assert result["input_errors"][0]["code"] == "unsupported_detect"


def test_duplicate_rule_id_fails_closed(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
) -> None:
    rules, _ = isolated_config
    source = yaml.safe_load((rules / "principles.yaml").read_text(encoding="utf-8"))
    _append_rule(rules, copy.deepcopy(source["rules"][0]))
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text()},
    )
    result = _review(pr, isolated_config)
    assert result["verdict"] == "input_error"
    assert result["input_errors"][0]["code"] == "duplicate_rule_id"


@pytest.mark.parametrize("missing", ["source_ref", "provenance"])
def test_rule_missing_source_or_provenance_fails_closed(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
    missing: str,
) -> None:
    rules, _ = isolated_config

    def remove(rule: dict[str, Any]) -> None:
        rule.pop(missing)

    _mutate_rule(rules, "PRIN-002", remove)
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text()},
    )
    result = _review(pr, isolated_config)
    assert result["verdict"] == "input_error"
    assert result["input_errors"][0]["code"] == "required"
    assert result["input_errors"][0]["field"] == missing


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pattern", "carrier_pigeon"),
        ("zone", "partner_cloud"),
        ("transfer_mode", "telepathy"),
    ],
)
def test_unknown_flow_vocab_value_fails_closed(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
    field: str,
    value: str,
) -> None:
    pr = _write_pr(
        tmp_path,
        changed=["flows/IF-9998.md"],
        files={"flows/IF-9998.md": _flow_text(**{field: value})},
    )
    result = _review(pr, isolated_config)
    assert result["verdict"] == "input_error"
    assert result["input_errors"][0]["code"] == "invalid_enum"
    assert result["input_errors"][0]["field"] == field


@pytest.mark.parametrize(
    ("relative", "metadata", "expected_field"),
    [
        (
            "systems/AS-0006.md",
            {
                "kind": "system_passport",
                "id": "AS-0006",
                "name": "CRM",
                "owner": ["Retail"],
                "criticality": "business_critical",
                "target_status": "invest",
            },
            "owner",
        ),
        (
            "adrs/ADR-9998.md",
            {
                "kind": "adr",
                "id": "ADR-9998",
                "status": "accepted",
                "date": 20260715,
                "author": "Architect",
                "systems": ["AS-0006"],
            },
            "date",
        ),
        (
            "adrs/ADR-9998.md",
            {
                "kind": "adr",
                "id": "ADR-9998",
                "status": ["accepted"],
                "date": "2026-07-15",
                "author": "Architect",
                "systems": ["AS-0006"],
            },
            "status",
        ),
    ],
)
def test_wrong_present_frontmatter_types_fail_closed(
    tmp_path: Path,
    isolated_config: tuple[Path, Path],
    relative: str,
    metadata: Mapping[str, Any],
    expected_field: str,
) -> None:
    pr = _write_pr(
        tmp_path,
        changed=[relative],
        files={relative: _markdown_artifact(metadata)},
    )
    result = _review(pr, isolated_config)
    assert result["verdict"] == "input_error"
    assert result["input_errors"][0]["code"] == "invalid_type"
    assert result["input_errors"][0]["field"] == expected_field
