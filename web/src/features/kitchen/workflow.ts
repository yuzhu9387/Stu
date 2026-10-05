import type { KitchenState, PlanningWorkflow, PlanStep, WeeklyPlan } from "./types";

/** A plan with at least one meal to eat; an empty draft is a plan not yet made. */
export function hasPlannedMeals(plan: WeeklyPlan | null | undefined): boolean {
  return !!plan?.meals.some(meal => meal.included !== false && meal.components.length > 0);
}

/** A draft holding + Prep dishes and nothing planned by hand: besides them
 * only the weekly locked meals (and their prep) every new plan starts with.
 * Its week is not yet planned. As the server's prep_only. */
export function prepOnly(plan: WeeklyPlan): boolean {
  const lockedPrep = new Set(plan.meals.filter(m => m.locked).flatMap(m => m.components.map(c => c.prepId)));
  return plan.status === "draft" && plan.prep.some(t => t.origin === "fridge") && plan.meals.every(m => m.locked) && plan.prep.every(t => t.origin === "fridge" || lockedPrep.has(t.id));
}

/** A draft laid out for the whole week: a meal slot on all seven days (Stu's
 * drafts lay out every slot, marking the ones not eaten) and something to eat. */
export function coversWeek(plan: WeeklyPlan): boolean {
  return new Set(plan.meals.map(meal => meal.day)).size >= 7 && hasPlannedMeals(plan);
}

/** Next week's plan that is ready to review: the week is not confirmed yet and
 * its latest draft covers the week. An edit of a confirmed plan, a superseded
 * version, an empty draft or one with a meal or two (a repeating breakfast
 * carried over) is not a plan waiting for review. */
export function readyDraft(plans: WeeklyPlan[], week: string): WeeklyPlan | null {
  const inWeek = plans.filter(p => p.weekStart === week);
  if (inWeek.some(p => p.status === "confirmed")) return null;
  const latest = [...inWeek].reverse().find(p => p.status === "draft" && !p.basePlanId);
  return latest && coversWeek(latest) ? latest : null;
}

export function rememberedPlan(plans: WeeklyPlan[], week: string, saved?: PlanningWorkflow): WeeklyPlan | null {
  const plan = plans.find(p => p.id === saved?.planId && p.weekStart === week);
  if (!plan || !saved) return null;
  const allowed = plan.status === "confirmed" ? ["confirmed", "shopping"] : ["preferences", "adjust"];
  if (!allowed.includes(saved.step)) return null;
  // Superseded confirmed versions are archived as drafts by the command engine.
  if (plans.some(p => p.status === "confirmed" && p.basePlanId === plan.id)) return null;
  return plan;
}

/** Explicit links win; stored stages only apply to the plan they belong to. */
export function planningStep(plan: WeeklyPlan | null, requested: string | null, saved?: PlanningWorkflow): PlanStep {
  if (!plan) return "preferences";
  const allowed: PlanStep[] = plan.status === "confirmed" ? ["confirmed", "shopping"] : ["preferences", "adjust"];
  if (requested && allowed.includes(requested as PlanStep)) return requested as PlanStep;
  if (saved?.planId === plan.id && allowed.includes(saved.step)) return saved.step;
  if (prepOnly(plan)) return "preferences";
  return plan.status === "confirmed" ? "confirmed" : "adjust";
}

/** Where a week's planning stands: confirmed, a draft, or nothing yet. */
export function weekStatus(state: KitchenState, monday: string): "confirmed" | "draft" | "none" {
  const plans = state.plans.filter(p => p.weekStart === monday);
  return plans.some(p => p.status === "confirmed") ? "confirmed" : plans.length ? "draft" : "none";
}
