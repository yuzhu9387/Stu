import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import type { KitchenState, WeeklyPlan } from "@/features/kitchen/types";
import { hasPlannedMeals, readyDraft } from "@/features/kitchen/workflow";
import { KitchenWorkspace } from "@/features/kitchen/workspace";

const nav = vi.hoisted(() => ({ query: "", listeners: new Set<() => void>() }));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(listener => { nav.listeners.add(listener); return () => { nav.listeners.delete(listener); }; }, () => nav.query)),
    useRouter: () => ({ push: (url: string) => { nav.query = url.split("?")[1] || ""; nav.listeners.forEach(listener => listener()); }, prefetch: () => {} }),
  };
});
beforeEach(() => { nav.query = "page=calendar"; localStorage.clear(); });

const THIS_WEEK = "2026-09-21", NEXT_WEEK = "2026-09-28";
const base = createDemoState().plans[0];
/** A plan for a week: `meals: false` is an empty draft, as "plan it myself" leaves it. */
const shift = (day: string, weeks: number) => new Date(Date.parse(`${day}T12:00:00Z`) + weeks * 7 * 86_400_000).toISOString().slice(0, 10);
/** A plan for a week: a full week of meals, `meals: false` an empty draft (as
 * "plan it myself" leaves it), or `meals: 1` a draft with a single meal. */
function planFor(week: string, status: WeeklyPlan["status"], meals: boolean | 1 = true, extra: Partial<WeeklyPlan> = {}): WeeklyPlan {
  const weeks = week === THIS_WEEK ? 0 : 1;
  const laid = structuredClone(base.meals).map(m => ({ ...m, id: `${week}-${m.id}`, day: shift(m.day, weeks) }));
  return { ...structuredClone(base), id: `${week}-${status}-${meals}-${extra.basePlanId ?? ""}`, weekStart: week, status, meals: meals === true ? laid : meals === 1 ? laid.slice(0, 1) : [], prep: meals === true ? structuredClone(base.prep) : [], ...extra };
}
function seed(plans: WeeklyPlan[]) {
  const state: KitchenState = { ...createDemoState(), plans };
  localStorage.setItem("stu-kitchen-demo-v1", JSON.stringify(state));
}
const banners = () => [...document.querySelectorAll(".kw-draft-banner")].map(node => node.textContent);

describe("which week needs attention", () => {
  it("does not call an empty draft ready, an edit copy, or a week already confirmed", () => {
    expect(hasPlannedMeals(planFor(NEXT_WEEK, "draft", false))).toBe(false);
    expect(readyDraft([planFor(NEXT_WEEK, "draft", false)], NEXT_WEEK)).toBeNull();
    expect(readyDraft([planFor(NEXT_WEEK, "draft")], NEXT_WEEK)).not.toBeNull();
    // One meal carried over (a repeating breakfast) is a start, not a week to review.
    expect(hasPlannedMeals(planFor(NEXT_WEEK, "draft", 1))).toBe(true);
    expect(readyDraft([planFor(NEXT_WEEK, "draft", 1)], NEXT_WEEK)).toBeNull();
    const confirmed = planFor(NEXT_WEEK, "confirmed");
    expect(readyDraft([confirmed, planFor(NEXT_WEEK, "draft", true, { basePlanId: confirmed.id })], NEXT_WEEK)).toBeNull();
    expect(readyDraft([planFor(NEXT_WEEK, "draft", true, { basePlanId: "elsewhere" })], NEXT_WEEK)).toBeNull();
  });
});

describe("calendar banners", () => {
  it("says an empty week is not planned yet, and never that next week's empty draft is ready", async () => {
    seed([planFor(THIS_WEEK, "draft", false), planFor(NEXT_WEEK, "draft", false)]);
    render(<KitchenWorkspace demo />);
    await screen.findByRole("region", { name: "Weekly meal calendar" });
    expect(banners()).toEqual(["This week isn’t planned yet. Continue planning"]);
  });

  it("shows one banner: this week's draft before next week's", async () => {
    seed([planFor(THIS_WEEK, "draft"), planFor(NEXT_WEEK, "draft")]);
    render(<KitchenWorkspace demo />);
    await screen.findByRole("region", { name: "Weekly meal calendar" });
    expect(banners()).toEqual(["You’re previewing a draft. Review and confirm"]);
  });

  it("points to next week's draft once this week is confirmed", async () => {
    seed([planFor(THIS_WEEK, "confirmed"), planFor(NEXT_WEEK, "draft")]);
    render(<KitchenWorkspace demo />);
    await screen.findByRole("region", { name: "Weekly meal calendar" });
    expect(banners()).toEqual(["Next week’s plan is ready. Review draft"]);
  });

  it("says nothing when this week is confirmed and next week has nothing to review", async () => {
    seed([planFor(THIS_WEEK, "confirmed"), planFor(NEXT_WEEK, "draft", 1)]);
    render(<KitchenWorkspace demo />);
    await screen.findByRole("region", { name: "Weekly meal calendar" });
    expect(banners()).toEqual([]);
  });
});
