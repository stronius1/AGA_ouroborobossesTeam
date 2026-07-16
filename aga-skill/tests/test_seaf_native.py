# -*- coding: utf-8 -*-
"""Contract and security tests for the SEAF-native canonical adapter."""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from tools.seaf_native import (  # noqa: E402
    CANONICAL_SCHEMA,
    DocHubImportResolver,
    RepositoryRevision,
    SeafCanonicalAdapter,
    load_seaf_native,
)
from tools.validation import ValidationError  # noqa: E402


ROOT_HEADER = """\
aga:
  schema: seaf-core/v1.4.0
  extensions: [aga.project/v1]
  data_classification: synthetic-public
"""
PROJECT_EXTENSION_TEXT = (
    PKG_ROOT.parent / "architecture" / "metamodel" / "aga-extension.yaml"
).read_text(encoding="utf-8")


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_extension(root: Path) -> None:
    _write(root, "aga-extension.yaml", PROJECT_EXTENSION_TEXT)


def _manifest(
    root: Path,
    body: str = "",
    *,
    imports: tuple[str, ...] = (),
    header: str = ROOT_HEADER,
) -> Path:
    _write_extension(root)
    all_imports = ("aga-extension.yaml", *imports)
    rendered = header + "imports:\n" + "".join(f"  - {item}\n" for item in all_imports)
    return _write(root, "dochub.yaml", rendered + body)


def _error(code: str):
    return pytest.raises(ValidationError, match=rf"\[{code}\]")


def _component(entity_id: str = "demo.billing", *, owner: bool = True) -> str:
    owner_line = "    owner: demo-team\n" if owner else ""
    return f"""\
components:
  {entity_id}:
    title: Synthetic Billing
    entity: component
{owner_line}    criticality: high
    target_status: strategic
    domain: payments
    infra: false
    description: Synthetic data only
"""


def _revision(manifest_sha256: str) -> RepositoryRevision:
    return RepositoryRevision(
        base_commit="1" * 40,
        head_commit="2" * 40,
        manifest_sha256=manifest_sha256,
        archtool_commit="3" * 40,
        seaf_core_commit="4" * 40,
        aga_version="2.0.0",
        rules_sha256="5" * 64,
    )


def test_seaf_native_component_maps_to_system(tmp_path):
    _manifest(tmp_path, imports=("model/components.yaml",))
    _write(tmp_path, "model/components.yaml", _component())

    workspace = DocHubImportResolver(tmp_path).resolve("dochub.yaml")
    snapshot = SeafCanonicalAdapter().adapt(
        workspace, revision=_revision(workspace.manifest_sha256)
    )

    assert snapshot.schema == CANONICAL_SCHEMA
    assert len(snapshot.systems) == 1
    system = snapshot.systems[0]
    assert (system.id, system.name) == ("demo.billing", "Synthetic Billing")
    assert (system.owner, system.criticality, system.target_status) == (
        "demo-team",
        "high",
        "strategic",
    )
    assert system.source_ref.file == "model/components.yaml"
    assert system.source_ref.pointer == "/components/demo.billing"
    assert system.source_ref.commit == "2" * 40
    component_document = next(
        document for document in workspace.documents if document.path == "model/components.yaml"
    )
    assert system.source_ref.sha256 == component_document.sha256
    assert snapshot.as_dict()["systems"][0]["source_ref"]["file"] == "model/components.yaml"


def test_seaf_component_uses_official_title_not_legacy_name_alias(tmp_path):
    component = _component().replace(
        "    title: Synthetic Billing\n",
        "    title: Synthetic Billing\n    name: Untrusted legacy alias\n",
    )
    _manifest(tmp_path, component)

    snapshot = load_seaf_native(tmp_path)

    assert snapshot.systems[0].name == "Synthetic Billing"


def test_seaf_native_integration_from_to_maps_to_flow(tmp_path):
    _manifest(
        tmp_path,
        _component("demo.source")
        + _component("demo.target").replace("components:\n", "", 1)
        + """
seaf.app.integrations:
  demo.invoice-flow:
    title: Invoice events
    description: Synthetic invoice event delivery
    from: demo.source
    to: demo.target
    protocol: HTTPS
    pattern: api_gateway
""",
    )

    snapshot = load_seaf_native(tmp_path)

    assert len(snapshot.integrations) == 1
    flow = snapshot.integrations[0]
    assert (flow.source, flow.target) == ("demo.source", "demo.target")
    assert flow.protocol == "HTTPS"
    assert flow.source_ref.pointer == "/seaf.app.integrations/demo.invoice-flow"


