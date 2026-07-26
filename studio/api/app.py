"""Studio FastAPI app.

Endpoints (per Plan.md Phase 5 acceptance):

- POST /projects                                       — create project
- GET  /projects                                       — list projects
- GET  /projects/{project_id}                          — get project
- POST /projects/{project_id}/source-documents         — add source doc
- GET  /projects/{project_id}/source-documents         — list source docs
- GET  /projects/{project_id}/source-documents/{sid}   — get source doc (latest by default)
- PATCH /projects/{project_id}/source-documents/{sid}  — edit source doc (bumps version)
- POST /projects/{project_id}/checks                   — submit a check
- GET  /projects/{project_id}/runs                     — list run history
- GET  /runs/{run_id}                                  — get a single run
- GET  /projects/{project_id}/gate-policy              — get gate policy
- PUT  /projects/{project_id}/gate-policy              — set gate policy

Per Rule 7, the handler that submits a check uses only the public
`elenchus.verifier.Verifier` API (verify + verify_claim). Internal
modules are not touched.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable, List, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from elenchus.config import VerificationConfig
from elenchus.types import Verdict
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier

from studio.db.store import StudioStore
from studio.gate import GatePolicy, evaluate_gate


NliFactory = Callable[[VerificationConfig], object]


# ---------- Request / response models ---------------------------------------


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    id: str
    name: str
    created_at: datetime


class AddSourceDocumentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str


class UpdateSourceDocumentRequest(BaseModel):
    content: str


class SourceDocumentResponse(BaseModel):
    id: str
    project_id: str
    name: str
    content: str
    content_sha256: str
    version: int
    created_at: datetime
    updated_at: datetime


class SubmitCheckRequest(BaseModel):
    question: Optional[str] = None
    model_or_prompt_label: str = Field(min_length=1, max_length=200)
    candidate_answer: str


class CheckResponse(BaseModel):
    id: str
    project_id: str
    question: Optional[str]
    model_or_prompt_label: str
    candidate_answer: str
    source_document_versions: dict
    verdicts: List[dict]
    gate_result: str
    latency_ms: float
    created_at: datetime


class GatePolicyRequest(BaseModel):
    block_on_any_contradiction: bool = True
    flag_if_unverifiable_count_exceeds: int = Field(default=1, ge=0)


class GatePolicyResponse(BaseModel):
    block_on_any_contradiction: bool
    flag_if_unverifiable_count_exceeds: int


# ---------- Serialization helpers -------------------------------------------


def _project_to_dict(p) -> dict:
    return {"id": p.id, "name": p.name, "created_at": p.created_at}


def _source_doc_to_dict(d) -> dict:
    return {
        "id": d.id,
        "project_id": d.project_id,
        "name": d.name,
        "content": d.content,
        "content_sha256": d.content_sha256,
        "version": d.version,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


def _verdict_to_dict(v: Verdict) -> dict:
    return {
        "claim": {
            "id": v.claim.id,
            "text": v.claim.text,
            "span": list(v.claim.span),
        },
        "label": v.label,
        "confidence": v.confidence,
        "tier": v.tier,
        "evidence": (
            None
            if v.evidence is None
            else {
                "source_id": v.evidence.source_id,
                "text": v.evidence.text,
                "span": list(v.evidence.span),
            }
        ),
        "checked_at": v.checked_at,
    }


def _run_to_dict(r) -> dict:
    return {
        "id": r.id,
        "project_id": r.project_id,
        "question": r.question,
        "model_or_prompt_label": r.model_or_prompt_label,
        "candidate_answer": r.candidate_answer,
        "source_document_versions": dict(r.source_document_versions),
        "verdicts": [_verdict_to_dict(v) for v in r.verdicts],
        "gate_result": r.gate_result,
        "latency_ms": r.latency_ms,
        "created_at": r.created_at,
    }


# ---------- App factory -----------------------------------------------------


def create_app(
    *,
    store: StudioStore,
    nli_factory: Optional[NliFactory] = None,
) -> FastAPI:
    """Build the Studio FastAPI app.

    The store is owned by the caller (so tests can share a temp DB). The
    `nli_factory` builds the NLI instance per check; if absent, the
    Verifier falls back to its default (real cross-encoder model).
    """
    app = FastAPI(
        title="Elenchus Studio",
        description="Backend API for Elenchus verification runs.",
        version="0.1.0",
    )

    # ---- Project endpoints ----------------------------------------------

    @app.post("/projects", response_model=ProjectResponse)
    def create_project(req: CreateProjectRequest) -> dict:
        p = store.create_project(name=req.name)
        return _project_to_dict(p)

    @app.get("/projects", response_model=List[ProjectResponse])
    def list_projects() -> list:
        return [_project_to_dict(p) for p in store.list_projects()]

    @app.get("/projects/{project_id}", response_model=ProjectResponse)
    def get_project(project_id: str) -> dict:
        try:
            p = store.get_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")
        return _project_to_dict(p)

    # ---- Source document endpoints --------------------------------------

    @app.post(
        "/projects/{project_id}/source-documents",
        response_model=SourceDocumentResponse,
    )
    def add_source_document(project_id: str, req: AddSourceDocumentRequest) -> dict:
        try:
            store.get_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")
        doc = store.add_source_document(
            project_id=project_id, name=req.name, content=req.content
        )
        return _source_doc_to_dict(doc)

    @app.get(
        "/projects/{project_id}/source-documents",
        response_model=List[SourceDocumentResponse],
    )
    def list_source_documents(project_id: str) -> list:
        try:
            store.get_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")
        return [
            _source_doc_to_dict(d)
            for d in store.list_source_documents(project_id=project_id)
        ]

    @app.get(
        "/projects/{project_id}/source-documents/{source_id}",
        response_model=SourceDocumentResponse,
    )
    def get_source_document(
        project_id: str, source_id: str, version: Optional[int] = None
    ) -> dict:
        try:
            store.get_project(project_id)
            doc = store.get_source_document(source_id=source_id, version=version)
        except KeyError:
            raise HTTPException(status_code=404, detail="source document not found")
        return _source_doc_to_dict(doc)

    @app.patch(
        "/projects/{project_id}/source-documents/{source_id}",
        response_model=SourceDocumentResponse,
    )
    def update_source_document(
        project_id: str, source_id: str, req: UpdateSourceDocumentRequest
    ) -> dict:
        try:
            store.get_project(project_id)
            doc = store.update_source_document(
                source_id=source_id, new_content=req.content
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="source document not found")
        return _source_doc_to_dict(doc)

    # ---- Check endpoint -------------------------------------------------

    @app.post(
        "/projects/{project_id}/checks",
        response_model=CheckResponse,
    )
    def submit_check(project_id: str, req: SubmitCheckRequest) -> dict:
        try:
            store.get_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")

        # Load current source docs to feed the verifier.
        source_docs = store.list_source_documents(project_id=project_id)
        sources_for_verifier: List = [(d.name, d.content) for d in source_docs]

        # Build Verifier via the (optional) NLI factory.
        cfg = VerificationConfig()
        log = InMemoryVerificationLog()
        if nli_factory is not None:
            nli = nli_factory(cfg)
            verifier = Verifier(config=cfg, log=log, nli=nli)
        else:
            verifier = Verifier(config=cfg, log=log)

        # Run and time it.
        t0 = time.perf_counter()
        verdicts = verifier.verify(
            output_text=req.candidate_answer,
            source_documents=sources_for_verifier,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        # Pin source versions at the moment of verification.
        source_versions = {
            d.id: d.version for d in source_docs
        }

        # Evaluate the gate.
        policy = store.get_gate_policy(project_id=project_id)
        gate_result = evaluate_gate(policy, verdicts)

        run = store.record_run(
            project_id=project_id,
            question=req.question,
            model_or_prompt_label=req.model_or_prompt_label,
            candidate_answer=req.candidate_answer,
            source_versions=source_versions,
            verdicts=verdicts,
            gate_result=gate_result,
            latency_ms=latency_ms,
        )
        return _run_to_dict(run)

    # ---- Run endpoints --------------------------------------------------

    @app.get("/runs/{run_id}", response_model=CheckResponse)
    def get_run(run_id: str) -> dict:
        try:
            run = store.get_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        return _run_to_dict(run)

    @app.get(
        "/projects/{project_id}/runs",
        response_model=List[CheckResponse],
    )
    def list_runs(project_id: str) -> list:
        try:
            store.get_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")
        return [_run_to_dict(r) for r in store.list_runs(project_id=project_id)]

    # ---- Gate policy endpoints ------------------------------------------

    @app.get(
        "/projects/{project_id}/gate-policy",
        response_model=GatePolicyResponse,
    )
    def get_gate_policy(project_id: str) -> dict:
        try:
            store.get_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")
        p = store.get_gate_policy(project_id=project_id)
        return {
            "block_on_any_contradiction": p.block_on_any_contradiction,
            "flag_if_unverifiable_count_exceeds": p.flag_if_unverifiable_count_exceeds,
        }

    @app.put(
        "/projects/{project_id}/gate-policy",
        response_model=GatePolicyResponse,
    )
    def set_gate_policy(project_id: str, req: GatePolicyRequest) -> dict:
        try:
            p = store.set_gate_policy(
                project_id=project_id,
                policy=GatePolicy(
                    block_on_any_contradiction=req.block_on_any_contradiction,
                    flag_if_unverifiable_count_exceeds=req.flag_if_unverifiable_count_exceeds,
                ),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")
        return {
            "block_on_any_contradiction": p.block_on_any_contradiction,
            "flag_if_unverifiable_count_exceeds": p.flag_if_unverifiable_count_exceeds,
        }

    return app


__all__ = ["create_app"]
