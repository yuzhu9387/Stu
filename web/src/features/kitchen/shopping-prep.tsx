"use client";
import { useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { PrepPage } from "./prep";
import { shoppingList } from "./shopping";
import type { FoodType, InventoryItem, PageProps } from "./types";

/** A shopping line's fridge batch: the same line is never stocked twice. */
function boughtId(planId: string, key: string) {
  let hash = 5381;
  for (const char of key) hash = (hash * 33 + char.charCodeAt(0)) >>> 0;
  return `bought-${planId}-${hash.toString(36)}`;
}
const FOOD_TYPES: FoodType[] = ["Protein", "Carbs", "Vegetables", "Dairy", "Other"];
/** The food group of a bought ingredient, from its shopping group. */
function foodType(group: string): FoodType {
  if ((FOOD_TYPES as string[]).includes(group)) return group as FoodType;
  if (/肉|鱼|虾|蛋|禽|meat|fish|egg|protein/i.test(group)) return "Protein";
  if (/菜|蔬|果|veg|fruit/i.test(group)) return "Vegetables";
  if (/米|面|粉|谷|grain|rice|noodle|carb/i.test(group)) return "Carbs";
  if (/奶|乳|dairy|milk|cheese/i.test(group)) return "Dairy";
  return "Other";
}
const today = (timezone: string) => new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());

