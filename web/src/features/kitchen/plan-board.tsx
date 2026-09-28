"use client";
import { useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { uid } from "./data";
import { foodEmoji } from "./food-art";
import { removeComponent, withDish } from "./meal-steps";
import type { InventoryItem, KitchenState, Meal, MealComponent, MealSlot, WeeklyPlan } from "./types";
import "./plan-board.css";

/** What is being moved: a food from the fridge, or a fridge dish already on a meal. */
export type FoodDrag = { kind: "stock"; inventoryId: string } | { kind: "dish"; mealId: string; componentId: string };
/** Where it lands: on a meal, on an empty slot, or back in the fridge. */
export type FoodDrop = { kind: "meal"; mealId: string } | { kind: "slot"; day: string; slot: MealSlot } | { kind: "fridge" };

export const dropKey = (drop: FoodDrop) => drop.kind === "meal" ? `meal:${drop.mealId}` : drop.kind === "slot" ? `slot:${drop.day}:${drop.slot}` : "fridge";
function parseDrop(key: string | null | undefined): FoodDrop | null {
  const [kind, a, b] = (key ?? "").split(":");
  if (kind === "meal" && a) return { kind, mealId: a };
  if (kind === "slot" && a && b) return { kind, day: a, slot: b as MealSlot };
  return kind === "fridge" ? { kind } : null;
}

/** Portions of each fridge food this plan's meals still to eat do not already
 * take. Below zero, the plan asks for more than the fridge has. */
export function freePortions(state: Pick<KitchenState, "inventory">, plan: WeeklyPlan): Map<string, number> {
  const free = new Map(state.inventory.map(item => [item.id, item.portions]));
  const take = (id: string | undefined, portions: number) => { if (id && free.has(id)) free.set(id, free.get(id)! - portions); };
  for (const meal of plan.meals) {
    if (meal.status !== "planned" || meal.included === false) continue;
    for (const c of meal.components) {
      if (!c.prepId) take(c.inventoryId, c.portions);
      c.uses?.forEach(use => take(use.inventoryId, use.portions));
    }
  }
  return free;
}

/** How a fridge food is made ready on the day: a cooked batch is reheated
 * (its recipe says how, when it does); raw food with a recipe follows it. */
function foodSteps(item: InventoryItem, state: Pick<KitchenState, "recipes">): string[] {
  const recipe = state.recipes.find(r => r.id === item.recipeId);
  if (item.prepared) return [recipe?.reheat?.[0]?.instruction ?? "Reheat until hot all the way through, then cool to eating temperature."];
  return recipe?.steps ?? [];
}

/** The meal with one more portion of a fridge food: a dish already served from
 * that batch gets another portion; otherwise the food joins as a new dish. Raw
 * food cooked from its recipe adds that recipe's hands-on time. */
export function withFood(meal: Meal, item: InventoryItem, state: Pick<KitchenState, "recipes">): Meal {
  const existing = meal.components.find(c => c.inventoryId === item.id && !c.prepId);
  if (existing) return { ...meal, components: meal.components.map(c => c === existing ? { ...c, portions: c.portions + 1 } : c) };
  const dish: MealComponent = { id: uid(), name: item.name, type: item.type, portions: 1, inventoryId: item.id, ...(item.recipeId ? { recipeId: item.recipeId } : {}) };
  const next = withDish(meal, dish, foodSteps(item, state));
  const recipe = item.prepared ? undefined : state.recipes.find(r => r.id === item.recipeId);
  if (!recipe) return next;
  const activeMinutes = meal.activeMinutes + recipe.activeMinutes;
  return { ...next, activeMinutes, elapsedMinutes: Math.max(meal.elapsedMinutes, recipe.elapsedMinutes, activeMinutes) };
}

/** A new meal of one fridge food, for an empty slot. */
export function mealOfFood(day: string, slot: MealSlot, item: InventoryItem, state: Pick<KitchenState, "recipes">): Meal {
  const recipe = item.prepared ? undefined : state.recipes.find(r => r.id === item.recipeId);
  const blank: Meal = { id: uid(), day, slot, included: true, components: [], activeMinutes: 0, elapsedMinutes: 0, steps: [], status: "planned", liked: false, locked: false };
  const meal = withFood(blank, item, state);
  return recipe ? meal : { ...meal, activeMinutes: 5, elapsedMinutes: 10 };
}

/** The meal with one portion of a dish taken off; the dish goes (with its
 * steps) at its last portion. `null`: that was the meal's only dish. */
export function withoutOne(meal: Meal, componentId: string): Meal | null {
  const dish = meal.components.find(c => c.id === componentId);
  if (!dish) return meal;
  if (dish.portions - 1 > 1e-9) return { ...meal, components: meal.components.map(c => c === dish ? { ...c, portions: c.portions - 1 } : c) };
  return meal.components.length > 1 ? removeComponent(meal, componentId) : null;
}

const MOUSE_DISTANCE = 6, TOUCH_HOLD = 260, TOUCH_SLOP = 10;

/** Move food by pointer: a mouse drag starts after a few pixels, a touch drag
 * after a short hold (so a swipe still scrolls). A lifted copy follows the
 * pointer; whatever carries `data-food-drop` under it is the target. */
function useFoodDrag(onDrop: (drag: FoodDrag, drop: FoodDrop) => void) {
  const [ghost, setGhost] = useState<{ label: string; x: number; y: number } | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const ghostRef = useRef<HTMLDivElement>(null);
  const point = useRef({ x: 0, y: 0 });
  const dropped = useRef(false);
  const place = () => { const node = ghostRef.current; if (node) node.style.transform = `translate(${point.current.x + 8}px, ${point.current.y + 8}px)`; };
  useLayoutEffect(() => { if (ghost) place(); }, [ghost]);
  const target = (x: number, y: number) => document.elementsFromPoint(x, y).map(node => (node as HTMLElement).closest?.("[data-food-drop]")).find(Boolean)?.getAttribute("data-food-drop") ?? null;

  function start(event: ReactPointerEvent<HTMLElement>, drag: FoodDrag, label: string) {
    if (event.button !== 0) return;
    dropped.current = false;
    const kind = event.pointerType, origin = { x: event.clientX, y: event.clientY };
    let active = false, hold = 0;
    const activate = (x: number, y: number) => { active = true; point.current = { x, y }; document.body.classList.add("kw-dragging"); setGhost({ label, x, y }); };
    const move = (e: PointerEvent) => {
      if (!active) {
        const distance = Math.hypot(e.clientX - origin.x, e.clientY - origin.y);
        if (kind === "mouse" && distance > MOUSE_DISTANCE) activate(e.clientX, e.clientY);
        else if (kind !== "mouse" && distance > TOUCH_SLOP) stop();
        if (!active) return;
      }
      point.current = { x: e.clientX, y: e.clientY };
      place();
      setOver(target(e.clientX, e.clientY));
    };
    const touchmove = (e: TouchEvent) => { if (active) e.preventDefault(); };
    const finish = (keep: boolean) => {
      const was = active; stop();
      if (!was) return;
      document.body.classList.remove("kw-dragging");
      const drop = keep ? parseDrop(target(point.current.x, point.current.y)) : null;
      setGhost(null); setOver(null);
      if (drop) { dropped.current = true; onDrop(drag, drop); }
    };
    const up = () => finish(true), cancel = () => finish(false);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") cancel(); };
    function stop() {
      window.clearTimeout(hold);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("touchmove", touchmove);
      window.removeEventListener("keydown", key);
    }
    if (kind !== "mouse") hold = window.setTimeout(() => activate(origin.x, origin.y), TOUCH_HOLD);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("touchmove", touchmove, { passive: false });
    window.addEventListener("keydown", key);
  }
  /** A click that ended a drag is not a click. */
  const clicked = () => { const drag = dropped.current; dropped.current = false; return !drag; };
  const ghostNode = ghost ? <div ref={ghostRef} className="kw-food-ghost" aria-hidden="true">{ghost.label}</div> : null;
  return { start, clicked, over, ghostNode };
}

/** What the calendar needs to take food: drop targets, a tap-to-place choice,
 * and a dish's fridge food to drag off or take one portion of. */
export interface CalendarBoard {
  picked: InventoryItem | null;
  over: string | null;
  onPlace: (drop: FoodDrop) => void;
  onTakeOne: (meal: Meal, componentId: string) => void;
  onDragDish: (event: ReactPointerEvent<HTMLElement>, meal: Meal, component: MealComponent) => void;
}

interface Save { save: (meal: Meal, note: string) => Promise<unknown>; remove: (meal: Meal, note: string) => Promise<unknown> }

/** The plan board: the fridge beside the week. Food dragged (or tapped, then
 * placed) onto a meal adds a portion; a dish dragged back to the fridge, or
 * its "−", takes one off. Each change saves the meal. */
export function usePlanBoard(state: KitchenState, plan: WeeklyPlan | null, { save, remove }: Save) {
  const [pickedId, setPickedId] = useState<string | null>(null);
  const free = plan ? freePortions(state, plan) : new Map<string, number>();
  const picked = state.inventory.find(item => item.id === pickedId && (free.get(item.id) ?? 0) > 0) ?? null;
  const stored = (id: string) => plan?.meals.find(meal => meal.id === id);

  async function add(item: InventoryItem, drop: FoodDrop) {
    if (!plan || drop.kind === "fridge") return;
    if (drop.kind === "meal") { const meal = stored(drop.mealId); if (meal && meal.status === "planned" && !meal.locked) await save(withFood(meal, item, state), `${item.name} +1`); return; }
    if (plan.meals.some(m => m.day === drop.day && m.slot === drop.slot)) return;
    await save(mealOfFood(drop.day, drop.slot, item, state), `${item.name} added`);
  }
  async function takeOne(meal: Meal, componentId: string) {
    const current = stored(meal.id), dish = current?.components.find(c => c.id === componentId);
    if (!current || !dish) return;
    const next = withoutOne(current, componentId);
    await (next ? save(next, `${dish.name} −1`) : remove(current, `${dish.name} back in the fridge`));
  }
  const drag = useFoodDrag((what, drop) => {
    if (what.kind === "stock") {
      const item = state.inventory.find(i => i.id === what.inventoryId);
      if (item && (free.get(item.id) ?? 0) > 0) void add(item, drop);
      return;
    }
    const from = stored(what.mealId), dish = from?.components.find(c => c.id === what.componentId);
    const item = state.inventory.find(i => i.id === dish?.inventoryId);
    if (!from || !dish || (drop.kind === "meal" && drop.mealId === from.id)) return;
    // Moved to another meal: that meal gets the portion this one gives up.
    void takeOne(from, dish.id).then(() => { if (item) return add(item, drop); });
  });

  const calendar: CalendarBoard = {
    picked, over: drag.over,
    onPlace: drop => { if (picked) void add(picked, drop); },
    onTakeOne: (meal, componentId) => void takeOne(meal, componentId),
    onDragDish: (event, meal, component) => drag.start(event, { kind: "dish", mealId: meal.id, componentId: component.id }, `${foodEmoji(component.name, component.type)} ${component.name}`),
  };
  const rail = { state, free, pickedId: picked?.id ?? null, over: drag.over, onPick: (id: string) => { if (drag.clicked()) setPickedId(current => current === id ? null : id); }, onDragFood: (event: ReactPointerEvent<HTMLElement>, item: InventoryItem) => drag.start(event, { kind: "stock", inventoryId: item.id }, `${item.emoji ?? foodEmoji(item.name, item.type)} ${item.name}`) };
  return { calendar, rail, ghost: drag.ghostNode };
}

const PLACES: [string, string][] = [["fridge", "冷藏 Fridge"], ["freezer", "冷冻 Freezer"]];

/** The fridge beside the week: each food with the portions this week's plan
 * has not taken yet. */
export function FridgeRail({ state, free, pickedId, over, onPick, onDragFood }: ReturnType<typeof usePlanBoard>["rail"]) {
  const foods = state.inventory.filter(item => item.portions > 0);
  const place = (item: InventoryItem) => item.location.trim().toLocaleLowerCase();
  const others = [...new Set(foods.map(place))].filter(key => !PLACES.some(([p]) => p === key)).map(key => [key, key.charAt(0).toUpperCase() + key.slice(1)] as [string, string]);
  const picked = foods.find(item => item.id === pickedId);
  return <aside className={`kw-board-fridge ${over === "fridge" ? "is-drop-over" : ""}`} data-food-drop="fridge" aria-label="Fridge for this week">
    <header><h2>🧊 In the fridge</h2><p>{picked ? `Now tap a meal to add ${picked.name}, or tap it again to stop.` : "Drag food onto a meal, or tap it and then a meal. Drag a dish back here to take it off."}</p></header>
    <div className="kw-board-shelves">{[...PLACES, ...others].map(([key, label]) => {
      const items = foods.filter(item => place(item) === key).sort((a, b) => Number(b.priority) - Number(a.priority) || (a.expiresOn ?? "9999").localeCompare(b.expiresOn ?? "9999") || a.name.localeCompare(b.name));
      if (!items.length) return null;
      return <section key={key} aria-label={label}><h3>{label}</h3><ul>{items.map(item => {
        const left = Math.max(0, Math.round((free.get(item.id) ?? 0) * 100) / 100);
        return <li key={item.id}><button type="button" className="kw-board-food" aria-pressed={pickedId === item.id} disabled={left <= 0} aria-label={`${item.name}, ${left} of ${item.portions} left`} onPointerDown={event => { if (left > 0) onDragFood(event, item); }} onClick={() => onPick(item.id)}>
          <span aria-hidden="true">{item.emoji ?? foodEmoji(item.name, item.type)}</span><strong>{item.name}</strong><small>{left} / {item.portions} left</small>
        </button></li>;
      })}</ul></section>;
    })}</div>
    {!foods.length && <p className="kw-empty">The fridge is empty. Add food in Fridge first.</p>}
  </aside>;
}
