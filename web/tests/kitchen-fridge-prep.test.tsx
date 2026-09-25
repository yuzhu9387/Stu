import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { FridgePage } from "@/features/kitchen/fridge";
import { PrepPage } from "@/features/kitchen/prep";
import { ShoppingPrepPage } from "@/features/kitchen/shopping-prep";
import type { KitchenState } from "@/features/kitchen/types";

const command = (state: KitchenState, type: string, payload: Record<string, unknown>) =>
  applyDemoCommand(state, { type, payload, expectedRevision: state.revision, operationId: crypto.randomUUID() }).state;

it("adds a dish from the recipes in a small popup", async () => {
  const state = createDemoState(), plan = state.plans[0], recipe = state.recipes.find(r => !r.incomplete)!;
  const send = vi.fn().mockResolvedValue(true);
  render(<PrepPage state={state} plan={plan} send={send} demo notify={vi.fn()} navigate={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "+ Add prep task" }));
  const popup = screen.getByRole("dialog", { name: "Add prep task" });
  expect(within(popup).getByRole("button", { name: "Add dish" })).toBeDisabled();
  fireEvent.click(within(popup).getByRole("option", { name: new RegExp(recipe.name) }));
  fireEvent.click(within(popup).getByRole("button", { name: "Add dish" }));
  await waitFor(() => expect(send).toHaveBeenCalledWith("prep.save", expect.objectContaining({
    prep: expect.objectContaining({ name: recipe.name, recipeId: recipe.id, plannedPortions: recipe.servings, steps: recipe.steps, status: "planned" }),
  })));
});

it("adds a quick task with just a title and a description, which makes no food", async () => {
  const state = createDemoState(), plan = state.plans[0];
  const send = vi.fn().mockResolvedValue(true);
  render(<PrepPage state={state} plan={plan} send={send} demo notify={vi.fn()} navigate={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "+ Add prep task" }));
  const popup = screen.getByRole("dialog", { name: "Add prep task" });
  fireEvent.click(within(popup).getByRole("tab", { name: "📝 Quick task" }));
  fireEvent.change(within(popup).getByLabelText("Title"), { target: { value: "Thaw the beef" } });
  fireEvent.change(within(popup).getByLabelText("Description"), { target: { value: "Move it to the fridge\nOvernight" } });
  fireEvent.click(within(popup).getByRole("button", { name: "Add task" }));
  await waitFor(() => expect(send).toHaveBeenCalledWith("prep.save", expect.objectContaining({
    prep: expect.objectContaining({ name: "Thaw the beef", plannedPortions: 0, steps: ["Move it to the fridge", "Overnight"] }),
  })));
  expect(send.mock.calls[0][1].prep.recipeId).toBeUndefined();
  // Finishing a quick task adds nothing to the fridge.
  const saved = command(state, "prep.save", { planId: plan.id, prep: send.mock.calls[0][1].prep });
  const done = command(saved, "prep.status", { planId: plan.id, prepId: send.mock.calls[0][1].prep.id, status: "completed", actualPortions: 0 });
  expect(done.inventory).toHaveLength(saved.inventory.length);
});

it("shows whether each box is cooked ahead or raw, and cooked dishes land in the freezer", () => {
  const state = createDemoState();
  const plan = state.plans[0], task = plan.prep.find(t => t.recipeId)!;
  task.outputInventoryId = undefined;
  const done = command(state, "prep.status", { planId: plan.id, prepId: task.id, status: "completed" });
  const output = done.inventory.find(i => i.id === done.plans[0].prep.find(t => t.id === task.id)!.outputInventoryId)!;
  expect(output.location).toBe("Freezer");
  done.inventory.push({ ...done.inventory[0], id: "raw-eggs", name: "鸡蛋", prepared: false, location: "Fridge", recipeId: undefined });
  render(<FridgePage state={done} plan={done.plans[0]} send={vi.fn()} demo notify={vi.fn()} navigate={vi.fn()} />);
  const freezer = document.querySelector("[data-compartment=freezer]") as HTMLElement;
  const boxes = within(freezer).getAllByRole("button", { name: new RegExp(`^${output.name}.*prepared$`) });
  expect(boxes.length).toBeGreaterThan(0);
  boxes.forEach(box => expect(box).toHaveTextContent("半成品"));
  const raw = done.inventory.find(i => !i.prepared)!;
  expect(screen.getByRole("button", { name: new RegExp(`^${raw.name}.*raw$`) })).toHaveTextContent("生食");
});

it("rearranges the fridge in one step: a new order and a box moved to the other compartment", () => {
  const state = createDemoState();
  const ids = state.inventory.map(i => i.id), moved = ids[0];
  const next = command(state, "inventory.arrange", { order: [...ids].reverse(), moves: [{ id: moved, location: "Freezer" }] });
  expect(next.inventory.map(i => i.id)).toEqual([...ids].reverse());
  expect(next.inventory.find(i => i.id === moved)!.location).toBe("Freezer");
  expect(next.inventory.map(i => i.portions).sort()).toEqual(state.inventory.map(i => i.portions).sort());
  expect(() => command(state, "inventory.arrange", { order: ids.slice(1) })).toThrow();
});

