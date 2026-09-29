import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { blankRecipe } from "@/features/kitchen/recipe-editor";
import { fridgeMatch } from "@/features/kitchen/fridge-match";
import { RecipesPage } from "@/features/kitchen/recipes";
import type { InventoryItem, KitchenState, Recipe } from "@/features/kitchen/types";

afterEach(() => vi.unstubAllGlobals());

const food = (name: string, portions = 1): InventoryItem => ({ id: `stock-${name}`, name, type: "Other", portions, location: "fridge", prepared: false, addedOn: "2026-09-20", priority: false });
const recipe = (id: string, name: string, ingredients: string[]): Recipe => ({ ...blankRecipe(), id, name, ingredients: ingredients.map(n => ({ name: n, quantity: 1, unit: "个" })) });
const page = (state: KitchenState, demo = false) => render(<RecipesPage state={state} plan={null} send={vi.fn().mockResolvedValue(true)} demo={demo} notify={vi.fn()} navigate={vi.fn()} />);
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("what a recipe needs that the fridge has", () => {
  it("counts the foods it uses, not water or seasoning, and only what is left", () => {
    const eggs = recipe("r", "番茄炒蛋", ["鸡蛋", "番茄", "葱", "盐", "水", "油"]);
    expect(fridgeMatch(eggs, [food("土鸡蛋", 6), food("番茄", 0), food("葱花")])).toEqual({ have: 2, total: 3 });
    expect(fridgeMatch(eggs, [])).toEqual({ have: 0, total: 3 });
    expect(fridgeMatch(recipe("s", "盐水", ["盐", "水"]), [food("盐")])).toEqual({ have: 0, total: 0 });
    // A food's English name counts too, for recipes written in English.
    expect(fridgeMatch(recipe("b", "Steamed broccoli", ["Broccoli", "Garlic"]), [{ ...food("西兰花"), nameEn: "Broccoli" }])).toEqual({ have: 1, total: 2 });
  });
});

describe("Uses my fridge", () => {
  it("puts the recipes the fridge can make most of first, and says how much it has", () => {
    const state = { ...createDemoState(), recipes: [recipe("a", "青椒肉丝", ["青椒", "猪肉"]), recipe("b", "番茄炒蛋", ["鸡蛋", "番茄"]), recipe("c", "蛋羹", ["鸡蛋", "虾"])], inventory: [food("鸡蛋", 4), food("番茄", 2)] };
    page(state);
    const names = () => screen.getAllByRole("button", { name: /^Open recipe / }).map(b => b.getAttribute("aria-label"));
    fireEvent.click(screen.getByRole("button", { name: "🧊 Uses my fridge" }));
    expect(screen.getByRole("button", { name: "🧊 Uses my fridge" })).toHaveAttribute("aria-pressed", "true");
    expect(names()).toEqual(["Open recipe 番茄炒蛋", "Open recipe 蛋羹", "Open recipe 青椒肉丝"]);
    const card = screen.getByRole("button", { name: "Open recipe 番茄炒蛋" }).closest("article")!;
    expect(within(card).getByText("🧊 2/2")).toBeInTheDocument();
    expect(within(card).getByTitle("In your fridge: 2 of 2 foods")).toBeInTheDocument();
  });
});

describe("importing a recipe from a link", () => {
  it("reads the link on the server and shows the recipe to review", async () => {
    const fetch = vi.fn().mockResolvedValue(json(200, { recipes: [{ ...recipe("x", "番茄炒蛋", ["鸡蛋"]), source: "https://www.youtube.com/watch?v=abc" }] }));
    vi.stubGlobal("fetch", fetch);
    page(createDemoState());
    fireEvent.click(screen.getByRole("button", { name: "Import recipe" }));
    const dialog = screen.getByRole("dialog", { name: "Import recipes" });
    fireEvent.change(within(dialog).getByLabelText("Recipe link"), { target: { value: " https://www.youtube.com/watch?v=abc " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Read link" }));
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/v1\/kitchen\/import-link$/);
    expect(JSON.parse(fetch.mock.calls[0][1].body as string)).toEqual({ url: "https://www.youtube.com/watch?v=abc" });
    expect(await screen.findByDisplayValue("番茄炒蛋")).toBeInTheDocument();
  });

  it("says to paste the text or a screenshot when the page cannot be read, and keeps the link", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(422, { detail: "This link could not be read. Paste the text or a screenshot instead." })));
    page(createDemoState());
    fireEvent.click(screen.getByRole("button", { name: "Import recipe" }));
    const dialog = screen.getByRole("dialog", { name: "Import recipes" });
    fireEvent.change(within(dialog).getByLabelText("Recipe link"), { target: { value: "https://www.xiaohongshu.com/explore/1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Read link" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Paste the text or a screenshot instead");
    expect(within(dialog).getByLabelText("Recipe link")).toHaveValue("https://www.xiaohongshu.com/explore/1");
  });

  it("only takes web links", () => {
    page(createDemoState());
    fireEvent.click(screen.getByRole("button", { name: "Import recipe" }));
    const dialog = screen.getByRole("dialog", { name: "Import recipes" });
    fireEvent.change(within(dialog).getByLabelText("Recipe link"), { target: { value: "not a link" } });
    expect(within(dialog).getByRole("button", { name: "Read link" })).toBeDisabled();
  });

  it("in the demo, shows a sample from the link without reading it", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    page(createDemoState(), true);
    fireEvent.click(screen.getByRole("button", { name: "Import recipe" }));
    const dialog = screen.getByRole("dialog", { name: "Import recipes" });
    fireEvent.change(within(dialog).getByLabelText("Recipe link"), { target: { value: "https://b23.tv/abc" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Read link" }));
    expect(await screen.findByText(/https:\/\/b23\.tv\/abc/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
});
