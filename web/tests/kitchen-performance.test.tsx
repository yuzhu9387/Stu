/** Opt-in, synthetic CPU benchmark. Run alone with KITCHEN_BENCHMARK=1.
 * React Profiler in jsdom measures rendering work, not browser paint/network. */
import { Profiler } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, vi } from "vitest";
import { writeFileSync } from "node:fs";
import { KitchenWorkspace } from "@/features/kitchen/workspace";
import { createDemoState, shiftWeek } from "@/features/kitchen/data";
import type { Page } from "@/features/kitchen/types";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }), useSearchParams: () => new URLSearchParams("week=2026-09-21&step=adjust") }));
vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), api: vi.fn() }));
const median = (values: number[]) => [...values].sort((a,b)=>a-b)[Math.floor(values.length/2)];

describe.skipIf(process.env.KITCHEN_BENCHMARK !== "1")("kitchen rendering benchmark", () => {
  it("profiles every main page and a profile-menu update using the same large fixture", async () => {
    const state = createDemoState(), template = structuredClone(state.plans[0]);
    state.plans[0].status = "draft";
    for (let i=1;i<=12;i++) state.plans.push({...structuredClone(template),id:`history-${i}`,weekStart:shiftWeek(template.weekStart,-i),meals:template.meals.map(m=>({...structuredClone(m),id:`${i}-${m.id}`,day:shiftWeek(m.day,-i)}))});
    state.recipes = Array.from({length:120},(_,i)=>({...structuredClone(state.recipes[i%state.recipes.length]),id:i<state.recipes.length?state.recipes[i].id:`recipe-${i}`}));
    state.inventory = Array.from({length:60},(_,i)=>({...structuredClone(state.inventory[i%state.inventory.length]),id:i<state.inventory.length?state.inventory[i].id:`stock-${i}`}));
    vi.mocked(api).mockImplementation(async path => path.includes("ai-tasks")?{task:null} as never:path.includes("generation-jobs")?{jobs:[]} as never:state as never);
    const results=[];
    for (const page of ["plan","calendar","fridge","recipes","guidance","knowledge","prep"] as Page[]) {
      const mount:number[]=[],update:number[]=[];
      for(let run=0;run<5;run++) {
        let timings:number[]=[];
        const view=render(<Profiler id={page} onRender={(_id,_phase,duration)=>timings.push(duration)}><KitchenWorkspace initialPage={page}/></Profiler>);
        await waitFor(()=>{if(view.container.querySelector(".kw-loading"))throw new Error("loading");});
        await act(async()=>{});
        if(run)mount.push(timings.reduce((a,b)=>a+b,0));
        timings=[];
        fireEvent.click(screen.getByRole("button",{name:"Settings and knowledge"}));
        if(run)update.push(timings.reduce((a,b)=>a+b,0));
        view.unmount();
      }
      results.push({page,initialRenderMs:+median(mount).toFixed(2),menuUpdateMs:+median(update).toFixed(2)});
    }
    const report={fixture:{recipes:120,inventory:60,weeks:13},environment:"React dev Profiler / jsdom, median of 4 runs after warmup, excludes network/paint",results};
    writeFileSync(process.env.KITCHEN_BENCHMARK_OUTPUT||"/tmp/stu-render-benchmark.json",JSON.stringify(report,null,2));
    console.info(JSON.stringify(report));
  },30000);
});
