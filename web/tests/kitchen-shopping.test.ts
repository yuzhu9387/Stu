import { describe, expect, it } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { shoppingList } from "@/features/kitchen/shopping";

function fixture() {
  const state = createDemoState(), plan = state.plans[0];
  const recipe = state.recipes[0];
  recipe.servings = 2;
  recipe.ingredients = [{ name: "鸡肉", quantity: 400, unit: "g" }, { name: "Egg", quantity: 2, unit: "pieces" }];
  plan.meals = [{ ...plan.meals[0], included: true, status: "planned", components: [{ id: "c", name: recipe.name, type: "Protein", recipeId: recipe.id, portions: 2 }] }];
  plan.prep = []; state.inventory = [];
  return { state, plan, recipe };
}

describe("shopping requirements", () => {
  it("scales servings, combines units, and deducts compatible raw stock", () => {
    const { state, plan, recipe } = fixture();
    recipe.ingredients.push({ name: "鸡肉", quantity: 0.2, unit: "kg" });
    plan.meals[0].components[0].portions = 4;
    state.inventory.push({ id: "raw", name: "鸡肉", type: "Protein", portions: 2, portionGrams: 100, location: "fridge", prepared: false, addedOn: "2026-09-20", priority: false });
    expect(shoppingList(state, plan).items.find(i => i.name === "鸡肉")).toMatchObject({ required: 1200, inStock: 200, toBuy: 1000, unit: "g" });
  });
  it("counts a prep batch once across multiple meals, and includes extra batch portions", () => {
    const { state, plan, recipe } = fixture();
    const task = createDemoState().plans[0].prep[0];
    plan.prep = [{ ...task, id: "prep", recipeId: recipe.id, plannedPortions: 6, status: "planned", inputs: [] }];
    plan.meals[0].components[0].prepId = "prep";
    plan.meals.push({ ...structuredClone(plan.meals[0]), id: "m2", day: "2026-09-23" });
    expect(shoppingList(state, plan).items.find(i => i.name === "鸡肉")?.required).toBe(1200);
  });
  it("does not count skipped, excluded or completed meals", () => {
    const { state, plan } = fixture();
    plan.meals[0].included = false;
    expect(shoppingList(state, plan).items).toEqual([]);
    plan.meals[0].included = true; plan.meals[0].status = "completed";
    expect(shoppingList(state, plan).items).toEqual([]);
    plan.meals[0].status = "skipped";
    expect(shoppingList(state, plan).items).toEqual([]);
  });
  it("deducts linked prepared food once and buys ingredients only for its shortfall", () => {
    const { state, plan, recipe } = fixture();
    plan.meals[0].components[0].inventoryId = "stored";
    state.inventory.push({ id: "stored", name: recipe.name, recipeId: recipe.id, type: "Protein", portions: 1, location: "freezer", prepared: true, addedOn: "2026-09-20", priority: false });
    expect(shoppingList(state, plan).items.find(i => i.name === "鸡肉")?.required).toBe(200);
  });
  it("flags unknown grams per portion and missing recipes without inventing conversions", () => {
    const { state, plan } = fixture();
    state.inventory.push({ id: "raw", name: "鸡肉", type: "Protein", portions: 2, location: "fridge", prepared: false, addedOn: "2026-09-20", priority: false });
    const result = shoppingList(state, plan);
    expect(result.items.find(i => i.name === "鸡肉")?.inStock).toBe(0);
    expect(result.warnings.join(" ")).toContain("鸡肉");
    plan.meals[0].components[0].recipeId = undefined;
    expect(shoppingList(state, plan).warnings.join(" ")).toContain("recipe");
  });
  it("excludes expired stock and changes the check key when the quantity changes", () => {
    const { state, plan } = fixture();
    const before = shoppingList(state, plan).items[0];
    state.inventory.push({ id: "raw", name: "鸡肉", type: "Protein", portions: 2, portionGrams: 100, location: "fridge", prepared: false, addedOn: "2026-09-10", expiresOn: "2026-09-19", priority: false });
    expect(shoppingList(state, plan).items.find(i => i.name === "鸡肉")?.inStock).toBe(0);
    plan.meals[0].components[0].portions = 4;
    expect(shoppingList(state, plan).items[0].key).not.toBe(before.key);
  });
  it("does not use stock that expired during the week or before its meal", () => {
    const { state, plan, recipe } = fixture();
    state.inventory.push({ id: "raw", name: "鸡肉", type: "Protein", portions: 4, portionGrams: 100, location: "fridge", prepared: false, addedOn: "2026-09-20", expiresOn: "2026-09-22", priority: false });
    expect(shoppingList(state, plan, "2026-09-24").items.find(i => i.name === "鸡肉")?.inStock).toBe(0);
    state.inventory = [{ ...state.inventory[0], id: "stored", name: recipe.name, prepared: true, recipeId: recipe.id, expiresOn: "2026-09-25" }];
    plan.meals[0].day = "2026-09-27"; plan.meals[0].components[0].inventoryId = "stored";
    expect(shoppingList(state, plan, "2026-09-24").items.find(i => i.name === "鸡肉")?.required).toBe(400);
  });
});
