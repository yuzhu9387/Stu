import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createDemoState } from "@/features/kitchen/data";
import { useKitchen } from "@/features/kitchen/store";

afterEach(() => vi.unstubAllGlobals());

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const at = (revision: number) => ({ ...createDemoState(), revision });

describe("a change sent while something else changed the kitchen", () => {
  it("is sent again once against the fresh kitchen when only the revision moved on", async () => {
    // Stu's lists arrive (revision 2) between the page loading and a tap.
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(200, at(1)))
      .mockResolvedValueOnce(json(409, { detail: "Workspace changed; refresh before applying this change" }))
      .mockResolvedValueOnce(json(200, at(2)))
      .mockResolvedValueOnce(json(200, { state: at(3), message: "Prep done" }));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useKitchen(false));
    await waitFor(() => expect(result.current.state.revision).toBe(1));
    await act(async () => { await result.current.send("prep.status", { planId: "p", prepId: "t", status: "completed" }); });
    const sent = fetch.mock.calls.filter(call => String(call[0]).endsWith("/api/v1/kitchen/commands")).map(call => JSON.parse(call[1].body as string));
    expect(sent.map(command => command.expectedRevision)).toEqual([1, 2]);
    expect(sent[0].operationId).not.toBe(sent[1].operationId);
    expect(result.current.state.revision).toBe(3);
  });

  it("records a meal or prep again even when the page pinned what it saw, but never re-sends a save", async () => {
    const stale = () => json(409, { detail: "Workspace changed; refresh before applying this change" });
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(200, at(1)))
      .mockResolvedValueOnce(stale()).mockResolvedValueOnce(json(200, at(2))).mockResolvedValueOnce(json(200, { state: at(3), message: "Done" }))
      .mockResolvedValueOnce(stale()).mockResolvedValueOnce(json(200, at(4)));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useKitchen(false));
    await waitFor(() => expect(result.current.state.revision).toBe(1));
    await act(async () => { await result.current.send("meal.status", { planId: "p", mealId: "m", status: "completed" }, 1); });
    expect(result.current.state.revision).toBe(3);
    let refused: unknown;
    await act(async () => { try { await result.current.send("meal.save", { planId: "p", meal: {} }, 3); } catch (e) { refused = e; } });
    expect(String(refused)).toContain("Workspace changed");
    expect(result.current.state.revision).toBe(4);
    const sent = fetch.mock.calls.filter(call => String(call[0]).endsWith("/api/v1/kitchen/commands")).map(call => JSON.parse(call[1].body as string));
    expect(sent.map(c => [c.type, c.expectedRevision])).toEqual([["meal.status", 1], ["meal.status", 2], ["meal.save", 3]]);
  });

  it("still says so when the change itself conflicts", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(200, at(1)))
      .mockResolvedValueOnce(json(409, { detail: "Confirmed plan changed; reconcile the draft" }))
      .mockResolvedValueOnce(json(200, at(1)));
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useKitchen(false));
    await waitFor(() => expect(result.current.state.revision).toBe(1));
    await expect(act(async () => { await result.current.send("plan.confirm", { id: "p" }); })).rejects.toThrow("Confirmed plan changed");
    expect(fetch.mock.calls.filter(call => String(call[0]).endsWith("/api/v1/kitchen/commands"))).toHaveLength(1);
  });
});
