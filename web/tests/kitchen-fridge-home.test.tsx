import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { KitchenWorkspace } from "@/features/kitchen/workspace";
import { createDemoState } from "@/features/kitchen/data";

const nav = vi.hoisted(() => ({ query: "", listeners: new Set<() => void>() }));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(listener => { nav.listeners.add(listener); return () => { nav.listeners.delete(listener); }; }, () => nav.query)),
    useRouter: () => ({ push: (url: string) => { nav.query = url.split("?")[1] || ""; nav.listeners.forEach(listener => listener()); } }),
  };
});
beforeEach(() => { nav.query = "week=2026-09-21&page=fridge"; localStorage.clear(); });

const kitchen = () => screen.getByRole("navigation", { name: "Kitchen" });
const way = (name: RegExp) => within(kitchen()).getByRole("button", { name });

it("puts the kitchen on a rail at the left: 冰箱, Plan and Calendar, then the Recipe Book above the profile, with no header", async () => {
  const { container } = render(<KitchenWorkspace demo initialPage="fridge" />);
  expect(await screen.findByRole("heading", { name: "Fridge" })).toBeInTheDocument();
  const state = createDemoState();
  expect(within(kitchen()).getAllByRole("button").map(button => button.textContent)).toEqual([
    `冰箱${state.inventory.length} items`, expect.stringMatching(/^Plan/), expect.stringMatching(/^Calendar/), `Recipe Book${state.recipes.length} recipes`,
  ]);
  expect(way(/^冰箱/)).toHaveAttribute("aria-current", "page");
  // The profile sits at the bottom, under the Recipe Book.
  const profile = screen.getByRole("button", { name: "Settings and knowledge" });
  expect(way(/^Recipe Book/).compareDocumentPosition(profile) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(container.querySelector(".kw-navigation")).toBeNull();
  expect(screen.queryByText(/\bpts\b/)).not.toBeInTheDocument();
  // No doors beside the fridge, and no way "back" to it: the rail is the way.
  expect(container.querySelector(".kw-fridge-doors")).toBeNull();
  expect(screen.queryByRole("button", { name: "← 冰箱" })).not.toBeInTheDocument();
});

it("tells what is waiting behind Plan and Calendar", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-23T09:00:00"));
  try {
    render(<KitchenWorkspace demo initialPage="fridge" />);
    await screen.findByRole("heading", { name: "Fridge" });
    const today = createDemoState().plans[0].meals.filter(meal => meal.day === "2026-09-23" && meal.status !== "skipped").length;
    expect(way(/^Calendar/)).toHaveTextContent(`Today · ${today} meals`);
    // This week is confirmed; next week is still to plan.
    expect(way(/^Plan/)).toHaveTextContent("Plan next week");
  } finally { vi.useRealTimers(); }
});

it("goes to the calendar from the rail; from there, back to Plan or on to Shopping & prep", async () => {
  render(<KitchenWorkspace demo initialPage="fridge" />);
  await screen.findByRole("heading", { name: "Fridge" });
  fireEvent.click(way(/^Calendar/));
  expect(await screen.findByRole("region", { name: "Weekly meal calendar" })).toBeInTheDocument();
  expect(new URLSearchParams(nav.query).get("page")).toBe("calendar");
  expect(way(/^Calendar/)).toHaveAttribute("aria-current", "page");
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

it("opens Plan, the fridge and the Recipe Book from the rail on every page", async () => {
  render(<KitchenWorkspace demo initialPage="fridge" />);
  await screen.findByRole("heading", { name: "Fridge" });
  fireEvent.click(way(/^Plan/));
  expect(new URLSearchParams(nav.query).get("page")).toBe("plan");
  expect(screen.queryByRole("button", { name: "← 冰箱" })).not.toBeInTheDocument();
  fireEvent.click(way(/^冰箱/));
  expect(new URLSearchParams(nav.query).get("page")).toBe("fridge");
  fireEvent.click(way(/^Recipe Book/));
  expect(new URLSearchParams(nav.query).get("page")).toBe("recipes");
});
