"use client";
import { useState } from "react";
import { RecipeArt, foodEmoji } from "./food-art";
import type { Ingredient, Recipe } from "./types";

/** Import, frames 46:8 (upload) and 127:4 (recognition results).
 *
 * The upload dialog only advertises the formats the extractor can actually
 * read: text files are read here and sent as text, one image is sent as image
 * data. A chip for a format that would fail is worse than a missing chip.
 */
const TEXT_TYPES = [".txt", ".md", ".json", ".csv"];
const IMAGE_TYPES = [".jpg", ".png"];
const ACCEPT = ".txt,.md,.json,.csv,text/plain,text/markdown,application/json,text/csv,image/jpeg,image/png,image/webp";

export function ImportDialog({ demo, busy, error, text, onText, onFiles, onExtract, onClose }: {
  demo: boolean; busy: boolean; error: string; text: string;
  onText: (value: string) => void;
  onFiles: (files: File[]) => Promise<void>;
  onExtract: () => void;
  onClose: () => void;
}) {
  const [over, setOver] = useState(false);
  const [pasting, setPasting] = useState(false);
  return <div className="kw-modal-backdrop" role="presentation" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="kw-modal kw-import-modal" role="dialog" aria-modal="true" aria-label="Import recipes">
      <header className="kw-modal-head">
        <div><h2>批量导入菜谱 Import Recipes 📎</h2><p>{demo ? "Demo import shows a simulated sample. Your files are not read by AI." : "上传文件，AI自动识别并转换为菜谱 · Upload files, AI will auto-recognize and convert them"}</p></div>
        <button type="button" className="kw-modal-close" aria-label="Close import" onClick={onClose}>✕</button>
      </header>
      <div className="kw-modal-body">
        <label className={`kw-dropzone ${over ? "over" : ""}`}
          onDragOver={e => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={e => { e.preventDefault(); setOver(false); void onFiles([...e.dataTransfer.files]); }}>
          <span className="kw-dropzone-icon" aria-hidden="true">📄</span>
          <strong>拖拽文件到此处 或 点击上传</strong>
          <span className="kw-dropzone-hint">Drag files here or click to upload</span>
          <span className="kw-dropzone-formats" aria-hidden="true">{[...TEXT_TYPES, ...IMAGE_TYPES].map(type => <em key={type}>{type}</em>)}</span>
          <input className="sr-only" type="file" multiple accept={ACCEPT} aria-label="Browse files" onChange={e => { void onFiles([...(e.target.files ?? [])]); e.target.value = ""; }} />
          <span className="kw-browse">浏览本地文件 Browse Files</span>
        </label>
        <details className="kw-paste" open={pasting} onToggle={e => setPasting((e.currentTarget as HTMLDetailsElement).open)}>
          <summary>or paste the recipe text</summary>
          <label className="kw-label">Recipe text<textarea className="kw-input" rows={5} maxLength={30000} placeholder="Paste ingredients and instructions…" value={text} onChange={e => onText(e.target.value)} /></label>
          <button className="kw-button kw-yellow" disabled={busy || !text.trim()} onClick={onExtract}>{busy ? "Extracting…" : "Extract preview"}</button>
        </details>
        {busy && <p className="kw-muted" role="status">Reading your files…</p>}
        {error && <p className="kw-error" role="alert">{error}</p>}
      </div>
    </section>
  </div>;
}

function group(recipe: Recipe) {
  const groups = new Map<string, Ingredient[]>();
  recipe.ingredients.forEach(item => {
    const key = item.group?.trim() || "";
    groups.set(key, [...(groups.get(key) ?? []), item]);
  });
  return [...groups.entries()];
}

export function ImportReview({ recipes, confirmed, busy, onSelectSave, onDelete, onReanalyze, onBack, onSaveAll, onChange }: {
  recipes: Recipe[]; confirmed: string[]; busy: boolean;
  onSelectSave: (recipe: Recipe) => Promise<void>;
  onDelete: (id: string) => void;
  onReanalyze: () => void;
  onBack: () => void;
  onSaveAll: () => Promise<void>;
  onChange: (recipe: Recipe) => void;
}) {
  const [selectedId, setSelectedId] = useState(recipes[0]?.id ?? "");
  const [dropped, setDropped] = useState<string[]>([]);
  const [cover, setCover] = useState(false);
  const current = recipes.find(r => r.id === selectedId) ?? recipes[0];
  if (!current) return null;
  const edit = (fields: Partial<Recipe>) => onChange({ ...current, ...fields });

  return <section className="kw-import-review" aria-label="Recognition results">
    <header className="kw-review-head">
      <div><h1>识别结果 Recognition Results ✨</h1><p className="kw-muted">共识别出 {recipes.length} 道菜谱，请逐一确认以存入您的家庭智能菜谱库</p></div>
      <span className="kw-review-count">🔥 {confirmed.length} / {recipes.length} 已确认 Confirmed</span>
    </header>
    <h2 className="kw-review-label">待审核菜谱 List 📋</h2>

    <div className="kw-review-layout">
      <div className="kw-review-list">
        {recipes.map((recipe, index) => {
          const done = confirmed.includes(recipe.id);
          return <button key={recipe.id} type="button" className={`kw-review-item ${recipe.id === current.id ? "on" : ""}`} aria-pressed={recipe.id === current.id} onClick={() => setSelectedId(recipe.id)}>
            <span className="kw-review-item-head"><small>#{String(index + 1).padStart(2, "0")}</small><span className={`kw-review-status ${done ? "done" : ""}`}>{done ? "已确认 Confirmed" : "待确认 Pending"}</span></span>
            <strong>{recipe.name || "Untitled"}</strong>
            {recipe.nameEn && <span className="kw-review-en">{recipe.nameEn}</span>}
            <span className="kw-review-tags">{recipe.tags.slice(0, 3).map(tag => <em key={tag}>{tag}</em>)}</span>
          </button>;
        })}
      </div>

      <div className="kw-review-detail">
        <section className="kw-card kw-review-hero">
          <div className="kw-review-cuisine">{current.cuisine && <span className="kw-chip red">{current.cuisine}</span>}<span className="kw-chip blue">{current.type}</span></div>
          <div className="kw-review-hero-body">
            <div className="kw-review-cover">
              <RecipeArt name={current.name} type={current.type} />
              <button type="button" className="kw-change-cover" aria-expanded={cover} onClick={() => setCover(v => !v)}>更换封面 Change Cover</button>
              {cover && <input className="kw-cover-input" aria-label="Cover image URL" placeholder="https://…" value={current.heroImageUrl ?? ""} onChange={e => edit({ heroImageUrl: e.target.value || undefined })} />}
            </div>
            <div className="kw-review-facts">
              <h2><input aria-label="Recipe name" className="kw-review-name" value={current.name} onChange={e => edit({ name: e.target.value })} /></h2>
              <input aria-label="English name" className="kw-review-name-en" placeholder="English name" value={current.nameEn ?? ""} onChange={e => edit({ nameEn: e.target.value || undefined })} />
              <p className="kw-review-meta">⏱ 烹饪时间 Time: <input aria-label="Elapsed minutes" type="number" min="0" value={current.elapsedMinutes} onChange={e => edit({ elapsedMinutes: e.target.valueAsNumber || 0 })} /> min · 🔍 难度 Difficulty:
                <select aria-label="Difficulty" value={current.difficulty ?? "medium"} onChange={e => edit({ difficulty: e.target.value as Recipe["difficulty"] })}><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select></p>
              <div className="kw-review-tags">{current.tags.map(tag => <em key={tag}>{tag}</em>)}</div>
            </div>
          </div>
        </section>

        <div className="kw-review-columns">
          <section className="kw-card">
            <h3>配方食材 Ingredients 🧂</h3>
            {group(current).map(([label, items]) => <div className="kw-review-group" key={label || "other"}>
              {label && <span className="kw-review-group-label">{foodEmoji(label, current.type)} {label}</span>}
              {items.map(item => { const key = `${current.id}:${item.name}`; const on = !dropped.includes(key);
                return <label className={`kw-review-ingredient ${on ? "" : "off"}`} key={key}>
                  <input type="checkbox" checked={on} aria-label={`Keep ${item.name}`} onChange={e => setDropped(list => e.target.checked ? list.filter(x => x !== key) : [...list, key])} />
                  <span>{item.name}</span><em>{item.quantity ? `${item.quantity}${item.unit}` : item.unit || "适量"}</em>
                </label>; })}
            </div>)}
            <button type="button" className="kw-review-add" onClick={() => edit({ ingredients: [...current.ingredients, { name: "", quantity: 0, unit: "" }] })}>+ 添加食材 Add Ingredient</button>
          </section>

          <section className="kw-card">
            <h3>烹饪步骤 Cooking Steps 🔍</h3>
            <ol className="kw-review-steps">{current.steps.map((step, index) => { const detail = current.stepDetails?.find(d => d.index === index);
              return <li key={index}><span className="kw-step-number" aria-hidden="true">{index + 1}</span>
                <span className="kw-review-step-body">{detail?.title && <strong>{detail.title}</strong>}
                  <textarea aria-label={`Step ${index + 1}`} rows={2} value={step} onChange={e => edit({ steps: current.steps.map((s, i) => i === index ? e.target.value : s) })} /></span>
                {detail?.activeMinutes ? <em className="kw-review-step-time">⏱ {detail.activeMinutes} min</em> : null}</li>; })}</ol>
            <button type="button" className="kw-review-add" onClick={() => edit({ steps: [...current.steps, ""] })}>+ 添加步骤 Add Step</button>
          </section>
        </div>
      </div>
    </div>

    <footer className="kw-review-foot">
      <div><button className="kw-button secondary" onClick={onBack}>返回 Back</button><button className="kw-button kw-yellow" disabled={busy} onClick={() => void onSaveAll()}>全部确认 Confirm all</button></div>
      <div><button className="kw-button secondary" disabled={busy} onClick={onReanalyze}>🔄 重新识别 Re-analyze</button>
        <button className="kw-button kw-danger" onClick={() => onDelete(current.id)}>🗑️ 删除 Delete</button>
        <button className="kw-button kw-yellow" disabled={busy || !current.name.trim()} onClick={() => void onSelectSave({ ...current, ingredients: current.ingredients.filter(item => !dropped.includes(`${current.id}:${item.name}`)) })}>保存菜谱 Save</button></div>
    </footer>
  </section>;
}
