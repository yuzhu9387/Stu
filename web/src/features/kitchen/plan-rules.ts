import type { PlanWarning } from "./analysis";
import { prepSchedule } from "./schedule";
import type { KitchenState, Meal, WeeklyPlan } from "./types";

const staples = new Set(["rice", "steamedrice", "plainsteamedrice", "cookedrice", "whiterice", "brownrice", "cookedbrownrice", "米饭", "白米饭", "糙米饭", "清水", "water", "milk", "牛奶", "plainbread", "白面包"]);
const key = (name: string) => name.replace(/[^\p{L}\p{N}]/gu, "");
const active = (meal: Meal) => meal.included !== false && meal.status !== "skipped";

/** Match the server's calendar-day rotation, including stock/prep recipe
 * aliases and the authoritative neighbouring week. These are advice only. */
export function planRuleWarnings(state: KitchenState, plan: WeeklyPlan): PlanWarning[] {
  const warnings: PlanWarning[] = [];
  const records: { name: string; keys: Set<string>; day: string; external: boolean }[] = [];
  const add = (source: WeeklyPlan, meal: Meal, external: boolean) => meal.components.forEach(c => {
    const stock = state.inventory.find(i => i.id === c.inventoryId);
    const prep = source.prep.find(p => p.id === c.prepId);
    const recipeId = c.recipeId ?? stock?.recipeId ?? prep?.recipeId;
    const recipe = state.recipes.find(r => r.id === recipeId);
    const name = recipe?.name ?? stock?.name ?? prep?.name ?? c.name;
    if (!external && !recipe && !stock && !prep) warnings.push({
      id: `missing-recipe:${meal.id}:${c.id}`, severity: "warning", title: `${c.name}: recipe not saved`,
      detail: `${meal.day} ${meal.slot}. This dish is kept in your plan. Open the meal to edit and add its recipe; cooking time is an estimate.`,
    });
    const normalized = name.normalize("NFKC").toLocaleLowerCase();
    const parts = normalized.split(/[()/|]/).map(key).filter(Boolean);
    if (parts.length && parts.every(p => staples.has(p)) && (recipe?.ingredients.length ?? 0) <= 3) return;
    const aliases = new Set([key(normalized), ...parts].filter(p => p && !staples.has(p)).map(p => `name:${p}`));
    if (recipeId) aliases.add(`recipe:${recipeId}`);
    records.push({ name, keys: aliases, day: meal.day, external });
  });
  const neighbours = new Map<string, WeeklyPlan>();
  state.plans.filter(p => p.weekStart !== plan.weekStart).forEach(p => {
    const previous = neighbours.get(p.weekStart);
    const rank = (value: WeeklyPlan) => value.status === "confirmed" ? 1 : 0;
    if (!previous || rank(p) > rank(previous) || rank(p) === rank(previous) && (p.version > previous.version || p.version === previous.version && p.id > previous.id)) neighbours.set(p.weekStart, p);
  });
  neighbours.forEach(p => p.meals.filter(m => active(m) && (m.status === "completed" || p.status === "confirmed")).forEach(m => add(p, m, true)));
  const meals = plan.meals.filter(active);
  meals.forEach(m => add(plan, m, false));
  records.sort((a, b) => a.day.localeCompare(b.day));
  const gap = state.settings.recipeRepeatGapDays ?? 1, seen = new Set<string>();
  records.forEach((current, index) => {
    for (let i = index - 1; i >= 0; i--) {
      const previous = records[i], days = (Date.parse(current.day) - Date.parse(previous.day)) / 86400000;
      if (days > gap) break;
      if (days <= 0 || current.external && previous.external || ![...current.keys].some(k => previous.keys.has(k))) continue;
      const id = `repeat-gap:${current.name}:${previous.day}:${current.day}`;
      if (seen.has(id)) continue;
      seen.add(id);
      warnings.push({ id, severity: "warning", title: `${current.name}: repeated too soon`, detail: `${previous.day} and ${current.day}. Your rule asks for ${gap} full day${gap === 1 ? "" : "s"} between repeats. You can keep it or adjust these meals.` });
    }
  });
  const days = new Map<string, number>();
  meals.forEach(m => days.set(m.day, (days.get(m.day) ?? 0) + m.activeMinutes));
  days.forEach((minutes, day) => {
    if (minutes > state.settings.maxDailyActiveMinutes) warnings.push({ id: `daily-limit:${day}`, severity: "warning", title: `${day}: cooking over budget`, detail: `${minutes} active minutes; your daily target is ${state.settings.maxDailyActiveMinutes} minutes.` });
  });
  try {
    const timing = prepSchedule(state, { ...plan, prep: plan.prep.filter(p => p.status !== "skipped") });
    if (timing.activeMinutes > state.settings.maxPrepMinutes || timing.ordinaryReadyMinutes > state.settings.maxPrepMinutes) warnings.push({ id: "prep-limit", severity: "warning", title: "Prep exceeds your time target", detail: `${timing.activeMinutes} active minutes and ${timing.ordinaryReadyMinutes} elapsed minutes; target ${state.settings.maxPrepMinutes} minutes.` });
  } catch { /* malformed timing is handled by the editor/server */ }
  return warnings;
}
