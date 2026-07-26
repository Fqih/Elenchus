import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ClaimSpan } from "../src/components/ClaimSpan";

const claim = {
  id: "c1",
  text: "Shipping takes 1 to 2 days.",
  span: [0, 30] as [number, number],
};

describe("ClaimSpan", () => {
  it("renders claim text with correct verdict class", () => {
    render(<ClaimSpan claim={claim} label="contradicted" onClick={() => {}} />);
    expect(screen.getByText("Shipping takes 1 to 2 days.")).toHaveClass("claim-contradicted");
  });
  it("invokes onClick when clicked", () => {
    const handler = vi.fn();
    render(<ClaimSpan claim={claim} label="contradicted" onClick={handler} />);
    fireEvent.click(screen.getByText("Shipping takes 1 to 2 days."));
    expect(handler).toHaveBeenCalledOnce();
  });
});