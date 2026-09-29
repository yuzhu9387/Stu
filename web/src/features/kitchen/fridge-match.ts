import { pantryStaple } from "./shopping";
import type { InventoryItem, Recipe } from "./types";

const normalize = (s: string) => s.normalize("NFKC").trim().toLocaleLowerCase().replace(/\s+/g, " ");

/** One name is the other, or holds it ("土鸡蛋" holds "鸡蛋"). A single
 * character ("葱", "蛋") counts only at either end ("葱花", "鸡蛋"), not
 * buried in the middle of another food's name. */
function same(a: string, b: string) {
  if (a === b) return true;
  const [short, long] = a.length <= b.length ? [a, b] : [b, a];
  return short.length >= 2 ? long.includes(short) : long.startsWith(short) || long.endsWith(short);
}

/** How many of a recipe's foods the fridge has something left of, by a
 * food's name or its English name. Water and seasonings are in every
 * kitchen, so they count neither way. */
export function fridgeMatch(recipe: Pick<Recipe, "ingredients">, inventory: InventoryItem[]): { have: number; total: number } {
  const stocked = inventory.filter(item => item.portions > 0).flatMap(item => [item.name, item.nameEn ?? ""]).filter(Boolean).map(normalize);
  const foods = [...new Set(recipe.ingredients.filter(i => i.name.trim() && !pantryStaple(i)).map(i => normalize(i.name)))];
  return { have: foods.filter(name => stocked.some(item => same(name, item))).length, total: foods.length };
}
