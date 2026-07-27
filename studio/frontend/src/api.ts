import type {
  Project,
  SourceDocument,
  Run,
  GatePolicy,
  MemoryClaim,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiCall<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    method: init.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // body was not JSON
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

// ---- Projects ----------------------------------------------------------

export function createProject(req: { name: string }): Promise<Project> {
  return apiCall<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function listProjects(): Promise<Project[]> {
  return apiCall<Project[]>("/api/projects");
}

export function getProject(projectId: string): Promise<Project> {
  return apiCall<Project>(`/api/projects/${projectId}`);
}

// ---- Source documents --------------------------------------------------

export function addSourceDocument(
  projectId: string,
  req: { name: string; content: string },
): Promise<SourceDocument> {
  return apiCall<SourceDocument>(
    `/api/projects/${projectId}/source-documents`,
    { method: "POST", body: JSON.stringify(req) },
  );
}

export function listSourceDocuments(projectId: string): Promise<SourceDocument[]> {
  return apiCall<SourceDocument[]>(`/api/projects/${projectId}/source-documents`);
}

export function getSourceDocument(
  projectId: string,
  sourceId: string,
  version?: number,
): Promise<SourceDocument> {
  const query = version !== undefined ? `?version=${version}` : "";
  return apiCall<SourceDocument>(
    `/api/projects/${projectId}/source-documents/${sourceId}${query}`,
  );
}

export function updateSourceDocument(
  projectId: string,
  sourceId: string,
  req: { content: string },
): Promise<SourceDocument> {
  return apiCall<SourceDocument>(
    `/api/projects/${projectId}/source-documents/${sourceId}`,
    { method: "PATCH", body: JSON.stringify(req) },
  );
}

// ---- Checks / runs -----------------------------------------------------

export function submitCheck(
  projectId: string,
  req: {
    question?: string | null;
    model_or_prompt_label: string;
    candidate_answer: string;
  },
): Promise<Run> {
  return apiCall<Run>(`/api/projects/${projectId}/checks`, {
    method: "POST",
    body: JSON.stringify({
      question: req.question ?? null,
      model_or_prompt_label: req.model_or_prompt_label,
      candidate_answer: req.candidate_answer,
    }),
  });
}

export function getRun(runId: string): Promise<Run> {
  return apiCall<Run>(`/api/runs/${runId}`);
}

export function listRuns(projectId: string): Promise<Run[]> {
  return apiCall<Run[]>(`/api/projects/${projectId}/runs`);
}

// ---- Gate policy -------------------------------------------------------

export function getGatePolicy(projectId: string): Promise<GatePolicy> {
  return apiCall<GatePolicy>(`/api/projects/${projectId}/gate-policy`);
}

export function setGatePolicy(
  projectId: string,
  policy: GatePolicy,
): Promise<GatePolicy> {
  return apiCall<GatePolicy>(`/api/projects/${projectId}/gate-policy`, {
    method: "PUT",
    body: JSON.stringify(policy),
  });
}

// ---- Phase 7: Lethe memory ---------------------------------------------

export function getRunMemoryClaims(
  projectId: string,
  runId: string,
): Promise<MemoryClaim[]> {
  return apiCall<MemoryClaim[]>(
    `/api/projects/${projectId}/runs/${runId}/memory-claims`,
  );
}
