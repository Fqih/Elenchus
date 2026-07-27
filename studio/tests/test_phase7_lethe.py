"""Unit tests for the Lethe adapter — supported-claims memory."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from elenchus.types import Claim, Evidence, Verdict

from studio.integrations.lethe import recall_run_claims, write_supported_claims


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _verdict(label: str, text: str = "C", source_id: str = "s1") -> Verdict:
    return Verdict(
        claim=Claim(id=f"c-{text[:4]}", text=text, span=(0, max(len(text), 1))),
        label=label,  # type: ignore[arg-type]
        confidence=0.9,
        tier="nli",
        evidence=Evidence(source_id=source_id, text="E", span=(0, 1)),
        checked_at=_now(),
    )


def test_writes_one_item_per_entailed_verdict(tmp_path: Path) -> None:
    verdicts = [
        _verdict("entailed", "claim A"),
        _verdict("contradicted", "claim B"),
        _verdict("entailed", "claim C"),
        _verdict("unverifiable", "claim D"),
    ]
    ids = write_supported_claims(
        project_id="p1", run_id="r1", verdicts=verdicts,
        source_versions={"s1": 3}, db_dir=tmp_path,
    )
    assert len(ids) == 2  # only the two entailed ones


def test_each_written_item_has_run_tag(tmp_path: Path) -> None:
    verdicts = [_verdict("entailed", "claim A")]
    ids = write_supported_claims(
        project_id="p1", run_id="r-xyz", verdicts=verdicts,
        source_versions={"s1": 1}, db_dir=tmp_path,
    )
    items = recall_run_claims(project_id="p1", run_id="r-xyz", db_dir=tmp_path)
    assert {item.id for item in items} == set(ids)
    for item in items:
        assert "run:r-xyz" in item.tags
        assert "project:p1" in item.tags
        assert "source:s1" in item.tags
        assert "v1" in item.tags
        assert "elenchus_verified" in item.tags


def test_recall_run_claims_filters_by_run(tmp_path: Path) -> None:
    v = [_verdict("entailed", "X")]
    write_supported_claims(
        project_id="p1", run_id="rA", verdicts=v,
        source_versions={"s1": 1}, db_dir=tmp_path,
    )
    write_supported_claims(
        project_id="p1", run_id="rB", verdicts=v,
        source_versions={"s1": 1}, db_dir=tmp_path,
    )
    a = recall_run_claims(project_id="p1", run_id="rA", db_dir=tmp_path)
    b = recall_run_claims(project_id="p1", run_id="rB", db_dir=tmp_path)
    assert len(a) == 1
    assert len(b) == 1
    assert a[0].id != b[0].id


def test_per_project_isolation(tmp_path: Path) -> None:
    v = [_verdict("entailed", "X")]
    write_supported_claims(
        project_id="pA", run_id="r1", verdicts=v,
        source_versions={"s1": 1}, db_dir=tmp_path,
    )
    write_supported_claims(
        project_id="pB", run_id="r1", verdicts=v,
        source_versions={"s1": 1}, db_dir=tmp_path,
    )
    a = recall_run_claims(project_id="pA", run_id="r1", db_dir=tmp_path)
    b = recall_run_claims(project_id="pB", run_id="r1", db_dir=tmp_path)
    a_ids = {i.id for i in a}
    b_ids = {i.id for i in b}
    assert a_ids.isdisjoint(b_ids)


def test_db_dir_env_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ELENCHUS_STUDIO_DB_DIR", str(tmp_path))
    v = [_verdict("entailed", "X")]
    ids = write_supported_claims(
        project_id="p1", run_id="r1", verdicts=v,
        source_versions={"s1": 1},
    )  # no db_dir
    assert len(ids) == 1
    items = recall_run_claims(project_id="p1", run_id="r1")
    assert len(items) == 1
