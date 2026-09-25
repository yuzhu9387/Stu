import { describe, expect, it } from "vitest";
import { prepSchedule, prepUnavailable, projectedMealShortages, scheduleTasks } from "@/features/kitchen/schedule";
import { createDemoState } from "@/features/kitchen/data";
describe("conservative prep scheduling", () => {
  it("serializes active work, overlaps waiting, and reserves shared equipment", () => {
    const schedule = scheduleTasks([{ id: "a", activeMinutes: 10, elapsedMinutes: 60, equipment: ["oven"] }, { id: "b", activeMinutes: 15, elapsedMinutes: 20 }, { id: "c", activeMinutes: 5, elapsedMinutes: 30, equipment: ["oven"] }]);
    expect(schedule.tasks.map(t => t.startMinutes)).toEqual([0, 10, 60]); expect(schedule.activeMinutes).toBe(30); expect(schedule.elapsedMinutes).toBe(90); expect(schedule.waitMinutes).toBe(60);
  });
  it("orders dependencies and rejects missing timing", () => {
    expect(scheduleTasks([{ id: "b", activeMinutes: 5, elapsedMinutes: 10, dependencies: ["a"] }, { id: "a", activeMinutes: 2, elapsedMinutes: 20 }]).tasks.map(t => t.startMinutes)).toEqual([0, 20]);
    expect(() => scheduleTasks([{ id: "a", activeMinutes: 1, elapsedMinutes: 2, dependencies: ["b"] }])).toThrow(/dependencies/);
    expect(() => scheduleTasks([{ id: "a", activeMinutes: 0, elapsedMinutes: 0 }])).toThrow(/timing/);
    expect(() => scheduleTasks([{ id: "a", activeMinutes: 2, elapsedMinutes: 1 }])).toThrow(/timing/);
  });
  it("checks combined input quantities before execution", () => {
    const state = createDemoState(); const plan = state.plans[0]; const task = plan.prep[0];
    task.inputs = [{ inventoryId: "stock-meatballs", portions: 2 }, { inventoryId: "stock-meatballs", portions: 1 }];
    expect(prepUnavailable(state, plan, task).join(" ")).toMatch(/1 more portions/);
  });
  it("allocates stock once in day order and links the affected meal", () => {
    const state = createDemoState(); const plan = state.plans[0];
    plan.prep = []; plan.meals = plan.meals.slice(0, 2).map((meal, index) => ({ ...meal, id: `test-${index}`, day: `2026-09-${21 + index}`, status: "planned", components: [{ id: `c-${index}`, name: "Meatballs", type: "Protein", portions: 2, inventoryId: "stock-meatballs" }] }));
    const shortages = projectedMealShortages(state, plan);
    expect(shortages).toHaveLength(1); expect(shortages[0].meal.id).toBe("test-1"); expect(shortages[0].missing[0].portions).toBe(2); expect(state.inventory.find(i => i.id === "stock-meatballs")?.portions).toBe(2);
  });
});

it("separates baking passive tails while preserving shared-device blocking", () => {
  const state=createDemoState();const plan=state.plans[0];const base=plan.prep[0];
  plan.prep=[{...base,id:"bread",recipeId:undefined,type:"Baking",activeMinutes:20,elapsedMinutes:360,equipment:["oven"],dependencies:[]},{...base,id:"soup",recipeId:undefined,type:"Other",activeMinutes:30,elapsedMinutes:60,equipment:["pot"],dependencies:[]}];
  expect(prepSchedule(state,plan)).toMatchObject({ordinaryReadyMinutes:80,activeMinutes:50,elapsedMinutes:360,bakingWaitMinutes:280});
  plan.prep[1].equipment=["oven"];
  expect(prepSchedule(state,plan).ordinaryReadyMinutes).toBe(420);
  plan.prep=plan.prep.slice(0,1);
  expect(prepSchedule(state,plan).bakingWaitMinutes).toBe(340);
});

it("uses free equipment while another ready task waits for the oven",()=>{
  const result=scheduleTasks([
    {id:"a",activeMinutes:10,elapsedMinutes:90,equipment:["oven"]},
    {id:"b",activeMinutes:10,elapsedMinutes:20,equipment:["oven"]},
    {id:"c",activeMinutes:10,elapsedMinutes:90,equipment:["pot"]},
  ]);
  expect(result.tasks.map(t=>[t.id,t.startMinutes])).toEqual([["a",0],["c",10],["b",90]]);
  expect(result.elapsedMinutes).toBe(110);
});
