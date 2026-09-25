import { slots, weekDays } from "./data";
import type { AnalysisMetric, KitchenState, Meal, MealComponent, Recipe, WeeklyPlan } from "./types";

/** Plan analysis for frame 105:513.
 *
 * Everything here is counted from the plan the user is looking at, never
 * stored and never inferred: a warning states the number it counted and the
 * rule it applied, so it can be argued with. Nothing claims a nutritional
 * effect — the product doc is explicit that food groups are countable but
 * nutrition is not derived from tags or dish names.
 *
 * A suggested fix is only offered when it would actually be accepted: it has
 * to fit the day's hands-on budget and respect the repeat gap, because a
 * suggestion the engine rejects is worse than no suggestion at all.
 */

export interface PlanFix {
  label: string;
  mealId: string;
  component: MealComponent;
}

export interface PlanWarning {
  id: string;
  severity: "warning" | "note";
  title: string;
  detail: string;
  /** The best fix, kept for callers that offer one. */
  fix?: PlanFix;
  /** Up to three alternatives, best first, each on a different meal. */
  fixes?: PlanFix[];
}

const VEGETABLE_VARIETY_TARGET = 3;
const REPEAT_NOTE_THRESHOLD = 3;

/** Slots the household actually intends to cook. */
function cooked(plan: WeeklyPlan): Meal[] {
  return plan.meals.filter(m => (m.included ?? true) && m.status !== "skipped");
}

function dishKey(component: MealComponent) {
  return component.recipeId ?? component.name.trim().toLocaleLowerCase();
}

function daysApart(a: string, b: string) {
  return Math.abs(
    (Date.parse(`${a}T12:00:00Z`) - Date.parse(`${b}T12:00:00Z`)) / 86_400_000,
  );
}

/** The engine requires the same dish to sit at least `gap + 1` calendar days
 * apart, counting every authoritative plan, so a fix has to clear that too. */
function violatesRepeatGap(state: KitchenState, recipeId: string, day: string) {
  const gap = state.settings.recipeRepeatGapDays ?? 1;
  return state.plans.some(plan =>
    cooked(plan).some(
      meal =>
        meal.day !== day &&
        daysApart(meal.day, day) <= gap &&
        meal.components.some(c => c.recipeId === recipeId),
    ),
  );
}

function dayActiveMinutes(plan: WeeklyPlan, day: string) {
  return cooked(plan)
    .filter(m => m.day === day)
    .reduce((total, meal) => total + meal.activeMinutes, 0);
}

/** How many planned meals use each recipe, however the component names it.
 *
 * A stock-based component carries an inventoryId and a name but often no
 * recipeId, so matching on recipeId alone reports a dish as unused when it is
 * already on the menu three times. Resolving through the fridge batch and the
 * dish name as well is what stops the fix suggesting more of the same.
 */
function recipeUses(state: KitchenState, plan: WeeklyPlan): Map<string, number> {
  const byName = new Map(state.recipes.map(r => [r.name.trim().toLocaleLowerCase(), r.id]));
  const uses = new Map<string, number>();
  cooked(plan).forEach(meal => {
    const ids = new Set<string>();
    meal.components.forEach(component => {
      if (component.recipeId) ids.add(component.recipeId);
      const batch = state.inventory.find(i => i.id === component.inventoryId);
      if (batch?.recipeId) ids.add(batch.recipeId);
      const prep = plan.prep.find(p => p.id === component.prepId);
      if (prep?.recipeId) ids.add(prep.recipeId);
      const named = byName.get(component.name.trim().toLocaleLowerCase());
      if (named) ids.add(named);
    });
    ids.forEach(id => uses.set(id, (uses.get(id) ?? 0) + 1));
  });
  return uses;
}

/** The vegetable dish that fits this meal best: fewest uses this week first,
 * then least hands-on time. It must suit the slot, fit the day's time budget,
 * clear the repeat gap, and not push the dish into "several times". */
