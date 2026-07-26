import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createProject,
  listProjects,
  getProject,
  addSourceDocument,
  listSourceDocuments,
  getSourceDocument,
  updateSourceDocument,
  submitCheck,
  getRun,
  listRuns,
  getGatePolicy,
  setGatePolicy,
} from "../src/api";

const originalFetch = global.fetch;

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    ),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe("apiCall", () => {
  it("createProject POSTs to /api/projects with the name", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "p1", name: "kb", created_at: "t" }), {
        status: 200,
      }),
    );
    const p = await createProject({ name: "kb" });
    expect(p.id).toBe("p1");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
        body: JSON.stringify({ name: "kb" }),
      }),
    );
  });

  it("listProjects GETs /api/projects", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await listProjects();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("throws ApiError with parsed detail on 4xx", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "project not found" }), {
        status: 404,
      }),
    );
    await expect(getProject("missing")).rejects.toThrow("project not found");
  });

  it("addSourceDocument POSTs to /api/projects/:id/source-documents", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "d1",
          project_id: "p1",
          name: "kb",
          content: "x",
          content_sha256: "abc",
          version: 1,
          created_at: "t",
          updated_at: "t",
        }),
        { status: 200 },
      ),
    );
    await addSourceDocument("p1", { name: "kb", content: "x" });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/source-documents",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("updateSourceDocument PATCHes with the new content", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "d1", version: 2 }), { status: 200 }),
    );
    await updateSourceDocument("p1", "d1", { content: "new" });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/source-documents/d1",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ content: "new" }) }),
    );
  });

  it("getSourceDocument includes ?version=N when supplied", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "d1", version: 1 }), { status: 200 }),
    );
    await getSourceDocument("p1", "d1", 1);
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/source-documents/d1?version=1",
      expect.any(Object),
    );
  });

  it("submitCheck POSTs to /api/projects/:id/checks", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "r1",
          project_id: "p1",
          question: "q",
          model_or_prompt_label: "gpt",
          candidate_answer: "a",
          source_document_versions: {},
          verdicts: [],
          gate_result: "allowed",
          latency_ms: 10,
          created_at: "t",
        }),
        { status: 200 },
      ),
    );
    await submitCheck("p1", {
      question: "q",
      model_or_prompt_label: "gpt",
      candidate_answer: "a",
    });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/checks",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("getRun GETs /api/runs/:id", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "r1" }), { status: 200 }),
    );
    await getRun("r1");
    expect(global.fetch).toHaveBeenCalledWith("/api/runs/r1", expect.any(Object));
  });

  it("listRuns GETs /api/projects/:id/runs", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await listRuns("p1");
    expect(global.fetch).toHaveBeenCalledWith("/api/projects/p1/runs", expect.any(Object));
  });

  it("listSourceDocuments GETs /api/projects/:id/source-documents", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await listSourceDocuments("p1");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/source-documents",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("getGatePolicy GETs /api/projects/:id/gate-policy", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          block_on_any_contradiction: true,
          flag_if_unverifiable_count_exceeds: 1,
        }),
        { status: 200 },
      ),
    );
    await getGatePolicy("p1");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/gate-policy",
      expect.any(Object),
    );
  });

  it("setGatePolicy PUTs to /api/projects/:id/gate-policy", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          block_on_any_contradiction: false,
          flag_if_unverifiable_count_exceeds: 0,
        }),
        { status: 200 },
      ),
    );
    await setGatePolicy("p1", {
      block_on_any_contradiction: false,
      flag_if_unverifiable_count_exceeds: 0,
    });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/gate-policy",
      expect.objectContaining({ method: "PUT" }),
    );
  });
});
