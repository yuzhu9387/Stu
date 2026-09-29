import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { blanks } from "@/features/kitchen/fill";
import { MealDrawer } from "@/features/kitchen/meal-drawer";
import type { KitchenState, Meal, Recipe } from "@/features/kitchen/types";

/** A draft dinner: rice from a recipe, and a spinach dish written by hand. */
function draft() {
  const state = createDemoState(), plan = state.plans[0];
  plan.status = "draft";
  const rice = state.recipes.find(r => r.id === "recipe-rice")!;
  const meal: Meal = { ...plan.meals.find(m => m.id === "meal-2-dinner")!, components: [
    { id: "rice", name: rice.name, type: "Carbs", portions: 1, recipeId: rice.id },
    { id: "greens", name: "蒜蓉菠菜", type: "Vegetables", portions: 1 },
  ], steps: [`${rice.name}: 加热`] };
  plan.meals = plan.meals.map(m => m.id === meal.id ? meal : m);
  return { state, plan, meal, rice };
}
const props = (state: KitchenState, meal: Meal, planning = true) => ({ state, plan: state.plans[0], meal, planning, onClose: vi.fn(), onDirty: vi.fn(), onSave: vi.fn().mockResolvedValue(true), onAction: vi.fn().mockResolvedValue(true), onReference: vi.fn(), onRecipe: vi.fn(), busy: false });
const filled = { dishes: [{ id: "greens", type: "Vegetables", secondaryTypes: [], ingredients: [{ name: "菠菜", quantity: 200, unit: "g" }], steps: ["焯水", "蒜末炒香下菠菜"], activeMinutes: 8, elapsedMinutes: 10 }] };

afterEach(() => vi.unstubAllGlobals());

