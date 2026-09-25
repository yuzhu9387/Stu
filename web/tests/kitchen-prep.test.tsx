import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PrepPage } from "@/features/kitchen/prep";
import { createDemoState } from "@/features/kitchen/data";
it("offers persistent skip undo from a saved prep audit",()=>{
  const state=createDemoState(),plan=state.plans[0],task=plan.prep[0];task.status="skipped";
  state.audit.push({id:"prep-skip",kind:"prep.status",message:"Skipped",at:"2026-09-17",...{undone:false,undo:{planId:plan.id,entityId:task.id,collection:"prep"}}});
  const send=vi.fn().mockResolvedValue(true);
  render(<PrepPage state={state} plan={plan} send={send} demo notify={vi.fn()} navigate={vi.fn()}/>);
  fireEvent.click(screen.getByText("Undo skip"));
  expect(send).toHaveBeenCalledWith("change.undo",{auditId:"prep-skip"});
});

it("offers only Mark All Done on an open prep task",()=>{
  const state=createDemoState(),plan=state.plans[0];
  render(<PrepPage state={state} plan={plan} send={vi.fn().mockResolvedValue(true)} demo notify={vi.fn()} navigate={vi.fn()}/>);
  const actions=document.querySelector(".kw-prep-actions")!;
  expect([...actions.querySelectorAll("button")].map(b=>b.textContent)).toEqual(["Mark All Done ✅"]);
  expect(screen.queryByLabelText("Skip prep")).not.toBeInTheDocument();
  expect(screen.queryByLabelText(`Edit prep ${plan.prep[0].name}`)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(`Remove prep ${plan.prep[0].name}`)).not.toBeInTheDocument();
});
