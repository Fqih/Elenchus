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
      label: "supported",
      confidence: 0.95,
      tier: "nli",
      evidence: null,
      checked_at: "t",
    },
  ],
  gate_result: "blocked",
  latency_ms: 642,
  created_at: "t",
  phase7_retry_stop_reason: null,
  phase7_retry_attempts: 0,
  phase7_memory_item_ids: [],
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
    expect(screen.getByText("Returns within 30 days.")).toHaveClass("claim-supported");
  });

  it("hides Phase 7 panel when nothing populated (default off / flagged)", () => {
    render(<RunResult run={run} onClaimClick={() => {}} />);
    expect(screen.queryByText("Phase 7")).not.toBeInTheDocument();
  });

  it("renders Phase 7 panel when Soteria retry populated state", () => {
    const retried = { ...run, phase7_retry_attempts: 3, phase7_retry_stop_reason: "repeated_action" };
    render(<RunResult run={retried} onClaimClick={() => {}} />);
    expect(screen.getByText("Phase 7")).toBeInTheDocument();
    expect(screen.getByText(/Soteria retry/)).toBeInTheDocument();
    expect(screen.getByText("3 attempts")).toBeInTheDocument();
    expect(screen.getByText("repeated_action")).toBeInTheDocument();
  });

  it("renders Phase 7 panel when Lethe memory populated state", () => {
    const remembered = {
      ...run,
      gate_result: "allowed" as const,
      phase7_memory_item_ids: ["mem-a", "mem-b", "mem-c"],
    };
    render(<RunResult run={remembered} onClaimClick={() => {}} />);
    expect(screen.getByText("Phase 7")).toBeInTheDocument();
    expect(screen.getByText(/Lethe memory/)).toBeInTheDocument();
    expect(screen.getByText("3 items stored")).toBeInTheDocument();
  });

  it("singular grammar for one stored item", () => {
    const remembered = {
      ...run,
      gate_result: "allowed" as const,
      phase7_memory_item_ids: ["only-one"],
    };
    render(<RunResult run={remembered} onClaimClick={() => {}} />);
    expect(screen.getByText("1 item stored")).toBeInTheDocument();
  });
});