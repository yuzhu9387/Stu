import type { Meal } from "./types";

/** A meal's steps for one dish, or (no componentId) for the meal as a whole. */
export interface StepGroup { componentId?: string; label: string; steps: string[] }

type Component = Meal["components"][number];
const PREFIX = /^\s*([^:：]{1,80}?)\s*[:：]\s*(.+)$/;

/** The dish a step belongs to: "Dish: step" names it; otherwise a step that
 * mentions exactly one dish is that dish's. Anything else is for the meal. */
function owner(step: string, components: Component[]): { id?: string; text: string } {
  const prefixed = PREFIX.exec(step);
  if (prefixed) {
    const dish = components.find(c => c.name.trim() === prefixed[1].trim());
    if (dish) return { id: dish.id, text: prefixed[2] };
  }
  const named = components.filter(c => c.name.trim() && step.includes(c.name.trim()));
  return named.length === 1 ? { id: named[0].id, text: step } : { text: step };
}

/** A meal's steps by dish, in the order of its dishes, then those for the whole
 * meal. A meal of one dish keeps every step under that dish. */
export function stepGroups(meal: Pick<Meal, "components" | "steps">): StepGroup[] {
  const steps = meal.steps.filter(step => step.trim());
  if (meal.components.length <= 1) {
    const only = meal.components[0];
    return [{ componentId: only?.id, label: only?.name || "This meal", steps: steps.map(step => owner(step, meal.components).text) }];
  }
  const groups: StepGroup[] = meal.components.map(c => ({ componentId: c.id, label: c.name, steps: [] }));
  const whole: StepGroup = { label: "Whole meal", steps: [] };
  for (const step of steps) {
    const { id, text } = owner(step, meal.components);
    (groups.find(g => g.componentId === id) ?? whole).steps.push(text);
  }
  return [...groups, whole].filter(group => group.steps.length || group.componentId);
}

/** Steps stored back: each dish's as "Dish: step", then the whole meal's. */
export function joinSteps(groups: StepGroup[], components: Component[]): string[] {
  const single = components.length <= 1;
  return groups.flatMap(group => {
    const dish = components.find(c => c.id === group.componentId);
    return group.steps.filter(step => step.trim()).map(step => dish && !single ? `${dish.name}: ${step}` : step);
  });
}

/** The meal without one dish: its steps go with it. */
export function removeComponent(meal: Meal, componentId: string): Meal {
  const components = meal.components.filter(c => c.id !== componentId);
  const kept = stepGroups(meal).filter(group => group.componentId !== componentId);
  return { ...meal, components, steps: joinSteps(kept, components) };
}

/** One dish's steps replaced (from a textarea, one step per line). */
export function setDishSteps(meal: Meal, componentId: string | undefined, text: string): Meal {
  const groups = stepGroups(meal);
  const lines = text.split("\n");
  const index = groups.findIndex(group => group.componentId === componentId);
  const next = index >= 0 ? groups.map((group, i) => i === index ? { ...group, steps: lines } : group) : [...groups, { componentId, label: "Whole meal", steps: lines }];
  return { ...meal, steps: joinSteps(next, meal.components) };
}