describe("the plan drawer", () => {
  it("opens straight into editing, a card per dish", () => {
    const { state, meal, rice } = draft();
    render(<MealDrawer {...props(state, meal)} />);
    expect(screen.getByRole("heading", { name: "Edit meal" })).toBeInTheDocument();
    const riceCard = screen.getByRole("group", { name: `Dish ${rice.name}` });
    // A recipe's own ingredients and time, as the recipe has them.
    expect(within(riceCard).getByText(rice.ingredients[0].name, { exact: false })).toBeInTheDocument();
    expect(within(riceCard).getByText(`${rice.activeMinutes} min active · from the recipe`)).toBeInTheDocument();
    const greens = screen.getByRole("group", { name: "Dish 蒜蓉菠菜" });
    expect(within(greens).getByLabelText("Source for 蒜蓉菠菜")).toBeInTheDocument();
    expect(within(greens).getByLabelText("Portions")).toHaveValue(1);
    expect(within(greens).getByLabelText("Food group")).toHaveValue("Vegetables");
    expect(within(greens).getByRole("group", { name: "Also contains, 蒜蓉菠菜" })).toBeInTheDocument();
    expect(within(greens).getByLabelText("Steps for 蒜蓉菠菜")).toBeInTheDocument();
    expect(within(greens).getByLabelText("Prep time (min)")).toBeInTheDocument();
    // Lock and reference stay at hand while planning.
    expect(screen.getByRole("button", { name: "Lock this meal every week" })).toBeInTheDocument();
  });

  it("counts what Stu will fill: a hand-written dish's ingredients, steps and time", () => {
    const { state, meal } = draft();
    expect(blanks(meal, state)).toEqual({ count: 3, dishes: [{ id: "greens", name: "蒜蓉菠菜", portions: 1, type: "Vegetables" }] });
    render(<MealDrawer {...props(state, meal)} />);
    expect(screen.getByRole("button", { name: /Save changes/ })).toHaveTextContent("Stu fills 3 blanks");
  });

  it("asks Stu for the blanks on save and keeps them with the meal, not the recipe book", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(filled), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    const { state, meal } = draft();
    const p = props(state, meal);
    render(<MealDrawer {...p} />);
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
    await waitFor(() => expect(p.onSave).toHaveBeenCalled());
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/v1\/kitchen\/fill$/);
    expect(JSON.parse(fetch.mock.calls[0][1].body as string)).toMatchObject({ slot: "dinner", dishes: [{ id: "greens", name: "蒜蓉菠菜" }] });
    const [saved, , recipes] = p.onSave.mock.calls[0] as [Meal, Meal, Recipe[] | undefined];
    const greens = saved.components.find(c => c.id === "greens")!;
    expect(greens).toMatchObject({ ingredients: [{ name: "菠菜", quantity: 200, unit: "g" }], activeMinutes: 8, elapsedMinutes: 10 });
    expect(greens.recipeId).toBeUndefined();
    expect(saved.steps).toEqual(expect.arrayContaining(["蒜蓉菠菜: 焯水", "蒜蓉菠菜: 蒜末炒香下菠菜"]));
    expect(recipes ?? []).toEqual([]);
  });

  it("shows Stu's steps in the dish after saving, and typing adds to them", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(filled), { status: 200, headers: { "content-type": "application/json" } })));
    const { state, meal } = draft();
    const p = props(state, meal);
    render(<MealDrawer {...p} />);
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
    await waitFor(() => expect(p.onSave).toHaveBeenCalled());
    const steps = await screen.findByLabelText("Steps for 蒜蓉菠菜");
    await waitFor(() => expect(steps).toHaveValue("焯水\n蒜末炒香下菠菜"));
    fireEvent.change(steps, { target: { value: "焯水\n蒜末炒香下菠菜\n出锅 " } });
    expect(steps).toHaveValue("焯水\n蒜末炒香下菠菜\n出锅 ");
  });

  it("drops an ingredient row left empty, so Stu fills the ingredients instead", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(filled), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    const { state, meal } = draft();
    meal.components[1] = { ...meal.components[1], ingredients: [{ name: " ", quantity: 1, unit: "" }] };
    const p = props(state, meal);
    render(<MealDrawer {...p} />);
    expect(screen.getByRole("button", { name: /Save changes/ })).toHaveTextContent("Stu fills 3 blanks");
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
    await waitFor(() => expect(p.onSave).toHaveBeenCalled());
    expect(JSON.parse(fetch.mock.calls[0][1].body as string).dishes[0].ingredients).toBeUndefined();
    const greens = (p.onSave.mock.calls[0][0] as Meal).components.find(c => c.id === "greens")!;
    expect(greens.ingredients).toEqual([{ name: "菠菜", quantity: 200, unit: "g" }]);
  });

  it("still saves when Stu cannot fill, blanks left blank", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const { state, meal } = draft();
    const p = props(state, meal);
    render(<MealDrawer {...p} />);
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
    await waitFor(() => expect(p.onSave).toHaveBeenCalled());
    const greens = (p.onSave.mock.calls[0][0] as Meal).components.find(c => c.id === "greens")!;
    expect(greens.ingredients).toBeUndefined();
  });

  it("keeps a hand-written ingredient and time as written", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const { state, meal } = draft();
    meal.components[1] = { ...meal.components[1], ingredients: [{ name: "菠菜", quantity: 150, unit: "g" }], activeMinutes: 6 };
    meal.steps = [...meal.steps, "蒜蓉菠菜: 炒"];
    const p = props(state, meal);
    render(<MealDrawer {...p} />);
    expect(screen.getByRole("button", { name: /Save changes/ })).not.toHaveTextContent("Stu fills");
    fireEvent.change(screen.getByLabelText("Prep time (min)"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: /Save changes/ }));
    await waitFor(() => expect(p.onSave).toHaveBeenCalled());
    expect(fetch).not.toHaveBeenCalled();
    expect((p.onSave.mock.calls[0][0] as Meal).components[1]).toMatchObject({ ingredients: [{ name: "菠菜", quantity: 150, unit: "g" }], activeMinutes: 7 });
  });

  it("keeps Save to recipe for a dish written here, starting from the dish's own details", () => {
    const { state, meal } = draft();
    meal.components[1] = { ...meal.components[1], ingredients: [{ name: "菠菜", quantity: 150, unit: "g" }], activeMinutes: 6, elapsedMinutes: 9 };
    meal.steps = [...meal.steps, "蒜蓉菠菜: 焯水", "蒜蓉菠菜: 炒"];
    render(<MealDrawer {...props(state, meal)} />);
    expect(within(screen.getByRole("group", { name: `Dish ${state.recipes.find(r => r.id === "recipe-rice")!.name}` })).queryByRole("button", { name: "Save to recipe 📖" })).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Dish 蒜蓉菠菜" })).getByRole("button", { name: "Save to recipe 📖" }));
    expect(screen.getByRole("heading", { name: "Edit and add recipe" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("菠菜")).toBeInTheDocument();
    expect(screen.getByDisplayValue("150")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/焯水[\s\S]*炒/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("6")).toBeInTheDocument();
  });

  it("the calendar drawer lists a dish's own ingredients too", () => {
    const { state, meal } = draft();
    meal.components[1] = { ...meal.components[1], ingredients: [{ name: "菠菜", quantity: 200, unit: "g" }] };
    render(<MealDrawer {...props(state, meal, false)} />);
    const list = screen.getByRole("heading", { name: "食材清单 Ingredients" }).closest("section")!;
    expect(within(list).getByText("菠菜", { exact: false })).toBeInTheDocument();
  });

  it("the calendar drawer still opens on the cooking view", () => {
    const { state, meal } = draft();
    render(<MealDrawer {...props(state, meal, false)} />);
    expect(screen.queryByRole("heading", { name: "Edit meal" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "简单步骤 Quick Steps" })).toBeInTheDocument();
  });
});
