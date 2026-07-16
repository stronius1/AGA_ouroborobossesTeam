# -*- coding: utf-8 -*-
"""Offline tests for trusted, Git-object-backed repository snapshots."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))
PROJECT_EXTENSION_TEXT = (
    PKG_ROOT.parent / "architecture" / "metamodel" / "aga-extension.yaml"
).read_text(encoding="utf-8")

from tools.git_cleanliness import (  # noqa: E402
    CheckoutCleanlinessError,
    DEFAULT_CLEANLINESS_LIMITS,
    assert_clean_checkout,
)
from tools.repository_snapshot import RepositorySnapshotBuilder  # noqa: E402
from tools.seaf_native import SeafCanonicalAdapter  # noqa: E402
from tools.seaf_review import prepare_seaf_review  # noqa: E402
from tools.validation import ValidationError  # noqa: E402


ARCHTOOL_COMMIT = "1" * 40
SEAF_CORE_COMMIT = "2" * 40


def _git(repository: Path, *arguments: str, commit_number: int | None = None) -> str:
    environment = os.environ.copy()
    if commit_number is not None:
        timestamp = f"2001-01-{commit_number:02d}T00:00:00+0000"
        environment.update({
            "GIT_AUTHOR_NAME": "AGA Synthetic Fixture",
            "GIT_AUTHOR_EMAIL": "aga-fixture@example.invalid",
            "GIT_COMMITTER_NAME": "AGA Synthetic Fixture",
            "GIT_COMMITTER_EMAIL": "aga-fixture@example.invalid",
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
        })
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return completed.stdout.strip()


def _write(repository: Path, relative: str, text: str) -> None:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repository: Path, message: str, number: int) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "-m", message, commit_number=number)
    return _git(repository, "rev-parse", "HEAD")


def _synthetic_repository(tmp_path: Path) -> tuple[Path, str, str]:
    repository = tmp_path / "synthetic-seaf"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "AGA Synthetic Fixture")
    _git(repository, "config", "user.email", "aga-fixture@example.invalid")

    _write(repository, "dochub.yaml", """aga:
  schema: seaf-core/v1.4.0
  extensions:
    - aga.project/v1
  data_classification: synthetic-public
imports:
  - architecture/aga-extension.yaml
  - architecture/components.yaml
  - architecture/integrations.yaml
  - architecture/contexts.yaml
""")
    _write(repository, "architecture/aga-extension.yaml", PROJECT_EXTENSION_TEXT)
    _write(repository, "architecture/components.yaml", """components:
  synthetic.orders:
    title: Synthetic Orders
    entity: component
    owner: synthetic-team
""")
    _write(repository, "architecture/integrations.yaml", """seaf.app.integrations:
  synthetic.orders-to-payments:
    from: synthetic.orders
    to: synthetic.payments
    protocol: HTTPS
""")
    _write(repository, "architecture/contexts.yaml", """contexts:
  synthetic.landscape:
    title: Synthetic landscape
    presentation: plantuml
    template: diagrams/landscape.puml
""")
    _write(repository, "architecture/diagrams/landscape.puml", """@startuml
component \"Synthetic Orders\" as orders
component \"Synthetic Payments\" as payments
orders --> payments : HTTPS
@enduml
""")
    _write(repository, "notes/retired.md", "Synthetic note removed at head.\n")
    base = _commit(repository, "synthetic SEAF base", 1)

    _write(repository, "architecture/components.yaml", """components:
  synthetic.orders:
    title: Synthetic Order Service
    entity: component
    owner: synthetic-team
  synthetic.payments:
    title: Synthetic Payment Service
    entity: component
    owner: synthetic-team
""")
    (repository / "notes/retired.md").unlink()
    _write(repository, "notes/added.md", "Synthetic note added at head.\n")
    head = _commit(repository, "synthetic SEAF head", 2)
    return repository, base, head


def _repository_with_dependency(
    tmp_path: Path, *, filter_attributes: bool = False,
) -> tuple[Path, Path, str, str, str, str]:
    dependency_source = tmp_path / "seaf-core-source"
    dependency_source.mkdir()
    _git(dependency_source, "init", "--quiet")
    _git(dependency_source, "config", "user.name", "AGA Synthetic Fixture")
    _git(dependency_source, "config", "user.email", "aga-fixture@example.invalid")
    _write(dependency_source, "dochub.yaml", "imports:\n  - model.yaml\n")
    _write(dependency_source, "model.yaml", """contexts:
  seaf.core.synthetic:
    title: Pinned SEAF core context
    presentation: plantuml
    template: diagrams/core.puml
