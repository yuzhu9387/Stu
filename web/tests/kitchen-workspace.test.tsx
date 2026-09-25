import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KitchenWorkspace } from "@/features/kitchen/workspace";
import { createDemoState } from "@/features/kitchen/data";
import { useKitchen } from "@/features/kitchen/store";
import { api, ApiError } from "@/lib/api";
import type { KitchenState } from "@/features/kitchen/types";

const nav=vi.hoisted(()=>({query:"",push:vi.fn(),listeners:new Set<()=>void>()}));
vi.mock("next/navigation",async()=>{
  const {useSyncExternalStore}=await import("react");
  return {
    useSearchParams:()=>new URLSearchParams(useSyncExternalStore((listener)=>{nav.listeners.add(listener);return()=>{nav.listeners.delete(listener);};},()=>nav.query)),
    useRouter:()=>({push:(url:string)=>{nav.push(url);nav.query=url.split("?")[1]||"";nav.listeners.forEach(listener=>listener());}}),
  };
});
vi.mock("@/lib/api",async importOriginal=>({...await importOriginal<typeof import("@/lib/api")>(),api:vi.fn()}));
const mockedApi=vi.mocked(api);
beforeEach(()=>{nav.query="week=2026-09-21&plan=plan-demo";nav.push.mockClear();mockedApi.mockReset();});
const dinner="meal-2-dinner";

it("does not resurrect an older generated draft after a newer plan was confirmed", async () => {
  const state=createDemoState(), old=structuredClone(state.plans[0]);old.id="old-generated";old.status="draft";
  state.plans.unshift(old);nav.query="week=2026-09-21";
  const task={id:"old-task",kind:"generate",status:"done",resolution:"open",weekStart:"2026-09-21",result:{planId:old.id},createdAt:new Date().toISOString(),now:new Date().toISOString()};
  mockedApi.mockImplementation(async(path)=>{
    if(path.includes("/latest?kind=generate"))return {task} as never;
    if(path.endsWith("/dismiss"))return {task:{...task,resolution:"dismissed"}} as never;
    if(path.includes("/ai-tasks/"))return {task:null} as never;
    return structuredClone(state) as never;
  });
  render(<KitchenWorkspace initialPage="plan"/>);await loaded();
  await waitFor(()=>expect(mockedApi.mock.calls.some(([path])=>path.endsWith("/old-task/dismiss"))).toBe(true));
  expect(nav.push).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Ask Stu to adjust your plan")).not.toBeInTheDocument();
});

it("opens and acknowledges a new draft that finished while the page was closed", async () => {
  const state=createDemoState();state.plans[0].status="draft";nav.query="week=2026-09-21&step=preferences";
  const task={id:"ready-task",kind:"generate",status:"done",resolution:"open",weekStart:"2026-09-21",result:{planId:state.plans[0].id},createdAt:new Date().toISOString(),now:new Date().toISOString()};
  mockedApi.mockImplementation(async(path)=>{
    if(path.includes("/latest?kind=generate"))return {task} as never;
    if(path.endsWith("/dismiss"))return {task:{...task,resolution:"dismissed"}} as never;
    if(path.includes("/ai-tasks/"))return {task:null} as never;
    return structuredClone(state) as never;
  });
  render(<KitchenWorkspace initialPage="plan"/>);await loaded();
  await screen.findByLabelText("Ask Stu to adjust your plan");
  await waitFor(()=>expect(mockedApi.mock.calls.some(([path])=>path.endsWith("/ready-task/dismiss"))).toBe(true));
  expect(new URLSearchParams(nav.query).get("step")).toBe("adjust");
});

