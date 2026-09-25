"use client";
import { Heart } from "@phosphor-icons/react";
import { RecipeArt } from "./food-art";
import { ImportDialog, ImportReview } from "./import-review";
import { NewRecipe, RecipeDetail } from "./recipe-detail-page";
import { blankRecipe } from "./recipe-editor";
import { TagManager } from "./tag-manager";
import { libraryTags } from "./tag-pins";
import { Fragment, memo, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { MealSlot, PageProps, Recipe } from "./types";
import "./recipe-pages.css";
export { RecipeEditor, RecipeSource } from "./recipe-editor";

type SortKey = "duration" | "active" | "name" | "saved";
/** Frame 7:949 shows a "Sort by: Duration" control. "Saved order" keeps the
 * order the workspace stores, which is the order recipes were added in. */
function sorter(key: SortKey) {
  if (key === "saved") return () => 0;
  if (key === "name") return (a: Recipe, b: Recipe) => a.name.localeCompare(b.name, "zh-Hans-CN");
  if (key === "active") return (a: Recipe, b: Recipe) => a.activeMinutes - b.activeMinutes;
  return (a: Recipe, b: Recipe) => a.elapsedMinutes - b.elapsedMinutes;
}


const RECIPE_BATCH_SIZE = 24;
const RecipeGrid = memo(function RecipeGrid({ recipes, onOpen, onLike }: {
  recipes: Recipe[]; onOpen: (id: string) => void; onLike: (recipe: Recipe) => void;
}) {
  const [visibleCount, setVisibleCount] = useState(RECIPE_BATCH_SIZE);
  return <>
    <div className="kw-support-grid kw-recipe-grid">{recipes.slice(0, visibleCount).map((r, index) => <article className={`kw-card kw-support-task kw-recipe-card accent-${index % 4}`} key={r.id} onClick={() => onOpen(r.id)}><button className="kw-recipe-art-button" aria-label={`Open recipe ${r.name}`} onClick={event => { event.stopPropagation(); onOpen(r.id); }}><RecipeArt name={r.name} type={r.type} sizes="(max-width: 760px) 50vw, (max-width: 1200px) 33vw, 25vw"/></button><button className="kw-recipe-heart" aria-label={`Baby liked ${r.name}`} aria-pressed={r.liked} onClick={event=>{event.stopPropagation();onLike(r);}}><Heart size={16} weight={r.liked?"fill":"regular"}/></button>{r.liked&&<span className="kw-recipe-baby">BABY 👶</span>}<div className="kw-recipe-content"><h3><button className="kw-recipe-title-button" onClick={event => { event.stopPropagation(); onOpen(r.id); }}>{r.name}{r.nameEn&&<small> {r.nameEn}</small>}</button></h3><p className="kw-muted">Total {r.elapsedMinutes}m ⏱ · Active {r.activeMinutes}m 👨‍🍳</p><div className="kw-support-tags">{r.tags.map(tag => <span className="kw-pill" key={tag}>{tag}</span>)}{r.incomplete && <span className="kw-pill">Needs review</span>}</div></div></article>)}</div>
    {recipes.length > visibleCount && <div className="kw-support-actions"><button className="kw-button secondary" onClick={()=>setVisibleCount(count=>count+RECIPE_BATCH_SIZE)}>Show more recipes ({recipes.length-visibleCount} remaining)</button></div>}
  </>;
});

/** The recipe library (frame 7:949), and each recipe on its own page (frame
 * 36:1030). `recipeId` is the open recipe ("new" for a new one); the workspace
 * keeps it in the address. Rendered on its own (tests), the page keeps it. */
export function RecipesPage({ state, send, demo, recipeId, onOpenRecipe }: PageProps & { recipeId?: string | null; onOpenRecipe?: (id: string | null) => void }) {
  const [localId, setLocalId] = useState<string | null>(null);
  const openId = onOpenRecipe ? recipeId ?? null : localId;
  const open = useCallback((id: string | null) => (onOpenRecipe ?? setLocalId)(id), [onOpenRecipe]);
  const [search, setSearch] = useState(""); const [mealFilter,setMealFilter]=useState<MealSlot|"">(""); const [tagFilter, setTagFilter] = useState("");
  const [sort, setSort] = useState<SortKey>("duration");
  const [tagsOpen, setTagsOpen] = useState(false);
  const [draft, setDraft] = useState<Recipe | null>(null);
  const [importing, setImporting] = useState(false); const [text, setText] = useState(""); const [imageData, setImageData] = useState(""); const [fileName, setFileName] = useState(""); const [preview, setPreview] = useState<Recipe[]>([]); const [confirmedIds, setConfirmedIds] = useState<string[]>([]); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  // A recipe page opens at its top, like any page.
  useEffect(() => { if (openId) window.scrollTo?.({ top: 0 }); }, [openId]);
  // Pinned tags (the meals among them) lead as large chips; the rest follow the divider.
  const tagChips = libraryTags(state.tags, state.settings);
  const pinnedChips = tagChips.filter(tag => tag.pinned), otherChips = tagChips.filter(tag => !tag.pinned);
  const filteredRecipes = useMemo(() => {
    const query=search.toLocaleLowerCase();
    return state.recipes.filter(r => (!query || [r.name,...r.tags,...r.ingredients.map(i=>i.name)].some(value=>value.toLocaleLowerCase().includes(query))) && (!tagFilter || r.tags.includes(tagFilter)) && (!mealFilter || r.mealTypes.includes(mealFilter) || r.tags.some(tag => tag.trim().toLocaleLowerCase() === mealFilter))).sort(sorter(sort));
  }, [state.recipes,search,tagFilter,mealFilter,sort]);
  const likeRecipe=useCallback((recipe:Recipe)=>{void send("recipe.save",{recipe:{...recipe,liked:!recipe.liked}});},[send]);
  /** Frame 46:8 accepts dropped files. Text files are read here and sent as
   * text; one image is sent as image data. Anything else is reported rather
   * than silently dropped, because a file that vanishes reads as a bug. */
  const readFiles = async (files: File[]) => {
    if (!files.length) return;
    setError("");
    const texts: string[] = [];
    let image = "";
    const rejected: string[] = [];
    for (const file of files) {
      if (/^image\//.test(file.type)) {
        if (image) continue;
        if (file.size > 1_300_000) { rejected.push(`${file.name} (over 1.3 MB)`); continue; }
        image = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(new Error("unreadable")); reader.readAsDataURL(file); }).catch(() => "");
        if (image) setFileName(file.name);
      } else if (/\.(txt|md|json|csv)$/i.test(file.name) || /^text\/|json/.test(file.type)) {
        texts.push(await file.text());
      } else rejected.push(`${file.name} (unsupported)`);
    }
    if (rejected.length) setError(`Skipped ${rejected.join(", ")}. Supported: .txt, .md, .json, .csv, JPEG and PNG.`);
    const joined = texts.join("\n\n").slice(0, 30000);
    if (!joined && !image) return;
    setText(joined);
    setImageData(image);
    await extractWith(joined, image);
  };
  const extract = async () => extractWith(text, imageData);
  const extractWith = async (value: string, image: string) => { setBusy(true); setError(""); try {
    if (demo) { setPreview([{ ...blankRecipe(), name: "Sample steamed vegetables", type: "Vegetables", activeMinutes: 5, elapsedMinutes: 12, ingredients: [{ name: "Broccoli", quantity: 300, unit: "g" }], steps: ["Wash and cut broccoli into small florets.", "Steam until tender; cool before serving."], source: `Simulated demo import${fileName ? ` from ${fileName}` : ""}. ${value}`, incomplete: true }]); setConfirmedIds([]); setImporting(false); }
    else { const result = await api<{ recipes: Recipe[] }>("/api/v1/kitchen/extract", { method: "POST", body: JSON.stringify({ ...(value.trim() ? { text: value } : {}), ...(image ? { imageData: image } : {}) }) }); setPreview(result.recipes); setConfirmedIds([]); setImporting(false); if (!result.recipes.length) setError("No recipes found. Add clearer text or another image."); }
  } catch (e) { setError(e instanceof Error ? e.message : "Extraction failed. Please try again."); } finally { setBusy(false); } };

  if (openId === "new") return <section className="kw-support-page kw-recipes-page"><NewRecipe key={draft?.id ?? "new"} tags={state.tags} initial={draft ?? blankRecipe()} send={send} onCancel={() => { setDraft(null); open(null); }} onSaved={id => { setDraft(null); open(id); }} /></section>;
  const opened = openId ? state.recipes.find(r => r.id === openId) : undefined;
  if (openId) return <section className="kw-support-page kw-recipes-page">{opened
    ? <RecipeDetail key={opened.id} recipe={opened} state={state} send={send} onBack={() => open(null)} onOpen={open} onDeleted={() => open(null)} />
    : <div className="kw-rd"><button type="button" className="kw-rd-back" onClick={() => open(null)}>← Recipe Book</button><h1>Recipe not found</h1><p className="kw-muted">It may have been deleted.</p></div>}</section>;

  const chip = (active: boolean, label: string, onClick: () => void, big: boolean) => <button key={label} type="button" className={`kw-filter-chip ${big ? "is-key" : ""} ${active ? "is-active" : ""}`} aria-pressed={active} onClick={onClick}>{label}</button>;
  return <section className="kw-support-page kw-recipes-page">{!preview.length && <header className="kw-page-header"><div><h1 aria-label="Recipes">Recipe Book 📖</h1></div><div className="kw-support-actions"><button className="kw-button secondary" onClick={() => setImporting(v => !v)} aria-label="Import recipe">📥 Import</button><button className="kw-button kw-yellow" aria-label="Add recipe" onClick={() => { setDraft(blankRecipe()); open("new"); }}>★ + New Recipe</button></div></header>}
    {importing && <ImportDialog demo={demo} busy={busy} error={error} text={text} onText={setText} onExtract={() => void extract()} onClose={() => setImporting(false)} onFiles={readFiles} />}
    {preview.length > 0 && <ImportReview recipes={preview} confirmed={confirmedIds} busy={busy}
      onChange={recipe => setPreview(items => items.map(item => item.id === recipe.id ? recipe : item))}
      onSelectSave={async recipe => { if (await send("recipe.save", { recipe })) setConfirmedIds(ids => ids.includes(recipe.id) ? ids : [...ids, recipe.id]); }}
      onSaveAll={async () => { for (const recipe of preview) { if (confirmedIds.includes(recipe.id) || !recipe.name.trim()) continue; if (await send("recipe.save", { recipe })) setConfirmedIds(ids => [...ids, recipe.id]); } }}
      onDelete={id => { setPreview(items => items.filter(item => item.id !== id)); setConfirmedIds(ids => ids.filter(x => x !== id)); }}
      onReanalyze={() => { setPreview([]); setConfirmedIds([]); setImporting(true); }}
      onBack={() => { setPreview([]); setConfirmedIds([]); }} />}
    {!preview.length && <>
    <div className="kw-support-toolbar kw-recipe-filters"><label className="kw-label"><span className="sr-only">Find a recipe</span><input className="kw-input" placeholder="🔍  Search recipes, ingredients, tags…" value={search} onChange={e=>setSearch(e.target.value)}/></label><label className="kw-sort"><span>Sort by:</span><select aria-label="Sort recipes" value={sort} onChange={e=>setSort(e.target.value as typeof sort)}><option value="duration">Duration ⏱</option><option value="active">Active time 👨‍🍳</option><option value="name">Name A–Z</option><option value="saved">Saved order 📖</option></select></label></div>
    {/* One row: everything first, then the pinned tags as large chips, then the other tags. */}
    <div className="kw-filter-row" role="group" aria-label="Filter recipes">
      {chip(!mealFilter && !tagFilter, "All ★", () => { setMealFilter(""); setTagFilter(""); }, true)}
      {[...pinnedChips, ...otherChips].map((tag, index) => <Fragment key={tag.key}>
        {index === pinnedChips.length && <span className="kw-filter-divider" aria-hidden="true" />}
        {tag.meal
          ? chip(mealFilter === tag.meal, tag.label, () => setMealFilter(mealFilter === tag.meal ? "" : tag.meal!), tag.pinned)
          : chip(tagFilter === tag.key, tag.label, () => setTagFilter(tagFilter === tag.key ? "" : tag.key), tag.pinned)}
      </Fragment>)}
      <button type="button" className="kw-filter-edit" onClick={() => setTagsOpen(true)}>✎ Edit tags</button>
    </div>
    <RecipeGrid key={JSON.stringify([search,tagFilter,mealFilter,sort])} recipes={filteredRecipes} onOpen={open} onLike={likeRecipe}/>
    {!state.recipes.length && <p className="kw-empty">No recipes yet. Add one manually or import a recipe to review.</p>}
    {tagsOpen && <TagManager tags={tagChips} recipes={state.recipes} send={send} onClose={() => setTagsOpen(false)} onChanged={(from, to) => { if (tagFilter === from) setTagFilter(to ?? ""); }} />}
    </>}
  </section>;
}
