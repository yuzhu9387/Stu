import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { MealDrawer } from "@/features/kitchen/meal-drawer";
import type { Meal } from "@/features/kitchen/types";

it("edits an invented dish before saving its recipe and linking the meal", async () => {
  const state = createDemoState(), plan = state.plans[0], meal = plan.meals[0];
  plan.status = "draft";
  meal.components = [{ id: "salad", name: "Simple salad", type: "Vegetables", portions: 3 }];
  const save = vi.fn(async () => true);
  render(<MealDrawer state={state} plan={plan} meal={meal} onClose={vi.fn()} onDirty={vi.fn()} onSave={save} onAction={vi.fn(async () => true)} onRecipe={vi.fn()} busy={false} />);
  fireEvent.click(screen.getByRole("button", { name: /Save to recipe/ }));
  fireEvent.change(screen.getByLabelText("Recipe name"), { target: { value: "Cucumber salad" } });
  fireEvent.change(screen.getByLabelText("Ingredient"), { target: { value: "Cucumber" } });
  fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "300" } });
  fireEvent.change(screen.getByLabelText("Steps (one per line)"), { target: { value: "Wash and slice the cucumber." } });
  fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith(
    expect.objectContaining({ components: [expect.objectContaining({ name: "Cucumber salad", recipeId: expect.any(String) })] }),
    meal,
    [expect.objectContaining({ name: "Cucumber salad", ingredients: [expect.objectContaining({ name: "Cucumber", quantity: 300 })] })],
  ));
  const link=await screen.findByRole("link",{name:/View full recipe/});
  expect(link).toHaveAttribute("target","_blank");
  expect(link).toHaveClass("is-recipe-saved");
});

it("uses the authoritative timing when adding a second dish's recipe", async () => {
  const state = createDemoState(), plan = state.plans[0], meal = plan.meals[0];
  plan.status = "draft";
  meal.components = [{ id: "a", name: "Salad A", type: "Vegetables", portions: 3 }, { id: "b", name: "Salad B", type: "Vegetables", portions: 3 }];
  const save = vi.fn<(meal: Meal, original: Meal) => Promise<boolean>>().mockResolvedValue(true);
  const props = { state, plan, meal, onClose: vi.fn(), onDirty: vi.fn(), onSave: save, onAction: vi.fn(async () => true), onRecipe: vi.fn(), busy: false };
  const view = render(<MealDrawer {...props} />);
  const fill = () => {
    fireEvent.change(screen.getByLabelText("Ingredient"), { target: { value: "Cucumber" } });
    fireEvent.change(screen.getByLabelText("Steps (one per line)"), { target: { value: "Wash and slice." } });
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
  };
  fireEvent.click(screen.getByRole("button", { name: "Edit and add recipe for Salad A" }));
  fill();
  await screen.findByRole("button", { name: "Edit and add recipe for Salad B" });
  const authoritative = { ...save.mock.calls[0][0], activeMinutes: 30, elapsedMinutes: 40 };
  view.rerender(<MealDrawer {...props} meal={authoritative} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit and add recipe for Salad B" }));
  fill();
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save.mock.calls[1][1]).toEqual(authoritative);
  expect(save.mock.calls[1][0].components[0].recipeId).toBe(authoritative.components[0].recipeId);
});
