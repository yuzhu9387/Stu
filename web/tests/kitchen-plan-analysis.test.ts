import { describe, expect, it } from "vitest";

import { planStats, planWarnings } from "@/features/kitchen/analysis";
import { emptyState } from "@/features/kitchen/data";
import type { KitchenState, Meal, Recipe, WeeklyPlan } from "@/features/kitchen/types";

const WEEK = "2026-09-14";

function recipe(id: string, name: string, over: Partial<Recipe> = {}): Recipe {
  return {
    id, name, type: "Vegetables", mealTypes: ["dinner"], tags: [], servings: 3,
    activeMinutes: 8, elapsedMinutes: 12, ingredients: [], steps: ["炒"],
    liked: false, source: "test", ...over,
  };
}

function meal(day: string, slot: Meal["slot"], components: Meal["components"], over: Partial<Meal> = {}): Meal {
  return {
    id: `m-${day}-${slot}`, day, slot, components,
    activeMinutes: 8, elapsedMinutes: 12, steps: [], status: "planned",
    liked: false, locked: false, ...over,
  };
}

function scenario(meals: Meal[], recipes: Recipe[] = []): { state: KitchenState; plan: WeeklyPlan } {
  const plan: WeeklyPlan = {
    id: "p-1", weekStart: WEEK, status: "confirmed", version: 1, prompt: "",
    meals, prep: [], chat: [],
  };
  const state = { ...emptyState(), recipes, plans: [plan] };
  return { state, plan };
}

const protein = (n: string) => ({ id: `c-${n}`, name: n, type: "Protein" as const, portions: 3 });
const veg = (n: string, recipeId?: string) => ({ id: `c-${n}`, name: n, type: "Vegetables" as const, portions: 3, recipeId });

describe("variety warnings, frame 105:513", () => {
  it("says nothing about an empty week", () => {
    expect(planWarnings(...Object.values(scenario([])) as [KitchenState, WeeklyPlan])).toEqual([]);
  });

  it("counts the distinct vegetable dishes it actually found", () => {
    const { state, plan } = scenario([
      meal(WEEK, "dinner", [protein("鸡肉丸"), veg("西兰花", "r-broccoli")]),
      meal("2026-09-15", "dinner", [protein("牛肉"), veg("西兰花", "r-broccoli")]),
    ]);
    const warning = planWarnings(state, plan).find(w => w.id === "vegetable-variety");
    expect(warning).toBeDefined();
    // One distinct dish used twice, not two.
    expect(warning!.detail).toContain("1 distinct vegetable dish");
  });

  it("stays quiet once the week has enough variety", () => {
    const { state, plan } = scenario([
      meal(WEEK, "dinner", [veg("西兰花", "r-1")]),
      meal("2026-09-16", "dinner", [veg("菠菜", "r-2")]),
      meal("2026-09-18", "dinner", [veg("青菜", "r-3")]),
    ]);
    expect(planWarnings(state, plan).some(w => w.id === "vegetable-variety")).toBe(false);
  });

  it("names the meals that have no vegetable at all", () => {
    const { state, plan } = scenario([
      meal(WEEK, "dinner", [protein("鸡肉丸")]),
      meal("2026-09-15", "lunch", [protein("牛肉")]),
    ]);
    const note = planWarnings(state, plan).find(w => w.id === "meals-without-vegetables");
    expect(note!.title).toContain("2 meals");
    expect(note!.detail).toContain("Mon dinner");
  });

  it("ignores slots the household excluded or skipped", () => {
    const { state, plan } = scenario([
      meal(WEEK, "dinner", [protein("鸡肉丸")], { included: false }),
      meal("2026-09-15", "dinner", [protein("牛肉")], { status: "skipped" }),
      meal("2026-09-16", "dinner", [veg("西兰花", "r-1")]),
    ]);
    const note = planWarnings(state, plan).find(w => w.id === "meals-without-vegetables");
    expect(note).toBeUndefined();
  });

  it("flags a dish used three or more times", () => {
    const days = ["2026-09-14", "2026-09-16", "2026-09-18"];
    const { state, plan } = scenario(days.map(d => meal(d, "dinner", [veg("西兰花", "r-1")])));
    const note = planWarnings(state, plan).find(w => w.id === "repeated-dishes");
    expect(note!.detail).toContain("×3");
  });
});