function suggestVegetable(state: KitchenState, plan: WeeklyPlan, meal: Meal, avoid: ReadonlySet<string> = new Set(), strict = false): Recipe | null {
  const uses = recipeUses(state, plan);
  const headroom = state.settings.maxDailyActiveMinutes - dayActiveMinutes(plan, meal.day);
  const candidates = state.recipes.filter(recipe =>
    recipe.type === "Vegetables" &&
    !recipe.incomplete &&
    recipe.mealTypes.includes(meal.slot) &&
    recipe.activeMinutes <= headroom &&
    (uses.get(recipe.id) ?? 0) < REPEAT_NOTE_THRESHOLD - 1 &&
    !meal.components.some(c => c.recipeId === recipe.id) &&
    !violatesRepeatGap(state, recipe.id, meal.day),
  );
  candidates.sort((a, b) => (uses.get(a.id) ?? 0) - (uses.get(b.id) ?? 0) || a.activeMinutes - b.activeMinutes);
  // Prefer a dish not already offered elsewhere, so the options are choices.
  return candidates.find(recipe => !avoid.has(recipe.id)) ?? (strict ? null : candidates[0] ?? null);
}

/** Up to three fixes to choose from, trying every candidate slot (the
 * earliest gap is often a breakfast, and most vegetable dishes are not
 * breakfast dishes). Options land on different days and, where the recipe
 * book allows, suggest different dishes — three copies of one dish on one day
 * is not a choice. */
function fixesFor(state: KitchenState, plan: WeeklyPlan, candidates: Meal[], limit = 3): PlanFix[] {
  const fixes: PlanFix[] = [], repeats: PlanFix[] = [];
  const days = new Set<string>(), dishes = new Set<string>();
  const dayOf = (fix: PlanFix) => plan.meals.find(m => m.id === fix.mealId)?.day ?? "";
  // First pass: a different dish on a different day. A day whose first slot
  // only fits a dish already offered keeps looking at its other slots.
  for (const meal of candidates) {
    if (fixes.length === limit) break;
    if (days.has(meal.day)) continue;
    const fresh = fixFor(state, plan, meal, dishes, true);
    if (fresh) { fixes.push(fresh); days.add(meal.day); dishes.add(fresh.component.recipeId!); continue; }
    const repeat = fixFor(state, plan, meal, dishes);
    if (repeat && !repeats.some(r => dayOf(r) === meal.day)) repeats.push(repeat);
  }
  // Then, if the recipe book has too few fitting dishes, the same dish on
  // another day is still a real choice.
  for (const repeat of repeats) {
    if (fixes.length === limit) break;
    if (!days.has(dayOf(repeat))) { fixes.push(repeat); days.add(dayOf(repeat)); }
  }
  return fixes;
}

function fixFor(state: KitchenState, plan: WeeklyPlan, meal: Meal, avoid?: ReadonlySet<string>, strict = false): PlanFix | undefined {
  const recipe = suggestVegetable(state, plan, meal, avoid, strict);
  if (!recipe) return undefined;
  const label = `${recipe.name} → ${dayName(meal.day)} ${meal.slot}`;
  return {
    label,
    mealId: meal.id,
    component: {
      id: crypto.randomUUID(),
      name: recipe.name,
      type: recipe.type,
      portions: state.settings.people,
      recipeId: recipe.id,
    },
  };
}

const dayNameFormat = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" });
function dayName(day: string) {
  return dayNameFormat.format(
    new Date(`${day}T12:00:00Z`),
  );
}

