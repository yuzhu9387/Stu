import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { planMetrics, planWarnings } from "@/features/kitchen/analysis";
import { createDemoState } from "@/features/kitchen/data";
import { componentGroups } from "@/features/kitchen/food-groups";
import { FridgePage } from "@/features/kitchen/fridge";
import type { InventoryItem } from "@/features/kitchen/types";

const buns: InventoryItem = { id: "buns", name: "包子", type: "Carbs", portions: 6, location: "Freezer", prepared: true, addedOn: "2026-09-27", priority: false, secondaryTypes: ["Protein", "Vegetables"] };

it("marks a food with the other groups it contains, and saves a change to them", async () => {
  const state = createDemoState();
  state.inventory = [buns];
  const send = vi.fn().mockResolvedValue(true);
  render(<FridgePage state={state} plan={state.plans[0]} send={send} demo notify={vi.fn()} navigate={vi.fn()} />);
  const card = screen.getByRole("button", { name: /^包子, / });
  expect(within(card).getByLabelText("Also contains Protein, Vegetables")).toHaveTextContent("+");
  fireEvent.click(card);
  const dialog = screen.getByRole("dialog");
  const also = within(dialog).getByRole("group", { name: "Also contains" });
  // The main group is not offered again.
  expect(within(also).queryByRole("button", { name: /Carbs/ })).not.toBeInTheDocument();
  expect(within(also).getByRole("button", { name: /Protein/ })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(also).getByRole("button", { name: /Vegetables/ }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Save food" }));
  await waitFor(() => expect(send).toHaveBeenCalledWith("inventory.save", { item: expect.objectContaining({ id: "buns", secondaryTypes: ["Protein"] }) }));
});

it("counts what a dish also contains when checking a meal's food groups", () => {
  const state = createDemoState(), plan = state.plans[0];
  state.inventory = [...state.inventory, buns];
  const meal = plan.meals.find(m => m.slot === "lunch" && m.status === "planned")!;
  meal.components = [{ id: "c-buns", name: "包子", type: "Carbs", portions: 1, inventoryId: "buns" }];
  expect(componentGroups(meal.components[0], state)).toEqual(["Carbs", "Protein", "Vegetables"]);
  const without = planWarnings(state, plan).find(w => w.id === "meals-without-vegetables");
  expect(without?.detail ?? "").not.toContain(meal.day);
  const balance = planMetrics(state, plan).find(m => m.id === "nutrition_balance")!;
  const meals = plan.meals.filter(m => m.included !== false && m.status !== "skipped");
  const withProtein = meals.filter(m => m.components.some(c => componentGroups(c, state).includes("Protein"))).length;
  expect(balance.value).toContain(`protein ${withProtein}`);
});

it("lets a dish in a meal name its own other groups, over its food's", async () => {
  const { MealDrawer } = await import("@/features/kitchen/meal-drawer");
  const state = createDemoState(), plan = state.plans[0];
  state.inventory = [...state.inventory, buns];
  const meal = { ...plan.meals.find(m => m.id === "meal-1-lunch")!, components: [{ id: "c-buns", name: "包子", type: "Carbs" as const, portions: 1, inventoryId: "buns" }] };
  const onSave = vi.fn().mockResolvedValue(true);
  render(<MealDrawer state={state} plan={plan} meal={meal} initialEdit onClose={vi.fn()} onDirty={vi.fn()} onSave={onSave} onAction={vi.fn()} onReference={vi.fn()} onRecipe={vi.fn()} busy={false} />);
  const also = screen.getByRole("group", { name: "Also contains, 包子" });
  // Until changed here, the dish shows what its fridge food says.
  expect(within(also).getByRole("button", { name: /Protein/ })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(also).getByRole("button", { name: /Vegetables/ }));
  fireEvent.click(within(also).getByRole("button", { name: /Dairy/ }));
  fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
  await waitFor(() => expect(onSave).toHaveBeenCalled());
  const dish = onSave.mock.calls[0][0].components[0];
  expect(dish.secondaryTypes).toEqual(["Protein", "Dairy"]);
  expect(componentGroups(dish, state)).toEqual(["Carbs", "Protein", "Dairy"]);
  expect(componentGroups({ ...dish, secondaryTypes: [] }, state)).toEqual(["Carbs"]);
});
