import { afterEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

it.each(["127.0.0.1", "localhost"])("keeps local API cookies on the browser's %s hostname", async hostname => {
  vi.stubGlobal("window", { location: { hostname } });
  const fetcher = vi.fn(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  await api("/api/v1/kitchen");
  expect(fetcher.mock.calls[0]).toEqual([`http://${hostname}:8000/api/v1/kitchen`, expect.objectContaining({ credentials: "include" })]);
});
