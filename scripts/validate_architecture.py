#!/usr/bin/env python3
"""Fail-closed smoke validation for the project SEAF-native workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
AGA_ROOT = ROOT / "aga-skill"
sys.path.insert(0, str(AGA_ROOT))

from tools.seaf_native import DocHubImportResolver, SeafCanonicalAdapter  # noqa: E402
from tools.validation import ValidationError  # noqa: E402


def _find_chat(workspace: Any) -> Mapping[str, Any] | None:
    for document in workspace.documents:
        docs = document.data.get("docs")
        if isinstance(docs, Mapping):
            value = docs.get("aga.governance.review")
            if isinstance(value, Mapping):
                return value
    return None


def validate(manifest: Path) -> None:
    repository_root = manifest.parent.resolve(strict=True)
    framework = repository_root / "vendor" / "seaf-core" / "dochub.yaml"
    if not framework.is_file():
        raise ValidationError(
            "pinned seaf-core checkout is not initialized",
            path=framework,
            code="dependency_not_initialized",
        )
    resolver = DocHubImportResolver(
        repository_root,
        max_files=1024,
        max_depth=64,
        max_total_bytes=32 * 1024 * 1024,
        max_yaml_nodes=750_000,
    )
    workspace = resolver.resolve(manifest.name)
    snapshot = SeafCanonicalAdapter().adapt(workspace)

    minimums = {
        "systems": (len(snapshot.systems), 6),
        "integrations": (len(snapshot.integrations), 4),
        "adrs": (len(snapshot.adrs), 2),
        "diagrams": (len(snapshot.diagrams), 2),
    }
    for name, (actual, expected) in minimums.items():
        if actual < expected:
            raise ValidationError(
                f"synthetic workspace requires at least {expected} {name}; got {actual}",
                path=manifest,
                field=name,
                code="smoke_entity_count",
            )

    system_ids = {system.id for system in snapshot.systems}
    for flow in snapshot.integrations:
        for endpoint_name, endpoint in (("from", flow.source), ("to", flow.target)):
            if endpoint not in system_ids:
                raise ValidationError(
                    f"integration endpoint does not resolve: {endpoint}",
                    path=flow.source_ref.file,
                    field=f"{flow.source_ref.pointer}/{endpoint_name}",
                    code="broken_reference",
                )

    chat = _find_chat(workspace)
    scenarios = chat.get("scenarios") if chat else None
    scenario = scenarios.get("aga-review") if isinstance(scenarios, Mapping) else None
    if not isinstance(scenario, Mapping):
        raise ValidationError(
            "AGA ai-chat scenario is missing", path=manifest, code="smoke_chat_missing"
        )
    if scenario.get("type") != "gigachat":
        raise ValidationError(
            "MCP scenario must use the pinned ArchTool gigachat agent type",
            path="model/ai-chat.yaml",
            field="/docs/aga.governance.review/scenarios/aga-review/type",
            code="smoke_chat_type",
        )
    servers = scenario.get("mcp_servers")
    expected_server = {"url": "http://aga-mcp:8000/mcp", "transport": "streamableHttp"}
    if servers != [expected_server]:
        raise ValidationError(
            "MCP scenario must use the internal non-root Streamable HTTP endpoint",
            path="model/ai-chat.yaml",
            field="/docs/aga.governance.review/scenarios/aga-review/mcp_servers",
            code="smoke_mcp_config",
        )

    print(
        "SEAF WORKSPACE OK: "
        f"{len(snapshot.systems)} systems, {len(snapshot.integrations)} integrations, "
        f"{len(snapshot.adrs)} ADRs, {len(snapshot.diagrams)} diagrams, "
        f"{len(workspace.documents)} imported YAML files"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        validate(args.manifest)
    except (ValidationError, OSError, UnicodeError) as error:
        print(f"SEAF WORKSPACE ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