describe("suggested fix", () => {
  it("offers an unused vegetable that fits the day", () => {
    const { state, plan } = scenario(
      [meal(WEEK, "dinner", [protein("鸡肉丸")], { activeMinutes: 10 })],
      [recipe("r-greens", "清炒时蔬")],
    );
    const fix = planWarnings(state, plan).find(w => w.id === "vegetable-variety")!.fix!;
    expect(fix.mealId).toBe(`m-${WEEK}-dinner`);
    expect(fix.component.recipeId).toBe("r-greens");
    expect(fix.component.portions).toBe(state.settings.people);
    expect(fix.label).toContain("清炒时蔬");
  });

  it("offers nothing when the day has no hands-on budget left", () => {
    // 28 of 30 minutes used; the only candidate needs 8.
    const { state, plan } = scenario(
      [meal(WEEK, "dinner", [protein("鸡肉丸")], { activeMinutes: 28 })],
      [recipe("r-greens", "清炒时蔬")],
    );
    expect(planWarnings(state, plan).find(w => w.id === "vegetable-variety")!.fix).toBeUndefined();
  });

  it("will not suggest a dish that breaks the repeat gap", () => {
    // 清炒时蔬 is cooked the next day, so adding it today is one day apart.
    const { state, plan } = scenario(
      [
        meal(WEEK, "dinner", [protein("鸡肉丸")]),
        meal("2026-09-15", "dinner", [veg("清炒时蔬", "r-greens")]),
      ],
      [recipe("r-greens", "清炒时蔬")],
    );
    const warning = planWarnings(state, plan).find(w => w.id === "vegetable-variety")!;
    expect(warning.fix).toBeUndefined();
  });

  it("will not suggest a recipe with unknown timing", () => {
    const { state, plan } = scenario(
      [meal(WEEK, "dinner", [protein("鸡肉丸")])],
      [recipe("r-legacy", "旧菜谱", { incomplete: true })],
    );
    expect(planWarnings(state, plan).find(w => w.id === "vegetable-variety")!.fix).toBeUndefined();
  });

  it("will not suggest a recipe that is wrong for the slot", () => {
    const { state, plan } = scenario(
      [meal(WEEK, "breakfast", [protein("鸡蛋")])],
      [recipe("r-greens", "清炒时蔬", { mealTypes: ["dinner"] })],
    );
    expect(planWarnings(state, plan).find(w => w.id === "vegetable-variety")!.fix).toBeUndefined();
  });
});

describe("headline stats", () => {
  it("counts planned slots and flags days over the hands-on budget", () => {
    const { state, plan } = scenario([
      meal(WEEK, "dinner", [veg("西兰花", "r-1")], { activeMinutes: 35 }),
      meal("2026-09-15", "dinner", [protein("牛肉")], { activeMinutes: 10 }),
      meal("2026-09-16", "dinner", [protein("鱼")], { included: false }),
    ]);
    const stats = planStats(state, plan);
    expect(stats.plannedSlots).toBe(2);
    expect(stats.totalSlots).toBe(21);
    expect(stats.overBudgetDays).toEqual([WEEK]);
  });

  it("reports how many meals lean on stock", () => {
    const { state, plan } = scenario([
      meal(WEEK, "dinner", [{ ...veg("西兰花"), inventoryId: "inv-1" }]),
      meal("2026-09-15", "dinner", [protein("牛肉")]),
    ]);
    expect(planStats(state, plan).fridgeUsage).toBe(50);
  });
});

describe("fix deduplication", () => {
  it("offers the same fix once even when two warnings point at it", () => {
    const { state, plan } = scenario(
      [meal(WEEK, "dinner", [protein("鸡肉丸")], { activeMinutes: 10 })],
      [recipe("r-greens", "清炒时蔬")],
    );
    const warnings = planWarnings(state, plan);
    // Both "low variety" and "no vegetable in this meal" apply here.
    expect(warnings.length).toBeGreaterThan(1);
    expect(warnings.filter(w => w.fix).length).toBe(1);
  });
});

