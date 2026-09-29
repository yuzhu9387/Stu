"use client";
import "./fridge-doors.css";

export type Door = "recipes" | "calendar" | "plan";

/** Beside the fridge, which is home: the recipe book on top, then the two
 * round buttons to the week — the calendar, and planning. */
export function FridgeDoors({ onOpen }: { onOpen: (door: Door) => void }) {
  return <nav className="kw-fridge-doors" aria-label="Kitchen">
    <button type="button" className="kw-door-book" onClick={() => onOpen("recipes")}><span aria-hidden="true">📖</span>Recipes</button>
    <button type="button" className="kw-door-round is-calendar" onClick={() => onOpen("calendar")}><span aria-hidden="true">📅</span>Calendar</button>
    <button type="button" className="kw-door-round is-plan" onClick={() => onOpen("plan")}><span aria-hidden="true">📋</span>Plan</button>
  </nav>;
}
