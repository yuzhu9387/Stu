import { api } from "@/lib/api";
import { setDishSteps, stepGroups } from "./meal-steps";
import type { FoodType, Ingredient, KitchenState, Meal, MealComponent, Recipe } from "./types";

/** A dish as sent to Stu: what the household wrote, blanks left out. */
export interface FillDish { id: string; name: string; portions: number; type?: FoodType; secondaryTypes?: FoodType[]; ingredients?: Ingredient[]; steps?: string[]; activeMinutes?: number; elapsedMinutes?: number }
export interface FilledDish { id: string; type: FoodType; secondaryTypes?: FoodType[]; ingredients: Ingredient[]; steps: string[]; activeMinutes: number; elapsedMinutes: number }

/** A dish written by hand: no recipe, and not served from the fridge or prep.
 * Only these have blanks for Stu; the others take theirs from their source. */
const handWritten = (c: MealComponent) => !c.recipeId && !c.prepId && !c.inventoryId && !c.uses?.length && !!c.name.trim();

const dishSteps = (meal: Meal, id: string) => stepGroups(meal).find(group => group.componentId === id)?.steps.filter(step => step.trim()) ?? [];

/** The meal without ingredient rows left empty: an empty row is a blank for
 * Stu, not an ingredient without a name. */
export function withoutEmptyRows(meal: Meal): Meal {
  return { ...meal, components: meal.components.map(c => c.ingredients?.some(i => !i.name.trim()) ? { ...c, ingredients: c.ingredients.filter(i => i.name.trim()) } : c) };
}

/** What Stu would fill on save: per hand-written dish, a missing food group
 * ("Other"), ingredients, steps or time each count as one blank. */
export function blanks(written: Meal, state: Pick<KitchenState, "recipes">): { count: number; dishes: FillDish[] } {
  void state;
  const meal = withoutEmptyRows(written);
  let count = 0;
  const dishes: FillDish[] = [];
  for (const c of meal.components.filter(handWritten)) {
    const steps = dishSteps(meal, c.id);
    const missing = [c.type === "Other", !c.ingredients?.length, !steps.length, c.activeMinutes === undefined].filter(Boolean).length;
    if (!missing) continue;
    count += missing;
    dishes.push({
      id: c.id, name: c.name, portions: c.portions,
      ...(c.type !== "Other" ? { type: c.type } : {}),
      ...(c.secondaryTypes ? { secondaryTypes: c.secondaryTypes } : {}),
      ...(c.ingredients?.length ? { ingredients: c.ingredients } : {}),
      ...(steps.length ? { steps } : {}),
      ...(c.activeMinutes !== undefined ? { activeMinutes: c.activeMinutes } : {}),
      ...(c.elapsedMinutes !== undefined ? { elapsedMinutes: c.elapsedMinutes } : {}),
    });
  }
  return { count, dishes };
}

/** The demo's stand-in for Stu: plain amounts and steps for each blank. */
function demoFill(dish: FillDish): FilledDish {
  return {
    id: dish.id, type: dish.type ?? "Vegetables",
    ingredients: dish.ingredients ?? [{ name: dish.name, quantity: 100 * dish.portions, unit: "g" }],
    steps: dish.steps ?? [`Wash and cut the ${dish.name}.`, "Cook until tender; season lightly for the child."],
    activeMinutes: dish.activeMinutes ?? 10, elapsedMinutes: dish.elapsedMinutes ?? 15,
  };
}

/** The meal with Stu's answers in its blanks only; anything written stays. */
export function mergeFilled(meal: Meal, filled: FilledDish[]): Meal {
  let next: Meal = { ...meal, components: meal.components.map(c => {
    const f = filled.find(dish => dish.id === c.id);
    if (!f) return c;
    const activeMinutes = c.activeMinutes ?? f.activeMinutes;
    return {
      ...c,
      type: c.type === "Other" ? f.type : c.type,
      ...(c.secondaryTypes === undefined && f.secondaryTypes?.length ? { secondaryTypes: f.secondaryTypes } : {}),
      ingredients: c.ingredients?.length ? c.ingredients : f.ingredients,
      activeMinutes,
      elapsedMinutes: c.elapsedMinutes ?? Math.max(f.elapsedMinutes, activeMinutes),
    };
  }) };
  for (const f of filled) if (!dishSteps(next, f.id).length && f.steps.length) next = setDishSteps(next, f.id, f.steps.join("\n"));
  return next;
}

/** Ask Stu (or, in the demo, fill plainly) for the meal's blanks. Throws when
 * Stu cannot answer; the caller saves the meal as it is then. */
export async function fillMeal(meal: Meal, state: Pick<KitchenState, "recipes">, demo: boolean): Promise<Meal> {
  const { dishes } = blanks(meal, state);
  if (!dishes.length) return meal;
  const answer = demo ? { dishes: dishes.map(demoFill) } : await api<{ dishes: FilledDish[] }>("/api/v1/kitchen/fill", { method: "POST", body: JSON.stringify({ slot: meal.slot, dishes }) });
  return mergeFilled(meal, answer.dishes);
}

/** A recipe's blanks for Stu: no ingredient named, no step written. */
export function recipeBlanks(recipe: Recipe): number {
  return Number(!recipe.ingredients.some(i => i.name.trim())) + Number(!recipe.steps.some(step => step.trim()));
}

/** A recipe with its blanks filled by Stu (or, in the demo, plainly), through
 * the same fill as a meal's dishes; anything written stays. Throws when Stu
 * cannot answer. */
export async function fillRecipe(recipe: Recipe, demo: boolean): Promise<Recipe> {
  const ingredients = recipe.ingredients.filter(i => i.name.trim()), steps = recipe.steps.map(step => step.trim()).filter(Boolean);
  const dish: FillDish = {
    id: recipe.id, name: recipe.name.trim(), portions: recipe.servings > 0 ? recipe.servings : 1,
    ...(recipe.type !== "Other" ? { type: recipe.type } : {}),
    ...(recipe.secondaryTypes ? { secondaryTypes: recipe.secondaryTypes } : {}),
    ...(ingredients.length ? { ingredients } : {}), ...(steps.length ? { steps } : {}),
    activeMinutes: recipe.activeMinutes, elapsedMinutes: recipe.elapsedMinutes,
  };
  const answer = demo ? { dishes: [demoFill(dish)] } : await api<{ dishes: FilledDish[] }>("/api/v1/kitchen/fill", { method: "POST", body: JSON.stringify({ slot: recipe.mealTypes[0] ?? "dinner", dishes: [dish] }) });
  const filled = answer.dishes.find(d => d.id === recipe.id);
  if (!filled) throw new Error("Stu could not fill this recipe.");
  return {
    ...recipe,
    type: recipe.type === "Other" ? filled.type : recipe.type,
    ...(recipe.secondaryTypes === undefined && filled.secondaryTypes?.length ? { secondaryTypes: filled.secondaryTypes } : {}),
    ingredients: ingredients.length ? ingredients : filled.ingredients,
    steps: steps.length ? steps : filled.steps,
    incomplete: false,
  };
}
