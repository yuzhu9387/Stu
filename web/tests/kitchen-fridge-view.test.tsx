import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { FridgePage } from "@/features/kitchen/fridge";
import type { InventoryItem } from "@/features/kitchen/types";

const food = (id: string, name: string, type: InventoryItem["type"], addedOn: string): InventoryItem => ({ id, name, type, portions: 2, location: "Fridge", prepared: false, addedOn, priority: false });

/** A chilled fridge whose boxes were dragged into a household order that is
 * neither by date nor by name. */
function fridge() {
  const state = createDemoState();
  state.inventory = [food("rice", "糙米饭", "Carbs", "2026-09-13"), food("eggs", "鸡蛋", "Protein", "2026-09-19"), food("toast", "全麦吐司", "Carbs", "2026-09-12"), food("tofu", "豆腐", "Protein", "2026-09-15"), food("spinach", "菠菜", "Vegetables", "2026-09-25")];
  const send = vi.fn().mockResolvedValue(true);
  render(<FridgePage state={state} plan={state.plans[0]} send={send} demo notify={vi.fn()} navigate={vi.fn()} />);
  const chilled = screen.getByRole("heading", { name: "🧊 冷藏 Fridge" }).closest("section")!;
  const names = () => within(chilled).getAllByRole("button", { name: /portions/ }).map(b => b.getAttribute("aria-label")!.split(",")[0]);
  const labels = () => [...chilled.querySelectorAll(".kw-shelf-group")].map(h => h.lastChild?.textContent);
  return { state, send, chilled, names, labels };
}

beforeEach(() => localStorage.clear());
afterEach(() => { Reflect.deleteProperty(document, "elementsFromPoint"); });

it("puts each food group on its own shelves, oldest made first", () => {
  const { names, labels } = fridge();
  expect(labels()).toEqual(["Protein", "Carbs", "Vegetables"]);
  expect(names()).toEqual(["豆腐", "鸡蛋", "全麦吐司", "糙米饭", "菠菜"]);
});

it("can show one run in the household's own order, or newest first, and remembers", () => {
  const { names, labels } = fridge();
  fireEvent.change(screen.getByLabelText("Group"), { target: { value: "none" } });
  fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "arranged" } });
  expect(labels()).toEqual([]);
  expect(names()).toEqual(["糙米饭", "鸡蛋", "全麦吐司", "豆腐", "菠菜"]);
  fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "newest" } });
  expect(names()).toEqual(["菠菜", "鸡蛋", "豆腐", "糙米饭", "全麦吐司"]);
  // The plan board reads the same choice.
  expect([localStorage.getItem("stu-board-group"), localStorage.getItem("stu-board-sort")]).toEqual(["none", "newest"]);
});

it("sorted by date, a drag moves a box to the freezer but keeps the household's order", async () => {
  const { state, send } = fridge();
  const freezer = screen.getByRole("heading", { name: "❄️ 冷冻 Freezer" }).closest("section")!;
  Object.defineProperty(document, "elementsFromPoint", { configurable: true, value: () => [freezer] });
  const eggs = screen.getByRole("button", { name: /^鸡蛋, / });
  fireEvent.pointerDown(eggs, { button: 0, pointerType: "mouse", clientX: 10, clientY: 10 });
  fireEvent.pointerMove(window, { clientX: 60, clientY: 80 });
  await act(async () => fireEvent.pointerUp(window, { clientX: 60, clientY: 80 }));
  expect(send).toHaveBeenCalledWith("inventory.arrange", { order: state.inventory.map(i => i.id), moves: [{ id: "eggs", location: "Freezer" }] }, { quiet: true });
});

it("fills each shelf with as many small cards as the compartment is wide", () => {
  // Measure every compartment as 560px wide: five cards to a shelf.
  vi.stubGlobal("ResizeObserver", class { constructor(private callback: () => void) {} observe() { this.callback(); } disconnect() {} });
  const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get() { return (this as HTMLElement).classList.contains("kw-shelves") ? 560 : 0; } });
  try {
    const state = createDemoState();
    state.inventory = Array.from({ length: 7 }, (_, i) => food(`f${i}`, `食物${i}`, "Protein", `2026-09-1${i}`));
    render(<FridgePage state={state} plan={state.plans[0]} send={vi.fn().mockResolvedValue(true)} demo notify={vi.fn()} navigate={vi.fn()} />);
    const chilled = screen.getByRole("heading", { name: "🧊 冷藏 Fridge" }).closest("section")!;
    const shelves = [...chilled.querySelectorAll<HTMLElement>(".kw-shelf")];
    expect(shelves.map(shelf => shelf.querySelectorAll(".kw-food-cell").length)).toEqual([5, 2]);
    expect(shelves[0].style.getPropertyValue("--per-shelf")).toBe("5");
  } finally {
    if (width) Object.defineProperty(HTMLElement.prototype, "clientWidth", width);
    vi.unstubAllGlobals();
  }
});