it("keeps an explicit plan selected when another tab's generation finishes", async () => {
  const state=createDemoState();state.plans[0].status="draft";
  let done=false;
  const task={id:"other-tab",kind:"generate",status:"running",resolution:"open",weekStart:"2026-09-21",result:null,createdAt:new Date().toISOString(),now:new Date().toISOString()};
  mockedApi.mockImplementation(async(path)=>{
    if(path.includes("/latest?kind=generate")||path.endsWith("/ai-tasks/other-tab"))return {task:done?{...task,status:"done",result:{planId:"new-draft"}}:task} as never;
    if(path.includes("/ai-tasks/"))return {task:null} as never;
    return structuredClone(state) as never;
  });
  render(<KitchenWorkspace initialPage="plan"/>);await loaded();
  await screen.findByText(/Stu is drafting your week/);
  state.plans.push({...structuredClone(state.plans[0]),id:"new-draft"});state.revision++;done=true;
  fireEvent(window,new Event("focus"));
  await screen.findByText("Stu’s result is ready to review.");
  expect(nav.push).not.toHaveBeenCalled();
  expect(new URLSearchParams(nav.query).get("plan")).toBe("plan-demo");
  expect(mockedApi.mock.calls.some(([path])=>path.endsWith("/dismiss"))).toBe(false);
});
async function loaded(){await screen.findByRole("region",{name:"Weekly meal calendar"});}

it("shows failed prep commands inside the shopping and prep stage", async () => {
  const state=createDemoState(),plan=state.plans[0];
  state.weeklyPrompts=[{weekStart:plan.weekStart,prompt:"",workflow:{planId:plan.id,step:"shopping",focus:"prep"}}];
  mockedApi.mockImplementation(async(path,options)=>{
    if(path.includes("/ai-tasks/"))return {task:null} as never;
    if(options?.method==="POST")throw new Error("Stock changed; refresh before completing prep.");
    return structuredClone(state) as never;
  });
  render(<KitchenWorkspace initialPage="plan"/>);
  await screen.findByRole("region",{name:"Shopping and prep"});
  fireEvent.click(screen.getByRole("button",{name:"Mark prepared"}));
  await waitFor(()=>expect(screen.getByRole("status")).toHaveTextContent("Stock changed; refresh before completing prep."));
  expect(screen.getByRole("status").closest(".kw-prep-feedback")).not.toBeNull();
});
function store(){return JSON.parse(localStorage.getItem("stu-kitchen-demo-v1")!) as KitchenState;}
/** The demo week as a draft: chat and analysis are part of adjusting one. */
function seedDraft(){const state=createDemoState();state.plans[0].status="draft";localStorage.setItem("stu-kitchen-demo-v1",JSON.stringify(state));}

