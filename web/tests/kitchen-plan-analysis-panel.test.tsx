import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { createDemoState } from "@/features/kitchen/data";
import { PlanningPage } from "@/features/kitchen/plan";
import { api } from "@/lib/api";
import type { Meal, Recipe } from "@/features/kitchen/types";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));
const mockedApi = vi.mocked(api);
beforeEach(() => mockedApi.mockReset());

function props() {
  const state = createDemoState();
  const plan = state.plans[0];
  // Analysis is part of adjusting a draft; a confirmed week shows only its calendar.
  plan.status = "draft";
  return {
    state, plan, week: plan.weekStart, selected: [], onSelect: () => {},
    step: null, onStep: vi.fn(), onGoal: vi.fn(async () => {}), onApplyFix: vi.fn<(meal: Meal) => Promise<void>>(async () => {}), onGenerate: async () => null,
    onSavePreferences: vi.fn(async () => 0), onChat: vi.fn(), onApply: vi.fn(), onConfirm: vi.fn(async () => null), onEdit: vi.fn(async () => {}), focusTick: 0, choices: { slots: {} }, onSlot: vi.fn(),
    onPrep: () => {}, onGuidance: () => {}, onWeek: () => {}, demo: true, busy: false,
    children: <div />,
  };
}

it("shows the plan analysis with the counts it used", () => {
  const p = props();
  render(<PlanningPage {...p} />);
  expect(screen.getByLabelText("Plan analysis")).toBeVisible();
  // The demo week reuses a small rotation, so variety is flagged and the
  // wording has to state the number it counted rather than just assert.
  expect(screen.getByText("Low vegetable variety")).toBeVisible();
  expect(screen.getByText(/distinct vegetable dish/)).toBeVisible();
});

it("applies a suggested fix through the normal meal save", async () => {
  const p = props();
  // A vegetable dish the demo week does not use, cheap enough to fit a day.
  const greens: Recipe = {
    id: "r-greens", name: "清炒时蔬", type: "Vegetables", mealTypes: ["breakfast", "lunch", "dinner"],
    tags: [], servings: 3, activeMinutes: 1, elapsedMinutes: 2, ingredients: [],
    steps: ["快炒"], liked: false, source: "test",
  };
  p.state.recipes = [...p.state.recipes, greens];
  render(<PlanningPage {...p} />);

  // Frame 47:195 names the dish in the "Friendly fix" line and keeps the
  // button itself generic.
  // Several fixes can be offered; the one naming the new dish is among them.
  const [button] = await screen.findAllByRole("button", { name: /Apply Fix · 清炒时蔬/ });
  fireEvent.click(button);
  await waitFor(() => expect(p.onApplyFix).toHaveBeenCalled());

  const saved = p.onApplyFix.mock.calls[0]![0]!;
  // The fix appends to the meal it named, leaving what was already there.
  expect(saved.components.at(-1)).toMatchObject({ recipeId: "r-greens", name: "清炒时蔬" });
  expect(saved.components.length).toBeGreaterThan(1);
});

it("offers up to three fixes for an issue, and says what the applied one settled", async () => {
  const p = props();
  const greens = (id: string, name: string): Recipe => ({
    id, name, type: "Vegetables", mealTypes: ["breakfast", "lunch", "dinner"],
    tags: [], servings: 3, activeMinutes: 1, elapsedMinutes: 2, ingredients: [],
    steps: ["快炒"], liked: false, source: "test",
  });
  p.state.recipes = [...p.state.recipes, greens("g1", "清炒时蔬"), greens("g2", "蒜蓉菜心"), greens("g3", "白灼生菜")];
  const { rerender } = render(<PlanningPage {...p} />);
  const fixes = await screen.findAllByRole("button", { name: /^Apply Fix · / });
  expect(fixes.length).toBeGreaterThan(1);
  expect(fixes.length).toBeLessThanOrEqual(3);

  // Apply one, then hand the page the plan as it is after the save.
  fireEvent.click(fixes[0]);
  await waitFor(() => expect(p.onApplyFix).toHaveBeenCalled());
  const saved = p.onApplyFix.mock.calls[0]![0]!;
  const after = { ...p.plan, meals: p.plan.meals.map(m => m.id === saved.id ? saved : m) };
  rerender(<PlanningPage {...p} plan={after} />);
  expect(await screen.findByText("After your change")).toBeVisible();
});
