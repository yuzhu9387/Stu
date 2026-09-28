"use client";
import { foodEmoji } from "./food-art";
import type { FoodType } from "./types";

const GROUPS: FoodType[] = ["Protein", "Carbs", "Vegetables", "Dairy"];

/** The other food groups a dish or food carries besides its main one. */
/** `name` names the dish when several are edited side by side. */
export function AlsoContains({ primary, value, onChange, name }: { primary: FoodType; value?: FoodType[]; onChange: (next: FoodType[]) => void; name?: string }) {
  const chosen = (value ?? []).filter(group => group !== primary);
  return <fieldset className="kw-also" aria-label={name ? `Also contains, ${name}` : undefined}>
    <legend>Also contains</legend>
    <div className="kw-also-chips">{GROUPS.filter(group => group !== primary).map(group => {
      const on = chosen.includes(group);
      return <button type="button" key={group} aria-pressed={on} className={`kw-also-chip ${on ? "is-on" : ""}`} onClick={() => onChange(on ? chosen.filter(g => g !== group) : [...chosen, group])}>
        <span aria-hidden="true">{foodEmoji("", group)}</span>{group}
      </button>;
    })}</div>
  </fieldset>;
}

/** A compact mark for a card: the emoji of each other group, e.g. "+🥩🥦". */
export function AlsoMark({ primary, groups }: { primary: FoodType; groups?: FoodType[] }) {
  const shown = (groups ?? []).filter(group => group !== primary);
  if (!shown.length) return null;
  return <span className="kw-also-mark" title={`Also contains ${shown.join(", ")}`} aria-label={`Also contains ${shown.join(", ")}`}>+{shown.map(group => foodEmoji("", group)).join("")}</span>;
}
