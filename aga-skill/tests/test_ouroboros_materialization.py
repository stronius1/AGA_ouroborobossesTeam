# -*- coding: utf-8 -*-
"""Persistent Ouroboros case materialization contracts."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evaluation.gigaagent import runner  # noqa: E402
from scripts import materialize_ouroboros_cases as materializer  # noqa: E402


def _case(case_id: str):
    paths = runner.corpus_files()
    runner.verify_lock(paths)
    return next(case for case in runner._cases_from_paths(paths) if case["id"] == case_id)


def test_materialize_case_at_preserves_frozen_commit_identity(tmp_path: Path) -> None:
    case = _case("ga-05-critical-eliminate")
    persistent = tmp_path / "persistent"
    persistent.mkdir()

    actual = runner.materialize_case_at(case, persistent / case["id"])
    historical = runner.materialize_case(case)

    assert actual == historical
    assert re.fullmatch(r"[0-9a-f]{40}", actual["base"])
    assert re.fullmatch(r"[0-9a-f]{40}", actual["head"])
    assert actual["base"] != actual["head"]
    assert runner.git(persistent / case["id"], "status", "--porcelain") == ""
    with pytest.raises(ValueError, match="already exists"):
        runner.materialize_case_at(case, persistent / case["id"])


def test_persistent_manifest_is_relative_synthetic_public_and_idempotent(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "ouroboros-cases"
    case_ids = ("ga-05-critical-eliminate", "ga-16-semantic-clean")

    first = materializer.materialize_cases(
        output_root=output_root,
        case_ids=case_ids,
    )
    first_bytes = (output_root / materializer.MANIFEST_NAME).read_bytes()
    second = materializer.materialize_cases(
        output_root=output_root,
        case_ids=case_ids,
    )

    assert second == first
    assert (output_root / materializer.MANIFEST_NAME).read_bytes() == first_bytes
    assert first["schema"] == materializer.MANIFEST_SCHEMA
    assert first["data_classification"] == "synthetic-public"
    assert first["path_base"] == "manifest_directory"
    assert [item["case_id"] for item in first["cases"]] == list(case_ids)
    serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "expected" not in serialized
    assert "labels" not in serialized
    for item in first["cases"]:
        repository_path = Path(item["repository_path"])
        assert not repository_path.is_absolute()
        assert ".." not in repository_path.parts
        assert (output_root / repository_path / ".git").is_dir()
        assert item["repository_id"] == item["case_id"]
        assert item["data_classification"] == "synthetic-public"


def test_lock_failure_writes_no_persistent_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "must-not-exist"

    def reject_lock(_paths):
        raise ValueError("synthetic lock mismatch")

    monkeypatch.setattr(materializer.runner, "verify_lock", reject_lock)
    with pytest.raises(ValueError, match="lock mismatch"):
        materializer.materialize_cases(
            output_root=output_root,
            case_ids=("ga-05-critical-eliminate",),
        )
    assert not output_root.exists()


def test_dirty_persistent_case_cannot_replace_last_valid_manifest(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "ouroboros-cases"
    materializer.materialize_cases(
        output_root=output_root,
        case_ids=("ga-05-critical-eliminate",),
    )
    manifest_path = output_root / materializer.MANIFEST_NAME
    trusted_manifest = manifest_path.read_bytes()
    repository = output_root / "ga-05-critical-eliminate"
    (repository / "untracked.yaml").write_text("synthetic: drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="repository is dirty"):
        materializer.materialize_cases(
            output_root=output_root,
            case_ids=("ga-05-critical-eliminate",),
        )
    assert manifest_path.read_bytes() == trusted_manifest