describe("kitchen workspace navigation and concurrency",()=>{
  it("opens replacement directly from a calendar card and protects unsaved edits",async()=>{
    seedDraft();
    render(<KitchenWorkspace demo/>);await loaded();
    fireEvent.click(screen.getByLabelText(/^Replace Wed.*dinner$/));
    expect(screen.getByText("Choose what to replace. The rest of your week stays as planned.")).toBeVisible();
    fireEvent.click(screen.getByRole("button",{name:/牛奶燕麦粥.*Carbs/}));
    fireEvent.click(screen.getByLabelText(/^Reference Tue.*dinner in chat$/));
    expect(await screen.findByText("Save or discard your drawer edits before leaving this meal.")).toBeVisible();
    expect(new URLSearchParams(nav.query).get("meal")).toBe(dinner);
    fireEvent.click(screen.getByLabelText("Close drawer"));
    fireEvent.click(screen.getByText("Discard changes"));
    fireEvent.click(screen.getByLabelText(/^Reference Wed.*dinner in chat$/));
    await screen.findByLabelText("Ask Stu to adjust your plan");
    // Only Wednesday was referenced — the attempt while the drawer was dirty
    // added nothing — and references no longer ride in the URL.
    expect(screen.getAllByLabelText("Remove dinner reference")).toHaveLength(1);
    expect(new URLSearchParams(nav.query).has("ref")).toBe(false);
  });

  it("discards a dirty deep-linked drawer and removes meal from its URL",async()=>{
    nav.query+=`&meal=${dinner}`;render(<KitchenWorkspace demo/>);await loaded();
    fireEvent.click(screen.getByLabelText("Edit meal"));
    fireEvent.change(screen.getAllByLabelText("Portions")[0],{target:{value:"2"}});
    fireEvent.click(screen.getByLabelText("Close drawer"));
    fireEvent.click(screen.getByText("Discard changes"));
    await waitFor(()=>expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(new URLSearchParams(nav.query).has("meal")).toBe(false);
    expect(store().plans[0].meals.find(m=>m.id===dinner)?.components[0].portions).toBe(3);
  });

  it("keeps a meal reference across route remount and focuses chat without sending",async()=>{
    seedDraft();
    nav.query+=`&meal=${dinner}`;
    const view=render(<KitchenWorkspace demo/>);await loaded();
    fireEvent.click(screen.getByText("Reference in chat"));
    // Asking to reference in chat takes you there once, and focuses the box.
    await waitFor(()=>expect(screen.getByLabelText("Ask Stu to adjust your plan")).toHaveFocus());
    view.unmount();render(<KitchenWorkspace demo/>);await loaded();
    // The reference survives a remount; the one-off move to the chat does not.
    expect(screen.getByLabelText("Remove dinner reference")).toBeVisible();
    expect(screen.getByLabelText("Ask Stu to adjust your plan")).not.toHaveFocus();
    expect(store().plans[0].chat).toHaveLength(0);
  });

  it("rejects applying a proposal after an intervening meal change",async()=>{
    seedDraft();
    nav.query+=`&page=plan`;render(<KitchenWorkspace demo/>);await loaded();
    // ⌘-click references the meal without opening it or leaving the page.
    fireEvent.click(screen.getByLabelText(/^Open Wed.*dinner$/),{metaKey:true});
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Remove dinner reference")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Ask Stu to adjust your plan"),{target:{value:"Make this simpler"}});
    fireEvent.click(screen.getByLabelText("Send plan request"));
    await screen.findByRole("button",{name:"Apply changes"});
    fireEvent.click(screen.getByLabelText(/^Open Wed.*dinner$/));
    fireEvent.click(screen.getByRole("button",{name:"Lock this meal every week"}));
    await waitFor(()=>expect(store().plans[0].meals.find(m=>m.id===dinner)?.locked).toBe(true));
    fireEvent.click(screen.getByLabelText("Close drawer"));
    fireEvent.click(screen.getByRole("button",{name:"Apply changes"}));
    // Said in the chat, not as a page banner.
    expect(await screen.findByRole("alert")).toHaveTextContent("This plan changed after Stu’s suggestion. Ask again before applying.");
    expect(screen.getByRole("alert").closest(".kw-chat")).not.toBeNull();
    expect(store().plans).toHaveLength(1);
  });

  it("does not overwrite a drawer meal changed by a background reload",async()=>{
    let server=createDemoState();nav.query+=`&meal=${dinner}`;
    mockedApi.mockImplementation(async()=>structuredClone(server) as never);
    render(<KitchenWorkspace/>);await loaded();
    fireEvent.click(screen.getByLabelText("Edit meal"));
    fireEvent.change(screen.getAllByLabelText("Portions")[0],{target:{value:"2"}});
    server=structuredClone(server);server.revision++;server.plans[0].meals.find(m=>m.id===dinner)!.components[0].portions=4;
    fireEvent(window,new Event("focus"));
    await waitFor(()=>expect(mockedApi.mock.calls.filter(([path])=>path==="/api/v1/kitchen")).toHaveLength(2));
    await act(async()=>{});
    fireEvent.click(screen.getByText("Save changes"));
    await screen.findByText("This meal changed while you were editing. Close and reopen it before saving.");
    expect(mockedApi.mock.calls.every(([,options])=>options?.method!=="POST")).toBe(true);
  });

  it("retains a newer mutation when an older reload arrives late",async()=>{
    const initial=createDemoState();initial.revision=5;
    mockedApi.mockResolvedValueOnce(initial);
    const hook=renderHook(()=>useKitchen(false));await waitFor(()=>expect(hook.result.current.loading).toBe(false));
    let finish!:(value:KitchenState)=>void;
    mockedApi.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve as typeof finish;}));
    let pending!:Promise<void>;
    act(()=>{pending=hook.result.current.reload();});
    const newer=structuredClone(initial);newer.revision=6;newer.tags.push("new tag");
    mockedApi.mockResolvedValueOnce({state:newer,message:"Saved"});
    await act(async()=>{await hook.result.current.send("tag.save",{name:"new tag"});});
    await act(async()=>{finish(initial);await pending;});
    expect(hook.result.current.state.revision).toBe(6);
    expect(hook.result.current.state.tags).toContain("new tag");
  });

  it("shows all seven days and never flags a completed meal as short",async()=>{
    const state=createDemoState();state.inventory.forEach(i=>{i.portions=0;});state.plans[0].meals.find(m=>m.id===dinner)!.status="completed";
    localStorage.setItem("stu-kitchen-demo-v1",JSON.stringify(state));render(<KitchenWorkspace demo/>);await loaded();
    expect(document.querySelectorAll(".kw-day")).toHaveLength(7);
    const card=screen.getByLabelText(/^Open Wed.*dinner$/).closest("article")!;
    expect(within(card).queryByText(/^⚠ Short:/)).not.toBeInTheDocument();
  });
  it("opens the ready next-week draft with its exact week and plan",async()=>{
    const state=createDemoState();
    state.plans.push({...structuredClone(state.plans[0]),id:"next-draft",weekStart:"2026-09-28",status:"draft",meals:[],prep:[]});
    localStorage.setItem("stu-kitchen-demo-v1",JSON.stringify(state));
    render(<KitchenWorkspace demo/>);await loaded();
    fireEvent.click(screen.getByText("Review draft"));
    expect(new URLSearchParams(nav.query).get("week")).toBe("2026-09-28");
    expect(new URLSearchParams(nav.query).get("page")).toBe("plan");
    // The draft is that week's default, so the URL does not need to name it.
    expect(new URLSearchParams(nav.query).has("plan")).toBe(false);
    expect(await screen.findByText("DRAFT")).toBeVisible();
  });

  it("clears household records when the session expires",async()=>{
    const state=createDemoState();state.revision=8;mockedApi.mockResolvedValueOnce(state);
    const hook=renderHook(()=>useKitchen(false));
    await waitFor(()=>expect(hook.result.current.loading).toBe(false));
    mockedApi.mockRejectedValueOnce(new ApiError(401,"Session expired"));
    await act(async()=>{await hook.result.current.reload();});
    expect(hook.result.current.unauthorized).toBe(true);
    expect(hook.result.current.state.plans).toHaveLength(0);
    const newHousehold=createDemoState();newHousehold.tags=["New household"];
    mockedApi.mockResolvedValueOnce(newHousehold);
    await act(async()=>{await hook.result.current.reload();});
    expect(hook.result.current.state.tags).toEqual(["New household"]);
  });

});

