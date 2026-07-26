export type VerdictLabel = "entailed" | "contradicted" | "unverifiable";
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
}

export interface GatePolicy {
  block_on_any_contradiction: boolean;
  flag_if_unverifiable_count_exceeds: number;
}