export function planWarnings(state: KitchenState, plan: WeeklyPlan): PlanWarning[] {
  const meals = cooked(plan);
  if (!meals.length) return [];
  const warnings: PlanWarning[] = [];

  const vegetables = new Set(
    meals.flatMap(m => m.components.filter(c => c.type === "Vegetables").map(dishKey)),
  );
  if (vegetables.size < VEGETABLE_VARIETY_TARGET) {
    // Prefer a planned meal that has no vegetable at all, and only then any
    // planned meal, so the fix lands where it changes the most.
    const candidates = meals.filter(m => m.status === "planned");
    // Slots that have no vegetable at all come first; they change the most.
    const ordered = [
      ...candidates.filter(m => !m.components.some(c => c.type === "Vegetables")),
      ...candidates.filter(m => m.components.some(c => c.type === "Vegetables")),
    ];
    warnings.push({
      id: "vegetable-variety",
      severity: "warning",
      title: "Low vegetable variety",
      detail: `${vegetables.size} distinct vegetable dish${
        vegetables.size === 1 ? "" : "es"
      } across ${meals.length} planned meals. Aiming for ${VEGETABLE_VARIETY_TARGET}.`,
      fixes: fixesFor(state, plan, ordered),
    });
  }

  const without = meals.filter(m => !m.components.some(c => c.type === "Vegetables"));
  if (without.length) {
    const targets = without.filter(m => m.status === "planned");
    warnings.push({
      id: "meals-without-vegetables",
      severity: "note",
      title: `${without.length} meal${without.length === 1 ? "" : "s"} without a vegetable`,
      detail: without
        .slice(0, 4)
        .map(m => `${dayName(m.day)} ${m.slot}`)
        .join(", ") + (without.length > 4 ? "…" : ""),
      fixes: fixesFor(state, plan, targets),
    });
  }

  const counts = new Map<string, { name: string; times: number }>();
  meals.forEach(m =>
    m.components.forEach(c => {
      const key = dishKey(c);
      const entry = counts.get(key) ?? { name: c.name, times: 0 };
      entry.times += 1;
      counts.set(key, entry);
    }),
  );
  const repeated = [...counts.values()]
    .filter(entry => entry.times >= REPEAT_NOTE_THRESHOLD)
    .sort((a, b) => b.times - a.times);
  if (repeated.length) {
    warnings.push({
      id: "repeated-dishes",
      severity: "note",
      title: "Same dish several times",
      detail: repeated
        .slice(0, 3)
        .map(entry => `${entry.name} ×${entry.times}`)
        .join(", "),
    });
  }

  // Two warnings can point at the same gap, and offering the same button twice
  // reads as two separate problems. Each fix is offered under its first issue.
  const offered = new Set<string>();
  return warnings.map(warning => {
    const fixes = (warning.fixes ?? []).filter(fix => {
      const key = `${fix.mealId}:${fix.component.recipeId}`;
      if (offered.has(key)) return false;
      offered.add(key);
      return true;
    });
    return { ...warning, fixes, fix: fixes[0] };
  });
}

/** The three headline numbers on frame 105:513, counted the same way. */
export function planStats(state: KitchenState, plan: WeeklyPlan) {
  const meals = cooked(plan);
  const week = weekDays(plan.weekStart);
  const budget = state.settings.maxDailyActiveMinutes;
  const overBudget = week.filter(day => dayActiveMinutes(plan, day) > budget);
  const fromStock = meals.filter(m =>
    m.components.some(c => c.inventoryId || c.prepId),
  ).length;
  return {
    foodGroups: new Set(meals.flatMap(m => m.components.map(c => c.type))).size,
    plannedSlots: meals.length,
    totalSlots: week.length * slots.length,
    overBudgetDays: overBudget,
    fridgeUsage: meals.length ? Math.round((fromStock / meals.length) * 100) : 0,
  };
}

/** The angles a week can be analysed from. The household picks which ones its
 * Plan Analysis shows (Settings → Planning Guidance). `rule` is the reference
 * text shown under Details: how each number is counted. */
