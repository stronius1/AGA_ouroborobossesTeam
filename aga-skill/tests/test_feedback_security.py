# -*- coding: utf-8 -*-
"""Hostile-path and concurrency regressions for the feedback audit log."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

import tools.feedback as feedback_module  # noqa: E402
from tools.feedback import (  # noqa: E402
    FeedbackError,
    FeedbackLogCorruptError,
    FeedbackValidationError,
    append_jsonl_atomic,
    log_review,
    read_jsonl,
)


def _review(review_id: str = "review-race") -> dict[str, object]:
    return {
        "review_id": review_id,
        "timestamp": "2026-07-16T00:00:00Z",
        "skill_version": "1.0.0",
        "rules_version": "rules-v1",
        "input_revision": "sha256:synthetic",
        "findings": [],
        "suppressed_findings": [],
        "observations": [],
        "verdict": "approve",
        "escalation": False,
        "architect_action": None,
    }


def test_missing_log_read_does_not_create_file(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "reviews.jsonl"

    assert read_jsonl(path) == []
    assert not path.exists()


def test_feedback_log_creates_nested_parents_without_symlinks(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "audit" / "reviews.jsonl"

    event = log_review(path, _review())

    assert read_jsonl(path) == [event]


def test_feedback_log_rejects_symlinked_parent_without_touching_target(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(outside, target_is_directory=True)
    path = linked_parent / "reviews.jsonl"

    with pytest.raises(FeedbackLogCorruptError, match="parent directory"):
        read_jsonl(path)
    with pytest.raises(FeedbackLogCorruptError, match="parent directory"):
        log_review(path, _review())
    assert not (outside / "reviews.jsonl").exists()


def test_feedback_log_parent_swap_cannot_redirect_leaf_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "audit"
    parent.mkdir()
    pinned_parent = tmp_path / "audit-pinned"
    outside = tmp_path / "outside"
    outside.mkdir()
    path = parent / "reviews.jsonl"
    real_inspect = feedback_module._inspect_log_entry
    swapped = False

    def racing_inspect(
        candidate: Path, parent_descriptor: int, leaf: str
    ) -> os.stat_result | None:
        nonlocal swapped
        result = real_inspect(candidate, parent_descriptor, leaf)
        if not swapped:
            parent.rename(pinned_parent)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return result

    monkeypatch.setattr(feedback_module, "_inspect_log_entry", racing_inspect)

    event = log_review(path, _review())

    assert swapped
    assert not (outside / path.name).exists()
    assert (pinned_parent / path.name).is_file()
    parent.unlink()
    pinned_parent.rename(parent)
    assert read_jsonl(path) == [event]


def test_feedback_log_rejects_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "outside.jsonl"
    original = b'{"outside":true}\n'
    target.write_bytes(original)
    link = tmp_path / "reviews.jsonl"
    link.symlink_to(target)

    with pytest.raises(FeedbackLogCorruptError, match="symlink"):
        read_jsonl(link)
    with pytest.raises(FeedbackLogCorruptError, match="symlink"):
        log_review(link, _review())
    assert target.read_bytes() == original


def test_feedback_log_rejects_hardlink_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "outside.jsonl"
    original = b'{"outside":true}\n'
    source.write_bytes(original)
    hardlink = tmp_path / "reviews.jsonl"
    try:
        os.link(source, hardlink)
    except OSError as exc:  # pragma: no cover - unusual temporary filesystem
        pytest.skip(f"hardlinks unsupported by temporary filesystem: {exc}")

    with pytest.raises(FeedbackLogCorruptError, match="hardlink"):
        read_jsonl(hardlink)
    with pytest.raises(FeedbackLogCorruptError, match="hardlink"):
        log_review(hardlink, _review())
    assert source.read_bytes() == original


def test_feedback_log_rejects_non_regular_path(tmp_path: Path) -> None:
    directory = tmp_path / "reviews.jsonl"
    directory.mkdir()

    with pytest.raises(FeedbackLogCorruptError, match="not a regular file"):
        read_jsonl(directory)
    with pytest.raises(FeedbackLogCorruptError, match="not a regular file"):
        log_review(directory, _review())


def test_feedback_log_byte_read_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reviews.jsonl"
    original = b'{"padding":"' + (b"x" * 64) + b'"}\n'
    path.write_bytes(original)
    monkeypatch.setattr(feedback_module, "MAX_FEEDBACK_LOG_BYTES", 32)

    with pytest.raises(FeedbackLogCorruptError, match="byte limit"):
        read_jsonl(path)
    with pytest.raises(FeedbackLogCorruptError, match="byte limit"):
        log_review(path, _review())
    assert path.read_bytes() == original


def test_feedback_log_record_read_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_bytes(b"{}\n{}\n{}\n")
    monkeypatch.setattr(feedback_module, "MAX_FEEDBACK_LOG_RECORDS", 2)

    with pytest.raises(FeedbackLogCorruptError, match="record limit"):
        read_jsonl(path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            b'{"event_type":"review","event_type":"architect_action"}\n',
            "duplicate JSON key",
        ),
        (
            b'{"event_type":"review","confidence":NaN}\n',
            "non-finite JSON number",
        ),
        (b"{}\n", "invalid event schema"),
        (
            b'{"event_type":"unknown"}\n',
            "event_type must be review, architect_action, or evolution_attempt",
        ),
    ],
)
def test_feedback_log_rejects_ambiguous_or_malformed_events(
    tmp_path: Path, payload: bytes, message: str
) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_bytes(payload)

    with pytest.raises(FeedbackLogCorruptError, match=message):
        read_jsonl(path)
    with pytest.raises(FeedbackLogCorruptError, match=message):
        log_review(path, _review("review-after-corruption"))
    assert path.read_bytes() == payload


def test_feedback_writer_rejects_unknown_fields_and_non_finite_values(
    tmp_path: Path,
) -> None:
    unknown = _review("review-unknown")
    unknown["unexpected"] = True
    with pytest.raises(FeedbackValidationError, match="unknown fields"):
        log_review(tmp_path / "unknown.jsonl", unknown)

    non_finite = _review("review-nan")
    non_finite["findings"] = [{"confidence": float("nan")}]
    with pytest.raises(FeedbackValidationError, match="JSON serialisable"):
        log_review(tmp_path / "nan.jsonl", non_finite)


def test_supported_evolution_event_round_trips_strictly(tmp_path: Path) -> None:
    path = tmp_path / "evolution.jsonl"
    event = {
        "event_type": "evolution_attempt",
        "cycle_id": "aga-20260716T000000Z-12345678",
        "timestamp": "2026-07-16T00:00:00Z",
        "precedent": "precedent:0001",
        "attempt": 1,
        "result": "validation_error",
        "error": "synthetic invalid candidate",
        "gate_checks": [],
    }

    append_jsonl_atomic(path, event)

    assert read_jsonl(path) == [event]


def test_feedback_log_fails_closed_without_safe_platform_primitives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_bytes(b"{}\n")
    monkeypatch.setattr(feedback_module, "fcntl", None)
    with pytest.raises(FeedbackError, match="interprocess file-lock"):
        read_jsonl(path)


def test_feedback_log_fails_closed_without_no_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "reviews.jsonl"
    path.write_bytes(b"{}\n")
    monkeypatch.delattr(feedback_module.os, "O_NOFOLLOW")

    with pytest.raises(FeedbackError, match="O_NOFOLLOW"):
        read_jsonl(path)


_RACE_SCRIPT = r"""
from pathlib import Path
import sys
import time