def test_native_adr_and_context_map_to_versioned_contract(tmp_path):
    _write(tmp_path, "diagrams/landscape.puml", "@startuml\n@enduml\n")
    _manifest(
        tmp_path,
        """
seaf.change.adr:
  demo.adr.001:
    title: Use a synthetic event stream
    moment: '2026-07-15'
    status: accepted
    issue: A synthetic integration decision is required.
    context:
      - area: technology
        vector: unknown
        content: No production identifiers are used.
    decision: Publish synthetic events.
    consequences:
      - area: technology
        vector: positive
        content: Demo consumers are isolated.
contexts:
  demo.landscape:
    title: Demo landscape
    uml: diagrams/landscape.puml
    components: [demo.source, demo.target]
""",
    )

    snapshot = load_seaf_native(tmp_path)

    assert snapshot.adrs[0].decision == "Publish synthetic events."
    assert snapshot.adrs[0].source_ref.pointer == "/seaf.change.adr/demo.adr.001"
    assert snapshot.diagrams[0].kind == "plantuml"
    assert snapshot.diagrams[0].artifact == "diagrams/landscape.puml"
    assert snapshot.diagrams[0].components == ("demo.source", "demo.target")


def test_unknown_seaf_schema_fails_closed(tmp_path):
    _manifest(
        tmp_path,
        header=ROOT_HEADER.replace("seaf-core/v1.4.0", "seaf-core/v9.9.9"),
    )

    with _error("schema_unsupported") as caught:
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")
    assert caught.value.field == "/aga/schema"