export function ShoppingPrepPage({ focus: savedFocus = "shopping", onFocus, notice, ...props }: PageProps & { notice?: ReactNode; focus?: "shopping" | "prep"; onFocus: (focus: "shopping" | "prep") => Promise<void> }) {
  const { state, plan, send, navigate } = props;
  const [selection, setSelection] = useState<{ from: "shopping" | "prep"; to: "shopping" | "prep" } | null>(null);
  const focus = selection && selection.from === savedFocus ? selection.to : savedFocus;
  const [pending, setPending] = useState(false), [error, setError] = useState<string | null>(null);
  // How many bought items the last "Update fridge" put away (0: nothing was ticked).
  const [putAway, setPutAway] = useState<number | null>(null);
  const [pendingCheck, setPendingCheck] = useState<{ keys: string[]; value: boolean } | null>(null);
  const list = useMemo(() => plan?.fulfillment && !plan.fulfillment.stale ? {items:plan.fulfillment.shopping.map(i=>({...i,key:JSON.stringify([i.name.normalize("NFKC").trim().toLocaleLowerCase().replace(/\s+/g," "),i.unit,i.toBuy])})),warnings:plan.fulfillment.warnings} : plan ? shoppingList(state, plan) : { items: [], warnings: [] }, [state, plan]);
  if (!plan) return null;
  const needed = list.items.filter(i => i.toBuy > 0), stocked = list.items.filter(i => i.toBuy === 0);
  const checked = new Set(plan.shoppingChecked ?? []);
  // Picked-up lines not yet put away. Grams become one pack of that weight, so
  // the list counts them as in stock; other units keep their count and a note.
  const toStock = needed.filter(i => checked.has(i.key) && !state.inventory.some(s => s.id === boughtId(plan.id, i.key)));
  if (pendingCheck) for (const key of pendingCheck.keys) { if (pendingCheck.value) checked.add(key); else checked.delete(key); }
  const done = needed.filter(i => checked.has(i.key)).length;
  const allDone = needed.length > 0 && done === needed.length;
  async function expand(next: "shopping" | "prep") {
    if (pending || focus === next) return;
    setPending(true); setError(null); setSelection({ from: savedFocus, to: next });
    try { await onFocus(next); } catch (e) { setSelection(null); setError(e instanceof Error ? e.message : "Unable to save progress."); } finally { setPending(false); }
  }
  /** One item, or every item still to buy ("Mark all picked up") in one save. */
  async function stockFridge() {
    if (!toStock.length) { setPutAway(0); return; }
    const added: InventoryItem[] = toStock.map(i => ({ id: boughtId(plan!.id, i.key), name: i.name, type: foodType(i.group), portions: i.unit === "g" || i.unit === "ml" ? 1 : i.toBuy, ...(i.unit === "g" ? { portionGrams: i.toBuy } : {}), location: "Fridge", prepared: false, addedOn: today(state.settings.timezone), priority: false, notes: `Bought ${i.toBuy} ${i.unit}` }));
    setPending(true); setError(null); setPutAway(null);
    try { if (await send("inventory.receive", { items: added }, { quiet: true })) setPutAway(added.length); else setError("Unable to update the fridge. Please try again."); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to update the fridge."); }
    finally { setPending(false); }
  }
  /** A folded panel opens from a click anywhere in it that is not on a control. */
  const openOnBlank = (next: "shopping" | "prep") => (event: MouseEvent<HTMLElement>) => {
    if (focus === next || (event.target as HTMLElement).closest("button,a,input,select,textarea,label,summary")) return;
    void expand(next);
  };
  async function check(keys: string[], value: boolean) {
    if (!keys.length) return;
    setPending(true); setError(null); setPendingCheck({ keys, value });
    try { if (!await send("shopping.check", keys.length === 1 ? { planId: plan!.id, key: keys[0], checked: value } : { planId: plan!.id, keys, checked: value })) setError("Unable to save the shopping checklist. Please try again."); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to save the shopping checklist."); }
    finally { setPending(false); setPendingCheck(null); }
  }
  return <section className="kw-shopping-prep" aria-label="Shopping and prep">
    
    {error && <p role="alert" className="kw-inline-error">{error}</p>}
    {notice && <div className="kw-prep-feedback">{notice}</div>}
    <div className={`kw-fulfilment-panels focus-${focus}`}>
      <section className={`kw-shopping-panel ${focus === "shopping" ? "is-expanded" : "is-collapsed"}`} aria-label="Shopping cart" onClick={openOnBlank("shopping")}>
        <button className="kw-panel-toggle" aria-expanded={focus === "shopping"} aria-controls="shopping-items" disabled={pending} onClick={() => void expand("shopping")}><span className="kw-panel-symbol">🛒</span><span><strong>Shopping cart</strong><small>{done} of {needed.length} picked up</small></span><span className="kw-panel-indicator" aria-hidden="true" /></button>
        <div id="shopping-items" className="kw-shopping-body">
          {focus === "shopping" && needed.length > 0 && <div className="kw-shopping-progress">
            <progress aria-label="Shopping progress" value={done} max={Math.max(1, needed.length)} />
            <button type="button" className="kw-shopping-all" disabled={pending} onClick={() => void check(allDone ? needed.map(i => i.key) : needed.filter(i => !checked.has(i.key)).map(i => i.key), !allDone)}>{allDone ? "Clear all" : "Mark all picked up ✓"}</button>
          </div>}
          {!needed.length && <div className="kw-shopping-empty"><span aria-hidden="true">{list.warnings.length ? "📝" : "✓"}</span><strong>{list.warnings.length ? "Check the items below" : "Nothing to buy"}</strong><p>{list.warnings.length ? "Some recipes or amounts still need review." : stocked.length ? "Your recorded stock covers the ingredients." : "There are no outstanding ingredients in this plan."}</p></div>}
          {[...new Set(needed.map(i => i.group))].map(group => <div className="kw-shopping-group" key={group}><h3>{group}</h3>{needed.filter(i => i.group === group).map(item => <label key={item.key} className={`kw-shopping-item ${checked.has(item.key) ? "is-picked" : ""}`}><input type="checkbox" aria-label={`Purchased ${item.name} ${item.toBuy} ${item.unit}`} checked={checked.has(item.key)} disabled={pending} onChange={e => void check([item.key], e.target.checked)} /><span><strong>{item.name}</strong>{focus === "shopping" && <small>{item.dishes.join(" · ")}{item.inStock > 0 && <><br />Need {item.required} {item.unit} · In fridge {item.inStock} {item.unit}</>}</small>}</span><b>{item.toBuy} <small>{item.unit}</small></b></label>)}</div>)}
          {focus === "shopping" && <>
            {stocked.length > 0 && <details className="kw-stock-covered"><summary>Already in your fridge · {stocked.length}</summary>{stocked.map(i => <p key={i.key}>{i.name}<span>{i.required} {i.unit}</span></p>)}</details>}
            {list.warnings.length > 0 && <div className="kw-shopping-review"><h3>Before you shop</h3><ul>{list.warnings.map(w => <li key={w}>{w}</li>)}</ul></div>}
            {putAway !== null && <p className="kw-stocked-note" role="status">{putAway ? <>Added {putAway} item{putAway === 1 ? "" : "s"} to the chilled fridge as raw food. <button type="button" onClick={() => navigate("fridge")}>View fridge →</button></> : "Tick what you picked up first, then update the fridge."}</p>}
            <footer className="kw-shopping-actions"><button className="kw-button secondary" disabled={pending} onClick={() => void stockFridge()}>{toStock.length ? `Update fridge · ${toStock.length} 🧊` : "Update fridge 🧊"}</button><button className="kw-cta" disabled={pending} onClick={() => void expand("prep")}>Ready for prep →</button></footer>
          </>}
        </div>
      </section>
      <section className={`kw-prep-panel ${focus === "prep" ? "is-expanded" : "is-collapsed"}`} aria-label="Prep day panel" onClick={openOnBlank("prep")}>
        <button className="kw-panel-toggle" aria-expanded={focus === "prep"} aria-controls="prep-panel-content" disabled={pending} onClick={() => void expand("prep")}><span className="kw-panel-symbol">🥣</span><span><strong>Prep day</strong><small>{plan.prep.filter(t => t.status === "completed").length} of {plan.prep.length} dishes ready</small></span><span className="kw-panel-indicator" aria-hidden="true" /></button>
        <div id="prep-panel-content"><PrepPage {...props} embedded compact={focus !== "prep"} onExpand={() => void expand("prep")} /></div>
      </section>
    </div>
  </section>;
}
