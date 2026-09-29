"use client";
import { ArrowSquareOut, ArrowsClockwise, Baby, Check, ChatCircle, Clock, LockSimple, PencilSimple, Plus, X } from "@phosphor-icons/react";
import { Fragment, useRef, useState, type ReactNode } from "react";
import { RecipeEditor } from "./recipes";
import { scheduleTasks } from "./schedule";
import { Drawer } from "./drawer";
import { RecipeArt, foodEmoji } from "./food-art";
import { dayLabel, uid } from "./data";
import { joinSteps, removeComponent, setDishSteps, stepGroups } from "./meal-steps";
import { DishCard } from "./dish-card";
import { blanks, fillMeal } from "./fill";
import { AlsoMark } from "./also-contains";
import { componentGroups } from "./food-groups";
import { BasketComposer, addComposedDish, type ComposedDish } from "./basket";
import type { KitchenState, Meal, WeeklyPlan, Recipe } from "./types";


/** A food added by hand starts at one portion. Defaulting to the household
 * size guessed high: most dishes on a plate are shared, not one each, so the
 * number had to be corrected more often than it was kept. */
const NEW_FOOD_PORTIONS=1;
/** "500g", "2个", but "1 piece" and "2 cups": a unit spelt as a word gets a space. */
const amount=(quantity:number,unit:string)=>/^[a-z]{3,}/i.test(unit.trim())?`${quantity} ${unit.trim()}`:`${quantity}${unit.trim()}`;

export function replaceMealComponent(meal:Meal,recipe:Recipe,part:string,state:KitchenState):Meal {
  const previous=meal.components.find(c=>c.id===part);
  if(part!=="all"&&!previous)throw new Error("Select a component to replace.");
  const replacement={id:previous?.id||uid(),name:recipe.name,type:recipe.type,recipeId:recipe.id,portions:previous?.portions||NEW_FOOD_PORTIONS};
  const components:Meal["components"]=part==="all"?[replacement]:meal.components.map(c=>c.id===part?replacement:c);
  const tasks=components.flatMap(c=>{if(c.prepId||state.inventory.find(i=>i.id===c.inventoryId)?.prepared)return [];const r=state.recipes.find(r=>r.id===c.recipeId);if(!r)throw new Error(`Recipe timing is missing for ${c.name}.`);const batches=Math.max(1,Math.ceil(c.portions/r.servings));return [{...r,id:c.id,activeMinutes:r.activeMinutes*batches,elapsedMinutes:r.elapsedMinutes*batches,dependencies:[]}];});
  const timing=scheduleTasks(tasks);
  return {...meal,components,activeMinutes:part==="all"?timing.activeMinutes:Math.max(meal.activeMinutes,timing.activeMinutes),elapsedMinutes:part==="all"?timing.elapsedMinutes:Math.max(meal.elapsedMinutes,timing.elapsedMinutes),steps:part==="all"?[...recipe.steps]:joinSteps(stepGroups(meal).map(g=>g.componentId===previous?.id?{...g,steps:[...recipe.steps]}:g),components)};
}

