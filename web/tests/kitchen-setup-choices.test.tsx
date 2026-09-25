import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { PlanningPage } from "@/features/kitchen/plan";
import { pendingWrites, slotKey, withChoices } from "@/features/kitchen/slot-choices";

function props(plan: ReturnType<typeof createDemoState>["plans"][number] | null) {
  const state = createDemoState();
  return {
    state, plan, week: "2026-09-21", choices: { slots: {} as Record<string, boolean> }, selected: [],
    step: null as string | null, onStep: vi.fn(), onSlot: vi.fn(), onGoal: vi.fn(async () => {}), onSelect: vi.fn(), onApplyFix: vi.fn(), onGenerate: vi.fn(async (): Promise<string | null> => null),
    onSavePreferences: vi.fn(async () => 0), onChat: vi.fn(), onApply: vi.fn(), onConfirm: vi.fn(async (): Promise<string | null> => null), onEdit: vi.fn(async () => {}), focusTick: 0, onPrep: vi.fn(),
    onGuidance: vi.fn(), onWeek: vi.fn(), demo: true, busy: false, children: <div />,
  };
}
const draft = () => { const plan = createDemoState().plans[0]; plan.status = "draft"; return plan; };

describe("setup choices stay in the browser until confirm", () => {
  it("overlays a draft by day and slot without touching the stored plan", () => {
    const plan = draft();
    const monday = plan.meals.find(m => m.day === "2026-09-21" && m.slot === "breakfast")!;
    const view = withChoices(plan, { slots: { [slotKey(monday.day, "breakfast")]: false } })!;
    expect(view.meals.find(m => m.id === monday.id)?.included).toBe(false);
    expect(plan.meals.find(m => m.id === monday.id)?.included).toBeUndefined();
  });

  it("never overlays a confirmed plan", () => {
    const plan = createDemoState().plans[0];
    expect(withChoices(plan, { slots: { [slotKey("2026-09-21", "breakfast")]: false } })).toBe(plan);
  });

  it("confirms only what differs from what is stored", () => {
    const plan = draft();
    const [first, second] = plan.meals;
    second.included = false;
    const writes = pendingWrites(plan, { slots: {
      [slotKey(first.day, first.slot)]: false,   // changed → write
      [slotKey(second.day, second.slot)]: false, // already stored → skip
    } });
    expect(writes).toEqual([{ mealId: first.id, included: false }]);
  });

  it("ticking a meal is a local choice, not a saved command", () => {
    const p = props(draft());
    const { rerender } = render(<PlanningPage {...p} step="preferences" />);
    fireEvent.click(screen.getByLabelText("Plan Mon breakfast"));
    expect(p.onSlot).toHaveBeenCalledWith("2026-09-21", "breakfast", false);
    rerender(<PlanningPage {...p} step="preferences" choices={{ slots: { [slotKey("2026-09-21", "breakfast")]: false } }} />);
    expect(screen.getByLabelText("Plan Mon breakfast")).not.toBeChecked();
  });

  it("works before any draft exists", () => {
    const p = props(null);
    render(<PlanningPage {...p} />);
    expect(screen.getByLabelText("Plan Sun dinner")).toBeEnabled();
  });
});

describe("planning rail", () => {
  it("shows all four steps before a draft exists", () => {
    render(<PlanningPage {...props(null)} />);
    expect(within(screen.getByRole("list", { name: "Planning steps" })).getAllByRole("listitem")).toHaveLength(4);
  });

  it("links back to step 1 and confirms from the last step, with no other confirm button", () => {
    const p = props(draft());
    const { rerender } = render(<PlanningPage {...p} />);
    const rail = screen.getByRole("list", { name: "Planning steps" });
    fireEvent.click(within(rail).getByRole("button", { name: /Back to step 1/ }));
    expect(p.onStep).toHaveBeenCalledWith("preferences");
    // The rail's last step is the only confirm on the page.
    expect(screen.getAllByRole("button", { name: "Confirm plan" })).toHaveLength(1);
    fireEvent.click(within(rail).getByRole("button", { name: "Confirm plan" }));
    expect(p.onConfirm).toHaveBeenCalled();

    rerender(<PlanningPage {...p} step="preferences" />);
    expect(screen.getByRole("button", { name: "Confirm plan" })).toBeDisabled();
    expect(within(screen.getByRole("list", { name: "Planning steps" })).getByRole("button", { name: /step 2, adjust/ })).toBeVisible();
  });

  it("offers Edit after the week is confirmed, and no confirm", () => {
    const p = props(createDemoState().plans[0]);
    render(<PlanningPage {...p} />);
    const rail = screen.getByRole("list", { name: "Planning steps" });
    expect(within(rail).getByRole("button", {name:"Edit plan"})).toBeVisible();
    expect(screen.queryByRole("button", { name: "Confirm plan" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit plan" }));
    expect(p.onEdit).toHaveBeenCalled();
  });

  it("does not block confirming on a stock shortage — it is prepared on prep day", () => {
    const plan = draft();
    const p = props(plan);
    // More meatballs than the fridge and the prep task will hold.
    plan.meals.find(m => m.id === "meal-2-dinner")!.components[0].portions = 40;
    render(<PlanningPage {...p} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm plan" })).toBeEnabled();
  });

  it("shows why the server refused to confirm, in the page", async () => {
    const p = props(draft());
    p.onConfirm = vi.fn(async () => "Insufficient stock for 卤牛肉: missing 3 portions");
    render(<PlanningPage {...p} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirm plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Insufficient stock for 卤牛肉: missing 3 portions");
  });
});

describe("meal style presets are the household's goals", () => {
  it("lists the same goals Manage Goals edits, and toggling one saves that goal", async () => {
    const p = props(draft());
    render(<PlanningPage {...p} step="preferences" />);
    const section = screen.getByRole("region", { name: "Meal style presets" });
    for (const goal of p.state.settings.guidance) expect(within(section).getByText(goal.title)).toBeVisible();
    const first = p.state.settings.guidance[0];
    fireEvent.click(within(section).getByLabelText(`Use goal ${first.title}`));
    expect(p.onGoal).toHaveBeenCalledWith(first.id, !first.enabled);
  });
});

describe("generating a plan", () => {
  it("shows how long Stu has been working, then the reason if it fails", async () => {
    let finish: (value: string | null) => void = () => {};
    const p = props(null);
    p.onGenerate = vi.fn(() => new Promise<string | null>(resolve => { finish = resolve; }));
    const { rerender } = render(<PlanningPage {...p} />);
    fireEvent.click(screen.getByRole("button", { name: "Generate week" }));
    rerender(<PlanningPage {...p} generatingSince={Date.now()} busy />);
    expect(screen.getByRole("status")).toHaveTextContent(/Stu is cooking… 0:0\d/);
    await act(async () => finish("AI must return all 21 meals for the requested week"));
    rerender(<PlanningPage {...p} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("AI must return all 21 meals for the requested week");
  });
});