it("puts what was picked up into the chilled fridge as raw food, once", async () => {
  const initial = createDemoState(), recipe = initial.recipes[0], plan = initial.plans[0];
  plan.meals = []; plan.prep = [{ ...plan.prep[0], recipeId: recipe.id, plannedPortions: 3, status: "planned" }];
  recipe.servings = 3; recipe.ingredients = [{ name: "Chicken", quantity: 300, unit: "g" }, { name: "Carrot", quantity: 2, unit: "pcs" }];
  initial.inventory = [];
  let latest = initial;
  function Harness() {
    const [state, setState] = useState(initial);
    return <ShoppingPrepPage state={state} plan={state.plans[0]} focus="shopping" onFocus={async () => {}} demo navigate={vi.fn()} notify={vi.fn()} send={async (type, payload) => { latest = command(latest, type, payload); setState(latest); return true; }} />;
  }
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Update fridge 🧊" }));
  expect(await screen.findByText("Tick what you picked up first, then update the fridge.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Mark all picked up ✓" }));
  fireEvent.click(await screen.findByRole("button", { name: "Update fridge · 2 🧊" }));
  await screen.findByText(/Added 2 items to the chilled fridge/);
  const chicken = latest.inventory.find(i => i.name === "Chicken")!;
  expect(chicken).toMatchObject({ location: "Fridge", prepared: false, portions: 1, portionGrams: 300 });
  expect(latest.inventory.find(i => i.name === "Carrot")).toMatchObject({ location: "Fridge", prepared: false, portions: 2 });
  // Nothing is added twice.
  const count = latest.inventory.length;
  fireEvent.click(screen.getByRole("button", { name: "Update fridge 🧊" }));
  await screen.findByText("Tick what you picked up first, then update the fridge.");
  expect(latest.inventory).toHaveLength(count);
});

it("removes a box straight from its corner ×, without opening it", async () => {
  const state = createDemoState(), item = state.inventory[0];
  const send = vi.fn().mockResolvedValue(true);
  render(<FridgePage state={state} plan={state.plans[0]} send={send} demo notify={vi.fn()} navigate={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: `Remove ${item.name}` }));
  await waitFor(() => expect(send).toHaveBeenCalledWith("inventory.delete", { id: item.id }, { quiet: true }));
  expect(send).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("renames a food from its dialog", async () => {
  const state = createDemoState(), item = state.inventory[0];
  const send = vi.fn().mockResolvedValue(true);
  render(<FridgePage state={state} plan={state.plans[0]} send={send} demo notify={vi.fn()} navigate={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${item.name}, `) }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "全麦面包" } });
  fireEvent.click(screen.getByRole("button", { name: "Save food" }));
  await waitFor(() => expect(send).toHaveBeenCalledWith("inventory.save", { item: expect.objectContaining({ id: item.id, name: "全麦面包" }) }));
  const renamed = command(state, "inventory.save", send.mock.calls[0][1]);
  expect(renamed.inventory.find(i => i.id === item.id)!.name).toBe("全麦面包");
});

it("shows each dish's progress as a bar, not a checkbox, filled by the steps ticked", () => {
  const state = createDemoState(), plan = state.plans[0];
  const task = plan.prep.find(t => t.status === "planned" && t.steps.length >= 2)!;
  localStorage.removeItem(`stu-prep-steps:${plan.id}`);
  const { container } = render(<PrepPage state={state} plan={plan} send={vi.fn()} demo notify={vi.fn()} navigate={vi.fn()} />);
  expect(container.querySelector(".kw-dish-check")).toBeNull();
  const row = screen.getAllByRole("button", { name: new RegExp(task.name) }).find(b => b.classList.contains("kw-dish-row"))!;
  const bar = () => row.querySelector<HTMLElement>(".kw-dish-progress>span")!.style.width;
  expect(bar()).toBe("0%");
  fireEvent.click(row);
  const steps = within(screen.getByRole("article")).getAllByRole("checkbox");
  fireEvent.click(steps[0]);
  expect(bar()).toBe(`${Math.round(100 / task.steps.length)}%`);
  expect(row).toHaveTextContent(`${Math.round(100 / task.steps.length)}% done`);
});

it("undoing a finished dish takes its new box out of the fridge again", () => {
  const state = createDemoState(), plan = state.plans[0];
  plan.status = "confirmed";
  const task = plan.prep.find(t => t.status === "planned" && !t.dependencies.length)!;
  task.outputInventoryId = undefined; task.inputs = [];
  const done = command(state, "prep.status", { planId: plan.id, prepId: task.id, status: "completed" });
  const box = `prep-${task.id}`;
  expect(done.inventory.find(i => i.id === box)).toMatchObject({ location: "Freezer" });
  const undone = command(done, "change.undo", { auditId: done.audit.at(-1)!.id });
  expect(undone.inventory.map(i => i.id)).toEqual(state.inventory.map(i => i.id));
  expect(undone.plans[0].prep.find(t => t.id === task.id)).toMatchObject({ status: "planned" });
});

it("keeps a box a meal still needs, and lets go of one only past meals used", () => {
  const state = createDemoState(), plan = state.plans[0];
  const meal = plan.meals.find(m => m.components.some(c => c.inventoryId))!, component = meal.components.find(c => c.inventoryId)!;
  const item = state.inventory.find(i => i.id === component.inventoryId)!;
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: state.settings.timezone }).format(new Date());
  meal.status = "planned"; meal.day = today;
  expect(() => command(state, "inventory.delete", { id: item.id })).toThrow(new RegExp(`${item.name} is planned for .* ${meal.slot}\\. Replace it in that meal first`));
  // Eaten already: the meals only remember where their food came from.
  plan.meals.filter(m => m.components.some(c => c.inventoryId === item.id)).forEach(m => { m.status = "completed"; });
  const removed = command(state, "inventory.delete", { id: item.id });
  expect(removed.inventory.some(i => i.id === item.id)).toBe(false);
  expect(removed.plans[0].meals.find(m => m.id === meal.id)!.components.find(c => c.id === component.id)!.inventoryId).toBeUndefined();
});
