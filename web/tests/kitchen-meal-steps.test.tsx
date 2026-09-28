import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { MealDrawer, replaceMealComponent } from "@/features/kitchen/meal-drawer";
import { removeComponent, stepGroups } from "@/features/kitchen/meal-steps";
import { useNumberFieldTidying } from "@/features/kitchen/number-fields";
import type { Meal } from "@/features/kitchen/types";

function twoDishMeal() {
  const state = createDemoState(), plan = state.plans[0];
  const meal: Meal = { ...structuredClone(plan.meals.find(m => m.id === "meal-2-dinner")!) };
  meal.components = [
    { id: "egg", name: "番茄炒蛋", type: "Protein", portions: 3 },
    { id: "greens", name: "蒜蓉菠菜", type: "Vegetables", portions: 3 },
  ];
  meal.steps = ["番茄炒蛋: 番茄切块，鸡蛋打散", "番茄炒蛋: 先炒蛋再炒番茄", "蒜蓉菠菜焯水后清炒", "盛盘上桌"];
  plan.meals = plan.meals.map(m => m.id === meal.id ? meal : m);
  return { state, plan, meal };
}

describe("a meal's steps, by dish", () => {
  it("groups named steps, steps that mention one dish, and steps for the whole meal", () => {
    const { meal } = twoDishMeal();
    expect(stepGroups(meal).map(g => [g.label, g.steps])).toEqual([
      ["番茄炒蛋", ["番茄切块，鸡蛋打散", "先炒蛋再炒番茄"]],
      ["蒜蓉菠菜", ["蒜蓉菠菜焯水后清炒"]],
      ["Whole meal", ["盛盘上桌"]],
    ]);
  });

  it("takes a dish's steps away with the dish", () => {
    const { meal } = twoDishMeal();
    const without = removeComponent(meal, "egg");
    expect(without.components.map(c => c.id)).toEqual(["greens"]);
    expect(without.steps).toEqual(["蒜蓉菠菜焯水后清炒", "盛盘上桌"]);
  });

  it("swaps a replaced dish's steps for the new dish's", () => {
    const { state, meal } = twoDishMeal();
    // Both dishes cook from recipes, so the meal's timing can be worked out.
    const [first, second, next] = state.recipes.filter(r => r.steps.length);
    meal.components = [{ ...meal.components[0], name: first.name, recipeId: first.id }, { ...meal.components[1], name: second.name, recipeId: second.id }];
    meal.steps = [`${first.name}: 旧的第一步`, `${second.name}: 另一道菜的步骤`, "盛盘上桌"];
    const replaced = replaceMealComponent(meal, next, "egg", state);
    expect(replaced.steps.some(step => step.includes("旧的第一步"))).toBe(false);
    expect(replaced.steps).toEqual([...next.steps.map(step => `${next.name}: ${step}`), `${second.name}: 另一道菜的步骤`, "盛盘上桌"]);
  });
});

describe("the meal drawer", () => {
  const props = (meal: Meal, state = twoDishMeal().state, plan = state.plans[0]) => ({ state, plan, meal, onClose: vi.fn(), onDirty: vi.fn(), onSave: vi.fn().mockResolvedValue(true), onAction: vi.fn().mockResolvedValue(true), onReference: vi.fn(), onRecipe: vi.fn(), busy: false });

  it("shows quick steps under each dish", () => {
    const { state, plan, meal } = twoDishMeal();
    render(<MealDrawer {...props(meal, state, plan)} />);
    const card = screen.getByRole("heading", { name: "简单步骤 Quick Steps" }).closest("section")!;
    expect(within(card).getAllByRole("heading", { level: 4 }).map(h => [...h.childNodes].at(-1)?.textContent)).toEqual(["番茄炒蛋", "蒜蓉菠菜", "Whole meal"]);
    expect(within(card).getAllByRole("list")[0]).toHaveTextContent("先炒蛋再炒番茄");
  });

  it("drops a removed dish's steps when saving, and keeps blank lines while typing", async () => {
    const { state, plan, meal } = twoDishMeal();
    const p = props(meal, state, plan);
    render(<MealDrawer {...p} initialEdit />);
    const greens = screen.getByLabelText("Steps for 蒜蓉菠菜") as HTMLTextAreaElement;
    fireEvent.change(greens, { target: { value: "蒜蓉菠菜焯水后清炒\n" } });
    expect(greens.value).toBe("蒜蓉菠菜焯水后清炒\n");
    fireEvent.click(screen.getByRole("button", { name: "Remove 番茄炒蛋" }));
    expect(screen.queryByLabelText("Steps for 番茄炒蛋")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
    await waitFor(() => expect(p.onSave).toHaveBeenCalled());
    const saved = p.onSave.mock.calls[0][0] as Meal;
    expect(saved.components.map(c => c.name)).toEqual(["蒜蓉菠菜"]);
    expect(saved.steps).toEqual(["蒜蓉菠菜焯水后清炒", "盛盘上桌"]);
  });
});

function PortionField() {
  useNumberFieldTidying();
  const [portions, setPortions] = useState(0);
  return <label>Portions<input type="number" value={portions} onChange={e => setPortions(e.target.valueAsNumber)} /><output>{portions}</output></label>;
}

it("replaces the 0 in a number field with what is typed", async () => {
  const user = userEvent.setup();
  render(<PortionField />);
  const field = screen.getByLabelText("Portions") as HTMLInputElement;
  await user.type(field, "5");
  await waitFor(() => expect(field.value).toBe("5"));
  expect(screen.getByRole("status")).toHaveTextContent("5");
  await user.clear(field);
  await user.type(field, "0.5");
  expect(field.value).toBe("0.5");
});
