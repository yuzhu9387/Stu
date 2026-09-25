import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { useAiTask, type AiTask } from "@/features/kitchen/ai-tasks";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));
const task = (status: AiTask["status"] = "running"): AiTask => ({ id: "task-1", kind: "generate", status, resolution: "open", planId: null, weekStart: "2026-09-21", message: "More vegetables", answering: false, result: status === "done" ? { planId: "draft-1" } : null, error: null, createdAt: new Date().toISOString(), now: new Date().toISOString() });
beforeEach(() => vi.mocked(api).mockReset());
afterEach(() => vi.useRealTimers());

it("shows a result that finished while the page was closed", async () => {
  const done = task("done"), settled = vi.fn();
  vi.mocked(api).mockResolvedValue({ task: done });
  const { result } = renderHook(() => useAiTask("kind=generate&weekStart=2026-09-21", settled));
  await waitFor(() => expect(result.current.task?.status).toBe("done"));
  expect(settled).toHaveBeenCalledWith(expect.objectContaining({ id: done.id }));
});

it("does not let an old latest query erase a just-started task", async () => {
  let respond!: (value: unknown) => void;
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { respond = resolve; }));
  const { result } = renderHook(() => useAiTask("kind=chat&planId=p"));
  act(() => result.current.set(task()));
  await act(async () => respond({ task: null }));
  expect(result.current.task?.id).toBe("task-1");
});

it("retries recovery after a transient network failure", async () => {
  vi.useFakeTimers();
  vi.mocked(api).mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ task: task() });
  const { result } = renderHook(() => useAiTask("kind=chat&planId=p"));
  await act(async () => {});
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(result.current.task?.id).toBe("task-1");
});

it("does not replace a new week's task when an old start request returns late", async () => {
  vi.mocked(api).mockResolvedValue({ task: task() });
  const { result, rerender } = renderHook(({ query }) => useAiTask(query), { initialProps: { query: "kind=generate&weekStart=2026-09-21" } });
  await waitFor(() => expect(result.current.task?.id).toBe("task-1"));
  const oldSet = result.current.set;
  vi.mocked(api).mockResolvedValue({ task: { ...task(), id: "task-2", weekStart: "2026-09-28" } });
  rerender({ query: "kind=generate&weekStart=2026-09-28" });
  await waitFor(() => expect(result.current.task?.id).toBe("task-2"));
  act(() => oldSet(task()));
  expect(result.current.task?.id).toBe("task-2");
});
