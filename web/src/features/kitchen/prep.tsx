"use client";
import { foodEmoji } from "./food-art";
import { useMemo, useState, useSyncExternalStore } from "react";
import { AddPrepDialog } from "./add-prep-dialog";
import { useStored } from "./browser-store";
import "./fridge-arrange.css";
import { weekPrep } from "./prep-from-fridge";
import { prepSchedule, prepUnavailable, projectedMealShortages } from "./schedule";
import type { PageProps, PrepTask } from "./types";

const ORDER = ["Protein", "Carbs", "Vegetables", "Baking", "Other"] as const;
/** Frame 7:800 groups the dish list under plural headings. */
const GROUP: Record<string, string> = { Protein: "Proteins", Carbs: "Carbs", Vegetables: "Vegetables", Baking: "Baking", Other: "Other" };

function hours(total: number) {
  if (total < 60) return `${total}min`;
  const rest = total % 60;
  return rest ? `${Math.floor(total / 60)}h ${rest}min` : `${Math.floor(total / 60)}h`;
}

/** "Batch Prep" vs "Same-day" on the dish list, counted from the meals that use
 * the task rather than stored: a dish eaten on the prep day itself is same-day
 * work, a dish that has to survive until later in the week is batch cooking. */
function batchLabel(task: PrepTask, plan: NonNullable<PageProps["plan"]>, prepDay: string | null, people: number) {
  const days = new Set(plan.meals.filter(m => m.components.some(c => c.prepId === task.id)).map(m => m.day));
  if (!days.size) return task.plannedPortions > people ? "Batch Prep" : "Same-day";
  if (days.size > 1) return "Batch Prep";
  return prepDay && [...days][0] === prepDay ? "Same-day" : "Batch Prep";
}

/** A quick task: no recipe and nothing to make (thaw the beef, wash the greens).
 * A + Prep dish is not one: it cooks fridge foods into a dish. */
const isQuick = (task: PrepTask) => !task.recipeId && task.plannedPortions === 0 && !task.outputInventoryId && task.origin !== "fridge";

/** How far along a dish is, 0–1: done is all the way, otherwise the steps ticked. */
function progress(task: PrepTask, ticked: number[]) {
  if (task.status === "completed") return 1;
  if (task.status === "skipped" || !task.steps.length) return 0;
  return ticked.filter(i => i < task.steps.length).length / task.steps.length;
}

