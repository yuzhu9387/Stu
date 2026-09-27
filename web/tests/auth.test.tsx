import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { Login } from "@/features/auth/login";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

const identity = {
  account_id: "10000000-0000-0000-0000-000000000001",
  household_id: "20000000-0000-0000-0000-000000000002",
  email: "cook@example.com",
  role: "owner",
};

/** A fake server: answers by path, and remembers what was asked. */
function server(routes: Record<string, () => Response>) {
  const calls: { path: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: string, init?: RequestInit) => {
    const path = new URL(input).pathname;
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const route = routes[path];
    return route ? route() : json({ detail: "Not Found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

it("signs in with an email and a password", async () => {
  const calls = server({
    "/api/v1/auth/methods": () => json({ password: true, developmentLink: false }),
    "/api/v1/auth/sign-in": () => new Response(null, { status: 204 }),
    "/api/v1/auth/session": () => json(identity),
  });
  const authenticated = vi.fn();
  const user = userEvent.setup();
  render(<Login locale="en-US" onAuthenticated={authenticated} />);
  await user.type(screen.getByLabelText("Email"), identity.email);
  await user.type(screen.getByLabelText("Password"), "correct horse");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(authenticated).toHaveBeenCalledWith(identity));
  expect(calls.find(c => c.path === "/api/v1/auth/sign-in")?.body).toEqual({ email: identity.email, password: "correct horse" });
  // Production offers no passwordless shortcut.
  expect(screen.queryByRole("button", { name: /without a password/ })).not.toBeInTheDocument();
});

it("says so when the password is wrong", async () => {
  server({
    "/api/v1/auth/methods": () => json({ password: true, developmentLink: false }),
    "/api/v1/auth/sign-in": () => json({ detail: "Email or password is incorrect." }, 401),
  });
  const user = userEvent.setup();
  render(<Login locale="en-US" onAuthenticated={vi.fn()} />);
  await user.type(screen.getByLabelText("Email"), identity.email);
  await user.type(screen.getByLabelText("Password"), "wrong horse");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
});

it("creates an account after checking the two passwords match", async () => {
  const calls = server({
    "/api/v1/auth/methods": () => json({ password: true, developmentLink: false }),
    "/api/v1/auth/register": () => new Response(null, { status: 204 }),
    "/api/v1/auth/session": () => json(identity),
  });
  const authenticated = vi.fn();
  const user = userEvent.setup();
  render(<Login locale="en-US" onAuthenticated={authenticated} />);
  await user.click(screen.getByRole("button", { name: "Create an account" }));
  await user.type(screen.getByLabelText("Email"), identity.email);
  await user.type(screen.getByLabelText("Password"), "correct horse");
  await user.type(screen.getByLabelText("Confirm password"), "correct hose");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The passwords do not match.");
  expect(calls.some(c => c.path === "/api/v1/auth/register")).toBe(false);

  await user.clear(screen.getByLabelText("Confirm password"));
  await user.type(screen.getByLabelText("Confirm password"), "correct horse");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  await waitFor(() => expect(authenticated).toHaveBeenCalledWith(identity));
  expect(calls.find(c => c.path === "/api/v1/auth/register")?.body).toEqual({ email: identity.email, password: "correct horse" });
});

it("keeps the local passwordless shortcut without exposing its token", async () => {
  server({
    "/api/v1/auth/methods": () => json({ password: true, developmentLink: true }),
    "/api/v1/auth/magic-links": () => json({ status: "accepted", development_token: "private-dev-token" }, 202),
    "/api/v1/auth/sessions": () => new Response(null, { status: 204 }),
    "/api/v1/auth/session": () => json(identity),
  });
  const authenticated = vi.fn();
  const user = userEvent.setup();
  render(<Login locale="en-US" onAuthenticated={authenticated} />);
  await user.type(screen.getByLabelText("Email"), identity.email);
  await user.click(await screen.findByRole("button", { name: "Local development: continue without a password" }));
  await waitFor(() => expect(authenticated).toHaveBeenCalledWith(identity));
  expect(screen.queryByText("private-dev-token")).not.toBeInTheDocument();
});
