import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RunResult } from "../src/components/RunResult";
import type { Run } from "../src/types";

void vi;

const run: Run = {
  id: "r1",
  project_id: "p1",
  question: "How long does shipping take?",
  model_or_prompt_label: "gpt-4",
  candidate_answer: "Shipping takes 1 to 2 days. Returns within 30 days.",
  source_document_versions: { d1: 1 },
  verdicts: [
    {
      claim: {
        id: "c1",
        text: "Shipping takes 1 to 2 days.",
        span: [0, 27],
      },
      label: "contradicted",
      confidence: 0.99,
      tier: "nli",
      evidence: {
        source_id: "d1",
        text: "3 to 5 business days.",
        span: [0, 22],
      },
      checked_at: "t",
    },
    {
      claim: {
        id: "c2",
        text: "Returns within 30 days.",
        span: [28, 50],
      },
      label: "entailed",
      confidence: 0.95,
      tier: "nli",
      evidence: null,
      checked_at: "t",
    },
  ],
  gate_result: "blocked",
  latency_ms: 642,
  created_at: "t",
};

describe("RunResult", () => {
  it("renders the gate badge with the right result", () => {
    render(<RunResult run={run} onClaimClick={() => {}} />);
    expect(screen.getByText("blocked")).toBeInTheDocument();
  });
  it("renders latency_ms formatted as ms", () => {
    render(<RunResult run={run} onClaimClick={() => {}} />);
    expect(screen.getByText(/642\s*ms/)).toBeInTheDocument();
  });
  it("renders both claim texts with the right verdict classes", () => {
    render(<RunResult run={run} onClaimClick={() => {}} />);
    expect(screen.getByText("Shipping takes 1 to 2 days.")).toHaveClass("claim-contradicted");
    expect(screen.getByText("Returns within 30 days.")).toHaveClass("claim-entailed");
  });
});