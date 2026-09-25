"use client";
import { useState } from "react";
import { RecipeArt } from "./food-art";
import { REHEAT_LABELS, ratingSummary, timesCooked } from "./data";
import { RecipeEditor, RecipeSource } from "./recipe-editor";
import type { KitchenState, Recipe } from "./types";
import "./recipe-pages.css";

type Send = (type: string, payload: Record<string, unknown>) => Promise<boolean>;

const MACROS = [
  ["proteinG", "蛋白质 Protein", "#c74732"],
  ["carbsG", "碳水 Carbs", "#f4af14"],
  ["fatG", "脂肪 Fat", "#64734b"],
  ["fiberG", "纤维 Fiber", "#8d7d70"],
] as const;

/** A small picture for an ingredient group, read from its (Chinese or English) name. */
function groupIcon(group: string) {
  const g = group.toLocaleLowerCase();
  if (/肉|鱼|虾|蛋|meat|protein|fish|egg/.test(g)) return "🥩";
  if (/辅|香|葱|姜|蒜|aromatic|herb/.test(g)) return "🌿";
  if (/糖|甜|sweet|sugar/.test(g)) return "🍬";
  if (/调|味|酱|season|sauce|spice/.test(g)) return "🧂";
  if (/菜|蔬|veg/.test(g)) return "🥬";
  if (/粉|米|面|grain|carb|flour|rice|noodle/.test(g)) return "🌾";
  return "🍽️";
}

/** Other recipes that share tags, type or meal with this one, most alike first. */
function related(recipes: Recipe[], recipe: Recipe) {
  return recipes
    .filter(other => other.id !== recipe.id)
    .map(other => ({
      other,
      score: other.tags.filter(tag => recipe.tags.includes(tag)).length * 2
        + (other.type === recipe.type ? 1 : 0)
        + other.mealTypes.filter(slot => recipe.mealTypes.includes(slot)).length * 0.5,
    }))
    .filter(entry => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 4)
    .map(entry => entry.other);
}

function Hero({ recipe }: { recipe: Recipe }) {
  if (recipe.heroImageUrl) {
    // The URL is user-pasted from an arbitrary host, so next/image would need
    // every host allowlisted in remotePatterns.
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="kw-rd-hero-image" src={recipe.heroImageUrl} alt="" />;
  }
  return <div className="kw-rd-hero-art"><RecipeArt name={recipe.name} type={recipe.type} sizes="100vw" /></div>;
}

function Nutrition({ recipe }: { recipe: Recipe }) {
  const nutrition = recipe.nutrition;
  const known = MACROS.filter(([key]) => nutrition?.[key] !== undefined);
  const total = known.reduce((sum, [key]) => sum + (nutrition?.[key] ?? 0), 0);
  const radius = 38, circumference = 2 * Math.PI * radius;
  let offset = 0;
  return <section className="kw-rd-card kw-rd-nutrition" aria-label="Nutrition info">
    <h2>营养信息 Nutrition Info <span aria-hidden="true">📊</span></h2>
    {!nutrition || (!known.length && nutrition.calories === undefined)
      ? <p className="kw-rd-empty">No nutrition recorded for this recipe.</p>
      : <div className="kw-rd-nutrition-body">
        <svg className="kw-rd-donut" viewBox="0 0 100 100" role="img" aria-label={nutrition.calories !== undefined ? `${nutrition.calories} kcal` : "Macros"}>
          <circle cx="50" cy="50" r={radius} fill="none" stroke="#eee4d6" strokeWidth="14" />
          {total > 0 && known.map(([key, , color]) => {
            const share = (nutrition[key] ?? 0) / total * circumference;
            const segment = <circle key={key} cx="50" cy="50" r={radius} fill="none" stroke={color} strokeWidth="14" strokeDasharray={`${share} ${circumference - share}`} strokeDashoffset={-offset} transform="rotate(-90 50 50)" />;
            offset += share;
            return segment;
          })}
          <text x="50" y="50" textAnchor="middle" className="kw-rd-kcal">{nutrition.calories ?? "–"}</text>
          <text x="50" y="63" textAnchor="middle" className="kw-rd-kcal-unit">kcal</text>
        </svg>
        <dl>{MACROS.map(([key, label, color]) => <div key={key}><dt><i style={{ background: color }} aria-hidden="true" />{label}</dt><dd>{nutrition[key] !== undefined ? `${nutrition[key]}g` : "–"}</dd></div>)}</dl>
      </div>}
  </section>;
}

