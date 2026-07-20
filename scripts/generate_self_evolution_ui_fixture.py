#!/usr/bin/env python3
"""Build a deterministic, public UI projection of both evolution loops.

The input files are already-sanitized evidence.  This module intentionally
projects only the small subset a browser needs: synthetic graph state,
before/after metrics, rule diff lines, timeline steps, and the exact places
where Ouroboros participated.  It never reads credentials, raw prompts, or
provider responses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHITECTURE_EVIDENCE = (
    REPOSITORY_ROOT / "docs" / "evidence" / "ouroboros-self-evolution-v1.json"
)
DEFAULT_RULE_MANIFEST = REPOSITORY_ROOT / "aga-skill" / "build" / "candidate-manifest.json"
DEFAULT_RULE_METRICS_BEFORE = REPOSITORY_ROOT / "aga-skill" / "build" / "metrics-baseline.json"
DEFAULT_RULE_METRICS_AFTER = REPOSITORY_ROOT / "aga-skill" / "build" / "metrics-candidate.json"
DEFAULT_RULE_DIFF = REPOSITORY_ROOT / "aga-skill" / "build" / "rules.diff"
DEFAULT_RULE_PUBLISHER = REPOSITORY_ROOT / "aga-skill" / "build" / "publisher-result.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs" / "evidence" / "self-evolution-ui-demo.json"
SCHEMA = "aga.self-evolution-ui/v1"
MAX_INPUT_BYTES = 4 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
SECRET_RE = re.compile(
    r"(?:sk-or-v1-[A-Za-z0-9_-]{8,}|OPENROUTER_API_KEY|Authorization\s*[:=])",
    re.IGNORECASE,
)
ABSOLUTE_PATH_RE = re.compile(
    r"(?:^|[\s\"'])(?:/(?:Users|home|private|tmp|var|etc)/|[A-Za-z]:[\\/])"
)


class UIFixtureError(RuntimeError):
    """A bounded, non-sensitive fixture generation failure."""


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UIFixtureError(f"invalid_{name}")
    return value


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise UIFixtureError(f"invalid_{name}")
    return value


def _string(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise UIFixtureError(f"invalid_{name}")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UIFixtureError(f"invalid_{name}")
    result = float(value)
    if result < 0 or result != result or result == float("inf"):
        raise UIFixtureError(f"invalid_{name}")
    return result


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise UIFixtureError("input_unavailable") from exc
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise UIFixtureError("input_size_invalid")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UIFixtureError("input_json_invalid") from exc
    return _mapping(value, "input_json")


def _read_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise UIFixtureError("input_unavailable") from exc
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise UIFixtureError("input_size_invalid")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UIFixtureError("input_text_invalid") from exc


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _artifact(value: Any, name: str) -> str:
    text = _string(value, name, maximum=256)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "\\" in text:
        raise UIFixtureError(f"invalid_{name}")
    return text


def _short_sha(value: Any, name: str) -> str:
    text = _string(value, name, maximum=64)
    if not SHA_RE.fullmatch(text):
        raise UIFixtureError(f"invalid_{name}")
    return text[:12]


def _extract_source_component(diff: str) -> str:
    for line in diff.splitlines():
        stripped = line.strip()
        if stripped.startswith("from: "):
            return _string(stripped.split(":", 1)[1].strip(), "source_component", maximum=128)
    raise UIFixtureError("source_component_missing")


def _label(identifier: str) -> str:
    return identifier.split(".")[-1].replace("_", " ").title()


def _diff_lines(diff: str) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            kind = "file"
        elif line.startswith("@@"):
            kind = "hunk"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "remove"
        else:
            kind = "context"
        lines.append({"kind": kind, "text": line[:1000]})
    if not lines or len(lines) > 500:
        raise UIFixtureError("rule_diff_invalid")
    return lines


def _metric_projection(metrics: Mapping[str, Any]) -> dict[str, Any]:
    fp = _mapping(metrics.get("fp"), "metrics_fp")
    fn = _mapping(metrics.get("fn"), "metrics_fn")
    return {
        "cases": int(_number(metrics.get("cases_evaluated"), "cases_evaluated")),
        "precision": _number(metrics.get("precision"), "precision"),
        "recall": _number(metrics.get("recall"), "recall"),
        "blocker_recall": _number(metrics.get("blocker_recall"), "blocker_recall"),
        "outcome_accuracy": _number(metrics.get("exact_case_accuracy"), "exact_case_accuracy"),
        "weighted_cost": _number(metrics.get("weighted_cost"), "weighted_cost"),
        "false_findings": sum(int(_number(fp.get(key, 0), f"fp_{key}")) for key in ("blocker", "major", "minor")),
        "missed_findings": sum(int(_number(fn.get(key, 0), f"fn_{key}")) for key in ("blocker", "major", "minor")),
    }


def _architecture_projection(evidence: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if evidence.get("schema") != "aga.architecture-self-evolution/v1":
        raise UIFixtureError("architecture_schema_invalid")
    if evidence.get("data_classification") != "synthetic-public":
        raise UIFixtureError("architecture_not_synthetic_public")
    runtime = _mapping(evidence.get("runtime"), "runtime")
    if runtime.get("name") != "ouroboros":
        raise UIFixtureError("runtime_not_ouroboros")
    review_before = _mapping(evidence.get("review_before"), "review_before")
    review_before_final = _mapping(review_before.get("final"), "review_before_final")
    findings = _list(review_before_final.get("findings"), "review_before_findings")
    target_findings = [
        item
        for item in findings
        if isinstance(item, Mapping)
        and item.get("severity") == "blocker"
        and item.get("rule_id") in {None, "SEAF-004"}
        and item.get("origin") in {None, "deterministic"}
    ]
    if len(target_findings) != 1:
        raise UIFixtureError("review_before_finding_count_invalid")
    finding = _mapping(target_findings[0], "initial_finding")
    remediation = _mapping(evidence.get("remediation"), "remediation")
    remediation_final = _mapping(remediation.get("final"), "remediation_final")
    patch = _mapping(remediation_final.get("patch"), "remediation_patch")
    review_after = _mapping(evidence.get("review_after"), "review_after")
    review_after_final = _mapping(review_after.get("final"), "review_after_final")
    if _list(review_after_final.get("findings"), "review_after_findings"):
        raise UIFixtureError("review_after_not_clean")
    gate = _mapping(evidence.get("gate"), "gate")
    if gate.get("passed") is not True:
        raise UIFixtureError("architecture_gate_not_passed")

    diff = _string(patch.get("diff"), "architecture_diff", maximum=32_000)
    source = _extract_source_component(diff)
    old_target = _string(patch.get("eliminated_component"), "eliminated_component", maximum=128)
    new_target = _string(patch.get("replacement_component"), "replacement_component", maximum=128)
    edge_id = _string(patch.get("entity_id"), "architecture_edge_id", maximum=128)
    rule_id = _string(patch.get("rule_id"), "architecture_rule_id", maximum=64)
    artifact = _artifact(patch.get("artifact"), "architecture_artifact")
    nodes = [
        {
            "id": source,
            "label": _label(source),
            "kind": "component",
            "target_status": "strategic",
        },
        {
            "id": old_target,
            "label": _label(old_target),
            "kind": "component",
            "target_status": "eliminate",
            "replaced_by": new_target,
        },
        {
            "id": new_target,
            "label": _label(new_target),
            "kind": "component",
            "target_status": "strategic",
        },
    ]
    before_edge = {
        "id": edge_id,
        "from": source,
        "to": old_target,
        "health": "blocked",
        "finding": rule_id,
    }
    after_edge = {
        "id": edge_id,
        "from": source,
        "to": new_target,
        "health": "healthy",
        "finding": None,
    }
    before_tools = _list(_mapping(review_before.get("receipts"), "review_before_receipts").get("tool_names"), "review_before_tools")
    remediation_tools = [
        _string(_mapping(item, "remediation_receipt").get("tool"), "remediation_tool", maximum=64)
        for item in _list(remediation.get("receipts"), "remediation_receipts")
    ]
    after_tools = _list(_mapping(review_after.get("receipts"), "review_after_receipts").get("tool_names"), "review_after_tools")

    architecture = {
        "title": "Самоэволюция синтетической архитектуры",
        "status": "passed",
        "dataset": {
            "classification": "synthetic-public",
            "description": "Три вымышленных компонента и один намеренно ошибочный интеграционный поток.",
            "components": nodes,
        },
        "before": {
            "revision": _short_sha(evidence.get("head"), "architecture_head"),
            "nodes": nodes,
            "edges": [before_edge],
            "findings": 1,
            "verdict": _string(review_before_final.get("verdict"), "review_before_verdict", maximum=64),
        },
        "after": {
            "revision": _short_sha(evidence.get("patched_head"), "architecture_patched_head"),
            "nodes": nodes,
            "edges": [after_edge],
            "findings": 0,
            "verdict": _string(review_after_final.get("verdict"), "review_after_verdict", maximum=64),
        },
        "change": {
            "artifact": artifact,
            "rule_id": rule_id,
            "severity": _string(finding.get("severity"), "finding_severity", maximum=32),
            "summary": _string(patch.get("summary"), "patch_summary", maximum=1000),
            "diff_lines": _diff_lines(diff),
        },
        "timeline": [
            {
                "id": "architecture.generated",
                "label": "Сгенерированы тестовые данные",
                "actor": "Synthetic Generator",
                "status": "completed",
                "detail": "Созданы 3 компонента и дефектный поток в выводимый из эксплуатации scorer.",
            },
            {
                "id": "architecture.review_before",
                "label": "Ouroboros нашёл проблему",
                "actor": "Ouroboros",
                "status": "blocked",
                "detail": f"{rule_id}: зависимость ведёт в компонент со статусом eliminate.",
            },
            {
                "id": "architecture.remediation",
                "label": "Ouroboros предложил изменение",
                "actor": "Ouroboros",
                "status": "completed",
                "detail": f"Поток перенаправлен: {old_target} → {new_target}.",
            },
            {
                "id": "architecture.candidate",
                "label": "Создан локальный кандидат",
                "actor": "AGA Host",
                "status": "completed",
                "detail": f"Изменён только {artifact}; публикация оставлена человеку.",
            },
            {
                "id": "architecture.review_after",
                "label": "Ouroboros перепроверил результат",
                "actor": "Ouroboros",
                "status": "completed",
                "detail": "Повторная проверка завершилась без findings: approve.",
            },
            {
                "id": "architecture.gate",
                "label": "Защитный гейт пройден",
                "actor": "AGA Gate",
                "status": "passed",
                "detail": "Blocker закрыт; auto-merge выключен, нужен review человека.",
            },
        ],
    }
    ouroboros = {
        "runtime_version": _string(runtime.get("version"), "runtime_version", maximum=32),
        "runtime_source_commit": _short_sha(runtime.get("source_commit"), "runtime_source_commit"),
        "model": _string(evidence.get("model"), "model", maximum=128),
        "provider": _string(evidence.get("provider"), "provider", maximum=64),
        "visible_steps": [
            {
                "timeline_id": "architecture.review_before",
                "task_id": _string(review_before.get("task_id"), "review_before_task", maximum=64),
                "tools": [_string(tool, "review_before_tool", maximum=64) for tool in before_tools],
                "outcome": _string(review_before_final.get("verdict"), "review_before_outcome", maximum=64),
                "cost_usd": _number(_mapping(review_before.get("model_usage"), "review_before_usage").get("known_cost_usd"), "review_before_cost"),
            },
            {
                "timeline_id": "architecture.remediation",
                "task_id": _string(remediation.get("task_id"), "remediation_task", maximum=64),
                "tools": remediation_tools,
                "outcome": _string(remediation_final.get("outcome"), "remediation_outcome", maximum=64),
                "cost_usd": _number(_mapping(remediation.get("model_usage"), "remediation_usage").get("known_cost_usd"), "remediation_cost"),
            },
            {
                "timeline_id": "architecture.review_after",
                "task_id": _string(review_after.get("task_id"), "review_after_task", maximum=64),
                "tools": [_string(tool, "review_after_tool", maximum=64) for tool in after_tools],
                "outcome": _string(review_after_final.get("verdict"), "review_after_outcome", maximum=64),
                "cost_usd": _number(_mapping(review_after.get("model_usage"), "review_after_usage").get("known_cost_usd"), "review_after_cost"),
            },
        ],
    }
    return architecture, ouroboros


def _rule_projection(
    manifest: Mapping[str, Any],
    metrics_before: Mapping[str, Any],
    metrics_after: Mapping[str, Any],
    rule_diff: str,
    publisher: Mapping[str, Any],
) -> dict[str, Any]:
    if manifest.get("schema") != "aga.candidate-manifest/v1":
        raise UIFixtureError("rule_manifest_schema_invalid")
    if manifest.get("gate_passed") is not True:
        raise UIFixtureError("rule_gate_not_passed")
    cycle_id = _string(manifest.get("cycle_id"), "rule_cycle_id", maximum=128)
    details = _mapping(publisher.get("details"), "publisher_details")
    branch = _string(details.get("candidate_branch"), "rule_candidate_branch", maximum=256)
    raw_commit = publisher.get("commit")
    commit = None if raw_commit is None else _short_sha(raw_commit, "rule_candidate_commit")
    before = _metric_projection(metrics_before)
    after = _metric_projection(metrics_after)
    if before["cases"] != after["cases"]:
        raise UIFixtureError("rule_case_count_changed")
    if after["precision"] < before["precision"] or after["recall"] < before["recall"]:
        raise UIFixtureError("rule_metrics_regressed")
    if after["weighted_cost"] > before["weighted_cost"]:
        raise UIFixtureError("rule_cost_regressed")
    diff_lines = _diff_lines(rule_diff)
    target_rule = "PRIN-002"
    if target_rule not in rule_diff or "EXC-PRIN-002-001" not in rule_diff:
        raise UIFixtureError("rule_diff_target_missing")
    return {
        "title": "Самоэволюция архитектурных правил",
        "status": "passed",
        "cycle_id": cycle_id,
        "mutation": {
            "type": "add_exception",
            "target_rule": target_rule,
            "file": "aga-skill/rules/principles.yaml",
            "precedent": "precedent:0001",
            "before": {
                "version": _string(manifest.get("version_from"), "version_from", maximum=32),
                "exception_present": False,
            },
            "after": {
                "version": _string(manifest.get("version_to"), "version_to", maximum=32),
                "exception_present": True,
                "exception_id": "EXC-PRIN-002-001",
                "scope": "DMZ file batch via controlled gateway with security approval",
            },
            "diff_lines": diff_lines,
        },
        "tests": {
            "synthetic_cases": before["cases"],
            "before": before,
            "after": after,
            "delta": {
                "precision": round(after["precision"] - before["precision"], 4),
                "outcome_accuracy": round(after["outcome_accuracy"] - before["outcome_accuracy"], 4),
                "weighted_cost": round(after["weighted_cost"] - before["weighted_cost"], 4),
                "false_findings": after["false_findings"] - before["false_findings"],
            },
            "gate_passed": True,
        },
        "candidate": {
            "branch": branch,
            "commit": commit,
            "status": "local_candidate_ready",
            "human_review_required": bool(manifest.get("human_confirmation_required")),
            "auto_merge": bool(manifest.get("auto_merge")),
            "external_side_effects": bool(publisher.get("external_side_effects")),
        },
        "timeline": [
            {
                "id": "rules.feedback",
                "label": "Получен проверенный прецедент",
                "actor": "Architect Feedback",
                "status": "completed",
                "detail": "Контролируемый batch-файловый обмен в DMZ оказался допустимым кейсом.",
            },
            {
                "id": "rules.mutation",
                "label": "Сформирована мутация правила",
                "actor": "AGA Evolver",
                "status": "completed",
                "detail": "В PRIN-002 добавлено узкое исключение EXC-PRIN-002-001.",
            },
            {
                "id": "rules.tests",
                "label": "Запущены синтетические тесты",
                "actor": "Golden Corpus",
                "status": "completed",
                "detail": f"Проверено {before['cases']} кейсов: precision {before['precision']:.4f} → {after['precision']:.4f}.",
            },
            {
                "id": "rules.gate",
                "label": "Мутация прошла fitness-гейт",
                "actor": "AGA Gate",
                "status": "passed",
                "detail": f"Weighted cost {before['weighted_cost']:g} → {after['weighted_cost']:g}; recall не снизился.",
            },
            {
                "id": "rules.candidate",
                "label": "Создан локальный кандидат правил",
                "actor": "AGA Publisher",
                "status": "completed",
                "detail": f"Версия {manifest['version_from']} → {manifest['version_to']}; merge оставлен человеку.",
            },
        ],
    }


def _assert_sanitized(value: Any) -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if SECRET_RE.search(serialized):
        raise UIFixtureError("output_contains_secret_marker")
    if ABSOLUTE_PATH_RE.search(serialized):
        raise UIFixtureError("output_contains_absolute_path")


def build_fixture_from_evidence(
    *,
    architecture_evidence: Mapping[str, Any],
    rule_manifest: Mapping[str, Any],
    rule_metrics_before: Mapping[str, Any],
    rule_metrics_after: Mapping[str, Any],
    rule_diff: str,
    rule_publisher: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic UI document from sanitized evidence objects."""

    architecture, ouroboros = _architecture_projection(architecture_evidence)
    rules = _rule_projection(
        rule_manifest,
        rule_metrics_before,
        rule_metrics_after,
        rule_diff,
        rule_publisher,
    )
    identity = {
        "architecture": architecture_evidence.get("correlation_sha256"),
        "rules": rule_manifest.get("cycle_id"),
    }
    fixture = {
        "schema": SCHEMA,
        "status": "ready",
        "classification": "synthetic-public",
        "sanitized": True,
        "scenario_id": f"self-evolution-{_sha256(identity)[:16]}",
        "summary": {
            "architecture_gate_passed": architecture["status"] == "passed",
            "rule_gate_passed": rules["status"] == "passed",
            "human_review_required": True,
            "external_side_effects": False,
        },
        "ouroboros": ouroboros,
        "architecture_evolution": architecture,
        "rule_evolution": rules,
    }
    _assert_sanitized(fixture)
    return fixture


