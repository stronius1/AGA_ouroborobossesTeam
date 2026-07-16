# -*- coding: utf-8 -*-
"""Contract tests for offline support modules (A2A, feedback, LLM, publisher)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from tools.a2a import (  # noqa: E402
    LocalTaskBackend,
    TaskStatus,
    aggregate_task_results,
    run_task_group,
)
from tools.feedback import (  # noqa: E402
    DuplicateFeedbackError,
    FeedbackValidationError,
    ReviewNotFoundError,
    generate_pending_precedent,
    log_review,
    read_jsonl,
    record_architect_action,
    sort_pending_precedents,
    validate_precedent_schema,
)
from tools.llm import (  # noqa: E402
    FixtureLLMAdapter,
    LLMHTTPError,
    LLMInvalidJSONError,
    LLMNetworkDisabledError,
    LLMRequest,
    LLMResponseTooLargeError,
    LLMTimeoutError,
    LLMTransportError,
    invoke_llm,
    merge_findings,
)
from tools.publisher import (  # noqa: E402
    DryRunPublisher,
    PublishRequest,
    PublisherPolicyError,
    default_publisher,
)
from tools.validation import load_precedent  # noqa: E402


def _finding(
    rule_id: str = "PRIN-002",
    severity: str = "major",
    artifact: str = "flows/IF-0001.md",
    confidence: float = 1.0,
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "confidence": confidence,
        "artifact": artifact,
        "location": "frontmatter: pattern",
        "evidence": "unsafe integration pattern",
        "source_ref": "ARCH-PRINCIPLES section 4.2",
        "suggested_fix": "use an approved integration pattern",
    }


def _review(review_id: str, findings: list[dict[str, object]] | None = None) -> dict:
    return {
        "review_id": review_id,
        "timestamp": "2026-07-15T10:00:00Z",
        "skill_version": "1.0.0",
        "rules_version": "rules-v1",
        "input_revision": f"sha256:{review_id}",
        "pr": f"pr-{review_id}",
        "findings": list(findings or []),
        "suppressed_findings": [],
        "observations": [],
        "verdict": "request_changes_escalate" if findings else "approve",
        "escalation": bool(findings),
        "architect_action": None,
    }


def _load_precedent(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    return yaml.safe_load(frontmatter)


def test_local_a2a_aggregates_results():
    duplicate = _finding(severity="minor", confidence=0.9)
    deterministic = dict(_finding(severity="major"), origin="deterministic")
    handlers = {
        "aga:diagram-checker": lambda _payload: {
            "findings": [duplicate],
            "observations": [],
        },
        "aga:seaf-consistency": lambda _payload: {
            "findings": [],
            "observations": [{"message": "SEAF checked"}],
        },
    }
    with LocalTaskBackend(handlers) as backend:
        result = run_task_group(
            backend,
            [
                ("aga:diagram-checker", {"path": "diagram.puml"}),
                ("aga:seaf-consistency", {"pr": "pr-01"}),
            ],
            deterministic_findings=[deterministic],
        )
    assert result.complete is True
    assert result.verdict == "request_changes_escalate"
    assert result.escalate is True
    assert len(result.findings) == 1
    assert result.findings[0]["severity"] == "major"
    assert result.findings[0]["origin"] == "deterministic"
    assert len(result.observations) == 1


def test_a2a_task_failure_fails_closed():
    def broken(_payload):
        raise RuntimeError("worker failed")

    with LocalTaskBackend({"aga:principles-reviewer": broken}) as backend:
        task_id = backend.schedule_task("aga:principles-reviewer", {})
        task = backend.wait_for_task(task_id, timeout=1)
        aggregate = aggregate_task_results([task])
    assert task.status is TaskStatus.FAILED
    assert aggregate.complete is False
    assert aggregate.verdict == "incomplete_error"
    assert aggregate.escalate is True
    assert "worker failed" in aggregate.errors[0]


def test_a2a_arbitrary_handler_exception_is_structured_and_fails_closed():
    def broken(_payload):
        return 1 / 0

    with LocalTaskBackend({"aga:principles-reviewer": broken}) as backend:
        task_id = backend.schedule_task("aga:principles-reviewer", {})
        task = backend.wait_for_task(task_id, timeout=1)
        aggregate = aggregate_task_results([task])
    assert task.status is TaskStatus.FAILED
    assert "ZeroDivisionError" in (task.error or "")
    assert aggregate.complete is False
    assert aggregate.verdict == "incomplete_error"


def test_a2a_task_timeout_fails_closed():
    def slow(_payload):
        time.sleep(0.05)
        return {"findings": [], "observations": []}

    with LocalTaskBackend({"aga:adr-writer": slow}) as backend:
        task_id = backend.schedule_task("aga:adr-writer", {})
        task = backend.wait_for_task(task_id, timeout=0.001)
        aggregate = aggregate_task_results([task])
    assert task.status is TaskStatus.TIMED_OUT
    assert aggregate.complete is False
    assert aggregate.verdict == "incomplete_error"


def test_review_log_written_atomically(tmp_path):
    log = tmp_path / "reviews.jsonl"

    def write(index: int) -> None:
        log_review(log, _review(f"review-{index:02d}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(32)))
    events = read_jsonl(log)
    assert len(events) == 32
    assert len({event["review_id"] for event in events}) == 32
    assert all(event["event_type"] == "review" for event in events)
    assert log.read_bytes().endswith(b"\n")


def test_review_log_rejects_full_llm_payload(tmp_path):
    review = _review("review-secret")
    review["llm_payload"] = "full raw prompt"
    with pytest.raises(FeedbackValidationError):
        log_review(tmp_path / "reviews.jsonl", review)


def test_architect_action_references_review(tmp_path):
    log = tmp_path / "reviews.jsonl"
    with pytest.raises(ReviewNotFoundError):
        record_architect_action(
            log,
            review_id="missing-review",
            action="accept",
            actor="architect@example.test",
        )


def test_override_creates_pending_precedent(tmp_path):
    log = tmp_path / "reviews.jsonl"
    log_review(log, _review("review-override", [_finding(severity="blocker")]))
    record_architect_action(
        log,
        review_id="review-override",
        action="override",
        actor="architect@example.test",
        rationale="Approved exception under policy GOV-17",
        rule_id="PRIN-002",
    )
    path = generate_pending_precedent(
        log,
        tmp_path / "precedents",
        review_id="review-override",
        precedent_id="0042-policy-exception",
    )
    precedent = _load_precedent(path)
    assert precedent["status"] == "pending"
    assert precedent["distilled_in"] is None
    assert precedent["priority_category"] == "false_blocker"
    assert precedent["architect_action"] == "override"
    assert precedent["golden_case"] is None
    assert precedent["proposed_mutation"] is None
    validated, _ = load_precedent(path)
    assert validated["id"] == "0042-policy-exception"
    with pytest.raises(DuplicateFeedbackError):
        generate_pending_precedent(
            log,
            tmp_path / "precedents",
            review_id="review-override",
            precedent_id="0042-policy-exception",
        )


def test_human_curated_feedback_precedent_is_evolution_ready(tmp_path):
    log = tmp_path / "reviews.jsonl"
    log_review(log, _review("review-ready", [_finding(severity="major")]))
    record_architect_action(
        log, review_id="review-ready", action="override",
        actor="architect@example.test", rationale="Approved policy exception",
        rule_id="PRIN-002")
    mutation = {
        "type": "add_exception", "provenance": "precedent:0043",
        "rule_id": "PRIN-002",
        "exception": {
            "when": {"all": [
                {"field": "pattern", "equals": "file"},
                {"field": "zone", "equals": "dmz"},
            ]},
            "rationale": "human-curated narrow exception",
            "provenance": "precedent:0043",
        },
    }
    path = generate_pending_precedent(
        log, tmp_path / "precedents", review_id="review-ready",
        precedent_id="0043", golden_case="pr-15",
        proposed_mutation=mutation)
    precedent = _load_precedent(path)
    assert precedent["review_id"] == "review-ready"
    assert precedent["golden_case"] == "pr-15"
    assert precedent["proposed_mutation"] == mutation


def test_precedent_priority_order():
    precedents = [
        {
            "id": "minor",
            "status": "pending",
            "architect_action": "override",
            "severity": "minor",
        },
        {
            "id": "missed-major",
            "status": "pending",
            "architect_action": "missed",
            "severity": "major",
        },
        {
            "id": "false-blocker",
            "status": "pending",
            "architect_action": "override",
            "severity": "blocker",
        },
        {
            "id": "missed-blocker",
            "status": "pending",
            "architect_action": "missed",
            "severity": "blocker",
        },
        {
            "id": "done",
            "status": "distilled",
            "architect_action": "missed",
            "severity": "blocker",
        },
    ]
    ordered = sort_pending_precedents(precedents)
    assert [item["id"] for item in ordered] == [
        "missed-blocker",
        "false-blocker",
        "missed-major",
        "minor",
    ]


def test_distilled_status_schema():
    precedent = {
        "schema": "aga.precedent/v1",
        "id": "p-1",
        "review_id": "r-1",
        "architect_action": "missed",
        "architect": "architect@example.test",
        "rationale": "missed governance issue",
        "severity": "major",
        "status": "distilled",
        "distilled_in": "1.1.0",
    }
    assert validate_precedent_schema(precedent)["distilled_in"] == "1.1.0"
    precedent["distilled_in"] = None
    with pytest.raises(FeedbackValidationError):
        validate_precedent_schema(precedent)


def test_llm_fixture_findings_are_validated():
    low_blocker = _finding(rule_id="PRIN-008", severity="blocker", confidence=0.60)
    observation = _finding(rule_id="PRIN-005", severity="major", confidence=0.30)
    adapter = FixtureLLMAdapter({"findings": [low_blocker, observation]})
    request = LLMRequest("Apply only supplied rules", "UNTRUSTED ARTIFACT")
    result = invoke_llm(adapter, request)
    assert len(adapter.calls) == 1
    assert result.findings[0]["severity"] == "major"
    assert result.findings[0]["low_confidence"] is True
    assert result.findings[0]["original_severity"] == "blocker"
    assert "severity" not in result.observations[0]
    assert result.observations[0]["original_severity"] == "major"
    assert result.observations[0]["low_confidence"] is True
    assert result.observations[0]["observation_type"] == "low_confidence"


def test_llm_invalid_json_is_rejected():
    adapter = FixtureLLMAdapter("not-json")
    with pytest.raises(LLMInvalidJSONError):
        invoke_llm(adapter, LLMRequest("rules", "artifact"))


def test_llm_oversized_response_is_rejected():
    adapter = FixtureLLMAdapter(json.dumps({"findings": [], "padding": "x" * 100}))
    with pytest.raises(LLMResponseTooLargeError):
        invoke_llm(
            adapter,
            LLMRequest("rules", "artifact", max_response_bytes=32),
        )


def test_llm_timeout_is_typed():
    adapter = FixtureLLMAdapter(error=TimeoutError("fixture timeout"))
    with pytest.raises(LLMTimeoutError):
        invoke_llm(adapter, LLMRequest("rules", "artifact"))


@pytest.mark.parametrize("timeout", [True, float("nan"), float("inf"), 120.1])
def test_llm_request_timeout_must_be_finite_and_bounded(timeout):
    with pytest.raises(ValueError, match="timeout_seconds"):
        LLMRequest("rules", "artifact", timeout_seconds=timeout)


def test_llm_timeout_waits_for_synchronous_adapter_to_finish_without_late_work():
    events: list[str] = []

    class SlowAdapter:
        requires_network = False

        def complete(self, _request):
            time.sleep(0.05)
            events.append("finished")
            return {"findings": []}

    started = time.monotonic()
    with pytest.raises(LLMTimeoutError):
        invoke_llm(
            SlowAdapter(),
            LLMRequest("rules", "artifact", timeout_seconds=0.001),
        )
    assert time.monotonic() - started >= 0.04
    assert events == ["finished"]


def test_arbitrary_adapter_exception_becomes_typed_transport_error():
    adapter = FixtureLLMAdapter(error=RuntimeError("synthetic adapter failure"))
    with pytest.raises(LLMTransportError) as caught:
        invoke_llm(adapter, LLMRequest("rules", "artifact"))
    assert "RuntimeError" in str(caught.value)


def test_llm_http_error_remains_typed():
    adapter = FixtureLLMAdapter(error=LLMHTTPError(503, "unavailable"))
    with pytest.raises(LLMHTTPError) as caught:
        invoke_llm(adapter, LLMRequest("rules", "artifact"))
    assert caught.value.status_code == 503


def test_network_adapter_is_off_by_default():
    class NetworkAdapter:
        requires_network = True

        def complete(self, _request):
            raise AssertionError("must not be called")

    with pytest.raises(LLMNetworkDisabledError):
        invoke_llm(NetworkAdapter(), LLMRequest("rules", "artifact"))


def test_network_permission_must_be_an_explicit_boolean():
    adapter = FixtureLLMAdapter({"findings": []})
    with pytest.raises(LLMTransportError, match="explicit boolean"):
        invoke_llm(
            adapter,
            LLMRequest("rules", "artifact"),
            network_enabled="yes",  # type: ignore[arg-type]
        )
    assert adapter.calls == []


def test_llm_and_deterministic_findings_are_deduplicated():
    deterministic = dict(_finding(severity="major"), origin="deterministic")
    llm = _finding(severity="major", confidence=0.99)
    merged = merge_findings([deterministic], [llm])
    assert len(merged) == 1
    assert merged[0]["origin"] == "deterministic"


def test_a2a_aggregation_applies_seaf_precedence():
    seaf = _finding(rule_id="SEAF-004", severity="blocker")
    semantic = _finding(rule_id="PRIN-006", severity="blocker")
    handlers = {
        "aga:principles-reviewer": lambda _payload: {
            "findings": [semantic],
            "observations": [],
        },
    }
    with LocalTaskBackend(handlers) as backend:
        result = run_task_group(
            backend,
            [("aga:principles-reviewer", {})],
            deterministic_findings=[seaf],
        )
    assert [finding["rule_id"] for finding in result.findings] == ["SEAF-004"]


def test_precedence_keeps_independent_locations_on_one_artifact():
    seaf = _finding(rule_id="SEAF-004", severity="blocker")
    semantic = _finding(rule_id="PRIN-006", severity="blocker")
    semantic["location"] = "body:42"
    handlers = {
        "aga:principles-reviewer": lambda _payload: {
            "findings": [semantic], "observations": []},
    }
    with LocalTaskBackend(handlers) as backend:
        result = run_task_group(
            backend, [("aga:principles-reviewer", {})],
            deterministic_findings=[seaf])
    assert [finding["rule_id"] for finding in result.findings] == [
        "SEAF-004", "PRIN-006"]


def test_publisher_default_is_dry_run(tmp_path):
    publisher = default_publisher()
    request = PublishRequest(
        cycle_id="cycle-001",
        artifacts={"metrics": tmp_path / "metrics.json"},
        branch_name="skill/evolution-cycle-001",
        commit_message="candidate mutation",
    )
    result = publisher.publish(request)
    assert isinstance(publisher, DryRunPublisher)
    assert result.status == "dry_run"
    assert result.external_side_effects is False
    assert result.branch_name is None
    assert result.draft_pr_url is None
    assert result.artifacts == ("metrics",)


def test_publisher_cannot_merge_or_approve(tmp_path):
    publisher = DryRunPublisher()
    with pytest.raises(PublisherPolicyError):
        publisher.publish(
            PublishRequest(
                cycle_id="cycle-forbidden",
                artifacts={"diff": tmp_path / "rules.diff"},
                requested_actions=("merge",),
            )
        )
    with pytest.raises(PublisherPolicyError):
        publisher.merge("draft-pr-1")
    with pytest.raises(PublisherPolicyError):
        publisher.approve("draft-pr-1")
