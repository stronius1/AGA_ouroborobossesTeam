#!/usr/bin/env python3
"""Owner-only durable journal for bounded sanitized MCP receipt projections."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import threading
from typing import Any, Mapping


MAX_JOURNAL_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 10_000
MAX_EVENT_BYTES = 16 * 1024


class ReceiptJournalError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _strict_object(text: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate receipt event key")
            result[key] = value
        return result

    value = json.loads(
        text,
        object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(
            ValueError("non-finite receipt event number")
        ),
    )
    if not isinstance(value, dict):
        raise ValueError("receipt event must be an object")
    return value


class PrivateReceiptJournal:
    """Append/read only MCP trace projections without raw arguments/results."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ReceiptJournalError("receipt_journal_unsafe")
        if self.path.exists() and stat.S_IMODE(self.path.stat().st_mode) != 0o600:
            raise ReceiptJournalError("receipt_journal_not_private")

    def append(self, event: Mapping[str, Any]) -> None:
        if not isinstance(event, Mapping):
            raise ReceiptJournalError("receipt_event_invalid")
        raw = _canonical(dict(event)) + b"\n"
        if len(raw) > MAX_EVENT_BYTES:
            raise ReceiptJournalError("receipt_event_too_large")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        with self._lock:
            if self.path.exists() and self.path.stat().st_size + len(raw) > MAX_JOURNAL_BYTES:
                raise ReceiptJournalError("receipt_journal_too_large")
            descriptor = os.open(self.path, flags, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                written = os.write(descriptor, raw)
                if written != len(raw):
                    raise ReceiptJournalError("receipt_journal_write_failed")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def read(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            info = self.path.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > MAX_JOURNAL_BYTES
            ):
                raise ReceiptJournalError("receipt_journal_invalid")
            try:
                lines = self.path.read_bytes().splitlines()
            except OSError as exc:
                raise ReceiptJournalError("receipt_journal_unavailable") from exc
        if len(lines) > MAX_EVENTS:
            raise ReceiptJournalError("receipt_journal_too_many_events")
        events: list[dict[str, Any]] = []
        for line in lines:
            if not line or len(line) > MAX_EVENT_BYTES:
                raise ReceiptJournalError("receipt_event_invalid")
            try:
                value = _strict_object(line.decode("utf-8", errors="strict"))
            except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise ReceiptJournalError("receipt_event_invalid") from exc
            events.append(value)
        return tuple(events)


__all__ = ["PrivateReceiptJournal", "ReceiptJournalError"]
