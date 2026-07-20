"""Offline contracts for the canonical submission facts checker."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import submission_consistency_check as checker  # noqa: E402


def _facts() -> dict:
    value = json.loads(
        (REPOSITORY_ROOT / "docs" / "SUBMISSION-FACTS.json").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(value, dict)
    return value


def test_canonical_submission_facts_match_retained_evidence_and_docs(
    capsys,
) -> None:
    assert checker.main() == 0
    captured = capsys.readouterr()
    assert "SUBMISSION FACTS AND MATERIALS OK" in captured.out
    assert captured.err == ""


def test_business_formula_tampering_fails_closed() -> None:
    facts = deepcopy(_facts())
    facts["business_case"]["derived"]["annual_gross_effect_rub"] += 1
    errors: list[str] = []

    checker._check_business_case(facts, errors)

    assert len(errors) == 1
    assert errors[0].startswith(
        "business_case.derived.annual_gross_effect_rub: facts=4108801, "
        "evidence/calculation="
    )


def test_publication_url_must_be_null_or_https() -> None:
    facts = deepcopy(_facts())
    facts["publication"]["demo_video_url"] = "VIDEO_URL_TBD"
    errors: list[str] = []

    checker._check_docs(facts, errors)

    assert errors == ["publication.demo_video_url must be null or an https URL"]


def test_development_v2_claims_match_pending_lock() -> None:
    facts = _facts()
    errors: list[str] = []

    checker._check_development_v2(facts, errors)

    assert errors == []


def test_development_v2_case_count_tampering_fails_closed() -> None:
    facts = deepcopy(_facts())
    facts["semantic_development_v2"]["case_count"] = 47
    errors: list[str] = []

    checker._check_development_v2(facts, errors)

    assert errors == [
        "semantic_development_v2.case_count: facts=47, evidence/calculation=48"
    ]


def test_local_pdf_and_eight_slide_deck_match_recorded_hashes() -> None:
    facts = _facts()
    errors: list[str] = []

    checker._check_local_submission_artifacts(facts, errors)

    assert errors == []


def test_local_submission_artifact_hash_tampering_fails_closed() -> None:
    facts = deepcopy(_facts())
    facts["local_submission_artifacts"]["project_results_pdf"]["sha256"] = "0" * 64
    errors: list[str] = []

    checker._check_local_submission_artifacts(facts, errors)

    assert len(errors) == 1
    assert errors[0].startswith(
        "local_submission_artifacts.project_results_pdf.sha256: facts="
    )


def test_local_submission_source_hash_tampering_fails_closed() -> None:
    facts = deepcopy(_facts())
    facts["local_submission_artifacts"]["project_results_pdf"]["sources"][0][
        "sha256"
    ] = "0" * 64
    errors: list[str] = []

    checker._check_local_submission_artifacts(facts, errors)

    assert len(errors) == 1
    assert errors[0].startswith(
        "local_submission_artifacts.project_results_pdf.sources[0].sha256: facts="
    )
