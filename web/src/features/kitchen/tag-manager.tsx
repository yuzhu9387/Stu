"use client";
import { PushPin } from "@phosphor-icons/react";
import { useState } from "react";
import { hasTag, type LibraryTag } from "./tag-pins";
import type { PageProps, Recipe } from "./types";

/** The recipe library's tags, managed in a popup over the Recipes page.
 *
 * Tags are the library's own vocabulary, so they are managed where they are
 * used rather than in Settings (which holds the household's planning rules).
 * Each tag leads; pinning, renaming and deleting are quiet options beside it.
 * A pinned tag leads the Recipe Book filters as a large chip, and leads this
 * list too. The meals are tags as well: they can be pinned, not renamed or
 * deleted. Merging two tags is rarer, so it sits folded away at the bottom.
 */
export function TagManager({ tags, recipes, send, onClose, onChanged }: {
  tags: LibraryTag[]; recipes: Recipe[]; send: PageProps["send"]; onClose: () => void;
  /** A tag was renamed (to the new name) or deleted (null), so a filter on it can follow. */
  onChanged: (from: string, to: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<{ tag: string; value: string } | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [merge, setMerge] = useState({ from: "", into: "" });
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const count = (tag: LibraryTag) => recipes.filter(r => hasTag(r, tag)).length;
  const named = tags.filter(tag => !tag.meal).map(tag => tag.key);
  async function run(type: string, payload: Record<string, unknown>, after: () => void, quiet = false) {
    setBusy(true); setError(null);
    try { if (await send(type, payload, { quiet })) after(); else setError("Unable to save the tag. Please try again."); }
    finally { setBusy(false); }
  }
  return <div className="kw-modal-backdrop" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="kw-modal kw-tag-modal" role="dialog" aria-modal="true" aria-label="Recipe tags">
      <header className="kw-modal-head"><h2>Tags 🏷️</h2><button type="button" className="kw-modal-close" aria-label="Close tags" onClick={onClose}>✕</button></header>
      <div className="kw-modal-body">
        <form className="kw-tag-add" onSubmit={e => { e.preventDefault(); const value = name.trim(); if (value) void run("tag.save", { name: value }, () => setName("")); }}>
          <input className="kw-input" aria-label="New tag" placeholder="New tag, e.g. 快手菜" value={name} onChange={e => setName(e.target.value)} />
          <button className="kw-tag-add-button" disabled={busy || !name.trim()}>+ Add</button>
        </form>
        {error && <p className="kw-inline-error" role="alert">{error}</p>}
        <ul className="kw-tag-list">{tags.map(entry => {
          const tag = entry.key, recipesWith = count(entry);
          const pin = <button type="button" className={`kw-tag-pin ${entry.pinned ? "is-on" : ""}`} aria-label={`${entry.pinned ? "Unpin" : "Pin"} tag ${tag}`} aria-pressed={entry.pinned} title={entry.pinned ? "Unpin" : "Pin to the front"} disabled={busy} onClick={() => void run("tag.pin", { name: tag, pinned: !entry.pinned }, () => {}, true)}><PushPin size={15} weight={entry.pinned ? "fill" : "bold"} aria-hidden="true" /></button>;
          return <li key={tag} className={`kw-tag-row ${entry.pinned ? "is-pinned" : ""} ${deleting === tag ? "is-deleting" : ""}`}>
            {renaming?.tag === tag
              ? <form className="kw-tag-rename" onSubmit={e => { e.preventDefault(); const value = renaming.value.trim(); if (!value || value === tag) { setRenaming(null); return; } void run("tag.save", { previous: tag, name: value }, () => { setRenaming(null); onChanged(tag, value); }); }}>
                <input className="kw-input" autoFocus aria-label={`New name for ${tag}`} value={renaming.value} onChange={e => setRenaming({ tag, value: e.target.value })} />
                <button className="kw-tag-save" disabled={busy || !renaming.value.trim()}>Save</button>
                <button type="button" className="kw-tag-option" onClick={() => setRenaming(null)}>Cancel</button>
              </form>
              : <>
                <span className="kw-tag-name">{entry.meal ? entry.label : tag}</span>
                <span className="kw-tag-count">{recipesWith} recipe{recipesWith === 1 ? "" : "s"}{entry.meal ? " · meal" : ""}</span>
                {entry.meal ? <span className="kw-tag-options">{pin}</span> : deleting === tag
                  ? <span className="kw-tag-options"><span className="kw-tag-confirm">{recipesWith ? `Remove it from ${recipesWith} recipe${recipesWith === 1 ? "" : "s"}?` : "Delete this tag?"}</span><button type="button" className="kw-tag-option danger" disabled={busy} onClick={() => void run("tag.delete", { name: tag }, () => { setDeleting(null); onChanged(tag, null); })}>Delete</button><button type="button" className="kw-tag-option" onClick={() => setDeleting(null)}>Cancel</button></span>
                  : <span className="kw-tag-options">{pin}<button type="button" className="kw-tag-option" aria-label={`Rename tag ${tag}`} onClick={() => { setDeleting(null); setRenaming({ tag, value: tag }); }}>✎ Rename</button><button type="button" className="kw-tag-option" aria-label={`Delete tag ${tag}`} onClick={() => { setRenaming(null); setDeleting(tag); }}>🗑 Delete</button></span>}
              </>}
          </li>;
        })}</ul>
        {named.length > 1 && <details className="kw-tag-merge"><summary>Merge two tags</summary>
          <form onSubmit={e => { e.preventDefault(); void run("tag.save", { previous: merge.from, name: merge.into }, () => { onChanged(merge.from, merge.into); setMerge({ from: "", into: "" }); }); }}>
            <label className="kw-label">Merge tag<select className="kw-input" value={merge.from} onChange={e => setMerge({ ...merge, from: e.target.value })}><option value="">Choose a tag</option>{named.map(tag => <option key={tag}>{tag}</option>)}</select></label>
            <label className="kw-label">Into tag<select className="kw-input" value={merge.into} onChange={e => setMerge({ ...merge, into: e.target.value })}><option value="">Choose destination</option>{named.filter(tag => tag !== merge.from).map(tag => <option key={tag}>{tag}</option>)}</select></label>
            <button className="kw-tag-save" disabled={busy || !merge.from || !merge.into || merge.from === merge.into}>Merge tags</button>
          </form>
        </details>}
      </div>
    </section>
  </div>;
}
