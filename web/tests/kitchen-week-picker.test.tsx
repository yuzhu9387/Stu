import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { createDemoState, weekLabel, weekOf, weeksBetween } from "@/features/kitchen/data";
import { PlanningPage } from "@/features/kitchen/plan";
import { WeekPicker } from "@/features/kitchen/week-picker";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

it("names a week clearly, across months and years", () => {
  expect(weekLabel("2026-09-21")).toBe("Sep 21–27, 2026");
  expect(weekLabel("2026-09-28")).toBe("Sep 28 – Oct 4, 2026");
  expect(weekLabel("2026-12-28")).toBe("Dec 28, 2026 – Jan 3, 2027");
  expect(weekOf("2026-10-04")).toBe("2026-09-28"); // a Sunday belongs to the week before
  expect(weekOf("2026-09-28")).toBe("2026-09-28");
  expect(weeksBetween("2026-09-21", "2026-10-12")).toBe(3);
});

it("opens a month calendar from the date box; any day picks its whole week", () => {
  const onPick = vi.fn();
  render(<WeekPicker week="2026-09-28" thisWeek="2026-09-21" onPick={onPick} />);
  const box = screen.getByRole("button", { name: /Week of Sep 28 – Oct 4, 2026/ });
  expect(box).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(box);
  const popover = screen.getByRole("dialog", { name: "Choose a week" });
  expect(within(popover).getByText("September 2026")).toBeVisible();
  // The chosen week's row is highlighted, all seven days.
  expect(within(popover).getAllByRole("gridcell", { selected: true })).toHaveLength(7);
  // A Thursday picks its Monday.
  fireEvent.click(within(popover).getByRole("gridcell", { name: "Thu, Sep 10, 2026" }));
  expect(onPick).toHaveBeenCalledWith("2026-09-07");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  // Other months, and a shortcut back to this week.
  fireEvent.click(box);
  fireEvent.click(screen.getByRole("button", { name: "Next month" }));
  expect(screen.getByText("October 2026")).toBeVisible();
  fireEvent.click(screen.getByRole("gridcell", { name: "Sat, Oct 17, 2026" }));
  expect(onPick).toHaveBeenLastCalledWith("2026-10-12");
  fireEvent.click(box);
  fireEvent.click(screen.getByRole("button", { name: "This week" }));
  expect(onPick).toHaveBeenLastCalledWith("2026-09-21");
  // Picking the week already shown changes nothing; Escape closes.
  onPick.mockClear();
  fireEvent.click(box);
  fireEvent.click(screen.getByRole("gridcell", { name: "Wed, Sep 30, 2026" }));
  expect(onPick).not.toHaveBeenCalled();
  fireEvent.click(box);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

function props(week: string, onWeek: (delta: number) => void) {
  const state = createDemoState();
  return { state, week, plan: null, selected: [], onSelect: () => {}, step: null, onStep: () => {}, onGoal: async () => {}, onApplyFix: async () => {}, onGenerate: async () => null, onSavePreferences: vi.fn().mockResolvedValue(2), onChat: async () => {}, onApply: async () => {}, onConfirm: async () => null, onEdit: async () => {}, focusTick: 0, choices: { slots: {} }, onSlot: () => {}, onPrep: () => {}, onGuidance: () => {}, onWeek, thisWeek: "2026-09-21", demo: true, busy: false, children: <div /> };
}

it("keeps this week and next one tap away on the plan page, with where each stands", () => {
  const onWeek = vi.fn();
  const p = props("2026-09-21", onWeek);
  render(<PlanningPage {...p} />);
  const weeks = screen.getByRole("group", { name: "Weeks to plan" });
  const [current, next] = within(weeks).getAllByRole("button");
  expect(current).toHaveTextContent("This week");
  expect(current).toHaveTextContent("Sep 21–27");
  expect(current).toHaveAttribute("aria-pressed", "true");
  // The demo's week has a confirmed plan; the next has none yet.
  expect(current).toHaveTextContent("Confirmed");
  expect(next).toHaveTextContent("Next week");
  expect(next).toHaveTextContent("Sep 28 – Oct 4");
  expect(next).toHaveTextContent("Not planned");
  fireEvent.click(next);
  expect(onWeek).toHaveBeenCalledWith(1);
  // The date box picks any week, as a jump from the one shown.
  fireEvent.click(screen.getByRole("button", { name: /Week of Sep 21–27, 2026/ }));
  fireEvent.click(screen.getByRole("gridcell", { name: "Mon, Sep 7, 2026" }));
  expect(onWeek).toHaveBeenLastCalledWith(-2);
});
