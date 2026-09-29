import { readFileSync } from "node:fs";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CalendarGrid } from "@/features/kitchen/calendar";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { MealDrawer } from "@/features/kitchen/meal-drawer";
import { planRuleWarnings } from "@/features/kitchen/plan-rules";
import { shoppingList } from "@/features/kitchen/shopping";
import type { KitchenState, Meal } from "@/features/kitchen/types";

function confirmed() {
  const state = createDemoState(), plan = state.plans[0];
  const meal = plan.meals.find(m => m.id === "meal-2-dinner")!;
  return { state, plan, meal };
}
const drawerProps = (state: KitchenState, meal: Meal) => ({ state, plan: state.plans[0], meal, onClose: vi.fn(), onDirty: vi.fn(), onSave: vi.fn().mockResolvedValue(true), onAction: vi.fn().mockResolvedValue(true), onReference: vi.fn(), onRecipe: vi.fn(), busy: false });

describe("a meal that went differently", () => {
  it("is marked Changed from the calendar drawer, with a note if you like", async () => {
    const { state, meal } = confirmed();
    const p = drawerProps(state, meal);
    render(<MealDrawer {...p} />);
    fireEvent.click(screen.getByRole("button", { name: "Mark changed" }));
    const note = screen.getByLabelText("What happened instead? (optional)");
    fireEvent.change(note, { target: { value: "改成了包子" } });
    fireEvent.click(screen.getByRole("button", { name: "Save as changed" }));
    await waitFor(() => expect(p.onAction).toHaveBeenCalledWith("meal.status", { planId: state.plans[0].id, mealId: meal.id, status: "changed", note: "改成了包子" }));
  });

  it("needs no note", async () => {
    const { state, meal } = confirmed();
    const p = drawerProps(state, meal);
    render(<MealDrawer {...p} />);
    fireEvent.click(screen.getByRole("button", { name: "Mark changed" }));
    fireEvent.click(screen.getByRole("button", { name: "Save as changed" }));
    await waitFor(() => expect(p.onAction).toHaveBeenCalledWith("meal.status", { planId: state.plans[0].id, mealId: meal.id, status: "changed" }));
  });

  it("shows its note and can be undone, like a skip", () => {
    const { state, meal } = confirmed();
    const changed: Meal = { ...meal, status: "changed", note: "改成了包子" };
    state.audit.push({ id: "changed-audit", kind: "meal.status", message: "Changed", at: "2026-09-23", ...{ undone: false, undo: { planId: state.plans[0].id, collection: "meals", entityId: meal.id } } });
    const p = drawerProps(state, changed);
    render(<MealDrawer {...p} />);
    expect(screen.getByText("改成了包子")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Undo changed" }));
    expect(p.onAction).toHaveBeenCalledWith("change.undo", { auditId: "changed-audit" });
  });

  it("takes nothing from the fridge in the demo, and the card says Changed", () => {
    const { state, plan, meal } = confirmed();
    const before = state.inventory.map(i => i.portions);
    const next = applyDemoCommand(state, { type: "meal.status", payload: { planId: plan.id, mealId: meal.id, status: "changed", note: "外卖" }, expectedRevision: state.revision, operationId: "c" }).state;
    const saved = next.plans[0].meals.find(m => m.id === meal.id)!;
    expect([saved.status, saved.note]).toEqual(["changed", "外卖"]);
    expect(next.inventory.map(i => i.portions)).toEqual(before);
    render(<CalendarGrid week={plan.weekStart} plan={next.plans[0]} state={next} selectedId={null} onSelect={() => {}} onAdd={() => {}} onStatus={() => {}} onLike={() => {}} />);
    const card = screen.getByRole("button", { name: `Open Wed, Sep 23 dinner` }).closest("article")!;
    expect(within(card).getByText("changed")).toBeInTheDocument();
  });
});

describe("a changed meal on the calendar", () => {
  it("shows its note on the card", () => {
    const { state, plan, meal } = confirmed();
    const next = applyDemoCommand(state, { type: "meal.status", payload: { planId: plan.id, mealId: meal.id, status: "changed", note: "改成了包子" }, expectedRevision: state.revision, operationId: "c" }).state;
    render(<CalendarGrid week={plan.weekStart} plan={next.plans[0]} state={next} selectedId={null} onSelect={() => {}} onAdd={() => {}} onStatus={() => {}} onLike={() => {}} />);
    const card = screen.getByRole("button", { name: "Open Wed, Sep 23 dinner" }).closest("article")!;
    expect(within(card).getByText("改成了包子")).toBeInTheDocument();
  });

  it("gets a stamp of its own, as Done and Skip do (the stamp's word comes from the stylesheet)", () => {
    const css = ["figma.css", "calendar.css", "support.css"].map(name => readFileSync(`src/features/kitchen/${name}`, "utf8")).join("\n");
    expect(css).toMatch(/\.changed \.kw-meal-state:after\{content:"CHANGED"/);
    expect(css).toMatch(/\.changed \.kw-card-slot\{padding-right/);
  });
});

describe("a dish's own details", () => {
  it("are bought and timed when the dish has no recipe, and a changed meal buys nothing", () => {
    const { state, plan } = confirmed();
    const meal = plan.meals.find(m => m.id === "meal-0-lunch")!;
    meal.components = [{ id: "greens", name: "蒜蓉菠菜", type: "Vegetables", portions: 2, ingredients: [{ name: "蒜", quantity: 2, unit: "瓣" }, { name: "盐", quantity: 1, unit: "g" }], activeMinutes: 8, elapsedMinutes: 10 }];
    plan.meals = [meal]; plan.prep = [];
    const rows = shoppingList(state, plan).items.map(i => [i.name, i.required]);
    expect(rows).toEqual([["蒜", 2]]);
    expect(planRuleWarnings(state, plan).some(w => w.id.startsWith("missing-recipe"))).toBe(false);
    meal.status = "changed";
    expect(shoppingList(state, plan).items).toEqual([]);
  });
});
