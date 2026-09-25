"use client";
import { foodEmoji } from "./food-art";
import { freshness } from "./data";
import { useMemo, useRef, useState } from "react";
import { useFridgeDrag, type Columns } from "./fridge-drag";
import "./fridge-arrange.css";
import type { FoodType, InventoryItem, PageProps } from "./types";

const types: FoodType[] = ["Protein", "Carbs", "Vegetables", "Dairy", "Other"];
/** Frame 7:651 prints the vegetable band as "Veggie"; the rest match the stored type. */
const BAND: Record<string, string> = { Protein: "Protein", Carbs: "Carbs", Vegetables: "Veggie", Dairy: "Dairy", Other: "Other" };

/** The frame draws real shelves, so a compartment holds a fixed number of cards
 * per row rather than a reflowing grid: a shelf carrying four items on one row
 * and two on the next stops reading as a shelf. The add tile always sits on the
 * last shelf, and a new empty shelf appears when the last one is full. */
function shelve(items: InventoryItem[], perShelf: number): InventoryItem[][] {
  const rows: InventoryItem[][] = [];
  for (let i = 0; i < items.length; i += perShelf) rows.push(items.slice(i, i + perShelf));
  if (!rows.length || rows[rows.length - 1].length === perShelf) rows.push([]);
  return rows;
}

function compartmentName(location: string) {
  const key = location.toLowerCase();
  if (key === "freezer") return "❄️ 冷冻 Freezer";
  if (key === "fridge") return "🧊 冷藏 Fridge";
  return `📦 ${location}`;
}

/** What is in the box: cooked ahead (半成品) or raw (生食). */
function FoodCardBody({ item }: { item: InventoryItem }) {
  const fresh = freshness(item.expiresOn);
  return <>
    <span className="kw-food-band">{BAND[item.type] ?? item.type}</span>
    <span className={`kw-food-kind ${item.prepared ? "prepared" : "raw"}`}>{item.prepared ? "半成品" : "生食"}</span>
    <span className="kw-food-art" aria-hidden="true">{item.emoji || foodEmoji(item.name, item.type)}</span>
    <span className="kw-food-line"><h3>{item.name}</h3><span className="kw-food-count">×{item.portions}</span>{item.priority && <span className="kw-food-flag" title="Use first">⭐</span>}</span>
    {fresh && fresh.tone !== "fresh" && <span className={`kw-food-expiry ${fresh.tone}`}>{fresh.label}</span>}
  </>;
}

function blank(location: string): InventoryItem {
  return { id: crypto.randomUUID(), name: "", type: "Protein", portions: 1, location, prepared: false, addedOn: new Date().toISOString().slice(0, 10), priority: false };
}

