import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GateBadge } from "../src/components/GateBadge";

describe("GateBadge", () => {
  it("applies gate-blocked class for blocked", () => {
    render(<GateBadge result="blocked" />);
    expect(screen.getByText("blocked")).toHaveClass("gate-blocked");
  });
  it("applies gate-flagged class for flagged", () => {
    render(<GateBadge result="flagged" />);
    expect(screen.getByText("flagged")).toHaveClass("gate-flagged");
  });
  it("applies gate-allowed class for allowed", () => {
    render(<GateBadge result="allowed" />);
    expect(screen.getByText("allowed")).toHaveClass("gate-allowed");
  });
});