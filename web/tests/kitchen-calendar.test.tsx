import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CalendarGrid } from "@/features/kitchen/calendar";
import { createDemoState } from "@/features/kitchen/data";

function setup() {
  const state = createDemoState();
  const plan = state.plans[0];
  return { week: plan.weekStart, plan, state, selectedId: "meal-2-dinner", onSelect: vi.fn(), onAdd: vi.fn(), onStatus: vi.fn(), onLike: vi.fn(), onReplace: vi.fn(), onReference: vi.fn() };
}

describe("calendar meal cards", () => {
  it("labels each date, shows hands-on time and real planned prep sources", () => {
    const props = setup();
    render(<CalendarGrid {...props}/>);
    expect(screen.getByRole("region",{name:"Monday, Sep 21"})).toBeVisible();
    expect(screen.getByRole("region",{name:"Sunday, Sep 27"})).toBeVisible();
    const card = screen.getByLabelText(/^Open Wed.*dinner$/).closest("article")!;
    expect(within(card).getByText("鸡肉丸 + 熟糙米饭 + 西兰花")).toBeVisible();
    expect(within(card).getByText("8 min")).toBeVisible();
    expect(within(card).getByText(/Planned prep/)).toBeVisible();
    expect(screen.getByLabelText(/^Open Wed.*dinner$/)).toHaveAttribute("title",expect.stringContaining("12 min elapsed"));
  });

  it("distinguishes existing chilled stock, freezer stock, fresh meals and missing stock", () => {
    const props = setup();
    const breakfast = props.plan.meals.find(meal => meal.id === "meal-0-breakfast")!;
    breakfast.components = [{ id: "fridge", name: "Chilled oats", type: "Carbs", portions: 1, inventoryId: "chilled-oats" }];
    props.state.inventory.push({ id: "chilled-oats", name: "Chilled oats", type: "Carbs", portions: 3, location: "Fridge", prepared: true, addedOn: "2026-09-20", priority: false });
    const lunch = props.plan.meals.find(meal => meal.id === "meal-0-lunch")!;
    lunch.components = [{ id: "frozen", name: "Frozen rice", type: "Carbs", portions: 1, inventoryId: "stock-rice" }];
    const dinner = props.plan.meals.find(meal => meal.id === "meal-0-dinner")!;
    dinner.components = [{ id: "missing", name: "Missing food", type: "Other", portions: 1, inventoryId: "missing" }];
    render(<CalendarGrid {...props}/>);
    const card = (name: RegExp) => screen.getByLabelText(name).closest("article")!;
    expect(within(card(/^Open Mon.*breakfast$/)).getByText(/From fridge/)).toBeVisible();
    expect(within(card(/^Open Mon.*lunch$/)).getByText(/From freezer/)).toBeVisible();
    expect(within(card(/^Open Mon.*dinner$/)).getByText(/Check stock/)).toBeVisible();
    expect(within(card(/^Open Tue.*breakfast$/)).getByText(/Fresh/)).toBeVisible();
    expect(screen.queryByText(/Pantry/)).not.toBeInTheDocument();
  });

  it("keeps replace and chat independent from opening or completing the meal", () => {
    const props = setup();
    render(<CalendarGrid {...props}/>);
    const meal = props.plan.meals.find(meal => meal.id === "meal-2-dinner")!;
    fireEvent.click(screen.getByLabelText(/^Replace Wed.*dinner$/));
    fireEvent.click(screen.getByLabelText(/^Reference Wed.*dinner in chat$/));
    expect(props.onReplace).toHaveBeenCalledWith(meal);
    expect(props.onReference).toHaveBeenCalledWith(meal);
    expect(props.onSelect).not.toHaveBeenCalled();
    expect(props.onStatus).not.toHaveBeenCalled();
  });

  it("disables replacement for locked or executed meals", () => {
    const props = setup();
    props.plan.meals.find(meal => meal.id === "meal-0-breakfast")!.locked = true;
    props.plan.meals.find(meal => meal.id === "meal-0-lunch")!.status = "completed";
    render(<CalendarGrid {...props}/>);
    expect(screen.getByLabelText(/^Replace Mon.*breakfast$/)).toBeDisabled();
    expect(screen.getByLabelText(/^Replace Mon.*lunch$/)).toBeDisabled();
    expect(screen.getByLabelText(/^Reference Mon.*lunch in chat$/)).toBeEnabled();
  });
});
