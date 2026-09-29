import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { KitchenWorkspace } from "@/features/kitchen/workspace";

const nav = vi.hoisted(() => ({ query: "", listeners: new Set<() => void>() }));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(listener => { nav.listeners.add(listener); return () => { nav.listeners.delete(listener); }; }, () => nav.query)),
    useRouter: () => ({ push: (url: string) => { nav.query = url.split("?")[1] || ""; nav.listeners.forEach(listener => listener()); } }),
  };
});
beforeEach(() => { nav.query = "week=2026-09-21&page=fridge"; localStorage.clear(); });

it("opens on the fridge, with Recipes, Calendar and Plan beside it and no top navigation", async () => {
  render(<KitchenWorkspace demo initialPage="fridge" />);
  expect(await screen.findByRole("heading", { name: "Fridge" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "Main navigation" })).not.toBeInTheDocument();
  const doors = screen.getByRole("navigation", { name: "Kitchen" });
  expect(within(doors).getAllByRole("button").map(button => button.textContent)).toEqual(["📖Recipes", "📅Calendar", "📋Plan"]);
  // The fridge is home: no way "back" from it.
  expect(screen.queryByRole("button", { name: "← 冰箱" })).not.toBeInTheDocument();
});

it("goes to the calendar from beside the fridge; from there, back to Plan or on to Shopping & prep", async () => {
  render(<KitchenWorkspace demo initialPage="fridge" />);
  fireEvent.click(within(await screen.findByRole("navigation", { name: "Kitchen" })).getByRole("button", { name: /Calendar/ }));
  expect(await screen.findByRole("region", { name: "Weekly meal calendar" })).toBeInTheDocument();
  expect(new URLSearchParams(nav.query).get("page")).toBe("calendar");
  // The calendar sits between the plan and the shopping: its buttons go there.
  expect(screen.queryByRole("button", { name: "← 冰箱" })).not.toBeInTheDocument();
  const onward = screen.getByRole("button", { name: "Shopping & prep →" });
  expect(onward).toHaveClass("kw-page-button");
  fireEvent.click(screen.getByRole("button", { name: "← Plan" }));
  expect(new URLSearchParams(nav.query).get("page")).toBe("plan");
  // The plan's way to the calendar is the same kind of button.
  const calendar = await screen.findByRole("button", { name: "View calendar" });
  expect(calendar).toHaveClass("kw-page-button");
  fireEvent.click(calendar);
  fireEvent.click(await screen.findByRole("button", { name: "Shopping & prep →" }));
  expect(new URLSearchParams(nav.query).get("page")).toBe("plan");
  expect(new URLSearchParams(nav.query).get("step")).toBe("shopping");
});

it("opens Plan and Recipes from beside the fridge too", async () => {
  render(<KitchenWorkspace demo initialPage="fridge" />);
  fireEvent.click(within(await screen.findByRole("navigation", { name: "Kitchen" })).getByRole("button", { name: /Plan/ }));
  expect(new URLSearchParams(nav.query).get("page")).toBe("plan");
  fireEvent.click(screen.getByRole("button", { name: "← 冰箱" }));
  fireEvent.click(within(await screen.findByRole("navigation", { name: "Kitchen" })).getByRole("button", { name: /Recipes/ }));
  expect(new URLSearchParams(nav.query).get("page")).toBe("recipes");
});
