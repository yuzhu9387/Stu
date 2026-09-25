import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RecipesPage } from "@/features/kitchen/recipes";
import { PrepPage } from "@/features/kitchen/prep";
import { MealDrawer } from "@/features/kitchen/meal-drawer";
import { createDemoState } from "@/features/kitchen/data";
import { applyDemoCommand } from "@/features/kitchen/demo-engine";
import type { KitchenState } from "@/features/kitchen/types";
function RecipeHarness({initial}:{initial:KitchenState}) {
  const [state,setState]=useState(initial);
  return <RecipesPage state={state} plan={state.plans[0]} demo notify={()=>{}} navigate={()=>{}} send={async(type,payload)=>{setState(current=>applyDemoCommand(current,{type,payload,expectedRevision:current.revision,operationId:crypto.randomUUID()}).state);return true;}}/>;
}
describe("completed kitchen interactions",()=>{
  it("manages tags in a popup: add, rename, delete with a confirmation, and merge",async()=>{
    const state=createDemoState();state.tags=["Kids","Family","Old"];state.recipes=state.recipes.slice(0,2).map((r,i)=>({...r,tags:i?["Family"]:["Kids","Old"]}));
    render(<RecipeHarness initial={state}/>);
    fireEvent.click(screen.getByRole("button",{name:"✎ Edit tags"}));
    const popup=screen.getByRole("dialog",{name:"Recipe tags"});
    expect(within(popup).getByText("Kids",{selector:".kw-tag-name"}).closest("li")).toHaveTextContent("1 recipe");
    fireEvent.change(within(popup).getByLabelText("New tag"),{target:{value:"快手菜"}});
    fireEvent.click(within(popup).getByRole("button",{name:"+ Add"}));
    await waitFor(()=>expect(within(popup).getByText("快手菜",{selector:".kw-tag-name"})).toBeVisible());
    fireEvent.click(within(popup).getByRole("button",{name:"Rename tag Kids"}));
    fireEvent.change(within(popup).getByLabelText("New name for Kids"),{target:{value:"小孩饭"}});
    fireEvent.click(within(popup).getByRole("button",{name:"Save"}));
    await waitFor(()=>expect(within(popup).getByText("小孩饭",{selector:".kw-tag-name"})).toBeVisible());
    fireEvent.click(within(popup).getByRole("button",{name:"Delete tag Old"}));
    expect(within(popup).getByText("Remove it from 1 recipe?")).toBeVisible();
    fireEvent.click(within(popup).getByRole("button",{name:"Delete"}));
    await waitFor(()=>expect(within(popup).queryByText("Old",{selector:".kw-tag-name"})).not.toBeInTheDocument());
    fireEvent.change(within(popup).getByLabelText("Merge tag"),{target:{value:"小孩饭"}});
    fireEvent.change(within(popup).getByLabelText("Into tag"),{target:{value:"Family"}});
    fireEvent.click(within(popup).getByRole("button",{name:"Merge tags"}));
    await waitFor(()=>expect(within(popup).queryByText("小孩饭",{selector:".kw-tag-name"})).not.toBeInTheDocument());
    fireEvent.click(within(popup).getByRole("button",{name:"Close tags"}));
    const first=screen.getByRole("heading",{name:state.recipes[0].name}).closest("article")!;
    expect(within(first).getByText("Family")).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });
  it("allows explicitly changing a component to an on-hand batch",async()=>{
    const state=createDemoState(),plan=state.plans[0],meal=plan.meals.find(m=>m.id==="meal-2-dinner")!;
    const save=vi.fn().mockResolvedValue(true);
    render(<MealDrawer state={state} plan={plan} meal={meal} initialEdit busy={false} onClose={()=>{}} onDirty={()=>{}} onSave={save} onAction={async()=>true} onReference={()=>{}} onRecipe={()=>{}}/>);
    fireEvent.change(screen.getByLabelText(`Source for ${meal.components[0].name}`),{target:{value:"inventory:stock-rice"}});
    fireEvent.click(screen.getByText("Save changes"));
    await waitFor(()=>expect(save).toHaveBeenCalledOnce());
    expect(save.mock.calls[0][0].components[0]).toMatchObject({inventoryId:"stock-rice",recipeId:"recipe-rice",name:state.inventory.find(i=>i.id==="stock-rice")!.name});
    expect(save.mock.calls[0][0].components[0].prepId).toBeUndefined();
  });
  it("shows the actual recommended prep ordering and overlapping wait windows",()=>{
    const state=createDemoState();
    render(<PrepPage state={state} plan={state.plans[0]} send={async()=>true} demo notify={()=>{}} navigate={()=>{}}/>);
    fireEvent.click(screen.getByText("Session timing & stock availability"));
    expect(screen.getByRole("table",{name:"Recommended prep order"})).toBeVisible();
    expect(screen.getByRole("columnheader",{name:"Hands-on window"})).toBeVisible();
    expect(screen.getByRole("columnheader",{name:"Ready at"})).toBeVisible();
  });
});

it("records leftovers from a completed component and allows undo before meal undo",async()=>{
  const initial=createDemoState();initial.plans[0].meals[0].status="completed";
  function LeftoversHarness(){const [state,setState]=useState(initial);return <><output aria-label="Inventory portions">{state.inventory.reduce((sum,item)=>sum+item.portions,0)}</output><MealDrawer state={state} plan={state.plans[0]} meal={state.plans[0].meals[0]} busy={false} onClose={()=>{}} onDirty={()=>{}} onSave={async()=>true} onAction={async(type,payload)=>{setState(current=>applyDemoCommand(current,{type,payload,expectedRevision:current.revision,operationId:crypto.randomUUID()}).state);return true;}} onReference={()=>{}} onRecipe={()=>{}}/></>;}
  render(<LeftoversHarness/>);
  fireEvent.click(screen.getByText("Save leftovers"));
  fireEvent.change(screen.getByLabelText("Leftover portions"),{target:{value:"1"}});
  fireEvent.click(screen.getByText("Add leftovers to fridge"));
  await waitFor(()=>expect(screen.getByLabelText("Inventory portions")).toHaveTextContent("13"));
  // The inventory render can precede the form's async saving flag clearing.
  await waitFor(()=>expect(screen.getByText("Undo latest leftovers")).toBeEnabled());
  fireEvent.click(screen.getByText("Undo latest leftovers"));
  await waitFor(()=>expect(screen.getByLabelText("Inventory portions")).toHaveTextContent("12"));
});
