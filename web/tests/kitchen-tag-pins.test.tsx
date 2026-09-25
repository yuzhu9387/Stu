import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { PrepPage } from "@/features/kitchen/prep";
import { RecipesPage } from "@/features/kitchen/recipes";
import { ShoppingPrepPage } from "@/features/kitchen/shopping-prep";
import type { KitchenState } from "@/features/kitchen/types";

let latest: KitchenState;
function Recipes({ initial }: { initial: KitchenState }) {
  const [state, setState] = useState(initial);
  return <RecipesPage state={state} plan={state.plans[0]} demo notify={() => {}} navigate={() => {}} send={async (type, payload) => { latest = applyDemoCommand(latest, { type, payload, expectedRevision: latest.revision, operationId: crypto.randomUUID() }).state; setState(latest); return true; }} />;
}
/** The filter chips in order, large (pinned) ones marked with "*", the divider as "|". */
const filterRow = () => [...screen.getByRole("group", { name: "Filter recipes" }).children].map(node => node.classList.contains("kw-filter-divider") ? "|" : `${node.textContent}${node.classList.contains("is-key") ? "*" : ""}`);

it("pins tags from the tag manager: pinned tags lead the list and the filters as large chips", async () => {
  const state = createDemoState();
  state.tags = ["Quick", "小孩饭", "Soup"];
  latest = state;
  render(<Recipes initial={state} />);
  expect(filterRow()).toEqual(["All ★*", "Breakfast 🌅*", "Lunch ☀️*", "Dinner 🌙*", "小孩饭 👶*", "|", "Quick", "Soup", "✎ Edit tags"]);

  fireEvent.click(screen.getByRole("button", { name: "✎ Edit tags" }));
  const popup = screen.getByRole("dialog", { name: "Recipe tags" });
  const names = () => within(popup).getAllByRole("listitem").map(row => row.querySelector(".kw-tag-name")!.textContent);
  // The meals are tags too: they can be pinned, not renamed or deleted.
  expect(names()).toEqual(["Breakfast 🌅", "Lunch ☀️", "Dinner 🌙", "小孩饭", "Quick", "Soup"]);
  expect(within(popup).queryByRole("button", { name: "Rename tag breakfast" })).not.toBeInTheDocument();
  // The pin is a small icon before Rename.
  const soup = within(popup).getByText("Soup", { selector: ".kw-tag-name" }).closest("li")!;
  const buttons = within(soup).getAllByRole("button");
  expect(buttons.map(b => b.getAttribute("aria-label"))).toEqual(["Pin tag Soup", "Rename tag Soup", "Delete tag Soup"]);
  expect(buttons[0].textContent).toBe("");

  fireEvent.click(within(popup).getByRole("button", { name: "Pin tag Soup" }));
  await waitFor(() => expect(names()).toEqual(["Breakfast 🌅", "Lunch ☀️", "Dinner 🌙", "小孩饭", "Soup", "Quick"]));
  expect(within(popup).getByRole("button", { name: "Unpin tag Soup" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(popup).getByRole("button", { name: "Unpin tag lunch" }));
  await waitFor(() => expect(names()).toEqual(["Breakfast 🌅", "Dinner 🌙", "小孩饭", "Soup", "Lunch ☀️", "Quick"]));
  expect(latest.settings.pinnedTags).toEqual(["breakfast", "dinner", "小孩饭", "Soup"]);

  // A renamed tag keeps its pin; a deleted one drops it.
  fireEvent.click(within(popup).getByRole("button", { name: "Rename tag Soup" }));
  fireEvent.change(within(popup).getByLabelText("New name for Soup"), { target: { value: "Soups" } });
  fireEvent.click(within(popup).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(latest.settings.pinnedTags).toEqual(["breakfast", "dinner", "小孩饭", "Soups"]));
  fireEvent.click(within(popup).getByRole("button", { name: "Delete tag 小孩饭" }));
  fireEvent.click(within(popup).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(latest.settings.pinnedTags).toEqual(["breakfast", "dinner", "Soups"]));

  fireEvent.click(within(popup).getByRole("button", { name: "Close tags" }));
  expect(filterRow()).toEqual(["All ★*", "Breakfast 🌅*", "Dinner 🌙*", "Soups*", "|", "Lunch ☀️", "Quick", "✎ Edit tags"]);
  // An unpinned meal still filters by meal.
  fireEvent.click(screen.getByRole("button", { name: "Lunch ☀️" }));
  expect(screen.getByRole("button", { name: "Lunch ☀️" })).toHaveAttribute("aria-pressed", "true");
});

it("opens the folded panel from a click on its blank space, but not from its controls", async () => {
  const state = createDemoState(), plan = state.plans[0];
  const onFocus = vi.fn(async () => {});
  const { container } = render(<ShoppingPrepPage state={state} plan={plan} focus="prep" onFocus={onFocus} demo navigate={vi.fn()} notify={vi.fn()} send={vi.fn().mockResolvedValue(true)} />);
  const shopping = container.querySelector(".kw-shopping-panel") as HTMLElement;
  const box = within(shopping).getAllByRole("checkbox")[0];
  fireEvent.click(box);
  await waitFor(() => expect(box).toBeEnabled());
  expect(onFocus).not.toHaveBeenCalled();
  fireEvent.click(shopping.querySelector(".kw-shopping-body")!);
  await waitFor(() => expect(onFocus).toHaveBeenCalledWith("shopping"));
  // The open panel does nothing on a blank click.
  await waitFor(() => expect(shopping).toHaveClass("is-expanded"));
  onFocus.mockClear();
  fireEvent.click(shopping.querySelector(".kw-shopping-body")!);
  expect(onFocus).not.toHaveBeenCalled();
});

it("labels the meals a prep dish is for with small tags that are not links", () => {
  const state = createDemoState(), plan = state.plans[0];
  const task = plan.prep.find(t => plan.meals.some(m => m.components.some(c => c.prepId === t.id)))!;
  const navigate = vi.fn();
  render(<PrepPage state={state} plan={plan} send={vi.fn()} demo notify={vi.fn()} navigate={navigate} />);
  fireEvent.click(screen.getAllByRole("button", { name: new RegExp(task.name) }).find(b => b.classList.contains("kw-dish-row"))!);
  const tags = document.querySelectorAll(".kw-prep-detail-links .kw-meal-date-tag");
  expect(tags.length).toBeGreaterThan(0);
  expect(document.querySelector(".kw-prep-detail-links .kw-linked-pill")).toBeNull();
  tags.forEach(tag => expect(tag.tagName).toBe("SPAN"));
});
