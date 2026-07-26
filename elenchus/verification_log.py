"""Append-only Verification Log — Rule 4.

Every check produces a log entry. No exceptions, no silent drops. The log is
the audit trail that makes downstream debugging possible; without it, the
system is a black box.

Two backends share the `VerificationLog` protocol:
    - `InMemoryVerificationLog` — process-local, ephemeral.
    - `SQLiteVerificationLog` — durable across restarts.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from typing import List, Protocol

from elenchus.types import Claim, Evidence, LogEntry, Verdict


class VerificationLog(Protocol):
    """Append-only log interface. Backed by in-memory or SQLite."""

    def append(self, verdict: Verdict) -> None: ...
    def entries(self) -> List[LogEntry]: ...


class InMemoryVerificationLog:
    """Process-local, in-memory implementation. Not durable across restarts."""

    def __init__(self) -> None:
        self._entries: List[LogEntry] = []

    def append(self, verdict: Verdict) -> None:
        self._entries.append(
            LogEntry(verdict=verdict, logged_at=datetime.now(timezone.utc))
        )

    def entries(self) -> List[LogEntry]:
        # Return a copy so callers can't mutate the log.
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verdict_json TEXT NOT NULL,
    logged_at TEXT NOT NULL
);
"""


def _verdict_to_dict(v: Verdict) -> dict:
    d = asdict(v)
    d["checked_at"] = v.checked_at.astimezone(timezone.utc).isoformat()
    return d


def _verdict_from_dict(d: dict) -> Verdict:
    return Verdict(
        claim=Claim(**d["claim"]),
        label=d["label"],  # type: ignore[arg-type]
        confidence=float(d["confidence"]),
        tier=d["tier"],  # type: ignore[arg-type]
        evidence=Evidence(**d["evidence"]) if d.get("evidence") else None,
        checked_at=datetime.fromisoformat(d["checked_at"]),
    )


class SQLiteVerificationLog:
    """Durable Verification Log backed by SQLite.

    Stores a JSON blob per Verdict (verdict_json) plus a logged_at ISO
    timestamp. JSON is simpler than normalized columns here because the shape
    already lives in `elenchus.types` and Verdict is nested.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def append(self, verdict: Verdict) -> None:
        payload = json.dumps(_verdict_to_dict(verdict), separators=(",", ":"))
        self._conn.execute(
            "INSERT INTO log_entries (verdict_json, logged_at) VALUES (?, ?)",
            (payload, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def entries(self) -> List[LogEntry]:
        cur = self._conn.execute(
            "SELECT verdict_json, logged_at FROM log_entries ORDER BY id ASC"
        )
        out: List[LogEntry] = []
        for verdict_json, logged_at in cur.fetchall():
            out.append(
                LogEntry(
                    verdict=_verdict_from_dict(json.loads(verdict_json)),
                    logged_at=datetime.fromisoformat(logged_at),
                )
            )
        return out

    def close(self) -> None:
        self._conn.close()

    def __len__(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM log_entries")
        return int(cur.fetchone()[0])


__all__ = [
    "VerificationLog",
    "InMemoryVerificationLog",
    "SQLiteVerificationLog",
]
