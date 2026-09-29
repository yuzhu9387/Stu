"use client";
import { Plus, X } from "@phosphor-icons/react";
import { useState } from "react";
import { uid } from "./data";
import { Drawer } from "./drawer";
import { foodEmoji } from "./food-art";
import type { FoodType, KitchenState, PageProps, ShoppingItem } from "./types";
import "./shopping-note.css";

// Words that count things ("2盒", "12个"); a weight ("2斤") stays in the name.
const COUNT = "(?:个|盒|瓶|袋|包|只|根|颗|把|罐|听|条|块|支|份|打|pcs?)";
const NUMBER = "(\\d+(?:\\.\\d+)?)";
// After the name: "*2", "×2" anywhere; "x2" after a space or a Chinese character;
// "2" after a space or right after a Chinese character ("牛奶2").
const TRAILING = new RegExp(`^(.+?)(?:\\s*[*×]\\s*|(?<=\\s|[^\\x00-\\x7F])[xX]\\s*|\\s+|(?<=[^\\x00-\\x7F]))${NUMBER}\\s*${COUNT}?$`, "i");
// Before the name: "2盒牛奶", "2 牛奶".
const LEADING = new RegExp(`^${NUMBER}\\s*(?:${COUNT}\\s*|\\s+)(.+)$`, "i");

/** A row as typed. However the amount is written ("牛奶 2", "牛奶2",
 * "鸡蛋*12", "鸡蛋×12", "2盒牛奶") it goes in the amount box; a number that is
 * part of the name ("维生素D3", "7up") or a weight ("猪肉2斤") stays in it. */
export function parseRow(text: string): { name: string; quantity?: number } | null {
  const value = text.trim();
  if (!value) return null;
  const trailing = TRAILING.exec(value);
  if (trailing && trailing[1].trim()) return { name: trailing[1].trim(), quantity: Number(trailing[2]) };
  const leading = LEADING.exec(value);
  if (leading && leading[2].trim()) return { name: leading[2].trim(), quantity: Number(leading[1]) };
  return { name: value };
}

/** A fridge food's groups (a dish has no Dairy of its own; a food can). */
const GROUPS: FoodType[] = ["Protein", "Carbs", "Vegetables", "Dairy", "Other"];
const plural = (n: number) => `${n} item${n === 1 ? "" : "s"}`;
const amount = (row: ShoppingItem) => row.quantity ? ` ${row.quantity}` : "";

/** The note stuck on the fridge door: its first few rows and how many there
 * are. On a phone it is just "🛒 5". */
export function ShoppingNote({ rows, onOpen }: { rows: ShoppingItem[]; onOpen: () => void }) {
  return <button type="button" className="kw-shopping-note" aria-label={`Shopping note, ${plural(rows.length)}`} onClick={onOpen}>
    <span className="kw-note-paper" aria-hidden="true">
      <span className="kw-note-head">🛒 Shopping <b>{rows.length}</b></span>
      <span className="kw-note-rows">{rows.length ? rows.slice(0, 3).map(row => <span key={row.id} className={row.checked ? "is-checked" : ""}>{row.name}{amount(row)}</span>) : <span>Nothing yet</span>}{rows.length > 3 && <em>+{rows.length - 3}</em>}</span>
    </span>
    <span className="kw-note-count" aria-hidden="true">🛒 {rows.length}</span>
  </button>;
}

/** One row, edited where it is: tick it when bought, rename it, change the
 * amount (saved when the field is left), or take it off. */
function Row({ row, busy, save, remove }: { row: ShoppingItem; busy: boolean; save: (row: ShoppingItem) => void; remove: () => void }) {
  const [name, setName] = useState(row.name), [quantity, setQuantity] = useState(row.quantity === undefined ? "" : String(row.quantity));
  // An amount typed into the name moves to the amount box.
  const commitName = () => {
    const parsed = parseRow(name);
    if (!parsed) { setName(row.name); return; }
    const next = { ...row, name: parsed.name, ...(parsed.quantity !== undefined ? { quantity: parsed.quantity } : {}) };
    if (next.name !== row.name || next.quantity !== row.quantity) save(next);
    else setName(row.name);
  };
  const commitQuantity = () => {
    const next = quantity.trim() === "" ? undefined : Number(quantity);
    if (next !== undefined && (!Number.isFinite(next) || next <= 0)) { setQuantity(row.quantity === undefined ? "" : String(row.quantity)); return; }
    if (next !== row.quantity) save(next === undefined ? { id: row.id, name: row.name, checked: row.checked } : { ...row, quantity: next });
  };
  return <li className={`kw-note-row ${row.checked ? "is-checked" : ""}`}>
    <input type="checkbox" aria-label={`Bought ${row.name}`} checked={row.checked} disabled={busy} onChange={e => save({ ...row, checked: e.target.checked })} />
    <input className="kw-input kw-note-name" aria-label={`Name of ${row.name}`} value={name} maxLength={200} onChange={e => setName(e.target.value)} onBlur={commitName} onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }} />
    <input className="kw-input kw-note-amount" aria-label={`Amount of ${row.name}`} type="number" min="0" step="any" placeholder="—" value={quantity} onChange={e => setQuantity(e.target.value)} onBlur={commitQuantity} onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }} />
    <button type="button" className="kw-icon" aria-label={`Remove ${row.name}`} disabled={busy} onClick={remove}><X size={14} /></button>
  </li>;
}