def build_fixture(project_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Build the standard UI fixture rooted at a project checkout.

    This is the intentionally small import contract used by the local UI
    server.  The evidence-oriented function remains available for unit tests
    and alternate data sources.
    """

    root = project_root.resolve()
    return generate_from_paths(
        architecture_evidence=root / "docs/evidence/ouroboros-self-evolution-v1.json",
        rule_manifest=root / "aga-skill/build/candidate-manifest.json",
        rule_metrics_before=root / "aga-skill/build/metrics-baseline.json",
        rule_metrics_after=root / "aga-skill/build/metrics-candidate.json",
        rule_diff=root / "aga-skill/build/rules.diff",
        rule_publisher=root / "aga-skill/build/publisher-result.json",
    )


def generate_from_paths(
    *,
    architecture_evidence: Path = DEFAULT_ARCHITECTURE_EVIDENCE,
    rule_manifest: Path = DEFAULT_RULE_MANIFEST,
    rule_metrics_before: Path = DEFAULT_RULE_METRICS_BEFORE,
    rule_metrics_after: Path = DEFAULT_RULE_METRICS_AFTER,
    rule_diff: Path = DEFAULT_RULE_DIFF,
    rule_publisher: Path = DEFAULT_RULE_PUBLISHER,
) -> dict[str, Any]:
    return build_fixture_from_evidence(
        architecture_evidence=_read_json(architecture_evidence),
        rule_manifest=_read_json(rule_manifest),
        rule_metrics_before=_read_json(rule_metrics_before),
        rule_metrics_after=_read_json(rule_metrics_after),
        rule_diff=_read_text(rule_diff),
        rule_publisher=_read_json(rule_publisher),
    )


def _write_output(path: Path, fixture: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise UIFixtureError("output_write_failed") from exc


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture-evidence", type=Path, default=DEFAULT_ARCHITECTURE_EVIDENCE)
    parser.add_argument("--rule-manifest", type=Path, default=DEFAULT_RULE_MANIFEST)
    parser.add_argument("--rule-metrics-before", type=Path, default=DEFAULT_RULE_METRICS_BEFORE)
    parser.add_argument("--rule-metrics-after", type=Path, default=DEFAULT_RULE_METRICS_AFTER)
    parser.add_argument("--rule-diff", type=Path, default=DEFAULT_RULE_DIFF)
    parser.add_argument("--rule-publisher", type=Path, default=DEFAULT_RULE_PUBLISHER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stdout", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_args(argv)
    try:
        fixture = generate_from_paths(
            architecture_evidence=arguments.architecture_evidence,
            rule_manifest=arguments.rule_manifest,
            rule_metrics_before=arguments.rule_metrics_before,
            rule_metrics_after=arguments.rule_metrics_after,
            rule_diff=arguments.rule_diff,
            rule_publisher=arguments.rule_publisher,
        )
        if arguments.stdout:
            json.dump(fixture, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
            sys.stdout.write("\n")
        else:
            _write_output(arguments.output, fixture)
            print(json.dumps({"schema": SCHEMA, "status": "ready", "scenario_id": fixture["scenario_id"]}, sort_keys=True))
        return 0
    except UIFixtureError as exc:
        print(json.dumps({"schema": SCHEMA, "status": "failed", "code": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
