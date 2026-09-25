import type { InventoryItem, KitchenState, MealComponent, PrepTask, WeeklyPlan } from "./types";
export interface TimingTask { id: string; name?: string; activeMinutes: number; elapsedMinutes: number; equipment?: string[]; dependencies?: string[]; incomplete?: boolean }
export function scheduleTasks(tasks: TimingTask[]) {
  const pending = new Map(tasks.map(task => [task.id, task]));
  if (pending.size !== tasks.length) throw new Error("Duplicate timing task IDs");
  const finished = new Map<string, number>(); const resources = new Map<string, number>();
  const rows: { id: string; startMinutes: number; activeEndMinutes: number; finishMinutes: number }[] = [];
  let activeMinutes = 0;
  while (pending.size) {
    const startAt = (task: TimingTask) => Math.max(task.activeMinutes ? resources.get("cook") || 0 : 0, ...(task.dependencies || []).map(dep => finished.get(dep)!), ...(task.equipment || []).map(e => resources.get(`equipment:${e}`) || 0));
    const task = [...pending.values()].filter(t => (t.dependencies || []).every(dep => finished.has(dep))).sort((a,b)=>startAt(a)-startAt(b))[0];
    if (!task) throw new Error("Timing dependencies are missing or cyclic");
    if (task.incomplete || !Number.isFinite(task.activeMinutes) || !Number.isFinite(task.elapsedMinutes) || task.activeMinutes < 0 || task.elapsedMinutes < task.activeMinutes || task.elapsedMinutes <= 0) throw new Error(`Complete timing is required for ${task.name || task.id}`);
    const start = startAt(task);
    if (task.activeMinutes) resources.set("cook", start + task.activeMinutes);
    const finish = start + task.elapsedMinutes;
    (task.equipment || []).forEach(e => resources.set(`equipment:${e}`, finish));
    finished.set(task.id, finish); activeMinutes += task.activeMinutes;
    rows.push({ id: task.id, startMinutes: start, activeEndMinutes: start + task.activeMinutes, finishMinutes: finish }); pending.delete(task.id);
  }
  const elapsedMinutes = Math.max(0, ...finished.values());
  return { activeMinutes, elapsedMinutes, waitMinutes: elapsedMinutes - activeMinutes, tasks: rows };
}
export function prepSchedule(state: KitchenState, plan: WeeklyPlan) {
  const tasks = plan.prep.map(task => {
    const recipe = state.recipes.find(r => r.id === task.recipeId);
    const batches = recipe ? Math.max(1, Math.ceil(task.plannedPortions / recipe.servings)) : 1;
    return { ...task, activeMinutes: Math.max(task.activeMinutes, recipe ? recipe.activeMinutes * batches : 0), elapsedMinutes: Math.max(task.elapsedMinutes, recipe ? recipe.elapsedMinutes * batches : 0), equipment: [...new Set([...task.equipment, ...(recipe?.equipment || [])])], incomplete: recipe?.incomplete };
  });
  const schedule = scheduleTasks(tasks);
  const ordinaryReadyMinutes = Math.max(0, ...schedule.tasks.filter(row => tasks.find(t => t.id === row.id)?.type !== "Baking").map(row => row.finishMinutes));
  return { ...schedule, ordinaryReadyMinutes: Math.max(0, ...schedule.tasks.filter(row => tasks.find(t => t.id === row.id)?.type !== "Baking").map(row => row.finishMinutes)), bakingWaitMinutes: Math.max(0, schedule.elapsedMinutes - Math.max(ordinaryReadyMinutes, ...schedule.tasks.map(row => row.activeEndMinutes))) };
}
export function prepUnavailable(state: KitchenState, plan: WeeklyPlan, task: PrepTask): string[] {
  const problems = task.dependencies.filter(id => plan.prep.find(p => p.id === id)?.status !== "completed").map(id => `Complete ${plan.prep.find(p => p.id === id)?.name || "prerequisite prep"} first.`);
  const totals = new Map<string, number>(); task.inputs.forEach(input => totals.set(input.inventoryId, (totals.get(input.inventoryId) || 0) + input.portions));
  totals.forEach((portions, id) => { const item = state.inventory.find(i => i.id === id); const missing = portions - (item?.portions || 0); if (missing > 1e-8) problems.push(`${item?.name || "Missing ingredient batch"}: ${missing} more portions needed.`); });
  return problems;
}
export function projectedMealShortages(state: KitchenState, plan: WeeklyPlan) {
  const stock: InventoryItem[] = structuredClone(state.inventory);
  const consume = (c: Pick<MealComponent, "portions" | "inventoryId" | "recipeId" | "name">) => {
    let remaining = c.portions;
    const candidates = stock.filter(i => c.inventoryId ? i.id === c.inventoryId : c.recipeId ? i.recipeId === c.recipeId : i.name.toLocaleLowerCase() === c.name.toLocaleLowerCase()).sort((a, b) => a.addedOn.localeCompare(b.addedOn) || a.id.localeCompare(b.id));
    candidates.forEach(i => { const used = Math.min(remaining, i.portions); i.portions -= used; remaining -= used; });
    return remaining;
  };
  const pending = plan.prep.filter(p => p.status === "planned");
  const ready = new Set(plan.prep.filter(p => p.status === "completed").map(p => p.id));
  while (pending.length) {
    const index = pending.findIndex(p => p.dependencies.every(id => ready.has(id))); if (index < 0) break;
    const task = pending.splice(index, 1)[0];
    const totals = new Map<string, number>(); task.inputs.forEach(i => totals.set(i.inventoryId, (totals.get(i.inventoryId) || 0) + i.portions));
    if ([...totals].some(([id, needed]) => (stock.find(i => i.id === id)?.portions || 0) < needed)) continue;
    task.inputs.forEach(i => consume({ ...i, name: "" }));
    const id = task.outputInventoryId || `prep-${task.id}`; const existing = stock.find(i => i.id === id);
    if (existing) existing.portions += task.plannedPortions;
    else stock.push({ id, name: task.name, type: task.type === "Baking" ? "Carbs" : task.type, portions: task.plannedPortions, recipeId: task.recipeId, location: "planned", prepared: true, addedOn: plan.weekStart, priority: false });
    ready.add(task.id);
  }
  state.plans.filter(p => p.status === "confirmed" && p.id !== plan.id && p.id !== plan.basePlanId).forEach(p => p.meals.filter(m => m.status === "planned" && m.included !== false).forEach(m => m.components.filter(c => c.inventoryId || c.prepId).forEach(consume)));
  const order = { breakfast: 0, lunch: 1, dinner: 2 };
  return plan.meals.filter(m => m.status === "planned" && m.included !== false).slice().sort((a,b) => a.day.localeCompare(b.day) || order[a.slot] - order[b.slot]).flatMap(meal => {
    const missing = meal.components.filter(c => c.inventoryId || c.prepId).flatMap(c => { const prep = plan.prep.find(p => p.id === c.prepId); const portions = consume({ ...c, inventoryId: prep ? prep.outputInventoryId || `prep-${prep.id}` : c.inventoryId }); return portions > 1e-8 ? [{ name: c.name, portions }] : []; });
    return missing.length ? [{ meal, missing }] : [];
  });
}
