#!/usr/bin/env python3
"""Run the submission SEAF-native review story without external services.

The demo creates two deterministic commits in an isolated temporary Git
repository.  It intentionally does not treat the offline semantic boundary as
a successful agent run: ``offline`` is a local diagnostic with an incomplete
final verdict, while ``gigaagent`` exits with code 2 until an official adapter
and an allowed real execution are configured.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))
PROJECT_EXTENSION_TEXT = (
    PACKAGE_ROOT.parent / "architecture" / "metamodel" / "aga-extension.yaml"
).read_text(encoding="utf-8")

from tools.repository_snapshot import RepositorySnapshotBuilder  # noqa: E402
from tools.seaf_review import prepare_seaf_review  # noqa: E402


COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "AGA Synthetic Demo",
    "GIT_AUTHOR_EMAIL": "aga-demo@example.invalid",
    "GIT_COMMITTER_NAME": "AGA Synthetic Demo",
    "GIT_COMMITTER_EMAIL": "aga-demo@example.invalid",
}


BASE_DOCUMENTS = {
    "dochub.yaml": """aga:
  schema: seaf-core/v1.4.0
  extensions: [aga.project/v1]
  data_classification: synthetic-public
imports:
  - aga-extension.yaml
  - model/components.yaml
  - model/integrations.yaml
  - model/adrs.yaml
""",
    "aga-extension.yaml": PROJECT_EXTENSION_TEXT,
    "model/components.yaml": """components:
  demo.checkout:
    title: Synthetic Checkout
    entity: component
    description: Synthetic customer checkout component.
    owner: Synthetic Commerce Team
    criticality: mission_critical
    target_status: strategic
  demo.legacy_scoring:
    title: Synthetic Legacy Scoring
    entity: component
    description: Synthetic scoring component scheduled for retirement.
    owner: Synthetic Legacy Team
    criticality: high
    target_status: eliminate
""",
    "model/integrations.yaml": "seaf.app.integrations: {}\n",
    "model/adrs.yaml": "seaf.change.adr: {}\n",
}


HEAD_INTEGRATIONS = """seaf.app.integrations:
  demo.checkout_to_legacy_scoring:
    title: Checkout to retiring scoring
    description: Synthetic synchronous lookup during checkout.
    from: demo.checkout
    to: demo.legacy_scoring
"""


def _git(repository: Path, *arguments: str, date: str | None = None) -> str:
    # The synthetic demo must be reproducible and must never execute caller-
    # supplied Git behavior.  Strip every inherited GIT_* variable, isolate
    # HOME/XDG config, and explicitly disable system/global config, attributes,
    # hooks, signing and replace objects.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    controlled_home = repository.parent / "git-home"
    controlled_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment.update(
        {
            "HOME": str(controlled_home),
            "XDG_CONFIG_HOME": str(controlled_home / ".config"),
            "LC_ALL": "C",
            "TZ": "UTC",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            **COMMIT_ENV,
        }
    )
    if date:
        environment.update({"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "tag.gpgSign=false",
            *arguments,
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    return completed.stdout.strip()


def _write(repository: Path, relative: str, content: str) -> None:
    target = repository / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _commit(repository: Path, message: str, date: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message, date=date)
    return _git(repository, "rev-parse", "HEAD")


def _materialize_demo(repository: Path) -> tuple[str, str]:
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main", "--object-format=sha1")
    for relative, content in BASE_DOCUMENTS.items():
        _write(repository, relative, content)
    base = _commit(repository, "synthetic SEAF base", "2026-07-15T08:00:00Z")
    _write(repository, "model/integrations.yaml", HEAD_INTEGRATIONS)
    head = _commit(
        repository, "add synthetic retiring dependency", "2026-07-15T08:01:00Z"
    )
    return base, head


def run_demo(mode: str) -> tuple[dict[str, object], int]:
    with tempfile.TemporaryDirectory(prefix="aga-seaf-demo-") as temporary:
        repository = Path(temporary) / "architecture"
        base, head = _materialize_demo(repository)
        with RepositorySnapshotBuilder(
            repository, base, head, dependency_mode="fixture"
        ).build() as snapshot:
            prepared = prepare_seaf_review(snapshot)

    result: dict[str, object] = {
        "schema": "aga.seaf-demo/v1",
        "case_id": "demo-critical-dependency",
        "data_classification": "synthetic-public",
        "mode": mode,
        "base_revision": base,
        "head_revision": head,
        "prepared_review_key": prepared["review_key"],
        "status": "incomplete",
        "verdict": "incomplete",
        "provisional_verdict": prepared["provisional_verdict"],
        "deterministic_findings": prepared["deterministic_findings"],
        "semantic_task_ids": [task["rule_id"] for task in prepared["semantic_tasks"]],
        "hitl_required": True,
        "auto_merge": False,
    }
    if mode == "offline":
        result.update(
            {
                "agent_status": "not_run",
                "reason": (
                    "Offline diagnostic completed; PRIN-004..007 still require the "
                    "official semantic agent before finalize."
                ),
            }
        )
        expected = (
            prepared["status"] == "needs_semantic_review"
            and prepared["incomplete"] is True
            and any(
                finding.get("rule_id") == "SEAF-004"
                for finding in prepared["deterministic_findings"]
            )
        )
        return result, 0 if expected else 1

    result.update(
        {
            "agent_status": "not_configured",
            "reason": (
                "No verified official GigaAgent adapter or permitted real-run evidence is "
                "configured; refusing to synthesize semantic findings."
            ),
        }
    )
    return result, 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("demo-critical-dependency",), required=True)
    parser.add_argument("--mode", choices=("offline", "gigaagent"), required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    result, exit_code = run_demo(arguments.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
