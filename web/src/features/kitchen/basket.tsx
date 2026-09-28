"use client";
import { X } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "@/lib/api";
import { uid } from "./data";
import { foodEmoji } from "./food-art";
import { joinSteps, stepGroups } from "./meal-steps";
import { RecipeEditor } from "./recipe-editor";
import type { FoodType, InventoryItem, KitchenState, Meal, MealComponent, Recipe, StockUse } from "./types";
import "./basket.css";

/** A dish Stu made up from a basket of fridge foods: its recipe, and what it
 * takes from each food. */
export interface ComposedDish { recipe: Recipe; uses: StockUse[] }

/** Fridge foods that can go in a basket: those with something left, soonest to
 * use first. */
export function basketFoods(state: Pick<KitchenState, "inventory">): InventoryItem[] {
  return state.inventory.filter(item => item.portions > 0).sort((a, b) => Number(b.priority) - Number(a.priority) || (a.expiresOn ?? "9999").localeCompare(b.expiresOn ?? "9999") || a.name.localeCompare(b.name));
}

/** The demo's stand-in for Stu: the basket's foods cooked together, a share of
 * each per person. */
export function demoComposition(foods: InventoryItem[], slot: Meal["slot"], people: number): ComposedDish {
  const main = foods.find(food => food.type === "Protein") ?? foods[0];
  const share = Math.max(0.25, Math.round(people / foods.length * 4) / 4);
  const others = [...new Set(foods.map(food => food.type))].filter(type => type !== main.type) as FoodType[];
  return {
    recipe: { id: uid(), name: `${foods.slice(0, 3).map(food => food.name).join("")}小炒`, type: main.type, secondaryTypes: others.length ? others : undefined, mealTypes: [slot], tags: [], servings: people, activeMinutes: 12, elapsedMinutes: 15, ingredients: [...foods.map(food => ({ name: food.name, quantity: 100, unit: "g" })), { name: "油", quantity: 5, unit: "ml" }], steps: ["食材洗净切小块", "少油小火炒熟，淡味出锅"], liked: false, source: "Composed from fridge" },
    uses: foods.map(food => ({ inventoryId: food.id, portions: Math.min(food.portions, share) })),
  };
}

/** The meal with a composed dish on it, in place of an empty "Add food" row if
 * there is one. A dish kept as a recipe links to it; otherwise its amounts go
 * at the top of its steps so they are not lost. Hands-on time adds up (one
 * cook); waiting overlaps. */
export function addComposedDish(meal: Meal, { recipe, uses }: ComposedDish, keep: boolean): Meal {
  const placeholder = meal.components.find(c => !c.name.trim());
  const component: MealComponent = { id: placeholder?.id ?? uid(), name: recipe.name, type: recipe.type, portions: recipe.servings, uses, ...(keep ? { recipeId: recipe.id } : {}) };
  const others = meal.components.filter(c => c !== placeholder);
  const components = [...others, component];
  const amounts = recipe.ingredients.map(i => `${i.name} ${i.quantity}${i.unit}`).join("、");
  const dishSteps = keep ? recipe.steps : [`食材 Ingredients: ${amounts}`, ...recipe.steps];
  const kept = stepGroups(meal).filter(group => !placeholder || group.componentId !== placeholder.id);
  const steps = joinSteps([...kept.filter(g => g.componentId), { componentId: component.id, label: recipe.name, steps: dishSteps }, ...kept.filter(g => !g.componentId)], components);
  const activeMinutes = others.length ? meal.activeMinutes + recipe.activeMinutes : recipe.activeMinutes;
  const elapsedMinutes = others.length ? Math.max(meal.elapsedMinutes, recipe.elapsedMinutes, activeMinutes) : Math.max(recipe.elapsedMinutes, activeMinutes);
  return { ...meal, components, steps, activeMinutes, elapsedMinutes };
}

interface Props { state: KitchenState; meal: Meal; demo: boolean; onCancel: () => void; onAdd: (dish: ComposedDish, keep: boolean) => void }

/** Pick fridge foods for one dish; Stu names it and writes the amounts and
 * steps; the household changes anything before it goes on the plate. */
