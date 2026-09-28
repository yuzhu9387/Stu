import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { addComposedDish, basketFoods, type ComposedDish } from "@/features/kitchen/basket";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { componentGroups } from "@/features/kitchen/food-groups";
import { MealDrawer } from "@/features/kitchen/meal-drawer";
import { projectedMealShortages } from "@/features/kitchen/schedule";
import { shoppingList } from "@/features/kitchen/shopping";
import type { InventoryItem, KitchenState, Meal, Recipe } from "@/features/kitchen/types";

const raw = (id: string, name: string, type: InventoryItem["type"], portions: number): InventoryItem => ({ id, name, type, portions, location: "Fridge", prepared: false, addedOn: "2026-09-20", priority: false });

function household() {
  const state = createDemoState();
  state.settings.people = 1;
  state.inventory.push(raw("eggs", "鸡蛋", "Protein", 10), raw("spinach", "菠菜", "Vegetables", 2), raw("gone", "玉米", "Carbs", 0));
  const plan = state.plans[0], meal = plan.meals.find(m => m.id === "meal-1-lunch")!;
  return { state, plan, meal };
}

const pancake = (extra: Partial<Recipe> = {}): Recipe => ({ id: "r-pancake", name: "菠菜鸡蛋饼", type: "Protein", secondaryTypes: ["Vegetables"], mealTypes: ["lunch"], tags: [], servings: 1, activeMinutes: 10, elapsedMinutes: 15, ingredients: [{ name: "鸡蛋", quantity: 2, unit: "个" }, { name: "菠菜", quantity: 50, unit: "g" }, { name: "面粉", quantity: 30, unit: "g" }], steps: ["菠菜焯水切碎", "小火煎熟"], liked: false, source: "Composed from fridge", ...extra });
const dish = (extra: Partial<Recipe> = {}): ComposedDish => ({ recipe: pancake(extra), uses: [{ inventoryId: "eggs", portions: 2 }, { inventoryId: "spinach", portions: 1 }] });

/** The household's lunch with the pancake on it, confirmed. */
function withPancake(recipeId?: string) {
  const { state, plan, meal } = household();
  const next = addComposedDish(meal, dish(), Boolean(recipeId));
  plan.meals = plan.meals.map(m => m.id === meal.id ? next : m);
  if (recipeId) state.recipes.push(pancake());
  plan.status = "confirmed";
  return { state, plan, meal: next };
}

describe("a dish composed from fridge foods", () => {
  it("offers only foods with something left, soonest to use first", () => {
    const { state } = household();
    state.inventory.find(i => i.id === "spinach")!.expiresOn = "2026-09-22";
    const ids = basketFoods(state).map(item => item.id);
    expect(ids).not.toContain("gone");
    expect(ids.indexOf("spinach")).toBeLessThan(ids.indexOf("eggs"));
  });

  it("joins the meal with its fridge foods, its steps and its time", () => {
    const { meal } = household();
    const next = addComposedDish(meal, dish(), false);
    const added = next.components.at(-1)!;
    expect(added).toMatchObject({ name: "菠菜鸡蛋饼", type: "Protein", portions: 1, uses: dish().uses });
    expect(added.recipeId).toBeUndefined();
    // Not kept as a recipe: the amounts lead its steps so they are not lost.
    expect(next.steps.filter(step => step.startsWith("菠菜鸡蛋饼: "))).toEqual(["菠菜鸡蛋饼: 食材 Ingredients: 鸡蛋 2个、菠菜 50g、面粉 30g", "菠菜鸡蛋饼: 菠菜焯水切碎", "菠菜鸡蛋饼: 小火煎熟"]);
    expect(next.activeMinutes).toBe(meal.activeMinutes + 10);
    const kept = addComposedDish(meal, dish(), true).components.at(-1)!;
    expect(kept.recipeId).toBe("r-pancake");
  });

  it("takes the place of an empty food row", () => {
    const { meal } = household();
    const blank: Meal = { ...meal, components: [{ id: "blank", name: "", type: "Other", portions: 1 }], steps: [] };
    const next = addComposedDish(blank, dish(), true);
    expect(next.components.map(c => [c.id, c.name])).toEqual([["blank", "菠菜鸡蛋饼"]]);
    expect(next.steps).toEqual(["菠菜焯水切碎", "小火煎熟"]);
    expect([next.activeMinutes, next.elapsedMinutes]).toEqual([10, 15]);
  });

  it("counts the groups of the foods it is made from", () => {
    const { state, meal } = withPancake();
    expect(componentGroups(meal.components.at(-1)!, state)).toEqual(["Protein", "Vegetables"]);
  });

  it("says which fridge food runs short, and buys only what the fridge lacks", () => {
    const { state, plan } = withPancake("r-pancake");
    state.inventory.find(i => i.id === "spinach")!.portions = 0.5;
    const short = projectedMealShortages(state, plan).flatMap(s => s.missing);
    expect(short).toContainEqual({ name: "菠菜", portions: 0.5 });
    const toBuy = shoppingList(state, plan).items.filter(item => item.dishes.includes("菠菜鸡蛋饼")).map(item => item.name);
    expect(toBuy).toEqual(["面粉"]);
  });

  it("takes each food from the fridge when the meal is eaten (demo)", () => {
    const { state, plan, meal } = withPancake();
    const done = applyDemoCommand(state, { type: "meal.status", payload: { planId: plan.id, mealId: meal.id, status: "completed" }, expectedRevision: state.revision, operationId: "eat" }).state;
    const left = (s: KitchenState, id: string) => s.inventory.find(i => i.id === id)?.portions;
    expect([left(done, "eggs"), left(done, "spinach")]).toEqual([8, 1]);
  });
});

