# -*- coding: utf-8 -*-
"""Fail-closed durability and disclosure tests for private MCP receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys
import time

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for root in (REPOSITORY_ROOT, REPOSITORY_ROOT / "aga-skill"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts.private_receipt_journal import (  # noqa: E402
    MAX_EVENT_BYTES,
    PrivateReceiptJournal,
    ReceiptJournalError,
)
from tools.mcp_server import MCPApplication, MCPServerConfig  # noqa: E402
from tools.review_service import ReviewService  # noqa: E402


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_append_read_is_canonical_and_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "private" / "receipts.jsonl"
    journal = PrivateReceiptJournal(path)
    event = {
        "tool": "aga_prepare_review",
        "status": "ok",
        "args_sha256": "a" * 64,
        "output_sha256": "b" * 64,
    }

    journal.append(event)

    assert _mode(path.parent) == 0o700
    assert _mode(path) == 0o600
    assert journal.read() == (event,)
    assert path.read_bytes() == (
        json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def test_mcp_trace_journal_never_persists_raw_arguments_or_output(
    tmp_path: Path,
) -> None:
    path = tmp_path / "private" / "receipts.jsonl"
    journal = PrivateReceiptJournal(path)
    application = MCPApplication(
        ReviewService(),
        MCPServerConfig(),
        trace_sink=journal.append,
    )
    raw_argument = "synthetic-private-argument"
    raw_result = "synthetic-private-result"

    application._record_trace(  # noqa: SLF001 - security boundary regression
        "aga_finalize_review",
        {"review_id": "review-1", "semantic_result": raw_argument},
        "ok",
        time.monotonic(),
        {
            "schema": "aga.final-review/v1",
            "status": "completed",
            "review_id": "review-1",
            "review_digest": "rvw_" + "a" * 64,
            "task_digest": "tsk_" + "b" * 64,
            "raw_result": raw_result,
        },
    )

    persisted = path.read_text(encoding="utf-8")
    event = journal.read()[0]
    assert raw_argument not in persisted
    assert raw_result not in persisted
    assert "semantic_result" not in persisted
    assert "raw_result" not in persisted
    assert event["tool"] == "aga_finalize_review"
    assert event["args_sha256"] == hashlib.sha256(
        json.dumps(
            {"review_id": "review-1", "semantic_result": raw_argument},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert event["output_sha256"]
    application.close()


def test_existing_non_private_file_and_permission_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "private" / "receipts.jsonl"
    path.parent.mkdir()
    path.write_text("{}\n", encoding="utf-8")
    path.chmod(0o644)

    with pytest.raises(ReceiptJournalError, match="receipt_journal_not_private"):
        PrivateReceiptJournal(path)

    path.chmod(0o600)
    journal = PrivateReceiptJournal(path)
    path.chmod(0o640)
    with pytest.raises(ReceiptJournalError, match="receipt_journal_invalid"):
        journal.read()


@pytest.mark.parametrize(
    "corrupt",
    [
        b'{"tool":"first","tool":"second"}\n',
        b'{"duration_ms":NaN}\n',
        b'{"tool":\n',
        b'"not-an-object"\n',
        b"\xff\n",
        b"\n",
    ],
)
def test_corrupt_or_ambiguous_content_fails_closed(
    tmp_path: Path,
    corrupt: bytes,
) -> None:
    path = tmp_path / "private" / "receipts.jsonl"
    journal = PrivateReceiptJournal(path)
    path.write_bytes(corrupt)
    path.chmod(0o600)

    with pytest.raises(ReceiptJournalError, match="receipt_event_invalid"):
        journal.read()


def test_oversized_event_and_symlink_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "private" / "receipts.jsonl"
    journal = PrivateReceiptJournal(path)
    with pytest.raises(ReceiptJournalError, match="receipt_event_too_large"):
        journal.append({"value": "x" * MAX_EVENT_BYTES})

    target = tmp_path / "target.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "link.jsonl"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this filesystem")
    with pytest.raises(ReceiptJournalError, match="receipt_journal_unsafe"):
        PrivateReceiptJournal(link)
