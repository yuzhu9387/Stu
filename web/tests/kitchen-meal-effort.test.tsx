import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { MealDrawer } from "@/features/kitchen/meal-drawer";

it("shows total effort as this meal's share of weekend prep plus time on the day", () => {
  const state = createDemoState();
  const plan = state.plans[0];
  // Wed dinner uses 3 of the 6 meatball portions from a 35-minute prep task,
  // so it carries half that prep: 18 min, plus its own 8 min on the day.
  const meal = plan.meals.find(m => m.id === "meal-2-dinner")!;
  const task = plan.prep.find(t => t.id === "prep-meatballs")!;
  expect(task.activeMinutes).toBe(35);
  expect(task.plannedPortions).toBe(6);
  render(<MealDrawer meal={meal} plan={plan} state={state} onClose={vi.fn()} onDirty={vi.fn()} onSave={vi.fn()} onAction={vi.fn()} onReference={vi.fn()} onRecipe={vi.fn()} busy={false} />);
  expect(screen.getByText("26 min")).toBeVisible();
  expect(screen.getByText("18 prep + 8 fresh")).toBeVisible();
});
