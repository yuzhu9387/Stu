import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Drawer } from "@/features/kitchen/drawer";

describe("drawer keyboard behavior", () => {
  it("contains keyboard focus, handles Escape and restores the opener", () => {
    const opener=document.createElement("button");opener.textContent="Open meal";document.body.append(opener);opener.focus();
    const onClose=vi.fn();const view=render(<Drawer title="Meal details" onClose={onClose} footer={<button>Save meal</button>}><input aria-label="Food"/></Drawer>);
    const close=screen.getByLabelText("Close drawer"),save=screen.getByText("Save meal");
    expect(close).toHaveFocus();
    fireEvent.keyDown(close,{key:"Tab",shiftKey:true});expect(save).toHaveFocus();
    fireEvent.keyDown(save,{key:"Tab"});expect(close).toHaveFocus();
    fireEvent.keyDown(close,{key:"Escape"});expect(onClose).toHaveBeenCalledOnce();
    view.unmount();expect(opener).toHaveFocus();opener.remove();
  });
});

it("closes on a click in empty page space, but not on a click inside it", () => {
  const onClose = vi.fn();
  render(<><main data-testid="page">Week</main><Drawer title="Wed dinner" onClose={onClose}><p>Details</p></Drawer></>);
  fireEvent.pointerDown(screen.getByText("Details"));
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.pointerDown(screen.getByTestId("page"));
  expect(onClose).toHaveBeenCalledTimes(1);
});
