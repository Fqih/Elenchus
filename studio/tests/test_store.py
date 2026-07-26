"""Tests for the Studio SQLite-backed store.

The store's job is to persist Projects, SourceDocuments (with content
hash + version), and VerificationRuns (with the source-document version
each run was actually checked against). Per Schema.md, a run pins the
version of every source document it was verified against, so editing a
document later does not retroactively change the run's reproducibility.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from elenchus.types import Claim, Verdict

from studio.db.store import (
    StudioStore,
    Project,
    SourceDocument,
    VerificationRun,
)
from studio.gate import GatePolicy


# ---------- Helpers ----------------------------------------------------------


def _tmp_store() -> StudioStore:
    f = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    f.close()
    return StudioStore(Path(f.name))


def _verdict(label: str, text: str = "x", confidence: float = 0.9) -> Verdict:
    return Verdict(
        claim=Claim(id="c", text=text, span=(0, len(text))),
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        tier="nli",
        evidence=None,
        checked_at=datetime.now(timezone.utc),
    )


# ---------- Project CRUD -----------------------------------------------------


def test_create_project_returns_project_with_id_and_name() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    assert p.id != ""
    assert p.name == "kb-test"
    assert isinstance(p.created_at, datetime)


def test_get_project_returns_same_project() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    fetched = store.get_project(p.id)
    assert fetched.id == p.id
    assert fetched.name == p.name


def test_get_project_missing_raises_keyerror() -> None:
    store = _tmp_store()
    try:
        store.get_project("does-not-exist")
    except KeyError:
        return
    raise AssertionError("expected KeyError for missing project")


def test_list_projects_returns_all() -> None:
    store = _tmp_store()
    a = store.create_project(name="a")
    b = store.create_project(name="b")
    assert {p.id for p in store.list_projects()} == {a.id, b.id}


# ---------- SourceDocument CRUD + version pinning ---------------------------


def test_add_source_document_assigns_version_1_and_sha256() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    doc = store.add_source_document(
        project_id=p.id, name="doc-1", content="hello world"
    )
    assert doc.version == 1
    assert doc.content_sha256 != ""
    assert len(doc.content_sha256) == 64  # sha256 hex
    assert doc.content == "hello world"
    assert doc.project_id == p.id


def test_same_content_different_documents_have_same_sha256() -> None:
    # The hash is for content identity, not doc identity.
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    a = store.add_source_document(project_id=p.id, name="doc-1", content="abc")
    b = store.add_source_document(project_id=p.id, name="doc-2", content="abc")
    assert a.content_sha256 == b.content_sha256
    assert a.id != b.id


def test_update_source_document_bumps_version() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    v1 = store.add_source_document(project_id=p.id, name="doc-1", content="old")
    v2 = store.update_source_document(source_id=v1.id, new_content="new")
    assert v2.version == 2
    assert v2.content == "new"
    assert v2.content_sha256 != v1.content_sha256
    assert v2.id == v1.id


def test_get_source_document_at_specific_version() -> None:
    # This is the load-bearing requirement: a run points at a version,
    # and that version must be retrievable later even after the document
    # has been edited.
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    v1 = store.add_source_document(project_id=p.id, name="doc-1", content="v1")
    v2 = store.update_source_document(source_id=v1.id, new_content="v2")
    assert v2.version == 2

    snap = store.get_source_document(source_id=v1.id, version=1)
    assert snap.content == "v1"
    assert snap.version == 1

    snap = store.get_source_document(source_id=v1.id, version=2)
    assert snap.content == "v2"
    assert snap.version == 2


def test_get_source_document_latest_version_by_default() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    v1 = store.add_source_document(project_id=p.id, name="doc-1", content="v1")
    v2 = store.update_source_document(source_id=v1.id, new_content="v2")
    snap = store.get_source_document(source_id=v1.id)
    assert snap.version == 2
    assert snap.content == "v2"


def test_list_source_documents_for_project() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    a = store.add_source_document(project_id=p.id, name="doc-a", content="a")
    b = store.add_source_document(project_id=p.id, name="doc-b", content="b")
    docs = store.list_source_documents(project_id=p.id)
    assert {d.id for d in docs} == {a.id, b.id}


def test_update_missing_doc_raises_keyerror() -> None:
    store = _tmp_store()
    try:
        store.update_source_document(source_id="nope", new_content="x")
    except KeyError:
        return
    raise AssertionError("expected KeyError for missing source document")


# ---------- VerificationRun + version pinning -------------------------------


def test_record_run_records_locked_source_versions() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    a = store.add_source_document(project_id=p.id, name="doc-a", content="a")
    b = store.add_source_document(project_id=p.id, name="doc-b", content="b")
    verdicts = [_verdict("supported", "claim 1")]

    run = store.record_run(
        project_id=p.id,
        question="What is a?",
        model_or_prompt_label="gpt4",
        candidate_answer="a is the first letter.",
        source_versions={a.id: 1, b.id: 1},
        verdicts=verdicts,
        gate_result="allowed",
        latency_ms=12.5,
    )
    assert run.project_id == p.id
    assert run.source_document_versions == {a.id: 1, b.id: 1}
    assert run.gate_result == "allowed"
    assert run.latency_ms == 12.5
    assert len(run.verdicts) == 1


def test_get_run_returns_same_run() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    run = store.record_run(
        project_id=p.id,
        question="q",
        model_or_prompt_label="m",
        candidate_answer="a",
        source_versions={},
        verdicts=[],
        gate_result="allowed",
        latency_ms=1.0,
    )
    fetched = store.get_run(run.id)
    assert fetched.id == run.id
    assert fetched.candidate_answer == "a"


def test_run_survives_source_edit_via_version_pin() -> None:
    # The acceptance criterion from Plan.md Phase 5: editing a source
    # document bumps its version AND a previously-recorded run still
    # points at the version it was actually checked against.
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    doc = store.add_source_document(project_id=p.id, name="doc", content="ORIG")
    run = store.record_run(
        project_id=p.id,
        question="q",
        model_or_prompt_label="m",
        candidate_answer="orig answer",
        source_versions={doc.id: 1},
        verdicts=[_verdict("supported", "orig")],
        gate_result="allowed",
        latency_ms=1.0,
    )
    # Edit the source doc.
    store.update_source_document(source_id=doc.id, new_content="EDITED")

    # The run still claims it was run against v1.
    snap = store.get_source_document(source_id=doc.id, version=1)
    assert snap.content == "ORIG"
    assert run.source_document_versions == {doc.id: 1}


def test_list_runs_for_project_in_chronological_order() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    import time

    runs: List[VerificationRun] = []
    for label in ["model-a", "model-b", "model-c"]:
        r = store.record_run(
            project_id=p.id,
            question="q",
            model_or_prompt_label=label,
            candidate_answer="ans",
            source_versions={},
            verdicts=[],
            gate_result="allowed",
            latency_ms=1.0,
        )
        runs.append(r)
        time.sleep(0.001)  # ensure distinct timestamps

    fetched = store.list_runs(project_id=p.id)
    fetched_labels = [r.model_or_prompt_label for r in fetched]
    assert fetched_labels == ["model-a", "model-b", "model-c"]


def test_record_run_missing_project_raises_keyerror() -> None:
    store = _tmp_store()
    try:
        store.record_run(
            project_id="nope",
            question="q",
            model_or_prompt_label="m",
            candidate_answer="a",
            source_versions={},
            verdicts=[],
            gate_result="allowed",
            latency_ms=1.0,
        )
    except KeyError:
        return
    raise AssertionError("expected KeyError for missing project")


# ---------- Gate policy (Rule 2) --------------------------------------------


def test_gate_policy_default_is_default_when_unset() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    policy = store.get_gate_policy(project_id=p.id)
    assert policy == GatePolicy()


def test_set_gate_policy_persists_and_round_trips() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    custom = GatePolicy(
        block_on_any_contradiction=False,
        flag_if_unverifiable_count_exceeds=5,
    )
    store.set_gate_policy(project_id=p.id, policy=custom)
    fetched = store.get_gate_policy(project_id=p.id)
    assert fetched == custom


def test_set_gate_policy_overwrites_existing() -> None:
    store = _tmp_store()
    p = store.create_project(name="kb-test")
    store.set_gate_policy(
        project_id=p.id, policy=GatePolicy(flag_if_unverifiable_count_exceeds=2)
    )
    store.set_gate_policy(
        project_id=p.id, policy=GatePolicy(flag_if_unverifiable_count_exceeds=10)
    )
    assert (
        store.get_gate_policy(project_id=p.id).flag_if_unverifiable_count_exceeds
        == 10
    )


def test_set_gate_policy_missing_project_raises_keyerror() -> None:
    store = _tmp_store()
    try:
        store.set_gate_policy(
            project_id="nope", policy=GatePolicy()
        )
    except KeyError:
        return
    raise AssertionError("expected KeyError for missing project")