""")
    _write(dependency_source, "diagrams/core.puml", """@startuml
component "Pinned SEAF core"
@enduml
""")
    _write(dependency_source, "unused.yaml", "unused: true\n")
    if filter_attributes:
        _write(dependency_source, ".gitattributes", "*.txt filter=evil\n")
        _write(dependency_source, "filtered.txt", "synthetic clean content\n")
    dependency_commit = _commit(dependency_source, "pinned synthetic seaf-core", 1)

    repository = tmp_path / "seaf-superproject"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "AGA Synthetic Fixture")
    _git(repository, "config", "user.email", "aga-fixture@example.invalid")
    dependency_path = "architecture/vendor/seaf-core"
    _git(
        repository,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "--quiet",
        str(dependency_source),
        dependency_path,
    )
    _write(repository, "dochub.yaml", f"""aga:
  schema: seaf-core/v1.4.0
  extensions:
    - aga.project/v1
  data_classification: synthetic-public
imports:
  - architecture/aga-extension.yaml
  - architecture/project.yaml
  - {dependency_path}/dochub.yaml
""")
    _write(repository, "architecture/aga-extension.yaml", PROJECT_EXTENSION_TEXT)
    _write(repository, "architecture/project.yaml", "components: {}\n")
    base = _commit(repository, "superproject base", 3)
    _write(repository, "architecture/project.yaml", """components:
  synthetic.project:
    title: Synthetic project
    entity: component
    owner: synthetic-team
    criticality: low
    target_status: strategic
