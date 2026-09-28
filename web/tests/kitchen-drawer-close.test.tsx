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

  it("asks first, next to the close button, when the recipe form was changed", () => {
    const props = drawer();
    fireEvent.click(screen.getByRole("button", { name: "Save to recipe 📖" }));
    fireEvent.change(screen.getByLabelText("Recipe name"), { target: { value: "香煎三文鱼块" } });
    fireEvent.click(screen.getByLabelText("Close drawer"));
    expect(props.onClose).not.toHaveBeenCalled();
    const prompt = screen.getByRole("alert");
    expect(prompt).toHaveTextContent("Discard these recipe edits?");
    // Right under the header, not below the form, with the choice in focus.
    expect(prompt.closest("footer")).toBeNull();
    expect(prompt.contains(document.activeElement)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard recipe edits" }));
    expect(screen.queryByRole("heading", { name: "Edit and add recipe" })).not.toBeInTheDocument();
  });

  it("asks about unsaved meal edits at the top, and discarding closes", () => {
    const props = drawer();
    fireEvent.click(screen.getByRole("button", { name: "Edit meal" }));
    fireEvent.change(screen.getAllByLabelText("Portions")[0], { target: { value: "5" } });
    fireEvent.click(screen.getByLabelText("Close drawer"));
    const prompt = screen.getByRole("alert");
    expect(prompt).toHaveTextContent("Keep your changes?");
    expect(prompt.closest("footer")).toBeNull();
    expect(prompt.contains(document.activeElement)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(props.onClose).toHaveBeenCalled();
  });
});
