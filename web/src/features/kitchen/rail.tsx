"use client";
import Image from "next/image";
import type { MouseEvent, ReactNode } from "react";
import { shiftWeek, todayIso, weekOf } from "./data";
import { KitchenProfileMenu } from "./profile-menu";
import type { KitchenState, Page } from "./types";
import { weekStatus } from "./workflow";
import "./rail.css";

export type RailPage = "fridge" | "plan" | "calendar" | "recipes";

/** What waits behind Plan: this week until it is confirmed, then next week. */
export function planHint(state: KitchenState, thisWeek: string): string {
  const now = weekStatus(state, thisWeek);
  if (now === "none") return "Plan this week";
  if (now === "draft") return "This week · draft";
  const next = weekStatus(state, shiftWeek(thisWeek, 1));
  return next === "confirmed" ? "Next week ready ✓" : next === "draft" ? "Next week · draft" : "Plan next week";
}

/** What waits behind Calendar: today's meals, or the week's. */
export function calendarHint(state: KitchenState, thisWeek: string, today: string): string {
  const eaten = (day?: string) => (plan?: KitchenState["plans"][number]) =>
    plan ? plan.meals.filter(meal => meal.included !== false && meal.status !== "skipped" && (!day || meal.day === day)).length : 0;
  const confirmed = (week: string) => state.plans.find(plan => plan.weekStart === week && plan.status === "confirmed");
  const todays = confirmed(weekOf(today));
  if (todays) { const count = eaten(today)(todays); return count ? `Today · ${count} ${count === 1 ? "meal" : "meals"}` : "Nothing planned today"; }
  const week = confirmed(thisWeek);
  return week ? `${eaten()(week)} meals this week` : "No menu yet";
}

/** The fridge: freezer above, fridge below, a handle on each. */
function FridgeIcon() {
  return <svg className="kw-rail-fridge" viewBox="0 0 22 30" aria-hidden="true">
    <rect x="1.5" y="1.5" width="19" height="27" rx="4" fill="#fff8ef" stroke="currentColor" strokeWidth="2.5" />
    <path d="M1.5 11.5h19" stroke="currentColor" strokeWidth="2.5" />
    <rect x="3" y="3" width="16" height="7.2" rx="2.4" fill="#c8e7f2" />
    <path d="M16 5.5v3M16 14v6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
  </svg>;
}

/** A small book whose cover opens and pages turn while the pointer is on it. */
function Book() {
  return <span className="kw-rail-book" aria-hidden="true">
    <i className="kw-book-back" /><i className="kw-book-page" /><i className="kw-book-page" /><i className="kw-book-page" /><i className="kw-book-cover" />
  </span>;
}

/** The kitchen's way around, down the left of every page: the fridge (home),
 * Plan and Calendar at the top, the Recipe Book at the bottom above the
 * profile. Each says what waits behind it. */
export function KitchenRail({ page, state, thisWeek, demo, onOpen, onHome, onNavigate, onPrefetch, onReset }: {
  page: Page; state: KitchenState; thisWeek: string; demo: boolean;
  onOpen: (page: RailPage) => void; onHome: (event: MouseEvent<HTMLAnchorElement>) => void;
  onNavigate: (page: Page) => void; onPrefetch: (page: Page) => void; onReset: () => boolean;
}) {
  const current = (target: RailPage) => page === target ? "page" as const : undefined;
  const way = (target: RailPage, label: string, hint: string, icon: ReactNode) =>
    <button type="button" className={`kw-rail-way is-${target}`} aria-current={current(target)} onClick={() => onOpen(target)}>
      {icon}<span className="kw-rail-text"><strong>{label}</strong><small>{hint}</small></span>
    </button>;
  return <aside className="kw-rail">
    <a className="kw-rail-brand" href={demo ? "/demo" : "/fridge"} onClick={onHome}><Image src="/assets/figma/stu-logo.png" alt="Stu baby logo" width={40} height={40} /><strong>Stu</strong></a>
    <nav className="kw-rail-nav" aria-label="Kitchen">
      {way("fridge", "冰箱", `${state.inventory.length} items`, <span className="kw-rail-icon"><FridgeIcon /></span>)}
      {way("plan", "Plan", planHint(state, thisWeek), <span className="kw-rail-icon" data-icon="📋" aria-hidden="true" />)}
      {way("calendar", "Calendar", calendarHint(state, thisWeek, todayIso()), <span className="kw-rail-icon" data-icon="📅" aria-hidden="true" />)}
      {way("recipes", "Recipe Book", `${state.recipes.length} recipes`, <Book />)}
    </nav>
    <KitchenProfileMenu key={page} demo={demo} onNavigate={onNavigate} onPrefetch={onPrefetch} onReset={onReset} />
  </aside>;
}
