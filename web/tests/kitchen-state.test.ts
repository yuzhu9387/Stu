import { describe, expect, it } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";

function command(state: ReturnType<typeof createDemoState>, type: string, payload: Record<string, unknown>, id = crypto.randomUUID()) {
  return applyDemoCommand(state, { type, payload, expectedRevision: state.revision, operationId: id }).state;
}
const stock = (s: ReturnType<typeof createDemoState>) => ["stock-meatballs", "stock-rice", "stock-broccoli"].map(id => s.inventory.find(x => x.id === id)?.portions);
describe("kitchen execution accounting", () => {
  it("records actual prep, consumes a meal once, keeps likes independent and reverses exact consumption", () => {
    let s = createDemoState();
    expect(stock(s)).toEqual([2, 6, 4]);
    s = command(s, "prep.status", {planId:"plan-demo",prepId:"prep-meatballs",status:"completed",actualPortions:3});
    expect(stock(s)).toEqual([5, 6, 4]);
    s = command(s,"meal.status",{planId:"plan-demo",mealId:"meal-2-dinner",status:"completed"});
    expect(stock(s)).toEqual([2,3,1]);
    const undoId=s.audit.at(-1)!.id;
    s = command(s,"meal.status",{planId:"plan-demo",mealId:"meal-2-dinner",status:"completed"});
    expect(stock(s)).toEqual([2,3,1]);
    s = command(s,"meal.like",{planId:"plan-demo",mealId:"meal-2-dinner",liked:true});
    expect(stock(s)).toEqual([2,3,1]);
    s = command(s,"change.undo",{auditId:undoId});
    expect(stock(s)).toEqual([5,6,4]);
    expect(s.plans[0].meals.find(m=>m.id==="meal-2-dinner")?.liked).toBe(true);
  });
  it("rejects insufficient inventory and stale revisions without changing original state", () => {
    const s=createDemoState();
    s.plans[0].meals.find(m=>m.id==="meal-2-dinner")!.components.forEach(c=>delete c.prepId);
    expect(()=>command(s,"meal.status",{planId:"plan-demo",mealId:"meal-2-dinner",status:"completed"})).toThrow(/enough|short/i);
    expect(stock(s)).toEqual([2,6,4]);
    expect(()=>applyDemoCommand(s,{type:"meal.like",payload:{},expectedRevision:99,operationId:"x"})).toThrow(/changed|revision/i);
  });
  it("skip and duplicate request do not consume inventory", () => {
    let s=createDemoState();
    s=command(s,"meal.status",{planId:"plan-demo",mealId:"meal-2-dinner",status:"skipped"},"skip-once");
    expect(stock(s)).toEqual([2,6,4]);
    const again=applyDemoCommand(s,{type:"meal.status",payload:{planId:"plan-demo",mealId:"meal-2-dinner",status:"skipped"},expectedRevision:0,operationId:"skip-once"});
    expect(stock(again.state)).toEqual([2,6,4]);
  });
  it("cannot execute a draft or erase a meal's consumed history through editing", () => {
    let s=createDemoState();
    s.plans[0].status="draft";
    expect(()=>command(s,"meal.status",{planId:"plan-demo",mealId:"meal-2-dinner",status:"completed"})).toThrow(/confirm/i);
    s=createDemoState();
    s=command(s,"meal.status",{planId:"plan-demo",mealId:"meal-0-breakfast",status:"completed"});
    expect(()=>command(s,"meal.save",{planId:"plan-demo",meal:{...s.plans[0].meals[0],day:"2026-09-24"}})).toThrow(/completed|undo/i);
  });
});

describe("demo command parity", () => {
  it("confirms a usable plan even when daily and prep time preferences are exceeded", () => {
    const s=createDemoState();s.plans[0].status="draft";
    s.settings.maxDailyActiveMinutes=1;s.settings.maxPrepMinutes=1;
    s.inventory.forEach(i=>{i.portions=100;});
    expect(command(s,"plan.confirm",{id:"plan-demo"}).plans[0].status).toBe("confirmed");
  });
  it("requires completed prep and rejects executing skipped records until undo", () => {
    let s=createDemoState();
    expect(()=>command(s,"meal.status",{planId:"plan-demo",mealId:"meal-2-dinner",status:"completed"})).toThrow(/prep/i);
    s=command(s,"meal.status",{planId:"plan-demo",mealId:"meal-0-breakfast",status:"skipped"});
    const audit=s.audit.at(-1)!;
    expect(audit).toMatchObject({undone:false,undo:{collection:"meals",entityId:"meal-0-breakfast"}});
    expect(()=>command(s,"meal.status",{planId:"plan-demo",mealId:"meal-0-breakfast",status:"completed"})).toThrow(/undo/i);
    s=command(s,"change.undo",{auditId:audit.id});
    expect(s.plans[0].meals[0].status).toBe("planned");
    expect(s.audit.find(a=>a.id===audit.id)).toMatchObject({undone:true});
  });
  it("rejects invalid status, locked edits and prep with unmet dependencies", () => {
    const s=createDemoState();const plan=s.plans[0];plan.meals[0].locked=true;
    expect(()=>command(s,"meal.save",{planId:plan.id,meal:plan.meals[0]})).toThrow(/unlock/i);
    expect(()=>command(s,"meal.status",{planId:plan.id,mealId:plan.meals[0].id,status:"invalid"})).toThrow(/status/i);
    plan.prep[0].dependencies=["missing"];
    expect(()=>command(s,"prep.status",{planId:plan.id,prepId:plan.prep[0].id,status:"completed"})).toThrow(/prerequisite/i);
  });
  it("rejects undo after dependent consumption or direct stock edits", () => {
    let s=command(createDemoState(),"prep.status",{planId:"plan-demo",prepId:"prep-meatballs",status:"completed",actualPortions:3});
    const id=s.audit.at(-1)!.id;
    const edited=command(s,"inventory.save",{item:{...s.inventory[0],location:"Other shelf"}});
    expect(()=>command(edited,"change.undo",{auditId:id})).toThrow(/stock changed/i);
    s=command(s,"meal.status",{planId:"plan-demo",mealId:"meal-2-dinner",status:"completed"});
    expect(()=>command(s,"change.undo",{auditId:id})).toThrow(/dependent/i);
  });
  it("stores chat messages together and validates meal references", () => {
    const s=createDemoState();const messages=[{id:"user",role:"user",text:"Change dinner",mealIds:["meal-2-dinner"]},{id:"assistant",role:"assistant",text:"Here is a proposal.",mealIds:["meal-2-dinner"]}];
    expect(command(s,"plan.chat",{planId:"plan-demo",messages}).plans[0].chat.slice(-2)).toEqual(messages);
    expect(()=>command(s,"plan.chat",{planId:"plan-demo",messages:[{...messages[0],mealIds:["missing"]}]})).toThrow(/reference/i);
  });
  it("does not debit fridge stock for a fresh recipe without stock references", () => {
    const s=createDemoState();const result=command(s,"meal.status",{planId:"plan-demo",mealId:"meal-0-breakfast",status:"completed"});
    expect(stock(result)).toEqual(stock(s));
  });
});
