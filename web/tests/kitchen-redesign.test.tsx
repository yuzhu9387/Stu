import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RecipesPage } from "@/features/kitchen/recipes";
import { PrepPage } from "@/features/kitchen/prep";
import { GuidancePage } from "@/features/kitchen/guidance";
import { createDemoState } from "@/features/kitchen/data";

function props(){const state=createDemoState();return {state,plan:state.plans[0],send:vi.fn().mockResolvedValue(true),navigate:vi.fn(),notify:vi.fn(),demo:true};}
it("opens a recipe on its own page without changing data, and edits it there",()=>{
 const p=props(),recipe=p.state.recipes[0];render(<RecipesPage {...p}/>);
 fireEvent.click(screen.getByRole("button",{name:`Open recipe ${recipe.name}`}));
 const page=screen.getByRole("article",{name:`Recipe ${recipe.name}`});
 expect(within(page).getByText(recipe.steps[0])).toBeVisible();
 expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
 expect(p.send).not.toHaveBeenCalled();
 fireEvent.click(within(page).getByRole("button",{name:/Edit/}));
 expect(screen.getByLabelText("Recipe name")).toHaveValue(recipe.name);
 fireEvent.click(screen.getByRole("button",{name:`← ${recipe.name}`}));
 fireEvent.click(screen.getByRole("button",{name:"← Recipe Book"}));
 expect(screen.getAllByRole("article").length).toBeGreaterThan(1);
});
it("selecting a queued prep task only changes the current task, and completes the selected task",async()=>{
 const p=props(),first=p.plan.prep[0];p.plan.prep.push({...structuredClone(first),id:"second-task",name:"蒸红薯",type:"Carbs",inputs:[],dependencies:[]});
 render(<PrepPage {...p}/>);
 expect(screen.getByText("Weekend Batch Cooking · Sunday, Sep 20")).toBeVisible();
 fireEvent.click(screen.getByRole("button",{name:/蒸红薯.*(Batch Prep|Same-day)/}));
 expect(p.send).not.toHaveBeenCalled();
 expect(screen.getByLabelText("Actual portions for 蒸红薯")).toBeVisible();
 fireEvent.click(screen.getByRole("button",{name:"Mark prepared"}));
 await waitFor(()=>expect(p.send).toHaveBeenCalledWith("prep.status",expect.objectContaining({prepId:"second-task",status:"completed"})));
});
it("planning preference stepper saves the entire household without dropping guidance",async()=>{
 const p=props();render(<GuidancePage {...p}/>);
 fireEvent.click(screen.getByRole("button",{name:"More new recipes"}));
 await waitFor(()=>expect(p.send).toHaveBeenCalledWith("settings.save",{settings:{...p.state.settings,newRecipesPerWeek:p.state.settings.newRecipesPerWeek+1}}));
 fireEvent.click(screen.getByRole("link",{name:/General Settings/}));
 expect(screen.getByLabelText("Timezone")).toBeVisible();
});
