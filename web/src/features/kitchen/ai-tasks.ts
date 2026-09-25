"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChatProposal } from "./types";

/** Stu's work as the server keeps it: a chat turn or a week's draft.
 *
 * The work runs on the server after the request that started it returns, so a
 * refresh or another page does not stop it. The page asks for the latest task,
 * follows it while it runs, and shows what it produced until the household
 * applies it, keeps the current meals, or sends the next message.
 */
export interface AiTask {
  id: string;
  kind: "chat" | "generate" | "fulfillment";
  status: "running" | "done" | "failed";
  resolution: "open" | "applied" | "dismissed" | "superseded";
  planId: string | null;
  weekStart: string;
  message: string;
  answering: boolean;
  result: (Partial<ChatProposal> & { planId?: string }) | null;
  error: string | null;
  createdAt: string;
  now: string;
}

/** A task as the page holds it, with its start on this browser's clock. */
export interface HeldTask extends AiTask { startedAt: number }

const hold = (task: AiTask): HeldTask => ({
  ...task,
  startedAt: Date.now() - Math.max(0, Date.parse(task.now) - Date.parse(task.createdAt)),
});

/** Recover the server-owned turn on mount, retry offline recovery, and follow
 * it until completion. A late lookup must never erase a locally started turn. */
export function useAiTask(query: string | null, onSettled?: (task: HeldTask) => void) {
  const [held, setHeld] = useState<{ query: string | null; task: HeldTask | null } | null>(null);
  const settled = useRef(onSettled), version = useRef(0), notified = useRef(new Set<string>());
  const currentQuery = useRef(query);
  useEffect(() => { currentQuery.current = query; }, [query]);
  useEffect(() => { settled.current = onSettled; });
  const finish = useCallback((next: HeldTask) => {
    if (next.status === "running" || next.resolution !== "open" || notified.current.has(next.id)) return;
    notified.current.add(next.id);
    settled.current?.(next);
  }, []);
  useEffect(() => {
    if (!query) return;
    let active = true, timer: number | undefined;
    const lookupVersion = version.current;
    const recover = async () => {
      try {
        const response = await api<{ task: AiTask | null }>(`/api/v1/kitchen/ai-tasks/latest?${query}`);
        if (!active || version.current !== lookupVersion) return;
        const next = response.task ? hold(response.task) : null;
        setHeld({ query, task: next });
        if (next) finish(next);
      } catch {
        if (active && version.current === lookupVersion) timer = window.setTimeout(() => void recover(), 2000);
      }
    };
    void recover();
    return () => { active = false; window.clearTimeout(timer); };
  }, [query, finish]);
  const task = held && held.query === query ? held.task : null;
  const running = task?.status === "running" ? task.id : null;
  useEffect(() => {
    if (!running) return;
    let active = true, asking = false;
    const poll = async () => {
      if (asking) return;
      asking = true;
      const askedVersion = version.current;
      try {
        const response = await api<{ task: AiTask }>(`/api/v1/kitchen/ai-tasks/${running}`);
        if (!active || version.current !== askedVersion) return;
        const next = hold(response.task);
        setHeld({ query, task: next });
        finish(next);
      } catch { /* server work continues while this browser is offline */ }
      finally { asking = false; }
    };
    const timer = window.setInterval(() => void poll(), 2000);
    window.addEventListener("focus", poll);
    window.addEventListener("online", poll);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", poll); window.removeEventListener("online", poll); };
  }, [running, query, finish]);
  const set = useCallback((next: AiTask | null) => {
    if (currentQuery.current !== query) return;
    version.current += 1;
    setHeld({ query, task: next ? hold(next) : null });
  }, [query]);
  const dismiss = useCallback(async (id: string) => {
    const response = await api<{ task: AiTask }>(`/api/v1/kitchen/ai-tasks/${id}/dismiss`, { method: "POST" });
    if (currentQuery.current !== query) return;
    setHeld(current => current?.query === query && current.task?.id === id ? { query, task: hold(response.task) } : current);
  }, [query]);
  return { task, set, dismiss };
}

/** What the plan page needs of Stu's latest chat turn, live or in the demo. */
export interface ChatTurn {
  id: string;
  status: AiTask["status"];
  resolution: AiTask["resolution"];
  answering: boolean;
  result: ChatProposal | null;
  error: string | null;
  /** Demo only: the plan as Stu saw it, to refuse applying onto a changed one. */
  base?: string;
}
