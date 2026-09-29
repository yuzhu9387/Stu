import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { demoComposition } from "@/features/kitchen/basket";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { FridgePage } from "@/features/kitchen/fridge";
import { PrepPage } from "@/features/kitchen/prep";
import { addToPrep, fridgePrepTask, nextWeekStart, prepPlan } from "@/features/kitchen/prep-from-fridge";
import type { KitchenState, PrepTask } from "@/features/kitchen/types";
import { planningStep } from "@/features/kitchen/workflow";

const command = (state: KitchenState, type: string, payload: Record<string, unknown>) =>
  applyDemoCommand(state, { type, payload, expectedRevision: state.revision, operationId: crypto.randomUUID() }).state;

// A Wednesday: this weekend's prep day belongs to the week of Monday, Oct 5.
const TODAY = "2026-09-30", NEXT = "2026-10-05";
const food = (state: KitchenState, name: string) => state.inventory.find(i => i.name === name)!;
const card = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}, `) });
/** ⌘-click: choose a food without holding it. */
const choose = (name: string) => fireEvent.click(card(name), { metaKey: true });

/** A kitchen whose commands run in the demo engine; `latest()` reads it. */
function kitchen(initial = createDemoState()) {
  let latest = initial;
  const calls: string[] = [];
  const send = async (type: string, payload: Record<string, unknown>) => { calls.push(type); latest = command(latest, type, payload); return true; };
  return { send, calls, latest: () => latest, set: (next: KitchenState) => { latest = next; } };
}

function Fridge({ k }: { k: ReturnType<typeof kitchen> }) {
  const [state, setState] = useState(k.latest());
  const send = async (type: string, payload: Record<string, unknown>) => { await k.send(type, payload); setState(k.latest()); return true; };
  return <FridgePage state={state} plan={state.plans[0]} send={send} demo notify={vi.fn()} navigate={vi.fn()} />;
}

function Prep({ k, week }: { k: ReturnType<typeof kitchen>; week: string }) {
  const [state, setState] = useState(k.latest());
  const send = async (type: string, payload: Record<string, unknown>) => { await k.send(type, payload); setState(k.latest()); return true; };
  return <PrepPage state={state} plan={prepPlan(state.plans, week)} send={send} demo notify={vi.fn()} navigate={vi.fn()} />;
}

/** Next week's draft holding one + Prep dish from rice and broccoli. */
async function prepOnly() {
  const k = kitchen();
  const task = fridgePrepTask(demoComposition([food(k.latest(), "熟糙米饭"), food(k.latest(), "西兰花")], "dinner", 3));
  await addToPrep(k.latest(), task, k.send, TODAY);
  return { k, task };
}

describe("the week a + Prep dish goes to", () => {
  it("is next week, whose prep day is this weekend", () => {
    expect(nextWeekStart("2026-09-30")).toBe(NEXT);
    expect(nextWeekStart("2026-10-03")).toBe(NEXT);
    expect(nextWeekStart("2026-10-04")).toBe(NEXT);
    // On a Monday that week is already under way; the coming weekend is next.
    expect(nextWeekStart("2026-10-05")).toBe("2026-10-12");
  });

  it("is a new draft holding only prep when next week has no plan, and a second + Prep adds to it", async () => {
    const { k, task } = await prepOnly();
    let week = k.latest().plans.filter(p => p.weekStart === NEXT);
    expect(week).toHaveLength(1);
    expect(week[0]).toMatchObject({ status: "draft", meals: [], prep: [{ id: task.id, origin: "fridge", plannedPortions: 0, actualPortions: 0, status: "planned" }] });
    expect(week[0].prep[0].inputs.map(i => i.inventoryId)).toEqual(["stock-rice", "stock-broccoli"]);
    const second = fridgePrepTask(demoComposition([food(k.latest(), "鸡肉丸")], "dinner", 3));
    await addToPrep(k.latest(), second, k.send, TODAY);
    week = k.latest().plans.filter(p => p.weekStart === NEXT);
    expect(week).toHaveLength(1);
    expect(week[0].prep.map(t => t.id)).toEqual([task.id, second.id]);
    expect(k.calls).toEqual(["plan.save", "prep.save"]);
  });

  it("is next week's plan when there is one", async () => {
    const k = kitchen(), plan = k.latest().plans[0];
    const task = fridgePrepTask(demoComposition([food(k.latest(), "西兰花")], "dinner", 3));
    await addToPrep(k.latest(), task, k.send, "2026-09-16");
    expect(k.calls).toEqual(["prep.save"]);
    expect(k.latest().plans.find(p => p.id === plan.id)!.prep.at(-1)).toMatchObject({ id: task.id, origin: "fridge" });
  });

  it("keeps Stu's amounts in the steps, since the dish is not a recipe", () => {
    const k = kitchen();
    const dish = demoComposition([food(k.latest(), "西兰花")], "dinner", 3);
    const task = fridgePrepTask(dish);
    expect(task.recipeId).toBeUndefined();
    expect(task.steps[0]).toMatch(/^食材 Ingredients: 西兰花 100g/);
    expect(task.steps.slice(1)).toEqual(dish.recipe.steps);
    expect(fridgePrepTask(dish, "recipe-broccoli")).toMatchObject({ recipeId: "recipe-broccoli", steps: dish.recipe.steps });
  });
});

describe("🔪 + Prep on the fridge", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-09-30T12:00:00-07:00")); });
  afterEach(() => { vi.useRealTimers(); });

  it("turns the chosen foods into a dish on next week's prep day, not in the recipe book", async () => {
    const k = kitchen(), recipes = k.latest().recipes.length;
    render(<Fridge k={k} />);
    choose("熟糙米饭");
    choose("西兰花");
    const bar = screen.getByRole("toolbar", { name: "Selected foods" });
    expect(bar).toHaveTextContent("2 selected");
    const prep = within(bar).getByRole("button", { name: "🔪 + Prep" });
    expect(prep).toHaveAttribute("title", "Add to prep day");
    fireEvent.click(prep);
    const drawer = screen.getByRole("dialog", { name: "🔪 + Prep" });
    fireEvent.click(within(drawer).getByRole("button", { name: /Make a dish from 2 foods/ }));
    fireEvent.change(await within(drawer).findByLabelText("Dish name"), { target: { value: "米饭西兰花饼" } });
    fireEvent.change(within(drawer).getByLabelText("Portions of 西兰花"), { target: { value: "2" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "Add to prep day" }));
    await waitFor(() => expect(k.latest().plans.some(p => p.weekStart === NEXT)).toBe(true));
    const task = k.latest().plans.find(p => p.weekStart === NEXT)!.prep[0];
    expect(task).toMatchObject({ name: "米饭西兰花饼", origin: "fridge", plannedPortions: 0, inputs: [{ inventoryId: "stock-rice", portions: 1.5 }, { inventoryId: "stock-broccoli", portions: 2 }] });
    expect(task.recipeId).toBeUndefined();
    expect(k.latest().recipes).toHaveLength(recipes);
    expect(k.calls).not.toContain("recipe.save");
    // Done: the selection is cleared and prep day is one tap away.
    expect(await screen.findByText(/米饭西兰花饼 is on prep day/)).toBeVisible();
    expect(screen.queryByRole("toolbar", { name: "Selected foods" })).not.toBeInTheDocument();
  });

  it("can use a recipe instead of Stu's dish", async () => {
    const k = kitchen();
    render(<Fridge k={k} />);
    choose("西兰花");
    fireEvent.click(within(screen.getByRole("toolbar", { name: "Selected foods" })).getByRole("button", { name: "🔪 + Prep" }));
    const drawer = screen.getByRole("dialog", { name: "🔪 + Prep" });
    fireEvent.change(within(drawer).getByLabelText("Or use a recipe"), { target: { value: "recipe-broccoli" } });
    expect(within(drawer).getByLabelText("Dish name")).toHaveValue(k.latest().recipes.find(r => r.id === "recipe-broccoli")!.name);
    fireEvent.click(within(drawer).getByRole("button", { name: "Add to prep day" }));
    await waitFor(() => expect(k.latest().plans.some(p => p.weekStart === NEXT)).toBe(true));
    expect(k.latest().plans.find(p => p.weekStart === NEXT)!.prep[0]).toMatchObject({ recipeId: "recipe-broccoli", origin: "fridge", inputs: [{ inventoryId: "stock-broccoli" }] });
  });

  it("while choosing, a tap picks a food; a food with nothing left cannot be picked; ✕ ends it", () => {
    const state = createDemoState();
    food(state, "鸡肉丸").portions = 0;
    render(<Fridge k={kitchen(state)} />);
    // No corner circles: a chosen card is highlighted instead.
    expect(screen.queryByRole("button", { name: /^Select / })).not.toBeInTheDocument();
    choose("鸡肉丸");
    expect(screen.queryByRole("toolbar", { name: "Selected foods" })).not.toBeInTheDocument();
    choose("熟糙米饭");
    fireEvent.click(card("西兰花"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(card("西兰花")).toHaveAttribute("aria-pressed", "true");
    expect(card("西兰花").closest(".kw-food-cell")).toHaveClass("is-chosen");
    const bar = screen.getByRole("toolbar", { name: "Selected foods" });
    expect(bar).toHaveTextContent("2 selected");
    fireEvent.click(within(bar).getByRole("button", { name: "Clear selection" }));
    expect(screen.queryByRole("toolbar", { name: "Selected foods" })).not.toBeInTheDocument();
    expect(card("西兰花")).not.toHaveAttribute("aria-pressed");
    // Not choosing: a tap opens the food again.
    fireEvent.click(card("西兰花"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("holding a food on the fridge", () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }); });
  afterEach(() => { vi.useRealTimers(); });
  const hold = (name: string, ms: number, pointerType = "mouse") => {
    const target = card(name);
    fireEvent.pointerDown(target, { pointerType, button: 0, clientX: 10, clientY: 10 });
    act(() => { vi.advanceTimersByTime(ms); });
    fireEvent.pointerUp(window, { pointerType, button: 0, clientX: 10, clientY: 10 });
    fireEvent.click(target);
  };

  it("chooses it with a mouse, and a quick click still opens it", () => {
    render(<Fridge k={kitchen()} />);
    hold("西兰花", 500);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "Selected foods" })).toHaveTextContent("1 selected");
    fireEvent.click(within(screen.getByRole("toolbar", { name: "Selected foods" })).getByRole("button", { name: "Clear selection" }));
    hold("西兰花", 100);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("chooses it with a finger too", () => {
    render(<Fridge k={kitchen()} />);
    hold("熟糙米饭", 500, "touch");
    expect(screen.getByRole("toolbar", { name: "Selected foods" })).toHaveTextContent("1 selected");
  });
});

describe("a + Prep dish on prep day", () => {
  it("is done before the week is confirmed, asking only for the extra portions and where they go", async () => {
    const { k, task } = await prepOnly();
    render(<Prep k={k} week={NEXT} />);
    expect(screen.queryByText(/Confirm this plan before recording prep/)).not.toBeInTheDocument();
    expect(screen.getByText("🔪 From the fridge")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "✓ Done" }));
    const extra = screen.getByLabelText("Extra portions");
    expect(extra).toHaveValue(0);
    expect(screen.getByRole("button", { name: "❄️ Freezer" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(extra, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(k.latest().plans.find(p => p.weekStart === NEXT)!.prep[0].status).toBe("completed"));
    const box = k.latest().inventory.find(i => i.id === `prep-${task.id}`)!;
    expect(box).toMatchObject({ name: task.name, portions: 4, location: "Freezer", prepared: true });
    expect(food(k.latest(), "熟糙米饭").portions).toBe(4.5);
    expect(await screen.findByRole("button", { name: "Undo completion" })).toBeInTheDocument();
  });

  it("puts the extra in the fridge when asked, and leaves no box when nothing is extra", async () => {
    const { k, task } = await prepOnly();
    render(<Prep k={k} week={NEXT} />);
    fireEvent.click(screen.getByRole("button", { name: "✓ Done" }));
    fireEvent.click(screen.getByRole("button", { name: "🧊 Fridge" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(k.latest().plans.find(p => p.weekStart === NEXT)!.prep[0].status).toBe("completed"));
    expect(k.latest().inventory.some(i => i.id === `prep-${task.id}`)).toBe(false);
    const withExtra = command(command(k.latest(), "change.undo", { auditId: k.latest().audit.at(-1)!.id }), "prep.status", { planId: k.latest().plans.find(p => p.weekStart === NEXT)!.id, prepId: task.id, status: "completed", actualPortions: 2, location: "fridge" });
    expect(withExtra.inventory.find(i => i.id === `prep-${task.id}`)).toMatchObject({ portions: 2, location: "Fridge" });
  });

  it("can be removed from prep day", async () => {
    const { k } = await prepOnly();
    render(<Prep k={k} week={NEXT} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(k.latest().plans.find(p => p.weekStart === NEXT)!.prep).toEqual([]));
  });

  it("still shows after Stu drafts that week as a new plan", async () => {
    const { k, task } = await prepOnly();
    const drafted = { ...k.latest().plans[0], id: "stu-draft", weekStart: NEXT, status: "draft" as const, meals: [], prep: [] as PrepTask[], basePlanId: undefined, baseVersion: undefined };
    k.set(command(k.latest(), "plan.save", { plan: drafted }));
    expect(prepPlan(k.latest().plans, NEXT)!.id).toBe("stu-draft");
    render(<Prep k={k} week={NEXT} />);
    expect(screen.getByRole("button", { name: new RegExp(task.name) })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "✓ Done" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(k.latest().plans.find(p => p.prep.some(t => t.id === task.id))!.prep[0].status).toBe("completed"));
  });

  it("batch prep still waits for the plan to be confirmed", async () => {
    const { k } = await prepOnly();
    const plan = k.latest().plans.find(p => p.weekStart === NEXT)!;
    const batch = { ...plan.prep[0], id: "batch", origin: undefined };
    const state = command(k.latest(), "prep.save", { planId: plan.id, prep: batch });
    expect(() => command(state, "prep.status", { planId: plan.id, prepId: "batch", status: "completed", actualPortions: 1 })).toThrow(/Confirm the plan/);
  });
});

describe("a superseded version of the week", () => {
  it("cannot cook or undo a + Prep dish that the confirmed version also holds", async () => {
    const { k, task } = await prepOnly();
    const draft = k.latest().plans.find(p => p.weekStart === NEXT)!;
    let state = command(k.latest(), "plan.confirm", { id: draft.id });
    const confirmed = state.plans.find(p => p.id === draft.id)!;
    state = command(state, "plan.save", { plan: { ...confirmed, id: "rev", status: "draft", basePlanId: confirmed.id, baseVersion: confirmed.version } });
    state = command(state, "plan.confirm", { id: "rev" });
    expect(() => command(state, "prep.status", { planId: draft.id, prepId: task.id, status: "completed", actualPortions: 1 })).toThrow(/Confirm the plan/);
    const old = state.plans.find(p => p.id === draft.id)!;
    render(<PrepPage state={state} plan={old} send={vi.fn()} demo notify={vi.fn()} navigate={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "✓ Done" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });
});

describe("a week holding only + Prep dishes", () => {
  it("is not yet planned: its Plan opens at the first step", async () => {
    const { k } = await prepOnly();
    const plan = k.latest().plans.find(p => p.weekStart === NEXT)!;
    expect(k.latest().weeklyPrompts?.find(w => w.weekStart === NEXT)?.workflow).toBeUndefined();
    expect(planningStep(plan, null, undefined)).toBe("preferences");
    // A meal planned by hand makes it a plan.
    const meal = { ...createDemoState().plans[0].meals[0], id: "hand", day: NEXT };
    expect(planningStep({ ...plan, meals: [meal] }, null, undefined)).toBe("adjust");
  });
});
