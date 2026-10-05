"use client";
import type { ReactNode } from "react";
import "./page-button.css";

const BACK = <svg className="kw-page-button-arrow" viewBox="0 0 10 16" aria-hidden="true"><path d="M8 2 2 8l6 6" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>;
const ONWARD = <svg className="kw-page-button-arrow" viewBox="0 0 10 16" aria-hidden="true"><path d="M2 2l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>;

/** A step between pages of the week (back to the plan, on to the calendar or
 * the shopping): an arrow, a small picture of where it goes, and its name. */
export function PageButton({ icon, label, name, onward = false, className = "", onClick }: { icon: ReactNode; label: string; name: string; onward?: boolean; className?: string; onClick: () => void }) {
  return <button type="button" className={`kw-page-button ${onward ? "is-onward" : ""} ${className}`} aria-label={name} onClick={onClick}>
    {!onward && BACK}<span className="kw-page-button-icon" aria-hidden="true">{icon}</span><span>{label}</span>{onward && ONWARD}
  </button>;
}
