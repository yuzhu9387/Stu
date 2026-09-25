"use client";
import { useCallback, useSyncExternalStore } from "react";

/** A string kept in the browser that React re-renders from.
 *
 * Storage can be missing or throw (private windows, blocked site data), so
 * every access is guarded and falls back to an in-memory copy for the tab: the
 * page keeps working, the value just does not outlive it.
 */
type Kind = "local" | "session";
const EVENT = "stu-browser-store";
const memory = new Map<string, string>();
const area = (kind: Kind) => (kind === "local" ? window.localStorage : window.sessionStorage);

export function readStored(kind: Kind, key: string): string | null {
  try { return area(kind).getItem(key); } catch { return memory.get(`${kind}:${key}`) ?? null; }
}

export function writeStored(kind: Kind, key: string, value: string | null) {
  try {
    if (value === null) area(kind).removeItem(key); else area(kind).setItem(key, value);
  } catch {
    if (value === null) memory.delete(`${kind}:${key}`); else memory.set(`${kind}:${key}`, value);
  }
  window.dispatchEvent(new Event(EVENT));
}

export function useStored(kind: Kind, key: string) {
  const raw = useSyncExternalStore(
    onChange => {
      window.addEventListener("storage", onChange);
      window.addEventListener(EVENT, onChange);
      return () => { window.removeEventListener("storage", onChange); window.removeEventListener(EVENT, onChange); };
    },
    () => readStored(kind, key),
    () => null,
  );
  const write = useCallback((value: string | null) => writeStored(kind, key, value), [kind, key]);
  return [raw, write] as const;
}
