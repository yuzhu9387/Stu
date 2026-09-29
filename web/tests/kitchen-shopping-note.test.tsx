import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import { FridgePage } from "@/features/kitchen/fridge";
import { parseRow } from "@/features/kitchen/shopping-note";
import type { KitchenState, ShoppingItem } from "@/features/kitchen/types";

const command = (state: KitchenState, type: string, payload: Record<string, unknown>) =>
  applyDemoCommand(state, { type, payload, expectedRevision: state.revision, operationId: crypto.randomUUID() }).state;
const row = (id: string, name: string, quantity?: number, checked = false): ShoppingItem => ({ id, name, ...(quantity === undefined ? {} : { quantity }), checked });

/** The fridge page over a demo kitchen; `latest()` reads what the commands did. */
function kitchen(rows: ShoppingItem[]) {
  let latest: KitchenState = { ...createDemoState(), shoppingList: rows };
  const calls: [string, Record<string, unknown>][] = [];
  function Page() {
    const [state, setState] = useState(latest);
    return <FridgePage state={state} plan={state.plans[0]} demo notify={vi.fn()} navigate={vi.fn()} send={async (type, payload) => { calls.push([type, payload]); latest = command(latest, type, payload); setState(latest); return true; }} />;
  }
  render(<Page />);
  return { calls, latest: () => latest };
}
const openNote = () => fireEvent.click(screen.getByRole("button", { name: /^Shopping note/ }));

describe("a shopping row as typed", () => {
  it("reads a trailing number as the amount", () => {
    expect(parseRow("牛奶 2")).toEqual({ name: "牛奶", quantity: 2 });
    expect(parseRow(" 鸡蛋 ×12 ")).toEqual({ name: "鸡蛋", quantity: 12 });
    expect(parseRow("香蕉")).toEqual({ name: "香蕉" });
    expect(parseRow("维生素D3")).toEqual({ name: "维生素D3" });
    expect(parseRow("  ")).toBeNull();
  });
});

describe("the shopping note on the fridge door", () => {
  it("shows its first few things and how many there are", () => {
    kitchen([row("a", "牛奶", 2), row("b", "鸡蛋"), row("c", "香蕉"), row("d", "面包"), row("e", "酸奶")]);
    const note = screen.getByRole("button", { name: "Shopping note, 5 items" });
    expect(note).toHaveTextContent("牛奶");
    expect(note).toHaveTextContent("香蕉");
    expect(note).not.toHaveTextContent("面包");
    expect(note).toHaveTextContent("+2");
  });

  it("adds a row with its amount, ticks it, and takes one off", async () => {
    const k = kitchen([row("b", "鸡蛋")]);
    openNote();
    const drawer = screen.getByRole("dialog", { name: "🛒 Shopping note" });
    fireEvent.change(within(drawer).getByLabelText("Add to the list"), { target: { value: "牛奶 2" } });
    fireEvent.click(within(drawer).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(k.latest().shoppingList?.map(r => [r.name, r.quantity])).toEqual([["鸡蛋", undefined], ["牛奶", 2]]));
    expect(within(drawer).getByLabelText("Add to the list")).toHaveValue("");
    fireEvent.click(within(drawer).getByRole("checkbox", { name: "Bought 牛奶" }));
    await waitFor(() => expect(k.latest().shoppingList?.find(r => r.name === "牛奶")?.checked).toBe(true));
    fireEvent.click(within(drawer).getByRole("button", { name: "Remove 鸡蛋" }));
    await waitFor(() => expect(k.latest().shoppingList?.map(r => r.name)).toEqual(["牛奶"]));
  });

  it("changes a row's name and amount in place", async () => {
    const k = kitchen([row("a", "牛奶", 2)]);
    openNote();
    const name = screen.getByLabelText("Name of 牛奶");
    fireEvent.change(name, { target: { value: "全脂牛奶" } });
    fireEvent.blur(name);
    await waitFor(() => expect(k.latest().shoppingList?.[0].name).toBe("全脂牛奶"));
    const amount = screen.getByLabelText("Amount of 全脂牛奶");
    fireEvent.change(amount, { target: { value: "3" } });
    fireEvent.blur(amount);
    await waitFor(() => expect(k.latest().shoppingList?.[0].quantity).toBe(3));
  });

  it("puts what was bought in the fridge, one portion each unless a number says, and those rows leave", async () => {
    const k = kitchen([row("a", "牛奶", 2, true), row("b", "鸡蛋", undefined, true), row("c", "面包")]);
    openNote();
    fireEvent.click(screen.getByRole("button", { name: "Put in fridge · 2" }));
    // Stored the way the fridge already stores it, or chosen for something new.
    expect(screen.getByLabelText("Portions of 牛奶")).toHaveValue(2);
    expect(screen.getByLabelText("Portions of 鸡蛋")).toHaveValue(1);
    expect(within(screen.getByRole("group", { name: "Where 牛奶 goes" })).getByRole("button", { name: "🧊 Fridge" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(screen.getByRole("group", { name: "Where 鸡蛋 goes" })).getByRole("button", { name: "❄️ Freezer" }));
    fireEvent.change(screen.getByLabelText("Food group of 牛奶"), { target: { value: "Dairy" } });
    fireEvent.click(screen.getByRole("button", { name: "Put 2 in the fridge" }));
    await waitFor(() => expect(k.calls.at(-1)?.[0]).toBe("shopping.putAway"));
    expect(k.calls.at(-1)?.[1]).toEqual({ items: [{ id: "a", location: "fridge", portions: 2, type: "Dairy" }, { id: "b", location: "freezer", portions: 1, type: "Other" }] });
    expect(k.latest().shoppingList?.map(r => r.name)).toEqual(["面包"]);
    expect(k.latest().inventory.find(i => i.name === "牛奶")).toMatchObject({ type: "Dairy", portions: 2, location: "Fridge", prepared: false });
    expect(k.latest().inventory.find(i => i.name === "鸡蛋")).toMatchObject({ portions: 1, location: "Freezer" });
    expect(await screen.findByRole("button", { name: "Shopping note, 1 item" })).toBeInTheDocument();
  });

  it("a food the fridge already has keeps its group and icon", () => {
    const state = { ...createDemoState(), shoppingList: [row("a", "西兰花", 2, true)] };
    const next = command(state, "shopping.putAway", { items: [{ id: "a", location: "fridge", portions: 2, type: "Other" }] });
    const boxes = next.inventory.filter(i => i.name === "西兰花");
    expect(boxes).toHaveLength(2);
    expect(new Set(boxes.map(b => b.type))).toEqual(new Set(["Vegetables"]));
    expect(next.shoppingList).toEqual([]);
  });
});
