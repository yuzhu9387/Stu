"use client";
import type { ReactNode } from "react";
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

const BACK = <svg className="kw-page-button-arrow" viewBox="0 0 10 16" aria-hidden="true"><path d="M8 2 2 8l6 6" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>;
const ONWARD = <svg className="kw-page-button-arrow" viewBox="0 0 10 16" aria-hidden="true"><path d="M2 2l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>;

/** A way between pages, drawn like the doors beside the fridge: an arrow, a
 * small picture of where it goes, and its name. */
export function PageButton({ icon, label, name, onward = false, className = "", onClick }: { icon: ReactNode; label: string; name: string; onward?: boolean; className?: string; onClick: () => void }) {
  return <button type="button" className={`kw-page-button ${onward ? "is-onward" : ""} ${className}`} aria-label={name} onClick={onClick}>
    {!onward && BACK}<span className="kw-page-button-icon" aria-hidden="true">{icon}</span><span>{label}</span>{onward && ONWARD}
  </button>;
}

/** The way home from any other page: a small two-door fridge (freezer above,
 * fridge below, a handle on each) and its name. */
export function HomeBack({ onClick }: { onClick: () => void }) {
  return <PageButton className="kw-home-back" name="← 冰箱" label="冰箱" onClick={onClick} icon={
    <svg className="kw-home-back-fridge" viewBox="0 0 22 30">
      <rect x="1.5" y="1.5" width="19" height="27" rx="4" fill="#fff8ef" stroke="currentColor" strokeWidth="2.5" />
      <path d="M1.5 11.5h19" stroke="currentColor" strokeWidth="2.5" />
      <rect x="3" y="3" width="16" height="7.2" rx="2.4" fill="#c8e7f2" />
      <path d="M16 5.5v3M16 14v6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>} />;
}
