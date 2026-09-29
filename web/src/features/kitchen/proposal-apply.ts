import type { ChatProposal, Meal, PrepTask } from "./types";

/** The plan's prep, with Stu's version of the tasks the chosen meals use (and
 * what those tasks depend on); every other task stays as it was. As the
 * server's `chosen_prep`. */
export function chosenPrep(current: PrepTask[], proposed: PrepTask[], meals: Meal[]): PrepTask[] {
  const byId = new Map(proposed.map(task => [task.id, task]));
  const wanted = new Set(meals.flatMap(meal => meal.components.map(c => c.prepId)).filter((id): id is string => !!id && byId.has(id)));
  const pending = [...wanted];
  while (pending.length) for (const dependency of byId.get(pending.pop()!)!.dependencies) if (byId.has(dependency) && !wanted.has(dependency)) { wanted.add(dependency); pending.push(dependency); }
  const known = new Set(current.map(task => task.id));
  return [...current.map(task => wanted.has(task.id) ? byId.get(task.id)! : task), ...proposed.filter(task => wanted.has(task.id) && !known.has(task.id))];
}

/** Stu's changes to a plan's meals and prep, all of them or only `mealIds`. */
export function applyChosen(meals: Meal[], prep: PrepTask[], proposal: Pick<ChatProposal, "meals" | "prep">, mealIds?: string[]) {
  const chosen = proposal.meals.filter(meal => !mealIds || mealIds.includes(meal.id));
  const partial = chosen.length < proposal.meals.length;
  return {
    meals: meals.map(meal => chosen.find(next => next.id === meal.id) ?? meal),
    prep: proposal.prep ? partial ? chosenPrep(prep, proposal.prep, chosen) : proposal.prep : prep,
  };
}