export function FridgePage({ state, plan, send, navigate }: PageProps) {
  const [editing, setEditing] = useState<InventoryItem | null>(null);
  const [search, setSearch] = useState("");
  // The corner × takes a box straight out; a box a meal still needs stays, and the reason shows.
  const remove = (item: InventoryItem) => void send("inventory.delete", { id: item.id }, { quiet: true });

  // Freezer first, then fridge, then anything the household invented.
  const extra = [...new Set(state.inventory.map(i => i.location).filter(l => !["fridge", "freezer"].includes(l.toLowerCase())))];
  const locations = ["Freezer", "Fridge", ...extra];
  const byId = new Map(state.inventory.map(item => [item.id, item]));
  const columns = useMemo<Columns>(() => Object.fromEntries(locations.map(location => [location.toLowerCase(), state.inventory.filter(i => i.location.toLowerCase() === location.toLowerCase()).map(i => i.id)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the locations follow the inventory
    [state.inventory]);
  const fridgeRef = useRef<HTMLDivElement>(null);
  /** A box let go somewhere new: save the whole order and any compartment change. */
  const { shown, dragId, ghost, ghostRef, over, start, clicked } = useFridgeDrag(fridgeRef, columns, async next => {
    const order = locations.flatMap(location => next[location.toLowerCase()] ?? []);
    const moves = locations.flatMap(location => (next[location.toLowerCase()] ?? []).filter(id => byId.get(id)?.location.toLowerCase() !== location.toLowerCase()).map(id => ({ id, location })));
    return send("inventory.arrange", { order, moves }, { quiet: true });
  });

  const groups = new Map<string, { name: string; type: string; onHand: number; planned: number; needed: number }>();
  const group = (name: string, type: string) => { const key = `${type}:${name.toLocaleLowerCase()}`; if (!groups.has(key)) groups.set(key, { name, type, onHand: 0, planned: 0, needed: 0 }); return groups.get(key)!; };
  state.inventory.forEach(i => { group(i.name, i.type).onHand += i.portions; });
  // A quick task (no recipe, nothing made) is not food on its way to the fridge.
  plan?.prep.filter(p => p.status === "planned" && (p.recipeId || p.plannedPortions > 0)).forEach(p => { group(p.name, p.type === "Baking" ? "Carbs" : p.type).planned += p.plannedPortions; p.inputs.forEach(input => { const item = state.inventory.find(i => i.id === input.inventoryId); if (item) group(item.name, item.type).needed += input.portions; }); });
  plan?.meals.filter(m => m.status === "planned").forEach(m => m.components.filter(c => c.inventoryId || c.prepId).forEach(c => { const item = state.inventory.find(i => i.id === c.inventoryId); const prep = plan.prep.find(p => p.id === c.prepId); group(item?.name || prep?.name || c.name, item?.type || (prep?.type === "Baking" ? "Carbs" : prep?.type) || c.type).needed += c.portions; }));
  const short = [...groups.values()].filter(g => g.needed > g.onHand + g.planned);

  return <section className="kw-support-page kw-fridge-page">
    <header className="kw-fridge-heading"><h1 aria-label="Fridge">冰箱</h1>{short.length > 0 && <span className="kw-pill kw-yellow">{short.length} Items Short! ⚠️</span>}</header>

    <div className="kw-fridge" ref={fridgeRef}>
      <header className="kw-fridge-badge"><span aria-hidden="true">🧊</span><strong>Kitchen Fridge</strong></header>
      <div className={`kw-fridge-body ${locations.length > 2 ? "wide" : ""}`}>
        {locations.map(location => {
          const key = location.toLowerCase();
          const items = (shown[key] ?? []).map(id => byId.get(id)).filter((item): item is InventoryItem => !!item);
          const perShelf = key === "fridge" ? 4 : 3;
          const rows = shelve(items, perShelf);
          return <section data-compartment={key} className={`kw-compartment ${key === "freezer" ? "freezer" : key === "fridge" ? "chilled" : "other"} ${over === key ? "is-drop-target" : ""}`} key={location}>
            <header><h2>{compartmentName(location)}</h2><span>{items.length} item{items.length === 1 ? "" : "s"}</span></header>
            <div className="kw-shelves">
              {rows.map((row, index) => <div className="kw-shelf" key={index} style={{ gridTemplateColumns: `repeat(${perShelf},minmax(0,1fr))` }}>
                {row.map(item => item.id === dragId
                  ? <span className="kw-food-card kw-food-placeholder" key={item.id} data-fridge-item={item.id} aria-hidden="true" />
                  : <div className="kw-food-cell" key={item.id} data-fridge-item={item.id}>
                    <button className={`kw-food-card type-${item.type}`} aria-label={`${item.name}, ${item.portions} portions, ${item.prepared ? "prepared" : "raw"}`} onPointerDown={event => start(event, item.id)} onClick={() => { if (clicked()) setEditing({ ...item }); }}>
                      <FoodCardBody item={item} />
                    </button>
                    <button type="button" className="kw-food-remove" aria-label={`Remove ${item.name}`} title="Remove" onClick={() => remove(item)}>×</button>
                  </div>)}
                {index === rows.length - 1 && <button className="kw-food-add" aria-label={`Add food to ${location}`} onClick={() => setEditing(blank(location))}>+</button>}
                {index === rows.length - 1 && Array.from({ length: Math.max(0, perShelf - row.length - 1) }, (_, i) => <span className="kw-food-slot" key={`slot-${i}`} aria-hidden="true" />)}
              </div>)}
            </div>
          </section>;
        })}
      </div>
      {ghost && byId.get(ghost.id) && <div ref={ghostRef} className={`kw-food-card kw-food-ghost type-${byId.get(ghost.id)!.type}`} style={{ width: ghost.width, height: ghost.height }} aria-hidden="true"><FoodCardBody item={byId.get(ghost.id)!} /></div>}
    </div>

    {editing && <FoodDialog key={editing.id} item={editing} state={state} plan={plan} send={send} navigate={navigate} onClose={() => setEditing(null)} />}

    <details className="kw-inventory-details"><summary>Search stock & weekly supply</summary>
      <label className="kw-label kw-support-search">Find food<input className="kw-input" placeholder="Search your fridge…" value={search} onChange={e => setSearch(e.target.value)} /></label>
      <div className="kw-support-table-wrap"><table className="kw-support-table"><caption>Supply for selected week · portions{plan?.status === "draft" ? " · draft projection" : ""}</caption><thead><tr><th>Food</th><th>On hand</th><th>Planned prep</th><th>Allocated</th><th>Shortage</th></tr></thead><tbody>{[...groups.values()].filter(g => g.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map(g => <tr key={`${g.type}:${g.name}`}><td>{g.name}<small>{g.type}</small></td><td>{g.onHand}</td><td>{g.planned}</td><td>{g.needed}</td><td className={g.needed > g.onHand + g.planned ? "kw-error" : ""}>{Math.max(0, g.needed - g.onHand - g.planned)}</td></tr>)}</tbody></table></div>
    </details>
  </section>;
}

/** Frame 110:5: the item opens as a modal over the fridge, not as a form above it.
 *
 * Control labels stay English so the page reads the same as the rest of the app;
 * the headings keep the frame's bilingual wording.
 */
function FoodDialog({ item, state, plan, send, navigate, onClose }: { item: InventoryItem; state: PageProps["state"]; plan: PageProps["plan"]; send: PageProps["send"]; navigate: PageProps["navigate"]; onClose: () => void }) {
  const [draft, setDraft] = useState(item);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const change = (fields: Partial<InventoryItem>) => setDraft(current => ({ ...current, ...fields }));
  const existing = state.inventory.some(i => i.id === item.id);
  const fresh = freshness(draft.expiresOn);
  const linked = (plan?.meals ?? []).filter(meal => meal.components.some(c => c.inventoryId === draft.id));
  const linkable = (plan?.meals ?? []).filter(meal => !linked.includes(meal) && meal.status === "planned");
  const dayName = (day: string) => new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" }).format(new Date(`${day}T12:00:00Z`));

  async function link(mealId: string) {
    const meal = plan?.meals.find(m => m.id === mealId);
    if (!meal || !plan) return;
    setBusy(true);
    try { await send("meal.save", { planId: plan.id, meal: { ...meal, components: [...meal.components, { id: crypto.randomUUID(), name: draft.name, type: draft.type, portions: 1, inventoryId: draft.id, recipeId: draft.recipeId }] } }); } finally { setBusy(false); }
  }

  return <div className="kw-modal-backdrop" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <form className="kw-modal kw-food-modal" role="dialog" aria-modal="true" aria-label={existing ? "Edit food" : "Add food"} onSubmit={async e => { e.preventDefault(); setBusy(true); try { if (await send("inventory.save", { item: { ...draft, name: draft.name.trim() } })) onClose(); } finally { setBusy(false); } }}>
      <header className="kw-modal-head">
        <input className="kw-food-emoji-input" aria-label="Icon" maxLength={8} placeholder="🥩" value={draft.emoji || ""} onChange={e => change({ emoji: e.target.value || undefined })} />
        <span className="kw-food-titles">
          <label className="kw-food-name-edit"><input className="kw-food-title" aria-label="Name" required autoFocus placeholder="Name" value={draft.name} onChange={e => change({ name: e.target.value })} /><span aria-hidden="true">✎</span></label>
          <input className="kw-food-subtitle" aria-label="English name" placeholder="English name" value={draft.nameEn || ""} onChange={e => change({ nameEn: e.target.value || undefined })} />
        </span>
        <button type="button" className="kw-modal-close" aria-label="Close" onClick={onClose}>✕</button>
      </header>

      <div className="kw-modal-body">
        <div className="kw-food-pair">
          <label className="kw-field">Category<select className="kw-food-select" aria-label="Type" value={draft.type} onChange={e => change({ type: e.target.value as FoodType })}>{types.map(t => <option key={t}>{t}</option>)}</select></label>
          <label className="kw-field">Location<span className="kw-segmented">{["Freezer", "Fridge"].map(place => <button type="button" key={place} className={draft.location.toLowerCase() === place.toLowerCase() ? "on" : ""} aria-pressed={draft.location.toLowerCase() === place.toLowerCase()} onClick={() => change({ location: place })}>{place === "Freezer" ? "冷冻 Freezer ❄️" : "冷藏 Fridge 🧊"}</button>)}</span></label>
        </div>

        <div className="kw-portion-box">
          <div><strong>Portions</strong><small>≈ <input className="kw-grams" aria-label="Grams per portion" type="number" min="1" step="1" placeholder="?" value={draft.portionGrams ?? ""} onChange={e => change({ portionGrams: Number.isNaN(e.target.valueAsNumber) ? undefined : e.target.valueAsNumber })} />g each</small></div>
          <button type="button" className="kw-step" aria-label="One portion fewer" onClick={() => change({ portions: Math.max(0, Math.round((draft.portions - 1) * 100) / 100) })}>−</button>
          <input className="kw-portion-value" aria-label="Portions" required type="number" min="0" step="0.25" value={draft.portions} onChange={e => change({ portions: e.target.valueAsNumber })} />
          <button type="button" className="kw-step add" aria-label="One portion more" onClick={() => change({ portions: Math.round((draft.portions + 1) * 100) / 100 })}>+</button>
        </div>

        <dl className="kw-food-dates">
          <div><dt>Stored</dt><dd><input className="kw-plain-input" aria-label="Added on" required type="date" value={draft.addedOn} onChange={e => change({ addedOn: e.target.value })} /></dd></div>
          <div><dt>Expires</dt><dd><input className="kw-plain-input" aria-label="Expires" type="date" min={draft.addedOn} value={draft.expiresOn || ""} onChange={e => change({ expiresOn: e.target.value || undefined })} /></dd></div>
          <div><dt>Status</dt><dd>{fresh ? <span className={`kw-freshness ${fresh.tone}`}>{fresh.label}</span> : <span className="kw-muted small">No expiry recorded</span>}</dd></div>
        </dl>

        <div className="kw-food-flags">
          <span className="kw-field">Kind<span className="kw-segmented">{([[true, "半成品 Prepared"], [false, "生食 Raw"]] as const).map(([value, label]) => <button type="button" key={label} className={draft.prepared === value ? "on" : ""} aria-pressed={draft.prepared === value} onClick={() => change({ prepared: value })}>{label}</button>)}</span></span>
          <label><input type="checkbox" checked={draft.priority} onChange={e => change({ priority: e.target.checked })} /> Use first ⭐</label>
          <label className="kw-field kw-grow">Recipe<select className="kw-food-select" aria-label="Recipe" value={draft.recipeId || ""} onChange={e => change({ recipeId: e.target.value || undefined })}><option value="">Unlinked</option>{state.recipes.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
        </div>

        <section className="kw-linked-meals"><h3>Linked Meals</h3><div>
          {linked.map(meal => <button type="button" key={meal.id} className="kw-linked-pill" onClick={() => navigate("calendar", meal.id)}>{dayName(meal.day)} {meal.slot} 📅</button>)}
          {!linked.length && <span className="kw-muted small">Not used by this week’s meals yet.</span>}
          {existing && linkable.length > 0 && <select className="kw-link-meal" aria-label="Link to meal" value="" disabled={busy} onChange={e => { if (e.target.value) void link(e.target.value); }}><option value="">+ Link to meal</option>{linkable.map(meal => <option key={meal.id} value={meal.id}>{dayName(meal.day)} {meal.slot}</option>)}</select>}
        </div></section>

        <label className="kw-field">Notes<textarea className="kw-input" rows={2} placeholder="e.g. 周日 batch cook 做的" value={draft.notes || ""} onChange={e => change({ notes: e.target.value || undefined })} /></label>
      </div>

      <footer className="kw-modal-foot">
        {existing ? (confirming
          ? <><button type="button" className="kw-button kw-danger" disabled={busy} onClick={async () => { setBusy(true); try { if (await send("inventory.delete", { id: draft.id })) onClose(); } finally { setBusy(false); } }}>Confirm remove 🗑️</button><button type="button" className="kw-button secondary" onClick={() => setConfirming(false)}>Keep food</button></>
          : <button type="button" className="kw-button kw-danger" onClick={() => setConfirming(true)}>Delete 删除 🗑️</button>)
          : <span />}
        <button className="kw-button kw-yellow" aria-label="Save food" disabled={busy || !draft.name.trim()}>Save 保存 💾</button>
      </footer>
    </form>
  </div>;
}
