import type {KitchenState,Meal,WeeklyPlan} from "./types";
const copy=<T,>(value:T):T=>JSON.parse(JSON.stringify(value)) as T;
const weekday=(meal:Meal)=>(new Date(`${meal.day}T12:00:00Z`).getUTCDay()+6)%7;
function reconcile(before:WeeklyPlan,after:WeeklyPlan){
  const demand=(p:WeeklyPlan)=>{const result=new Map<string,number>();p.meals.filter(m=>m.status!=="skipped").forEach(m=>m.components.forEach(c=>{if(c.prepId)result.set(c.prepId,(result.get(c.prepId)??0)+c.portions);}));return result;};
  const old=demand(before),next=demand(after),dependencies=new Set(after.prep.flatMap(t=>t.dependencies));
  after.prep=after.prep.flatMap(t=>{if(t.status!=="planned"||!old.get(t.id)||dependencies.has(t.id))return [t];const need=next.get(t.id)??0;if(!need)return [];const factor=need/old.get(t.id)!;return [{...t,plannedPortions:t.plannedPortions*factor,activeMinutes:t.activeMinutes*factor,elapsedMinutes:t.elapsedMinutes*factor,inputs:t.inputs.map(i=>({...i,portions:i.portions*factor}))}];});
}
/** Demo uses the same weekly rule semantics as the service. */
export function applyRecurring(state:KitchenState,plan:WeeklyPlan){
  const before=copy(plan);
  for(const rule of state.settings.recurringMeals??[]){
    const old=plan.meals.find(m=>weekday(m)===rule.weekday&&m.slot===rule.slot);
    if(old&&(old.locked||old.status!=="planned"))continue;
    const date=new Date(`${plan.weekStart}T12:00:00Z`);date.setUTCDate(date.getUTCDate()+rule.weekday);
    const ids=new Map(rule.prep.map(t=>[t.id,`recurring-${plan.id}-${rule.weekday}-${rule.slot}-${t.id}`]));
    const tasks=rule.prep.map(t=>{const need=rule.meal.components.filter(c=>c.prepId===t.id).reduce((n,c)=>n+c.portions,0),factor=need&&t.plannedPortions?need/t.plannedPortions:1;return {...copy(t),id:ids.get(t.id)!,status:"planned" as const,actualPortions:0,plannedPortions:t.plannedPortions*factor,activeMinutes:t.activeMinutes*factor,elapsedMinutes:t.elapsedMinutes*factor,liked:false,outputInventoryId:undefined,inputs:[],dependencies:t.dependencies.flatMap(d=>ids.has(d)?[ids.get(d)!]:[])};});
    plan.prep.push(...tasks.filter(t=>!plan.prep.some(p=>p.id===t.id)));
    const meal:Meal={...copy(rule.meal),id:old?.id??`recurring-${plan.id}-${rule.weekday}-${rule.slot}`,day:date.toISOString().slice(0,10),included:true,status:"planned",liked:false,locked:true,components:rule.meal.components.map(c=>({...c,inventoryId:undefined,prepId:c.prepId?ids.get(c.prepId):undefined}))};
    if(old)plan.meals[plan.meals.indexOf(old)]=meal;else plan.meals.push(meal);
  }
  reconcile(before,plan);
}
export function toggleRecurring(state:KitchenState,plan:WeeklyPlan,meal:Meal,locked:boolean){
  const base=state.plans.find(p=>p.id===plan.basePlanId);
  if(base&&base.version!==plan.baseVersion)throw new Error("Confirmed plan changed; reconcile this draft before changing weekly locks.");
  const day=weekday(meal),ids=new Set(meal.components.map(c=>c.prepId));
  state.settings.recurringMeals=(state.settings.recurringMeals??[]).filter(r=>r.weekday!==day||r.slot!==meal.slot);
  if(locked){
    if(meal.included===false)throw new Error("Include this meal before locking it every week.");
    let size=-1;while(size!==ids.size){size=ids.size;plan.prep.filter(t=>ids.has(t.id)).forEach(t=>t.dependencies.forEach(d=>ids.add(d)));}
    state.settings.recurringMeals.push({weekday:day,slot:meal.slot,meal:copy(meal),prep:copy(plan.prep.filter(t=>ids.has(t.id)))});
  }
  meal.locked=locked;
  for(const other of state.plans){
    if(other.id===plan.id)continue;
    const before=copy(other),matches=other.meals.filter(m=>weekday(m)===day&&m.slot===meal.slot);
    for(const m of matches){
      m.locked=locked&&m.status!=="planned";
      if(locked&&other.weekStart===plan.weekStart&&m.status==="planned"){
        Object.assign(m,copy(meal),{id:m.id});
        for(const t of plan.prep.filter(t=>ids.has(t.id))){const existing=other.prep.find(p=>p.id===t.id);if(!existing)other.prep.push(copy(t));else if(existing.status==="planned")Object.assign(existing,copy(t));}
      }
    }
    if(locked)applyRecurring(state,other);
    if(matches.length){reconcile(before,other);other.version++;delete other.fulfillment;}
  }
  if(base)plan.baseVersion=base.version;
}
