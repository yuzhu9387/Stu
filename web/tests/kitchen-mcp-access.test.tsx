import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { McpAccess } from "@/features/kitchen/mcp-access";

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

it("makes an access token, shows it once with the connect command, and revokes it", async () => {
  const token = "stu_secret-value";
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input);
    calls.push(`${init?.method ?? "GET"} ${url.pathname}`);
    if (url.pathname === "/api/v1/auth/mcp-tokens" && (init?.method ?? "GET") === "GET") return json({ tokens: [] });
    if (url.pathname === "/api/v1/auth/mcp-tokens") return json({ id: "t1", name: "Claude", createdAt: "2026-09-25T20:00:00Z", lastUsedAt: null, token }, 201);
    if (url.pathname === "/api/v1/auth/mcp-tokens/t1") return new Response(null, { status: 204 });
    return json({ detail: "Not Found" }, 404);
  }));
  const user = userEvent.setup();
  render(<McpAccess demo={false} />);
  expect(await screen.findByText("No access tokens yet.")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "+ New access token" }));
  const fresh = await screen.findByRole("status");
  expect(within(fresh).getByText(token)).toBeVisible();
  expect(fresh).toHaveTextContent(`claude mcp add --transport http stu`);
  expect(fresh).toHaveTextContent(`/api/v1/kitchen/mcp --header "Authorization: Bearer ${token}"`);
  // Once dismissed, the token is gone from the page for good.
  await user.click(within(fresh).getByRole("button", { name: "Done" }));
  expect(screen.queryByText(token)).not.toBeInTheDocument();
  expect(screen.getByText("Claude")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Revoke Claude" }));
  await user.click(screen.getByRole("button", { name: "Revoke" }));
  await waitFor(() => expect(screen.getByText("No access tokens yet.")).toBeVisible());
  expect(calls).toContain("DELETE /api/v1/auth/mcp-tokens/t1");
});

it("has no tokens in the demo", () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  render(<McpAccess demo />);
  expect(screen.getByText("Access tokens are for your own account; the demo has none.")).toBeVisible();
  expect(fetchMock).not.toHaveBeenCalled();
});
