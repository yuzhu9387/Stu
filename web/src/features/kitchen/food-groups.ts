import type { FoodType, KitchenState, Meal, MealComponent } from "./types";

type Sources = Pick<KitchenState, "recipes" | "inventory">;

/** The food groups a dish on a plate carries: its own type first, then what
 * its fridge food or recipe also contains (buns: Carbs, with Protein and
 * Vegetables). A dish has no groups of its own beyond its type. */
export function componentGroups(component: MealComponent, sources: Sources): FoodType[] {
  const source = sources.inventory.find(i => i.id === component.inventoryId) ?? sources.recipes.find(r => r.id === component.recipeId);
  return [component.type, ...(source?.secondaryTypes ?? []).filter(group => group !== component.type)];
}

/** Whether any dish in the meal carries a food group, main or secondary. */
export const mealHas = (meal: Meal, group: FoodType, sources: Sources) =>
  meal.components.some(component => componentGroups(component, sources).includes(group));
