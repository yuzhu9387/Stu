"use client";
import { useCallback, useMemo } from "react";
import { readStored, useStored, writeStored } from "./browser-store";

/** Meals referenced in the Stu chat, per week, for this browser tab.
 *
 * They used to ride in the URL as repeated `ref=` parameters, which made
 * addresses long and turned every ⌘-click into a navigation that scrolled the
 * page. They are a working selection, not an address: the tab keeps them.
 */
export function useChatRefs(week: string, demo: boolean) {
  const key = `stu-chat-refs:${demo ? "demo" : "live"}:${week}`;
  const [raw, write] = useStored("session", key);
  const refs = useMemo(() => { try { const value = raw ? JSON.parse(raw) : []; return Array.isArray(value) ? value.map(String) : []; } catch { return []; } }, [raw]);
  const set = useCallback((ids: string[]) => write(ids.length ? JSON.stringify([...new Set(ids)]) : null), [write]);
  const add = useCallback((id: string) => {
    let current: string[] = [];
    try { current = JSON.parse(readStored("session", key) ?? "[]"); } catch { current = []; }
    write(JSON.stringify([...new Set([...current, id])]));
  }, [key, write]);
  return { refs, set, add };
}

/** Moving to the chat is a one-off request, made by the action that asked for
 * it ("Reference in chat") and consumed by the plan page that answers it. An
 * in-page ⌘-click never asks, so the page stays where it is. */
const FOCUS = "stu-chat-focus";
export const requestChatFocus = () => writeStored("session", FOCUS, "1");
export function takeChatFocus() {
  const wanted = readStored("session", FOCUS) === "1";
  if (wanted) writeStored("session", FOCUS, null);
  return wanted;
}
