"use client";
import { useEffect, useRef, useState } from "react";
import { shiftWeek, weekDays, weekLabel, weekOf } from "./data";

const monthTitle = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
const dayName = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
const utc = (day: string) => new Date(`${day}T12:00:00Z`);

/** The Mondays of every week that touches a month ("YYYY-MM"). */
function monthWeeks(month: string) {
  const first = `${month}-01`, next = utc(first);
  next.setUTCMonth(next.getUTCMonth() + 1);
  const weeks: string[] = [];
  for (let monday = weekOf(first); utc(monday) < next; monday = shiftWeek(monday, 1)) weeks.push(monday);
  return weeks;
}
function shiftMonth(month: string, delta: number) {
  const d = utc(`${month}-01`);
  d.setUTCMonth(d.getUTCMonth() + delta);
  return d.toISOString().slice(0, 7);
}

/** The week in view, as a button that opens a month calendar. Picking any day
 * picks its whole week (Monday to Sunday); the chosen week is highlighted. */
export function WeekPicker({ week, thisWeek, onPick, className = "" }: { week: string; thisWeek: string; onPick: (week: string) => void; className?: string }) {
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(week.slice(0, 7));
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  const toggle = () => { if (!open) setMonth(week.slice(0, 7)); setOpen(!open); };
  const pick = (monday: string) => { setOpen(false); if (monday !== week) onPick(monday); };

  return <div className="kw-week-chooser" ref={root}>
    <button type="button" className={`kw-week-label ${className}`} aria-haspopup="dialog" aria-expanded={open} aria-label={`Week of ${weekLabel(week)}, choose a week`} onClick={toggle}>
      {weekLabel(week)}<span className="kw-week-caret" aria-hidden="true">▾</span>
    </button>
    {open && <div className="kw-week-popover" role="dialog" aria-label="Choose a week">
      <header>
        <button type="button" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>‹</button>
        <strong>{monthTitle.format(utc(`${month}-01`))}</strong>
        <button type="button" aria-label="Next month" onClick={() => setMonth(shiftMonth(month, 1))}>›</button>
      </header>
      <div className="kw-week-grid" role="grid" aria-label={monthTitle.format(utc(`${month}-01`))}>
        <div className="kw-week-row is-head" role="row">{WEEKDAYS.map(day => <span key={day} role="columnheader">{day}</span>)}</div>
        {monthWeeks(month).map(monday => <div key={monday} role="row" className={`kw-week-row ${monday === week ? "is-chosen" : ""} ${monday === thisWeek ? "is-current" : ""}`}>
          {weekDays(monday).map(day => <button type="button" role="gridcell" key={day} aria-selected={monday === week} aria-label={dayName.format(utc(day))} className={day.slice(0, 7) === month ? "" : "is-outside"} onClick={() => pick(monday)}>{utc(day).getUTCDate()}</button>)}
        </div>)}
      </div>
      <footer><button type="button" onClick={() => pick(thisWeek)}>This week</button></footer>
    </div>}
  </div>;
}
