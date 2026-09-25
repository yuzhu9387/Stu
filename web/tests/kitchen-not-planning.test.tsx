import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { CalendarGrid } from "@/features/kitchen/calendar";
import { createDemoState } from "@/features/kitchen/data";

function setup(includedOnFirst: boolean) {
  const state = createDemoState();
  const plan = structuredClone(state.plans[0]);
  plan.meals[0] = { ...plan.meals[0], included: includedOnFirst };
  state.plans = [plan];
  const onInclude = vi.fn();
  render(
    <CalendarGrid
      week={plan.weekStart} plan={plan} state={state} selectedId={null}
      onSelect={() => {}} onAdd={() => {}} onStatus={() => {}} onLike={() => {}}
      onInclude={onInclude} planning
    />,
  );
  return { onInclude, plan };
}

it("shows an excluded slot as Not Planning rather than an empty gap", () => {
  setup(false);
  expect(screen.getByText("Not Planning")).toBeVisible();
});

it("leaves an excluded slot static on the plan page, where slots are chosen in step 1", () => {
  const { onInclude } = setup(false);
  expect(screen.queryByRole("button", { name: /after all$/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Not Planning"));
  expect(onInclude).not.toHaveBeenCalled();
});

it("puts an excluded slot back from the calendar page", () => {
  const state = createDemoState();
  const plan = structuredClone(state.plans[0]);
  plan.meals[0] = { ...plan.meals[0], included: false };
  state.plans = [plan];
  const onInclude = vi.fn();
  render(
    <CalendarGrid
      week={plan.weekStart} plan={plan} state={state} selectedId={null}
      onSelect={() => {}} onAdd={() => {}} onStatus={() => {}} onLike={() => {}}
      onInclude={onInclude}
    />,
  );
  fireEvent.click(screen.getByText("Not Planning"));
  expect(onInclude).toHaveBeenCalledWith(expect.objectContaining({ id: plan.meals[0].id }), true);
});

it("leaves an ordinary slot alone", () => {
  setup(true);
  expect(screen.queryByText("Not Planning")).toBeNull();
});

it("keeps an excluded slot out of the day's hands-on total", () => {
  const state = createDemoState();
  const plan = structuredClone(state.plans[0]);
  const day = plan.meals[0].day;
  const full = plan.meals.filter(m => m.day === day)
    .reduce((sum, m) => sum + m.activeMinutes, 0);
  plan.meals[0] = { ...plan.meals[0], included: false };
  state.plans = [plan];
  render(
    <CalendarGrid
      week={plan.weekStart} plan={plan} state={state} selectedId={null}
      onSelect={() => {}} onAdd={() => {}} onStatus={() => {}} onLike={() => {}}
    />,
  );
  const expected = full - plan.meals[0].activeMinutes;
  expect(screen.getAllByText(`⏱️ ${expected} mins`).length).toBeGreaterThan(0);
});
