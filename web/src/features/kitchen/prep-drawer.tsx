"use client";
import { X } from "@phosphor-icons/react";
import { useState } from "react";
import { api } from "@/lib/api";
import { demoComposition, type ComposedDish } from "./basket";
import { Drawer } from "./drawer";
import { foodEmoji } from "./food-art";
import { addToPrep, fridgePrepTask, nextWeekStart } from "./prep-from-fridge";
import type { InventoryItem, KitchenState, PageProps, PrepTask } from "./types";

interface Props { state: KitchenState; foods: InventoryItem[]; demo: boolean; send: PageProps["send"]; today: string; onClose: () => void; onAdded: () => void; onPrepDay?: (week: string) => void }

/** The weekend day a week's prep belongs to, as the Prep page counts it. */
function prepDayOf(week: string, prepDay: number) {
  const day = new Date(`${week}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() - 7 + prepDay);
  return day.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}

/** 🔪 + Prep: one dish for this weekend's prep day from the chosen fridge
 * foods. Stu names it and writes the amounts, steps and time (or a recipe
 * does); the household changes anything, and it goes on prep day. It is not
 * saved to the recipe book. */
export function PrepFromFridge({ state, foods, demo, send, today, onClose, onAdded, onPrepDay }: Props) {
  const [note, setNote] = useState(""), [composing, setComposing] = useState(false), [error, setError] = useState("");
  const [task, setTask] = useState<PrepTask | null>(null), [saving, setSaving] = useState(false);
  const [added, setAdded] = useState<{ name: string; week: string } | null>(null);
  const change = (patch: Partial<PrepTask>) => setTask(current => current && { ...current, ...patch });
  const recipes = state.recipes.filter(r => !r.incomplete);
  const starting = (): ComposedDish["uses"] => task?.inputs ?? foods.map(food => ({ inventoryId: food.id, portions: Math.min(food.portions, 1) }));

  async function compose() {
    setComposing(true); setError("");
    try {
      const dish = demo ? demoComposition(foods, "dinner", state.settings.people) : await api<ComposedDish>("/api/v1/kitchen/compose", { method: "POST", body: JSON.stringify({ inventoryIds: foods.map(food => food.id), note: note.trim() }) });
      setTask(fridgePrepTask(dish));
    } catch (e) { setError(e instanceof Error ? e.message : "Stu could not make a dish. Please try again."); } finally { setComposing(false); }
  }
  function pickRecipe(id: string) {
    const recipe = recipes.find(r => r.id === id);
    if (recipe) setTask(fridgePrepTask({ recipe, uses: starting() }, recipe.id));
  }
  const valid = !!task && !!task.name.trim() && task.inputs.length > 0 && task.inputs.every(use => { const food = state.inventory.find(item => item.id === use.inventoryId); return Number.isFinite(use.portions) && use.portions > 0 && use.portions <= (food?.portions ?? 0); }) && task.elapsedMinutes > 0 && task.elapsedMinutes >= task.activeMinutes;
  async function add() {
    if (!task || !valid || saving) return;
    setSaving(true); setError("");
    try {
      const week = await addToPrep(state, { ...task, name: task.name.trim(), steps: task.steps.map(step => step.trim()).filter(Boolean) }, send, today);
      if (week) { setAdded({ name: task.name.trim(), week }); onAdded(); } else setError("Could not add it to prep day. Please try again.");
    } finally { setSaving(false); }
  }

  const recipePicker = <label className="kw-label">Or use a recipe<select className="kw-input" value={task?.recipeId ?? ""} onChange={e => pickRecipe(e.target.value)}><option value="">{task && !task.recipeId ? "Stu’s dish" : "Choose a recipe…"}</option>{recipes.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>;

  const footer = added
    ? <>{onPrepDay && <button type="button" className="kw-button" onClick={() => onPrepDay(added.week)}>Open prep day</button>}<button type="button" className="kw-button secondary" onClick={onClose}>Close</button></>
    : task ? <><button type="button" className="kw-button" disabled={!valid || saving} onClick={() => void add()}>{saving ? "Adding…" : "Add to prep day"}</button><button type="button" className="kw-button secondary" onClick={() => setTask(null)}>Back</button></> : null;

  return <Drawer title="🔪 + Prep" subtitle={`Prep day · ${prepDayOf(nextWeekStart(today), state.settings.prepDay)}`} onClose={onClose} footer={footer}>
    {added ? <p className="kw-prep-added" role="status">✓ {added.name} is on prep day, {prepDayOf(added.week, state.settings.prepDay)}.</p>
      : !task ? <div className="kw-basket">
        <ul className="kw-prep-picked" aria-label="Chosen foods">{foods.map(food => <li key={food.id}><span aria-hidden="true">{food.emoji ?? foodEmoji(food.name, food.type)}</span>{food.name}<small>{food.portions} left</small></li>)}</ul>
        <label className="kw-label">Anything Stu should know?<input className="kw-input" value={note} maxLength={1000} placeholder="e.g. soft for the baby, keeps well frozen" onChange={e => setNote(e.target.value)} /></label>
        {error && <p className="kw-error" role="alert">{error}</p>}
        <div className="kw-basket-actions"><button type="button" className="kw-button" disabled={composing} onClick={() => void compose()}>{composing ? "Stu is making a dish…" : `✨ Make a dish from ${foods.length} ${foods.length === 1 ? "food" : "foods"}`}</button></div>
        {recipePicker}
      </div>
      : <div className="kw-edit-form">
        <label className="kw-label">Dish name<input className="kw-input" value={task.name} onChange={e => change({ name: e.target.value })} /></label>
        <fieldset className="kw-basket-uses"><legend>From your fridge</legend>{task.inputs.map(use => {
          const food = state.inventory.find(item => item.id === use.inventoryId);
          return <div className="kw-basket-use" key={use.inventoryId}><span aria-hidden="true">{food?.emoji ?? foodEmoji(food?.name ?? "", food?.type)}</span><label className="kw-label">{food?.name ?? "Missing food"}<input className="kw-input" required type="number" min="0.25" step="0.25" max={food?.portions} value={use.portions} aria-label={`Portions of ${food?.name ?? "food"}`} onChange={e => change({ inputs: task.inputs.map(u => u.inventoryId === use.inventoryId ? { ...u, portions: e.target.valueAsNumber } : u) })} /></label><small>of {food?.portions ?? 0} left</small><button type="button" className="kw-icon" aria-label={`Leave out ${food?.name ?? "food"}`} disabled={task.inputs.length === 1} onClick={() => change({ inputs: task.inputs.filter(u => u !== use) })}><X size={14} /></button></div>;
        })}</fieldset>
        <label className="kw-label">Steps<textarea className="kw-input" rows={Math.min(8, task.steps.length + 2)} placeholder="One step per line" value={task.steps.join("\n")} onChange={e => change({ steps: e.target.value.split("\n") })} /></label>
        <div className="kw-form-grid"><label className="kw-label">Active minutes<input className="kw-input" type="number" min="0" value={task.activeMinutes} onChange={e => change({ activeMinutes: e.target.valueAsNumber })} /></label><label className="kw-label">Total minutes<input className="kw-input" type="number" min={task.activeMinutes} value={task.elapsedMinutes} onChange={e => change({ elapsedMinutes: e.target.valueAsNumber })} /></label></div>
        {recipePicker}
        {!task.recipeId && <p className="kw-muted small">Kept with prep day only; not saved to your recipe book.</p>}
        {error && <p className="kw-error" role="alert">{error}</p>}
      </div>}
  </Drawer>;
}
