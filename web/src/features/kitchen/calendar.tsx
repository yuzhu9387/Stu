"use client";
import { Fragment, useMemo } from "react";
import { AlsoMark } from "./also-contains";
import { componentGroups } from "./food-groups";
import { ArrowsClockwise, ChatCircleDots, LockSimple, Plus } from "@phosphor-icons/react";
import { foodEmoji } from "./food-art";
import { dayLabel, slots, weekDays } from "./data";
import type { CalendarBoard } from "./plan-board";
import { projectedMealShortages } from "./schedule";
import type { KitchenState, Meal, MealSlot, WeeklyPlan } from "./types";
import "./calendar.css";

/** What the last quick action on a card did, or why it failed. Shown on that
 * card only — Plan and Calendar have no page-wide banner. */
export interface CardNote { mealId: string; text: string; error?: boolean; success?: boolean; undo?: string }

interface CalendarProps {
  onUnlock?: (meal:Meal)=>void;
  week: string;
  plan: WeeklyPlan | null;
  state: KitchenState;
  selectedId: string | null;
  onSelect: (meal: Meal) => void;
  onAdd: (day: string, slot: MealSlot) => void;
  onStatus: (meal: Meal, status: "completed" | "skipped") => void;
  onLike: (meal: Meal) => void;
  onReplace?: (meal: Meal) => void;
  onReference?: (meal: Meal) => void;
  /** Frame 47:195: mark a slot as one the household is not cooking. */
  onInclude?: (meal: Meal, included: boolean) => void;
  /** Meals currently referenced in the Stu chat, marked on their cards. */
  referencedIds?: string[];
  onAddToMeal?: (meal: Meal) => void;
  /** Adjusting a draft beside the fridge: meals and empty slots take food. */
  board?: CalendarBoard;
  planning?: boolean;
  /** On the plan page, what an empty slot offers: "add" (chosen, fill it from
   * recipes), "off" (left out in step 1) or nothing. */
  slotState?: (day: string, slot: MealSlot) => "add" | "off" | "none";
  note?: CardNote | null;
  onUndo?: (note: CardNote) => void;
  onDismissNote?: () => void;
}

const mealStyles = {
  breakfast: { label: "Breakfast", emoji: "🌅" },
  lunch: { label: "Lunch", emoji: "☀️" },
  dinner: { label: "Dinner", emoji: "🌙" },
};

function mealSource(meal: Meal, state: KitchenState, plan: WeeklyPlan | null): string {
  const sources = meal.components.map(component => {
    const prep = plan?.prep.find(task => task.id === component.prepId);
    if (component.prepId && prep?.status !== "completed") return prep?.status === "planned" ? "prep" : "missing";
    // A dish cooked from fridge foods is as ready as the scarcest of them.
    const stockIds = component.uses?.map(use => use.inventoryId) ?? [prep?.outputInventoryId || component.inventoryId];
    if (!stockIds[0]) return "fresh";
    const foods = stockIds.map(id => state.inventory.find(item => item.id === id));
    const stock = foods.some(food => !food || (meal.status === "planned" && food.portions <= 0)) ? undefined : foods[0];
    if (!stock || (meal.status === "planned" && stock.portions <= 0)) return "missing";
    return stock.location.toLowerCase() === "freezer" ? "freezer" : stock.location.toLowerCase() === "fridge" ? "fridge" : "stored";
  });
  if (sources.includes("missing")) return "Check stock";
  if (sources.includes("prep")) return "Planned prep";
  const stored = new Set(sources.filter(source => source !== "fresh"));
  if (!stored.size) return "Prepare fresh";
  if (stored.size > 1 || stored.has("stored")) return sources.includes("fresh") ? "Stock + fresh" : "Stored food";
  if (stored.has("freezer")) return sources.includes("fresh") ? "Freezer + fresh" : "From freezer";
  return sources.includes("fresh") ? "Fridge + fresh" : "From fridge";
}