""")
    head = _commit(repository, "superproject head", 4)
    checkout = repository / dependency_path
    return repository, checkout, dependency_path, dependency_commit, base, head


def _dependency_builder(
    repository: Path,
    checkout: Path,
    dependency_path: str,
    dependency_commit: str,
    base: str,
    head: str,
) -> RepositorySnapshotBuilder:
    return RepositorySnapshotBuilder(
        repository,
        base,
        head,
        archtool_commit=ARCHTOOL_COMMIT,
        seaf_core_commit=dependency_commit,
        dependency_mode="fixture",
        trusted_dependencies={
            dependency_path: {
                "checkout": checkout,
                "commit": dependency_commit,
            }
        },
        aga_version="2.0.0-test",
    )


def _builder(repository: Path, base: str, head: str) -> RepositorySnapshotBuilder:
    return RepositorySnapshotBuilder(
        repository,
        base,
        head,
        archtool_commit=ARCHTOOL_COMMIT,
        seaf_core_commit=SEAF_CORE_COMMIT,
        dependency_mode="fixture",
        aga_version="2.0.0-test",
    )


def test_git_snapshot_uses_base_and_head(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)
    # This is deliberately neither committed nor valid SEAF. A trusted
    # snapshot must still contain the selected head blob.
    _write(repository, "architecture/components.yaml", "WORKTREE MUST NOT BE READ\n")

    with _builder(repository, base, head).build() as snapshot:
        staged = (snapshot.root / "architecture/components.yaml").read_text(encoding="utf-8")
        assert snapshot.revision.base_commit == base
        assert snapshot.revision.head_commit == head
        assert snapshot.changed_paths == (
            "architecture/components.yaml",
            "notes/added.md",
            "notes/retired.md",
        )
        assert snapshot.changed_statuses == {
            "architecture/components.yaml": "modified",
            "notes/added.md": "added",
            "notes/retired.md": "deleted",
        }
        artifact_by_path = {artifact.path: artifact for artifact in snapshot.changed_artifacts}
        assert artifact_by_path["architecture/components.yaml"].sha256 is not None
        assert artifact_by_path["notes/added.md"].sha256 is not None
        assert artifact_by_path["notes/retired.md"].sha256 is not None
        assert artifact_by_path["notes/retired.md"].source_ref.commit == base
        assert "notes/added.md" in snapshot.materialized_paths
        assert "Synthetic Payment Service" in staged
        assert "WORKTREE MUST NOT BE READ" not in staged


def test_manifest_cannot_omit_changed_file(tmp_path: Path) -> None:
    repository, base, _ = _synthetic_repository(tmp_path)
    _write(repository, "architecture/omitted.yaml", "components:\n  omitted: {title: Omitted}\n")
    head = _commit(repository, "changed YAML omitted from manifest", 3)

    with pytest.raises(ValidationError) as caught:
        _builder(repository, base, head).build()
    assert caught.value.code == "manifest_omits_changed_file"
    assert "architecture/omitted.yaml" in str(caught.value)


def test_manifest_cannot_omit_changed_diagram(tmp_path: Path) -> None:
    repository, base, _ = _synthetic_repository(tmp_path)
    _write(repository, "architecture/diagrams/orphan.puml", "@startuml\n@enduml\n")
    head = _commit(repository, "add unreferenced diagram", 3)

    with pytest.raises(ValidationError) as caught:
        _builder(repository, base, head).build()

    assert caught.value.code == "manifest_omits_changed_file"
    assert caught.value.field == "changed_paths"
    assert "architecture/diagrams/orphan.puml" in str(caught.value)


def test_context_closure_is_materialized(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)

    with _builder(repository, base, head).build() as snapshot:
        expected = "architecture/diagrams/landscape.puml"
        assert expected in snapshot.context_paths
        assert (snapshot.root / expected).read_text(encoding="utf-8").startswith("@startuml")
        resolved = snapshot.resolve()
        assert "architecture/contexts.yaml" in resolved.import_paths
        assert set(snapshot.materialized_paths) == {
            "dochub.yaml",
            "architecture/aga-extension.yaml",
            "architecture/components.yaml",
            "architecture/integrations.yaml",
            "architecture/contexts.yaml",
            expected,
            "notes/added.md",
        }


def test_manifest_directory_is_a_trusted_review_scope(tmp_path: Path) -> None:
    repository = tmp_path / "scoped"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "AGA Synthetic Fixture")
    _git(repository, "config", "user.email", "aga-fixture@example.invalid")
    _write(repository, "architecture/dochub.yaml", "imports: [model.yaml]\n")
    _write(repository, "architecture/model.yaml", "components: {}\n")
    _write(repository, "docs/note.md", "base note\n")
    base = _commit(repository, "scoped base", 1)
    _write(repository, "architecture/model.yaml", "components: {demo: {title: Demo}}\n")
    _write(repository, "docs/note.md", "head note\n")
    head = _commit(repository, "scoped head", 2)

    with RepositorySnapshotBuilder(
        repository,
        base,
        head,
        manifest_path="architecture/dochub.yaml",
        archtool_commit=ARCHTOOL_COMMIT,
        seaf_core_commit=SEAF_CORE_COMMIT,
        dependency_mode="fixture",
        aga_version="2.0.0-test",
    ).build() as snapshot:
        assert snapshot.review_scope == "architecture/"
        assert snapshot.changed_paths == ("architecture/model.yaml",)
        assert snapshot.ignored_out_of_scope_paths == ("docs/note.md",)
        assert snapshot.review_provenance["ignored_out_of_scope_paths"] == ["docs/note.md"]


def test_review_provenance_contains_all_commits(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)

    with _builder(repository, base, head).build() as snapshot:
        provenance = snapshot.review_provenance
        assert provenance["base_commit"] == base
        assert provenance["head_commit"] == head
        assert provenance["archtool_commit"] == ARCHTOOL_COMMIT
        assert provenance["seaf_core_commit"] == SEAF_CORE_COMMIT
        assert provenance["dependency_verification"] == "fixture-unverified"
        assert provenance["aga_version"] == "2.0.0-test"
        assert len(provenance["manifest_sha256"]) == 64
        assert len(provenance["rules_sha256"]) == 64


def test_verified_mode_requires_both_pinned_gitlinks(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)

    with pytest.raises(ValidationError) as caught:
        RepositorySnapshotBuilder(repository, base, head)

    assert caught.value.code == "dependency_provenance_unverified"
    assert caught.value.field == "trusted_dependencies"


def test_verified_mode_accepts_both_exact_clean_gitlinks(tmp_path: Path) -> None:
    repository, seaf_checkout, seaf_path, seaf_commit, _, existing_head = (
        _repository_with_dependency(tmp_path)
    )
    archtool_source = tmp_path / "archtool-source"
    archtool_source.mkdir()
    _git(archtool_source, "init", "--quiet")
    _git(archtool_source, "config", "user.name", "AGA Synthetic Fixture")
    _git(archtool_source, "config", "user.email", "aga-fixture@example.invalid")
    _write(archtool_source, "README.md", "Synthetic ArchTool dependency.\n")
    archtool_commit = _commit(archtool_source, "pinned synthetic ArchTool", 1)
    archtool_path = "seaf-archtool-core"
    _git(
        repository,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "--quiet",
        str(archtool_source),
        archtool_path,
    )
    dependency_base = _commit(repository, "both verified dependencies", 5)
    assert dependency_base != existing_head
    _write(
        repository,
        "architecture/project.yaml",
        """components:
  synthetic.project:
    title: Synthetic project v2
    owner: synthetic-team
    criticality: low
    target_status: strategic
