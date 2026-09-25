"use client";
import { useState } from "react";
import type { FoodType, MealSlot, Recipe } from "./types";

/** Where a recipe came from: an uploaded image is shown, anything else as text. */
export function RecipeSource({ source }: { source: string }) {
  if (source.startsWith("data:image/")) {
    // Uploaded data URLs are already bounded and kept locally; Next image optimization is unnecessary.
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="kw-support-source-image" src={source} alt="Original uploaded recipe" />;
  }
  return <p className="kw-muted kw-support-source">Source: {source || "Not recorded"}</p>;
}

const foodTypes: FoodType[] = ["Protein", "Carbs", "Vegetables", "Dairy", "Other"];

export const blankRecipe = (): Recipe => ({ id: crypto.randomUUID(), name: "", type: "Other", mealTypes: ["dinner"], tags: [], servings: 3, activeMinutes: 15, elapsedMinutes: 20, ingredients: [{ name: "", quantity: 1, unit: "portion" }], steps: [""], liked: false, source: "Manual" });

/** The recipe form, used on a recipe's own page (edit) and for a new recipe. */
export function RecipeEditor({ initial, tags, save, cancel, title = "Edit recipe" }: { initial: Recipe; tags: string[]; save: (recipe: Recipe) => Promise<boolean>; cancel: () => void; title?: string }) {
  const [recipe, setRecipe] = useState<Recipe>(structuredClone(initial));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const update = (patch: Partial<Recipe>) => setRecipe(r => ({ ...r, ...patch }));
  return <form className="kw-card kw-support-editor" onSubmit={async e => { e.preventDefault(); setError(""); if (recipe.elapsedMinutes < recipe.activeMinutes) { setError("Elapsed time must include all active time."); return; } if (!recipe.mealTypes.length || !recipe.ingredients.length || !recipe.steps.some(s => s.trim())) { setError("Choose a meal, add an ingredient and include at least one step."); return; } setBusy(true); try { if (await save({ ...recipe, name: recipe.name.trim(), steps: recipe.steps.map(s => s.trim()).filter(Boolean), incomplete: false })) cancel(); } finally { setBusy(false); } }}>
    <div className="kw-row"><h2>{title}</h2><button className="kw-button" type="button" onClick={cancel}>Cancel</button></div>
    <div className="kw-form-grid"><label className="kw-label">Recipe name<input autoFocus className="kw-input" required value={recipe.name} onChange={e => update({ name: e.target.value })} /></label><label className="kw-label">Type<select className="kw-input" value={recipe.type} onChange={e => update({ type: e.target.value as FoodType })}>{foodTypes.map(t => <option key={t}>{t}</option>)}</select></label>
      {([ ["servings", "Servings", 0.25], ["activeMinutes", "Active minutes", 0], ["elapsedMinutes", "Elapsed minutes", 0] ] as const).map(([key, label, min]) => <label className="kw-label" key={key}>{label}<input className="kw-input" required type="number" min={min} step={key === "servings" ? "0.25" : "1"} value={recipe[key]} onChange={e => update({ [key]: e.target.valueAsNumber })} /></label>)}
    </div><fieldset className="kw-support-fieldset"><legend>Meals</legend>{(["breakfast", "lunch", "dinner"] as MealSlot[]).map(slot => <label key={slot}><input type="checkbox" checked={recipe.mealTypes.includes(slot)} onChange={e => update({ mealTypes: e.target.checked ? [...recipe.mealTypes, slot] : recipe.mealTypes.filter(s => s !== slot) })} />{slot}</label>)}</fieldset>
    {!!tags.length && <fieldset className="kw-support-fieldset"><legend>Tags</legend>{tags.map(tag => <label key={tag}><input type="checkbox" checked={recipe.tags.includes(tag)} onChange={e => update({ tags: e.target.checked ? [...recipe.tags, tag] : recipe.tags.filter(t => t !== tag) })} />{tag}</label>)}</fieldset>}
    <h3>Ingredients</h3>{recipe.ingredients.map((ingredient, index) => <div className="kw-support-ingredient" key={index}><label className="kw-label">Ingredient<input className="kw-input" required value={ingredient.name} onChange={e => update({ ingredients: recipe.ingredients.map((item, i) => i === index ? { ...item, name: e.target.value } : item) })} /></label><label className="kw-label">Quantity<input className="kw-input" required type="number" min="0.01" step="any" value={ingredient.quantity} onChange={e => update({ ingredients: recipe.ingredients.map((item, i) => i === index ? { ...item, quantity: e.target.valueAsNumber } : item) })} /></label><label className="kw-label">Unit<input className="kw-input" required value={ingredient.unit} onChange={e => update({ ingredients: recipe.ingredients.map((item, i) => i === index ? { ...item, unit: e.target.value } : item) })} /></label><button type="button" className="kw-button" aria-label={`Remove ingredient ${index + 1}`} onClick={() => update({ ingredients: recipe.ingredients.filter((_, i) => i !== index) })}>Remove</button></div>)}<button type="button" className="kw-button" onClick={() => update({ ingredients: [...recipe.ingredients, { name: "", quantity: 1, unit: "g" }] })}>Add ingredient</button>
    <label className="kw-label kw-support-spaced">Steps (one per line)<textarea className="kw-input" required rows={5} value={recipe.steps.join("\n")} onChange={e => update({ steps: e.target.value.split("\n") })} /></label>
    <div className="kw-form-grid"><label className="kw-label">Allergens (comma separated)<input className="kw-input" value={(recipe.allergens || []).join(",")} onChange={e => update({ allergens: e.target.value.split(",") })} /></label><label className="kw-label">Equipment (comma separated)<input className="kw-input" value={(recipe.equipment || []).join(",")} onChange={e => update({ equipment: e.target.value.split(",") })} /></label></div>
    {recipe.source.startsWith("data:image/") ? <div className="kw-support-source"><span className="kw-label">Original recipe image</span><RecipeSource source={recipe.source}/></div> : <label className="kw-label">Source<textarea className="kw-input" rows={2} value={recipe.source} onChange={e => update({ source: e.target.value })} /></label>}{error && <p className="kw-error" role="alert">{error}</p>}<div className="kw-support-actions"><button className="kw-button kw-primary" disabled={busy || !recipe.name.trim()}>Save recipe</button><label><input type="checkbox" checked={recipe.liked} onChange={e => update({ liked: e.target.checked })} /> Baby liked it</label></div>
  </form>;
}
