import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { LiveFeatureScreen } from "@/features/records/live-feature-screen";
import { AccountFamilySettings } from "@/features/settings/account-family-settings";
import { LocaleProvider } from "@/i18n/locale-context";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

it("shows separate owner labels for family recipes", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ recipes: [
    { id: "1", owner_display_name: "alice", is_owned_by_current_account: true, name: "Tomato soup", visibility: "family", created_at: "2026-07-16T00:00:00Z" },
    { id: "2", owner_display_name: "bob", is_owned_by_current_account: false, name: "Noodles", visibility: "family", created_at: "2026-07-15T00:00:00Z" },
  ] })));

  render(<LocaleProvider initialLocale="en-US"><LiveFeatureScreen page="recipes" /></LocaleProvider>);

  expect(await screen.findByText("Tomato soup")).toBeVisible();
  expect(screen.getByText(/Owner: Me/)).toBeVisible();
  expect(screen.getByText(/Owner: bob/)).toBeVisible();
  expect(screen.getAllByRole("article")).toHaveLength(2);
});

it("creates a family invite and Lark link code from live settings", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(json({ preferences: [], members: [], lark_binding: { is_linked: false } }))
    .mockResolvedValueOnce(json({ code: "FAMILY42", expires_at: "2026-07-16T01:00:00Z" }, 201))
    .mockResolvedValueOnce(json({ code: "LARK42" }, 201));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();

  render(<LocaleProvider initialLocale="en-US"><AccountFamilySettings /></LocaleProvider>);
  await user.click(await screen.findByRole("button", { name: "Create family invite" }));
  expect(await screen.findByText(/FAMILY42/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Link Lark" }));
  expect(await screen.findByText(/link LARK42/)).toBeVisible();
});
