"""Lethe adapter for the Studio Phase 7 allowed-path memory.

Writes one MemoryItem per 'supported' verdict into a per-project Lethe
SQLiteBackend at <studio_db_dir>/phase7/{project_id}.sqlite. Each item
is tagged with run:{run_id}, project:{project_id}, source:{source_id},
v{version} so the run_id is filterable for traceability.

Why per-project: each project's memory is its own. No cross-project
leak. The Lethe backend's SQLite file lives next to the Studio DB
under a 'phase7/' subdirectory.

Why HashFakeEmbedder: no sentence-transformers dependency for v1. Real
embeddings are a v1.5 enhancement.

Why _ThreadSafeSQLiteBackend: Lethe's stock SQLiteBackend opens with
the default check_same_thread=True. Studio's handler can be invoked
from a different thread than where the connection was first opened
(FastAPI under TestClient, ASGI workers under uvicorn), so we open
with check_same_thread=False. SQLite serializes writes itself; the
absence of cross-connection locking is fine for our usage.

Public entry points:
  write_supported_claims(*, project_id, run_id, verdicts, source_versions,
                         db_dir) -> list[str]
  recall_run_claims(*, project_id, run_id, db_dir) -> list[MemoryItem]
"""

from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from elenchus.types import Verdict

from lethe import DecayConfig, MemoryStore
from lethe.backends.sqlite_backend import SQLiteBackend
from lethe.embeddings import HashFakeEmbedder
from lethe.memory_item import MemoryItem


_TAG_PREFIX_RUN = "run:"
_TAG_PREFIX_PROJECT = "project:"
_TAG_PREFIX_SOURCE = "source:"
_TAG_PREFIX_VERSION = "v"
_TAG_VERIFIED = "elenchus_verified"


def _phase7_dir(db_dir: Path) -> Path:
    """Return the per-project Lethe DB directory; create if missing."""
    out = Path(db_dir) / "phase7"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _project_db_path(db_dir: Path, project_id: str) -> Path:
    return _phase7_dir(db_dir) / f"{project_id}.sqlite"


class _ThreadSafeSQLiteBackend(SQLiteBackend):
    """SQLiteBackend subclass that lets the connection cross threads.

    Lethe 0.1.0's stock SQLiteBackend opens with check_same_thread=True
    (the sqlite3 default). The Studio handler can be invoked from a
    thread different from the one that first opened the file (e.g.
    when ASGI dispatch or TestClient switches threads). We trade a
    little thread safety for the Studio's reality: SQLite serializes
    writes per-connection so we never get a torn write, and the
    backend's reads/writes are tiny.

    We don't touch lethe's schema bootstrap — we still call the
    parent __init__.
    """

    def __init__(self, path: str | Path) -> None:  # type: ignore[override]
        # Open with check_same_thread=False BEFORE parent __init__ runs.
        # The parent calls sqlite3.connect again internally, which
        # overwrites self._conn; we then close-and-replace with our
        # thread-safe connection.
        self._path = str(path)
        super().__init__(self._path)
        self._conn.close()
        self._conn = sqlite3.connect(
            self._path,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row


@lru_cache(maxsize=64)
def _open_store(db_dir_str: str, project_id: str) -> MemoryStore:
    """Open (and cache) the per-project Lethe MemoryStore.

    The lru_cache means we re-use a single MemoryStore per (db_dir,
    project_id) within the process. _ThreadSafeSQLiteBackend lets the
    underlying connection be used from any thread (the Studio handler
    may run on a worker thread distinct from the writer).
    """
    db_dir = Path(db_dir_str)
    backend = _ThreadSafeSQLiteBackend(_project_db_path(db_dir, project_id))
    store = MemoryStore(
        backend=backend,
        embedder=HashFakeEmbedder(),
        decay_config=DecayConfig(),
    )
    return store


def _resolve_db_dir(db_dir: Optional[Path]) -> Path:
    if db_dir is not None:
        return Path(db_dir)
    env = os.environ.get("ELENCHUS_STUDIO_DB_DIR")
    if env:
        return Path(env)
    raise ValueError(
        "db_dir must be provided or ELENCHUS_STUDIO_DB_DIR must be set."
    )


def write_supported_claims(
    *,
    project_id: str,
    run_id: str,
    verdicts: List[Verdict],
    source_versions: Dict[str, int],
    db_dir: Optional[Path] = None,
) -> List[str]:
    """Write one MemoryItem per supported verdict. Return the memory_ids.

    Only verdicts with label == 'supported' are written (Plan.md:
    "exactly the supported claims and only those"). The returned list
    is in input order so the /checks handler can persist it 1:1 with
    the verdict list (filtering out the skipped ones in lockstep).
    """
    resolved_db_dir = _resolve_db_dir(db_dir)
    store = _open_store(str(resolved_db_dir), project_id)
    memory_ids: List[str] = []
    for verdict in verdicts:
        if verdict.label != "supported":
            continue
        evidence = verdict.evidence
        source_id = evidence.source_id if evidence is not None else "unknown"
        version = source_versions.get(source_id, 0)
        tags = [
            _TAG_VERIFIED,
            f"{_TAG_PREFIX_RUN}{run_id}",
            f"{_TAG_PREFIX_PROJECT}{project_id}",
            f"{_TAG_PREFIX_SOURCE}{source_id}",
            f"{_TAG_PREFIX_VERSION}{version}",
        ]
        item = store.remember(
            content=verdict.claim.text,
            session_id=project_id,
            tags=tags,
        )
        memory_ids.append(item.id)
    return memory_ids


def recall_run_claims(
    *,
    project_id: str,
    run_id: str,
    db_dir: Optional[Path] = None,
) -> List[MemoryItem]:
    """Return all MemoryItems tagged with run:{run_id} for this project.

    Filters via the backend's list_all() (Lethe's MemoryStore.recall
    does not support tag-based `where=` clauses).
    """
    resolved_db_dir = _resolve_db_dir(db_dir)
    store = _open_store(str(resolved_db_dir), project_id)
    target_tag = f"{_TAG_PREFIX_RUN}{run_id}"
    return [item for item in store.backend.list_all() if target_tag in item.tags]


__all__ = ["write_supported_claims", "recall_run_claims"]
