"use client";
import { useStored } from "./browser-store";
import { foodEmoji } from "./food-art";
import type { FoodType, InventoryItem } from "./types";
import "./fridge-arrange.css";

/** How the fridge is shown, on the Fridge page and beside the week alike:
 * grouped by food group or not, and in which order. One choice for both,
 * kept in this browser. */
const SORTS = { arranged: "Your order", made: "Oldest made", newest: "Newest made", name: "Name" } as const;
export type FridgeSort = keyof typeof SORTS;
export const FOOD_GROUPS: FoodType[] = ["Protein", "Carbs", "Vegetables", "Dairy", "Other"];

export function useFridgeView() {
  const [group, setGroup] = useStored("local", "stu-board-group");
  const [sortRaw, setSort] = useStored("local", "stu-board-sort");
  const sort: FridgeSort = sortRaw && sortRaw in SORTS ? sortRaw as FridgeSort : "made";
  return { byType: group !== "none", sort, setByType: (on: boolean) => setGroup(on ? null : "none"), setSort: (next: FridgeSort) => setSort(next) };
}
export type FridgeView = ReturnType<typeof useFridgeView>;

/** Foods in the chosen order. "Your order" follows `arranged` (the order the
 * household dragged boxes into); the rest ignore it. */
export function sortFoods(items: InventoryItem[], sort: FridgeSort, arranged: string[]): InventoryItem[] {
  const rank = new Map(arranged.map((id, index) => [id, index]));
  const byName = (a: InventoryItem, b: InventoryItem) => a.name.localeCompare(b.name);
  return [...items].sort((a, b) => sort === "arranged" ? (rank.get(a.id) ?? 0) - (rank.get(b.id) ?? 0)
    : sort === "name" ? byName(a, b)
    : (sort === "made" ? 1 : -1) * a.addedOn.localeCompare(b.addedOn) || byName(a, b));
}

/** The foods a food group at a time (only groups that have some), or as one run. */
export function groupFoods(items: InventoryItem[], byType: boolean): { type?: FoodType; items: InventoryItem[] }[] {
  if (!byType) return [{ items }];
  return FOOD_GROUPS.map(type => ({ type, items: items.filter(item => item.type === type) })).filter(group => group.items.length);
}

export const groupLabel = (type: FoodType) => <><span aria-hidden="true">{foodEmoji("", type)}</span>{type}</>;

export function FridgeViewControls({ view }: { view: FridgeView }) {
  return <div className="kw-fridge-view">
    <label>Group<select value={view.byType ? "type" : "none"} onChange={e => view.setByType(e.target.value === "type")}><option value="type">Food group</option><option value="none">None</option></select></label>
    <label>Sort<select value={view.sort} onChange={e => view.setSort(e.target.value as FridgeSort)}>{Object.entries(SORTS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
  </div>;
}
