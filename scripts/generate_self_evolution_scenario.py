#!/usr/bin/env python3
"""Generate a deterministic, inspectable synthetic E2E scenario for the UI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGA_ROOT = REPOSITORY_ROOT / "aga-skill"
CORPUS_PATH = AGA_ROOT / "golden" / "corpus.yaml"
PRS_ROOT = AGA_ROOT / "golden" / "prs"
SCHEMA = "aga.self-evolution-scenario/v2"
SAFE_SEED_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
PRESETS = {
    "demo": {
        "title": "Короткое демо · 6 ключевых кейсов",
        "description": "Блокеры SEAF и principle, ADR, диаграмма и пара Loop A target/control.",
        "case_ids": {"pr-09", "pr-12", "pr-15", "pr-16", "pr-18", "pr-21"},
        "domains": set(),
        "defect_count": 1,
    },
    "full": {
        "title": "Полный E2E · архитектура + 26 PR",
        "description": "Весь golden-корпус, реальный архитектурный remediation-кейс и четыре параллельных домена.",
        "domains": {"clean", "ADR", "DIAG", "PRIN", "SEAF"},
        "defect_count": 1,
    },
    "integration": {
        "title": "Интеграции и SEAF",
        "description": "Потоки, паспорта систем, DMZ-прецедент и архитектурные зависимости.",
        "domains": {"clean", "PRIN", "SEAF"},
        "defect_count": 1,
    },
    "governance": {
        "title": "ADR и диаграммы",
        "description": "Архитектурные решения, диаграммы и обязательная пара rule-target/negative-control.",
        "domains": {"clean", "ADR", "DIAG"},
        "defect_count": 1,
    },
}
MAX_PREVIEW_CHARS = 900
MAX_ARTIFACT_BYTES = 256 * 1024


class ScenarioError(RuntimeError):
    pass


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ScenarioError("scenario_source_invalid") from exc
    if not isinstance(value, Mapping):
        raise ScenarioError("scenario_source_invalid")
    return value


def _safe_relative(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ScenarioError("scenario_artifact_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ScenarioError("scenario_artifact_invalid")
    return value


def _domain(case: Mapping[str, Any]) -> str:
    findings = case.get("expected", {}).get("findings", [])
    if not findings:
        return "clean"
    rule_id = str(findings[0].get("rule_id") or "")
    return rule_id.split("-", 1)[0] if "-" in rule_id else "clean"


def _artifact_snapshot(path: Path) -> tuple[str, str]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_ARTIFACT_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise ScenarioError("scenario_artifact_unavailable") from exc
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ScenarioError("scenario_artifact_too_large")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ScenarioError("scenario_artifact_unavailable") from exc
    compact = text[:MAX_PREVIEW_CHARS]
    preview = compact + ("\n…" if len(text) > MAX_PREVIEW_CHARS else "")
    return preview, hashlib.sha256(raw).hexdigest()


def build_test_catalog(project_root: Path = REPOSITORY_ROOT) -> list[dict[str, Any]]:
    root = project_root.resolve(strict=True)
    corpus = _load_yaml(root / "aga-skill" / "golden" / "corpus.yaml")
    raw_cases = corpus.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ScenarioError("scenario_corpus_invalid")
    catalog: list[dict[str, Any]] = []
    for raw in raw_cases:
        if not isinstance(raw, Mapping):
            raise ScenarioError("scenario_case_invalid")
        case_id = str(raw.get("id") or "")
        if re.fullmatch(r"pr-[0-9]{2}", case_id) is None:
            raise ScenarioError("scenario_case_invalid")
        case_root = root / "aga-skill" / "golden" / "prs" / case_id
        meta = _load_yaml(case_root / "meta.yaml")
        changed = meta.get("changed_files")
        if not isinstance(changed, list) or not changed:
            raise ScenarioError("scenario_changed_files_invalid")
        artifacts: list[dict[str, str]] = []
        changed_files: list[str] = []
        for value in changed:
            relative = _safe_relative(value)
            changed_files.append(relative)
            files_root = (case_root / "files").resolve(strict=True)
            lexical_target = case_root / "files" / relative
            cursor = lexical_target
            while cursor != files_root and cursor != cursor.parent:
                if cursor.is_symlink():
                    raise ScenarioError("scenario_artifact_invalid")
                cursor = cursor.parent
            target = lexical_target.resolve(strict=True)
            try:
                target.relative_to(files_root)
            except ValueError as exc:
                raise ScenarioError("scenario_artifact_invalid") from exc
            preview, sha256 = _artifact_snapshot(target)
            artifacts.append({"path": relative, "preview": preview, "sha256": sha256})
        expected = raw.get("expected")
        if not isinstance(expected, Mapping):
            raise ScenarioError("scenario_expected_invalid")
        findings = expected.get("findings", [])
        if not isinstance(findings, list):
            raise ScenarioError("scenario_expected_invalid")
        catalog.append(
            {
                "id": case_id,
                "title": str(raw.get("title") or case_id),
                "scenario": str(raw.get("scenario") or ""),
                "domain": _domain(raw),
                "origin": str(raw.get("origin") or "human-approved golden corpus"),
                "changed_files": changed_files,
                "input_artifacts": artifacts,
                "expected": {
                    "outcome": str(expected.get("outcome") or ""),
                    "findings": [
                        {
                            "rule_id": str(item.get("rule_id") or ""),
                            "severity": str(item.get("severity") or ""),
                        }
                        for item in findings
                        if isinstance(item, Mapping)
                    ],
                },
            }
        )
    return catalog


def _graph(seed: str, defect_count: int) -> dict[str, Any]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    nodes = [
        {"id": "demo.checkout", "label": "Checkout", "kind": "channel", "target_status": "strategic"},
        {"id": "demo.mobile", "label": "Mobile", "kind": "channel", "target_status": "strategic"},
        {"id": "demo.partner", "label": "Partner API", "kind": "external", "target_status": "tolerate"},
        {"id": "demo.gateway", "label": "API Gateway", "kind": "platform", "target_status": "strategic"},
        {"id": "demo.orders", "label": "Orders", "kind": "service", "target_status": "strategic"},
        {"id": "demo.profile", "label": "Profile Master", "kind": "master", "target_status": "strategic"},
        {"id": "demo.legacy_scoring", "label": "Legacy Scoring", "kind": "legacy", "target_status": "eliminate", "replaced_by": "demo.scoring_v2"},
        {"id": "demo.scoring_v2", "label": "Scoring V2", "kind": "service", "target_status": "strategic"},
        {"id": "demo.legacy_archive", "label": "Legacy Archive", "kind": "legacy", "target_status": "eliminate", "replaced_by": "demo.archive_v2"},
        {"id": "demo.archive_v2", "label": "Archive V2", "kind": "service", "target_status": "strategic"},
        {"id": "demo.analytics", "label": "Analytics", "kind": "data", "target_status": "tolerate"},
    ]
    healthy = [
        ("checkout_gateway", "demo.checkout", "demo.gateway", "HTTPS"),
        ("mobile_gateway", "demo.mobile", "demo.gateway", "HTTPS"),
        ("partner_gateway", "demo.partner", "demo.gateway", "mTLS" if digest[1] % 2 else "HTTPS+JWS"),
        ("gateway_orders", "demo.gateway", "demo.orders", "gRPC"),
        ("gateway_profile", "demo.gateway", "demo.profile", "REST"),
        ("orders_scoring", "demo.orders", "demo.scoring_v2", "Kafka" if digest[2] % 2 else "gRPC"),
        ("profile_analytics", "demo.profile", "demo.analytics", "CDC"),
        ("archive_analytics", "demo.archive_v2", "demo.analytics", "Batch"),
    ]
    defect_sources = ["demo.checkout", "demo.mobile", "demo.partner"]
    rotation = digest[0] % len(defect_sources)
    defect_sources = defect_sources[rotation:] + defect_sources[:rotation]
    selected_source = defect_sources[0]
    defects = [
        (
            f"{selected_source.split('.', 1)[-1]}_to_legacy_scoring",
            selected_source,
            "demo.legacy_scoring",
            "REST",
            "demo.scoring_v2",
        ),
    ][:defect_count]
    edges = [
        {"id": identifier, "from": source, "to": target, "protocol": protocol, "status": "unchecked"}
        for identifier, source, target, protocol in healthy
    ]
    edges.extend(
        {
            "id": identifier,
            "from": source,
            "to": target,
            "protocol": protocol,
            "status": "unchecked",
            "expected_rule": "SEAF-004",
            "replacement_to": replacement,
        }
        for identifier, source, target, protocol, replacement in defects
    )
    return {"nodes": nodes, "edges": edges}


def build_scenario(
    *,
    seed: str,
    preset: str = "full",
    parallel_workers: int = 4,
    project_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    if not isinstance(seed, str) or SAFE_SEED_RE.fullmatch(seed) is None:
        raise ScenarioError("scenario_seed_invalid")
    if preset not in PRESETS:
        raise ScenarioError("scenario_preset_invalid")
    if isinstance(parallel_workers, bool) or parallel_workers not in {2, 3, 4}:
        raise ScenarioError("scenario_workers_invalid")
    definition = PRESETS[preset]
    # The only enabled rule mutation targets the approved DMZ precedent in
    # pr-15.  pr-16 is its negative control.  Every preset therefore includes
    # both cases; otherwise a preset could claim an improvement it never ran.
    mandatory_rule_controls = {"pr-15", "pr-16"}
    selected_case_ids = set(definition.get("case_ids") or ())
    catalog = [
        case
        for case in build_test_catalog(project_root)
        if (
            case["id"] in selected_case_ids
            if selected_case_ids
            else case["domain"] in definition["domains"]
            or case["id"] in mandatory_rule_controls
        )
    ]
    catalog.sort(
        key=lambda case: hashlib.sha256(f"{seed}:{case['id']}".encode("utf-8")).hexdigest()
    )
    if not catalog:
        raise ScenarioError("scenario_empty")
    graph = _graph(seed, int(definition["defect_count"]))
    digest_input = {
        "schema": SCHEMA,
        "seed": seed,
        "preset": preset,
        "parallel_workers": parallel_workers,
        "graph": graph,
        "tests": catalog,
    }
    digest = hashlib.sha256(
        json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    scenario_id = f"e2e-{digest[:16]}"
    domains = sorted({case["domain"] for case in catalog})
    planned_agents = [
        {"id": "orchestrator", "name": "E2E Orchestrator", "type": "orchestrator", "stage": "planning"},
        {"id": "architecture", "name": "Architecture Evolution", "type": "architecture", "stage": "reviewing"},
        {"id": "workspace-validator", "name": "Scenario Graph Validator", "type": "test_worker", "stage": "reviewing"},
        {"id": "rule-evolver", "name": "Rule Evolver · Loop A", "type": "fitness", "stage": "remediating"},
        {"id": "gate", "name": "Unified Safety Gate", "type": "gate", "stage": "gating"},
    ]
    for phase in ("baseline", "candidate"):
        for index in range(1, parallel_workers + 1):
            planned_agents.append(
                {
                    "id": f"{phase}-worker-{index}",
                    "name": f"{phase.title()} Test Worker {index}",
                    "type": "test_worker",
                    "stage": "testing" if phase == "baseline" else "rereview",
                }
            )
    return {
        "schema": SCHEMA,
        "scenario_id": scenario_id,
        "preset": preset,
        "title": definition["title"],
        "description": definition["description"],
        "seed": seed,
        "classification": "synthetic-public",
        "content_sha256": digest,
        "parallel_workers": parallel_workers,
        "summary": {
            "systems": len(graph["nodes"]),
            "flows": len(graph["edges"]),
            "architecture_checks": int(definition["defect_count"]),
            "tests": len(catalog),
            "domains": domains,
        },
        "graph": graph,
        "tests": catalog,
        "agent_plan": {
            "parallel_workers": parallel_workers,
            "stages": ["generate", "baseline", "evolve", "candidate", "gate"],
            "real_execution": True,
            "live_ouroboros_optional": True,
            "agents": planned_agents,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default="full-e2e")
    parser.add_argument("--preset", choices=tuple(PRESETS), default="full")
    parser.add_argument("--parallel-workers", type=int, choices=(2, 3, 4), default=4)
    args = parser.parse_args(argv)
    try:
        scenario = build_scenario(
            seed=args.seed,
            preset=args.preset,
            parallel_workers=args.parallel_workers,
        )
    except ScenarioError as exc:
        print(json.dumps({"schema": SCHEMA, "status": "failed", "code": str(exc)}))
        return 2
    print(json.dumps(scenario, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
