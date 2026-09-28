"use client";
import { useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { AlsoMark } from "./also-contains";
import { useStored } from "./browser-store";
import { uid } from "./data";
import { foodEmoji } from "./food-art";
import { withDish } from "./meal-steps";
import type { FoodType, InventoryItem, KitchenState, Meal, MealComponent, MealSlot, WeeklyPlan } from "./types";
import "./plan-board.css";

/** Where a fridge food lands: on a meal, or on an empty slot. */
export type FoodDrop = { kind: "meal"; mealId: string } | { kind: "slot"; day: string; slot: MealSlot };

function parseDrop(key: string | null | undefined): FoodDrop | null {
  const [kind, a, b] = (key ?? "").split(":");
  if (kind === "meal" && a) return { kind, mealId: a };
  return kind === "slot" && a && b ? { kind, day: a, slot: b as MealSlot } : null;
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

const MOUSE_DISTANCE = 6, TOUCH_HOLD = 260, TOUCH_SLOP = 10;

/** Move food by pointer: a mouse drag starts after a few pixels, a touch drag
 * after a short hold (so a swipe still scrolls). A lifted copy follows the
 * pointer; whatever carries `data-food-drop` under it is the target. */
function useFoodDrag(onDrop: (item: InventoryItem, drop: FoodDrop) => void) {
  const [ghost, setGhost] = useState<{ label: string; x: number; y: number } | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const ghostRef = useRef<HTMLDivElement>(null);
  const point = useRef({ x: 0, y: 0 });
  const dropped = useRef(false);
  const place = () => { const node = ghostRef.current; if (node) node.style.transform = `translate(${point.current.x + 8}px, ${point.current.y + 8}px)`; };
  useLayoutEffect(() => { if (ghost) place(); }, [ghost]);
  const target = (x: number, y: number) => document.elementsFromPoint(x, y).map(node => (node as HTMLElement).closest?.("[data-food-drop]")).find(Boolean)?.getAttribute("data-food-drop") ?? null;

  function start(event: ReactPointerEvent<HTMLElement>, item: InventoryItem, label: string) {
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
      if (drop) { dropped.current = true; onDrop(item, drop); }
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

/** What the calendar needs to take food: drop targets, and the food picked
 * in the fridge that a tap on a meal or empty slot places. */
export interface CalendarBoard {
  picked: InventoryItem | null;
  over: string | null;
  onPlace: (drop: FoodDrop) => void;
}

/** The plan board: the fridge beside the week. Food dragged (or tapped, then
 * placed) onto a meal adds a portion; onto an empty slot, it makes a meal.
 * Each change saves the meal. */
export function usePlanBoard(state: KitchenState, plan: WeeklyPlan | null, save: (meal: Meal, note: string) => Promise<unknown>) {
  const [pickedId, setPickedId] = useState<string | null>(null);
  const free = plan ? freePortions(state, plan) : new Map<string, number>();
  const picked = state.inventory.find(item => item.id === pickedId && (free.get(item.id) ?? 0) > 0) ?? null;

  async function add(item: InventoryItem, drop: FoodDrop) {
    if (!plan) return;
    if (drop.kind === "meal") { const meal = plan.meals.find(m => m.id === drop.mealId); if (meal && meal.status === "planned" && !meal.locked) await save(withFood(meal, item, state), `${item.name} +1`); return; }
    if (plan.meals.some(m => m.day === drop.day && m.slot === drop.slot)) return;
    await save(mealOfFood(drop.day, drop.slot, item, state), `${item.name} added`);
  }
  const drag = useFoodDrag((item, drop) => { if ((free.get(item.id) ?? 0) > 0) void add(item, drop); });

  const calendar: CalendarBoard = { picked, over: drag.over, onPlace: drop => { if (picked) void add(picked, drop); } };
  const rail = { state, free, pickedId: picked?.id ?? null, onPick: (id: string) => { if (drag.clicked()) setPickedId(current => current === id ? null : id); }, onDragFood: (event: ReactPointerEvent<HTMLElement>, item: InventoryItem) => drag.start(event, item, `${item.emoji ?? foodEmoji(item.name, item.type)} ${item.name}`) };
  return { calendar, rail, ghost: drag.ghostNode };
}

/** Freezer first, as on the Fridge page; any other place after. */
const PLACES: [string, string][] = [["freezer", "❄️ 冷冻 Freezer"], ["fridge", "🧊 冷藏 Fridge"]];
const TYPES: FoodType[] = ["Protein", "Carbs", "Vegetables", "Dairy", "Other"];
const SORTS = { made: "Oldest made", newest: "Newest made", name: "Name" } as const;
type Sort = keyof typeof SORTS;
const madeOn = (day: string) => new Intl.DateTimeFormat("en-US", { month: "numeric", day: "numeric", timeZone: "UTC" }).format(new Date(`${day}T12:00:00Z`));

/** The fridge beside the week, one block per compartment. Foods are grouped by
 * food group (each group on its own rows) unless the household turns that off,
 * and ordered by the day they were made or by name; both choices are kept in
 * this browser. Each food shows the portions this week has not taken yet. */
export function FridgeRail({ state, free, pickedId, onPick, onDragFood }: ReturnType<typeof usePlanBoard>["rail"]) {
  const [groupRaw, setGroup] = useStored("local", "stu-board-group");
  const [sortRaw, setSort] = useStored("local", "stu-board-sort");
  const byType = groupRaw !== "none";
  const sort: Sort = sortRaw && sortRaw in SORTS ? sortRaw as Sort : "made";
  const foods = state.inventory.filter(item => item.portions > 0);
  const place = (item: InventoryItem) => item.location.trim().toLocaleLowerCase();
  const places = [...PLACES, ...[...new Set(foods.map(place))].filter(key => !PLACES.some(([p]) => p === key)).map(key => [key, key.charAt(0).toUpperCase() + key.slice(1)] as [string, string])];
  const order = (a: InventoryItem, b: InventoryItem) => sort === "name" ? a.name.localeCompare(b.name) : (sort === "made" ? 1 : -1) * a.addedOn.localeCompare(b.addedOn) || a.name.localeCompare(b.name);
  const picked = foods.find(item => item.id === pickedId);
  const food = (item: InventoryItem) => {
    const left = Math.max(0, Math.round((free.get(item.id) ?? 0) * 100) / 100);
    return <li key={item.id}><button type="button" className="kw-board-food" aria-pressed={pickedId === item.id} disabled={left <= 0} aria-label={`${item.name}, ${left} of ${item.portions} left, made ${madeOn(item.addedOn)}`} onPointerDown={event => { if (left > 0) onDragFood(event, item); }} onClick={() => onPick(item.id)}>
      <span aria-hidden="true">{item.emoji ?? foodEmoji(item.name, item.type)}</span><strong>{item.name}<AlsoMark primary={item.type} groups={item.secondaryTypes} /></strong><small>{left}/{item.portions} left · {madeOn(item.addedOn)}</small>
    </button></li>;
  };
  return <aside className="kw-board-fridge" aria-label="Fridge for this week">
    <header>
      <h2>冰箱 Fridge</h2>
      <div className="kw-board-controls">
        <label>Group<select value={byType ? "type" : "none"} onChange={e => setGroup(e.target.value === "none" ? "none" : null)}><option value="type">Food group</option><option value="none">None</option></select></label>
        <label>Sort<select value={sort} onChange={e => setSort(e.target.value)}>{Object.entries(SORTS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      </div>
      {picked && <p className="kw-board-hint" role="status">Tap a meal to add {picked.name}</p>}
    </header>
    <div className="kw-board-shelves">{places.map(([key, label]) => {
      const items = foods.filter(item => place(item) === key).sort(order);
      if (!items.length) return null;
      return <section key={key} className={`kw-board-place is-${key}`} aria-label={label}><h3>{label}</h3>
        {byType
          ? TYPES.map(type => { const group = items.filter(item => item.type === type); return group.length ? <div key={type} className="kw-board-group" role="group" aria-label={type}><h4><span aria-hidden="true">{foodEmoji("", type)}</span>{type}</h4><ul>{group.map(food)}</ul></div> : null; })
          : <ul>{items.map(food)}</ul>}
      </section>;
    })}</div>
    {!foods.length && <p className="kw-empty">The fridge is empty. Add food in Fridge first.</p>}
  </aside>;
}
