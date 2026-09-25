import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useState } from "react";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { ShoppingPrepPage } from "@/features/kitchen/shopping-prep";
import { planningStep, rememberedPlan } from "@/features/kitchen/workflow";
import type { KitchenState } from "@/features/kitchen/types";

it("restores only steps allowed for the current plan and gives explicit links priority", () => {
  const plan = createDemoState().plans[0];
  expect(planningStep(plan, null, { planId: plan.id, step: "shopping", focus: "prep" })).toBe("shopping");
  expect(planningStep(plan, "confirmed", { planId: plan.id, step: "shopping", focus: "prep" })).toBe("confirmed");
  expect(planningStep(plan, null, { planId: "another-plan", step: "shopping", focus: "prep" })).toBe("confirmed");
  plan.status = "draft";
  expect(planningStep(plan, "shopping", { planId: plan.id, step: "preferences", focus: "prep" })).toBe("preferences");
  expect(planningStep(null, "shopping")).toBe("preferences");
});

it("recovers the remembered draft and rejects a superseded confirmed version", () => {
  const a = createDemoState().plans[0]; a.status = "draft";
  const b = { ...a, id: "newer-draft" };
  const saved = { planId: a.id, step: "preferences" as const, focus: "shopping" as const };
  expect(rememberedPlan([a, b], a.weekStart, saved)).toBe(a);
  expect(rememberedPlan([a, b], "2026-09-28", saved)).toBeNull();
  expect(rememberedPlan([a, { ...b, status: "confirmed", basePlanId: a.id }], a.weekStart, saved)).toBeNull();
});

it("switches shopping/prep panels, scales ingredients and saves purchase checks", async () => {
  const initial = createDemoState(), recipe = initial.recipes[0], plan = initial.plans[0];
  plan.meals = []; plan.prep = [{ ...plan.prep[0], recipeId: recipe.id, plannedPortions: 6, status: "planned" }];
  recipe.servings = 3; recipe.ingredients = [{ name: "Chicken", quantity: 300, unit: "g" }];
  initial.inventory = [];
  let saved: KitchenState = initial;
  function Harness() {
    const [state, setState] = useState(initial), [focus, setFocus] = useState<"shopping" | "prep">("shopping");
    return <ShoppingPrepPage state={state} plan={state.plans[0]} focus={focus} onFocus={async next => setFocus(next)} demo navigate={vi.fn()} notify={vi.fn()} send={async (type, payload) => { saved = applyDemoCommand(state, { type, payload, operationId: crypto.randomUUID(), expectedRevision: state.revision }).state; setState(saved); return true; }} />;
  }
  render(<Harness />);
  const prep = screen.getByRole("button", { name: /Prep day.*dishes ready/ });
  expect(prep).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(prep);
  await waitFor(() => expect(prep).toHaveAttribute("aria-expanded", "true"));
  expect(within(screen.getByRole("region", { name: `Ingredients for ${plan.prep[0].name}` })).getByText("600 g")).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Purchased Chicken 600 g"));
  await waitFor(() => expect(saved.plans[0].shoppingChecked).toHaveLength(1));
  expect(saved.inventory).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: /Shopping cart.*picked up/ }));
  await waitFor(() => expect(prep).toHaveAttribute("aria-expanded", "false"));
  expect(screen.getByLabelText("Purchased Chicken 600 g")).toBeChecked();
});

it("keeps the panel unchanged if saving fails", async () => {
  const state = createDemoState();
  render(<ShoppingPrepPage state={state} plan={state.plans[0]} focus="shopping" onFocus={async () => { throw new Error("Offline. Try again."); }} demo navigate={vi.fn()} notify={vi.fn()} send={async () => false} />);
  fireEvent.click(screen.getByRole("button", { name: /Prep day.*dishes ready/ }));
  await screen.findByText("Offline. Try again.");
  expect(screen.getByRole("button", { name: /Prep day.*dishes ready/ })).toHaveAttribute("aria-expanded", "false");
});

it("opens prep immediately while its preference is still saving", async () => {
  const state = createDemoState();
  let finish!: () => void;
  const saving = new Promise<void>(resolve => { finish = resolve; });
  render(<ShoppingPrepPage state={state} plan={state.plans[0]} focus="shopping" onFocus={() => saving} demo navigate={vi.fn()} notify={vi.fn()} send={async () => true} />);
  const prep = screen.getByRole("button", { name: /Prep day.*dishes ready/ });
  fireEvent.click(prep);
  expect(prep).toHaveAttribute("aria-expanded", "true");
  finish();
  await waitFor(() => expect(prep).not.toBeDisabled());
});

it("rolls a purchase check back after a failed save", async () => {
  const state = createDemoState(), plan = state.plans[0], recipe = state.recipes[0];
  recipe.ingredients = [{ name: "Chicken", quantity: 300, unit: "g" }]; recipe.servings = 3;
  plan.meals = []; plan.prep = [{ ...plan.prep[0], recipeId: recipe.id, plannedPortions: 3, status: "planned" }];
  state.inventory = [];
  render(<ShoppingPrepPage state={state} plan={plan} focus="shopping" onFocus={vi.fn()} demo navigate={vi.fn()} notify={vi.fn()} send={async () => false} />);
  const checkbox = screen.getByLabelText("Purchased Chicken 300 g");
  fireEvent.click(checkbox);
  await screen.findByRole("alert");
  expect(checkbox).not.toBeChecked();
});

it("marks every item picked up in one save, and clears them again", async () => {
  const initial = createDemoState(), recipe = initial.recipes[0];
  const plan = initial.plans[0];
  plan.meals = []; plan.prep = [{ ...plan.prep[0], recipeId: recipe.id, plannedPortions: 3, status: "planned" }];
  recipe.servings = 3; recipe.ingredients = [{ name: "Chicken", quantity: 300, unit: "g" }, { name: "Rice", quantity: 200, unit: "g" }];
  initial.inventory = [];
  const sent: Record<string, unknown>[] = [];
  function Harness() {
    const [state, setState] = useState(initial);
    return <ShoppingPrepPage state={state} plan={state.plans[0]} focus="shopping" onFocus={async () => {}} demo navigate={vi.fn()} notify={vi.fn()} send={async (type, payload) => { sent.push({ type, ...payload }); setState(current => applyDemoCommand(current, { type, payload, operationId: crypto.randomUUID(), expectedRevision: current.revision }).state); return true; }} />;
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Mark all picked up ✓" }));
  await waitFor(() => expect(screen.getByLabelText("Purchased Chicken 300 g")).toBeChecked());
  expect(screen.getByLabelText("Purchased Rice 200 g")).toBeChecked();
  expect(sent).toHaveLength(1);
  expect(sent[0]).toMatchObject({ type: "shopping.check", checked: true });
  expect(sent[0].keys).toHaveLength(2);
  fireEvent.click(await screen.findByRole("button", { name: "Clear all" }));
  await waitFor(() => expect(screen.getByLabelText("Purchased Chicken 300 g")).not.toBeChecked());
  expect(screen.getByLabelText("Purchased Rice 200 g")).not.toBeChecked();
});