def test_missing_project_extension_marker_fails_closed(tmp_path):
    _manifest(
        tmp_path,
        header=(
            "aga:\n"
            "  schema: seaf-core/v1.4.0\n"
            "  extensions: []\n"
            "  data_classification: synthetic-public\n"
        ),
    )

    with _error("extension_missing"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")


def test_declared_but_unloaded_project_extension_fails_closed(tmp_path):
    _write(tmp_path, "dochub.yaml", ROOT_HEADER)

    with _error("extension_missing"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")


def test_inline_project_extension_marker_is_not_a_loaded_schema(tmp_path):
    _write(tmp_path, "dochub.yaml", PROJECT_EXTENSION_TEXT + "\n" + ROOT_HEADER)

    with _error("extension_inline_forbidden"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")


def test_project_extension_requires_the_versioned_schema_contract(tmp_path):
    _write(
        tmp_path,
        "aga-extension.yaml",
        "$package:\n  aga-project:\n    version: 1.0.0\n",
    )
    _write(
        tmp_path,
        "dochub.yaml",
        ROOT_HEADER + "imports: [aga-extension.yaml]\n",
    )

    with _error("extension_invalid"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")


@pytest.mark.parametrize("missing", ["owner", "criticality", "target_status"])
def test_missing_required_extension_field_fails_closed(tmp_path, missing):
    component = _component()
    component = "\n".join(
        line for line in component.splitlines() if not line.lstrip().startswith(f"{missing}:")
    )
    _manifest(tmp_path, component + "\n")

    with _error("extension_field_missing") as caught:
        load_seaf_native(tmp_path)
    assert missing in caught.value.message


def test_duplicate_entity_id_rejected(tmp_path):
    _manifest(tmp_path, imports=("one.yaml", "two.yaml"))
    definition = _component("demo.duplicate")
    _write(tmp_path, "one.yaml", definition)
    _write(tmp_path, "two.yaml", definition)

    with _error("duplicate_id") as caught:
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")
    assert caught.value.path == "two.yaml"


def test_conflicting_entity_definition_is_distinct_from_duplicate(tmp_path):
    _manifest(tmp_path, imports=("one.yaml", "two.yaml"))
    _write(tmp_path, "one.yaml", _component("demo.conflict"))
    _write(
        tmp_path,
        "two.yaml",
        _component("demo.conflict").replace("Synthetic Billing", "Different title"),
    )

    with _error("conflicting_definition"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")


def test_import_cycle_rejected(tmp_path):
    _manifest(tmp_path, imports=("a.yaml",))
    _write(tmp_path, "a.yaml", "imports: [b.yaml]\n")
    _write(tmp_path, "b.yaml", "imports: [a.yaml]\n")

    with _error("import_cycle") as caught:
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")
    assert "a.yaml -> b.yaml -> a.yaml" in caught.value.message


@pytest.mark.parametrize("unsafe", ["../outside.yaml", "/etc/passwd", "C:\\outside.yaml"])
def test_import_traversal_rejected(tmp_path, unsafe):
    _manifest(tmp_path, imports=(f"'{unsafe}'",))

    expected = "path_traversal" if unsafe.startswith("..") else "path_absolute"
    with _error(expected):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")


@pytest.mark.parametrize(
    "remote_import",
    [
        "https://example.invalid/seaf/root.yaml",
        {
            "url": "https://example.invalid/seaf/root.yaml",
            "sha256": "a" * 64,
            "path": "vendor/root.yaml",
        },
        {
            "url": "https://example.invalid/seaf/root.yaml",
            "revision": "b" * 40,
            "path": "vendor/root.yaml",
        },
    ],
)
def test_remote_import_requires_pin_and_checksum(tmp_path, remote_import):
    if isinstance(remote_import, str):
        rendered = f"  - {remote_import}\n"
    else:
        rendered = "  - " + "\n    ".join(
            f"{key}: {value}" for key, value in remote_import.items()
        ) + "\n"
    _write_extension(tmp_path)
    _write(
        tmp_path,
        "dochub.yaml",
        ROOT_HEADER + "imports:\n  - aga-extension.yaml\n" + rendered,
    )

    with _error("remote_import_unpinned"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")


def test_pinned_remote_is_resolved_only_from_checksum_verified_vendor_file(tmp_path):
    vendor = _write(tmp_path, "vendor/root.yaml", "docs: {}\n")
    digest = hashlib.sha256(vendor.read_bytes()).hexdigest()
    _write_extension(tmp_path)
    _write(
        tmp_path,
        "dochub.yaml",
        ROOT_HEADER
        + f"""
imports:
  - aga-extension.yaml
  - url: https://example.invalid/seaf/root.yaml
    revision: {'a' * 40}
    sha256: {digest}
    path: vendor/root.yaml
""",
    )

    workspace = DocHubImportResolver(
        tmp_path, trusted_dependencies={"vendor": "a" * 40}
    ).resolve("dochub.yaml")
    assert set(workspace.import_paths) == {"aga-extension.yaml", "vendor/root.yaml"}


@pytest.mark.parametrize(
    "trusted_dependencies",
    ({}, {"other-vendor": "a" * 40}, {"vendor": "b" * 40}),
)
def test_remote_import_revision_must_have_trusted_provenance(
    tmp_path, trusted_dependencies
):
    vendor = _write(tmp_path, "vendor/root.yaml", "docs: {}\n")
    digest = hashlib.sha256(vendor.read_bytes()).hexdigest()
    _write_extension(tmp_path)
    _write(
        tmp_path,
        "dochub.yaml",
        ROOT_HEADER
        + f"""
imports:
  - aga-extension.yaml
  - url: https://example.invalid/seaf/root.yaml
    revision: {'a' * 40}
    sha256: {digest}
    path: vendor/root.yaml
""",
    )

    with _error("remote_import_revision_unverified"):
        DocHubImportResolver(
            tmp_path, trusted_dependencies=trusted_dependencies
        ).resolve("dochub.yaml")


def test_symlink_and_hardlink_imports_are_rejected(tmp_path):
    _manifest(tmp_path, imports=("linked.yaml",))
    target = _write(tmp_path, "target.yaml", "docs: {}\n")
    (tmp_path / "linked.yaml").symlink_to(target)
    with _error("path_symlink"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")

    (tmp_path / "linked.yaml").unlink()
    try:
        os.link(target, tmp_path / "linked.yaml")
    except OSError:
        pytest.skip("hardlinks are not available on this filesystem")
    with _error("path_hardlink"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")


def test_import_graph_resource_limits_are_enforced(tmp_path):
    _manifest(tmp_path, imports=("child.yaml",))
    _write(tmp_path, "child.yaml", "docs: {one: {two: three}}\n")

    with _error("import_file_limit"):
        DocHubImportResolver(tmp_path, max_files=1).resolve("dochub.yaml")

    _write(tmp_path, "child.yaml", "imports: [grandchild.yaml]\n")
    _write(tmp_path, "grandchild.yaml", "docs: {}\n")
    with _error("import_depth_limit"):
        DocHubImportResolver(tmp_path, max_depth=1).resolve("dochub.yaml")


def test_exact_pinned_seaf_core_duplicate_remains_a_hard_failure(tmp_path):
    relative = "vendor/seaf-core/entities/ta/presentation/components.yaml"
    source = PKG_ROOT.parent / "architecture" / relative
    pinned_text = source.read_text(encoding="utf-8")
    _manifest(tmp_path, imports=(relative,))
    _write(tmp_path, relative, pinned_text)

    with _error("yaml_duplicate_key"):
        DocHubImportResolver(tmp_path).resolve("dochub.yaml")
    with _error("yaml_duplicate_key"):
        DocHubImportResolver(
            tmp_path,
            trusted_dependencies={
                "vendor/seaf-core": "60ce335832d2734814c020306a85d1e8b12cf67b"
            },
        ).resolve("dochub.yaml")


def test_project_seaf_overlay_is_content_addressed_and_strictly_resolvable(tmp_path):
    architecture_root = PKG_ROOT.parent / "architecture"
    upstream = (
        architecture_root
        / "vendor/seaf-core/entities/ta/presentation/components.yaml"
    )
    overlay_relative = (
        "overrides/seaf-core-v1.4.0/entities/ta/presentation/components.yaml"
    )
    overlay = architecture_root / overlay_relative

    assert hashlib.sha256(upstream.read_bytes()).hexdigest() == (
        "c784b57b54aa5f5ebab57f732d7088617661ac4d206493f39a4a6e9a6f628ad6"
    )
    assert hashlib.sha256(overlay.read_bytes()).hexdigest() == (
        "0af3c2c90a3a31257b2f38ba577590f1f32da048a72e2264fb80793b415efb7c"
    )
    assert overlay.read_text(encoding="utf-8") == upstream.read_text(
        encoding="utf-8"
    ).replace(
        "  seaf.ta.components.server:",
        "  seaf.ta.components.k8s_namespace:",
        1,
    )
    workspace = DocHubImportResolver(
        architecture_root,
        max_files=1024,
        max_depth=64,
        max_total_bytes=32 * 1024 * 1024,
        max_yaml_nodes=750_000,
    ).resolve("dochub.yaml")
    assert overlay_relative in workspace.paths
    assert (
        "vendor/seaf-core/entities/ta/presentation/components.yaml"
        not in workspace.paths
    )

    copied_root = tmp_path / "architecture"
    shutil.copytree(architecture_root, copied_root)
    copied_manifest = copied_root / "dochub.yaml"
    copied_manifest.write_text(
        copied_manifest.read_text(encoding="utf-8").replace(
            "seaf-core-v1.4.0-overlay.yaml",
            "vendor/seaf-core/dochub.yaml",
            1,
        ),
        encoding="utf-8",
    )
    copied_upstream = copied_root / (
        "vendor/seaf-core/entities/ta/presentation/components.yaml"
    )
    copied_upstream.write_text(overlay.read_text(encoding="utf-8"), encoding="utf-8")
    corrected_workspace = DocHubImportResolver(
        copied_root,
        max_files=1024,
        max_depth=64,
        max_total_bytes=32 * 1024 * 1024,
        max_yaml_nodes=750_000,
    ).resolve("dochub.yaml")

    import_only_aggregators = {
        "vendor/seaf-core/dochub.yaml",
        "vendor/seaf-core/entities/root.yaml",
        "vendor/seaf-core/entities/ta/root.yaml",
        "vendor/seaf-core/entities/ta/presentation/root.yaml",
    }

    def leaf_closure(paths):
        normalized = []
        for path in paths:
            if path in import_only_aggregators or path == "seaf-core-v1.4.0-overlay.yaml":
                continue
            normalized.append(
                "vendor/seaf-core/entities/ta/presentation/components.yaml"
                if path == overlay_relative
                else path
            )
        return tuple(normalized)

    assert leaf_closure(workspace.paths) == leaf_closure(corrected_workspace.paths)


def test_repository_revision_is_serialisable():
    revision = _revision("a" * 64)
    assert revision.as_dict()["base_commit"] == "1" * 40
    assert revision.to_dict()["rules_sha256"] == "5" * 64
