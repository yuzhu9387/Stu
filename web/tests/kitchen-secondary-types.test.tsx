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
