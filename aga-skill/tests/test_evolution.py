# -*- coding: utf-8 -*-
"""Contract tests for mutation validation and the runtime policy guard."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from evolver.mutations import (  # noqa: E402
    MutationValidationError,
    UnsupportedMutationTypeError,
    validate_mutation,
)
from evolver.policy import (  # noqa: E402
    CandidateChange,
    PolicyViolation,
    guard_candidate_changes,
)
from scripts import run_evolution  # noqa: E402
from tools.publisher import (  # noqa: E402
    DryRunPublisher,
    PublicationResult,
    PublishRequest,
    PublisherPolicyError,
)
from tools.validation import ValidationError  # noqa: E402


def _rule(
    rule_id: str,
    *,
    severity: str = "major",
    status: str = "active",
    detect=None,
):
    return {
        "id": rule_id,
        "title": f"Rule {rule_id}",
        "statement": "A test rule",
        "severity": severity,
        "scope": ["integration_flow"],
        "check_type": "deterministic",
        "detect": detect or {"field": "pattern", "banned": ["file"]},
        "source_ref": "TEST-POLICY section 1",
        "exceptions": [],
        "provenance": {"origin": "seed", "added_in": "1.0.0"},
        "status": status,
    }


class LocalPublisherBoundaryTests(unittest.TestCase):
    def request(self) -> PublishRequest:
        return PublishRequest(
            cycle_id="cycle-local-only",
            artifacts={"rules.diff": PKG_ROOT / "build" / "rules.diff"},
            branch_name="skill/evolution-local-only",
            commit_message="candidate mutation",
            draft=True,
            requested_actions=(),
            metadata={"gate_passed": True, "auto_merge": False},
        )

    def test_run_cycle_has_no_injected_publisher_boundary(self):
        class HostilePublisher:
            requires_network = False

            def __init__(self):
                self.called = False

            def publish(self, _request):
                self.called = True
                raise AssertionError("hostile publisher must never be invoked")

        publisher = HostilePublisher()
        with self.assertRaises(TypeError):
            run_evolution.run_cycle(max_attempts=1, publisher=publisher)
        self.assertFalse(publisher.called)

    def test_forged_dry_run_result_is_rejected(self):
        def forged_publish(_publisher, request):
            return PublicationResult(
                publisher="dry-run",
                status="dry_run",
                cycle_id=request.cycle_id,
                artifacts=tuple(request.artifacts),
                external_side_effects=True,
                branch_name="attacker/branch",
                draft_pr_url="https://example.invalid/pr/1",
            )

        original_publish = DryRunPublisher.publish
        try:
            DryRunPublisher.publish = forged_publish  # type: ignore[method-assign]
            with self.assertRaises(PublisherPolicyError):
                run_evolution._publish_local_dry_run(self.request())
        finally:
            DryRunPublisher.publish = original_publish  # type: ignore[method-assign]

    def test_exact_dry_run_result_is_accepted(self):
        result = run_evolution._publish_local_dry_run(self.request())
        self.assertEqual(result["status"], "dry_run")
        self.assertIs(result["external_side_effects"], False)
        self.assertIsNone(result["branch_name"])
        self.assertIsNone(result["draft_pr_url"])


class MutationValidationTests(unittest.TestCase):
    def setUp(self):
        self.rules = [
            _rule("PRIN-002"),
            _rule("PRIN-003", severity="blocker", detect={"field": "pattern", "banned": ["direct_db"]}),
            _rule("PRIN-009", status="candidate", detect={"field": "transfer_mode", "banned": ["sync"]}),
        ]
        self.approved = {"precedent:0001"}

    def valid_exception(self):
        return {
            "type": "add_exception",
            "rule_id": "PRIN-002",
            "provenance": "precedent:0001",
            "exception": {
                "id": "EXC-PRIN-002-001",
                "when": {
                    "all": [
                        {"field": "zone", "equals": "dmz"},
                        {"field": "transfer_mode", "equals": "batch"},
                        {"field": "gateway_controlled", "equals": True},
                        {"field": "approvals", "contains": "security"},
                    ]
                },
                "rationale": "Approved controlled batch transfer",
                "provenance": "precedent:0001",
            },
        }

    def assert_code(self, code, callable_):
        with self.assertRaises(MutationValidationError) as caught:
            callable_()
        self.assertEqual(caught.exception.code, code)

    def test_valid_add_exception_returns_defensive_copy(self):
        mutation = self.valid_exception()
        validated = validate_mutation(mutation, self.rules, approved_provenance=self.approved)
        validated["exception"]["rationale"] = "changed"
        self.assertEqual(mutation["exception"]["rationale"], "Approved controlled batch transfer")

    def test_mutation_without_provenance_rejected(self):
        mutation = self.valid_exception()
        mutation.pop("provenance")
        self.assert_code(
            "required_field",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )

    def test_unapproved_provenance_rejected(self):
        self.assert_code(
            "unapproved_provenance",
            lambda: validate_mutation(
                self.valid_exception(), self.rules, approved_provenance={"precedent:9999"}
            ),
        )

    def test_mapping_registry_needs_explicit_approval(self):
        self.assert_code(
            "unapproved_provenance",
            lambda: validate_mutation(
                self.valid_exception(),
                self.rules,
                approved_provenance={"precedent:0001": {"approved": False}},
            ),
        )

    def test_tautological_exception_rejected(self):
        mutation = self.valid_exception()
        mutation["exception"]["when"] = {}
        self.assert_code(
            "tautological_exception",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )

    def test_exception_that_disables_whole_trigger_rejected(self):
        mutation = self.valid_exception()
        mutation["exception"]["when"] = {"field": "pattern", "equals": "file"}
        self.assert_code(
            "global_exception",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )

    def test_exception_provenance_must_match_mutation(self):
        mutation = self.valid_exception()
        mutation["exception"]["provenance"] = "incident:INC-1"
        self.assert_code(
            "provenance_mismatch",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )

    def test_duplicate_rule_ids_in_base_are_rejected(self):
        rules = self.rules + [copy.deepcopy(self.rules[0])]
        self.assert_code(
            "duplicate_rule_id",
            lambda: validate_mutation(self.valid_exception(), rules, approved_provenance=self.approved),
        )

    def test_duplicate_add_rule_rejected(self):
        mutation = {
            "type": "add_rule",
            "provenance": "precedent:0001",
            "rule": copy.deepcopy(self.rules[0]),
        }
        mutation["rule"]["provenance"] = {
            "origin": "precedent:0001",
            "added_in": "1.1.0",
        }
        self.assert_code(
            "duplicate_rule_id",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )

    def test_active_blocker_add_rule_rejected(self):
        new_rule = _rule("PRIN-010", severity="blocker", status="active")
        new_rule["provenance"] = {"origin": "precedent:0001", "added_in": "1.1.0"}
        mutation = {"type": "add_rule", "provenance": "precedent:0001", "rule": new_rule}
        self.assert_code(
            "active_blocker_rule_forbidden",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )

    def test_candidate_add_rule_is_valid(self):
        new_rule = _rule("PRIN-010", status="candidate")
        new_rule["provenance"] = {"origin": "precedent:0001", "added_in": "1.1.0"}
        mutation = {"type": "add_rule", "provenance": "precedent:0001", "rule": new_rule}
        self.assertEqual(
            validate_mutation(mutation, self.rules, approved_provenance=self.approved)["type"],
            "add_rule",
        )

    def test_blocker_downgrade_requires_committee_decision(self):
        mutation = {
            "type": "adjust_severity",
            "rule_id": "PRIN-003",
            "new_severity": "major",
            "provenance": "precedent:0001",
        }
        self.assert_code(
            "invalid_type",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )
        mutation["committee_decision"] = {
            "id": "ARCH-COMMITTEE-42",
            "approved": True,
            "evidence": "Signed committee minutes",
        }
        self.assertEqual(
            validate_mutation(mutation, self.rules, approved_provenance=self.approved)["new_severity"],
            "major",
        )

    def test_activate_rule_requires_explicit_human_approval(self):
        mutation = {
            "type": "activate_rule",
            "rule_id": "PRIN-009",
            "provenance": "precedent:0001",
        }
        self.assert_code(
            "invalid_type",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )
        mutation["human_approval"] = {
            "approved": True,
            "actor": "architect@example.test",
            "evidence": "review:123",
        }
        self.assertEqual(
            validate_mutation(mutation, self.rules, approved_provenance=self.approved)["type"],
            "activate_rule",
        )

    def test_deprecate_rule_requires_reason_evidence_and_coverage(self):
        mutation = {
            "type": "deprecate_rule",
            "rule_id": "PRIN-002",
            "provenance": "precedent:0001",
            "reason": "Superseded",
            "evidence": "Policy v2",
        }
        self.assert_code(
            "invalid_type",
            lambda: validate_mutation(mutation, self.rules, approved_provenance=self.approved),
        )
        mutation["coverage"] = {
            "positive_cases": ["pr-15"],
            "negative_cases": ["pr-16"],
        }
        self.assertEqual(
            validate_mutation(mutation, self.rules, approved_provenance=self.approved)["type"],
            "deprecate_rule",
        )

    def test_deprecate_rule_coverage_ids_are_unique_and_disjoint(self):
        mutation = {
            "type": "deprecate_rule",
            "rule_id": "PRIN-002",
            "provenance": "precedent:0001",
            "reason": "Superseded",
            "evidence": "Policy v2",
            "coverage": {
                "positive_cases": ["pr-15", "pr-15"],
                "negative_cases": ["pr-16"],
            },
        }
        self.assert_code(
            "duplicate_coverage_case",
            lambda: validate_mutation(
                mutation, self.rules, approved_provenance=self.approved
            ),
        )
        mutation["coverage"] = {
            "positive_cases": ["pr-15"],
            "negative_cases": ["pr-15"],
        }
        self.assert_code(
            "overlapping_coverage_case",
            lambda: validate_mutation(
                mutation, self.rules, approved_provenance=self.approved
            ),
        )

    def test_documented_but_unimplemented_type_is_typed(self):
        with self.assertRaises(UnsupportedMutationTypeError) as caught:
            validate_mutation(
                {"type": "add_fewshot", "provenance": "precedent:0001"},
                self.rules,
                approved_provenance=self.approved,
            )
        self.assertEqual(caught.exception.code, "unsupported_mutation_type")


class PolicyGuardTests(unittest.TestCase):
    def severity_policy(self):
        return {
            "autonomy": {"auto_merge": False, "auto_verdicts": ["approve"]},
            "error_costs": {"missed_blocker": 10.0, "false_major": 2.0},
            "verdict_policy": {"none": "approve"},
        }

    def corpus(self):
        return {
            "schema": "aga.golden-corpus/v1",
            "cases": [
                {
                    "id": "pr-01",
                    "materialized": True,
                    "expected": {"findings": [], "outcome": "approve"},
                }
            ],
        }

    def assert_policy_code(self, code, changes):
        with self.assertRaises(PolicyViolation) as caught:
            guard_candidate_changes(changes)
        self.assertEqual(caught.exception.code, code)

    def test_protected_files_rejected(self):
        for path in (
            "evolver/fitness.py",
            "evolver/permissions.yaml",
            "evolver/policy.py",
            "SKILL.md",
        ):
            with self.subTest(path=path):
                self.assert_policy_code(
                    "protected_path", [CandidateChange(path, "before", "after")]
                )

    def test_unlisted_source_and_materialized_fixture_paths_are_rejected(self):
        for path in ("scripts/run_review.py", "golden/prs/pr-15/meta.yaml",
                     "fixtures/seaf.yaml", "rules/unvalidated.py"):
            with self.subTest(path=path), self.assertRaises(PolicyViolation) as caught:
                guard_candidate_changes([CandidateChange(path, "before", "after")])
            self.assertEqual(caught.exception.code, "unapproved_path")

    def test_parent_traversal_and_absolute_path_rejected(self):
        self.assert_policy_code(
            "invalid_path", [CandidateChange("../evolver/fitness.py", "before", "after")]
        )
        self.assert_policy_code(
            "invalid_path", [CandidateChange("/tmp/rules.yaml", "before", "after")]
        )

    def test_auto_merge_change_rejected(self):
        before = self.severity_policy()
        after = copy.deepcopy(before)
        after["autonomy"]["auto_merge"] = True
        self.assert_policy_code(
            "auto_merge_invariant",
            [CandidateChange("rules/severity-policy.yaml", before, after)],
        )

    def test_error_weights_change_rejected(self):
        before = self.severity_policy()
        after = copy.deepcopy(before)
        after["error_costs"]["false_major"] = 0.1
        self.assert_policy_code(
            "error_weights_change_forbidden",
            [CandidateChange("rules/severity-policy.yaml", before, after)],
        )

    def test_other_severity_policy_change_allowed(self):
        before = self.severity_policy()
        after = copy.deepcopy(before)
        after["verdict_policy"]["minor_only"] = "approve_with_warnings"
        validated = guard_candidate_changes(
            [CandidateChange("rules/severity-policy.yaml", before, after)]
        )
        self.assertEqual(len(validated), 1)

    def test_existing_expected_change_rejected(self):
        before = self.corpus()
        after = copy.deepcopy(before)
        after["cases"][0]["expected"]["outcome"] = "request_changes_escalate"
        self.assert_policy_code(
            "existing_expected_change_forbidden",
            [CandidateChange("golden/corpus.yaml", before, after)],
        )

    def test_existing_case_removal_rejected(self):
        self.assert_policy_code(
            "existing_case_removed",
            [CandidateChange("golden/corpus.yaml", self.corpus(), {"cases": []})],
        )

    def test_new_corpus_case_is_allowed(self):
        before = self.corpus()
        after = copy.deepcopy(before)
        after["cases"].append(
            {
                "id": "pr-02",
                "materialized": True,
                "expected": {"findings": [], "outcome": "approve"},
            }
        )
        validated = guard_candidate_changes(
            [CandidateChange("golden/corpus.yaml", before, after)]
        )
        self.assertEqual(validated[0].path, "golden/corpus.yaml")

    def test_duplicate_yaml_cases_key_rejected(self):
        before = "cases:\n  - id: pr-01\n    expected: {findings: [], outcome: approve}\n"
        after = "cases: []\ncases: []\n"
        self.assert_policy_code(
            "invalid_candidate_yaml",
            [CandidateChange("golden/corpus.yaml", before, after)],
        )

    def test_ordinary_rules_change_is_allowed(self):
        validated = guard_candidate_changes(
            [CandidateChange("rules/principles.yaml", "rules: []\n", "rules: [{id: PRIN-010}]\n")]
        )
        self.assertEqual(len(validated), 1)


class CorpusFixtureLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aga-corpus-lock-")
        self.package = Path(self.temporary.name).resolve()
        shutil.copytree(PKG_ROOT / "golden", self.package / "golden")
        (self.package / "fixtures").mkdir()
        shutil.copy2(
            PKG_ROOT / "fixtures" / "seaf.yaml",
            self.package / "fixtures" / "seaf.yaml",
        )
        self.previous_root = run_evolution.PKG_ROOT
        run_evolution.PKG_ROOT = self.package
        self.precedent = {"id": "0001", "golden_case": "pr-15"}

    def tearDown(self):
        run_evolution.PKG_ROOT = self.previous_root
        self.temporary.cleanup()

    def assert_lock_code(self, code, operation):
        with self.assertRaises(ValidationError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)

    def test_approved_fixture_tree_matches_locked_hash(self):
        lock = json.loads(
            (self.package / "golden" / "corpus.lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            run_evolution._fixtures_sha256(lock["approved_cases"]),
            lock["fixtures_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(
                (self.package / "fixtures" / "seaf.yaml").read_bytes()
            ).hexdigest(),
            lock["seaf_fixture_sha256"],
        )

    def test_corpus_yaml_change_is_rejected(self):
        corpus = self.package / "golden" / "corpus.yaml"
        corpus.write_bytes(corpus.read_bytes() + b"\n# same-cycle mutation\n")
        self.assert_lock_code(
            "same_cycle_corpus_change",
            lambda: run_evolution._verify_locked_corpus(self.precedent),
        )

    def test_fixture_artifact_or_manifest_change_is_rejected(self):
        relatives = (
            "golden/prs/pr-15/meta.yaml",
            "golden/prs/pr-15/files/flows/IF-0104.md",
        )
        for relative in relatives:
            with self.subTest(relative=relative):
                path = self.package / relative
                original = path.read_bytes()
                path.write_bytes(original + b"\n# same-cycle mutation\n")
                self.assert_lock_code(
                    "same_cycle_corpus_change",
                    lambda: run_evolution._verify_locked_corpus(self.precedent),
                )
                path.write_bytes(original)

    def test_seaf_registry_change_is_rejected_before_fitness(self):
        seaf = self.package / "fixtures" / "seaf.yaml"
        seaf.write_bytes(seaf.read_bytes() + b"\n# same-cycle mutation\n")
        self.assert_lock_code(
            "same_cycle_corpus_change",
            lambda: run_evolution._verify_locked_corpus(self.precedent),
        )

    def test_wrong_precedent_origin_is_rejected(self):
        self.assert_lock_code(
            "wrong_precedent_origin",
            lambda: run_evolution._verify_locked_corpus(
                {"id": "9999", "golden_case": "pr-15"}
            ),
        )

    def test_missing_or_unmaterialized_case_is_rejected(self):
        self.assert_lock_code(
            "anti_goodhart",
            lambda: run_evolution._verify_locked_corpus(
                {"id": "0001", "golden_case": "pr-99"}
            ),
        )
        shutil.rmtree(self.package / "golden" / "prs" / "pr-15" / "files")
        self.assert_lock_code(
            "same_cycle_corpus_change",
            lambda: run_evolution._verify_locked_corpus(self.precedent),
        )


if __name__ == "__main__":
    unittest.main()
