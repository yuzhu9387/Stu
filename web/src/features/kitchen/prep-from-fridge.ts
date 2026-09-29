import type { ComposedDish } from "./basket";
import { uid } from "./data";
import type { KitchenState, PageProps, PrepTask, WeeklyPlan } from "./types";

const DAY = 86_400_000;

/** The Monday of the week whose prep day is this coming weekend: prep day
 * falls on the weekend before the week it cooks for. On a Monday that week is
 * already under way, so it is the Monday after. */
export function nextWeekStart(today: string): string {
  const date = new Date(`${today}T12:00:00Z`);
  const ahead = (8 - date.getUTCDay()) % 7 || 7;
  return new Date(date.getTime() + ahead * DAY).toISOString().slice(0, 10);
}

/** The plan a week's prep day belongs to, as the Prep page shows it: the
 * confirmed plan, else the latest draft. */
export function prepPlan(plans: WeeklyPlan[], week: string): WeeklyPlan | null {
  const choices = plans.filter(p => p.weekStart === week);
  return choices.find(p => p.status === "confirmed") ?? choices.at(-1) ?? null;
}

/** A + Prep dish this plan alone holds, which it can cook before the week is
 * confirmed. A copy in another version of the week (an edit confirmed in
 * this one's place) is that version's to cook. As the server. */
export function ownFridgeDish(plans: WeeklyPlan[], plan: WeeklyPlan, task: PrepTask) {
  return task.origin === "fridge" && !plans.some(other => other.id !== plan.id && other.prep.some(t => t.id === task.id));
}

/** Everything on a week's prep day: the plan's own prep, and + Prep dishes
 * added to another plan of that week (a prep-only draft, before Stu drafted
 * the week as a new plan). Each task comes with the plan that holds it. */
export function weekPrep(plans: WeeklyPlan[], plan: WeeklyPlan): { task: PrepTask; owner: WeeklyPlan }[] {
  const own = plan.prep.map(task => ({ task, owner: plan }));
  const seen = new Set(plan.prep.map(task => task.id));
  const others = plans.filter(p => p.weekStart === plan.weekStart && p.id !== plan.id).flatMap(owner => owner.prep.filter(task => task.origin === "fridge" && !seen.has(task.id)).map(task => { seen.add(task.id); return { task, owner }; }));
  return [...own, ...others];
}

/** A dish for prep day from fridge foods: Stu's (or a recipe's) name, steps
 * and time, and what it takes from each food. Nothing is planned to be eaten
 * from it; what is left over is counted when it is done. A dish that is not a
 * recipe keeps Stu's amounts at the top of its steps, as a meal's does. */
export function fridgePrepTask({ recipe, uses }: ComposedDish, recipeId?: string): PrepTask {
  const amounts = recipe.ingredients.map(i => `${i.name} ${i.quantity}${i.unit}`).join("、");
  return {
    id: uid(), name: recipe.name.trim(), type: recipe.type === "Dairy" ? "Other" : recipe.type, origin: "fridge",
    ...(recipeId ? { recipeId } : {}),
    plannedPortions: 0, actualPortions: 0,
    activeMinutes: recipe.activeMinutes, elapsedMinutes: Math.max(recipe.elapsedMinutes, recipe.activeMinutes),
    steps: recipeId || !amounts ? [...recipe.steps] : [`食材 Ingredients: ${amounts}`, ...recipe.steps],
    status: "planned", liked: false, inputs: uses.map(use => ({ ...use })), equipment: [...(recipe.equipment ?? [])], dependencies: [],
  };
}

/** Put a dish on this coming weekend's prep day: into next week's plan, or a
 * new draft holding only prep when next week has none yet (a second + Prep
 * then finds that draft). Returns the week, or null when it was not saved. */
export async function addToPrep(state: Pick<KitchenState, "plans">, task: PrepTask, send: PageProps["send"], today: string): Promise<string | null> {
  const week = nextWeekStart(today);
  const plan = prepPlan(state.plans, week);
  const saved = plan
    ? await send("prep.save", { planId: plan.id, prep: task })
    : await send("plan.save", { plan: { id: uid(), weekStart: week, status: "draft", version: 1, prompt: "", meals: [], prep: [task], chat: [] } satisfies WeeklyPlan });
  return saved ? week : null;
}