function Ingredients({ recipe }: { recipe: Recipe }) {
  // Ticking off what is already on the counter is a cooking aid, not data.
  const [have, setHave] = useState<number[]>([]);
  const groups = [...new Set(recipe.ingredients.map(i => i.group || "Ingredients"))];
  return <section className="kw-rd-card" aria-label="Ingredients">
    <h2>配方食材 Ingredients <span aria-hidden="true">🛒</span> <small>for {recipe.servings} servings</small></h2>
    {groups.map(group => <div className="kw-rd-group" key={group}>
      {groups.length > 1 && <h3><span aria-hidden="true">{groupIcon(group)}</span>{group}</h3>}
      {recipe.ingredients.map((ingredient, index) => (ingredient.group || "Ingredients") !== group ? null : <label key={index} className={`kw-rd-ingredient ${have.includes(index) ? "is-had" : ""}`}>
        <input type="checkbox" checked={have.includes(index)} onChange={e => setHave(current => e.target.checked ? [...current, index] : current.filter(i => i !== index))} />
        <span>{ingredient.name}</span><strong>{ingredient.quantity} {ingredient.unit}</strong>
      </label>)}
    </div>)}
  </section>;
}

function Steps({ recipe }: { recipe: Recipe }) {
  return <section className="kw-rd-card" aria-label="Cooking steps">
    <h2>烹饪步骤 Cooking Steps <span aria-hidden="true">🍳</span></h2>
    <ol className="kw-rd-steps">{recipe.steps.map((step, index) => {
      const detail = recipe.stepDetails?.find(d => d.index === index);
      const minutes = detail?.activeMinutes ?? detail?.waitMinutes;
      return <li key={index}>
        <span className="kw-rd-step-number" aria-hidden="true">{index + 1}</span>
        <div>{detail?.title && <strong>{detail.title}{detail.titleEn && ` ${detail.titleEn}`}</strong>}<p>{step}</p></div>
        {minutes !== undefined && <span className="kw-rd-time">⏱ {minutes} min</span>}
      </li>;
    })}</ol>
  </section>;
}

/** Frame 36:1030: a recipe on its own page. The photo leads with the title
 * card (tags, favourite, rating, times cooked, edit and delete); nutrition and
 * ingredients sit beside the steps and reheating; related recipes close it.
 * Editing happens here, on the recipe's page, not above the list. */
