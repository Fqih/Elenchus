export type VerdictLabel = "supported" | "contradicted" | "unverifiable";
export type GateResult = "allowed" | "flagged" | "blocked";
export type Tier = "nli" | "judge";

export interface Claim {
  id: string;
  text: string;
  span: [number, number];
}

export interface Evidence {
  source_id: string;
  text: string;
  span: [number, number];
}

export interface Verdict {
  claim: Claim;
  label: VerdictLabel;
  confidence: number;
  tier: Tier;
  evidence: Evidence | null;
  checked_at: string;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
}

export interface SourceDocument {
  id: string;
  project_id: string;
  name: string;
  content: string;
  content_sha256: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Run {
  id: string;
  project_id: string;
  question: string | null;
  model_or_prompt_label: string;
  candidate_answer: string;
  source_document_versions: Record<string, number>;
  verdicts: Verdict[];
  gate_result: GateResult;
  latency_ms: number;
  created_at: string;
  // Phase 7 — set when the project's gate policy has phase7_enabled=True.
  // For blocked runs: stop_reason + attempts (Soteria retry summary).
  // For allowed runs: memory_item_ids (Lethe MemoryItem ids). Empty when
  // phase7_enabled is off, or for flagged runs, or when soft-failed.
  phase7_retry_stop_reason: string | null;
  phase7_retry_attempts: number;
  phase7_memory_item_ids: string[];
}

export interface GatePolicy {
  block_on_any_contradiction: boolean;
  flag_if_unverifiable_count_exceeds: number;
  phase7_enabled: boolean;
}

export interface MemoryClaim {
  id: string;
  content: string;
  tags: string[];
  source_session_id: string;
  created_at: string;
  last_accessed_at: string;
  access_count: number;
  importance_score: number;
}