export const ANALYSIS_METRICS: { id: AnalysisMetric; label: string; rule: string }[] = [
  { id: "prep_time", label: "Weekend prep", rule: "Hands-on minutes of this week's prep tasks, against the prep limit." },
  { id: "daily_time", label: "Daily cooking", rule: "Hands-on minutes of each day's planned meals: the daily average and the busiest day, against the daily limit." },
  { id: "nutrition_balance", label: "Food-group balance", rule: "How many planned meals include a protein, a carb and a vegetable, and how many different vegetable dishes the week uses. Counted from food groups, not measured nutrients." },
  { id: "repetition", label: "Repetition", rule: "How many different dishes the week uses, and any dish planned three or more times." },
  { id: "fridge_usage", label: "Fridge usage", rule: "Share of planned meals that use food already in the fridge or from weekend prep." },
];

export interface MetricResult { id: AnalysisMetric; label: string; value: string; status: "ok" | "warn" | "info"; warnings: PlanWarning[] }

/** Each chosen metric with its number, whether it needs attention, and the
 * issues (with their fixes) that belong to it. */
export function planMetrics(state: KitchenState, plan: WeeklyPlan): MetricResult[] {
  const chosen = state.settings.analysisMetrics ?? ANALYSIS_METRICS.map(m => m.id);
  const meals = cooked(plan);
  const warnings = planWarnings(state, plan);
  const week = weekDays(plan.weekStart);
  const dailyLimit = state.settings.maxDailyActiveMinutes;
  const results: Record<AnalysisMetric, () => Omit<MetricResult, "id" | "label">> = {
    prep_time: () => {
      const tasks = plan.prep.filter(t => t.status !== "skipped");
      const minutes = tasks.reduce((sum, t) => sum + t.activeMinutes, 0);
      const limit = state.settings.maxPrepMinutes;
      return tasks.length
        ? { value: `${minutes} min across ${tasks.length} task${tasks.length === 1 ? "" : "s"} · limit ${limit} min`, status: minutes > limit ? "warn" : "ok", warnings: [] }
        : { value: "No prep tasks this week", status: "info", warnings: [] };
    },
    daily_time: () => {
      const days = week.map(day => ({ day, minutes: dayActiveMinutes(plan, day) })).filter(d => meals.some(m => m.day === d.day));
      if (!days.length) return { value: "-", status: "info", warnings: [] };
      const average = Math.round(days.reduce((sum, d) => sum + d.minutes, 0) / days.length);
      const busiest = days.reduce((a, b) => (b.minutes > a.minutes ? b : a));
      const over = days.filter(d => d.minutes > dailyLimit);
      return {
        value: `${average} min a day on average · busiest ${dayName(busiest.day)} ${busiest.minutes} min · limit ${dailyLimit} min`,
        status: over.length ? "warn" : "ok",
        warnings: over.length ? [{ id: "daily-over", severity: "warning", title: `${over.length} day${over.length === 1 ? "" : "s"} over the daily limit`, detail: over.map(d => `${dayName(d.day)} ${d.minutes} min`).join(", ") }] : [],
      };
    },
    nutrition_balance: () => {
      const count = (type: MealComponent["type"]) => meals.filter(m => m.components.some(c => c.type === type)).length;
      const own = warnings.filter(w => w.id === "vegetable-variety" || w.id === "meals-without-vegetables");
      return {
        value: `Vegetables in ${count("Vegetables")} of ${meals.length} meals · protein ${count("Protein")} · carbs ${count("Carbs")}`,
        status: own.some(w => w.severity === "warning") || count("Vegetables") * 2 < meals.length ? "warn" : "ok",
        warnings: own,
      };
    },
    repetition: () => {
      const dishes = new Set(meals.flatMap(m => m.components.map(dishKey)));
      const own = warnings.filter(w => w.id === "repeated-dishes");
      return { value: `${dishes.size} different dishes${own.length ? ` · ${own[0].detail}` : ""}`, status: own.length ? "warn" : "ok", warnings: [] };
    },
    fridge_usage: () => ({ value: `${planStats(state, plan).fridgeUsage}% of meals use fridge or prep food`, status: "info", warnings: [] }),
  };
  return ANALYSIS_METRICS.filter(metric => chosen.includes(metric.id)).map(metric => ({ id: metric.id, label: metric.label, ...results[metric.id]() }));
}
