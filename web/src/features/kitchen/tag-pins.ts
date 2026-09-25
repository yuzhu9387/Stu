import type { KitchenSettings, MealSlot, Recipe } from "./types";

/** The meals count as tags: each is pinned and filtered by its slot. */
export const MEAL_TAGS: { slot: MealSlot; label: string }[] = [
  { slot: "breakfast", label: "Breakfast 🌅" },
  { slot: "lunch", label: "Lunch ☀️" },
  { slot: "dinner", label: "Dinner 🌙" },
];
/** Pinned until the household chooses (as on the server): the meals and the child's tags. */
export const DEFAULT_PINNED_TAGS = ["breakfast", "lunch", "dinner", "小孩饭", "Baby-friendly"];
const LABELS: Record<string, string> = { "小孩饭": "小孩饭 👶", "Baby-friendly": "Baby-friendly 👶" };

export const isMealTag = (tag: string) => MEAL_TAGS.some(m => m.slot === tag.trim().toLocaleLowerCase());
export const pinsOf = (settings: KitchenSettings) => settings.pinnedTags ?? DEFAULT_PINNED_TAGS;

/** One tag of the library as the filters and the tag manager show it. */
export interface LibraryTag { key: string; label: string; meal?: MealSlot; pinned: boolean }

/** The meals and the library's tags, pinned ones first in the order they were
 * pinned, then the rest (meals first). A tag named after a meal is that meal. */
export function libraryTags(tags: string[], settings: KitchenSettings): LibraryTag[] {
  const pins = pinsOf(settings);
  const all: LibraryTag[] = [
    ...MEAL_TAGS.map(m => ({ key: m.slot, label: m.label, meal: m.slot, pinned: pins.includes(m.slot) })),
    ...tags.filter(tag => !isMealTag(tag)).map(tag => ({ key: tag, label: LABELS[tag] ?? tag, pinned: pins.includes(tag) })),
  ];
  const rank = (tag: LibraryTag) => tag.pinned ? pins.indexOf(tag.key) : pins.length;
  return all.map((tag, index) => ({ tag, index })).sort((a, b) => rank(a.tag) - rank(b.tag) || a.index - b.index).map(({ tag }) => tag);
}

/** Whether a recipe carries a library tag (a meal by its meal types or a tag of that name). */
export const hasTag = (recipe: Recipe, tag: LibraryTag) => tag.meal
  ? recipe.mealTypes.includes(tag.meal) || recipe.tags.some(t => t.trim().toLocaleLowerCase() === tag.meal)
  : recipe.tags.includes(tag.key);

/** As the server: change the pins, saving them only when they change. The
 * first change starts from the defaults the household has. */
export function repin(state: { settings: KitchenSettings; tags: string[] }, change: (pins: string[]) => string[]) {
  const pins = state.settings.pinnedTags ?? DEFAULT_PINNED_TAGS.filter(pin => isMealTag(pin) || state.tags.includes(pin));
  const next = [...new Set(change(pins))];
  if (next.join("\u0000") !== pins.join("\u0000")) state.settings.pinnedTags = next;
}
