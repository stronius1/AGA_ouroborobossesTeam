#!/usr/bin/env python3
"""Execute one real shard of the 26-case deterministic AGA golden corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGA_ROOT = REPOSITORY_ROOT / "aga-skill"
if str(AGA_ROOT) not in sys.path:
    sys.path.insert(0, str(AGA_ROOT))

from evolver.fitness import (  # noqa: E402
    _match_findings,
    _normalise_expected,
    _normalise_predicted,
)
from tools.aga import review_pr  # noqa: E402
from tools.validation import strict_load_yaml, validate_corpus  # noqa: E402


SCHEMA = "aga.self-evolution-test-shard/v1"
CASE_RE = re.compile(r"^pr-[0-9]{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def rules_directory_sha256(path: Path) -> str:
    root = path.resolve(strict=True)
    files = sorted(item for item in root.iterdir() if item.is_file() and item.suffix == ".yaml")
    if not files or any(item.is_symlink() for item in files):
        raise ValueError("ruleset_unavailable")
    digest = hashlib.sha256()
    for item in files:
        raw = item.read_bytes()
        digest.update(item.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _case_map() -> dict[str, Mapping[str, Any]]:
    corpus_path = AGA_ROOT / "golden" / "corpus.yaml"
    corpus = strict_load_yaml(corpus_path, expected_type=dict)
    validate_corpus(corpus, path=corpus_path)
    return {str(case["id"]): case for case in corpus["cases"] if case.get("materialized") is True}


def _finding(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": str(value.get("rule_id") or ""),
        "severity": str(value.get("severity") or ""),
        "artifact": str(value.get("artifact") or ""),
        "location": str(value.get("location") or ""),
        "evidence": str(value.get("evidence") or value.get("canonical_defect") or "")[:500],
    }


def execute_shard(
    *,
    ruleset: str,
    case_ids: Sequence[str],
    worker_id: str,
    rules_dir: Path | None = None,
    expected_rules_sha256: str | None = None,
) -> dict[str, Any]:
    if ruleset not in {"baseline", "candidate"}:
        raise ValueError("ruleset_invalid")
    if not re.fullmatch(r"worker-[1-4]", worker_id):
        raise ValueError("worker_id_invalid")
    cases = _case_map()
    if not case_ids or len(set(case_ids)) != len(case_ids):
        raise ValueError("case_selection_invalid")
    if any(CASE_RE.fullmatch(case_id) is None or case_id not in cases for case_id in case_ids):
        raise ValueError("case_selection_invalid")
    selected_rules = rules_dir or AGA_ROOT / ("rules" if ruleset == "baseline" else "build/candidate-rules")
    if not selected_rules.is_dir():
        raise ValueError("ruleset_unavailable")
    rules_sha256 = rules_directory_sha256(selected_rules)
    if expected_rules_sha256 is not None:
        if SHA256_RE.fullmatch(expected_rules_sha256) is None or rules_sha256 != expected_rules_sha256:
            raise ValueError("ruleset_hash_mismatch")
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for case_id in case_ids:
        case_started = time.perf_counter()
        case = cases[case_id]
        review = review_pr(AGA_ROOT / "golden" / "prs" / case_id, selected_rules)
        if review.get("input_errors") or review.get("verdict") in {"input_error", "incomplete"}:
            raise ValueError("case_execution_failed")
        predicted = [_normalise_predicted(item) for item in review.get("findings", [])]
        expected = [
            _normalise_expected(item)
            for item in case.get("expected", {}).get("findings", [])
        ]
        true_positive, false_positive, false_negative, confusion = _match_findings(
            expected, predicted
        )
        expected_outcome = str(case["expected"]["outcome"])
        actual_outcome = str(review.get("verdict") or "")
        exact = not false_positive and not false_negative
        passed = exact and actual_outcome == expected_outcome
        results.append(
            {
                "id": case_id,
                "passed": passed,
                "expected_outcome": expected_outcome,
                "actual_outcome": actual_outcome,
                "actual_findings": [_finding(item) for item in review.get("findings", [])],
                "tp": [item[0]["rule_id"] for item in true_positive],
                "fp": [item["rule_id"] for item in false_positive],
                "fn": [item["rule_id"] for item in false_negative],
                "severity_confusion": dict(confusion),
                "suppressed": [
                    {
                        "rule_id": str(item.get("rule_id") or ""),
                        "exception": str(item.get("exception") or ""),
                    }
                    for item in review.get("suppressed_by_exception", [])
                    if isinstance(item, Mapping)
                ],
                "reviewed_files": [str(item) for item in review.get("reviewed_files", [])],
                "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
            }
        )
    return {
        "schema": SCHEMA,
        "status": "completed",
        "ruleset": ruleset,
        "worker_id": worker_id,
        "rules_sha256": rules_sha256,
        "cases": results,
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ruleset", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--worker", choices=tuple(f"worker-{index}" for index in range(1, 5)), required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--rules-dir", type=Path)
    parser.add_argument("--rules-sha256")
    args = parser.parse_args(argv)
    case_ids = tuple(item for item in args.cases.split(",") if item)
    try:
        result = execute_shard(
            ruleset=args.ruleset,
            case_ids=case_ids,
            worker_id=args.worker,
            rules_dir=args.rules_dir,
            expected_rules_sha256=args.rules_sha256,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "failed", "code": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