it("asks Stu on the server and applies the stored suggestion there",async()=>{
  const state=createDemoState();state.plans[0].status="draft";
  const meal=structuredClone(state.plans[0].meals.find(m=>m.id===dinner)!);
  meal.components=[{id:"fresh-oats",name:"牛奶燕麦粥",type:"Carbs",recipeId:"recipe-oats",portions:3}];
  const task={id:"turn-1",kind:"chat",status:"done",resolution:"open",planId:state.plans[0].id,weekStart:"2026-09-21",message:"Use oats instead",answering:false,result:{reply:"Use fresh oats",scope:dinner,meals:[meal],prep:[],needsClarification:false},error:null,createdAt:"2026-09-24T10:00:00Z",now:"2026-09-24T10:00:01Z"};
  mockedApi.mockImplementation(async(path,options)=>{
    if(path.endsWith("/generation-jobs"))return {jobs:[]} as never;
    if(path.includes("/ai-tasks/latest"))return {task:null} as never;
    if(path.endsWith("/ai-tasks/chat"))return {task,state} as never;
    if(path.endsWith("/ai-tasks/turn-1/apply"))return {state,message:"Saved",planId:state.plans[0].id} as never;
    if(options?.method==="POST")return {state,message:"Saved"} as never;
    return structuredClone(state) as never;
  });
  render(<KitchenWorkspace initialPage="plan"/>);await loaded();
  fireEvent.click(screen.getByLabelText(/^Open Wed.*dinner$/),{metaKey:true});
  fireEvent.change(screen.getByLabelText("Ask Stu to adjust your plan"),{target:{value:"Use oats instead"}});
  fireEvent.click(screen.getByLabelText("Send plan request"));
  await waitFor(()=>{
    const call=mockedApi.mock.calls.find(([path])=>path.endsWith("/ai-tasks/chat"));
    expect(call).toBeDefined();
    const body=JSON.parse(call![1]!.body as string);
    expect(body).toMatchObject({message:"Use oats instead",mealIds:[dinner],answeringClarification:false});
  });
  fireEvent.click(await screen.findByRole("button",{name:"Apply changes"}));
  await waitFor(()=>expect(mockedApi.mock.calls.some(([path])=>path.endsWith("/ai-tasks/turn-1/apply"))).toBe(true));
  // The plan is saved by the server, never by the page.
  expect(mockedApi.mock.calls.some(([path])=>path.endsWith("/commands"))).toBe(false);
});

