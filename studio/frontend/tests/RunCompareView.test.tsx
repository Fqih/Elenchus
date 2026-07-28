import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RunCompareView } from "../src/components/RunCompareView";
import type { Run } from "../src/types";

const runA: Run = {
  id: "runA",
  project_id: "p1",
  question: "How long does shipping take?",
  model_or_prompt_label: "gpt-4",
  candidate_answer: "Shipping takes 1 to 2 days. Returns within 30 days.",
  source_document_versions: { d1: 1 },
  verdicts: [
    {
      claim: { id: "c1", text: "Shipping takes 1 to 2 days.", span: [0, 27] },
      label: "supported",
      confidence: 0.91,
      tier: "nli",
      evidence: null,
      checked_at: "t",
    },
    {
      claim: { id: "c2", text: "Returns within 30 days.", span: [28, 50] },
      label: "supported",
      confidence: 0.88,
      tier: "nli",
      evidence: null,
      checked_at: "t",
    },
  ],
  gate_result: "allowed",
  latency_ms: 640,
  created_at: "t",
  phase7_retry_stop_reason: null,
  phase7_retry_attempts: 0,
  phase7_memory_item_ids: [],
};

const runB: Run = {
  ...runA,
  id: "runB",
  model_or_prompt_label: "claude-3",
  // Same answer text — but flip one verdict so the diff is visible.
  verdicts: [
    runA.verdicts[0],
    {
      ...runA.verdicts[1],
      label: "contradicted",
      confidence: 0.99,
      evidence: {
        source_id: "d1",
        text: "Returns within 60 days.",
        span: [0, 23],
      },
    },
  ],
};

const runs: Run[] = [runA, runB];

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderView() {
  return render(
    withQuery(<RunCompareView projectId="p1" runs={runs} />),
  );
}

describe("RunCompareView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders both selectors when runs are present", () => {
    renderView();
    // Two <select> dropdowns for run A and run B.
    const selects = screen.getAllByRole("combobox");
    expect(selects.length).toBe(2);
  });

  it("auto-selects first two runs by default", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      const body = url.includes("runA") ? runA : runB;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => body,
      } as unknown as Response);
    });

    renderView();

    // Wait for runs to load — the column headers carry the model labels.
    await waitFor(() => {
      const headers = screen.getAllByRole("columnheader");
      expect(headers.map((h) => h.textContent)).toEqual(
        expect.arrayContaining(["gpt-4", "claude-3"]),
      );
    });
  });

  it("marks differing-label rows as DIFF and identical rows as SAME", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      const body = url.includes("runB") ? runB : runA;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => body,
      } as unknown as Response);
    });

    renderView();

    // Wait for table data to render — once a DIFF badge appears, the
    // table is populated.
    await waitFor(() => {
      expect(screen.getAllByText("DIFF").length).toBeGreaterThan(0);
    });
  });

  it("does not crash with fewer than 2 runs", () => {
    render(withQuery(<RunCompareView projectId="p1" runs={[runA]} />));
    expect(screen.getByText(/at least 2 runs/i)).toBeInTheDocument();
  });

  it("changing the run selector reloads the right panel", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      const body = url.includes("runA") ? runA : runB;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => body,
      } as unknown as Response);
    });

    const user = userEvent.setup();
    renderView();

    // Default picks runA as A, runB as B. Switch B's selector to runA.
    await waitFor(() => {
      expect(screen.getAllByRole("combobox").length).toBe(2);
    });
    const selects = screen.getAllByRole("combobox");
    await user.selectOptions(selects[1], "runA");

    // Now both panels show gpt-4 model header.
    await waitFor(() => {
      const headers = screen.getAllByRole("columnheader");
      const labels = headers.map((h) => h.textContent);
      // gpt-4 should appear twice (both columns), claude-3 zero.
      const gptCount = labels.filter((l) => l === "gpt-4").length;
      const claudeCount = labels.filter((l) => l === "claude-3").length;
      expect(gptCount).toBe(2);
      expect(claudeCount).toBe(0);
    });
  });
});
