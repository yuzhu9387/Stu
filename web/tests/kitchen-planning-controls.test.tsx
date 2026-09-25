import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { PlanningPage } from "@/features/kitchen/plan";
import { createDemoState } from "@/features/kitchen/data";
import { api } from "@/lib/api";
vi.mock("@/lib/api",()=>({api:vi.fn()}));
const mockedApi=vi.mocked(api);
beforeEach(()=>mockedApi.mockReset());
function props(){const state=createDemoState();return {state,week:"2026-09-28",plan:null,selected:[],onSelect:()=>{},step:null,onStep:()=>{},onGoal:async()=>{},onApplyFix:async()=>{},onGenerate:async()=>null,onSavePreferences:vi.fn().mockResolvedValue(2),onChat:async()=>{},onApply:async()=>{},onConfirm:async()=>null,onEdit:async()=>{},focusTick:0,choices:{slots:{}},onSlot:()=>{},onPrep:()=>{},onGuidance:()=>{},onWeek:()=>{},demo:true,busy:false,children:<div/>};}
it("saves preferences for a scheduled week before a plan exists",async()=>{
  const p=props();render(<PlanningPage {...p}/>);
  fireEvent.change(screen.getByLabelText("This week’s preferences"),{target:{value:"优先吃冰箱里的菠菜"}});
  fireEvent.click(screen.getByText("Save weekly preferences"));
  await waitFor(()=>expect(p.onSavePreferences).toHaveBeenCalledWith("优先吃冰箱里的菠菜"));
  // Saving splits the note into goals; the button reports how many were added.
  expect(await screen.findByRole("button",{name:"Saved ✓ · 2 added to goals"})).toBeDisabled();
});
it("reads persisted weekly preferences and exposes a failed generation retry",async()=>{
  const p=props();p.demo=false;Object.assign(p.state,{weeklyPrompts:[{weekStart:p.week,prompt:"下周少做鱼"}]});
  mockedApi.mockResolvedValueOnce({jobs:[{weekStart:p.week,status:"failed",attempts:3,error:"AI provider unavailable",nextAttemptAt:null}]}).mockResolvedValueOnce({message:"Retry scheduled",job:{weekStart:p.week,status:"pending",attempts:3,error:null,nextAttemptAt:null}});
  render(<PlanningPage {...p}/>);
  expect(screen.getByLabelText("This week’s preferences")).toHaveValue("下周少做鱼");
  await screen.findByText("AI provider unavailable");
  fireEvent.click(screen.getByText("Retry scheduled generation"));
  await screen.findByText("Retry scheduled");
  expect(mockedApi.mock.calls[1]).toEqual([`/api/v1/kitchen/generation-jobs/${p.week}/retry`,{method:"POST"}]);
});

it("shows the guidance versions saved with the plan, even after current guidance changes",()=>{
  const p=props();const plan=p.state.plans[0];plan.status="draft";Object.assign(plan,{guidanceSnapshot:[{id:"old-guidance",title:"Original guidance",content:"Saved old instructions",version:2,enabled:true}]});
  p.state.settings.guidance=[{id:"old-guidance",title:"Updated guidance",content:"New instructions for future plans",version:3,enabled:true}];
  render(<PlanningPage {...p} plan={plan}/>);
  fireEvent.click(screen.getByText("Details"));
  expect(screen.getByText("Original guidance · v2")).toBeVisible();
  fireEvent.click(screen.getByText("Original guidance · v2"));
  expect(screen.getByText("Saved old instructions")).toBeVisible();
  expect(screen.queryByText("New instructions for future plans")).not.toBeInTheDocument();
});

it("shows knowledge versions used for the plan after the source document changes",()=>{
  const p=props();const plan=p.state.plans[0];plan.status="draft";
  const original={id:"nutrition",title:"Saved nutrition reference",content:"Original reference text",category:"Nutrition",enabled:true,version:1,updatedAt:"2026-09-17T10:00:00Z"};
  Object.assign(plan,{knowledgeSnapshot:[original]});
  Object.assign(p.state,{knowledgeDocuments:[{...original,title:"Edited reference",content:"New content",version:2}]});
  render(<PlanningPage {...p} plan={plan}/>);
  fireEvent.click(screen.getByText("Details"));
  expect(screen.getByText("Saved nutrition reference · v1")).toBeVisible();
  fireEvent.click(screen.getByText("Saved nutrition reference · v1"));
  expect(screen.getByText("Original reference text")).toBeVisible();
  expect(screen.queryByText("New content")).not.toBeInTheDocument();
});
