import type { FoodType, KitchenState, Meal, MealComponent } from "./types";

type Sources = Pick<KitchenState, "recipes" | "inventory">;

/** The other groups a dish's recipe or fridge food says it contains. */
export function sourceGroups(component: MealComponent, sources: Sources): FoodType[] | undefined {
  return (sources.inventory.find(i => i.id === component.inventoryId) ?? sources.recipes.find(r => r.id === component.recipeId))?.secondaryTypes;
}

/** The food groups a dish on a plate carries: its own type first, then its
 * other groups (buns: Carbs, with Protein and Vegetables) — set on the dish
 * itself, or else those of its recipe or fridge food — and for a dish cooked
 * from fridge foods, what those foods are. */
export function componentGroups(component: MealComponent, sources: Sources): FoodType[] {
  const own = component.secondaryTypes ?? sourceGroups(component, sources) ?? [];
  const foods = (component.uses ?? []).flatMap(use => { const food = sources.inventory.find(i => i.id === use.inventoryId); return food ? [food.type, ...(food.secondaryTypes ?? [])] : []; });
  return [...new Set([component.type, ...own, ...foods])];
}

/** Whether any dish in the meal carries a food group, main or secondary. */
export const mealHas = (meal: Meal, group: FoodType, sources: Sources) =>
  meal.components.some(component => componentGroups(component, sources).includes(group));
