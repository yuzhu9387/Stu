import { expect, it } from "vitest";
import { applyChosen } from "@/features/kitchen/proposal-apply";
import type { Meal, PrepTask } from "@/features/kitchen/types";

const task = (id: string, plannedPortions: number, dependencies: string[] = []) => ({ id, plannedPortions, dependencies }) as PrepTask;
const meal = (id: string, prepId?: string) => ({ id, components: [{ id: `${id}-c`, name: id, type: "Other", portions: 1, ...(prepId ? { prepId } : {}) }] }) as Meal;

it("applies only the chosen meals, with just the prep they use", () => {
  const meals = [meal("a"), meal("b"), meal("c")];
  const prep = [task("rice", 4), task("soup", 3)];
  const proposal = { meals: [meal("a", "dumplings"), meal("b", "rice")], prep: [task("rice", 6), task("soup", 5), task("stock", 2), task("dumplings", 4, ["stock"])] };
  const some = applyChosen(meals, prep, proposal, ["a"]);
  expect(some.meals.map(m => m.components[0].prepId)).toEqual(["dumplings", undefined, undefined]);
  expect(some.prep.map(t => [t.id, t.plannedPortions])).toEqual([["rice", 4], ["soup", 3], ["stock", 2], ["dumplings", 4]]);
  const all = applyChosen(meals, prep, proposal);
  expect(all.prep).toBe(proposal.prep);
  expect(all.meals.map(m => m.components[0].prepId)).toEqual(["dumplings", "rice", undefined]);
});
