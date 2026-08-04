import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { Login } from "@/features/auth/login";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

it("consumes the local development magic link without exposing its token", async () => {
  const identity = {
    account_id: "10000000-0000-0000-0000-000000000001",
    household_id: "20000000-0000-0000-0000-000000000002",
    email: "cook@example.com",
    role: "owner",
  };
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(json({ status: "accepted", development_token: "private-dev-token" }, 202))
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(json(identity));
  vi.stubGlobal("fetch", fetchMock);
  const authenticated = vi.fn();
  const user = userEvent.setup();

  render(<Login locale="en-US" onAuthenticated={authenticated} />);
  await user.type(screen.getByLabelText("Email"), identity.email);
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByText("Every family member keeps a separate account.")).toBeVisible();
  expect(authenticated).toHaveBeenCalledWith(identity);
  expect(screen.queryByText("private-dev-token")).not.toBeInTheDocument();
});
