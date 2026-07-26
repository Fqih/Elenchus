import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import * as api from "../api";
import type { Project, Run, SourceDocument, GatePolicy } from "../types";

export function useProjects(): UseQueryResult<Project[], Error> {
  return useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
}

export function useProject(projectId: string): UseQueryResult<Project, Error> {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: !!projectId,
  });
}

export function useSourceDocuments(
  projectId: string,
): UseQueryResult<SourceDocument[], Error> {
  return useQuery({
    queryKey: ["source-docs", projectId],
    queryFn: () => api.listSourceDocuments(projectId),
    enabled: !!projectId,
  });
}

export function useSourceDocument(
  projectId: string,
  sourceId: string,
  version?: number,
): UseQueryResult<SourceDocument, Error> {
  return useQuery({
    queryKey: ["source-doc", projectId, sourceId, version ?? "latest"],
    queryFn: () => api.getSourceDocument(projectId, sourceId, version),
    enabled: !!projectId && !!sourceId,
  });
}

export function useRuns(projectId: string): UseQueryResult<Run[], Error> {
  return useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns(projectId),
    enabled: !!projectId,
  });
}

export function useRun(runId: string): UseQueryResult<Run, Error> {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
    enabled: !!runId,
  });
}

export function useGatePolicy(
  projectId: string,
): UseQueryResult<GatePolicy, Error> {
  return useQuery({
    queryKey: ["gate-policy", projectId],
    queryFn: () => api.getGatePolicy(projectId),
    enabled: !!projectId,
  });
}

// ---- Mutations --------------------------------------------------------

export function useCreateProject(): UseMutationResult<Project, Error, { name: string }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createProject,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useAddSourceDocument(
  projectId: string,
): UseMutationResult<SourceDocument, Error, { name: string; content: string }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req) => api.addSourceDocument(projectId, req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["source-docs", projectId] }),
  });
}

export function useUpdateSourceDocument(
  projectId: string,
  sourceId: string,
): UseMutationResult<SourceDocument, Error, { content: string }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req) => api.updateSourceDocument(projectId, sourceId, req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["source-docs", projectId] }),
  });
}

export function useSubmitCheck(
  projectId: string,
): UseMutationResult<Run, Error, { question?: string | null; model_or_prompt_label: string; candidate_answer: string }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req) => api.submitCheck(projectId, req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs", projectId] }),
  });
}

export function useSetGatePolicy(
  projectId: string,
): UseMutationResult<GatePolicy, Error, GatePolicy> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policy) => api.setGatePolicy(projectId, policy),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gate-policy", projectId] }),
  });
}