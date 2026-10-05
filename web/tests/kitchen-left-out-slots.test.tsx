import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { FridgePage } from "@/features/kitchen/fridge";

beforeEach(() => localStorage.clear());

/** The demo week with one food that only one meal uses, more than the fridge has. */
function hungry(included: boolean) {
  const state = createDemoState(), plan = state.plans[0];
  const meal = plan.meals.find(m => m.status === "planned" && m.components.some(c => c.inventoryId))!;
  const component = meal.components.find(c => c.inventoryId)!;
  const item = state.inventory.find(i => i.id === component.inventoryId)!;
  plan.meals.forEach(m => m.components.forEach(c => { if (c.inventoryId === item.id && c !== component) delete c.inventoryId; }));
  plan.prep.forEach(t => { t.inputs = t.inputs.filter(i => i.inventoryId !== item.id); });
  component.portions = item.portions + 5;
  meal.included = included;
  render(<FridgePage state={state} plan={plan} send={vi.fn().mockResolvedValue(true)} demo notify={vi.fn()} navigate={vi.fn()} />);
  return { item };
}

it("a meal still planned holds its food: it is short, and linked from the food", () => {
  const { item } = hungry(true);
  expect(screen.getByText(/short ⚠️/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${item.name}, `) }));
  expect(screen.queryByText("Not used by this week’s meals yet.")).not.toBeInTheDocument();
});

it("a slot left out in step 1 holds nothing in the fridge", () => {
  const { item } = hungry(false);
  expect(screen.queryByText(/short ⚠️/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${item.name}, `) }));
  expect(screen.getByText("Not used by this week’s meals yet.")).toBeInTheDocument();
});
