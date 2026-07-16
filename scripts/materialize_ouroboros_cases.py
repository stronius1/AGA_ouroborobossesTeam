#!/usr/bin/env python3
"""Persist locked synthetic-public evaluation cases for Ouroboros runs.

The independent evaluator historically materialized every case in a temporary
directory.  Ouroboros and the AGA MCP registry need a stable worktree for the
duration of a task, so this script publishes the same deterministic commits
under an ignored local directory.  Its manifest is local orchestration input:
repository paths are relative to the manifest directory and no ground-truth
labels or expected findings are copied into it.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping, Sequence
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from evaluation.gigaagent import runner  # noqa: E402


DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / ".tmp" / "ouroboros-cases"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = "aga.ouroboros-materialized-cases/v1"
DATA_CLASSIFICATION = "synthetic-public"


def _locked_cases() -> tuple[str, list[Mapping[str, Any]]]:
    paths = runner.corpus_files()
    digest = runner.verify_lock(paths)
    corpus = runner.load_yaml(runner.CORPUS)
    if not isinstance(corpus, Mapping) or corpus.get("data_policy") != DATA_CLASSIFICATION:
        raise ValueError("the locked corpus is not classified synthetic-public")
    return digest, runner._cases_from_paths(paths)


def _select_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    case_ids: Sequence[str] | None,
    split: str | None,
) -> list[Mapping[str, Any]]:
    if bool(case_ids) == bool(split):
        raise ValueError("select cases with either case_ids or split, but not both")
    if case_ids:
        requested = tuple(case_ids)
        if len(requested) != len(set(requested)):
            raise ValueError("case_ids must not contain duplicates")
        known = {str(case["id"]) for case in cases}
        unknown = sorted(set(requested) - known)
        if unknown:
            raise ValueError(f"unknown frozen case id(s): {', '.join(unknown)}")
        selected = [case for case in cases if case["id"] in set(requested)]
    else:
        if split not in {"development", "holdout", "all"}:
            raise ValueError("split must be development, holdout, or all")
        selected = list(cases) if split == "all" else [
            case for case in cases if case["split"] == split
        ]
    if not selected:
        raise ValueError("case selection is empty")
    return selected


def _prepare_output_root(output_root: Path) -> Path:
    root = output_root.expanduser()
    if root.exists():
        if root.is_symlink() or not root.is_dir():
            raise ValueError("output root must be a real directory")
    else:
        root.mkdir(mode=0o700, parents=True)
    return root


def _validate_existing_repository(
    repository: Path,
    expected: Mapping[str, Any],
) -> None:
    if repository.is_symlink() or not repository.is_dir():
        raise ValueError("persistent case path must be a real directory")
    top = Path(runner.git(repository, "rev-parse", "--show-toplevel")).resolve()
    if top != repository.resolve():
        raise ValueError("persistent case path is not the exact Git worktree root")
    head = runner.git(repository, "rev-parse", "--verify", "HEAD^{commit}")
    if head != expected["head"]:
        raise ValueError("persistent case HEAD differs from the locked materialization")
    runner.git(repository, "cat-file", "-e", f"{expected['base']}^{{commit}}")
    runner.git(
        repository,
        "merge-base",
        "--is-ancestor",
        str(expected["base"]),
        str(expected["head"]),
    )
    changed = runner.git(
        repository,
        "diff",
        "--name-only",
        str(expected["base"]),
        str(expected["head"]),
    ).splitlines()
    if changed != list(expected["changed_files"]):
        raise ValueError("persistent case diff differs from the locked materialization")
    if runner.git(repository, "status", "--porcelain"):
        raise ValueError("persistent case repository is dirty")


def _materialize_or_validate(
    case: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    repository = output_root / str(case["id"])
    if repository.exists() or repository.is_symlink():
        expected = runner.materialize_case(case)
        _validate_existing_repository(repository, expected)
        return expected

    staging = output_root / f".{case['id']}.staging-{uuid.uuid4().hex}"
    try:
        metadata = runner.materialize_case_at(case, staging)
        os.replace(staging, repository)
    finally:
        if staging.exists() or staging.is_symlink():
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            else:
                staging.unlink()
    return metadata


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def materialize_cases(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    case_ids: Sequence[str] | None = None,
    split: str | None = None,
) -> dict[str, Any]:
    """Materialize a locked selection and atomically publish its local manifest."""

    corpus_digest, cases = _locked_cases()
    selected = _select_cases(cases, case_ids=case_ids, split=split)
    root = _prepare_output_root(Path(output_root))
    records: list[dict[str, Any]] = []
    for case in selected:
        metadata = _materialize_or_validate(case, root)
        repository_relative = str(case["id"])
        if Path(repository_relative).is_absolute() or ".." in Path(repository_relative).parts:
            raise ValueError("repository path is not a safe manifest-relative path")
        records.append(
            {
                "case_id": case["id"],
                "split": case["split"],
                "repository_id": case["id"],
                "repository_path": repository_relative,
                "base_revision": metadata["base"],
                "head_revision": metadata["head"],
                "changed_files": list(metadata["changed_files"]),
                "data_classification": DATA_CLASSIFICATION,
            }
        )

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "corpus_hash": corpus_digest,
        "data_classification": DATA_CLASSIFICATION,
        "path_base": "manifest_directory",
        "cases": records,
    }
    _atomic_write_json(root / MANIFEST_NAME, manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Persist locked synthetic-public cases for the Ouroboros AGA runner"
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        metavar="CASE_ID",
        help="frozen case ID to materialize; repeat for multiple cases",
    )
    selection.add_argument(
        "--split",
        choices=("development", "holdout", "all"),
        help="materialize one frozen split or the complete basket",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="ignored persistent directory; repository paths in manifest.json stay relative",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        manifest = materialize_cases(
            output_root=arguments.output_root,
            case_ids=arguments.case_ids,
            split=arguments.split,
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"OUROBOROS MATERIALIZATION ERROR: {error}", file=sys.stderr)
        return 1
    summary = {
        "status": "materialized",
        "manifest": MANIFEST_NAME,
        "case_ids": [item["case_id"] for item in manifest["cases"]],
        "corpus_hash": manifest["corpus_hash"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