function PrepDetail({ task, plan, send, state, ticked, onTick }: { task: PrepTask; plan: NonNullable<PageProps["plan"]>; send: PageProps["send"]; state: PageProps["state"]; ticked: number[]; onTick: (steps: number[]) => void }) {
  const [actual, setActual] = useState(String(task.actualPortions || task.plannedPortions));
  const [busy, setBusy] = useState(false);
  // A + Prep dish is done before its week is confirmed (batch prep waits),
  // asking only how many portions are left over and where they go.
  const fromFridge = task.origin === "fridge", executable = plan.status === "confirmed" || fromFridge;
  const [finishing, setFinishing] = useState(false), [extra, setExtra] = useState("0"), [place, setPlace] = useState<"freezer" | "fridge">("freezer");
  const latestExecution = [...state.audit].reverse().find(a => { const entry = a as typeof a & { undone?: boolean; undo?: { entityId?: string; collection?: string; planId?: string } }; return entry.kind === "prep.status" && !entry.undone && entry.undo?.entityId === task.id && entry.undo.collection === "prep" && entry.undo.planId === plan.id; });
  const unavailable = prepUnavailable(state, plan, task);
  const recipe = state.recipes.find(r => r.id === task.recipeId);
  const linked = plan.meals.filter(meal => meal.components.some(c => c.prepId === task.id));
  const stock = state.inventory.find(i => i.id === task.outputInventoryId);
  const execute = async () => {
    if (unavailable.length) return;
    setBusy(true);
    try { await send("prep.status", { planId: plan.id, prepId: task.id, status: "completed", actualPortions: Number(actual) }); } finally { setBusy(false); }
  };
  const ready = !busy && !unavailable.length && actual !== "" && Number.isFinite(Number(actual)) && Number(actual) >= 0;
  const extraOk = !busy && !unavailable.length && extra !== "" && Number.isFinite(Number(extra)) && Number(extra) >= 0;
  const finish = async () => {
    setBusy(true);
    try { if (await send("prep.status", { planId: plan.id, prepId: task.id, status: "completed", actualPortions: Number(extra), location: place })) setFinishing(false); } finally { setBusy(false); }
  };
  const remove = async () => { setBusy(true); try { await send("prep.delete", { planId: plan.id, prepId: task.id }); } finally { setBusy(false); } };

  return <article className="kw-card kw-prep-current">
    <header className="kw-prep-detail-head">
      <span className="kw-prep-avatar" aria-hidden="true">{foodEmoji(task.name, task.type)}</span>
      <div className="kw-prep-detail-title">
        <h3>{task.name}</h3>
        <div className="kw-prep-chips">{fromFridge ? <><span className="on">🔪 From the fridge</span><span>{task.activeMinutes} min</span></> : isQuick(task) ? <span className="on">Quick task</span> : <><span>×{task.plannedPortions} 份</span><span>{task.type}</span><span className="on">{batchLabel(task, plan, null, state.settings.people)}</span></>}</div>
      </div>
      <div className="kw-prep-detail-links">
        {linked.map(meal => <span key={meal.id} className="kw-meal-date-tag">{new Date(meal.day + "T12:00:00").toLocaleDateString("en-US", { weekday: "short" })} {meal.slot}</span>)}
        {!linked.length && <span className="kw-muted small">For your fridge</span>}
        {plan.status === "confirmed" && task.status === "planned" && !isQuick(task) && !fromFridge && <span className="kw-prep-yield"><span aria-hidden="true">🧊</span>{stock ? `${stock.name} ${stock.portions} →` : "Freezer →"}
          <button type="button" className="kw-step" aria-label={`One portion fewer for ${task.name}`} onClick={() => setActual(String(Math.max(0, Number(actual || 0) - 1)))}>−</button>
          <input className="kw-prep-yield-value" aria-label={`Actual portions for ${task.name}`} type="number" min="0" step="0.25" value={actual} onChange={e => setActual(e.target.value)} />
          <button type="button" className="kw-step add" aria-label={`One portion more for ${task.name}`} onClick={() => setActual(String(Number(actual || 0) + 1))}>+</button>
        </span>}
      </div>
    </header>

    {task.status === "completed" && fromFridge && <p className="kw-muted">Done · {task.actualPortions ? `${task.actualPortions} extra portion${task.actualPortions === 1 ? "" : "s"} put away` : "nothing extra"}</p>}
    {task.status === "completed" && !isQuick(task) && !fromFridge && <p className="kw-muted">Produced {task.actualPortions} portions{task.actualPortions < task.plannedPortions ? ` · ${task.plannedPortions - task.actualPortions} fewer than planned` : ""}</p>}
    {task.status === "planned" && unavailable.length > 0 && <ul className="kw-error">{unavailable.map(message => <li key={message}>{message}</li>)}</ul>}

    {fromFridge && <section className="kw-prep-ingredients" aria-label={`From the fridge for ${task.name}`}><h4>From your fridge</h4>
      <ul>{task.inputs.map(input => { const item = state.inventory.find(i => i.id === input.inventoryId); return <li key={input.inventoryId}><span><span aria-hidden="true">{item?.emoji ?? foodEmoji(item?.name ?? "", item?.type)} </span>{item?.name ?? "Stored ingredient"}</span><strong>{input.portions} portion{input.portions === 1 ? "" : "s"}</strong></li>; })}</ul>
    </section>}
    {!isQuick(task) && !fromFridge && <section className="kw-prep-ingredients" aria-label={`Ingredients for ${task.name}`}><h4>Ingredients <span>for {task.plannedPortions} portions</span></h4>
      {recipe?.ingredients.length ? <ul>{recipe.ingredients.map((ingredient, index) => <li key={index}><span>{ingredient.name}</span><strong>{Math.round(ingredient.quantity * task.plannedPortions / recipe.servings * 100) / 100} {ingredient.unit}</strong></li>)}</ul> : task.inputs.length ? <ul>{task.inputs.map(input => <li key={input.inventoryId}><span>{state.inventory.find(i => i.id === input.inventoryId)?.name ?? "Stored ingredient"}</span><strong>{input.portions} portions</strong></li>)}</ul> : <p className="kw-muted small">Add ingredients to the linked recipe to see the shopping quantities.</p>}
    </section>}

    <ol className="kw-prep-steps">
      {task.steps.map((body, index) => {
        const detail = recipe?.stepDetails?.find(d => d.index === index);
        const on = ticked.includes(index) || task.status === "completed";
        return <li key={index}><label className={`kw-prep-step ${on ? "on" : ""}`}>
          <input type="checkbox" checked={on} disabled={task.status === "completed"} onChange={e => onTick(e.target.checked ? [...ticked, index] : ticked.filter(i => i !== index))} />
          <span className="kw-prep-step-body">{detail?.title && <strong>{detail.title}</strong>}<span>{body}</span></span>
          <span className="kw-prep-step-times">{detail?.activeMinutes ? <em>{detail.activeMinutes} min</em> : null}{detail?.waitMinutes ? <em className="wait">{detail.waitMinutes} min</em> : null}</span>
        </label></li>;
      })}
    </ol>

    {!!task.equipment.length && <p className="kw-muted small">Equipment: {task.equipment.join(", ")}</p>}
    {!!task.dependencies.length && <p className="kw-muted small">After: {task.dependencies.map(id => plan.prep.find(p => p.id === id)?.name || id).join(", ")}</p>}

    {/* One action while the task is open; after it, a way back if tapped by mistake. */}
    <div className="kw-prep-actions">
      {plan.status === "confirmed" && task.status === "planned" && !fromFridge && <button className="kw-mark-all" aria-label="Mark prepared" disabled={!ready} onClick={() => void execute()}>Mark All Done ✅</button>}
      {fromFridge && task.status === "planned" && (finishing
        ? <form className="kw-prep-finish" onSubmit={event => { event.preventDefault(); if (extraOk) void finish(); }}>
            <label className="kw-label">Extra portions<input className="kw-input" type="number" min="0" step="0.5" autoFocus value={extra} onChange={e => setExtra(e.target.value)} /></label>
            <div className="kw-prep-place" role="group" aria-label="Put them in"><button type="button" aria-pressed={place === "freezer"} onClick={() => setPlace("freezer")}>❄️ Freezer</button><button type="button" aria-pressed={place === "fridge"} onClick={() => setPlace("fridge")}>🧊 Fridge</button></div>
            <p className="kw-muted small">Only what is left after this weekend’s meals; nothing extra puts nothing away.</p>
            <div className="kw-prep-finish-actions"><button type="submit" className="kw-button" disabled={!extraOk}>Save</button><button type="button" className="kw-button secondary" onClick={() => setFinishing(false)}>Cancel</button></div>
          </form>
        : <><button className="kw-mark-all" disabled={busy || !!unavailable.length} onClick={() => setFinishing(true)}>✓ Done</button><button className="kw-button secondary" disabled={busy} onClick={() => void remove()}>Remove</button></>)}
      {executable && task.status !== "planned" && latestExecution && <button className="kw-button" disabled={busy} onClick={async () => { setBusy(true); try { await send("change.undo", { auditId: latestExecution.id }); } finally { setBusy(false); } }}>{task.status === "skipped" ? "Undo skip" : "Undo completion"}</button>}
    </div>
  </article>;
}

