import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import KitchenLayout from "@/app/(kitchen)/layout";
import { createDemoState } from "@/features/kitchen/data";
import { api } from "@/lib/api";

const nav=vi.hoisted(()=>({path:"/plan",query:"week=2026-09-21&step=adjust",listeners:new Set<()=>void>(),prefetch:vi.fn()}));
vi.mock("next/navigation",async()=>{
  const {useSyncExternalStore}=await import("react");
  const subscribe=(listener:()=>void)=>{nav.listeners.add(listener);return()=>{nav.listeners.delete(listener);};};
  return {
    usePathname:()=>useSyncExternalStore(subscribe,()=>nav.path),
    useSearchParams:()=>new URLSearchParams(useSyncExternalStore(subscribe,()=>nav.query)),
    useRouter:()=>({push:(url:string)=>{[nav.path,nav.query=""]=url.split("?");nav.listeners.forEach(listener=>listener());},prefetch:nav.prefetch}),
  };
});
vi.mock("@/lib/api",async original=>({...await original<typeof import("@/lib/api")>(),api:vi.fn()}));
beforeEach(()=>{nav.path="/plan";nav.query="week=2026-09-21&step=adjust";nav.prefetch.mockClear();vi.mocked(api).mockReset();});

it("keeps the workspace and task subscriptions across main routes without reloading kitchen data",async()=>{
  const state=createDemoState();state.plans[0].status="draft";
  vi.mocked(api).mockImplementation(async path=>path.includes("ai-tasks")?{task:null} as never:structuredClone(state) as never);
  const view=render(<KitchenLayout><span data-testid="route-child">Plan route</span></KitchenLayout>);
  const composer=await screen.findByLabelText("Ask Stu to adjust your plan");
  fireEvent.change(composer,{target:{value:"More vegetables tomorrow"}});
  await waitFor(()=>{
    expect(vi.mocked(api).mock.calls.some(([path])=>path.includes("/latest?kind=chat"))).toBe(true);
    expect(vi.mocked(api).mock.calls.some(([path])=>path.includes("/latest?kind=generate"))).toBe(true);
  });
  const taskReads=vi.mocked(api).mock.calls.filter(([path])=>path.includes("/latest?")).length;
  for(const page of ["calendar","fridge","recipes","guidance","knowledge","prep","plan"]){
    act(()=>{nav.path=`/${page}`;nav.listeners.forEach(listener=>listener());});
    view.rerender(<KitchenLayout><span data-testid="route-child">{page} route</span></KitchenLayout>);
    expect(document.querySelector(`.kw-page-${page}`)).toBeInTheDocument();
    expect(screen.queryByText("Loading your kitchen…")).not.toBeInTheDocument();
  }
  expect(screen.getByLabelText("Ask Stu to adjust your plan")).toHaveValue("More vegetables tomorrow");
  expect(vi.mocked(api).mock.calls.filter(([path])=>path==="/api/v1/kitchen")).toHaveLength(1);
  expect(vi.mocked(api).mock.calls.filter(([path])=>path.includes("/latest?"))).toHaveLength(taskReads);
  fireEvent.click(screen.getByLabelText(/^Open Wed.*dinner$/));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  // Browser history bypasses the app's navigate helper.
  act(()=>{nav.path="/recipes";nav.query="week=2026-09-21";nav.listeners.forEach(listener=>listener());});
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.querySelector(".kw-page-recipes")).toBeInTheDocument();
  const workspace=view.container.querySelector<HTMLDivElement>(".kw-workspace")!;
  workspace.scrollIntoView=vi.fn();
  fireEvent.click(screen.getByRole("button",{name:"Calendar"}));
  expect(workspace.scrollIntoView).toHaveBeenCalledOnce();
  act(()=>{nav.path="/recipes";nav.listeners.forEach(listener=>listener());});
  // History keeps the browser's restored scroll position.
  expect(workspace.scrollIntoView).toHaveBeenCalledOnce();
  fireEvent(window,new Event("focus"));
  await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([path])=>path==="/api/v1/kitchen")).toHaveLength(2));
});