export function CalendarGrid({ onUnlock, week, plan, state, selectedId, onSelect, onAdd, onStatus, onLike, onReplace, onReference, onInclude, onAddToMeal, referencedIds = [], planning = false, slotState, note = null, onUndo, onDismissNote, board }: CalendarProps) {
  const days = weekDays(week);
  const dateFormat = useMemo(() => new Intl.DateTimeFormat("en-CA", { timeZone: state.settings.timezone }), [state.settings.timezone]);
  const today = dateFormat.format(new Date());
  const shortages = useMemo(() => new Map(plan ? projectedMealShortages(state, plan).map(row => [row.meal.id, row.missing]) : []), [state, plan]);

  return <div className="kw-calendar-scroll"><div className={`kw-calendar kw-calendar-reference kw-calendar-plan ${plan?.status==="confirmed"?"is-confirmed":""}`} role="region" aria-label="Weekly meal calendar">
    {days.map((day, dayIndex) => {
      const label = dayLabel(day);
      const total = plan?.meals.filter(meal => meal.day === day && meal.included !== false).reduce((sum, meal) => sum + meal.activeMinutes, 0) ?? 0;
      return <section key={day} className={`kw-day ${day === today ? "is-today" : ""}`} aria-label={dayLabel(day, true)}>
        <header className="kw-day-header"><strong>{label.split(",")[0]}</strong><span lang="zh">{["周一","周二","周三","周四","周五","周六","周日"][dayIndex]}</span>{day === today && <span className="kw-calendar-today">Today</span>}</header>
        {slots.map(slot => {
          const meal = plan?.meals.find(candidate => candidate.day === day && candidate.slot === slot);
          const source = meal ? mealSource(meal, state, plan) : "";
          const missing = meal?.status === "planned" ? shortages.get(meal.id) : undefined;
          const { label: slotLabel, emoji } = mealStyles[slot];
          const slotHeader = <span className="kw-card-slot"><span>{slotLabel} <span aria-hidden="true">{emoji}</span></span></span>;
          const cardNote = note && meal && note.mealId === meal.id ? note : null;
          return <div className={`kw-meal-slot kw-slot-${slot}`} key={slot}>
            {cardNote && <p className={`kw-card-note ${cardNote.error ? "is-error" : cardNote.success ? "is-success" : ""}`} role={cardNote.error ? "alert" : "status"}><span>{cardNote.text}</span>{!cardNote.error && cardNote.undo && onUndo && <button type="button" onClick={() => onUndo(cardNote)}>Undo</button>}{cardNote.error && onDismissNote && <button type="button" aria-label="Dismiss" onClick={onDismissNote}>×</button>}</p>}
            {meal && meal.included === false ? (planning ? <div className="kw-not-planning is-static">{slotHeader}<span className="kw-not-planning-label"><span aria-hidden="true">💤</span>Not Planning</span></div> : <button className="kw-not-planning" onClick={() => onInclude?.(meal, true)} disabled={!onInclude} aria-label={`Plan ${label} ${slot} after all`}>{slotHeader}<span className="kw-not-planning-label"><span aria-hidden="true">💤</span>Not Planning</span></button>)
            : meal ? <article data-food-drop={board ? `meal:${meal.id}` : undefined} className={`kw-meal-card ${selectedId === meal.id ? "is-selected" : ""} ${referencedIds.includes(meal.id) ? "is-referenced" : ""} ${board?.over === `meal:${meal.id}` ? "is-drop-over" : ""} ${meal.status}`}>{referencedIds.includes(meal.id) && <span className="kw-ref-badge" title="Referenced in the Stu chat">💬</span>}
              <button className="kw-meal-open" onClick={event => { if (board?.picked && meal.status === "planned" && !meal.locked) board.onPlace({ kind: "meal", mealId: meal.id }); else if ((event.metaKey || event.ctrlKey) && onReference) onReference(meal); else onSelect(meal); }} aria-label={`Open ${label} ${slot}`} aria-pressed={selectedId === meal.id} title={`${meal.components.map(component => component.name).join(" + ")} · ${Math.max(0, ...meal.components.map(component => component.portions))} portions · ${meal.activeMinutes} min hands-on · ${meal.elapsedMinutes} min elapsed`}>
                {slotHeader}
                <span className="kw-meal-title"><span className="kw-food-emoji" aria-hidden="true">{foodEmoji(meal.components[0]?.name||"",meal.components[0]?.type)}</span><strong>{meal.components.length ? meal.components.map((c, i) => <Fragment key={c.id}>{i ? " + " : ""}{c.name}<AlsoMark primary={c.type} groups={componentGroups(c, state)} /></Fragment>) : "Untitled meal"}</strong></span>
                <small className="kw-meal-meta"><span>{meal.activeMinutes} min</span><span>{source.replace("Prepare fresh","Fresh")} {source.includes("fridge")?"🧊":"🌿"}</span></small>
                {missing && <span className="kw-shortage" title={`Not in the fridge yet — prepare on prep day: ${missing.map(item => `${item.name} ×${item.portions}`).join(", ")}`}>🥣 To prep: {missing.map(item => `${item.name} ×${item.portions}`).join(", ")}</span>}
              </button>
              <div className="kw-card-tools">
                {meal.locked && <button className="kw-meal-lock" aria-label="Unlock weekly meal" title="Locked every week · click to unlock" onClick={event=>{event.stopPropagation();onUnlock?.(meal);}}><LockSimple size={13} weight="fill"/></button>}
                {meal.status !== "planned" && <span className="kw-meal-state">{meal.status}</span>}
                <div className="kw-meal-quick-actions">
                  {!planning && plan?.status === "confirmed" && <>
                    <button aria-label={`Mark ${label} ${slot} completed`} className={`kw-complete ${meal.status === "completed" ? "selected" : ""}`} disabled={meal.status !== "planned"} onClick={() => onStatus(meal, "completed")} title="Mark completed"><span aria-hidden="true">✓</span></button>
                    <button className={`kw-skip ${meal.status === "skipped" ? "selected" : ""}`} aria-label={`Skip ${label} ${slot}`} disabled={meal.status !== "planned"} onClick={() => onStatus(meal, "skipped")} title="Skip meal"><span aria-hidden="true">✗</span></button>
                    <button aria-pressed={meal.liked} aria-label={`Baby liked ${label} ${slot}`} className={`kw-liked ${meal.liked ? "selected" : ""}`} onClick={() => onLike(meal)} title="Baby liked it"><span aria-hidden="true">♥</span></button>
                  </>}
                  {onReplace && <button className="kw-secondary-action" aria-label={`Replace ${label} ${slot}`} disabled={meal.locked || meal.status !== "planned"} onClick={() => onReplace(meal)} title="Replace meal"><ArrowsClockwise size={15}/></button>}
                  {onReference && <button className="kw-secondary-action" aria-label={`Reference ${label} ${slot} in chat`} onClick={() => onReference(meal)} title="Reference in chat (or ⌘/Ctrl-click the meal)"><ChatCircleDots size={15}/></button>}
                  {!planning && onInclude && meal.status === "planned" && <button className="kw-secondary-action" aria-label={`Do not plan ${label} ${slot}`} onClick={() => onInclude(meal, false)} title="Do not plan this slot"><span aria-hidden="true">💤</span></button>}
                </div>
              </div>
              {board && meal.status === "planned" && !meal.locked && <FridgeDishes meal={meal} where={`${label} ${slot}`} board={board} />}
              {planning && plan?.status === "draft" && onAddToMeal && <button className="kw-add-from-recipes" onClick={() => onAddToMeal(meal)} aria-label={`Add a dish to ${label} ${slot}`}><Plus size={12}/>Add from recipes</button>}
            </article> : planning ? (slotState?.(day, slot) === "add"
              ? board?.picked
                ? <button data-food-drop={`slot:${day}:${slot}`} className={`kw-add-meal kw-add-slot is-placing ${board.over === `slot:${day}:${slot}` ? "is-drop-over" : ""}`} onClick={() => board.onPlace({ kind: "slot", day, slot })} aria-label={`Put ${board.picked.name} in ${label} ${slot}`}>{slotHeader}<span className="kw-add-meal-label"><Plus size={13} />{board.picked.name}</span></button>
                : <button data-food-drop={board ? `slot:${day}:${slot}` : undefined} className={`kw-add-meal kw-add-slot ${board?.over === `slot:${day}:${slot}` ? "is-drop-over" : ""}`} onClick={() => onAdd(day, slot)} aria-label={`Add ${label} ${slot} from recipes`}>{slotHeader}<span className="kw-add-meal-label"><Plus size={13} />Add from recipes</span></button>
              : slotState?.(day, slot) === "off"
                ? <div className="kw-not-planning is-static">{slotHeader}<span className="kw-not-planning-label"><span aria-hidden="true">💤</span>Not Planning</span></div>
                : <div className="kw-add-meal is-static">{slotHeader}<span className="kw-add-meal-label">—</span></div>) : <button className="kw-add-meal" onClick={() => onAdd(day, slot)} aria-label={`Add ${label} ${slot}`}>{slotHeader}<span className="kw-add-meal-label"><Plus size={15}/>Add</span></button>}
          </div>;
        })}
        <div className={`kw-day-total ${total > state.settings.maxDailyActiveMinutes ? "over-budget" : ""}`}><span>⏱️ {total} mins</span></div>
      </section>;
    })}
  </div></div>;
}

/** A meal's dishes served from fridge batches: each can be dragged off (back to
 * the fridge or to another meal), or lose a portion with "−". With a food
 * picked in the fridge, the meal offers to take it. */
function FridgeDishes({ meal, where, board }: { meal: Meal; where: string; board: CalendarBoard }) {
  const dishes = meal.components.filter(c => c.inventoryId && !c.prepId);
  if (!dishes.length && !board.picked) return null;
  return <div className="kw-card-foods">
    {dishes.map(c => <span key={c.id} className="kw-card-food" onPointerDown={event => board.onDragDish(event, meal, c)} title={`${c.name} ×${c.portions} · drag to the fridge or another meal`}>
      <span aria-hidden="true">{foodEmoji(c.name, c.type)}</span><span className="kw-card-food-name">{c.name}</span><span>×{c.portions}</span>
      <button type="button" aria-label={`Take one ${c.name} off ${where}`} onClick={() => board.onTakeOne(meal, c.id)}>−</button>
    </span>)}
    {board.picked && <button type="button" className="kw-card-place" onClick={() => board.onPlace({ kind: "meal", mealId: meal.id })} aria-label={`Add ${board.picked.name} to ${where}`}>+ {board.picked.name}</button>}
  </div>;
}
