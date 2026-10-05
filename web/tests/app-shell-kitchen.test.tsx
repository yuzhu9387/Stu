import { render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AppShell } from "@/components/app-shell";
import { KitchenWorkspace } from "@/features/kitchen/workspace";
import { LocaleProvider } from "@/i18n/locale-context";

const navigation = vi.hoisted(() => ({ pathname: "/knowledge" }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/lib/use-feature-data", () => ({ useFeatureData: () => ({ status: "ready", data: { members: [], lark_binding: { is_linked: false } } }) }));
beforeEach(() => { navigation.pathname = "/knowledge"; });

it("renders the knowledge route with the kitchen rail and no legacy shell", async () => {
  render(<LocaleProvider initialLocale="en-US"><AppShell><KitchenWorkspace initialPage="knowledge" demo /></AppShell></LocaleProvider>);
  await screen.findByRole("heading", { name: "Your reference library" });
  // The rail at the left is the only navigation; the fridge is on it.
  expect(screen.getAllByRole("navigation").map(nav => nav.getAttribute("aria-label"))).toEqual(["Kitchen"]);
  expect(within(screen.getByRole("navigation", { name: "Kitchen" })).getByRole("button", { name: /^冰箱/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: "← 冰箱" })).not.toBeInTheDocument();
  expect(screen.queryByText("Family Table")).not.toBeInTheDocument();
});

it("preserves the legacy settings shell", () => {
  navigation.pathname = "/settings";
  render(<LocaleProvider initialLocale="en-US"><AppShell><p>Legacy settings content</p></AppShell></LocaleProvider>);
  expect(screen.getByText("Family Table")).toBeVisible();
  expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  expect(screen.getByText("Legacy settings content")).toBeVisible();
});