""",
    )
    head = _commit(repository, "verified architecture change", 6)

    with RepositorySnapshotBuilder(
        repository,
        dependency_base,
        head,
        archtool_commit=archtool_commit,
        seaf_core_commit=seaf_commit,
        dependency_mode="verified",
        trusted_dependencies={
            archtool_path: {
                "checkout": repository / archtool_path,
                "commit": archtool_commit,
            },
            seaf_path: {"checkout": seaf_checkout, "commit": seaf_commit},
        },
        aga_version="2.0.0-test",
    ).build() as snapshot:
        assert snapshot.dependency_verification == "verified-gitlinks"
        assert set(snapshot.review_provenance["trusted_dependencies"]) == {
            archtool_path,
            seaf_path,
        }


def test_repeat_review_is_deterministic(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)
    first = _builder(repository, base, head).build()
    second = _builder(repository, base, head).build()
    try:
        assert first.root != second.root
        assert first == second
        assert first.as_dict() == second.as_dict()
        assert {
            path: (first.root / path).read_bytes()
            for path in first.materialized_paths
        } == {
            path: (second.root / path).read_bytes()
            for path in second.materialized_paths
        }
    finally:
        first.close()
        second.close()


def test_snapshot_resolve_rejects_staging_tamper(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)
    snapshot = _builder(repository, base, head).build()
    try:
        target = snapshot.root / "architecture/components.yaml"
        target.write_text("components: {}\n", encoding="utf-8")
        with pytest.raises(ValidationError) as caught:
            snapshot.resolve()
        assert caught.value.code == "snapshot_integrity_mismatch"
    finally:
        snapshot.close()


def test_trusted_gitlink_dependency_closure_is_materialized(tmp_path: Path) -> None:
    repository, checkout, dependency_path, dependency_commit, base, head = (
        _repository_with_dependency(tmp_path)
    )

    with _dependency_builder(
        repository, checkout, dependency_path, dependency_commit, base, head
    ).build() as snapshot:
        expected = f"{dependency_path}/diagrams/core.puml"
        assert expected in snapshot.materialized_paths
        assert (snapshot.root / expected).read_text(encoding="utf-8").startswith("@startuml")
        assert f"{dependency_path}/unused.yaml" not in snapshot.materialized_paths
        workspace = snapshot.resolve()
        assert f"{dependency_path}/dochub.yaml" in workspace.import_paths
        canonical = SeafCanonicalAdapter().adapt(
            workspace,
            revision=snapshot.revision,
            changed_artifacts=snapshot.changed_artifacts,
        )
        dependency_diagram = next(
            diagram for diagram in canonical.diagrams if diagram.id == "seaf.core.synthetic"
        )
        assert dependency_diagram.source_ref.commit == dependency_commit
        dependency = snapshot.review_provenance["trusted_dependencies"][dependency_path]
        assert dependency["commit"] == dependency_commit
        assert len(dependency["closure_sha256"]) == 64


def test_trusted_dependency_wrong_pin_is_rejected(tmp_path: Path) -> None:
    repository, checkout, dependency_path, _, base, head = _repository_with_dependency(tmp_path)
    wrong_pin = "f" * 40
    builder = _dependency_builder(
        repository, checkout, dependency_path, wrong_pin, base, head
    )

    with pytest.raises(ValidationError) as caught:
        builder.build()
    assert caught.value.code == "dependency_gitlink_mismatch"


def test_trusted_dependency_dirty_checkout_is_rejected(tmp_path: Path) -> None:
    repository, checkout, dependency_path, dependency_commit, base, head = (
        _repository_with_dependency(tmp_path)
    )
    _write(checkout, "model.yaml", "contexts: {}\n")
    builder = _dependency_builder(
        repository, checkout, dependency_path, dependency_commit, base, head
    )

    with pytest.raises(ValidationError) as caught:
        builder.build()
    assert caught.value.code == "dependency_checkout_dirty"


def test_trusted_dependency_clean_filter_is_never_executed(
    tmp_path: Path,
) -> None:
    repository, checkout, dependency_path, dependency_commit, base, head = (
        _repository_with_dependency(tmp_path, filter_attributes=True)
    )
    marker = tmp_path / "builder-filter-marker"
    filter_script = tmp_path / "evil-clean-filter.sh"
    filter_script.write_text(
        '#!/bin/sh\nprintf invoked > "$1"\ncat\n',
        encoding="utf-8",
    )
    filter_script.chmod(0o700)
    _git(
        checkout,
        "config",
        "filter.evil.clean",
        f"{shlex.quote(str(filter_script))} {shlex.quote(str(marker))}",
    )
    _write(checkout, "filtered.txt", "synthetic modified content\n")
    builder = _dependency_builder(
        repository, checkout, dependency_path, dependency_commit, base, head
    )

    with pytest.raises(ValidationError) as caught:
        builder.build()
    assert caught.value.code == "dependency_checkout_dirty"
    assert not marker.exists()


def test_trusted_dependency_untracked_enumeration_is_bounded_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, checkout, dependency_path, dependency_commit, base, head = (
        _repository_with_dependency(tmp_path)
    )
    for index in range(80):
        _write(
            checkout,
            f"untracked/{index:03d}-{'x' * 80}.yaml",
            "synthetic untracked payload\n",
        )
    builder = _dependency_builder(
        repository, checkout, dependency_path, dependency_commit, base, head
    )
    real_run_git = builder._run_git
    dependency_calls: list[tuple[tuple[str, ...], int | None]] = []

    def recording_run_git(
        git_repository: Path,
        arguments: list[str],
        *,
        max_stdout_bytes: int | None = None,
    ) -> bytes:
        if git_repository == checkout:
            dependency_calls.append((tuple(arguments), max_stdout_bytes))
        return real_run_git(
            git_repository,
            arguments,
            max_stdout_bytes=max_stdout_bytes,
        )

    monkeypatch.setattr(builder, "_run_git", recording_run_git)
    with pytest.raises(ValidationError) as caught:
        builder.build()
    assert caught.value.code == "dependency_checkout_dirty"
    assert all(arguments[0] != "status" for arguments, _ in dependency_calls)
    assert (
        ("ls-tree", "-r", "-z", "-l", "--full-tree", dependency_commit),
        DEFAULT_CLEANLINESS_LIMITS.max_metadata_bytes,
    ) in dependency_calls
    assert (
        ("ls-files", "--stage", "-z"),
        DEFAULT_CLEANLINESS_LIMITS.max_metadata_bytes,
    ) in dependency_calls


def test_cleanliness_rejects_ambiguous_alternate_object_path(tmp_path: Path) -> None:
    colon_root = tmp_path / "synthetic:colon"
    colon_root.mkdir()
    repository, checkout, dependency_path, dependency_commit, base, head = (
        _repository_with_dependency(colon_root)
    )
    builder = _dependency_builder(
        repository, checkout, dependency_path, dependency_commit, base, head
    )

    with pytest.raises(CheckoutCleanlinessError, match="ambiguous"):
        assert_clean_checkout(
            checkout,
            dependency_commit,
            lambda arguments, cap: builder._run_git(
                checkout,
                arguments,
                max_stdout_bytes=cap,
            ),
        )


def test_snapshot_git_environment_ignores_hostile_git_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, _, previous_head = _synthetic_repository(tmp_path)
    hostile_bare = tmp_path / "hostile.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(repository), str(hostile_bare)],
        check=True,
        capture_output=True,
    )
    _write(repository, "notes/git-hardening.md", "Synthetic hardening change.\n")
    head = _commit(repository, "synthetic Git hardening", 3)

    monkeypatch.setenv("GIT_DIR", str(hostile_bare))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")

    with _builder(repository, previous_head, head).build() as snapshot:
        assert snapshot.revision.head_commit == head
        assert snapshot.changed_paths == ("notes/git-hardening.md",)


def test_snapshot_rejects_bare_repository_root(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(repository), str(bare)],
        check=True,
        capture_output=True,
    )

    with pytest.raises(ValidationError) as caught:
        _builder(bare, base, head)
    assert caught.value.code == "invalid_repository"


def test_deleted_blob_bytes_are_charged_to_aggregate_limit(tmp_path: Path) -> None:
    repository = tmp_path / "deleted-byte-limit"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "AGA Synthetic Fixture")
    _git(repository, "config", "user.email", "aga-fixture@example.invalid")
    _write(repository, "dochub.yaml", """aga:
  schema: seaf-core/v1.4.0
  extensions:
    - aga.project/v1
  data_classification: synthetic-public
