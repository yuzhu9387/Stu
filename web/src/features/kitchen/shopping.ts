import type { KitchenState, WeeklyPlan } from "./types";

export interface ShoppingItem {
  key: string; name: string; unit: string; group: string;
  required: number; inStock: number; toBuy: number; dishes: string[];
}
const normalize = (s: string) => s.normalize("NFKC").trim().toLocaleLowerCase().replace(/\s+/g, " ");
const round = (n: number) => Math.round(n * 10000) / 10000;
const units: Record<string, [string, number]> = {
  g: ["g", 1], gram: ["g", 1], grams: ["g", 1], "克": ["g", 1],
  kg: ["g", 1000], kilograms: ["g", 1000], "千克": ["g", 1000], "公斤": ["g", 1000],
  ml: ["ml", 1], "毫升": ["ml", 1], l: ["ml", 1000], liter: ["ml", 1000], liters: ["ml", 1000], "升": ["ml", 1000],
  piece: ["pcs", 1], pieces: ["pcs", 1], pcs: ["pcs", 1], "个": ["pcs", 1],
  portion: ["portions", 1], portions: ["portions", 1], "份": ["portions", 1],
};

/** The checklist is a projection, never a stock reservation. Only explicitly
 * linked prepared food covers a meal; a fresh recipe still needs ingredients.
 * Stock is pooled once, and incompatible units are never silently converted. */
export function shoppingList(state: KitchenState, plan: WeeklyPlan, asOf = new Intl.DateTimeFormat("en-CA", { timeZone: state.settings.timezone }).format(new Date())) {
  const warnings = new Set<string>();
  const ingredients = new Map<string, ShoppingItem>();
  const recipes = new Map(state.recipes.map(r => [r.id, r]));
  const stockDate = asOf > plan.weekStart ? asOf : plan.weekStart;
  const balances = new Map(state.inventory.map(i => [i.id, i.expiresOn && i.expiresOn < stockDate ? 0 : i.portions]));
  const capacity = new Map(plan.prep.filter(t => t.status === "planned").map(t => [t.id, t.plannedPortions]));
  function take(id: string, need: number, day: string) {
    const stock = state.inventory.find(i => i.id === id);
    if (stock?.expiresOn && stock.expiresOn < day) return need;
    const amount = Math.min(need, balances.get(id) ?? 0);
    balances.set(id, (balances.get(id) ?? 0) - amount);
    return need - amount;
  }
  function addRecipe(id: string | undefined, portions: number, name: string) {
    if (portions <= 0) return;
    const recipe = id ? recipes.get(id) : undefined;
    if (!recipe?.ingredients.length || !recipe.servings) {
      warnings.add(`${name}: add a recipe with ingredients to complete this shopping list.`);
      return;
    }
    for (const ingredient of recipe.ingredients) {
      if (!ingredient.quantity || !ingredient.unit.trim()) {
        warnings.add(`${ingredient.name} (${name}): check the amount in the recipe.`);
        continue;
      }
      const rawUnit = normalize(ingredient.unit), [unit, factor] = units[rawUnit] ?? [rawUnit, 1];
      const key = JSON.stringify([normalize(ingredient.name), unit]);
      const item = ingredients.get(key) ?? { key, name: ingredient.name, unit, group: ingredient.group || "Other", required: 0, inStock: 0, toBuy: 0, dishes: [] };
      item.required += ingredient.quantity * factor * portions / recipe.servings;
      if (!item.dishes.includes(name)) item.dishes.push(name);
      ingredients.set(key, item);
    }
  }
  for (const task of plan.prep) {
    if (task.status === "planned") addRecipe(task.recipeId, task.plannedPortions, task.name);
  }
  for (const meal of [...plan.meals].sort((a, b) => a.day.localeCompare(b.day) || a.slot.localeCompare(b.slot))) {
    if (meal.included === false || meal.status !== "planned") continue;
    for (const component of meal.components) {
      let need = component.portions;
      const task = plan.prep.find(t => t.id === component.prepId);
      if (task?.status === "planned") {
        const covered = Math.min(need, capacity.get(task.id) ?? 0);
        capacity.set(task.id, (capacity.get(task.id) ?? 0) - covered);
        need -= covered;
        if (need > 0) warnings.add(`${task.name}: increase prep by ${round(need)} portions or replace the uncovered meal.`);
      } else if (task?.status === "completed" && task.outputInventoryId) {
        need = take(task.outputInventoryId, need, meal.day);
      } else if (component.inventoryId) {
        need = take(component.inventoryId, need, meal.day);
      }
      const stored = state.inventory.find(i => i.id === component.inventoryId);
      addRecipe(component.recipeId ?? task?.recipeId ?? stored?.recipeId, need, component.name);
    }
  }
  const rawBalances = new Map(balances);
  for (const item of ingredients.values()) {
    for (const stock of state.inventory) {
      if (stock.prepared || ![stock.name, stock.nameEn ?? ""].some(name => normalize(name) === normalize(item.name))) continue;
      const portions = rawBalances.get(stock.id) ?? 0;
      if (portions <= 0) continue;
      // A fridge portion has a known mass only when the household recorded it.
      const factor = item.unit === "g" ? stock.portionGrams : item.unit === "portions" ? 1 : undefined;
      if (!factor) {
        warnings.add(`${stock.name}: ${portions} portions in stock; check the amount in ${item.unit} before buying.`);
        continue;
      }
      const amount = Math.min(item.required - item.inStock, portions * factor);
      item.inStock += amount;
      rawBalances.set(stock.id, portions - amount / factor);
      if (item.group === "Other") item.group = stock.type;
    }
    item.required = round(item.required); item.inStock = round(item.inStock);
    item.toBuy = round(Math.max(0, item.required - item.inStock));
    item.key = JSON.stringify([normalize(item.name), item.unit, item.toBuy]);
  }
  return { items: [...ingredients.values()], warnings: [...warnings] };
}
