"""Studio FastAPI app.

Endpoints (all under /api):

- POST /api/projects                                       — create project
- GET  /api/projects                                       — list projects
- GET  /api/projects/{project_id}                          — get project
- POST /api/projects/{project_id}/source-documents         — add source doc
- GET  /api/projects/{project_id}/source-documents         — list source docs
- GET  /api/projects/{project_id}/source-documents/{sid}   — get source doc (latest by default)
- PATCH /api/projects/{project_id}/source-documents/{sid}  — edit source doc (bumps version)
- POST /api/projects/{project_id}/checks                   — submit a check
- GET  /api/projects/{project_id}/runs                     — list run history
- GET  /api/runs/{run_id}                                  — get a single run
- GET  /api/projects/{project_id}/gate-policy              — get gate policy
- PUT  /api/projects/{project_id}/gate-policy              — set gate policy

Per Rule 7, the handler that submits a check uses only the public
`elenchus.verifier.Verifier` API (verify + verify_claim). Internal
modules are not touched.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from elenchus.config import VerificationConfig
from elenchus.types import Verdict
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier

from studio.db.store import StudioStore
from studio.gate import GatePolicy, evaluate_gate
from studio.integrations import (
    Phase7DependencyError,
    run_retry,
    write_supported_claims,
)


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
    phase7_retry_stop_reason: Optional[str] = None
    phase7_retry_attempts: int = 0
    phase7_memory_item_ids: List[str] = Field(default_factory=list)


class GatePolicyRequest(BaseModel):
    block_on_any_contradiction: bool = True
    flag_if_unverifiable_count_exceeds: int = Field(default=1, ge=0)
    phase7_enabled: bool = False


class GatePolicyResponse(BaseModel):
    block_on_any_contradiction: bool
    flag_if_unverifiable_count_exceeds: int
    phase7_enabled: bool


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
        "phase7_retry_stop_reason": r.phase7_retry_stop_reason,
        "phase7_retry_attempts": r.phase7_retry_attempts,
        "phase7_memory_item_ids": list(r.phase7_memory_item_ids),
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api = APIRouter(prefix="/api")

    # ---- Project endpoints ----------------------------------------------

    @api.post("/projects", response_model=ProjectResponse)
    def create_project(req: CreateProjectRequest) -> dict:
        p = store.create_project(name=req.name)
        return _project_to_dict(p)

    @api.get("/projects", response_model=List[ProjectResponse])
    def list_projects() -> list:
        return [_project_to_dict(p) for p in store.list_projects()]

    @api.get("/projects/{project_id}", response_model=ProjectResponse)
    def get_project(project_id: str) -> dict:
        try:
            p = store.get_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")
        return _project_to_dict(p)

    # ---- Source document endpoints --------------------------------------

    @api.post(
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

    @api.get(
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

    @api.get(
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

    @api.patch(
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

    @api.post(
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

        # Persist the run first (gives us the run_id to tag Lethe items with).
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

        # Phase 7 integrations (post-persist; soft-fail per spec).
        retry_stop_reason: Optional[str] = None
        retry_attempts: int = 0
        memory_item_ids: List[str] = []

        if policy.phase7_enabled and gate_result == "blocked":
            try:
                retry = run_retry(
                    verifier, cfg,
                    candidate_answer=req.candidate_answer,
                    source_documents=sources_for_verifier,
                )
                retry_stop_reason = retry.stop_reason
                retry_attempts = retry.attempts
            except Phase7DependencyError:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Phase 7 retry requested but soteria-loop is not installed. "
                        "Install with: pip install -e \".[phase7]\" or pip install soteria-loop."
                    ),
                )
            except Exception:  # noqa: BLE001 — soft-fail per spec
                retry_stop_reason = "error"
                retry_attempts = 0

        elif policy.phase7_enabled and gate_result == "allowed":
            try:
                memory_item_ids = write_supported_claims(
                    project_id=project_id,
                    run_id=run.id,
                    verdicts=verdicts,
                    source_versions=source_versions,
                    db_dir=store._path.parent,  # noqa: SLF001
                )
            except Phase7DependencyError:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Phase 7 memory requested but lethe-agent is not installed. "
                        "Install with: pip install -e \".[phase7]\" or pip install lethe-agent."
                    ),
                )
            except Exception:  # noqa: BLE001 — soft-fail per spec
                memory_item_ids = []

        # flagged → skip both integrations (per spec)

        # If either integration populated state, update the run row.
        if retry_stop_reason or retry_attempts or memory_item_ids:
            store.update_run_phase7(
                run_id=run.id,
                phase7_retry_stop_reason=retry_stop_reason,
                phase7_retry_attempts=retry_attempts,
                phase7_memory_item_ids=memory_item_ids,
            )
            run.phase7_retry_stop_reason = retry_stop_reason
            run.phase7_retry_attempts = retry_attempts
            run.phase7_memory_item_ids = memory_item_ids

        return _run_to_dict(run)

    # ---- Run endpoints --------------------------------------------------

    @api.get("/runs/{run_id}", response_model=CheckResponse)
    def get_run(run_id: str) -> dict:
        try:
            run = store.get_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        return _run_to_dict(run)

    @api.get(
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

    @api.get(
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
            "phase7_enabled": p.phase7_enabled,
        }

    @api.put(
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
                    phase7_enabled=req.phase7_enabled,
                ),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="project not found")
        return {
            "block_on_any_contradiction": p.block_on_any_contradiction,
            "flag_if_unverifiable_count_exceeds": p.flag_if_unverifiable_count_exceeds,
            "phase7_enabled": p.phase7_enabled,
        }

    app.include_router(api)

    dist_dir = Path(__file__).parent.parent / "frontend" / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

        # SPA fallback: deep links like /projects/{id} are not real files in
        # the dist tree. StaticFiles would 404 them in production. This
        # catch-all returns index.html for any non-/api path that didn't
        # match a static file. Registered AFTER the static mount so the
        # mount gets first crack at serving real files.
        index_file = dist_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            if not index_file.is_file():
                raise HTTPException(
                    status_code=404,
                    detail="Frontend not built. Run: cd studio/frontend && npm run build",
                )
            return FileResponse(index_file)

    return app


__all__ = ["create_app"]