sys.path.insert(0, sys.argv[1])
from tools.feedback import DuplicateFeedbackError, log_review, record_architect_action

log_path = Path(sys.argv[2])
start_path = Path(sys.argv[3])
operation = sys.argv[4]
deadline = time.monotonic() + 10
while not start_path.exists():
    if time.monotonic() >= deadline:
        raise RuntimeError("race start timed out")
    time.sleep(0.001)

review = {
    "review_id": "review-race",
    "timestamp": "2026-07-16T00:00:00Z",
    "skill_version": "1.0.0",
    "rules_version": "rules-v1",
    "input_revision": "sha256:synthetic",
    "findings": [],
    "suppressed_findings": [],
    "observations": [],
    "verdict": "approve",
    "escalation": False,
    "architect_action": None,
}
try:
    if operation == "review":
        log_review(log_path, review)
    else:
        record_architect_action(
            log_path,
            review_id="review-race",
            action="accept",
            actor="architect@example.test",
            timestamp="2026-07-16T00:01:00Z",
        )
except DuplicateFeedbackError:
    print("duplicate")
else:
    print("added")
"""


def _race_same_event(log_path: Path, start_path: Path, operation: str) -> list[str]:
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _RACE_SCRIPT,
                str(PKG_ROOT),
                str(log_path),
                str(start_path),
                operation,
            ],
            cwd=PKG_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(6)
    ]
    outputs: list[str] = []
    try:
        start_path.touch()
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
            outputs.append(stdout.strip())
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    return outputs


def test_duplicate_review_and_action_are_atomic_across_processes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reviews.jsonl"

    review_results = _race_same_event(path, tmp_path / "start-review", "review")
    assert review_results.count("added") == 1
    assert review_results.count("duplicate") == 5
    assert len(read_jsonl(path)) == 1

    action_results = _race_same_event(path, tmp_path / "start-action", "action")
    assert action_results.count("added") == 1
    assert action_results.count("duplicate") == 5
    events = read_jsonl(path)
    assert [event["event_type"] for event in events] == [
        "review",
        "architect_action",
    ]