it("adds an empty calendar slot to the currently confirmed plan",async()=>{
  const state=createDemoState();state.plans[0].meals=state.plans[0].meals.filter(m=>m.id!=="meal-0-breakfast");
  localStorage.setItem("stu-kitchen-demo-v1",JSON.stringify(state));
  render(<KitchenWorkspace demo/>);await loaded();
  fireEvent.click(screen.getByLabelText(/^Add Mon.*breakfast$/));
  fireEvent.click(screen.getByText("Choose recipe"));
  fireEvent.click(screen.getByRole("button",{name:/牛奶燕麦粥.*Carbs/}));
  fireEvent.click(screen.getByText("Save changes"));
  await waitFor(()=>expect(store().plans[0].meals).toHaveLength(21));
  expect(store().plans).toHaveLength(1);
  expect(store().plans[0].status).toBe("confirmed");
});

it("places meal feedback inside the drawer layout instead of floating above its footer",async()=>{
  nav.query+="&meal=meal-0-breakfast";
  render(<KitchenWorkspace demo/>);await loaded();
  fireEvent.click(screen.getByRole("button",{name:"Mark completed"}));
  const dialog=screen.getByRole("dialog");
  await waitFor(()=>expect(within(dialog).getByRole("status")).toHaveTextContent("Meal completed"));
  expect(within(dialog).getByRole("status").parentElement).toHaveClass("kw-drawer-notice");
  expect(within(dialog).getByRole("button",{name:"Baby liked it"})).toBeEnabled();
});

it("switches planning steps at once and remembers the step behind the scenes",async()=>{
  const state=createDemoState();
  let finish:(value:unknown)=>void=()=>{};
  const commands:string[]=[];
  mockedApi.mockImplementation(async(path,options)=>{
    if(path.endsWith("/generation-jobs"))return {jobs:[]} as never;
    if(path.includes("/ai-tasks/latest"))return {task:null} as never;
    if(path.endsWith("/commands")){commands.push(JSON.parse(options!.body as string).type);return new Promise(resolve=>{finish=resolve;}) as never;}
    return structuredClone(state) as never;
  });
  render(<KitchenWorkspace initialPage="plan"/>);await loaded();
  fireEvent.click(screen.getByRole("button",{name:"Open shopping and prep"}));
  // The page has moved on while the server is still saving the step.
  await waitFor(()=>expect(new URLSearchParams(nav.query).get("step")).toBe("shopping"));
  expect(commands).toEqual(["planning.workflow"]);
  finish({state:{...state,revision:state.revision+1},message:"Saved"});
});
