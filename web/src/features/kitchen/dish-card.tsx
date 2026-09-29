"use client";
import { Plus, Trash, X } from "@phosphor-icons/react";
import { useState } from "react";
import { AlsoContains } from "./also-contains";
import { foodTypes } from "./data";
import { foodEmoji } from "./food-art";
import { sourceGroups } from "./food-groups";
import { setDishSteps, stepGroups } from "./meal-steps";
import type { Ingredient, KitchenState, Meal, MealComponent, WeeklyPlan } from "./types";

/** Steps as saved: each line trimmed, blank lines gone. */
const tidy = (text: string) => text.split("\n").map(line => line.trim()).filter(Boolean).join("\n");

interface Props { dish: MealComponent; index: number; meal: Meal; state: KitchenState; plan: WeeklyPlan; basketLine: string; recipeHref: (id: string) => string; onMeal: (meal: Meal) => void; onSource: (value: string) => void; onRemove: () => void }

/** One dish of a meal being planned: where it comes from and how many
 * portions, its food groups, ingredients, steps and time. A recipe or a
 * ready-made fridge dish brings its own; a hand-written dish keeps them here,
 * and Stu fills what is left blank when the meal is saved. */
export function DishCard({ dish, index, meal, state, plan, basketLine, recipeHref, onMeal, onSource, onRemove }: Props) {
  const recipe = state.recipes.find(r => r.id === dish.recipeId);
  const stock = state.inventory.find(i => i.id === dish.inventoryId);
  const ready = !!dish.prepId || !!stock?.prepared;
  const label = dish.name || `food ${index + 1}`;
  const set = (patch: Partial<MealComponent>) => onMeal({ ...meal, components: meal.components.map(c => c.id === dish.id ? { ...c, ...patch } : c) });
  // The textarea keeps its own text so blank lines survive while typing; when
  // the dish's steps change from outside (Stu filled them on save), it shows them.
  const fromMeal = stepGroups(meal).find(group => group.componentId === dish.id)?.steps.join("\n") ?? "";
  const [steps, setSteps] = useState(fromMeal), [shown, setShown] = useState(fromMeal);
  if (fromMeal !== shown) {
    setShown(fromMeal);
    if (tidy(fromMeal) !== tidy(steps)) setSteps(fromMeal);
  }
  const own = dish.ingredients ?? [];
  const setOwn = (next: Ingredient[]) => set({ ingredients: next });
  const sourceValue = dish.uses?.length ? "basket" : dish.prepId ? `prep:${dish.prepId}` : dish.inventoryId ? `inventory:${dish.inventoryId}` : dish.recipeId ? `recipe:${dish.recipeId}` : "fresh";

  return <section className="kw-dish-card" role="group" aria-label={`Dish ${label}`}>
    <div className="kw-dish-card-head">
      <span className="kw-dish-card-emoji" aria-hidden="true">{foodEmoji(dish.name, dish.type)}</span>
      <label className="kw-label">Food<input className="kw-input" value={dish.name} onChange={e => set({ name: e.target.value, recipeId: undefined, inventoryId: undefined, prepId: undefined })} /></label>
      <button type="button" className="kw-icon danger" aria-label={`Remove ${dish.name}`} onClick={onRemove}><Trash size={16} /></button>
    </div>
    <div className="kw-dish-card-row">
      <label className="kw-label">Source<select className="kw-input" aria-label={`Source for ${label}`} value={sourceValue} onChange={e => onSource(e.target.value)}>
        {dish.uses?.length ? <option value="basket">🧺 {basketLine}</option> : null}
        <option value="fresh">Fresh / written here</option>
        <optgroup label="Recipes">{state.recipes.map(r => <option key={r.id} value={`recipe:${r.id}`} disabled={r.incomplete}>{r.name}{r.incomplete ? " (needs review)" : ""}</option>)}</optgroup>
        <optgroup label="On hand">{state.inventory.map(item => <option key={item.id} value={`inventory:${item.id}`}>{item.name} · {item.portions} portions · {item.location}</option>)}</optgroup>
        <optgroup label="Weekend prep">{plan.prep.map(task => <option key={task.id} value={`prep:${task.id}`}>{task.name} · {task.status}</option>)}</optgroup>
      </select></label>
      <label className="kw-label kw-dish-portions">Portions<input className="kw-input" type="number" min="0.25" step="0.25" value={dish.portions} onChange={e => set({ portions: Number(e.target.value) })} /></label>
    </div>
    <label className="kw-label">Food group<select className="kw-input" value={dish.type} onChange={e => set({ type: e.target.value as MealComponent["type"] })}>{foodTypes.map(type => <option key={type}>{type}</option>)}</select></label>
    <AlsoContains primary={dish.type} name={label} value={dish.secondaryTypes ?? sourceGroups(dish, state)} onChange={groups => set({ secondaryTypes: groups })} />

    <div className="kw-dish-card-block">
      <span className="kw-dish-card-label">Ingredients</span>
      {recipe ? <ul className="kw-dish-ingredients">{recipe.ingredients.map((i, n) => <li key={n}>{i.name} {i.quantity}{/^[a-z]{3,}/i.test(i.unit) ? " " : ""}{i.unit}</li>)}<li className="kw-muted">from the recipe · <a href={recipeHref(recipe.id)} target="_blank" rel="noopener noreferrer" aria-label={`View recipe for ${dish.name}`}>View recipe ↗</a></li></ul>
        : ready ? <p className="kw-muted">Ready-made: reheat before serving.</p>
        : dish.uses?.length ? <p className="kw-muted">From the fridge: {basketLine}</p>
        : <>{own.map((ingredient, n) => <div className="kw-dish-ingredient" key={n}>
            <input className="kw-input" aria-label={`Ingredient ${n + 1}`} value={ingredient.name} placeholder="菠菜" onChange={e => setOwn(own.map((x, m) => m === n ? { ...x, name: e.target.value } : x))} />
            <input className="kw-input" type="number" min="0" step="any" aria-label={`Amount ${n + 1}`} value={ingredient.quantity} onChange={e => setOwn(own.map((x, m) => m === n ? { ...x, quantity: Number(e.target.value) } : x))} />
            <input className="kw-input" aria-label={`Unit ${n + 1}`} value={ingredient.unit} placeholder="g" onChange={e => setOwn(own.map((x, m) => m === n ? { ...x, unit: e.target.value } : x))} />
            <button type="button" className="kw-icon" aria-label={`Remove ingredient ${n + 1}`} onClick={() => setOwn(own.filter((_, m) => m !== n))}><X size={14} /></button>
          </div>)}
          <button type="button" className="kw-text-button" onClick={() => setOwn([...own, { name: "", quantity: 1, unit: "" }])}><Plus size={14} />Ingredient</button>
          {!own.length && <p className="kw-muted small">Leave empty and Stu fills it on save.</p>}</>}
    </div>

    <label className="kw-label">Steps<textarea className="kw-input" rows={Math.min(8, Math.max(3, steps.split("\n").length + 1))} aria-label={`Steps for ${label}`} placeholder={ready ? "e.g. Reheat until hot all the way through" : "One step per line — or leave empty for Stu"} value={steps} onChange={e => { setSteps(e.target.value); onMeal(setDishSteps(meal, dish.id, e.target.value)); }} /></label>

    {recipe
      ? <p className="kw-dish-time">{recipe.activeMinutes} min active · from the recipe</p>
      : <label className="kw-label kw-dish-time-field">Prep time (min)<input className="kw-input" type="number" min="0" placeholder={ready ? "reheat" : "Stu fills"} value={dish.activeMinutes ?? ""} onChange={e => { const value = e.target.value === "" ? undefined : Number(e.target.value); set({ activeMinutes: value, elapsedMinutes: value === undefined ? undefined : Math.max(value, dish.elapsedMinutes ?? 0) }); }} /></label>}
  </section>;
}
