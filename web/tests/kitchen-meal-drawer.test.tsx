import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MealDrawer, replaceMealComponent } from "@/features/kitchen/meal-drawer";
import { createDemoState } from "@/features/kitchen/data";

function setup() {
  const state=createDemoState(),plan=state.plans[0],meal=plan.meals.find(m=>m.id==="meal-2-dinner")!;
  const props={state,plan,meal,onClose:vi.fn(),onDirty:vi.fn(),onSave:vi.fn().mockResolvedValue(true),onAction:vi.fn().mockResolvedValue(true),onReference:vi.fn(),onRecipe:vi.fn(),busy:false};
  return props;
}
describe("meal drawer persistence",()=>{
  it("preserves other components and instructions when replacing one part",()=>{
    const {state,meal}=setup();const replaced=replaceMealComponent(meal,state.recipes[3],meal.components[0].id,state);
    expect(replaced.components.slice(1)).toEqual(meal.components.slice(1));
    expect(replaced.steps.slice(0,meal.steps.length)).toEqual(meal.steps);
    expect(replaced.steps.at(-1)).toContain(state.recipes[3].steps.at(-1));
    expect(replaced.components[0].inventoryId).toBeUndefined();
    expect(replaced.activeMinutes).toBeGreaterThanOrEqual(meal.activeMinutes);
  });
  it("saves dirty edits and closes after Save in the close prompt",async()=>{
    const props=setup();render(<MealDrawer {...props} initialEdit/>);
    fireEvent.change(screen.getAllByLabelText("Portions")[0],{target:{value:"2"}});
    fireEvent.click(screen.getByLabelText("Close drawer"));
    expect(screen.getByText("Keep your changes?")).toBeVisible();
    fireEvent.click(screen.getByText("Save changes"));
    await waitFor(()=>expect(props.onClose).toHaveBeenCalledOnce());
    expect(props.onSave.mock.calls[0][0].components[0].portions).toBe(2);
  });
  it("blocks locked editing and exposes live audit undo for a skipped meal",()=>{
    const props=setup();props.meal.status="skipped";props.meal.locked=true;
    props.state.audit.push({id:"skip-audit",kind:"meal.status",message:"Skipped",at:"2026-09-17",...{undone:false,undo:{planId:props.plan.id,collection:"meals",entityId:props.meal.id}}});
    render(<MealDrawer {...props}/>);
    expect(screen.getByLabelText("Edit meal")).toBeDisabled();expect(screen.getByRole("button",{name:"Replace"})).toBeDisabled();
    fireEvent.click(screen.getByText("Undo skip"));
    expect(props.onAction).toHaveBeenCalledWith("change.undo",{auditId:"skip-audit"});
  });
});

it("shows completed prep correctly with mixed fresh and stock components in one compact list",()=>{
  const props=setup();props.meal.status="completed";props.plan.prep[0].status="completed";
  render(<MealDrawer {...props}/>);
  expect(screen.getByText("Prep complete: your portions are ready.")).toBeVisible();
  expect(screen.queryByText("Prep needed: check your Sunday tasks.")).not.toBeInTheDocument();
  expect(screen.getAllByText("3 portions used")).toHaveLength(3);
  expect(screen.getAllByRole("link",{name:/View recipe for/})).toHaveLength(3);
});

it("fills a new meal from a complete recipe and saves its recipe reference",async()=>{
  const props=setup();props.meal={...props.meal,id:"new-meal",components:[{id:"new-component",name:"",type:"Other",portions:3}],steps:[],activeMinutes:0,elapsedMinutes:0};
  props.state.recipes[0].incomplete=true;
  render(<MealDrawer {...props} initialEdit/>);
  fireEvent.click(screen.getByText("Choose recipe"));
  expect(screen.getByRole("button",{name:/鸡肉丸.*Protein/})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:/牛奶燕麦粥.*Carbs/}));
  fireEvent.click(screen.getByText("Save changes"));
  await waitFor(()=>expect(props.onSave).toHaveBeenCalledOnce());
  expect(props.onSave.mock.calls[0][0].components[0].recipeId).toBe("recipe-oats");
  expect(props.onSave.mock.calls[0][0].steps).toEqual(props.state.recipes[3].steps);
});

it("keeps fridge context, removes execution controls during planning and links recipes in a new tab",()=>{
  const props=setup();render(<MealDrawer {...props} planning/>);
  expect(screen.getByText("From your fridge")).toBeVisible();
  expect(screen.queryByRole("button",{name:"Mark completed"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"Baby liked it"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"Skip meal"})).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"Edit meal"})).toHaveTextContent("Edit meal");
  const link=screen.getByRole("link",{name:/View full recipe/});
  expect(link).toHaveAttribute("target","_blank");
  expect(link).toHaveAttribute("href",`/recipes/${props.meal.components[0].recipeId}`);
});
