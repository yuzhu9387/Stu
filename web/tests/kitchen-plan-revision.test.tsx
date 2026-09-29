import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import type { KitchenState } from "@/features/kitchen/types";
import { KitchenWorkspace } from "@/features/kitchen/workspace";

const nav = vi.hoisted(() => ({ query: "", listeners: new Set<() => void>() }));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(listener => { nav.listeners.add(listener); return () => { nav.listeners.delete(listener); }; }, () => nav.query)),
    useRouter: () => ({ push: (url: string) => { nav.query = url.split("?")[1] || ""; nav.listeners.forEach(listener => listener()); } }),
  };
});
beforeEach(() => { localStorage.clear(); });

const command = (state: KitchenState, type: string, payload: Record<string, unknown>) =>
  applyDemoCommand(state, { type, payload, expectedRevision: state.revision, operationId: crypto.randomUUID() }).state;

/** The demo week confirmed, and opened for editing as a copy. */
function editing() {
  const state = createDemoState(), base = state.plans[0];
  return command(state, "plan.save", { plan: { ...base, id: "rev", status: "draft", basePlanId: base.id, baseVersion: base.version } });
}
const plan = (state: KitchenState, id: string) => state.plans.find(p => p.id === id)!;

describe("while the week is being edited", () => {
  it("what the calendar records follows into the edit, which still confirms", () => {
    let state = editing();
    state = command(state, "meal.status", { planId: "plan-demo", mealId: "meal-0-lunch", status: "completed" });
    const done = state.audit.at(-1)!.id;
    state = command(state, "meal.like", { planId: "plan-demo", mealId: "meal-1-lunch", liked: true });
    let edit = plan(state, "rev");
    expect(edit.meals.find(m => m.id === "meal-0-lunch")!.status).toBe("completed");
    expect(edit.meals.find(m => m.id === "meal-1-lunch")!.liked).toBe(true);
    expect(edit.baseVersion).toBe(plan(state, "plan-demo").version);
    state = command(state, "change.undo", { auditId: done });
    edit = plan(state, "rev");
    expect(edit.meals.find(m => m.id === "meal-0-lunch")!.status).toBe("planned");
    expect(edit.baseVersion).toBe(plan(state, "plan-demo").version);
    state = command(state, "plan.confirm", { id: "rev" });
    expect(plan(state, "rev").status).toBe("confirmed");
  });

  it("the calendar shows the confirmed version, where meals can still be marked", async () => {
    nav.query = "week=2026-09-21&page=plan";
    render(<KitchenWorkspace demo initialPage="plan" />);
    fireEvent.click(await screen.findByRole("button", { name: /Edit plan/ }));
    await waitFor(() => expect(JSON.parse(localStorage.getItem("stu-kitchen-demo-v1") ?? "{\"plans\":[]}").plans.some((p: { basePlanId?: string }) => p.basePlanId)).toBe(true));
    fireEvent.click(await screen.findByRole("button", { name: "← 冰箱" }));
    fireEvent.click(within(await screen.findByRole("navigation", { name: "Kitchen" })).getByRole("button", { name: /Calendar/ }));
    expect(await screen.findByRole("button", { name: "Mark Mon, Sep 21 lunch completed" })).toBeEnabled();
    expect(screen.queryByText(/Draft/i, { selector: ".kw-plan-stamp" })).not.toBeInTheDocument();
  });
});
