import type { PlanningWorkflow, PlanStep, WeeklyPlan } from "./types";

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
  return plan.status === "confirmed" ? "confirmed" : "adjust";
}
