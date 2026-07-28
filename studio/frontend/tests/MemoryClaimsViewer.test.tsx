import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryClaimsViewer } from "../src/components/MemoryClaimsViewer";
import type { MemoryClaim } from "../src/types";

const fixture: MemoryClaim[] = [
  {
    id: "mem-1",
    content: "Items can be returned within 30 days.",
    tags: [
      "elenchus_verified",
      "run:r-abc",
      "project:p1",
      "source:kb",
      "v1",
    ],
    source_session_id: "p1",
    created_at: "2026-07-27T07:00:00Z",
    last_accessed_at: "2026-07-27T07:00:00Z",
    access_count: 0,
    importance_score: 0.81,
  },
];

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("MemoryClaimsViewer", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns null when expectedCount is 0", () => {
    const { container } = render(
      withQuery(
        <MemoryClaimsViewer projectId="p1" runId="r1" expectedCount={0} />,
      ),
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a toggle button when expectedCount > 0", () => {
    render(
      withQuery(
        <MemoryClaimsViewer projectId="p1" runId="r1" expectedCount={3} />,
      ),
    );
    expect(
      screen.getByText(/Lethe memory \(3 items\)/),
    ).toBeInTheDocument();
  });

  it("uses singular grammar for one item", () => {
    render(
      withQuery(
        <MemoryClaimsViewer projectId="p1" runId="r1" expectedCount={1} />,
      ),
    );
    expect(
      screen.getByText(/Lethe memory \(1 item\)/),
    ).toBeInTheDocument();
  });

  it("fetches + displays claims on toggle (lazy fetch)", async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => fixture,
    } as unknown as Response);

    const user = userEvent.setup();
    render(
      withQuery(
        <MemoryClaimsViewer projectId="p1" runId="r-abc" expectedCount={1} />,
      ),
    );

    // Not fetched yet — closed toggle.
    expect(global.fetch).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/projects/p1/runs/r-abc/memory-claims",
        expect.any(Object),
      );
    });
    expect(
      screen.getByText("Items can be returned within 30 days."),
    ).toBeInTheDocument();
    expect(screen.getByText("source:kb")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.getByText("elenchus_verified")).toBeInTheDocument();
    expect(screen.getByText(/importance/)).toBeInTheDocument();
  });

  it("shows empty state when backend returns []", async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => [],
    } as unknown as Response);
    const user = userEvent.setup();
    render(
      withQuery(
        <MemoryClaimsViewer projectId="p1" runId="r-x" expectedCount={2} />,
      ),
    );
    await user.click(screen.getByRole("button"));
    expect(
      await screen.findByText(/No memory items found/),
    ).toBeInTheDocument();
  });

  it("renders error when fetch fails", async () => {
    global.fetch = vi.fn().mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(
      withQuery(
        <MemoryClaimsViewer projectId="p1" runId="r-x" expectedCount={1} />,
      ),
    );
    await user.click(screen.getByRole("button"));
    expect(
      await screen.findByText(/Failed to load memory/),
    ).toBeInTheDocument();
  });
});
