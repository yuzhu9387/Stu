import { expect, it } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { planRuleWarnings } from "@/features/kitchen/plan-rules";

it("reports a two-day repeat and an unsaved dish, without exempting a renamed recipe", () => {
  const state = createDemoState(), plan = state.plans[0];
  plan.meals = plan.meals.slice(0, 2).map((meal, i) => ({ ...meal, day: `2026-09-${21+i}`, components: [{ id: `c${i}`, name: "鸡肉丸 (Chicken Meatballs)", type: "Protein", portions: 3 }] }));
  plan.meals[1].components[0].name = "Chicken Meatballs";
  const issues = planRuleWarnings(state, plan);
  expect(issues.some(w => w.id.startsWith("repeat-gap:"))).toBe(true);
  expect(issues.some(w => w.id.startsWith("missing-recipe:"))).toBe(true);
  plan.meals[1].included = false;
  expect(planRuleWarnings(state, plan).some(w => w.id.startsWith("repeat-gap:"))).toBe(false);
});

it("allows plain rice on consecutive days and ignores alternate drafts", () => {
  const state = createDemoState(), plan = state.plans[0];
  plan.meals = plan.meals.slice(0, 2).map((meal, i) => ({ ...meal, day: `2026-09-${21+i}`, components: [{ id: `c${i}`, name: "Rice", type: "Carbs", portions: 3 }] }));
  state.plans.push({ ...structuredClone(plan), id: "other", status: "draft" });
  expect(planRuleWarnings(state, plan).some(w => w.id.startsWith("repeat-gap:"))).toBe(false);
});
