"use client";
import { X } from "@phosphor-icons/react";
import { useState } from "react";
import { Drawer } from "./drawer";
import { foodEmoji } from "./food-art";
import { prepDrafts, usePrepDrafts, type PrepDraft } from "./prep-drafts";
import { addToPrep, fridgePrepTask, nextWeekStart } from "./prep-from-fridge";
import type { InventoryItem, KitchenState, PageProps, PrepTask } from "./types";

/** What the + Prep drawer shows: foods just chosen, all dishes on their way,
 * or one of them to review. */
export type PrepView = { kind: "new"; foods: InventoryItem[] } | { kind: "list" } | { kind: "review"; id: string };

interface Props { state: KitchenState; demo: boolean; send: PageProps["send"]; view: PrepView; onView: (view: PrepView | null) => void; onStarted: () => void; onPrepDay?: (week: string) => void }

const today = (timezone: string) => new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());

/** The weekend day a week's prep belongs to, as the Prep page counts it. */
function prepDayOf(week: string, prepDay: number) {
  const day = new Date(`${week}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() - 7 + prepDay);
  return day.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}

const foodsLine = (draft: PrepDraft) => draft.foods.map(f => f.name).join(" · ");

/** 🔪 + Prep: dishes for this weekend's prep day from fridge foods. Stu makes
 * each one in the background (several at once, drawer open or closed); the
 * household reviews it, changes anything, and adds it to prep day or
 * discards it. A dish Stu makes is not saved to the recipe book. */
export function PrepDrawer({ state, demo, send, view, onView, onStarted, onPrepDay }: Props) {
  const drafts = usePrepDrafts(demo), store = prepDrafts(demo);
  const [note, setNote] = useState(""), [saving, setSaving] = useState(false), [error, setError] = useState("");
  const [added, setAdded] = useState<{ name: string; week: string } | null>(null);
  const recipes = state.recipes.filter(r => !r.incomplete);
  const day = prepDayOf(nextWeekStart(today(state.settings.timezone)), state.settings.prepDay);
  const close = () => onView(null);
  const draft = view.kind === "review" ? drafts.find(d => d.id === view.id) : undefined;
  const task = draft?.task;
  const change = (patch: Partial<PrepTask>) => { if (draft?.task) store.update(draft.id, { ...draft.task, ...patch }); };

  function make(foods: InventoryItem[]) {
    store.make(foods, note.trim(), state.settings.people);
    setNote(""); setAdded(null); onStarted(); onView({ kind: "list" });
  }
  function pickRecipe(id: string) {
    const recipe = recipes.find(r => r.id === id);
    if (!recipe) return;
    if (view.kind === "new") { const made = store.fromRecipe(view.foods, recipe); onStarted(); onView({ kind: "review", id: made }); }
    else if (draft?.task) store.update(draft.id, fridgePrepTask({ recipe, uses: draft.task.inputs }, recipe.id));
  }
  const valid = !!task && !!task.name.trim() && task.inputs.length > 0 && task.inputs.every(use => { const food = state.inventory.find(item => item.id === use.inventoryId); return Number.isFinite(use.portions) && use.portions > 0 && use.portions <= (food?.portions ?? 0); }) && task.elapsedMinutes > 0 && task.elapsedMinutes >= task.activeMinutes;
  async function add() {
    if (!draft || !task || !valid || saving) return;
    setSaving(true); setError("");
    try {
      const week = await addToPrep(state, { ...task, name: task.name.trim(), steps: task.steps.map(step => step.trim()).filter(Boolean) }, send, today(state.settings.timezone));
      if (week) { store.remove(draft.id); setAdded({ name: task.name.trim(), week }); onView({ kind: "list" }); } else setError("Could not add it to prep day. Please try again.");
    } finally { setSaving(false); }
  }
  const discard = (id: string) => { store.remove(id); if (view.kind === "review") onView({ kind: "list" }); };

  const recipePicker = <label className="kw-label">Or use a recipe<select className="kw-input" value={task?.recipeId ?? ""} onChange={e => pickRecipe(e.target.value)}><option value="">{task && !task.recipeId ? "Stu’s dish" : "Choose a recipe…"}</option>{recipes.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>;

  let body, footer;
  if (view.kind === "new") {
    const foods = view.foods;
    body = <div className="kw-basket">
      <ul className="kw-prep-picked" aria-label="Chosen foods">{foods.map(food => <li key={food.id}><span aria-hidden="true">{food.emoji ?? foodEmoji(food.name, food.type)}</span>{food.name}<small>{food.portions} left</small></li>)}</ul>
      <label className="kw-label">Anything Stu should know?<input className="kw-input" value={note} maxLength={1000} placeholder="e.g. soft for the baby, keeps well frozen" onChange={e => setNote(e.target.value)} /></label>
      <div className="kw-basket-actions"><button type="button" className="kw-button" onClick={() => make(foods)}>{`✨ Make a dish from ${foods.length} ${foods.length === 1 ? "food" : "foods"}`}</button></div>
      <p className="kw-muted small">Stu makes it in the background; close this and choose more foods if you like.</p>
      {recipePicker}
    </div>;
    footer = <button type="button" className="kw-button secondary" onClick={() => onView(drafts.length ? { kind: "list" } : null)}>{drafts.length ? "See dishes on their way" : "Cancel"}</button>;
  } else if (view.kind === "review" && draft && task) {
    body = <div className="kw-edit-form">
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
    </div>;
    footer = <><button type="button" className="kw-button" disabled={!valid || saving} onClick={() => void add()}>{saving ? "Adding…" : "Add to prep day"}</button><button type="button" className="kw-button secondary" onClick={() => discard(draft.id)}>Discard</button><button type="button" className="kw-text-button" onClick={() => onView({ kind: "list" })}>← All dishes</button></>;
  } else {
    body = <>
      {added && <p className="kw-prep-added" role="status">✓ {added.name} is on prep day, {prepDayOf(added.week, state.settings.prepDay)}.</p>}
      {drafts.length ? <ul className="kw-prep-drafts">{drafts.map(d => <li key={d.id} className={`kw-prep-draft is-${d.status}`}>
        <div className="kw-prep-draft-body">
          <span className="kw-prep-draft-foods"><span aria-hidden="true">{d.foods.map(f => f.emoji ?? foodEmoji(f.name, f.type)).join("")}</span> {foodsLine(d)}</span>
          {d.status === "making" && <span className="kw-prep-draft-status"><span className="kw-spinner" aria-hidden="true" />Stu is making a dish…</span>}
          {d.status === "ready" && d.task && <button type="button" className="kw-prep-draft-review" aria-label={`Review ${d.task.name}`} onClick={() => onView({ kind: "review", id: d.id })}><strong>{d.task.name}</strong><span aria-hidden="true">Review →</span></button>}
          {d.status === "failed" && <><span className="kw-prep-draft-status kw-error">{d.error}</span><button type="button" className="kw-text-button" onClick={() => store.retry(d.id, state.settings.people)}>Try again</button></>}
        </div>
        <button type="button" className="kw-icon" aria-label={`Discard ${d.task?.name ?? foodsLine(d)}`} onClick={() => discard(d.id)}><X size={14} /></button>
      </li>)}</ul> : !added && <p className="kw-empty">No dishes on their way. Hold foods in the fridge to choose them, then tap 🔪 + Prep.</p>}
    </>;
    footer = <>{onPrepDay && <button type="button" className="kw-button" onClick={() => onPrepDay(nextWeekStart(today(state.settings.timezone)))}>Open prep day →</button>}<button type="button" className="kw-button secondary" onClick={close}>Close</button></>;
  }

  return <Drawer title="🔪 + Prep" subtitle={`Prep day · ${day}`} onClose={close} footer={footer}>{body}</Drawer>;
}