interface Props { planning?:boolean;demo?:boolean; notice?:ReactNode;meal:Meal;plan:WeeklyPlan;state:KitchenState;initialEdit?:boolean;initialReplace?:boolean;onClose:()=>void;onDirty:(dirty:boolean)=>void;onSave:(meal:Meal,original:Meal,recipes?:Recipe[])=>Promise<boolean>;onAction:(type:string,payload:Record<string,unknown>)=>Promise<boolean>;onReference?:()=>void;onRecipe:(id:string)=>void;busy:boolean }
export function MealDrawer({planning=false,demo=false,meal,plan,state,initialEdit=false,initialReplace=false,onClose,onDirty,onSave,onAction,onReference,busy,notice}:Props) {
  const initial=useRef(meal),[draft,setDraft]=useState<Meal>(()=>JSON.parse(JSON.stringify(meal)) as Meal),[mode,setMode]=useState<"detail"|"edit"|"replace"|"basket">(initialReplace?"replace":initialEdit||planning?"edit":"detail"),[dirty,setDirty]=useState(false),[closing,setClosing]=useState(false),[replacePart,setReplacePart]=useState("all"),[error,setError]=useState("");
  const [savedRecipeId,setSavedRecipeId]=useState<string|null>(null);
  // Calendar: the meal went differently — an optional note, nothing leaves the fridge.
  const [changing,setChanging]=useState(false),[noteText,setNoteText]=useState("");
  // Recipes of dishes composed from the fridge, saved with the meal.
  const [newRecipes,setNewRecipes]=useState<Recipe[]>([]);
  function addDish(dish:ComposedDish,keep:boolean){setComposed(false);change(addComposedDish(draft,dish,keep));if(keep)setNewRecipes(current=>[...current,dish.recipe]);setMode("edit");}
  const recipeUrl=(id:string)=>demo?`/demo?page=recipes&recipe=${encodeURIComponent(id)}`:`/recipes/${encodeURIComponent(id)}`;
  const [recipeDraft,setRecipeDraft]=useState<{componentId:string;recipe:Recipe}|null>(null),[recipeEdited,setRecipeEdited]=useState(false);
  // A dish Stu composed, not yet added: closing would throw it away.
  const [filling,setFilling]=useState(false);
  const [composed,setComposed]=useState(false),[basketFrom,setBasketFrom]=useState<"edit"|"replace">("edit");
  function openBasket(from:"edit"|"replace"){setBasketFrom(from);setMode("basket");}
  function editRecipe(component:Meal["components"][number]){
    initial.current=meal;setDraft(JSON.parse(JSON.stringify(meal)) as Meal);
    setRecipeEdited(false);setRecipeDraft({componentId:component.id,recipe:{id:uid(),name:component.name,type:component.type,mealTypes:[meal.slot],tags:[],servings:component.portions,activeMinutes:meal.activeMinutes,elapsedMinutes:meal.elapsedMinutes,ingredients:[{name:"",quantity:1,unit:"g"}],steps:meal.components.length===1?meal.steps:[""],liked:false,source:"Created from meal plan",incomplete:true}});
    onDirty(true);
  }
  function cancelRecipe(){setRecipeDraft(null);setRecipeEdited(false);setClosing(false);onDirty(dirty);}
  async function saveRecipe(recipe:Recipe){
    if(!recipeDraft)return false;
    const next={...draft,components:draft.components.map(c=>c.id===recipeDraft.componentId?{...c,name:recipe.name,type:recipe.type,recipeId:recipe.id}:c)};
    const saved=await onSave(next,initial.current,[recipe]);
    if(saved){setSavedRecipeId(recipe.id);initial.current=next;setDraft(next);setDirty(false);onDirty(false);setRecipeDraft(null);setMode("detail");setClosing(false);}
    return saved;
  }
  function change(next:Meal){setDraft(next);setDirty(true);onDirty(true);setError("");}
  /** Escape or a press outside: ask first when something would be lost. */
  function close(){if(dirty||(mode==="basket"&&composed))setClosing(true);else onClose();}
  /** The close button: close, dropping any unsaved edits. */
  function discard(){onDirty(false);onClose();}
  async function save(){if(!editable){setError("Unlock or undo execution before editing this meal.");return;}if(draft.components.length===0||draft.components.some(c=>!c.name.trim()||!Number.isFinite(c.portions)||c.portions<=0)){setError("Add at least one food and a positive portion count.");return;}if(!draft.day||!Number.isFinite(draft.activeMinutes)||!Number.isFinite(draft.elapsedMinutes)||draft.activeMinutes<0||draft.elapsedMinutes<draft.activeMinutes||draft.elapsedMinutes<=0){setError("Choose a date and valid active and elapsed minutes.");return;}// Stu fills the hand-written dishes' blanks first; if it cannot, the meal saves as it is.
let next=draft;if(blanks(draft,state).count){setFilling(true);try{next=await fillMeal(draft,state,demo);}catch{setError("Stu could not fill the blanks just now; the meal is saved as it is, and you can fill them later.");}finally{setFilling(false);}}const saved=await onSave(next,initial.current,newRecipes.filter(r=>next.components.some(c=>c.recipeId===r.id)));if(saved){setNewRecipes([]);setDraft(next);setDirty(false);onDirty(false);setClosing(false);setMode(planning?"edit":"detail");initial.current=next;if(closing)onClose();}}
  function replace(id:string){const recipe=state.recipes.find(r=>r.id===id);if(!recipe||recipe.incomplete)return;try{change(replaceMealComponent(draft,recipe,replacePart,state));setMode("edit");}catch(error){setError(error instanceof Error?error.message:"Unable to calculate recipe timing.");}}
  function source(index:number,value:string){
    const current=draft.components[index];
    const inventory=value.startsWith("inventory:")?state.inventory.find(item=>item.id===value.slice(10)):undefined;
    const prep=value.startsWith("prep:")?plan.prep.find(task=>task.id===value.slice(5)):undefined;
    const recipe=value.startsWith("recipe:")?state.recipes.find(item=>item.id===value.slice(7)):undefined;
    if(value==="basket")return;
    const component={...current,inventoryId:inventory?.id,prepId:prep?.id,recipeId:inventory?.recipeId||prep?.recipeId||recipe?.id,name:inventory?.name||prep?.name||recipe?.name||current.name,type:inventory?.type||(prep?.type==="Baking"?"Carbs":prep?.type)||recipe?.type||current.type,uses:undefined,secondaryTypes:undefined};
    change({...draft,components:draft.components.map((item,i)=>i===index?component:item)});
  }
  const executed=meal.status!=="planned",confirmed=plan.status==="confirmed",editable=!executed&&!meal.locked;
  const [gathered,setGathered]=useState<Record<string,boolean>>({});
  const fromFridge=meal.components.some(c=>c.inventoryId||c.prepId||c.uses?.length);
  const basketLine=(c:Meal["components"][number])=>(c.uses??[]).map(u=>`${state.inventory.find(i=>i.id===u.inventoryId)?.name??"Missing food"} ${u.portions}`).join(" · ");
  /** Total effort = this meal's share of the weekend prep it draws on, plus the
   * hands-on time on the day. A batch feeds several meals, so a meal carries the
   * prep minutes for the portions it uses, not the whole batch. */
  const prepMinutes=Math.round(meal.components.reduce((sum,c)=>{const task=plan.prep.find(t=>t.id===c.prepId);if(!task)return sum;return sum+(task.plannedPortions>0?task.activeMinutes*Math.min(1,c.portions/task.plannedPortions):task.activeMinutes);},0));
  const effort=prepMinutes+meal.activeMinutes;
  const heroRecipe=state.recipes.find(r=>r.id===meal.components.find(c=>c.recipeId)?.recipeId);
  /** Frame 42:37 lists the ingredients grouped the way the recipe stores them.
   * A row starts ticked when the fridge already holds that food, so the list
   * reads as "what is still missing" without inventing stock the app cannot see. */
  const ingredientGroups=(()=>{
    const groups=new Map<string,{label:string;emoji:string;items:{name:string;quantity:number;unit:string;onHand:boolean}[]}>();
    meal.components.forEach(component=>{
      const recipe=state.recipes.find(r=>r.id===component.recipeId);
      recipe?.ingredients.forEach(ingredient=>{
        const label=ingredient.group?.trim()||"";
        const entry=groups.get(label)??{label,emoji:foodEmoji(label||ingredient.name,recipe.type),items:[]};
        if(!entry.items.some(item=>item.name===ingredient.name))
          entry.items.push({name:ingredient.name,quantity:ingredient.quantity,unit:ingredient.unit,onHand:state.inventory.some(stock=>stock.portions>0&&stock.name.toLocaleLowerCase()===ingredient.name.toLocaleLowerCase())});
        groups.set(label,entry);
      });
    });
    return [...groups.values()];
  })();
  const lastExecution=[...state.audit].reverse().find(a=>{const entry=a as typeof a & {undo?:{entityId?:string;collection?:string;planId?:string};undone?:boolean};return entry.kind==="meal.status"&&entry.undo?.entityId===meal.id&&entry.undo.collection==="meals"&&entry.undo.planId===plan.id&&!entry.undone;});
  const chineseDay=new Intl.DateTimeFormat("zh-CN",{weekday:"long",timeZone:"UTC"}).format(new Date(`${meal.day}T12:00:00Z`));
  const slotLabel=meal.slot[0].toUpperCase()+meal.slot.slice(1);
  // A meal not in the plan yet is being added, not replaced.
  const adding=!plan.meals.some(m=>m.id===meal.id);
  const title=mode==="detail"?`${chineseDay} ${dayLabel(meal.day,true)}`:mode==="basket"?"Cook from the fridge":mode==="replace"?(adding?"Add a meal":"Replace a meal"):adding?"New meal":"Edit meal";
  const dish=meal.components.map(c=>c.name).join(" + ")||"Untitled meal";
  if(recipeDraft)return <Drawer title="Edit and add recipe" subtitle="Review ingredients, quantities and steps before saving." onClose={discard} onDismiss={()=>{if(recipeEdited||dirty)setClosing(true);else onClose();}} notice={notice} prompt={closing?<div className="kw-unsaved" role="alert"><strong>Discard these recipe edits?</strong><button className="kw-button" onClick={cancelRecipe}>Discard recipe edits</button><button className="kw-text-button" onClick={()=>setClosing(false)}>Keep editing</button></div>:undefined}><RecipeEditor initial={recipeDraft.recipe} tags={state.tags} save={saveRecipe} cancel={cancelRecipe} onEdited={()=>setRecipeEdited(true)}/></Drawer>;
  const displayMeal=savedRecipeId?draft:meal;
  const missingRecipe=displayMeal.components.find(c=>!state.recipes.some(r=>r.id===c.recipeId)&&c.recipeId!==savedRecipeId);
  const firstRecipe=displayMeal.components.find(c=>c.recipeId&&(c.recipeId===savedRecipeId||state.recipes.some(r=>r.id===c.recipeId)))?.recipeId;
  const unsaved=closing?<div className="kw-unsaved" role="alert"><strong>Keep your changes?</strong><p>Your edits haven’t been saved yet.</p><button className="kw-button" disabled={busy} onClick={()=>void save()}>Save changes</button><button className="kw-button secondary" onClick={discard}>Discard changes</button><button className="kw-text-button" onClick={()=>setClosing(false)}>Keep editing</button></div>:undefined;
  // While asking, the answer is in the prompt; the footer's own buttons wait.
  const footer=closing||mode==="basket"?undefined:mode!=="detail"?<><button className="kw-button full" disabled={busy||filling} onClick={()=>void save()}><Check size={16}/>{filling?"Stu is filling the blanks…":<>Save changes{blanks(draft,state).count?` · Stu fills ${blanks(draft,state).count} blanks`:""}</>}</button><button className="kw-button secondary full" onClick={()=>{if(planning){discard();return;}setDraft(JSON.parse(JSON.stringify(meal)) as Meal);setDirty(false);onDirty(false);setMode("detail");}}>Cancel editing</button></>:<>{missingRecipe?<button className="kw-button kw-full-recipe" disabled={!editable||busy} onClick={()=>editRecipe(missingRecipe)}>Save to recipe 📖</button>:firstRecipe?<a className={`kw-button kw-full-recipe ${savedRecipeId?"is-recipe-saved":""}`} href={recipeUrl(firstRecipe)} target="_blank" rel="noopener noreferrer">{savedRecipeId&&<span className="kw-recipe-saved-check" aria-hidden="true">✓</span>}View full recipe 📖 <ArrowSquareOut size={16}/></a>:null}<button className="kw-button kw-swap-dish" aria-label="Replace" disabled={!editable||busy} onClick={()=>{initial.current=meal;setDraft(JSON.parse(JSON.stringify(meal)) as Meal);setMode("replace");}}>换一道菜 Swap Dish 🔄</button></>;
  return <Drawer title={title} subtitle={mode==="detail"?`${slotLabel} · ${fromFridge?"Fridge 🧊":"Fresh 🌿"} · ${plan.status==="draft"?"Draft":"Confirmed"}`:`${slotLabel} · ${plan.status==="draft"?"Draft":"Confirmed"}`} lead={mode==="detail"?<h3 className="kw-dish-title">{meal.components.length?meal.components.map((c,i)=><Fragment key={c.id}>{i?" + ":""}{c.name}<AlsoMark primary={c.type} groups={componentGroups(c,state)}/></Fragment>):dish}</h3>:undefined} onClose={discard} onDismiss={close} footer={footer} notice={notice} prompt={unsaved}>{error&&<p className="kw-error" role="alert">{error}</p>}{mode==="detail"?<><div className="kw-meal-hero"><RecipeArt name={heroRecipe?.name??meal.components[0]?.name??""} type={heroRecipe?.type??meal.components[0]?.type??"Other"}/>{!planning&&confirmed&&<div className="kw-hero-actions"><button className="kw-hero-action done" aria-label="Mark completed" title="Mark completed" disabled={!confirmed||executed||busy} onClick={()=>void onAction("meal.status",{planId:plan.id,mealId:meal.id,status:"completed"})}><Check size={17}/></button><button className="kw-hero-action skip" aria-label="Skip meal" title="Skip meal" disabled={!confirmed||executed||meal.status==="skipped"||busy} onClick={()=>void onAction("meal.status",{planId:plan.id,mealId:meal.id,status:"skipped"})}><X size={16}/></button><button className="kw-hero-action changed" aria-label="Mark changed" title="It went differently" aria-expanded={changing} disabled={!confirmed||executed||busy} onClick={()=>setChanging(open=>!open)}><ArrowsClockwise size={16}/></button><button className={`kw-hero-action like ${meal.liked?"is-active":""}`} aria-label="Baby liked it" title="Baby liked it" aria-pressed={meal.liked} disabled={busy} onClick={()=>void onAction("meal.like",{planId:plan.id,mealId:meal.id,liked:!meal.liked})}><Baby size={17}/></button></div>}</div>
{changing&&!executed&&<form className="kw-changed-note" onSubmit={event=>{event.preventDefault();const text=noteText.trim();void onAction("meal.status",{planId:plan.id,mealId:meal.id,status:"changed",...(text?{note:text}:{})}).then(ok=>{if(ok){setChanging(false);setNoteText("");}});}}><label className="kw-label">What happened instead? (optional)<textarea className="kw-input" rows={2} maxLength={500} value={noteText} placeholder="e.g. 改成了包子" onChange={event=>setNoteText(event.target.value)}/></label><div className="kw-row"><button className="kw-button" disabled={busy}>Save as changed</button><button type="button" className="kw-text-button" onClick={()=>setChanging(false)}>Cancel</button></div><p className="kw-muted small">Nothing is taken from the fridge; change it there if something else was eaten.</p></form>}
{meal.status==="changed"&&<p className="kw-changed-shown"><ArrowsClockwise size={14}/> Changed{meal.note&&<>: <span>{meal.note}</span></>}</p>}
<div className="kw-meal-chips"><span className="kw-effort" title="Total effort"><Clock size={14}/><strong>{effort} min</strong><small>{prepMinutes>0?`${prepMinutes} prep + ${meal.activeMinutes} fresh`:`${meal.activeMinutes} fresh`}</small></span><span className={`kw-source ${fromFridge?"fridge":"fresh"}`}>{fromFridge?"🧊 From fridge":"🌿 Fresh"}</span>{heroRecipe?.difficulty&&<span className="kw-source">⭐ {heroRecipe.difficulty[0].toUpperCase()+heroRecipe.difficulty.slice(1)}</span>}{!planning&&<span className="kw-meta">{meal.status==="planned"?"Planned":meal.status}</span>}<span className="kw-meta">{Math.max(...meal.components.map(c=>c.portions),0)} portions</span><button className="kw-button kw-edit-meal" disabled={!editable||busy} aria-label="Edit meal" onClick={()=>{initial.current=meal;setDraft(JSON.parse(JSON.stringify(meal)) as Meal);setMode("edit");}}><PencilSimple size={17}/>Edit meal</button></div>
{ingredientGroups.length>0&&<section className="kw-detail-card"><h3>食材清单 Ingredients</h3><div className="kw-ingredient-list">{ingredientGroups.map(group=><div className="kw-ingredient-group" key={group.label}>{group.label&&<span className="kw-ingredient-label">{group.emoji} {group.label}</span>}{group.items.map(item=><label className="kw-ingredient-row" key={`${group.label}:${item.name}`}><span>{item.name}{item.quantity?` ${amount(item.quantity,item.unit)}`:""}</span><input type="checkbox" aria-label={`Have ${item.name}`} checked={gathered[item.name]??item.onHand} onChange={e=>setGathered(current=>({...current,[item.name]:e.target.checked}))}/></label>)}</div>)}</div></section>}
<section className="kw-detail-card"><h3>简单步骤 Quick Steps</h3>{stepGroups(meal).filter(group=>group.steps.length).map((group,_,groups)=>{const dish=meal.components.find(c=>c.id===group.componentId);return <div className="kw-step-group" key={group.componentId??"whole"}>{groups.length>1&&<h4 className="kw-step-dish"><span aria-hidden="true">{dish?foodEmoji(dish.name,dish.type):"🍽️"}</span>{group.label}</h4>}<ol className="kw-quick-steps">{group.steps.map((step,i)=>{const detail=groups.length===1?heroRecipe?.stepDetails?.find(d=>d.index===i):undefined;return <li key={i}><span className="kw-step-number" aria-hidden="true">{i+1}</span><span className="kw-step-text">{detail?.title&&<strong>{detail.title} — </strong>}{step}{detail?.activeMinutes?<em> ({detail.activeMinutes} min)</em>:null}</span></li>;})}</ol></div>;})}</section>
<section className="kw-detail-section"><h3>From your fridge</h3>{meal.components.map(c=>{const prep=plan.prep.find(t=>t.id===c.prepId);const stock=state.inventory.find(x=>x.id===(prep?.outputInventoryId||c.inventoryId));return <div className="kw-stock-row" key={c.id}><span>{c.name}<AlsoMark primary={c.type} groups={componentGroups(c,state)}/><small>{c.portions} portions {meal.status==="completed"?"used":"needed"}</small></span><small>{c.uses?.length?`🧺 ${basketLine(c)}`:stock?`${stock.location} · ${stock.portions} on hand`:c.inventoryId||c.prepId?"Prep / stock needed":"Prepare fresh"}</small>{!c.recipeId&&!c.inventoryId&&!c.prepId&&<button className="kw-text-button" disabled={!editable||busy} aria-label={`Edit and add recipe for ${c.name}`} onClick={()=>editRecipe(c)}>Edit & add recipe</button>}{c.recipeId&&state.recipes.some(r=>r.id===c.recipeId)&&<a className="kw-icon" aria-label={`View recipe for ${c.name}`} href={recipeUrl(c.recipeId)} target="_blank" rel="noopener noreferrer"><ArrowSquareOut size={14}/></a>}</div>;})}{meal.components.some(c=>c.prepId)&&<p className="kw-prep-note">{meal.components.filter(c=>c.prepId).some(c=>plan.prep.find(t=>t.id===c.prepId)?.status!=="completed")?"Prep needed: check your Sunday tasks.":"Prep complete: your portions are ready."}</p>}</section>
<>{!planning&&confirmed&&meal.status==="completed"&&<LeftoversForm meal={meal} plan={plan} state={state} onAction={onAction} busy={busy}/>}</>
<div className="kw-detail-extra">{onReference&&<button className="kw-text-button" onClick={onReference}><ChatCircle size={14}/>Reference in chat</button>}<button className="kw-text-button" aria-pressed={meal.locked} disabled={busy} onClick={()=>void onAction("meal.lock",{planId:plan.id,mealId:meal.id,locked:!meal.locked})}><LockSimple size={14}/>{meal.locked?"Unlock meal":"Lock this meal every week"}</button>{!planning&&lastExecution&&executed&&<button className="kw-text-button" disabled={busy} onClick={()=>void onAction("change.undo",{auditId:lastExecution.id})}>{meal.status==="skipped"?"Undo skip":meal.status==="changed"?"Undo changed":"Undo completion"}</button>}</div></>:mode==="basket"?<BasketComposer state={state} meal={draft} demo={demo} onCancel={()=>{setComposed(false);setMode(basketFrom);}} onAdd={addDish} onComposed={setComposed}/>:mode==="replace"?<>{adding?<><button className="kw-button kw-make-own" onClick={()=>openBasket("replace")}>🧺 Make your own</button><p className="kw-or"><span>or choose a recipe</span></p></>:<p className="kw-muted">Choose what to replace. The rest of your week stays as planned.</p>}{!adding&&<label className="kw-label">Replace<select className="kw-input" value={replacePart} onChange={e=>setReplacePart(e.target.value)}><option value="all">Entire meal</option>{draft.components.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}<div className="kw-replacement-list">{state.recipes.map(r=><button key={r.id} className="kw-replacement" disabled={r.incomplete} onClick={()=>replace(r.id)}><strong>{r.name}</strong><span>{r.type} · {r.activeMinutes} min active</span><small>{r.incomplete?"Needs review · complete this recipe in Recipes first. ":""}{r.liked?"Baby liked this · ":""}{state.inventory.some(s=>s.recipeId===r.id&&s.portions>0)?"Stored portions available · choose the source when editing":"Prepare fresh"}</small></button>)}</div>{state.recipes.length===0&&<p className="kw-empty">Add recipes to see replacement options.</p>}</>:<div className="kw-edit-form"><div className="kw-form-grid"><label className="kw-label">Date<input className="kw-input" type="date" value={draft.day} min={plan.weekStart} max={new Date(new Date(`${plan.weekStart}T12:00:00Z`).getTime()+6*86400000).toISOString().slice(0,10)} onChange={e=>change({...draft,day:e.target.value})}/></label><label className="kw-label">Meal<select className="kw-input" value={draft.slot} onChange={e=>change({...draft,slot:e.target.value as Meal["slot"]})}><option value="breakfast">Breakfast</option><option value="lunch">Lunch</option><option value="dinner">Dinner</option></select></label></div><div className="kw-row"><h3 className="kw-section-label">Meal composition</h3><span className="kw-composition-actions"><button className="kw-text-button" onClick={()=>{setReplacePart(draft.components.some(c=>c.name.trim())?draft.components[0]?.id||"all":"all");setMode("replace");}}>Choose recipe</button><button className="kw-text-button" onClick={()=>openBasket("edit")}>🧺 Cook from fridge</button></span></div>{draft.components.map((c,i)=><DishCard key={c.id} dish={c} index={i} meal={draft} state={state} plan={plan} basketLine={basketLine(c)} recipeHref={recipeUrl} onMeal={change} onSource={value=>source(i,value)} onRemove={()=>change(removeComponent(draft,c.id))}/>)}<button className="kw-text-button" onClick={()=>change({...draft,components:[...draft.components,{id:uid(),name:"",type:"Other",portions:NEW_FOOD_PORTIONS}]})}><Plus size={15}/>Add food</button><div className="kw-form-grid"><label className="kw-label">Active minutes<input className="kw-input" type="number" min="0" value={draft.activeMinutes} onChange={e=>change({...draft,activeMinutes:Number(e.target.value)})}/></label><label className="kw-label">Elapsed minutes<input className="kw-input" type="number" min={draft.activeMinutes} value={draft.elapsedMinutes} onChange={e=>change({...draft,elapsedMinutes:Number(e.target.value)})}/></label></div><p className="kw-label kw-steps-heading">Today’s steps <span className="kw-muted">One step per line, by dish</span></p><WholeSteps meal={draft} onMeal={change}/>{planning&&<div className="kw-detail-extra">{onReference&&<button className="kw-text-button" onClick={onReference}><ChatCircle size={14}/>Reference in chat</button>}<button className="kw-text-button" aria-pressed={meal.locked} disabled={busy} onClick={()=>void onAction("meal.lock",{planId:plan.id,mealId:meal.id,locked:!meal.locked})}><LockSimple size={14}/>{meal.locked?"Unlock meal":"Lock this meal every week"}</button></div>}<p className="kw-muted small">Saving updates this {plan.status} plan in Calendar and Plan. Rule conflicts will appear in Plan Analysis.</p></div>}</Drawer>;
}

function LeftoversForm({meal,plan,state,onAction,busy}:Pick<Props,"meal"|"plan"|"state"|"onAction"|"busy">) {
  const [open,setOpen]=useState(false),[componentId,setComponentId]=useState(meal.components[0]?.id||""),[portions,setPortions]=useState("1"),[location,setLocation]=useState("Fridge"),[saving,setSaving]=useState(false);
  const records=state.audit.filter(a=>a.kind==="meal.leftovers"&&!a.undone&&a.planId===plan.id&&a.entityId===meal.id);
  const component=meal.components.find(c=>c.id===componentId);
  const remaining=(component?.portions||0)-records.filter(a=>a.componentId===componentId).reduce((sum,a)=>sum+(a.deltas||[]).reduce((n,d)=>n+d.amount,0),0);
  const latest=records.at(-1);
  return <section className="kw-detail-section"><h3>Keep the extra portions</h3><p className="kw-muted small">Record prepared food left after this meal as a new fridge batch.</p>{!open?<button className="kw-button secondary" onClick={()=>setOpen(true)}>Save leftovers</button>:<form onSubmit={async e=>{e.preventDefault();setSaving(true);try{if(await onAction("meal.leftovers",{planId:plan.id,mealId:meal.id,componentId,portions:Number(portions),location}))setOpen(false);}finally{setSaving(false);}}}><label className="kw-label">Leftover food<select className="kw-input" value={componentId} onChange={e=>setComponentId(e.target.value)}>{meal.components.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><label className="kw-label">Leftover portions<input className="kw-input" type="number" min="0.25" max={remaining} step="0.25" required value={portions} onChange={e=>setPortions(e.target.value)}/></label><p className="kw-muted small">Up to {Math.max(0,remaining)} portions remaining to record.</p><label className="kw-label">Store in<select className="kw-input" value={location} onChange={e=>setLocation(e.target.value)}><option>Fridge</option><option>Freezer</option></select></label><div className="kw-support-actions"><button className="kw-button" disabled={busy||saving||!Number.isFinite(Number(portions))||Number(portions)<=0||Number(portions)>remaining}>Add leftovers to fridge</button><button className="kw-button secondary" type="button" onClick={()=>setOpen(false)}>Cancel</button></div></form>}{latest&&<button className="kw-text-button" disabled={busy||saving} onClick={()=>void onAction("change.undo",{auditId:latest.id})}>Undo latest leftovers</button>}</section>;
}

/** The steps for the whole meal (serving, anything shared), after the dishes'
 * own. A one-dish meal keeps every step with its dish, so this only shows for
 * several dishes or when such steps exist. Its own text keeps blank lines. */
function WholeSteps({meal,onMeal}:{meal:Meal;onMeal:(meal:Meal)=>void}){
  const [text,setText]=useState(()=>stepGroups(meal).find(group=>!group.componentId)?.steps.join("\n")??"");
  if(meal.components.length<=1&&!text.trim())return null;
  return <label className="kw-label"><span className="kw-dish-steps-label"><span aria-hidden="true">🍽️</span>Whole meal</span><textarea className="kw-input" rows={Math.min(8,Math.max(2,text.split("\n").length+1))} aria-label="Steps for Whole meal" placeholder="Serving, or anything done for the whole meal" value={text} onChange={event=>{setText(event.target.value);onMeal(setDishSteps(meal,undefined,event.target.value));}}/></label>;
}

