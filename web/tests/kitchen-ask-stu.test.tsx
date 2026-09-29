import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { demoAnswer } from "@/features/kitchen/ask-stu";
import { createDemoState } from "@/features/kitchen/data";
import { FridgePage } from "@/features/kitchen/fridge";
import type { KitchenState } from "@/features/kitchen/types";

afterEach(() => vi.unstubAllGlobals());

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
function fridge(state: KitchenState = createDemoState(), demo = false) {
  const send = vi.fn().mockResolvedValue(true);
  render(<FridgePage state={state} plan={state.plans[0]} send={send} demo={demo} notify={vi.fn()} navigate={vi.fn()} />);
  return { send, box: screen.getByRole("search", { name: "Ask Stu" }) };
}
const ask = (box: HTMLElement, question: string) => {
  fireEvent.change(within(box).getByLabelText("Question for Stu"), { target: { value: question } });
  fireEvent.click(within(box).getByRole("button", { name: "Ask" }));
};

describe("asking Stu on the fridge page", () => {
  it("asks the server and shows the answer, changing nothing", async () => {
    const fetch = vi.fn().mockResolvedValue(json(200, { reply: "今晚吃鸡肉丸配西兰花。" }));
    vi.stubGlobal("fetch", fetch);
    const { send, box } = fridge();
    ask(box, "今晚吃什么？");
    expect(await within(box).findByText("今晚吃鸡肉丸配西兰花。")).toBeVisible();
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/v1\/kitchen\/ask$/);
    expect(JSON.parse(fetch.mock.calls[0][1].body as string)).toEqual({ message: "今晚吃什么？" });
    expect(send).not.toHaveBeenCalled();
  });

  it("says when Stu cannot answer, and keeps the question", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(503, { detail: "Stu is not available right now." })));
    const { box } = fridge();
    ask(box, "今晚吃什么？");
    expect(await within(box).findByRole("alert")).toHaveTextContent("Stu is not available right now.");
    expect(within(box).getByLabelText("Question for Stu")).toHaveValue("今晚吃什么？");
  });

  it("needs a question", () => {
    const { box } = fridge();
    expect(within(box).getByRole("button", { name: "Ask" })).toBeDisabled();
  });

  it("in the demo answers from the fridge without asking the server", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const { box } = fridge(createDemoState(), true);
    ask(box, "今晚吃什么？");
    await waitFor(() => expect(within(box).getByText(/鸡肉丸/)).toBeVisible());
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("the demo's answer", () => {
  it("names what is in the fridge, what to use first, and says the fridge is empty when it is", () => {
    const state = createDemoState();
    expect(demoAnswer(state)).toMatch(/鸡肉丸/);
    expect(demoAnswer(state)).toMatch(/先用/);
    expect(demoAnswer({ ...state, inventory: [] })).toMatch(/冰箱/);
  });
});