describe("cooking from the fridge in the meal drawer", () => {
  afterEach(() => vi.unstubAllGlobals());
  const props = (demo: boolean) => {
    const { state, plan, meal } = household();
    return { state, plan, meal, demo, onClose: vi.fn(), onDirty: vi.fn(), onSave: vi.fn().mockResolvedValue(true), onAction: vi.fn().mockResolvedValue(true), onReference: vi.fn(), onRecipe: vi.fn(), busy: false, initialEdit: true };
  };

  it("asks Stu for a dish from the chosen foods and saves it with its recipe", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(dish()), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    const p = props(false);
    render(<MealDrawer {...p} />);
    fireEvent.click(screen.getByRole("button", { name: "🧺 Cook from fridge" }));
    const foods = screen.getByRole("group", { name: "Fridge foods" });
    expect(within(foods).queryByRole("button", { name: /玉米/ })).not.toBeInTheDocument();
    fireEvent.click(within(foods).getByRole("button", { name: /鸡蛋/ }));
    fireEvent.click(within(foods).getByRole("button", { name: /菠菜/ }));
    fireEvent.change(screen.getByLabelText("Anything Stu should know?"), { target: { value: "软一点" } });
    fireEvent.click(screen.getByRole("button", { name: "✨ Make a dish from 2 foods" }));
    await screen.findByRole("heading", { name: "Stu’s dish" });
    const sent = JSON.parse(fetch.mock.calls[0][1].body as string);
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/v1\/kitchen\/compose$/);
    expect(sent).toMatchObject({ inventoryIds: ["eggs", "spinach"], slot: "lunch", note: "软一点" });
    fireEvent.change(screen.getByLabelText("Portions of 菠菜"), { target: { value: "0.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to meal" }));
    expect(await screen.findByLabelText("Source for 菠菜鸡蛋饼")).toHaveDisplayValue("🧺 鸡蛋 2 · 菠菜 0.5");
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
    await waitFor(() => expect(p.onSave).toHaveBeenCalled());
    const [saved, , recipes] = p.onSave.mock.calls[0] as [Meal, Meal, Recipe[]];
    expect(saved.components.at(-1)).toMatchObject({ name: "菠菜鸡蛋饼", recipeId: "r-pancake", uses: [{ inventoryId: "eggs", portions: 2 }, { inventoryId: "spinach", portions: 0.5 }] });
    expect(recipes.map(r => r.id)).toEqual(["r-pancake"]);
  });

  it("makes up a dish without the AI in the demo, and can leave the recipe out", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const p = props(true);
    render(<MealDrawer {...p} />);
    fireEvent.click(screen.getByRole("button", { name: "🧺 Cook from fridge" }));
    fireEvent.click(within(screen.getByRole("group", { name: "Fridge foods" })).getByRole("button", { name: /鸡蛋/ }));
    fireEvent.click(screen.getByRole("button", { name: "✨ Make a dish from 1 food" }));
    await screen.findByRole("heading", { name: "Stu’s dish" });
    fireEvent.click(screen.getByLabelText("Save to Recipe Book too"));
    fireEvent.click(screen.getByRole("button", { name: "Add to meal" }));
    await screen.findByLabelText("Source for 鸡蛋小炒");
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
    await waitFor(() => expect(p.onSave).toHaveBeenCalled());
    const [saved, , recipes] = p.onSave.mock.calls[0] as [Meal, Meal, Recipe[]];
    expect(saved.components.at(-1)).toMatchObject({ name: "鸡蛋小炒", uses: [{ inventoryId: "eggs", portions: 1 }] });
    expect(saved.components.at(-1)!.recipeId).toBeUndefined();
    expect(recipes).toEqual([]);
    expect(fetch).not.toHaveBeenCalled();
  });
});

it("offers to make your own dish first when filling an empty slot", async () => {
  const { state, plan } = household();
  const fresh: Meal = { id: "new-meal", day: "2026-09-21", slot: "dinner", components: [{ id: "blank", name: "", type: "Other", portions: 1 }], activeMinutes: 0, elapsedMinutes: 0, steps: [], status: "planned", liked: false, locked: false };
  const onSave = vi.fn().mockResolvedValue(true);
  render(<MealDrawer state={state} plan={plan} meal={fresh} demo initialReplace onClose={vi.fn()} onDirty={vi.fn()} onSave={onSave} onAction={vi.fn()} onReference={vi.fn()} onRecipe={vi.fn()} busy={false} />);
  expect(screen.getByRole("heading", { name: "Add a meal" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "🧺 Make your own" }));
  expect(screen.getByRole("group", { name: "Fridge foods" })).toBeInTheDocument();
  // Back returns to the choice it came from.
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  fireEvent.click(screen.getByRole("button", { name: "🧺 Make your own" }));
  fireEvent.click(within(screen.getByRole("group", { name: "Fridge foods" })).getByRole("button", { name: /鸡蛋/ }));
  fireEvent.click(screen.getByRole("button", { name: "✨ Make a dish from 1 food" }));
  await screen.findByRole("heading", { name: "Stu’s dish" });
  fireEvent.click(screen.getByRole("button", { name: "Add to meal" }));
  await screen.findByLabelText("Source for 鸡蛋小炒");
  fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
  await waitFor(() => expect(onSave).toHaveBeenCalled());
  expect((onSave.mock.calls[0][0] as Meal).components.map(c => c.name)).toEqual(["鸡蛋小炒"]);
});
