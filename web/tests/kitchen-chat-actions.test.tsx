import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatTurn } from "@/features/kitchen/ai-tasks";
import { createDemoState } from "@/features/kitchen/data";
import { PlanningPage } from "@/features/kitchen/plan";
import { KitchenWorkspace } from "@/features/kitchen/workspace";
import type { ChatProposal, KitchenState, WeeklyPlan } from "@/features/kitchen/types";

const nav = vi.hoisted(() => ({ query: "", listeners: new Set<() => void>() }));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(listener => { nav.listeners.add(listener); return () => { nav.listeners.delete(listener); }; }, () => nav.query)),
    useRouter: () => ({ push: (url: string) => { nav.query = url.split("?")[1] || ""; nav.listeners.forEach(listener => listener()); } }),
  };
});
beforeEach(() => { nav.query = ""; });

const draft = (edit = false) => {
  const plan = createDemoState().plans[0];
  plan.status = "draft";
  if (edit) { plan.basePlanId = "plan-confirmed"; plan.baseVersion = 1; }
  return plan;
};
type Ask = (text: string, answering: boolean) => Promise<ChatProposal>;
function props(plan: WeeklyPlan | null, onChat = vi.fn<Ask>(async () => ({ reply: "", scope: "", meals: [], needsClarification: false }))) {
  return {
    state: createDemoState(), plan, week: "2026-09-21", choices: { slots: {} as Record<string, boolean> }, selected: [], step: null as string | null,
    onStep: vi.fn(), onSlot: vi.fn(), onGoal: vi.fn(async () => {}), onSelect: vi.fn(), onApplyFix: vi.fn(async () => {}), onGenerate: vi.fn(async (): Promise<string | null> => null),
    onSavePreferences: vi.fn(async () => 0), onChat, onApply: vi.fn(async () => {}), onConfirm: vi.fn(async (): Promise<string | null> => null), onEdit: vi.fn(async () => {}),
    focusTick: 0, onPrep: vi.fn(), onGuidance: vi.fn(), onWeek: vi.fn(), demo: true, busy: false, children: <div />,
  };
}
/** Props for rendering the page directly, with a turn passed in. */
const direct = (plan: WeeklyPlan | null) => ({ ...props(plan), onChat: vi.fn(async () => {}) });
/** Plays the server's part: a sent message becomes a running turn, then Stu's
 * answer (from `onChat`, standing in for the model). */
function WithTurn({ onChat: ask, ...rest }: ReturnType<typeof props>) {
  const [turn, setTurn] = useState<ChatTurn | null>(null);
  return <PlanningPage {...rest} turn={turn}
    onKeep={async () => setTurn(current => current && { ...current, resolution: "dismissed" })}
    onChat={async (text, answering) => {
      setTurn({ id: text, status: "running", resolution: "open", answering, result: null, error: null });
      try { const result = await ask(text, answering); setTurn({ id: text, status: "done", resolution: "open", answering, result, error: null }); }
      catch (e) { setTurn(null); throw e; }
    }} />;
}
const slotDay = (day: string) => new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" }).format(new Date(`${day}T12:00:00Z`));
const composer = () => screen.getByLabelText("Ask Stu to adjust your plan");

