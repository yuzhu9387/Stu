import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { MealDrawer } from "@/features/kitchen/meal-drawer";

/** A dinner whose dish has no recipe yet, so "Save to recipe" is offered. */
function drawer() {
  const state = createDemoState(), plan = state.plans[0];
  const meal = plan.meals.find(m => m.id === "meal-1-dinner")!;
  const props = { state, plan, meal, onClose: vi.fn(), onDirty: vi.fn(), onSave: vi.fn().mockResolvedValue(true), onAction: vi.fn().mockResolvedValue(true), onReference: vi.fn(), onRecipe: vi.fn(), busy: false };
  render(<MealDrawer {...props} />);
  return props;
}

describe("closing the meal drawer", () => {
  it("closes from the recipe form when nothing was typed in it", () => {
    const props = drawer();
    fireEvent.click(screen.getByRole("button", { name: "Save to recipe 📖" }));
    expect(screen.getByRole("heading", { name: "Edit and add recipe" })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Close drawer"));
    expect(props.onClose).toHaveBeenCalled();
  });

  it("closes from the recipe form even after typing, dropping the edits", () => {
    const props = drawer();
    fireEvent.click(screen.getByRole("button", { name: "Save to recipe 📖" }));
    fireEvent.change(screen.getByLabelText("Recipe name"), { target: { value: "香煎三文鱼块" } });
    fireEvent.click(screen.getByLabelText("Close drawer"));
    expect(props.onClose).toHaveBeenCalled();
    expect(props.onSave).not.toHaveBeenCalled();
  });

  it("asks on Escape when the recipe form was changed, right under the header", () => {
    const props = drawer();
    fireEvent.click(screen.getByRole("button", { name: "Save to recipe 📖" }));
    fireEvent.change(screen.getByLabelText("Recipe name"), { target: { value: "香煎三文鱼块" } });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onClose).not.toHaveBeenCalled();
    const prompt = screen.getByRole("alert");
    expect(prompt).toHaveTextContent("Discard these recipe edits?");
    expect(prompt.closest("footer")).toBeNull();
    expect(prompt.contains(document.activeElement)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard recipe edits" }));
    expect(screen.queryByRole("heading", { name: "Edit and add recipe" })).not.toBeInTheDocument();
  });

  it("closes with unsaved meal edits, even ones that could not be saved", () => {
    const props = drawer();
    fireEvent.click(screen.getByRole("button", { name: "Edit meal" }));
    // Every dish taken off: Save would refuse this meal.
    for (const remove of screen.getAllByRole("button", { name: /^Remove / })) fireEvent.click(remove);
    fireEvent.keyDown(document, { key: "Escape" });
    const prompt = screen.getByRole("alert");
    expect(prompt).toHaveTextContent("Keep your changes?");
    expect(prompt.contains(document.activeElement)).toBe(true);
    // With the question showing, the close button still just closes.
    fireEvent.click(screen.getByLabelText("Close drawer"));
    expect(props.onClose).toHaveBeenCalled();
    expect(props.onDirty).toHaveBeenLastCalledWith(false);
    expect(props.onSave).not.toHaveBeenCalled();
  });
});
