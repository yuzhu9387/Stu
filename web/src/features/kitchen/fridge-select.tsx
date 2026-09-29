"use client";
import { useEffect, useState } from "react";
import type { InventoryItem } from "./types";

/** Foods chosen on the fridge for 🔪 + Prep. Choosing starts from a card's
 * corner circle (or a long press on a phone); while anything is chosen a tap
 * on a card chooses it too. A food with nothing left cannot be chosen. */
export function useFoodChoice(inventory: InventoryItem[]) {
  const [ids, setIds] = useState<string[]>([]);
  const chosen = ids.map(id => inventory.find(item => item.id === id)).filter((item): item is InventoryItem => !!item && item.portions > 0);
  const toggle = (item: InventoryItem) => {
    if (item.portions <= 0) return;
    setIds(current => current.includes(item.id) ? current.filter(id => id !== item.id) : [...current, item.id]);
  };
  const has = (id: string) => chosen.some(item => item.id === id);
  return { chosen, choosing: chosen.length > 0, has, toggle, clear: () => setIds([]) };
}

/** The bar along the bottom while foods are chosen: how many, the one thing
 * to do with them, and a way out (✕ or Escape). */
export function ChoiceBar({ count, onPrep, onClear }: { count: number; onPrep: () => void; onClear: () => void }) {
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") onClear(); };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClear]);
  return <div className="kw-choice-bar" role="toolbar" aria-label="Selected foods">
    <span className="kw-choice-count">{count} selected</span>
    <button type="button" className="kw-choice-prep" title="Add to prep day" onClick={onPrep}>🔪 + Prep</button>
    <button type="button" className="kw-choice-clear" aria-label="Clear selection" onClick={onClear}>✕</button>
  </div>;
}
