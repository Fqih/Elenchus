import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useProjects, useCreateProject } from "../src/hooks/useStudioApi";

const originalFetch = global.fetch;

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  global.fetch = jest_fetch_ok({ id: "p1", name: "kb", created_at: "t" });
});

afterEach(() => {
  global.fetch = originalFetch;
});

function jest_fetch_ok(body: any) {
  return ((_url: any, _init: any) =>
    Promise.resolve(
      new Response(typeof body === "string" ? body : JSON.stringify(body), {
        status: 200,
      }),
    )) as unknown as typeof fetch;
}

describe("useProjects", () => {
  it("fetches /api/projects and returns the JSON", async () => {
    global.fetch = jest_fetch_ok([{ id: "p1", name: "kb", created_at: "t" }]);
    const { result } = renderHook(() => useProjects(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([{ id: "p1", name: "kb", created_at: "t" }]);
  });
});

describe("useCreateProject", () => {
  it("POSTs the name and returns the new project", async () => {
    let captured: any = null;
    global.fetch = (async (_url: any, init: any) => {
      captured = init;
      return new Response(
        JSON.stringify({ id: "p2", name: "new", created_at: "t" }),
        { status: 200 },
      );
    }) as unknown as typeof fetch;
    const { result } = renderHook(() => useCreateProject(), { wrapper: wrapper() });
    await result.current.mutateAsync({ name: "new" });
    expect(captured.method).toBe("POST");
    expect(captured.body).toBe(JSON.stringify({ name: "new" }));
  });
});