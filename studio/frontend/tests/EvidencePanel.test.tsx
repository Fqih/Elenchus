import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EvidencePanel } from "../src/components/EvidencePanel";

const verdict = {
  claim: { id: "c1", text: "1 to 2 days.", span: [0, 12] as [number, number] },
  label: "contradicted" as const,
  confidence: 0.95,
  tier: "nli" as const,
  evidence: {
    source_id: "d1",
    text: "3 to 5 business days.",
    span: [0, 22] as [number, number],
  },
  checked_at: "t",
};

describe("EvidencePanel", () => {
  it("renders the claim text and evidence excerpt", () => {
    render(<EvidencePanel verdict={verdict} onClose={() => {}} />);
    expect(screen.getByText("1 to 2 days.")).toBeInTheDocument();
    expect(screen.getByText("3 to 5 business days.")).toBeInTheDocument();
  });
  it("invokes onClose when close button clicked", () => {
    const handler = vi.fn();
    render(<EvidencePanel verdict={verdict} onClose={handler} />);
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(handler).toHaveBeenCalledOnce();
  });
  it("shows 'no evidence available' when evidence is null", () => {
    render(
      <EvidencePanel
        verdict={{ ...verdict, evidence: null }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/no evidence available/i)).toBeInTheDocument();
  });
});