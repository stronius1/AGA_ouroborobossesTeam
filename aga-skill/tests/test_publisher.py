# -*- coding: utf-8 -*-
"""Local-only Loop-A publisher contracts and real Git integration."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PKG_ROOT.parent
sys.path.insert(0, str(PKG_ROOT))

import tools.publisher as publisher_module  # noqa: E402
from tools.publisher import (  # noqa: E402
    LocalCandidatePublisher,
    LocalCandidateRequest,
    PublisherError,
    PublisherPolicyError,
    PublisherValidationError,
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "AGA Test",
    "GIT_AUTHOR_EMAIL": "aga-test@example.invalid",
    "GIT_COMMITTER_NAME": "AGA Test",
    "GIT_COMMITTER_EMAIL": "aga-test@example.invalid",
}
CYCLE_ID = "aga-20260719T120000Z-a1b2c3d4"
BRANCH = "skill/evolution-2026-07-19-PRIN-002-a1b2c3d4"


def _run(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    )
    return completed.stdout.strip()


def _status(repo: Path) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v2", "-z", "--untracked-files=all"],
        check=True,
        capture_output=True,
    ).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    directory = tmp_path / "repo"
    directory.mkdir()
    base_files = {
        "aga-skill/rules/principles.yaml": b"rules:\n  - id: PRIN-002\n    exceptions: []\n",
        "aga-skill/VERSION": b"2.0.0\n",
        "aga-skill/CHANGELOG.md": b"# Changelog\n\n## v2.0.0\n- base\n",
        "aga-skill/precedents/cases/0001-case.md": b"---\nstatus: pending\n---\n# Case\n",
        "unrelated.txt": b"base\n",
    }
    for relative, payload in base_files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    _run(directory, "init", "-q", "--initial-branch=main")
    _run(directory, "config", "user.name", GIT_ENV["GIT_AUTHOR_NAME"])
    _run(directory, "config", "user.email", GIT_ENV["GIT_AUTHOR_EMAIL"])
    _run(directory, "add", "-A")
    _run(directory, "commit", "-q", "-m", "base")
    return directory


def _request(repo: Path) -> LocalCandidateRequest:
    rule = "aga-skill/rules/principles.yaml"
    version = "aga-skill/VERSION"
    changelog = "aga-skill/CHANGELOG.md"
    precedent = "aga-skill/precedents/cases/0001-case.md"
    report = f"docs/evidence/evolution/{CYCLE_ID}.md"
    manifest = f"docs/evidence/evolution/{CYCLE_ID}.json"
    base_bindings = {
        rule: (repo / rule).read_bytes(),
        version: (repo / version).read_bytes(),
        changelog: (repo / changelog).read_bytes(),
        precedent: (repo / precedent).read_bytes(),
    }
    files = {
        rule: b"rules:\n  - id: PRIN-002\n    exceptions:\n      - id: EXC-001\n",
        version: b"2.1.0\n",
        changelog: b"# Changelog\n\n## v2.1.0\n- candidate\n\n## v2.0.0\n- base\n",
        precedent: b"---\nstatus: distilled\ndistilled_in: 2.1.0\n---\n# Case\n",
        report: b"# Candidate report\n",
        manifest: b'{"schema":"aga.local-candidate-evidence/v1"}\n',
    }
    return LocalCandidateRequest(
        cycle_id=CYCLE_ID,
        base_commit=_run(repo, "rev-parse", "HEAD"),
        branch_name=BRANCH,
        commit_message="AGA candidate 2.0.0 -> 2.1.0",
        files=files,
        base_bindings=base_bindings,
        changed_rule_paths=(rule,),
        precedent_path=precedent,
        report_path=report,
        manifest_path=manifest,
    )


def test_local_candidate_commit_is_exact_idempotent_and_preserves_dirty_caller(
    repo: Path,
) -> None:
    request = _request(repo)
    (repo / "unrelated.txt").write_text("staged user change\n", encoding="utf-8")
    _run(repo, "add", "unrelated.txt")
    (repo / "caller-untracked.txt").write_text("user data\n", encoding="utf-8")
    before_status = _status(repo)
    before_head = _run(repo, "rev-parse", "HEAD")

    publisher = LocalCandidatePublisher(repository_root=repo)
    result = publisher.publish(request)

    assert result.status == "local_candidate_ready"
    assert result.external_side_effects is False
    assert result.draft_pr_url is None
    assert result.human_review_required is True
    assert result.auto_merge is False
    assert result.commit and result.branch_name == BRANCH
    assert _run(repo, "rev-parse", "HEAD") == before_head
    assert _run(repo, "branch", "--show-current") == "main"
    assert _status(repo) == before_status
    assert set(
        _run(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", BRANCH).splitlines()
    ) == set(request.files)
    assert _run(repo, "rev-parse", f"{BRANCH}^") == before_head

    repeated = publisher.publish(request)
    assert repeated.commit == result.commit
    assert repeated.details["idempotent"] is True
    assert repeated.details["local_commit_created"] is False
    assert _status(repo) == before_status


def test_commit_failure_rolls_back_worktree_index_and_branch(repo: Path) -> None:
    request = _request(repo)
    before_status = _status(repo)
    before_head = _run(repo, "rev-parse", "HEAD")

    def failing_runner(args, **kwargs):
        if "commit" in args[3:]:
            return subprocess.CompletedProcess(args, 9, stdout=b"", stderr=b"failed")
        return subprocess.run(args, **kwargs)

    publisher = LocalCandidatePublisher(repository_root=repo, runner=failing_runner)
    with pytest.raises(PublisherError, match="git commit failed"):
        publisher.publish(request)

    assert _run(repo, "rev-parse", "HEAD") == before_head
    assert _status(repo) == before_status
    absent = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{BRANCH}"],
        check=False,
    )
    assert absent.returncode == 1
    assert _run(repo, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_local_candidate_commit_disables_repository_hooks(repo: Path) -> None:
    marker = repo / "hook-ran"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 9\n", encoding="utf-8")
    hook.chmod(0o755)

    result = LocalCandidatePublisher(repository_root=repo).publish(_request(repo))

    assert result.status == "local_candidate_ready"
    assert not marker.exists()


def test_local_candidate_rejects_executable_clean_filters(repo: Path) -> None:
    (repo / ".gitattributes").write_text(
        "aga-skill/VERSION filter=untrusted\n",
        encoding="utf-8",
    )
    _run(repo, "add", ".gitattributes")
    _run(repo, "commit", "-q", "-m", "declare filter")

    with pytest.raises(PublisherValidationError, match="executable Git filters"):
        LocalCandidatePublisher(repository_root=repo).publish(_request(repo))


def test_target_base_binding_mismatch_fails_before_any_write(repo: Path) -> None:
    request = _request(repo)
    bindings = dict(request.base_bindings)
    bindings["aga-skill/VERSION"] = b"forged\n"
    forged = LocalCandidateRequest(
        **{**request.__dict__, "base_bindings": bindings}
    )
    before = _status(repo)
    with pytest.raises(PublisherValidationError, match="base binding differs"):
        LocalCandidatePublisher(repository_root=repo).publish(forged)
    assert _status(repo) == before
    assert _run(repo, "branch", "--list", BRANCH) == ""


def test_candidate_evidence_cannot_follow_tracked_directory_symlink(
    repo: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "docs").symlink_to(outside, target_is_directory=True)
    _run(repo, "add", "docs")
    _run(repo, "commit", "-q", "-m", "tracked symlink")
    request = _request(repo)

    with pytest.raises(PublisherValidationError, match="contains a symlink"):
        LocalCandidatePublisher(repository_root=repo).publish(request)

    assert list(outside.iterdir()) == []
    assert _run(repo, "branch", "--list", BRANCH) == ""


def test_network_pr_merge_approve_and_push_surfaces_do_not_exist(repo: Path) -> None:
    publisher = LocalCandidatePublisher(repository_root=repo)
    assert publisher.requires_network is False
    assert not hasattr(publisher_module, "DraftPRPublisher")
    for method in (
        publisher.merge,
        publisher.approve,
        publisher.approve_pr,
        publisher.push,
        publisher.push_to_main,
        publisher.open_pull_request,
    ):
        with pytest.raises(PublisherPolicyError):
            method()


def _full_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "project"
    repository.mkdir()
    shutil.copytree(
        PKG_ROOT,
        repository / "aga-skill",
        ignore=shutil.ignore_patterns(
            ".venv", "build", "__pycache__", ".pytest_cache", "*.pyc"
        ),
    )
    shutil.copy2(PROJECT_ROOT / ".gitignore", repository / ".gitignore")
    _run(repository, "init", "-q", "--initial-branch=main")
    _run(repository, "config", "user.name", GIT_ENV["GIT_AUTHOR_NAME"])
    _run(repository, "config", "user.email", GIT_ENV["GIT_AUTHOR_EMAIL"])
    _run(repository, "add", "-A")
    _run(repository, "commit", "-q", "-m", "base")
    return repository


def test_full_loop_a_cli_creates_complete_local_candidate(tmp_path: Path) -> None:
    repository = _full_repository(tmp_path)
    package = repository / "aga-skill"
    evolved = subprocess.run(
        ["python3", "scripts/run_evolution.py", "--demo"],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert evolved.returncode == 0, evolved.stdout + evolved.stderr

    # A dirty caller index/worktree is allowed because candidate materialization
    # happens in a separate worktree and is bound to committed protected inputs.
    readme = package / "README.md"
    readme.write_bytes(readme.read_bytes() + b"\n<!-- unrelated staged user work -->\n")
    _run(repository, "add", "aga-skill/README.md")
    (repository / "untracked-user-note.txt").write_text("keep me\n", encoding="utf-8")
    before_status = _status(repository)
    before_head = _run(repository, "rev-parse", "HEAD")

    published = subprocess.run(
        [
            "python3",
            "scripts/publish_candidate.py",
            "--build",
            "build",
            "--repository",
            str(repository),
            "--actor",
            "Test Architect",
        ],
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert published.returncode == 0, published.stdout + published.stderr
    result = json.loads(published.stdout)
    assert result["status"] == "local_candidate_ready"
    assert result["external_side_effects"] is False
    assert result["draft_pr_url"] is None
    assert result["human_review_required"] is True
    assert result["auto_merge"] is False
    assert result["base_commit"] == before_head
    assert _run(repository, "rev-parse", "HEAD") == before_head
    assert _status(repository) == before_status

    branch = result["branch_name"]
    cycle = result["cycle_id"]
    expected_paths = {
        "aga-skill/rules/principles.yaml",
        "aga-skill/VERSION",
        "aga-skill/CHANGELOG.md",
        "aga-skill/precedents/cases/0001-dmz-file-exchange.md",
        f"docs/evidence/evolution/{cycle}.md",
        f"docs/evidence/evolution/{cycle}.json",
    }
    actual_paths = set(
        _run(
            repository,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            branch,
        ).splitlines()
    )
    assert actual_paths == expected_paths
    assert _run(repository, "show", f"{branch}:aga-skill/VERSION") == "2.1.0"
    changelog = _run(repository, "show", f"{branch}:aga-skill/CHANGELOG.md")
    assert changelog.startswith("# Changelog\n\n## v2.1.0")
    precedent = _run(
        repository,
        "show",
        f"{branch}:aga-skill/precedents/cases/0001-dmz-file-exchange.md",
    )
    assert "status: distilled" in precedent
    assert "distilled_in: 2.1.0" in precedent
    assert _run(repository, "show", f"main:aga-skill/VERSION") == "2.0.0"

    repeated = subprocess.run(
        published.args,
        cwd=package,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    repeated_result = json.loads(repeated.stdout)
    assert repeated_result["commit"] == result["commit"]
    assert repeated_result["publication"]["details"]["idempotent"] is True
    assert _status(repository) == before_status


def test_publish_cli_rejects_removed_remote_surface(tmp_path: Path) -> None:
    repository = _full_repository(tmp_path)
    completed = subprocess.run(
        [
            "python3",
            "scripts/publish_candidate.py",
            "--repository",
            str(repository),
            "--actor",
            "Test Architect",
            "--remote",
            "origin",
        ],
        cwd=repository / "aga-skill",
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 2
    assert "unrecognized arguments: --remote origin" in completed.stderr