describe("the Stu chat", () => {
  it("keeps the meal selected at send time on the pending message", async () => {
    const plan = draft(), p = direct(plan);
    let accept!: () => void;
    p.onChat.mockImplementation(() => new Promise<void>(resolve => { accept = resolve; }));
    const view = render(<PlanningPage {...p} selected={["meal-2-dinner"]} />);
    fireEvent.change(composer(), { target: { value: "Less rice" } });
    fireEvent.click(screen.getByLabelText("Send plan request"));
    view.rerender(<PlanningPage {...p} selected={["meal-0-breakfast"]} />);
    const bubble = screen.getByText("Less rice").closest(".kw-chat-message")!;
    const tags = within(bubble as HTMLElement).getByRole("group", { name: "Referenced meals" });
    expect(tags).toHaveTextContent("Wed, Sep 23 · Dinner");
    expect(tags).not.toHaveTextContent("Breakfast");
    await act(async () => accept());
  });

  it("restores each sent message's meal tags independently of the current composer selection", () => {
    const plan = draft(true);
    plan.chat = [
      { id: "u", role: "user", text: "Make this meal simpler", mealIds: ["meal-2-dinner", "meal-0-breakfast"] },
      { id: "a", role: "assistant", text: "I will suggest changes.", mealIds: ["meal-2-dinner", "meal-0-breakfast"] },
      { id: "u2", role: "user", text: "More vegetables this week", mealIds: [] },
    ];
    const view = render(<PlanningPage {...direct(plan)} selected={["meal-4-lunch"]} />);
    const bubble = screen.getByText("Make this meal simpler").closest(".kw-chat-message")!;
    const tags = within(bubble as HTMLElement).getByRole("group", { name: "Referenced meals" });
    expect(tags).toHaveTextContent("Wed, Sep 23 · Dinner");
    expect(tags).toHaveTextContent("Mon, Sep 21 · Breakfast");
    expect(tags).not.toHaveTextContent("Fri");
    expect(within(screen.getByText("More vegetables this week").closest(".kw-chat-message") as HTMLElement).queryByRole("group", { name: "Referenced meals" })).not.toBeInTheDocument();
    view.unmount();
    render(<PlanningPage {...direct(plan)} />);
    expect(screen.getByRole("group", { name: "Referenced meals" })).toHaveTextContent("Wed, Sep 23 · Dinner");
  });

  it("sends on Shift+Enter; plain Enter is a new line", async () => {
    const p = props(draft());
    render(<WithTurn {...p} />);
    fireEvent.change(composer(), { target: { value: "Swap Wednesday dinner" } });
    fireEvent.keyDown(composer(), { key: "Enter" });
    expect(p.onChat).not.toHaveBeenCalled();
    fireEvent.keyDown(composer(), { key: "Enter", shiftKey: true });
    await waitFor(() => expect(p.onChat).toHaveBeenCalledWith("Swap Wednesday dinner", false));
  });

  it("shows the message at once, with Stu typing, until Stu answers", async () => {
    let answer!: (value: ChatProposal) => void;
    const p = props(draft(), vi.fn<Ask>(() => new Promise<ChatProposal>(resolve => { answer = resolve; })));
    render(<WithTurn {...p} />);
    fireEvent.change(composer(), { target: { value: "Less rice" } });
    fireEvent.click(screen.getByLabelText("Send plan request"));
    const chat = screen.getByRole("region", { name: "Plan conversation" });
    expect(within(chat).getByText("Less rice")).toBeVisible();
    expect(within(chat).getByLabelText("Stu is thinking")).toBeVisible();
    await act(async () => answer({ reply: "", scope: "", meals: [], needsClarification: false }));
    expect(within(chat).queryByLabelText("Stu is thinking")).not.toBeInTheDocument();
  });

  it("offers a question's answers as chips, and an answer is sent as the answer", async () => {
    const onChat = vi.fn<Ask>(async text => text === "Rebuild the whole week"
      ? { reply: "What should change most?", scope: "", meals: [], needsClarification: true, options: ["More vegetables", "Quicker dinners"] }
      : { reply: "Done", scope: "", meals: [], needsClarification: false });
    const p = props(draft(), onChat);
    render(<WithTurn {...p} />);
    fireEvent.change(composer(), { target: { value: "Rebuild the whole week" } });
    fireEvent.click(screen.getByLabelText("Send plan request"));
    const answers = await screen.findByRole("group", { name: "Answer Stu" });
    fireEvent.click(within(answers).getByRole("button", { name: "More vegetables" }));
    await waitFor(() => expect(onChat).toHaveBeenLastCalledWith("More vegetables", true));
    // Stu acted, so there is nothing left to answer.
    await waitFor(() => expect(screen.queryByRole("group", { name: "Answer Stu" })).not.toBeInTheDocument());
  });

  it("shows a single-meal swap as Now → After to confirm", async () => {
    const plan = draft();
    const before = plan.meals.find(m => m.id === "meal-2-dinner")!;
    const after = { ...structuredClone(before), activeMinutes: before.activeMinutes + 5, components: [before.components[0], { id: "new-veg", name: "蒸胡萝卜", type: "Vegetables" as const, portions: 3 }] };
    const p = props(plan, vi.fn<Ask>(async () => ({ reply: "Swapped", scope: after.id, meals: [after], needsClarification: false })));
    render(<WithTurn {...p} />);
    fireEvent.change(composer(), { target: { value: "Different vegetable" } });
    fireEvent.click(screen.getByLabelText("Send plan request"));
    const card = await screen.findByRole("group", { name: "Proposed changes" });
    const [now, next] = [card.querySelector(".is-before")!, card.querySelector(".is-after")!];
    const dropped = before.components.filter(c => !after.components.some(x => x.name === c.name));
    for (const c of dropped) expect(within(now as HTMLElement).getByText(c.name).tagName).toBe("S");
    expect(within(next as HTMLElement).getByText("蒸胡萝卜")).toHaveClass("is-added");
    expect(within(next as HTMLElement).getByText(`${after.activeMinutes} min`)).toHaveClass("is-changed");
    const apply = within(card).getByRole("button", { name: "Apply changes" });
    expect(apply).toHaveTextContent("Apply change");
    fireEvent.click(apply);
    await waitFor(() => expect(p.onApply).toHaveBeenCalled());
  });

  it("picks up where Stu was after a refresh: typing, then the suggestion", () => {
    const plan = draft();
    const after = { ...structuredClone(plan.meals[8]), steps: ["Reheat"] };
    const running: ChatTurn = { id: "t", status: "running", resolution: "open", answering: false, result: null, error: null };
    const { rerender } = render(<PlanningPage {...direct(plan)} turn={running} />);
    expect(screen.getByLabelText("Stu is thinking")).toBeVisible();
    expect(screen.getByLabelText("Send plan request")).toBeDisabled();
    rerender(<PlanningPage {...direct(plan)} turn={{ ...running, status: "done", result: { reply: "Done", scope: after.id, meals: [after], needsClarification: false } }} />);
    expect(screen.queryByLabelText("Stu is thinking")).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Proposed changes" })).toBeVisible();
    // Applied or kept, the suggestion is gone for good.
    rerender(<PlanningPage {...direct(plan)} turn={{ ...running, status: "done", resolution: "applied", result: { reply: "Done", scope: after.id, meals: [after], needsClarification: false } }} />);
    expect(screen.queryByRole("group", { name: "Proposed changes" })).not.toBeInTheDocument();
  });

  it("keeps an unsent composer draft when the page is remounted", () => {
    const p = direct(draft());
    const view = render(<PlanningPage {...p} />);
    fireEvent.change(composer(), { target: { value: "周末可以丰富一点" } });
    view.unmount();
    render(<PlanningPage {...p} />);
    expect(composer()).toHaveValue("周末可以丰富一点");
  });

  it("says in the chat when Stu could not finish", () => {
    const failed: ChatTurn = { id: "t", status: "failed", resolution: "open", answering: false, result: null, error: "Stu was interrupted before finishing. Please try again." };
    render(<PlanningPage {...direct(draft())} turn={failed} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("interrupted");
    expect(alert.closest(".kw-chat")).not.toBeNull();
  });

  it("keeps the current meals with Keep current", async () => {
    const plan = draft();
    const after = { ...structuredClone(plan.meals[8]), steps: ["Reheat"] };
    const p = props(plan, vi.fn<Ask>(async () => ({ reply: "Done", scope: after.id, meals: [after], needsClarification: false })));
    render(<WithTurn {...p} />);
    fireEvent.change(composer(), { target: { value: "Simpler" } });
    fireEvent.click(screen.getByLabelText("Send plan request"));
    fireEvent.click(await screen.findByRole("button", { name: "Keep current" }));
    await waitFor(() => expect(screen.queryByRole("group", { name: "Proposed changes" })).not.toBeInTheDocument());
  });

  it("says why Stu could not answer inside the chat and keeps the message", async () => {
    const p = props(draft(), vi.fn<Ask>(async () => { throw new Error("Full recipe required for 牛奶"); }));
    render(<WithTurn {...p} />);
    fireEvent.change(composer(), { target: { value: "Add milk" } });
    fireEvent.click(screen.getByLabelText("Send plan request"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Full recipe required for 牛奶");
    expect(alert.closest(".kw-chat")).not.toBeNull();
    expect(composer()).toHaveValue("Add milk");
  });
});

describe("editing a confirmed week", () => {
  it("shows all four steps on step 1, and saves from there", () => {
    const p = props(draft(true));
    render(<WithTurn {...p} step="preferences" />);
    const rail = screen.getByRole("list", { name: "Planning steps" });
    expect(within(rail).getAllByRole("listitem")).toHaveLength(4);
    expect(within(rail).getByText("Meals & preferences")).toBeVisible();
    expect(within(rail).getByRole("button", { name: /step 2, adjust/ })).toBeVisible();
    const save = within(rail).getByRole("button", { name: "Confirm plan" });
    expect(save.parentElement).toHaveTextContent("Save changes");
    fireEvent.click(save);
    expect(p.onConfirm).toHaveBeenCalled();
  });

  it("shows the latest exchange with Stu on step 1", () => {
    const plan = draft(true);
    plan.chat = [
      { id: "u", role: "user", text: "Less rice", mealIds: [] },
      { id: "a", role: "assistant", text: "Swapped rice for noodles", mealIds: [] },
    ];
    render(<PlanningPage {...direct(plan)} step="preferences" />);
    const latest = screen.getByLabelText("Latest with Stu");
    expect(latest).toHaveTextContent("Less rice");
    expect(latest).toHaveTextContent("Swapped rice for noodles");
  });

  it("a new week still has no confirm on step 1", () => {
    render(<PlanningPage {...direct(draft())} step="preferences" />);
    expect(screen.getByRole("button", { name: "Confirm plan" })).toBeDisabled();
  });

  it("turns step 1's request into a chat with Stu on Adjust", async () => {
    const p = props(draft(true));
    render(<WithTurn {...p} step="preferences" />);
    expect(screen.queryByRole("button", { name: /Generate/ })).not.toBeInTheDocument();
    const box = screen.getByLabelText("This week’s preferences");
    expect(box).toHaveValue("");
    const ask = screen.getByRole("button", { name: "Ask Stu to change this week" });
    expect(ask).toBeDisabled();
    fireEvent.change(box, { target: { value: "No eggs on Friday" } });
    fireEvent.click(ask);
    expect(p.onStep).toHaveBeenCalledWith("adjust");
    await waitFor(() => expect(p.onChat).toHaveBeenCalledWith("No eggs on Friday", false));
  });
});

describe("an empty week", () => {
  it("can be planned by hand: skip AI starts an empty draft", async () => {
    const onPlanMyself = vi.fn(async () => {});
    render(<PlanningPage {...direct(null)} onPlanMyself={onPlanMyself} />);
    fireEvent.click(screen.getByRole("button", { name: /or skip AI, I’ll plan myself/ }));
    await waitFor(() => expect(onPlanMyself).toHaveBeenCalled());
  });
});

describe("no page banner on Plan and Calendar", () => {
  const seed = (change?: (state: KitchenState) => void) => { const state = createDemoState(); change?.(state); localStorage.setItem("stu-kitchen-demo-v1", JSON.stringify(state)); };
  const loaded = () => screen.findByRole("region", { name: "Weekly meal calendar" });

  it("says what a card action did on that card, with Undo", async () => {
    seed();
    // A meal that needs no prep can be marked done straight away.
    const meal = createDemoState().plans[0].meals.find(m => m.status === "planned" && m.included !== false && m.components.every(c => !c.prepId))!;
    const label = new RegExp(`^Mark ${slotDay(meal.day)}.*${meal.slot} completed$`);
    nav.query = "page=calendar";
    const { container } = render(<KitchenWorkspace demo />); await loaded();
    fireEvent.click(screen.getByLabelText(label));
    const note = await screen.findByRole("status");
    expect(note).toHaveTextContent("Done ✓");
    expect(note.closest(".kw-meal-slot")).not.toBeNull();
    expect(container.querySelector(".kw-page-notice")).toBeNull();
    expect(screen.getByLabelText(label)).toBeDisabled();
    fireEvent.click(within(note).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(screen.getByLabelText(label)).toBeEnabled());
  });

  it("shows done in green for two seconds, with the done mark grown to show the state", async () => {
    seed();
    const meal = createDemoState().plans[0].meals.find(m => m.status === "planned" && m.included !== false && m.components.every(c => !c.prepId))!;
    const done = new RegExp(`^Mark ${slotDay(meal.day)}.*${meal.slot} completed$`), skip = new RegExp(`^Skip ${slotDay(meal.day)}.*${meal.slot}$`);
    nav.query = "page=calendar";
    render(<KitchenWorkspace demo />); await loaded();
    fireEvent.click(screen.getByLabelText(done));
    expect(await screen.findByRole("status")).toHaveClass("is-success");
    expect(screen.getByLabelText(done)).toHaveClass("selected");
    expect(screen.getByLabelText(skip)).not.toHaveClass("selected");
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument(), { timeout: 3000 });
  });

  it("hides a failed card action after two seconds too", async () => {
    seed();
    const state = createDemoState();
    const meal = state.plans[0].meals.find(m => m.components.some(c => c.prepId && state.plans[0].prep.find(t => t.id === c.prepId)?.status === "planned"))!;
    nav.query = "page=calendar";
    render(<KitchenWorkspace demo />); await loaded();
    fireEvent.click(screen.getByLabelText(new RegExp(`^Mark ${slotDay(meal.day)}.*${meal.slot} completed$`)));
    expect(await screen.findByRole("alert")).not.toHaveClass("is-success");
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument(), { timeout: 3000 });
  });

  it("shows a failed card action on the card, not as a banner", async () => {
    seed();
    const state = createDemoState();
    // A meal whose prep has not been done yet cannot be marked completed.
    const meal = state.plans[0].meals.find(m => m.components.some(c => c.prepId && state.plans[0].prep.find(t => t.id === c.prepId)?.status === "planned"))!;
    nav.query = "page=calendar";
    const { container } = render(<KitchenWorkspace demo />); await loaded();
    const slot = new RegExp(`^Mark ${slotDay(meal.day)}.*${meal.slot} completed$`);
    fireEvent.click(screen.getByLabelText(slot));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Prep is not complete.");
    expect(alert.closest(".kw-meal-slot")).not.toBeNull();
    expect(container.querySelector(".kw-page-notice")).toBeNull();
    fireEvent.click(within(alert).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
