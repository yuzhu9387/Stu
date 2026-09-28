import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { CalendarGrid } from "@/features/kitchen/calendar";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { FridgeRail, freePortions, mealOfFood, usePlanBoard, withFood, withoutOne } from "@/features/kitchen/plan-board";
import type { KitchenState, Meal } from "@/features/kitchen/types";

/** The demo week as a draft, with Monday dinner still empty. */
function draft() {
  const state = createDemoState();
  const plan = state.plans[0];
  plan.status = "draft";
  plan.meals = plan.meals.filter(m => m.id !== "meal-0-dinner");
  return state;
}
const rice = (state: KitchenState) => state.inventory.find(i => i.id === "stock-rice")!;
const lunch = (state: KitchenState) => state.plans[0].meals.find(m => m.id === "meal-0-lunch")!;

describe("the plan board's food moves", () => {
  it("counts what this week's meals still to eat already take", () => {
    const state = draft();
    // Wednesday dinner takes 3 rice and 3 broccoli; the meatballs come from prep.
    expect(Object.fromEntries(freePortions(state, state.plans[0]))).toEqual({ "stock-meatballs": 2, "stock-rice": 3, "stock-broccoli": 1 });
    state.plans[0].meals.find(m => m.id === "meal-2-dinner")!.status = "skipped";
    expect(freePortions(state, state.plans[0]).get("stock-rice")).toBe(6);
  });

  it("adds a portion: a new dish with its reheating step, then one more of it", () => {
    const state = draft(), meal = lunch(state);
    const once = withFood(meal, rice(state), state);
    const dish = once.components.at(-1)!;
    expect(dish).toMatchObject({ name: "熟糙米饭", portions: 1, inventoryId: "stock-rice", recipeId: "recipe-rice" });
    expect(once.steps.some(step => step.startsWith("熟糙米饭: "))).toBe(true);
    const twice = withFood(once, rice(state), state);
    expect(twice.components).toHaveLength(once.components.length);
    expect(twice.components.at(-1)!.portions).toBe(2);
  });

  it("takes a portion off, and the dish and its steps at its last one", () => {
    const state = draft(), meal = withFood(withFood(lunch(state), rice(state), state), rice(state), state);
    const id = meal.components.at(-1)!.id;
    const one = withoutOne(meal, id)!;
    expect(one.components.at(-1)!.portions).toBe(1);
    const none = withoutOne(one, id)!;
    expect(none.components.map(c => c.id)).toEqual(lunch(state).components.map(c => c.id));
    expect(none.steps.some(step => step.includes("熟糙米饭"))).toBe(false);
    const alone = mealOfFood("2026-09-21", "dinner", rice(state), state);
    expect(withoutOne(alone, alone.components[0].id)).toBeNull();
  });
});

function Board({ initial }: { initial: KitchenState }) {
  const [state, setState] = useState(initial);
  const plan = state.plans[0];
  const apply = async (type: string, payload: Record<string, unknown>) => setState(current => applyDemoCommand(current, { type, payload, expectedRevision: current.revision, operationId: crypto.randomUUID() }).state);
  const board = usePlanBoard(state, plan, { save: meal => apply("meal.save", { planId: plan.id, meal }), remove: meal => apply("meal.delete", { planId: plan.id, mealId: meal.id }) });
  return <><output aria-label="Meals">{plan.meals.length}</output><FridgeRail {...board.rail} /><CalendarGrid week={plan.weekStart} plan={plan} state={state} selectedId={null} onSelect={() => {}} onAdd={() => {}} onStatus={() => {}} onLike={() => {}} planning slotState={() => "add"} board={board.calendar} />{board.ghost}</>;
}

describe("the plan board", () => {
  afterEach(() => { Reflect.deleteProperty(document, "elementsFromPoint"); });

  it("puts a tapped food on the meal tapped next, and '−' takes it off", async () => {
    render(<Board initial={draft()} />);
    const fridge = screen.getByRole("complementary", { name: "Fridge for this week" });
    fireEvent.click(within(fridge).getByRole("button", { name: "熟糙米饭, 3 of 6 left" }));
    expect(within(fridge).getByRole("button", { name: "熟糙米饭, 3 of 6 left" })).toHaveAttribute("aria-pressed", "true");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Add 熟糙米饭 to Mon, Sep 21 lunch" })));
    expect(within(fridge).getByRole("button", { name: "熟糙米饭, 2 of 6 left" })).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Take one 熟糙米饭 off Mon, Sep 21 lunch" })));
    expect(within(fridge).getByRole("button", { name: "熟糙米饭, 3 of 6 left" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Take one 熟糙米饭 off Mon, Sep 21 lunch" })).not.toBeInTheDocument();
  });

  it("makes a meal of a food put on an empty slot, and lets it go when its last portion leaves", async () => {
    render(<Board initial={draft()} />);
    expect(screen.getByLabelText("Meals")).toHaveTextContent("20");
    fireEvent.click(screen.getByRole("button", { name: "西兰花, 1 of 4 left" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Put 西兰花 in Mon, Sep 21 dinner" })));
    expect(screen.getByLabelText("Meals")).toHaveTextContent("21");
    // The last free broccoli is on the plate now: it cannot be picked again.
    expect(screen.getByRole("button", { name: "西兰花, 0 of 4 left" })).toBeDisabled();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Take one 西兰花 off Mon, Sep 21 dinner" })));
    expect(screen.getByLabelText("Meals")).toHaveTextContent("20");
  });

  it("drops a dragged food on the meal under the pointer, and a dish dragged back into the fridge", async () => {
    render(<Board initial={draft()} />);
    const card = screen.getByRole("button", { name: "Open Mon, Sep 21 lunch" }).closest("article")!;
    let under: Element = card;
    Object.defineProperty(document, "elementsFromPoint", { configurable: true, value: () => [under] });
    const food = screen.getByRole("button", { name: "熟糙米饭, 3 of 6 left" });
    fireEvent.pointerDown(food, { button: 0, pointerType: "mouse", clientX: 10, clientY: 10 });
    fireEvent.pointerMove(window, { clientX: 60, clientY: 80 });
    expect(card).toHaveClass("is-drop-over");
    await act(async () => fireEvent.pointerUp(window, { clientX: 60, clientY: 80 }));
    const chip = within(card).getByRole("button", { name: "Take one 熟糙米饭 off Mon, Sep 21 lunch" }).parentElement!;
    expect(chip).toHaveTextContent("熟糙米饭×1");
    under = screen.getByRole("complementary", { name: "Fridge for this week" });
    fireEvent.pointerDown(chip, { button: 0, pointerType: "mouse", clientX: 60, clientY: 80 });
    fireEvent.pointerMove(window, { clientX: 5, clientY: 5 });
    await act(async () => fireEvent.pointerUp(window, { clientX: 5, clientY: 5 }));
    expect(within(card).queryByRole("button", { name: /Take one 熟糙米饭/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "熟糙米饭, 3 of 6 left" })).toBeInTheDocument();
  });

  it("shows only the meal's own dishes when nothing is picked", () => {
    const state = draft();
    const meal: Meal = lunch(state);
    render(<Board initial={state} />);
    expect(screen.queryByRole("button", { name: `Add 熟糙米饭 to Mon, Sep 21 lunch` })).not.toBeInTheDocument();
    expect(meal.components.some(c => c.inventoryId)).toBe(false);
  });
});