describe("choosing where the fix lands", () => {
  it("skips a slot the dish does not suit and offers the next one", () => {
    // 蒜香菠菜 is a lunch/dinner dish, and the first gap is a breakfast.
    const { state, plan } = scenario(
      [
        meal(WEEK, "breakfast", [protein("鸡蛋")]),
        meal(WEEK, "lunch", [protein("牛肉")]),
      ],
      [recipe("r-spinach", "蒜香菠菜", { mealTypes: ["lunch", "dinner"] })],
    );
    const fix = planWarnings(state, plan).find(w => w.fix)?.fix;
    expect(fix).toBeDefined();
    expect(fix!.mealId).toBe(`m-${WEEK}-lunch`);
    expect(fix!.label).toContain("lunch");
  });

  it("still offers nothing when no slot can take any candidate", () => {
    const { state, plan } = scenario(
      [meal(WEEK, "breakfast", [protein("鸡蛋")])],
      [recipe("r-spinach", "蒜香菠菜", { mealTypes: ["dinner"] })],
    );
    expect(planWarnings(state, plan).every(w => !w.fix)).toBe(true);
  });
});

describe("what counts as already used", () => {
  it("counts a dish served via a fridge batch toward its uses", () => {
    // The component names the soup and points at stock, with no recipeId —
    // the shape a stock-based meal actually has. Twice already, so a third
    // serving would make it a repeated dish and is not suggested.
    const soup = recipe("r-soup", "胡萝卜玉米汤", { mealTypes: ["lunch", "dinner"] });
    const fromFridge = (id: string) => ({ id, name: "胡萝卜玉米汤", type: "Vegetables" as const, portions: 3, inventoryId: "inv-soup" });
    const { state, plan } = scenario(
      [
        meal(WEEK, "dinner", [fromFridge("c1")]),
        meal("2026-09-18", "dinner", [fromFridge("c2")]),
        meal("2026-09-16", "dinner", [protein("牛肉")]),
      ],
      [soup],
    );
    state.inventory = [{
      id: "inv-soup", name: "胡萝卜玉米汤", type: "Vegetables", portions: 6,
      location: "fridge", prepared: true, addedOn: WEEK, priority: false, recipeId: "r-soup",
    }];
    expect(planWarnings(state, plan).flatMap(w => w.fixes ?? []).some(f => f.component.recipeId === "r-soup")).toBe(false);
  });

  it("counts a dish matched only by name toward its uses", () => {
    const named = (id: string) => ({ id, name: "蒜香菠菜", type: "Vegetables" as const, portions: 3 });
    const { state, plan } = scenario(
      [
        meal(WEEK, "dinner", [named("c1")]),
        meal("2026-09-18", "dinner", [named("c2")]),
        meal("2026-09-16", "dinner", [protein("牛肉")]),
      ],
      [recipe("r-spinach", "蒜香菠菜")],
    );
    expect(planWarnings(state, plan).flatMap(w => w.fixes ?? []).some(f => f.component.recipeId === "r-spinach")).toBe(false);
  });

  it("still suggests a dish used once, when the repeat gap allows it", () => {
    // Suggesting only never-used dishes left most real weeks with no fix at all.
    const { state, plan } = scenario(
      [
        meal(WEEK, "dinner", [{ id: "c1", name: "蒜香菠菜", type: "Vegetables", portions: 3, recipeId: "r-spinach" }]),
        meal("2026-09-17", "dinner", [protein("牛肉")]),
      ],
      [recipe("r-spinach", "蒜香菠菜")],
    );
    const fixes = planWarnings(state, plan).flatMap(w => w.fixes ?? []);
    expect(fixes.some(f => f.component.recipeId === "r-spinach" && f.mealId === plan.meals[1].id)).toBe(true);
  });


});