type Away = { location: "fridge" | "freezer"; portions: string; type: FoodType };

/** The note, opened: a plain list to add to, tick and tidy; what was bought
 * goes into the fridge in one go, each with where it goes and how many
 * portions (one, unless the row has a number), and leaves the list. */
export function ShoppingDrawer({ state, send, onClose }: { state: KitchenState; send: PageProps["send"]; onClose: () => void }) {
  const rows = state.shoppingList ?? [];
  const [text, setText] = useState(""), [busy, setBusy] = useState(false);
  const [away, setAway] = useState<Record<string, Away> | null>(null);
  const bought = rows.filter(row => row.checked);
  const known = (row: ShoppingItem) => state.inventory.find(item => item.name.toLocaleLowerCase() === row.name.toLocaleLowerCase());
  const run = async (type: string, payload: Record<string, unknown>) => { setBusy(true); try { return await send(type, payload, { quiet: true }); } finally { setBusy(false); } };
  const save = (row: ShoppingItem) => void run("shopping.save", { item: row });

  async function add() {
    const parsed = parseRow(text);
    if (!parsed || busy) return;
    if (await run("shopping.save", { item: { id: uid(), ...parsed, checked: false } })) setText("");
  }
  const startAway = () => setAway(Object.fromEntries(bought.map(row => [row.id, { location: "fridge", portions: String(row.quantity || 1), type: known(row)?.type ?? "Other" }])));
  const set = (id: string, patch: Partial<Away>) => setAway(current => current && { ...current, [id]: { ...current[id], ...patch } });
  const ready = !!away && bought.length > 0 && bought.every(row => { const n = Number(away[row.id]?.portions); return Number.isFinite(n) && n > 0; });
  async function putAway() {
    if (!away || !ready) return;
    const items = bought.map(row => ({ id: row.id, location: away[row.id].location, portions: Number(away[row.id].portions), type: away[row.id].type }));
    if (await run("shopping.putAway", { items })) setAway(null);
  }

  const footer = away
    ? <><button type="button" className="kw-button" disabled={!ready || busy} onClick={() => void putAway()}>{`Put ${bought.length} in the fridge`}</button><button type="button" className="kw-button secondary" onClick={() => setAway(null)}>Back</button></>
    : <button type="button" className="kw-button" disabled={!bought.length || busy} onClick={startAway}>{`Put in fridge · ${bought.length}`}</button>;

  return <Drawer title="🛒 Shopping note" subtitle={plural(rows.length)} onClose={onClose} footer={footer}>
    {away ? <ul className="kw-note-away">{bought.map(row => {
      const stock = known(row), choice = away[row.id];
      if (!choice) return null;
      return <li key={row.id}>
        <div className="kw-note-away-head"><span aria-hidden="true">{stock?.emoji ?? foodEmoji(row.name, choice.type)}</span><strong>{row.name}</strong>
          {stock ? <small>{stock.type} · like the one in your fridge</small>
            : <label className="kw-note-group">Food group<select className="kw-input" aria-label={`Food group of ${row.name}`} value={choice.type} onChange={e => set(row.id, { type: e.target.value as FoodType })}>{GROUPS.map(type => <option key={type}>{type}</option>)}</select></label>}</div>
        <div className="kw-note-away-fields">
          <label className="kw-label">Portions<input className="kw-input" type="number" min="0.25" step="0.25" aria-label={`Portions of ${row.name}`} value={choice.portions} onChange={e => set(row.id, { portions: e.target.value })} /></label>
          <div className="kw-prep-place" role="group" aria-label={`Where ${row.name} goes`}><button type="button" aria-pressed={choice.location === "fridge"} onClick={() => set(row.id, { location: "fridge" })}>🧊 Fridge</button><button type="button" aria-pressed={choice.location === "freezer"} onClick={() => set(row.id, { location: "freezer" })}>❄️ Freezer</button></div>
        </div>
      </li>;
    })}</ul> : <>
      <form className="kw-note-add" onSubmit={e => { e.preventDefault(); void add(); }}>
        <input className="kw-input" aria-label="Add to the list" placeholder="e.g. 牛奶 2" maxLength={200} value={text} onChange={e => setText(e.target.value)} />
        <button type="submit" className="kw-button" disabled={!text.trim() || busy}><Plus size={15} />Add</button>
      </form>
      {rows.length ? <ul className="kw-note-list">{rows.map(row => <Row key={`${row.id}:${row.name}:${row.quantity ?? ""}`} row={row} busy={busy} save={save} remove={() => void run("shopping.delete", { id: row.id })} />)}</ul>
        : <p className="kw-empty">Nothing on the list. Add what you need; tick it when it is bought.</p>}
      {rows.length > 0 && <p className="kw-muted small">Tick what you bought, then put it in the fridge.</p>}
    </>}
  </Drawer>;
}
