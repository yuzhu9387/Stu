"use client";
import { useState } from "react";
import { foodEmoji } from "./food-art";
import type { PageProps, PrepTask, Recipe } from "./types";

/** A prep task's category, read from its recipe (prep has no Dairy; baking is its own). */
function prepType(recipe: Recipe): PrepTask["type"] {
  if (recipe.tags.some(tag => /baking|烘焙/i.test(tag))) return "Baking";
  return recipe.type === "Dairy" ? "Other" : recipe.type;
}

/** Adding to prep day, kept small: pick a dish from the recipes and it is added
 * with the recipe's servings, time and steps; or, for anything else (thaw the
 * beef, wash the greens), just a title and a description. A quick task makes
 * no food, so finishing it puts nothing in the fridge. */
export function AddPrepDialog({ state, plan, send, onClose, onAdded }: {
  state: PageProps["state"]; plan: NonNullable<PageProps["plan"]>; send: PageProps["send"];
  onClose: () => void; onAdded: (id: string) => void;
}) {
  const [mode, setMode] = useState<"dish" | "task">("dish");
  const [query, setQuery] = useState(""), [picked, setPicked] = useState<string | null>(null);
  const [title, setTitle] = useState(""), [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const planned = new Set(plan.prep.filter(t => t.status === "planned").map(t => t.recipeId));
  const needle = query.trim().toLocaleLowerCase();
  const recipes = state.recipes.filter(r => !r.incomplete && (!needle || [r.name, r.nameEn ?? "", ...r.tags].some(v => v.toLocaleLowerCase().includes(needle))));
  const recipe = state.recipes.find(r => r.id === picked);
  const ready = mode === "dish" ? !!recipe : !!title.trim();

  async function add() {
    if (!ready || busy) return;
    const base = { id: crypto.randomUUID(), actualPortions: 0, status: "planned" as const, liked: false, inputs: [], dependencies: [] };
    const task: PrepTask = mode === "dish" && recipe
      ? { ...base, name: recipe.name, type: prepType(recipe), recipeId: recipe.id, plannedPortions: recipe.servings, activeMinutes: recipe.activeMinutes, elapsedMinutes: Math.max(recipe.elapsedMinutes, recipe.activeMinutes), steps: [...recipe.steps], equipment: [...(recipe.equipment ?? [])] }
      : { ...base, name: title.trim(), type: "Other", plannedPortions: 0, activeMinutes: 10, elapsedMinutes: 10, steps: description.split("\n").map(s => s.trim()).filter(Boolean), equipment: [] };
    setBusy(true); setError(null);
    try { if (await send("prep.save", { planId: plan.id, prep: task })) onAdded(task.id); else setError("Unable to add this task. Please try again."); }
    finally { setBusy(false); }
  }

  return <div className="kw-modal-backdrop" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="kw-modal kw-add-prep" role="dialog" aria-modal="true" aria-label="Add prep task">
      <header className="kw-modal-head"><h2>Add prep task</h2><button type="button" className="kw-modal-close" aria-label="Close" onClick={onClose}>✕</button></header>
      <div className="kw-modal-body">
        <div className="kw-add-prep-tabs" role="tablist" aria-label="What to add">
          <button type="button" role="tab" aria-selected={mode === "dish"} className={mode === "dish" ? "is-on" : ""} onClick={() => setMode("dish")}>🍲 From recipes</button>
          <button type="button" role="tab" aria-selected={mode === "task"} className={mode === "task" ? "is-on" : ""} onClick={() => setMode("task")}>📝 Quick task</button>
        </div>
        {mode === "dish" ? <>
          <input className="kw-input" aria-label="Find a dish" placeholder="🔍 Find a dish…" value={query} onChange={e => setQuery(e.target.value)} />
          <div className="kw-add-prep-list" role="listbox" aria-label="Dishes">
            {recipes.map(r => <button type="button" role="option" aria-selected={picked === r.id} key={r.id} className={`kw-add-prep-dish ${picked === r.id ? "is-on" : ""}`} onClick={() => setPicked(r.id)}>
              <span className="kw-add-prep-emoji" aria-hidden="true">{foodEmoji(r.name, r.type)}</span>
              <span><strong>{r.name}</strong><small>{r.type} · {r.activeMinutes} min · {r.servings} servings{planned.has(r.id) ? " · already on prep day" : ""}</small></span>
            </button>)}
            {!recipes.length && <p className="kw-muted">No dish matches. Add it as a quick task instead.</p>}
          </div>
        </> : <>
          <label className="kw-label">Title<input className="kw-input" autoFocus placeholder="e.g. Thaw the beef" value={title} onChange={e => setTitle(e.target.value)} /></label>
          <label className="kw-label">Description<textarea className="kw-input" rows={4} placeholder="One step per line" value={description} onChange={e => setDescription(e.target.value)} /></label>
        </>}
        {error && <p className="kw-inline-error" role="alert">{error}</p>}
        <footer className="kw-add-prep-actions"><button type="button" className="kw-button secondary" onClick={onClose}>Cancel</button><button type="button" className="kw-button kw-yellow" disabled={!ready || busy} onClick={() => void add()}>{busy ? "Adding…" : mode === "dish" ? "Add dish" : "Add task"}</button></footer>
      </div>
    </section>
  </div>;
}
