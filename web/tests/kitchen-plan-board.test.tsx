import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CalendarGrid } from "@/features/kitchen/calendar";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { FridgeRail, freePortions, mealOfFood, usePlanBoard, withFood } from "@/features/kitchen/plan-board";
import type { InventoryItem, KitchenState } from "@/features/kitchen/types";

/** The demo week as a draft, with Monday dinner still empty, and a fridge of
 * raw food beside the frozen batches. */
function draft() {
  const state = createDemoState();
  const plan = state.plans[0];
  plan.status = "draft";
  plan.meals = plan.meals.filter(m => m.id !== "meal-0-dinner");
  const raw = (id: string, name: string, type: InventoryItem["type"], addedOn: string): InventoryItem => ({ id, name, type, portions: 2, location: "fridge", prepared: false, addedOn, priority: false });
  state.inventory.push(raw("eggs", "鸡蛋", "Protein", "2026-09-19"), raw("tofu", "豆腐", "Protein", "2026-09-15"), raw("corn", "玉米", "Carbs", "2026-09-18"));
  return state;
}
const rice = (state: KitchenState) => state.inventory.find(i => i.id === "stock-rice")!;
const lunch = (state: KitchenState) => state.plans[0].meals.find(m => m.id === "meal-0-lunch")!;

describe("the plan board's food moves", () => {
  it("counts what this week's meals still to eat already take", () => {
    const state = draft();
    // Wednesday dinner takes 3 rice and 3 broccoli; the meatballs come from prep.
    expect(freePortions(state, state.plans[0]).get("stock-rice")).toBe(3);
    expect(freePortions(state, state.plans[0]).get("stock-broccoli")).toBe(1);
    state.plans[0].meals.find(m => m.id === "meal-2-dinner")!.status = "skipped";
    expect(freePortions(state, state.plans[0]).get("stock-rice")).toBe(6);
  });

  it("adds a portion: a new dish with its reheating step, then one more of it", () => {
    const state = draft(), meal = lunch(state);
    const once = withFood(meal, rice(state), state);
    expect(once.components.at(-1)).toMatchObject({ name: "熟糙米饭", portions: 1, inventoryId: "stock-rice", recipeId: "recipe-rice" });
    expect(once.steps.some(step => step.startsWith("熟糙米饭: "))).toBe(true);
    const twice = withFood(once, rice(state), state);
    expect(twice.components).toHaveLength(once.components.length);
    expect(twice.components.at(-1)!.portions).toBe(2);
    expect(mealOfFood("2026-09-21", "dinner", rice(state), state).components.map(c => c.name)).toEqual(["熟糙米饭"]);
  });
});

function Board({ initial }: { initial: KitchenState }) {
  const [state, setState] = useState(initial);
  const plan = state.plans[0];
  const board = usePlanBoard(state, plan, async meal => setState(current => applyDemoCommand(current, { type: "meal.save", payload: { planId: plan.id, meal }, expectedRevision: current.revision, operationId: crypto.randomUUID() }).state));
  return <><output aria-label="Meals">{plan.meals.length}</output><FridgeRail {...board.rail} /><CalendarGrid week={plan.weekStart} plan={plan} state={state} selectedId={null} onSelect={() => {}} onAdd={() => {}} onStatus={() => {}} onLike={() => {}} planning slotState={() => "add"} board={board.calendar} />{board.ghost}</>;
}

describe("the plan board", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => { Reflect.deleteProperty(document, "elementsFromPoint"); });
  const fridge = () => screen.getByRole("complementary", { name: "Fridge for this week" });

  it("keeps freezer and fridge apart, a food group to each row, oldest made first", () => {
    render(<Board initial={draft()} />);
    const [freezer, chilled] = within(fridge()).getAllByRole("region");
    expect(freezer).toHaveAccessibleName("❄️ 冷冻 Freezer");
    expect(chilled).toHaveAccessibleName("🧊 冷藏 Fridge");
    const protein = within(chilled).getByRole("group", { name: "Protein" });
    expect(within(protein).getAllByRole("button").map(b => b.getAttribute("aria-label"))).toEqual(["豆腐, 2 of 2 left, made 9/15", "鸡蛋, 2 of 2 left, made 9/19"]);
    expect(within(chilled).getByRole("group", { name: "Carbs" })).toHaveTextContent("玉米");
    // Newest first, and no groups: one list per compartment.
    fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "newest" } });
    fireEvent.change(screen.getByLabelText("Group"), { target: { value: "none" } });
    expect(within(chilled).queryByRole("group")).not.toBeInTheDocument();
    expect(within(chilled).getAllByRole("button").map(b => b.getAttribute("aria-label")?.split(",")[0])).toEqual(["鸡蛋", "玉米", "豆腐"]);
    expect(localStorage.getItem("stu-board-sort")).toBe("newest");
  });

  it("puts a tapped food on the meal tapped next, or makes a meal of an empty slot", async () => {
    render(<Board initial={draft()} />);
    fireEvent.click(within(fridge()).getByRole("button", { name: /^熟糙米饭, 3 of 6 left/ }));
    expect(within(fridge()).getByRole("status")).toHaveTextContent("Tap a meal to add 熟糙米饭");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Add 熟糙米饭 to Mon, Sep 21 lunch" })));
    expect(within(fridge()).getByRole("button", { name: /^熟糙米饭, 2 of 6 left/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add 熟糙米饭 to Mon, Sep 21 lunch" })).toHaveTextContent("熟糙米饭");
    expect(screen.getByLabelText("Meals")).toHaveTextContent("20");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Put 熟糙米饭 in Mon, Sep 21 dinner" })));
    expect(screen.getByLabelText("Meals")).toHaveTextContent("21");
  });

  it("drops a dragged food on the meal under the pointer", async () => {
    render(<Board initial={draft()} />);
    const card = screen.getByRole("button", { name: "Open Mon, Sep 21 lunch" }).closest("article")!;
    Object.defineProperty(document, "elementsFromPoint", { configurable: true, value: () => [card] });
    const food = within(fridge()).getByRole("button", { name: /^熟糙米饭, 3 of 6 left/ });
    fireEvent.pointerDown(food, { button: 0, pointerType: "mouse", clientX: 10, clientY: 10 });
    fireEvent.pointerMove(window, { clientX: 60, clientY: 80 });
    expect(card).toHaveClass("is-drop-over");
    await act(async () => fireEvent.pointerUp(window, { clientX: 60, clientY: 80 }));
    expect(within(card).getByRole("button", { name: "Open Mon, Sep 21 lunch" })).toHaveTextContent("熟糙米饭");
    expect(within(fridge()).getByRole("button", { name: /^熟糙米饭, 2 of 6 left/ })).toBeInTheDocument();
  });

  it("offers nothing extra on a card: no food chips, no 'Add from recipes'", () => {
    render(<Board initial={draft()} />);
    expect(screen.queryByRole("button", { name: /^Add a dish to/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Take one/ })).not.toBeInTheDocument();
  });
});
