# -*- coding: utf-8 -*-
"""Append a human architect action and optionally create a pending precedent."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from tools.feedback import (  # noqa: E402
    FeedbackError,
    generate_pending_precedent,
    record_architect_action,
)
from tools.validation import strict_load_yaml  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Record an AGA human architect decision")
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--action", required=True, choices=["accept", "override", "edit", "missed"])
    parser.add_argument("--actor", required=True, help="authenticated/display actor identity")
    parser.add_argument("--rationale")
    parser.add_argument("--severity", choices=["blocker", "major", "minor"])
    parser.add_argument("--rule-id")
    parser.add_argument("--log", default=str(PKG_ROOT / "logs" / "reviews.jsonl"))
    parser.add_argument("--precedent-id",
                        help="for override/missed: create a new pending precedent with this ID")
    parser.add_argument("--golden-case",
                        help="already approved/materialized pr-NN for an evolution-ready precedent")
    parser.add_argument("--mutation-file",
                        help="human-curated YAML mutation; requires --golden-case")
    args = parser.parse_args()
    try:
        if args.precedent_id and args.action not in {"override", "missed"}:
            raise ValueError("only override/missed can generate a precedent")
        if (args.golden_case or args.mutation_file) and not args.precedent_id:
            raise ValueError("--golden-case/--mutation-file require --precedent-id")
        if bool(args.golden_case) != bool(args.mutation_file):
            raise ValueError(
                "--golden-case and --mutation-file must be provided together")
        mutation = (
            strict_load_yaml(args.mutation_file, expected_type=dict)
            if args.mutation_file else None
        )
        event = record_architect_action(
            args.log, review_id=args.review_id, action=args.action, actor=args.actor,
            rationale=args.rationale, severity=args.severity, rule_id=args.rule_id)
        output = {"architect_action": event}
        if args.precedent_id:
            path = generate_pending_precedent(
                args.log, PKG_ROOT / "precedents" / "cases",
                review_id=args.review_id, precedent_id=args.precedent_id,
                golden_case=args.golden_case, proposed_mutation=mutation)
            output["pending_precedent"] = str(path)
    except (FeedbackError, OSError, ValueError) as error:
        print(json.dumps({"error": "feedback_error", "message": str(error)},
                         ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from error
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