export function RecipeDetail({ recipe, state, send, onBack, onOpen, onDeleted }: {
  recipe: Recipe; state: KitchenState; send: Send;
  onBack: () => void; onOpen: (id: string) => void; onDeleted: () => void;
}) {
  const [editing, setEditing] = useState(false), [deleting, setDeleting] = useState(false), [busy, setBusy] = useState(false);
  const rating = ratingSummary(state, recipe.id), cooked = timesCooked(state, recipe.id);
  const stars = Math.round(rating?.average ?? 0);
  const others = related(state.recipes, recipe);
  const labels = [...(recipe.cuisine ? [recipe.cuisine] : []), ...recipe.tags];

  if (editing) return <div className="kw-rd kw-rd-editing">
    <button type="button" className="kw-rd-back" onClick={() => setEditing(false)}>← {recipe.name}</button>
    <RecipeEditor initial={recipe} tags={state.tags} cancel={() => setEditing(false)} save={next => send("recipe.save", { recipe: { ...next, allergens: next.allergens?.map(s => s.trim()).filter(Boolean), equipment: next.equipment?.map(s => s.trim()).filter(Boolean) } })} />
  </div>;

  return <article className="kw-rd" aria-label={`Recipe ${recipe.name}`}>
    <header className="kw-rd-hero">
      <Hero recipe={recipe} />
      <button type="button" className="kw-rd-back on-hero" onClick={onBack}>← Recipe Book</button>
      <div className="kw-rd-title-card">
        <div className="kw-rd-title-top">
          <div className="kw-rd-labels">{labels.map((label, index) => <span key={label} className={`kw-rd-label tone-${index % 3}`}>{label}</span>)}</div>
          <button type="button" className={`kw-rd-favorite ${recipe.liked ? "is-on" : ""}`} aria-pressed={recipe.liked} onClick={() => void send("recipe.save", { recipe: { ...recipe, liked: !recipe.liked } })}>{recipe.liked ? "♥" : "♡"} Baby liked it</button>
        </div>
        <h1>{recipe.name}{recipe.nameEn && <small> {recipe.nameEn}</small>}</h1>
        <div className="kw-rd-stats">
          <span className="kw-rd-stars" role="group" aria-label="Rate this recipe">{[1, 2, 3, 4, 5].map(n => <button key={n} type="button" aria-label={`Rate ${n} stars`} className={n <= stars ? "is-on" : ""} onClick={() => void send("recipe.rate", { recipeId: recipe.id, stars: n })}>★</button>)}</span>
          {rating ? <span className="kw-rd-rating">{rating.average} ({rating.count} 评分)</span> : <span className="kw-rd-rating muted">Not rated yet</span>}
          {cooked > 0 && <span>已做过 {cooked} 次</span>}
        </div>
        <p className="kw-rd-meta">{recipe.servings} servings · Active {recipe.activeMinutes} min · Total {recipe.elapsedMinutes} min{recipe.difficulty && ` · ⭐ ${recipe.difficulty}`}</p>
        {recipe.incomplete && <p className="kw-rd-review" role="status">Needs review: complete the amounts and steps.</p>}
        <div className="kw-rd-actions">
          <button type="button" className="kw-rd-edit" onClick={() => setEditing(true)}>✎ 编辑 Edit</button>
          {deleting
            ? <><button type="button" className="kw-rd-delete is-confirm" disabled={busy} onClick={async () => { setBusy(true); try { if (await send("recipe.delete", { id: recipe.id })) onDeleted(); } finally { setBusy(false); } }}>Delete for good</button><button type="button" className="kw-rd-edit" onClick={() => setDeleting(false)}>Cancel</button></>
            : <button type="button" className="kw-rd-delete" onClick={() => setDeleting(true)}>🗑 删除 Delete</button>}
        </div>
      </div>
    </header>

    <div className="kw-rd-body">
      <div className="kw-rd-column"><Nutrition recipe={recipe} /><Ingredients recipe={recipe} /></div>
      <div className="kw-rd-column">
        <Steps recipe={recipe} />
        {!!recipe.reheat?.length && <section className="kw-rd-card" aria-label="Reheating instructions">
          <h2>复热说明 Reheating Instructions <span aria-hidden="true">🔥</span></h2>
          <ul className="kw-rd-reheat">{recipe.reheat.map(r => <li key={r.method}><strong>{REHEAT_LABELS[r.method] ?? r.method}</strong><span>{r.instruction}</span></li>)}</ul>
        </section>}
        {(!!recipe.equipment?.length || !!recipe.allergens?.length) && <p className="kw-rd-note">{!!recipe.equipment?.length && <span><strong>Equipment:</strong> {recipe.equipment.join(", ")}</span>}{!!recipe.allergens?.length && <span><strong>Allergens:</strong> {recipe.allergens.join(", ")}</span>}</p>}
        <RecipeSource source={recipe.source} />
      </div>
    </div>

    {others.length > 0 && <section className="kw-rd-related" aria-label="Related recipes">
      <h2>相关菜谱 Related Recipes <span aria-hidden="true">📖</span></h2>
      <div className="kw-rd-related-grid">{others.map(other => <button type="button" key={other.id} className="kw-rd-related-card" aria-label={`Open recipe ${other.name}`} onClick={() => onOpen(other.id)}>
        <span className="kw-rd-related-art"><RecipeArt name={other.name} type={other.type} sizes="(max-width: 760px) 50vw, 25vw" /></span>
        <strong>{other.name}{other.nameEn && ` ${other.nameEn}`}</strong>
        <span className="kw-rd-related-meta"><span>⏱ {other.elapsedMinutes} min</span>{other.nutrition?.calories !== undefined && <span className="kcal">🔥 {other.nutrition.calories} kcal</span>}</span>
      </button>)}</div>
    </section>}
  </article>;
}

/** A new recipe gets the same page layout: the form first, its page after saving. */
export function NewRecipe({ tags, initial, send, onSaved, onCancel }: { tags: string[]; initial: Recipe; send: Send; onSaved: (id: string) => void; onCancel: () => void }) {
  return <div className="kw-rd kw-rd-editing">
    <button type="button" className="kw-rd-back" onClick={onCancel}>← Recipe Book</button>
    <RecipeEditor title="New recipe" initial={initial} tags={tags} cancel={onCancel} save={async next => {
      const saved = await send("recipe.save", { recipe: { ...next, allergens: next.allergens?.map(s => s.trim()).filter(Boolean), equipment: next.equipment?.map(s => s.trim()).filter(Boolean) } });
      if (saved) onSaved(next.id);
      return false; // the page moves to the saved recipe instead of closing the form
    }} />
  </div>;
}
