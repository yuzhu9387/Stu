import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RecipesPage } from "@/features/kitchen/recipes";
import { createDemoState } from "@/features/kitchen/data";

it("renders recipes in batches while search covers the whole library",()=>{
  const state=createDemoState(),template=state.recipes[0];
  state.recipes=Array.from({length:80},(_,i)=>({...template,id:`recipe-${i}`,name:`Recipe ${String(i).padStart(2,"0")}`}));
  render(<RecipesPage state={state} plan={null} demo send={vi.fn()} notify={vi.fn()} navigate={vi.fn()}/>);
  expect(screen.getAllByRole("article")).toHaveLength(24);
  // Cards have nothing to tick: a card opens its recipe.
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:/Show more recipes/}));
  expect(screen.getAllByRole("article")).toHaveLength(48);
  fireEvent.change(screen.getByLabelText("Find a recipe"),{target:{value:"Recipe 79"}});
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByRole("button",{name:"Open recipe Recipe 79"})).toBeVisible();
});

it("puts every filter in one row: All, then meals and key tags large, then the rest",()=>{
  const state=createDemoState();
  state.tags=["Protein","小孩饭","Breakfast","快手菜"];
  state.recipes=[
    {...state.recipes[0],id:"a",name:"Kid oats",mealTypes:["breakfast"],tags:["小孩饭"]},
    {...state.recipes[0],id:"b",name:"Quick fish",mealTypes:["dinner"],tags:["快手菜","Protein"]},
  ];
  render(<RecipesPage state={state} plan={null} demo send={vi.fn()} notify={vi.fn()} navigate={vi.fn()}/>);
  const row=screen.getByRole("group",{name:"Filter recipes"});
  const chips=[...row.querySelectorAll(".kw-filter-chip")].map(b=>[b.textContent,b.classList.contains("is-key")]);
  expect(chips).toEqual([["All ★",true],["Breakfast 🌅",true],["Lunch ☀️",true],["Dinner 🌙",true],["小孩饭 👶",true],["Protein",false],["快手菜",false]]);
  fireEvent.click(screen.getByRole("button",{name:"小孩饭 👶"}));
  expect(screen.getAllByRole("article").map(a=>a.textContent)).toEqual([expect.stringContaining("Kid oats")]);
  fireEvent.click(screen.getByRole("button",{name:"All ★"}));
  expect(screen.getAllByRole("article")).toHaveLength(2);
});