imports:
  - architecture/aga-extension.yaml
  - architecture/project.yaml
""")
    _write(repository, "architecture/aga-extension.yaml", PROJECT_EXTENSION_TEXT)
    _write(repository, "architecture/project.yaml", "components: {}\n")
    deleted = "synthetic deleted payload " * 20
    _write(repository, "architecture/deleted.txt", deleted)
    base = _commit(repository, "base with synthetic deleted payload", 7)
    (repository / "architecture/deleted.txt").unlink()
    head = _commit(repository, "delete synthetic payload", 8)

    head_closure_bytes = sum(
        (repository / relative).stat().st_size
        for relative in (
            "dochub.yaml",
            "architecture/aga-extension.yaml",
            "architecture/project.yaml",
        )
    )
    builder = RepositorySnapshotBuilder(
        repository,
        base,
        head,
        archtool_commit=ARCHTOOL_COMMIT,
        seaf_core_commit=SEAF_CORE_COMMIT,
        dependency_mode="fixture",
        aga_version="2.0.0-test",
        max_total_bytes=head_closure_bytes + len(deleted.encode("utf-8")) - 1,
    )
    with pytest.raises(ValidationError) as caught:
        builder.build()
    assert caught.value.code == "snapshot_too_large"


def test_git_diff_output_is_stream_capped_before_parsing(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)
    builder = RepositorySnapshotBuilder(
        repository,
        base,
        head,
        archtool_commit=ARCHTOOL_COMMIT,
        seaf_core_commit=SEAF_CORE_COMMIT,
        dependency_mode="fixture",
        aga_version="2.0.0-test",
        max_total_bytes=20,
    )
    with pytest.raises(ValidationError) as caught:
        builder.build()
    assert caught.value.code == "snapshot_too_large"


def test_rules_must_still_match_the_snapshot_digest_at_prepare(tmp_path: Path) -> None:
    repository, base, head = _synthetic_repository(tmp_path)
    rules = tmp_path / "rules"
    shutil.copytree(PKG_ROOT / "rules", rules)
    snapshot = RepositorySnapshotBuilder(
        repository,
        base,
        head,
        archtool_commit=ARCHTOOL_COMMIT,
        seaf_core_commit=SEAF_CORE_COMMIT,
        dependency_mode="fixture",
        aga_version="2.0.0-test",
        rules_dir=rules,
    ).build()
    try:
        principles = rules / "principles.yaml"
        principles.write_text(
            principles.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ValidationError) as caught:
            prepare_seaf_review(snapshot, rules_dir=rules)
        assert caught.value.code == "rules_provenance_mismatch"
    finally:
        snapshot.close()
