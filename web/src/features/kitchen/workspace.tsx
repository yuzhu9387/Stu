"use client";
import Image from "next/image";
import { CalendarBlank, Check, ArrowRight } from "@phosphor-icons/react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Login } from "@/features/auth/login";
import { api, ApiError } from "@/lib/api";
import { useAiTask, type AiTask, type ChatTurn } from "./ai-tasks";
import { useStored } from "./browser-store";
import { CalendarGrid } from "./calendar";
import { createDemoState, mondayOf, shiftWeek, uid, weekDays, weekLabel } from "./data";
import { Drawer } from "./drawer";
import { FridgePage } from "./fridge";
import { GuidancePage } from "./guidance";
import { KnowledgePage } from "./knowledge";
import { MealDrawer } from "./meal-drawer";
import { PlanningPage } from "./plan";
import { PrepPage } from "./prep";
import { KitchenProfileMenu } from "./profile-menu";
import { ShoppingPrepPage } from "./shopping-prep";
import { planningStep, rememberedPlan } from "./workflow";
import { RecipesPage, RecipeSource } from "./recipes";
import { requestChatFocus, useChatRefs } from "./chat-refs";
import { pendingWrites, slotKey, useSetupChoices, useChosenPlan } from "./slot-choices";
import { useKitchen } from "./store";
import type { CardNote } from "./calendar";
import type { ChatProposal, CommandResult, Guidance, KitchenState, Meal, MealSlot, Page, Recipe, WeeklyPlan, PlanStep } from "./types";

const failure=(e:unknown,fallback:string)=>e instanceof Error?e.message:fallback;
/** The time an action started, read in its event handler (never in render). */
const startedNow=()=>Date.now();
/** The demo has no AI: split the note on punctuation, one preference per
 * clause, skipping titles the household already has. */
function splitDemoPreferences(text:string,existing:Guidance[]){
  const seen=new Set(existing.map(g=>g.title.trim().toLocaleLowerCase()));
  return text.split(/[\n，。；;,.!！?？]+/).map(part=>part.trim()).filter(part=>part.length>1).flatMap(part=>{const title=part.length>24?`${part.slice(0,24)}…`:part;const key=title.toLocaleLowerCase();if(seen.has(key))return [];seen.add(key);return [{title,content:part}];});
}
import "./kitchen.css";
import "./support.css";
import "./figma.css";
import "./workflow.css";

const pages:Page[]=["calendar","plan","fridge","recipes","guidance","knowledge","prep"];
const titles:Record<Page,string>={calendar:"Calendar",plan:"Plan",prep:"Weekend prep",fridge:"Fridge",recipes:"Recipes",guidance:"Settings",knowledge:"Nutrition knowledge"};
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value)) as T;

function preferredPlan(plans:WeeklyPlan[],target:Page,week:string){
  const choices=plans.filter(p=>p.weekStart===week),confirmed=choices.find(p=>p.status==="confirmed");
  if(target==="plan"){if(confirmed)return [...choices].reverse().find(p=>p.status==="draft"&&p.basePlanId===confirmed.id)??confirmed;return [...choices].reverse().find(p=>p.status==="draft")??choices.at(-1)??null;}
  return confirmed??choices.at(-1)??null;
}

