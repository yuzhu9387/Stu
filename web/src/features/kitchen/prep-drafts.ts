"use client";
import { useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { demoComposition, type ComposedDish } from "./basket";
import { uid } from "./data";
import { fridgePrepTask } from "./prep-from-fridge";
import type { FoodType, InventoryItem, PrepTask, Recipe } from "./types";

/** A fridge food as a draft remembers it, for showing and for asking again. */
export interface DraftFood { id: string; name: string; type: FoodType; portions: number; emoji?: string }

/** A + Prep dish on its way: Stu making it, ready for the household to review,
 * or failed (try again). Added to prep day or discarded, it is gone. */
export interface PrepDraft { id: string; foods: DraftFood[]; note: string; status: "making" | "ready" | "failed"; task?: PrepTask; error?: string }

const NONE: PrepDraft[] = [];
const INTERRUPTED = "The page closed while Stu was making this dish.";
/** In the demo Stu takes a moment, as the real one does. */
const DEMO_MOMENT = 400;

/** The drafts of one kitchen (the demo's or the household's), kept on this
 * device. Stu keeps working when the drawer or the page is closed; a dish
 * still being made when the whole page reloads comes back as "try again". */
class PrepDrafts {
  private drafts: PrepDraft[] = NONE;
  private listeners = new Set<() => void>();
  constructor(private key: string, private demo: boolean) {
    try {
      const saved = JSON.parse(localStorage.getItem(key) ?? "[]") as PrepDraft[];
      if (Array.isArray(saved)) this.drafts = saved.map(d => d.status === "making" ? { ...d, status: "failed", error: INTERRUPTED } : d);
    } catch { this.drafts = NONE; }
  }
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  snapshot = () => this.drafts;
  private set(next: PrepDraft[]) {
    this.drafts = next;
    try { localStorage.setItem(this.key, JSON.stringify(next)); } catch { /* a full or blocked store keeps them for this page only */ }
    this.listeners.forEach(listener => listener());
  }
  private patch(id: string, change: Partial<PrepDraft>) {
    if (this.drafts.some(d => d.id === id)) this.set(this.drafts.map(d => d.id === id ? { ...d, ...change } : d));
  }
  /** Ask Stu for a dish from these foods; returns the new draft's id at once. */
  make(foods: InventoryItem[], note: string, people: number): string {
    const id = uid();
    this.set([...this.drafts, { id, foods: foods.map(f => ({ id: f.id, name: f.name, type: f.type, portions: f.portions, ...(f.emoji ? { emoji: f.emoji } : {}) })), note, status: "making" }]);
    void this.compose(id, people);
    return id;
  }
  /** A dish from a recipe instead: nothing to wait for. */
  fromRecipe(foods: InventoryItem[], recipe: Recipe): string {
    const id = uid();
    const uses = foods.map(food => ({ inventoryId: food.id, portions: Math.min(food.portions, 1) }));
    this.set([...this.drafts, { id, foods: foods.map(f => ({ id: f.id, name: f.name, type: f.type, portions: f.portions })), note: "", status: "ready", task: fridgePrepTask({ recipe, uses }, recipe.id) }]);
    return id;
  }
  retry(id: string, people: number) {
    this.patch(id, { status: "making", error: undefined });
    void this.compose(id, people);
  }
  update(id: string, task: PrepTask) { this.patch(id, { task }); }
  remove(id: string) { this.set(this.drafts.filter(d => d.id !== id)); }
  private async compose(id: string, people: number) {
    const draft = this.drafts.find(d => d.id === id);
    if (!draft) return;
    try {
      const dish = this.demo
        ? await new Promise<ComposedDish>(resolve => setTimeout(() => resolve(demoComposition(draft.foods.map(f => ({ ...f, location: "", prepared: false, addedOn: "", priority: false })), "dinner", people)), DEMO_MOMENT))
        : await api<ComposedDish>("/api/v1/kitchen/compose", { method: "POST", body: JSON.stringify({ inventoryIds: draft.foods.map(f => f.id), note: draft.note }) });
      this.patch(id, { status: "ready", task: fridgePrepTask(dish), error: undefined });
    } catch (e) {
      this.patch(id, { status: "failed", error: e instanceof Error ? e.message : "Stu could not make a dish. Please try again." });
    }
  }
}

let stores = new Map<string, PrepDrafts>();

export function prepDrafts(demo: boolean): PrepDrafts {
  const key = `stu-prep-drafts:${demo ? "demo" : "home"}`;
  let store = stores.get(key);
  if (!store) { store = new PrepDrafts(key, demo); stores.set(key, store); }
  return store;
}

/** Read the drafts from this device again, as a new page load does. */
export function reloadPrepDrafts() { stores = new Map(); }

export function usePrepDrafts(demo: boolean): PrepDraft[] {
  const store = prepDrafts(demo);
  return useSyncExternalStore(store.subscribe, store.snapshot, () => NONE);
}