export function BasketComposer({ state, meal, demo, onCancel, onAdd }: Props) {
  const foods = basketFoods(state);
  const [chosen, setChosen] = useState<string[]>([]), [note, setNote] = useState(""), [composing, setComposing] = useState(false), [error, setError] = useState("");
  const [dish, setDish] = useState<ComposedDish | null>(null), [keep, setKeep] = useState(true);
  const toggle = (id: string) => setChosen(current => current.includes(id) ? current.filter(x => x !== id) : [...current, id]);
  async function compose() {
    setComposing(true); setError("");
    try {
      const basket = chosen.flatMap(id => foods.filter(food => food.id === id));
      const mealDishes = meal.components.map(c => c.name.trim()).filter(Boolean);
      setDish(demo ? demoComposition(basket, meal.slot, state.settings.people) : await api<ComposedDish>("/api/v1/kitchen/compose", { method: "POST", body: JSON.stringify({ inventoryIds: chosen, slot: meal.slot, mealDishes, note: note.trim() }) }));
    } catch (e) { setError(e instanceof Error ? e.message : "Stu could not make a dish. Please try again."); } finally { setComposing(false); }
  }
  if (dish) {
    const setUse = (id: string, portions: number) => setDish({ ...dish, uses: dish.uses.map(use => use.inventoryId === id ? { ...use, portions } : use) });
    return <RecipeEditor key={dish.recipe.id} initial={dish.recipe} tags={state.tags} title="Stu’s dish" submitLabel="Add to meal" cancel={() => setDish(null)}
      save={async recipe => { if (!dish.uses.length || dish.uses.some(use => !Number.isFinite(use.portions) || use.portions <= 0)) return false; onAdd({ recipe, uses: dish.uses }, keep); return true; }}
      actions={<label><input type="checkbox" checked={keep} onChange={e => setKeep(e.target.checked)} /> Save to Recipe Book too</label>}>
      <fieldset className="kw-basket-uses"><legend>From your fridge</legend>{dish.uses.map(use => {
        const food = state.inventory.find(item => item.id === use.inventoryId);
        return <div className="kw-basket-use" key={use.inventoryId}><span aria-hidden="true">{food?.emoji ?? foodEmoji(food?.name ?? "", food?.type)}</span><label className="kw-label">{food?.name ?? "Missing food"}<input className="kw-input" required type="number" min="0.25" step="0.25" max={food?.portions} value={use.portions} aria-label={`Portions of ${food?.name ?? "food"}`} onChange={e => setUse(use.inventoryId, e.target.valueAsNumber)} /></label><small>of {food?.portions ?? 0} left</small><button type="button" className="kw-icon" aria-label={`Leave out ${food?.name ?? "food"}`} disabled={dish.uses.length === 1} onClick={() => setDish({ ...dish, uses: dish.uses.filter(u => u !== use) })}><X size={14} /></button></div>;
      })}</fieldset>
    </RecipeEditor>;
  }
  return <div className="kw-basket">
    <p className="kw-muted">Pick the fridge foods for one dish. Stu names it and writes the amounts and steps, following your household rules; you can change anything before adding it.</p>
    {foods.length ? <div className="kw-basket-foods" role="group" aria-label="Fridge foods">{foods.map(food => <button type="button" key={food.id} className="kw-basket-food" aria-pressed={chosen.includes(food.id)} onClick={() => toggle(food.id)}><span aria-hidden="true">{food.emoji ?? foodEmoji(food.name, food.type)}</span><strong>{food.name}</strong><small>{food.portions} left · {food.location.charAt(0).toUpperCase() + food.location.slice(1)}</small></button>)}</div> : <p className="kw-empty">Your fridge is empty. Add food in Fridge first.</p>}
    <label className="kw-label">Anything Stu should know?<input className="kw-input" value={note} maxLength={1000} placeholder="e.g. soft for the baby, no frying" onChange={e => setNote(e.target.value)} /></label>
    {error && <p className="kw-error" role="alert">{error}</p>}
    <div className="kw-basket-actions"><button type="button" className="kw-button" disabled={!chosen.length || composing} onClick={() => void compose()}>{composing ? "Stu is making a dish…" : chosen.length ? `✨ Make a dish from ${chosen.length} ${chosen.length === 1 ? "food" : "foods"}` : "✨ Make a dish"}</button><button type="button" className="kw-button secondary" onClick={onCancel}>Back</button></div>
  </div>;
}