export function KitchenWorkspace({initialPage="calendar",demo=false,recipeId:routeRecipe}:{initialPage?:Page;demo?:boolean;recipeId?:string}){
  const router=useRouter(),params=useSearchParams(),kitchen=useKitchen(demo);
  const page=demo&&pages.includes(params.get("page") as Page)?params.get("page") as Page:initialPage;
  const defaultWeek=demo?"2026-09-21":mondayOf();
  const rawWeek=params.get("week"),week=rawWeek&&/^\d{4}-\d{2}-\d{2}$/.test(rawWeek)&&!Number.isNaN(Date.parse(rawWeek))?rawWeek:defaultWeek;
  const {state}=kitchen;
  const workspaceRef=useRef<HTMLDivElement>(null),scrollToPage=useRef<Page|null>(null);
  // The page content lives in a persistent layout. Next cannot scroll an
  // empty leaf route into view, so app navigation does it after that page commits.
  useLayoutEffect(()=>{
    if(scrollToPage.current!==page)return;
    scrollToPage.current=null;
    workspaceRef.current?.scrollIntoView?.({block:"start"});
  },[page]);
  const [workflowError,setWorkflowError]=useState<string|null>(null);
  const stepWanted=useRef<{weekStart:string;workflow:{planId?:string;step:PlanStep;focus:"shopping"|"prep"}}|null>(null),stepSaving=useRef<Promise<Error|null>|null>(null);
  const options=state.plans.filter(p=>p.weekStart===week);
  const upcomingDraft=[...state.plans].reverse().find(p=>p.weekStart===shiftWeek(week,1)&&p.status==="draft");
  /** The plan a page shows when the URL names none. The plan page shows the
   * week being worked on: an edit in progress on the confirmed plan, else the
   * confirmed plan, else the latest draft. A confirmed plan's superseded
   * versions (demoted to draft by a later confirm) are never the default. */
  function defaultPlanFor(target:Page,forWeek:string){
    const saved=state.weeklyPrompts?.find(entry=>entry.weekStart===forWeek)?.workflow;
    return (target==="plan"?rememberedPlan(state.plans,forWeek,saved):null)??preferredPlan(state.plans,target,forWeek);
  }
  const plan=options.find(p=>p.id===params.get("plan"))??defaultPlanFor(page,week);
  const setupChoices=useSetupChoices(week,demo);
  const view=useChosenPlan(plan,setupChoices.choices);
  const points=useMemo(()=>state.plans.reduce((sum,p)=>sum+p.meals.filter(m=>m.status==="completed").length+p.prep.filter(t=>t.status==="completed").length,0)*10,[state.plans]);
  const [opened,setOpened]=useState<{id:string;edit?:boolean;replace?:boolean;fresh?:Meal}|null>(null),[dirty,setDirty]=useState(false),[recipeId,setRecipeId]=useState<string|null>(null),[message,setMessage]=useState(""),[aiBusy,setAiBusy]=useState(false),[undoId,setUndoId]=useState<string|null>(null);
  const chatRefs=useChatRefs(week,demo),[focusTick,setFocusTick]=useState(0);
  // Plan and Calendar show no page banner: what a card action did (or why it
  // failed) is said on that card instead.
  const [cardNote,setCardNote]=useState<CardNote|null>(null),noteSeq=useRef(0);
  // Back/Forward also changes pages, without going through navigate(). Keep
  // page-local drawers and notices from following the persistent workspace.
  const [previousPage,setPreviousPage]=useState(page);
  if(previousPage!==page){
    setPreviousPage(page);setOpened(null);setRecipeId(null);setDirty(false);
    setMessage("");setCardNote(null);setWorkflowError(null);setUndoId(null);
  }
  const contexts=chatRefs.refs.filter(id=>plan?.meals.some(m=>m.id===id));
  const planSnapshot=(value:WeeklyPlan)=>JSON.stringify({...value,chat:[]});
  useEffect(()=>{if(!dirty)return;const protect=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue="";};window.addEventListener("beforeunload",protect);return()=>window.removeEventListener("beforeunload",protect);},[dirty]);
  const selected=opened?.fresh??plan?.meals.find(m=>m.id===opened?.id)??plan?.meals.find(m=>m.id===params.get("meal"))??null;
  const recipe=state.recipes.find(r=>r.id===recipeId);
  const notify=(text:string)=>setMessage(text);
  function href(next:Page,{week:toWeek=week,plan:toPlan,meal,step}:{week?:string;plan?:string|null;meal?:string|null;step?:string|null}={}){
    const query=new URLSearchParams();
    if(demo)query.set("page",next);
    if(toWeek!==defaultWeek)query.set("week",toWeek);
    if(toPlan&&toPlan!==defaultPlanFor(next,toWeek)?.id)query.set("plan",toPlan);
    if(step)query.set("step",step);
    if(meal)query.set("meal",meal);
    const search=query.toString();
    return `${demo?"/demo":`/${next}`}${search?`?${search}`:""}`;
  }
  function navigate(next:Page,mealId?:string,nextWeek=week,nextPlan:string|null|undefined=plan?.id,step?:PlanStep){
    if(dirty){notify("Save or discard your drawer edits before leaving this meal.");return;}
    if(next!==page)scrollToPage.current=next;
    setOpened(null);setRecipeId(null);setMessage("");setCardNote(null);router.push(href(next,{week:nextWeek,plan:nextPlan,meal:mealId,step}));
  }
  // Stu's work is kept on the server, so a refresh or another page neither
  // stops it nor loses it: the plan page picks up the latest chat turn and the
  // week's draft, and follows them while they run.
  // Only once the kitchen has loaded for a signed-in household: asking earlier
  // would fail and not be asked again after signing in.
  const live=!demo&&!kitchen.loading&&!kitchen.unauthorized&&!kitchen.error;
  const conversationPlan=page==="plan"?plan:defaultPlanFor("plan",week);
  const chatTask=useAiTask(live&&conversationPlan?`kind=chat&planId=${encodeURIComponent(conversationPlan.id)}`:null,()=>void kitchen.reload());
  const genTask=useAiTask(live?`kind=generate&weekStart=${week}`:null,()=>void kitchen.reload());
  const generationOrigins=useRef(new Map<string,{planId:string|null;step:string|null}>()),acknowledging=useRef(new Set<string>());
  const generationTask=genTask.task,dismissTask=genTask.dismiss;
  const selectedPlanId=params.get("plan"),selectedStep=params.get("step");
  // Show a recovered result after the kitchen contains it. Once opened, mark
  // it reviewed so later visits cannot resurrect a superseded draft.
  useEffect(()=>{
    if(page!=="plan"||dirty||generationTask?.status!=="done"||generationTask.resolution!=="open"||acknowledging.current.has(generationTask.id))return;
    const generated=state.plans.find(p=>p.id===generationTask.result?.planId);
    if(!generated)return;
    const obsolete=preferredPlan(state.plans,"plan",generationTask.weekStart)?.id!==generated.id;
    const origin=generationOrigins.current.get(generationTask.id);
    const unchangedOrigin=origin&&origin.planId===selectedPlanId&&origin.step===selectedStep;
    if(!obsolete&&selectedPlanId&&selectedPlanId!==generated.id&&!unchangedOrigin)return;
    acknowledging.current.add(generationTask.id);
    if(!obsolete&&generated.status==="draft"&&(plan?.id!==generated.id||selectedStep!=="adjust")){
      router.push(`/plan?${new URLSearchParams({week:generationTask.weekStart,plan:generated.id,step:"adjust"})}`);
    }
    void dismissTask(generationTask.id).catch(()=>{acknowledging.current.delete(generationTask.id);});
  },[page,dirty,generationTask,state.plans,selectedPlanId,selectedStep,plan?.id,router,dismissTask]);
  const generatedPlanId=generationTask?.result?.planId;
  const readyGeneration=generationTask?.status==="done"&&generationTask.resolution==="open"&&generatedPlanId&&defaultPlanFor("plan",week)?.id===generatedPlanId?generatedPlanId:null;
  // The demo has no server: its latest turn is kept in the browser instead.
  const [demoTurnRaw,writeDemoTurn]=useStored("local",`stu-chat-turn:demo:${plan?.id??"none"}`);
  const demoTurn=useMemo(()=>{try{return demoTurnRaw?JSON.parse(demoTurnRaw) as ChatTurn:null;}catch{return null;}},[demoTurnRaw]);
  const turn:ChatTurn|null=demo?demoTurn:chatTask.task&&{...chatTask.task,result:chatTask.task.result as ChatProposal|null};
  const fulfillment=useAiTask(live&&plan?`kind=fulfillment&planId=${encodeURIComponent(plan.id)}`:null,()=>void kitchen.reload());
  const [demoConfirmSince,setDemoConfirmSince]=useState<number|null>(null);
  const confirmingSince=demo?demoConfirmSince:fulfillment.task?.status==="running"?fulfillment.task.startedAt:null;
  const fulfillmentError=fulfillment.task?.status==="failed"&&fulfillment.task.resolution==="open"?fulfillment.task.error:null;
  const fulfilled=useRef(new Set<string>());
  useEffect(()=>{
    const task=fulfillment.task;
    if(page!=="plan"||!task||task.status!=="done"||task.resolution!=="open"||plan?.status!=="confirmed"||dirty||fulfilled.current.has(task.id))return;
    fulfilled.current.add(task.id);setupChoices.clear();
    router.push(`/plan?${new URLSearchParams({week:plan.weekStart,plan:plan.id,step:"shopping"})}`);
    void fulfillment.dismiss(task.id).catch(()=>fulfilled.current.delete(task.id));
  },[fulfillment,plan,page,dirty,router,setupChoices]);
  const [demoSince,setDemoSince]=useState<number|null>(null);
  const generatingSince=demo?demoSince:genTask.task?.status==="running"?genTask.task.startedAt:null;
  const generationError=!demo&&genTask.task?.status==="failed"&&genTask.task.resolution==="open"?genTask.task.error:null;
  function close(){setOpened(null);setDirty(false);setMessage("");if(params.get("meal")){const query=new URLSearchParams(params.toString());query.delete("meal");router.push(`${demo?"/demo":`/${page}`}?${query}`);}}
  function setContexts(ids:string[]){chatRefs.set(ids);}
  async function send(type:string,payload:Record<string,unknown>,options?:{quiet?:boolean}){try{const result=await kitchen.send(type,payload,state.revision);if(!options?.quiet)notify(result.message);const last=result.state.audit.at(-1);if(last&&(type==="meal.status"||type==="meal.save"||type==="prep.status"||type==="meal.leftovers"))setUndoId(last.id);return true;}catch(e){notify(e instanceof Error?e.message:"Unable to save. Please try again.");return false;}}
  /** A note on a calendar card shows for two seconds, failures included; a
   * newer note replaces it and starts its own two seconds. */
  function flashNote(note:CardNote){
    const seq=++noteSeq.current;setCardNote(note);
    window.setTimeout(()=>{if(noteSeq.current===seq)setCardNote(null);},2000);
  }
  /** A quick action on a calendar card; the outcome shows on the card (with
   * Undo for done/skipped, and done in green). */
  async function cardAction(meal:Meal,type:string,payload:Record<string,unknown>,done?:string,success=false){
    const seq=++noteSeq.current;
    try{
      const result=await kitchen.send(type,payload,state.revision);
      if(!done){if(noteSeq.current===seq)setCardNote(null);return;}
      flashNote({mealId:meal.id,text:done,undo:result.state.audit.at(-1)?.id,success});
    }catch(e){flashNote({mealId:meal.id,text:failure(e,"Unable to save. Please try again."),error:true});}
  }
  async function undoCard(note:CardNote){
    if(!note.undo)return;const seq=++noteSeq.current;
    try{await kitchen.send("change.undo",{auditId:note.undo},state.revision);if(noteSeq.current===seq)setCardNote(null);}
    catch(e){flashNote({mealId:note.mealId,text:failure(e,"Unable to undo."),error:true});}
  }
  function select(meal:Meal,replace=false){if(dirty){notify("Save or discard your drawer edits before opening another meal.");return;}setOpened({id:meal.id,replace});router.push(href(page,{plan:plan?.id,meal:meal.id,step:params.get("step")}));}
  function add(day:string,slot:MealSlot){if(dirty)return;const meal:Meal={id:uid(),day,slot,components:[{id:uid(),name:"",type:"Other",portions:state.settings.people}],activeMinutes:0,elapsedMinutes:0,steps:[],status:"planned",liked:false,locked:false};setOpened(page==="plan"?{id:meal.id,fresh:meal,replace:true}:{id:meal.id,edit:true,fresh:meal});}
  /** In a draft on the plan page, an empty slot the household chose to cook
   * can be filled from recipes; a slot left out stays "Not Planning". */
  function slotState(day:string,slot:MealSlot):"add"|"off"|"none"{
    if(page!=="plan"||plan?.status!=="draft")return "none";
    return setupChoices.choices.slots[slotKey(day,slot)]===false?"off":"add";
  }
  async function saveMeal(meal:Meal,original:Meal,recipes:Recipe[]=[]){
    const current=plan?.meals.find(m=>m.id===meal.id);
    if(current&&JSON.stringify(current)!==JSON.stringify(original)){notify("This meal changed while you were editing. Close and reopen it before saving.");return false;}
    if(plan){const saved=await send("meal.save",{planId:plan.id,meal,recipes});if(saved&&opened?.fresh){setOpened({id:meal.id});router.push(href(page,{plan:plan.id,meal:meal.id,step:params.get("step")}));}return saved;}
    const draft:WeeklyPlan={id:uid(),weekStart:week,status:"draft",version:1,prompt:"",meals:[],prep:[],chat:[]};
    draft.meals.push(meal);const saved=await send("plan.save",{plan:draft,recipes});if(saved){setDirty(false);setOpened(null);router.push(href(page,{plan:draft.id}));}return saved;
  }
  async function generate(prompt:string):Promise<string|null>{
    if(dirty||aiBusy||generatingSince!==null)return null;
    if(!demo){
      // Drafting takes minutes; it runs on the server and this page follows it.
      try{const started=await api<{task:AiTask}>("/api/v1/kitchen/ai-tasks/generate",{method:"POST",body:JSON.stringify({weekStart:week,prompt,expectedRevision:state.revision,operationId:uid()})});generationOrigins.current.set(started.task.id,{planId:selectedPlanId,step:selectedStep});genTask.set(started.task);return null;}
      catch(e){if(e instanceof ApiError&&e.status===409)void kitchen.reload();return e instanceof Error?e.message:"Generation failed. Your saved plan is unchanged.";}
    }
    setAiBusy(true);setDemoSince(startedNow());
    try{
      {const template=clone(createDemoState().plans[0]);template.id=uid();template.weekStart=week;template.status="draft";template.prompt=prompt;template.chat=[];template.meals=template.meals.map((m,i)=>({...m,day:weekDays(week)[Math.floor(i/3)]}));const confirmed=options.find(p=>p.status==="confirmed");if(confirmed){template.basePlanId=confirmed.id;template.baseVersion=confirmed.version;template.meals=template.meals.map(m=>{const old=confirmed.meals.find(x=>x.id===m.id);return old&&(old.locked||old.status!=="planned")?clone(old):m;});template.prep=clone(confirmed.prep);}const ok=await send("plan.save",{plan:template});if(!ok)return "Unable to create the demo draft.";navigate("plan",undefined,week,null,"adjust");return null;}
    }catch(e){return e instanceof Error?e.message:"Generation failed. Your saved plan is unchanged.";}finally{setAiBusy(false);setDemoSince(null);}
  }
  async function dismissGeneration(){
    const task=genTask.task;if(!task)return;
    try{await genTask.dismiss(task.id);}catch{notify("Unable to dismiss this message. Please try again.");}
  }
  /** Ask Stu. Stu acts on what was asked: the referenced meals, else the meals
   * the message names, else the whole week. Only a whole-week rebuild may get
   * one question back (with answers to tap); the answer is always acted on.
   * The message joins the conversation at once and Stu answers on the server;
   * throws only when the message could not be sent. */
  async function chat(text:string,answering:boolean):Promise<void>{
    if(!plan)throw new Error("There is no plan to adjust yet.");
    if(!demo){
      const start=(revision:number)=>api<{task:AiTask;state:KitchenState}>("/api/v1/kitchen/ai-tasks/chat",{method:"POST",body:JSON.stringify({planId:plan.id,message:text,mealIds:contexts,expectedRevision:revision,answeringClarification:answering})});
      let started;
      try{started=await start(state.revision);}
      catch(e){
        // Stu's last answer (or another tab) moved the workspace on: catch up once.
        if(!(e instanceof ApiError&&e.status===409&&/Workspace changed/.test(e.message)))throw e;
        const fresh=await api<KitchenState>("/api/v1/kitchen");kitchen.accept(fresh);started=await start(fresh.revision);
      }
      kitchen.accept(started.state);chatTask.set(started.task);return;
    }
    const named=contexts.length?plan.meals.filter(m=>contexts.includes(m.id)):plan.meals.filter(m=>(/breakfast|早饭|早餐/i.test(text)&&m.slot==="breakfast")||(/Wednesday|周三|星期三/i.test(text)&&m.day===weekDays(week)[2]&&m.slot==="dinner"));
    const wholeWeek=!named.length,rebuild=/regenerat|redo|start over|whole week|entire week|重新|整周|一周/i.test(text);
    let proposal:ChatProposal;
    if(wholeWeek&&rebuild&&!answering)proposal={reply:"Simulation: before I rebuild the week, what should change most?",scope:"",meals:[],needsClarification:true,options:["Keep what we liked, refresh the rest","More vegetables","Quicker weeknight dinners"]};
    else{
      const scope=(wholeWeek?plan.meals:named).filter(m=>!m.locked&&m.status==="planned"&&m.included!==false);
      const swapVegetables=wholeWeek||/broccoli|西兰花|vegetable|蔬菜/i.test(text);
      const meals=scope.map(m=>{const next=clone(m);if(swapVegetables){next.components=next.components.map(c=>c.type==="Vegetables"?{id:c.id,name:"蒸胡萝卜",type:"Vegetables",portions:c.portions}:c);next.steps=["Gather the ingredients and cut the carrots.","Steam the carrots until tender while reheating the other components.","Plate, serve and tidy up."];}else{const r=state.recipes.find(r=>r.id==="recipe-toast")!;next.components=[{id:uid(),name:r.name,type:r.type,portions:state.settings.people,recipeId:r.id}];next.activeMinutes=r.activeMinutes;next.elapsedMinutes=r.elapsedMinutes;next.steps=r.steps;}return next;}).filter(next=>JSON.stringify(next.components)!==JSON.stringify(plan.meals.find(m=>m.id===next.id)?.components));
      proposal={reply:meals.length?`Simulation: here is what would change in ${meals.length} meal${meals.length===1?"":"s"}.`:"Simulation: nothing there can change — those meals are locked, done or not planned.",scope:meals.map(m=>m.id).join(","),meals,needsClarification:false,options:[]};
    }
    const ids=proposal.meals.map(m=>m.id);
    await kitchen.send("plan.chat",{planId:plan.id,messages:[{id:uid(),role:"user",text,mealIds:contexts},{id:uid(),role:"assistant",text:proposal.reply,mealIds:ids}]});
    writeDemoTurn(JSON.stringify({id:uid(),status:"done",resolution:"open",answering,result:proposal,error:null,base:planSnapshot(plan)} satisfies ChatTurn));
  }
  /** Save Stu's open suggestion into the plan — refused if the plan changed
   * since Stu made it. */
  async function applyTurn(){
    if(!plan||!turn?.result)throw new Error("There is nothing to apply.");
    if(!demo){
      const saved=await api<CommandResult&{planId:string}>(`/api/v1/kitchen/ai-tasks/${turn.id}/apply`,{method:"POST"});
      kitchen.accept(saved.state);if(chatTask.task)chatTask.set({...chatTask.task,resolution:"applied"});
      if(saved.planId!==plan.id)navigate("plan",undefined,week,saved.planId,"adjust");
      return;
    }
    if(turn.base!==planSnapshot(plan))throw new Error("This plan changed after Stu’s suggestion. Ask again before applying.");
    const proposal=turn.result;
    const draft={...clone(plan),id:plan.status==="confirmed"?uid():plan.id,status:"draft" as const,...(plan.status==="confirmed"?{basePlanId:plan.id,baseVersion:plan.version}:{})};
    draft.meals=draft.meals.map(m=>proposal.meals.find(x=>x.id===m.id)??m);if(proposal.prep)draft.prep=clone(proposal.prep);
    await kitchen.send("plan.save",{plan:draft});
    writeDemoTurn(JSON.stringify({...turn,resolution:"applied"}));
    if(draft.id!==plan.id)navigate("plan",undefined,week,draft.id,"adjust");
  }
  async function keepTurn(){
    if(!turn)return;
    if(!demo){chatTask.set((await api<{task:AiTask}>(`/api/v1/kitchen/ai-tasks/${turn.id}/dismiss`,{method:"POST"})).task);return;}
    writeDemoTurn(JSON.stringify({...turn,resolution:"dismissed"}));
  }
  /** "I'll plan myself" on an empty week: an empty draft to fill by hand. */
  async function planMyself(){
    const draft:WeeklyPlan={id:uid(),weekStart:week,status:"draft",version:1,prompt:"",meals:[],prep:[],chat:[]};
    await kitchen.send("plan.save",{plan:draft});
    navigate("plan",undefined,week,null,"adjust");
  }
  function reference(meal:Meal,goToChat:boolean){
    if(dirty){notify("Save or discard your drawer edits before leaving this meal.");return;}
    chatRefs.add(meal.id);
    if(!goToChat)return;
    requestChatFocus();
    if(page==="plan"){setOpened(null);setFocusTick(tick=>tick+1);if(params.get("meal"))router.push(href("plan",{plan:plan?.id,step:params.get("step")}));}
    else navigate("plan",undefined,week,plan?.id,"adjust");
  }
  /** Editing a confirmed week works on a copy based on it; saving that copy
   * confirms it in the original's place. An edit already in progress for this
   * version of the plan is reopened rather than duplicated. */
  async function editConfirmed(){
    if(!plan||plan.status!=="confirmed")return;
    const open=[...state.plans].reverse().find(p=>p.weekStart===week&&p.status==="draft"&&p.basePlanId===plan.id&&p.baseVersion===plan.version);
    if(open){navigate("plan",undefined,week,open.id,"adjust");return;}
    const copy:WeeklyPlan={...clone(plan),id:uid(),status:"draft",basePlanId:plan.id,baseVersion:plan.version};
    await kitchen.send("plan.save",{plan:copy});navigate("plan",undefined,week,null,"adjust");
  }
  async function toggleGoal(id:string,enabled:boolean){
    await kitchen.send("settings.save",{settings:{...state.settings,guidance:state.settings.guidance.map(g=>g.id===id?{...g,enabled}:g)}});
  }
  /** Saves the week's note, then splits it into preferences kept in Settings.
   * Returns how many were added; throws so the setup can say what failed. */
  async function savePreferences(text:string):Promise<number>{
    const saved=await kitchen.send("planning.prompt",{weekStart:week,prompt:text});
    if(!text.trim())return 0;
    const current=saved.state.settings;
    const items=demo?splitDemoPreferences(text,current.guidance):(await api<{preferences:{title:string;content:string}[]}>("/api/v1/kitchen/preferences",{method:"POST",body:JSON.stringify({text})})).preferences;
    if(!items.length)return 0;
    await kitchen.send("settings.save",{settings:{...current,guidance:[...current.guidance,...items.map(item=>({id:uid(),title:item.title,content:item.content,enabled:true,version:1}))]}});
    return items.length;
  }
  async function confirm():Promise<string|null>{
    if(!plan)return "There is no plan to confirm.";
    try{
      let revision=state.revision;
      for(const change of pendingWrites(plan,setupChoices.choices)){const result=await kitchen.send("meal.include",{planId:plan.id,mealId:change.mealId,included:change.included});revision=result.state.revision;}
      if(demo){
        setDemoConfirmSince(Date.now());
        try{await new Promise(resolve=>window.setTimeout(resolve,1000));await kitchen.send("plan.confirm",{id:plan.id});setupChoices.clear();navigate("plan",undefined,week,plan.id,"shopping");}
        finally{setDemoConfirmSince(null);}
      }else{
        const response=await api<{task:AiTask}>("/api/v1/kitchen/ai-tasks/fulfillment",{method:"POST",body:JSON.stringify({planId:plan.id,expectedRevision:revision})});
        fulfillment.set(response.task);
      }
      return null;
    }catch(e){return e instanceof Error?e.message:"Unable to confirm. Please try again.";}
  }
  const savedWorkflow=state.weeklyPrompts?.find(entry=>entry.weekStart===week)?.workflow;
  const currentStep=planningStep(plan,params.get("step"),savedWorkflow);
  const prepFocus=savedWorkflow?.planId===plan?.id?savedWorkflow?.focus??"shopping":"shopping";
  /** Remembers the step for next time, behind the scenes: the latest choice
   * wins, and a save that finds another change in flight waits its turn.
   * Resolves with the error, if saving failed. */
  function rememberStep(weekStart:string,workflow:{planId?:string;step:PlanStep;focus:"shopping"|"prep"}){
    stepWanted.current={weekStart,workflow};
    if(!stepSaving.current){
      stepSaving.current=(async()=>{
        try{
          while(stepWanted.current){
            const next=stepWanted.current;stepWanted.current=null;
            for(let attempt=0;;attempt+=1){
              try{await kitchen.send("planning.workflow",next);break;}
              catch(e){if(attempt<40&&e instanceof Error&&/Please wait/.test(e.message)){await new Promise(resolve=>window.setTimeout(resolve,150));continue;}throw e;}
            }
          }
          return null;
        }catch(e){stepWanted.current=null;return e instanceof Error?e:new Error("Unable to save planning progress.");}
        finally{stepSaving.current=null;}
      })();
    }
    return stepSaving.current;
  }
  /** Moving between steps is instant: the step is in the address, so the page
   * switches at once and the step is remembered behind it. (Waiting for that
   * save first made every switch take over a second.) */
  async function changeStep(step:PlanStep,focus:"shopping"|"prep"=prepFocus,move=true){
    if(dirty)throw new Error("Save or discard your drawer edits before leaving this meal.");
    const saved=rememberStep(week,{...(plan?{planId:plan.id}:{}),step,focus});
    if(move){navigate("plan",undefined,week,plan?.id,step);void saved.then(error=>{if(error)setWorkflowError(failure(error,"Unable to save planning progress."));});return;}
    // The shopping/prep panels stay on this page and undo their switch on failure.
    const error=await saved;if(error)throw error;
  }
  async function goStep(step:PlanStep,focus:"shopping"|"prep"=prepFocus){
    setWorkflowError(null);
    try{await changeStep(step,focus);}catch(e){setWorkflowError(failure(e,"Unable to save planning progress."));}
  }
  /** A recipe has its own page under the library; null goes back to the list. */
  function openRecipe(id:string|null){
    if(dirty){notify("Save or discard your drawer edits before leaving this meal.");return;}
    setOpened(null);setRecipeId(null);setMessage("");
    router.push(demo?`/demo?page=recipes${id?`&recipe=${encodeURIComponent(id)}`:""}`:id?`/recipes/${encodeURIComponent(id)}`:"/recipes");
  }
  const shared={state,plan,send,notify,navigate,demo};
  const feedback=message&&<div className="kw-toast" role="status"><Check size={16}/><span>{message}</span>{undoId&&<button onClick={()=>void send("change.undo",{auditId:undoId}).then(ok=>{if(ok)setUndoId(null);})}>Undo last change</button>}<button className="kw-icon" aria-label="Dismiss message" onClick={()=>setMessage("")}>×</button></div>;
  const calendar=<CalendarGrid onUnlock={meal=>void cardAction(meal,"meal.lock",{planId:plan?.id,mealId:meal.id,locked:false},"Weekly meal unlocked")} week={week} plan={view} state={state} referencedIds={page==="plan"?contexts:[]} selectedId={selected?.id??null} onSelect={select} onReplace={meal=>select(meal,true)} onReference={plan?.status==="confirmed"?undefined:meal=>reference(meal,page!=="plan")} onAdd={add} onStatus={(meal,status)=>void cardAction(meal,"meal.status",{planId:plan?.id,mealId:meal.id,status},status==="completed"?"Done ✓":"Skipped",status==="completed")} onLike={meal=>void cardAction(meal,"meal.like",{planId:plan?.id,mealId:meal.id,liked:!meal.liked})} onInclude={(meal,included)=>{if(plan?.status==="draft")setupChoices.setSlot(meal.day,meal.slot,included);else void cardAction(meal,"meal.include",{planId:plan?.id,mealId:meal.id,included});}} onAddToMeal={meal=>select(meal,false)} planning={page==="plan"} slotState={slotState} note={cardNote} onUndo={note=>void undoCard(note)} onDismissNote={()=>setCardNote(null)}/>;
  return <div ref={workspaceRef} className={`kw-workspace kw-page-${page} ${selected||recipe?"has-drawer":""}`}>
    <header className="kw-navigation">
      <a className="kw-brand" href={demo?"/demo":"/calendar"} onClick={event=>{if(dirty){event.preventDefault();notify("Save or discard your drawer edits before leaving this meal.");}}}><Image src="/assets/figma/stu-logo.png" alt="Stu baby logo" width={44} height={44}/><div><strong>Stu</strong><small>FAMILY TABLE</small></div></a>
      <nav aria-label="Main navigation">{([{id:"plan",label:"Plan",emoji:"📋"},{id:"calendar",label:"Calendar",emoji:"🍳"},{id:"fridge",label:"Fridge",emoji:"🧊"},{id:"recipes",label:"Recipes",emoji:"📖"}] as const).map(({id,label,emoji})=><button key={id} aria-current={page===id?"page":undefined} className={page===id||id==="plan"&&page==="prep"?"active":""} onMouseEnter={()=>router.prefetch?.(href(id,{plan:id==="plan"?"":plan?.id}))} onFocus={()=>router.prefetch?.(href(id,{plan:id==="plan"?"":plan?.id}))} onClick={()=>navigate(id,undefined,week,id==="plan"?"":undefined)}>{label}<span aria-hidden="true">{emoji}</span></button>)}</nav>
      <KitchenProfileMenu key={page} points={points} demo={demo} onNavigate={navigate} onPrefetch={next=>router.prefetch?.(href(next,{plan:plan?.id}))} onReset={()=>{if(dirty){notify("Save or discard your drawer edits before resetting.");return false;}kitchen.reset();setUndoId(null);notify("Demo reset to its original data.");return true;}}/>
    </header><main className="kw-main" aria-label={titles[page]}>
    {demo&&<span className="kw-demo-ribbon">Interactive demo · simulated AI</span>}

    {!selected&&!recipe&&feedback&&page!=="plan"&&page!=="calendar"&&<div className="kw-page-notice">{feedback}</div>}
    {kitchen.loading?<div className="kw-loading">Loading your kitchen…</div>:kitchen.unauthorized?<div className="kw-auth"><Login locale="en-US" onAuthenticated={()=>void kitchen.reload()}/></div>:kitchen.error?<div className="kw-load-error"><h2>We couldn’t load your kitchen</h2><p>{kitchen.error}</p><button className="kw-button" onClick={()=>void kitchen.reload()}>Try again</button><a href="/demo">Explore the interactive demo</a></div>:<>
      {page==="calendar"&&<header className="kw-calendar-heading"><h1 aria-label="Calendar">{"This Week's Menu! 🍳"}</h1><div className="kw-weekbar"><button className="kw-week-step" aria-label="Previous week" onClick={()=>navigate(page,undefined,shiftWeek(week,-1),"")}><span aria-hidden="true">◀</span></button><button className="kw-week-label" title="Go to this week" onClick={()=>navigate(page,undefined,defaultWeek,"")}>{weekLabel(week)}</button><button className="kw-week-step" aria-label="Next week" onClick={()=>navigate(page,undefined,shiftWeek(week,1),"")}><span aria-hidden="true">▶</span></button>{plan&&<label className={`kw-version-control ${plan.status}`}><span className="kw-version-dot" aria-hidden="true"/><span className="kw-version-caption">VERSION</span><select aria-label="Plan version" className="kw-version-select" value={plan.id} onChange={e=>navigate(page,undefined,week,e.target.value)}>{options.map(p=><option value={p.id} key={p.id}>{p.status==="confirmed"?"Confirmed":"Draft"} · v{p.version}</option>)}</select><span className="kw-version-chevron" aria-hidden="true">⌄</span></label>}</div><button className="kw-button kw-prep-link" onClick={()=>plan?.status==="confirmed"?void goStep("shopping","prep"):navigate("prep")}>Shopping & Prep → 🥣</button></header>}

      {page==="calendar"&&<>{upcomingDraft&&<div className="kw-draft-banner">Next week’s plan is ready. <button onClick={()=>navigate("plan",undefined,upcomingDraft.weekStart,upcomingDraft.id)}>Review draft<ArrowRight size={14}/></button></div>}{!plan&&<div className="kw-empty-week"><CalendarBlank size={30}/><h2>A calmer week starts here</h2><p>Tell Stu what’s in your fridge and what your family likes.</p><button className="kw-button" onClick={()=>navigate("plan")}>Plan this week<ArrowRight size={16}/></button></div>}{plan?.status==="draft"&&<div className="kw-draft-banner">You’re previewing a draft. <button onClick={()=>navigate("plan")}>Review and confirm<ArrowRight size={14}/></button></div>}{calendar}</>}
      {(page!=="plan"&&(genTask.task?.status==="running"||chatTask.task?.status==="running"||readyGeneration||chatTask.task?.status==="done"&&chatTask.task.resolution==="open")||page==="plan"&&readyGeneration&&readyGeneration!==plan?.id)&&<div className="kw-panel kw-row" role="status"><span>{genTask.task?.status==="running"?"Stu is drafting your week in the background. Allow 2–7 minutes.":chatTask.task?.status==="running"?"Stu is continuing your conversation in the background.":"Stu’s result is ready to review."}</span><button className="kw-link" onClick={()=>navigate("plan",undefined,week,readyGeneration??conversationPlan?.id,"adjust")}>Open plan →</button></div>}
      {workflowError&&<p className="kw-inline-error" role="alert">{workflowError}</p>}
      {page==="plan"&&<PlanningPage week={week} choices={setupChoices.choices} onSlot={setupChoices.setSlot} onGoal={toggleGoal} onSavePreferences={savePreferences} step={currentStep} onStep={next=>changeStep(next)} onApplyFix={async meal=>{if(plan)await kitchen.send("meal.save",{planId:plan.id,meal});}} key={plan?.id??week} state={state} plan={plan} selected={contexts} onSelect={setContexts} onGenerate={generate} generatingSince={generatingSince} generationError={generationError} onDismissGenerationError={()=>void dismissGeneration()} onPlanMyself={planMyself} turn={turn} onChat={chat} onApply={applyTurn} onKeep={keepTurn} confirmingSince={confirmingSince} fulfillmentError={fulfillmentError} onConfirm={confirm} onEdit={editConfirmed} focusTick={focusTick} onCalendar={()=>navigate("calendar")} shoppingContent={<ShoppingPrepPage {...shared} notice={feedback} focus={prepFocus} onFocus={focus=>changeStep("shopping",focus,false)}/>} onPrep={()=>void goStep("shopping","shopping")} onGuidance={()=>navigate("guidance")} onWeek={delta=>navigate("plan",undefined,shiftWeek(week,delta),"")} demo={demo} busy={aiBusy||kitchen.busy}>{calendar}</PlanningPage>}
      {page==="prep"&&<PrepPage {...shared}/>}{page==="fridge"&&<FridgePage {...shared}/>}{page==="recipes"&&<RecipesPage {...shared} recipeId={demo?params.get("recipe"):routeRecipe??null} onOpenRecipe={openRecipe}/>}{page==="guidance"&&<GuidancePage {...shared}/>}{page==="knowledge"&&<KnowledgePage {...shared}/>}
    </>}
  </main>{recipe?<Drawer notice={feedback} title={recipe.name} subtitle="Recipe" onClose={()=>setRecipeId(null)} footer={<button className="kw-button secondary full" onClick={()=>setRecipeId(null)}>Back to meal</button>}><div className="kw-row"><span className="kw-pill">{recipe.servings} servings</span><span className="kw-pill">{recipe.type}</span></div><p className="kw-time">Active {recipe.activeMinutes} min · Elapsed {recipe.elapsedMinutes} min</p><section className="kw-detail-section"><h3>Ingredients</h3>{recipe.ingredients.map((i,n)=><div className="kw-stock-row" key={n}><span>{i.name}</span><span>{i.quantity} {i.unit}</span></div>)}</section><section className="kw-detail-section"><h3>Preparation</h3><ol className="kw-steps">{recipe.steps.map((s,i)=><li key={i}>{s}</li>)}</ol></section><RecipeSource source={recipe.source}/></Drawer>:selected&&<MealDrawer planning={page==="plan"} demo={demo} notice={feedback} key={`${selected.id}:${opened?.replace?"replace":"detail"}`} meal={selected} plan={plan??{id:"",weekStart:week,status:"draft",version:0,prompt:"",meals:[],prep:[],chat:[]}} state={state} initialEdit={opened?.edit} initialReplace={opened?.replace} onClose={close} onDirty={setDirty} onSave={saveMeal} onAction={send} onReference={plan?.status==="confirmed"?undefined:()=>reference(selected,true)} onRecipe={setRecipeId} busy={kitchen.busy}/>}
  </div>;
}
