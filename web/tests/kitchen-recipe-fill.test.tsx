import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { RecipesPage } from "@/features/kitchen/recipes";
import type { Recipe } from "@/features/kitchen/types";

afterEach(() => vi.unstubAllGlobals());

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** A new recipe with only its name written, saved from the Recipe Book. */
async function saveNamedOnly(demo = false) {
  const send = vi.fn().mockResolvedValue(true);
  render(<RecipesPage state={createDemoState()} plan={null} send={send} demo={demo} notify={vi.fn()} navigate={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Add recipe" }));
  fireEvent.change(screen.getByLabelText("Recipe name"), { target: { value: "蒜蓉西兰花" } });
  const save = screen.getByRole("button", { name: /Save recipe/ });
  expect(save).toHaveTextContent("Stu fills 2 blanks");
  fireEvent.click(save);
  await waitFor(() => expect(send).toHaveBeenCalledWith("recipe.save", expect.anything()));
  return send.mock.calls.find(call => call[0] === "recipe.save")![1].recipe as Recipe;
}

describe("a recipe left incomplete", () => {
  it("has its blanks filled by Stu on save, through the same fill as a meal", async () => {
    // Stu answers for the dish it was asked about, by its id.
    const fetch = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => json(200, { dishes: [{ id: JSON.parse(init.body as string).dishes[0].id, type: "Vegetables", ingredients: [{ name: "西兰花", quantity: 300, unit: "g" }, { name: "蒜", quantity: 3, unit: "瓣" }], steps: ["西兰花焯水", "蒜末爆香后翻炒"], activeMinutes: 10, elapsedMinutes: 12 }] }));
    vi.stubGlobal("fetch", fetch);
    const recipe = await saveNamedOnly();
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/v1\/kitchen\/fill$/);
    const asked = JSON.parse(fetch.mock.calls[0][1].body as string);
    expect(asked.dishes[0]).toMatchObject({ name: "蒜蓉西兰花" });
    expect(asked.dishes[0].ingredients).toBeUndefined();
    expect(asked.dishes[0].steps).toBeUndefined();
    expect(recipe).toMatchObject({ name: "蒜蓉西兰花", steps: ["西兰花焯水", "蒜末爆香后翻炒"], incomplete: false });
    expect(recipe.ingredients.map(i => i.name)).toEqual(["西兰花", "蒜"]);
  });

  it("is still saved, marked for review, when Stu cannot fill it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(503, { detail: "Stu is not available right now." })));
    const recipe = await saveNamedOnly();
    expect(recipe).toMatchObject({ name: "蒜蓉西兰花", ingredients: [], steps: [], incomplete: true });
  });

  it("in the demo is filled without asking the server", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const recipe = await saveNamedOnly(true);
    expect(fetch).not.toHaveBeenCalled();
    expect(recipe.ingredients.length).toBeGreaterThan(0);
    expect(recipe.steps.length).toBeGreaterThan(0);
    expect(recipe.incomplete).toBe(false);
  });
});
