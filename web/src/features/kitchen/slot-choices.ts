"use client";
import { useCallback, useMemo } from "react";
import { readStored, useStored } from "./browser-store";
import type { WeeklyPlan } from "./types";

/** Setup choices for a week — which slots to cook — kept in this browser
 * until the plan is confirmed.
 *
 * Ticking a box is a draft decision, so it should feel instant: no round trip,
 * no revision bump, no toast. Choices are keyed by day and slot rather than by
 * meal id, so they survive regenerating the draft and can be made before any
 * draft exists. Confirming writes the differences to the plan once.
 */
export interface SetupChoices { slots: Record<string, boolean> }

const EMPTY: SetupChoices = { slots: {} };

function parse(raw: string | null): SetupChoices {
  if (!raw) return EMPTY;
  try {
    const value = JSON.parse(raw) as Partial<SetupChoices>;
    return { slots: value.slots && typeof value.slots === "object" ? value.slots : {} };
  } catch { return EMPTY; }
}

export const slotKey = (day: string, slot: string) => `${day}|${slot}`;

export function useSetupChoices(week: string, demo: boolean) {
  const key = `stu-setup-choices:${demo ? "demo" : "live"}:${week}`;
  const [raw, write] = useStored("local", key);
  const choices = useMemo(() => parse(raw), [raw]);
  const setSlot = useCallback((day: string, slot: string, included: boolean) => {
    const current = parse(readStored("local", key));
    write(JSON.stringify({ ...current, slots: { ...current.slots, [slotKey(day, slot)]: included } }));
  }, [key, write]);
  const clear = useCallback(() => write(null), [write]);
  return { choices, setSlot, clear };
}

/** The draft as the household currently sees it: stored flags overlaid by the
 * choices made in this browser. A confirmed plan is never overlaid. */
export function withChoices(plan: WeeklyPlan | null, choices: SetupChoices): WeeklyPlan | null {
  if (!plan || plan.status !== "draft") return plan;
  if (!Object.keys(choices.slots).length) return plan;
  return {
    ...plan,
    meals: plan.meals.map(meal => {
      const chosen = choices.slots[slotKey(meal.day, meal.slot)];
      return chosen === undefined || meal.status !== "planned" ? meal : { ...meal, included: chosen };
    }),
  };
}

export function useChosenPlan(plan: WeeklyPlan | null, choices: SetupChoices) {
  return useMemo(() => withChoices(plan, choices), [plan, choices]);
}

/** The writes confirming needs: only slots that differ from what is stored. */
export function pendingWrites(plan: WeeklyPlan, choices: SetupChoices) {
  return plan.meals.flatMap(meal => {
    const chosen = choices.slots[slotKey(meal.day, meal.slot)];
    return chosen === undefined || meal.status !== "planned" || chosen === (meal.included ?? true) ? [] : [{ mealId: meal.id, included: chosen }];
  });
}