export function PrepPage({ state, plan, send, navigate, embedded = false, compact = false, onExpand }: PageProps & { embedded?: boolean; compact?: boolean; onExpand?: () => void }) {
  const [adding, setAdding] = useState(false), [selected, setSelected] = useState<string | null>(null), [category, setCategory] = useState<string | null>(null), [recommended, setRecommended] = useState(true);
  // The steps ticked off while cooking, per dish, kept on this device so the
  // dish list can show how far each dish has got.
  const [storedTicks, writeTicks] = useStored("local", `stu-prep-steps:${plan?.id ?? "none"}`);
  const ticks = useMemo<Record<string, number[]>>(() => { try { return storedTicks ? JSON.parse(storedTicks) : {}; } catch { return {}; } }, [storedTicks]);
  // Estimated finish is clock time: read it from a subscribed minute ticker so
  // the server renders nothing (a server minute would hydrate against a
  // different client minute) and the estimate keeps up while you cook.
  const minute = useSyncExternalStore(
    onChange => { const timer = setInterval(onChange, 60_000); return () => clearInterval(timer); },
    () => Math.floor(Date.now() / 60_000),
    () => null,
  );
  // The week's prep day: this plan's prep, and + Prep dishes another plan of
  // the week holds (a prep-only draft from before Stu drafted the week).
  const items = plan ? weekPrep(state.plans, plan) : [];
  const owners = new Map(items.map(({ task, owner }) => [task.id, owner]));
  const day = plan ? { ...plan, prep: items.map(item => item.task) } : null;
  let timing: ReturnType<typeof prepSchedule> | null = null;
  let timingError = "";
  if (day) { try { timing = prepSchedule(state, day); } catch (error) { timingError = error instanceof Error ? error.message : "Unable to calculate prep timing."; } }
  const impacts = plan ? projectedMealShortages(state, plan) : [];
  const ordered = day ? [...day.prep].sort((a, b) => recommended ? (timing?.tasks.find(t => t.id === a.id)?.startMinutes ?? 0) - (timing?.tasks.find(t => t.id === b.id)?.startMinutes ?? 0) : 0) : [];
  const current = ordered.find(t => t.id === selected) ?? ordered.find(t => t.status === "planned") ?? ordered[0];
  const done = day?.prep.filter(p => p.status === "completed").length ?? 0;
  const prepDate = plan ? new Date(plan.weekStart + "T12:00:00") : null;
  if (prepDate) prepDate.setDate(prepDate.getDate() - 7 + state.settings.prepDay);
  const prepDay = prepDate ? prepDate.toISOString().slice(0, 10) : null;
  const remaining = (day?.prep ?? []).filter(t => t.status === "planned").reduce((total, t) => total + t.elapsedMinutes, 0);
  const finish = minute !== null && remaining ? new Date((minute + remaining) * 60_000) : null;
  const wait = Math.max(0, (timing?.elapsedMinutes ?? 0) - (timing?.activeMinutes ?? 0));

  return <section className={`kw-support-page kw-prep-page ${embedded ? "is-embedded" : ""} ${compact ? "is-compact" : ""}`}>
    <header className="kw-page-header">
      <div><h1 aria-label="Prep">Prep Day! 🍳 👨‍🍳</h1><p className="kw-muted">Weekend Batch Cooking · {prepDate ? prepDate.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" }) : "Plan your week"}</p></div>
      <div className="kw-prep-stats">
        <div>⏱️ <span>TOTAL ACTIVE TIME<strong>{hours(timing?.activeMinutes ?? 0)}</strong></span></div>
        <div>⌛ <span>TOTAL WAIT TIME<strong>~{hours(wait)}</strong></span></div>
        <div>📋 <span>TASKS<strong>{day?.prep.length ?? 0} tasks</strong></span></div>
      </div>
    </header>
    {adding && plan && <AddPrepDialog state={state} plan={plan} send={send} onClose={() => setAdding(false)} onAdded={id => { setAdding(false); setSelected(id); }} />}
    {!plan || !day || !day.prep.length ? <div className="kw-empty">No batch cooking scheduled.<button className="kw-button" onClick={() => navigate("plan")}>Open Plan</button></div> : <>
      {timingError && <p role="alert" className="kw-error">{timingError}</p>}
      {plan.status === "draft" && day.prep.some(t => t.origin !== "fridge") && <p className="kw-support-notice">Preview only. Confirm this plan before recording prep or changing stock.</p>}

      {/* The frame's category pills count and highlight a group; the dish list
          keeps showing every dish, because hiding the rest of the session is
          not what a cook standing at the stove wants. */}
      <div className="kw-prep-toolbar"><div className="kw-prep-tabs">{ORDER.filter(type => day.prep.some(t => t.type === type)).map(type => <button key={type} className={`kw-button secondary ${category === type ? "is-active" : ""}`} aria-pressed={category === type} onClick={() => setCategory(current => current === type ? null : type)}>{foodEmoji("", type)} {GROUP[type]} <span>{day.prep.filter(t => t.type === type).length}</span></button>)}</div><label className="kw-support-toggle">Recommended order ✨<input type="checkbox" checked={recommended} onChange={e => setRecommended(e.target.checked)} /></label></div>

      <div className="kw-prep-layout">
        <section className="kw-dish-list" aria-label="Dish list">
          <header><h2>Dish List 🍴</h2><span>{day.prep.length} dish{day.prep.length === 1 ? "" : "es"}</span></header>
          {ORDER.filter(type => ordered.some(t => t.type === type)).map(type => <div className={`kw-dish-group ${category === type ? "on" : ""}`} key={type}>
            <span className="kw-dish-chip">{foodEmoji("", type)} {GROUP[type]}</span>
            {ordered.filter(t => t.type === type).map(task => <button key={task.id} className={`kw-dish-row ${task.id === current?.id ? "on" : ""}`} aria-pressed={task.id === current?.id} onClick={() => { setSelected(task.id); if (compact) onExpand?.(); }}>
              <span className={`kw-dish-dot type-${task.type}`} aria-hidden="true" />
              <strong>{task.name}</strong>
              <span className="kw-dish-badge">{task.origin === "fridge" ? "🔪 Fridge" : isQuick(task) ? "Task" : batchLabel(task, plan, prepDay, state.settings.people)}</span>
              {/* Progress, not a checkbox: dishes are finished from their own card. */}
              <span className={`kw-dish-progress ${task.status}`} aria-hidden="true"><span style={{ width: `${Math.round(progress(task, ticks[task.id] ?? []) * 100)}%` }} /></span>
              <span className="sr-only">{task.status === "completed" ? "Done" : task.status === "skipped" ? "Skipped" : `${Math.round(progress(task, ticks[task.id] ?? []) * 100)}% done`}</span>
            </button>)}
          </div>)}
          <button className="kw-button secondary kw-dish-add" onClick={() => setAdding(true)}>+ Add prep task</button>
        </section>
        {current && <PrepDetail key={current.id} task={current} plan={owners.get(current.id) ?? plan} send={send} state={state} ticked={ticks[current.id] ?? []} onTick={steps => writeTicks(JSON.stringify({ ...ticks, [current.id]: steps }))} />}
      </div>

      <div className="kw-prep-progress"><strong>{done} of {day.prep.length} completed 🎯{finish ? ` · Est. finish: ${finish.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })} ⏰` : ""}</strong><progress value={done} max={day.prep.length} /><button className="kw-button kw-yellow" onClick={() => navigate("calendar")}>Back to calendar →</button></div>

      <details className="kw-prep-diagnostics"><summary>Session timing & stock availability</summary>
        {timing && <div className="kw-support-notice"><p>Full session estimate: one cook, active work first, equipment reserved until each task finishes. Waiting may overlap other active work.</p><p>Ordinary prep ready by minute {timing.ordinaryReadyMinutes} · Ordinary prep and total active limit {state.settings.maxPrepMinutes} min</p></div>}
        {timing && <div className="kw-support-table-wrap"><table className="kw-support-table"><caption>Recommended prep order</caption><thead><tr><th>Task</th><th>Hands-on window</th><th>Ready at</th><th>Equipment</th></tr></thead><tbody>{[...timing.tasks].sort((a, b) => a.startMinutes - b.startMinutes).map(row => { const task = day.prep.find(t => t.id === row.id); return <tr key={row.id}><td>{task?.name ?? row.id}</td><td>{row.startMinutes}–{row.startMinutes + (task?.activeMinutes ?? 0)} min</td><td>{row.finishMinutes} min</td><td>{task?.equipment.join(", ") || "—"}</td></tr>; })}</tbody></table></div>}
        {impacts.length > 0 && <section className="kw-card kw-support-editor"><h2>Meals affected by stock shortages</h2><p className="kw-muted">Projected in day order using available stock, feasible planned prep and reservations in other confirmed plans. Actual output may change these amounts.</p>{impacts.map(({ meal, missing }) => <div key={meal.id}><strong>{new Date(meal.day + "T12:00:00").toLocaleDateString("en-US", { weekday: "short" })} {meal.slot}</strong><ul>{missing.map(item => <li key={item.name}>{item.name}: short {item.portions} portion{item.portions === 1 ? "" : "s"}</li>)}</ul></div>)}</section>}
      </details>
    </>}
  </section>;
}
