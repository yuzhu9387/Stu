"use client";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";

/** Compartment key → the ids of its boxes, in shelf order. */
export type Columns = Record<string, string[]>;
type Rect = { x: number; y: number; w: number; h: number };

const MOUSE_DISTANCE = 6;   // px a mouse moves before a press becomes a drag
const TOUCH_HOLD = 260;     // ms a finger rests before a press becomes a drag
const TOUCH_SLOP = 10;      // px a finger may drift during the hold (more is a scroll)
const EASE = "transform 260ms cubic-bezier(.2,.8,.2,1)";

const pageRect = (node: Element): Rect => {
  const r = node.getBoundingClientRect();
  return { x: r.left + window.scrollX, y: r.top + window.scrollY, w: r.width, h: r.height };
};
const same = (a: Columns, b: Columns) => Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(key => (b[key] ?? []).join("\u0000") === a[key].join("\u0000"));

/** Drag boxes between shelves and compartments, with every other box gliding
 * to its new place (FLIP: each box starts where it was and eases to where it
 * now sits). A mouse drag starts after a few pixels; a touch drag after a short
 * hold, so swiping still scrolls the page. The dragged box follows the pointer
 * as a lifted copy while a dashed slot shows where it will land; on release it
 * settles into that slot. `commit` saves; if it fails, everything eases back.
 *
 * Boxes carry `data-fridge-item={id}` and compartments `data-compartment={key}`
 * inside `container`.
 */
export function useFridgeDrag(container: RefObject<HTMLElement | null>, columns: Columns, commit: (next: Columns) => Promise<unknown>) {
  const [preview, setPreview] = useState<Columns | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [ghost, setGhost] = useState<{ id: string; width: number; height: number } | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const ghostRef = useRef<HTMLDivElement>(null);
  const layout = useRef(new Map<string, Rect>());
  const previewRef = useRef<Columns | null>(null);
  const pointer = useRef({ x: 0, y: 0, dx: 0, dy: 0 });
  const suppressClick = useRef(false);
  const shown = preview ?? columns;
  const shownKey = JSON.stringify(shown);

  // FLIP: after every rearrangement, move each box from where it was to where it is.
  useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    const next = new Map<string, Rect>();
    root.querySelectorAll<HTMLElement>("[data-fridge-item]").forEach(node => {
      node.style.transition = "none";
      node.style.transform = "";
      const id = node.dataset.fridgeItem!, rect = pageRect(node), before = layout.current.get(id);
      next.set(id, rect);
      if (!before || (Math.abs(before.x - rect.x) < 1 && Math.abs(before.y - rect.y) < 1)) return;
      node.style.transform = `translate(${before.x - rect.x}px, ${before.y - rect.y}px)`;
      void node.offsetWidth; // start the transition from the old place
      node.style.transition = EASE;
      node.style.transform = "";
    });
    layout.current = next;
  }, [container, shownKey, dragId]);

  // A resized window moves the shelves: remember the new places without animating.
  useEffect(() => {
    const remeasure = () => {
      const root = container.current; if (!root) return;
      const next = new Map<string, Rect>();
      root.querySelectorAll<HTMLElement>("[data-fridge-item]").forEach(node => next.set(node.dataset.fridgeItem!, pageRect(node)));
      layout.current = next;
    };
    window.addEventListener("resize", remeasure);
    return () => window.removeEventListener("resize", remeasure);
  }, [container]);

  const place = useCallback(() => {
    const node = ghostRef.current; if (!node) return;
    const { x, y, dx, dy } = pointer.current;
    node.style.transform = `translate(${x - dx}px, ${y - dy}px) rotate(2deg) scale(1.05)`;
  }, []);
  useLayoutEffect(() => { if (ghost) place(); }, [ghost, place]);

  const setShown = (value: Columns | null) => { previewRef.current = value; setPreview(value); };

  /** Where the dragged box would land for a pointer at (x, y): the first box in
   * reading order that the pointer sits before, in the compartment under it. */
  const retarget = (id: string, x: number, y: number) => {
    const target = document.elementsFromPoint(x, y).map(node => (node as HTMLElement).closest?.("[data-compartment]")).find(Boolean);
    const key = target?.getAttribute("data-compartment");
    const current = previewRef.current;
    if (!key || !current) return;
    setOver(key);
    const px = x + window.scrollX, py = y + window.scrollY;
    const next: Columns = Object.fromEntries(Object.entries(current).map(([k, ids]) => [k, ids.filter(other => other !== id)]));
    const ids = next[key] ?? (next[key] = []);
    let index = ids.length;
    for (let i = 0; i < ids.length; i += 1) {
      const r = layout.current.get(ids[i]);
      if (r && (py < r.y || (py <= r.y + r.h && px < r.x + r.w / 2))) { index = i; break; }
    }
    ids.splice(index, 0, id);
    if (!same(next, current)) setShown(next);
  };

  const finish = (id: string, keep: boolean) => {
    document.body.classList.remove("kw-dragging");
    const node = ghostRef.current;
    // The box settles from where it was let go into its slot.
    if (node) layout.current.set(id, pageRect(node));
    setGhost(null); setDragId(null); setOver(null);
    const final = previewRef.current;
    if (!keep || !final || same(final, columns)) { setShown(null); return; }
    void commit(final).finally(() => setShown(null));
  };

  const start = (event: ReactPointerEvent<HTMLElement>, id: string) => {
    if (event.button !== 0 || previewRef.current) return;
    suppressClick.current = false;
    const card = event.currentTarget, kind = event.pointerType, origin = { x: event.clientX, y: event.clientY };
    let active = false, hold = 0;
    const activate = (x: number, y: number) => {
      active = true; suppressClick.current = true;
      const r = card.getBoundingClientRect();
      pointer.current = { x, y, dx: x - r.left, dy: y - r.top };
      document.body.classList.add("kw-dragging");
      setShown(Object.fromEntries(Object.entries(columns).map(([k, ids]) => [k, [...ids]])));
      setDragId(id);
      setGhost({ id, width: r.width, height: r.height });
    };
    const move = (e: PointerEvent) => {
      if (!active) {
        const distance = Math.hypot(e.clientX - origin.x, e.clientY - origin.y);
        if (kind === "mouse" && distance > MOUSE_DISTANCE) activate(e.clientX, e.clientY);
        else if (kind !== "mouse" && distance > TOUCH_SLOP) stop();
        if (!active) return;
      }
      pointer.current = { ...pointer.current, x: e.clientX, y: e.clientY };
      place();
      retarget(id, e.clientX, e.clientY);
    };
    const touchmove = (e: TouchEvent) => { if (active) e.preventDefault(); };
    const up = () => { const was = active; stop(); if (was) finish(id, true); };
    const cancel = () => { const was = active; stop(); if (was) finish(id, false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") cancel(); };
    function stop() {
      window.clearTimeout(hold);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("touchmove", touchmove);
      window.removeEventListener("keydown", key);
    }
    if (kind !== "mouse") hold = window.setTimeout(() => activate(origin.x, origin.y), TOUCH_HOLD);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("touchmove", touchmove, { passive: false });
    window.addEventListener("keydown", key);
  };

  /** A click that ended a drag is not a click on the box. */
  const clicked = () => { const drag = suppressClick.current; suppressClick.current = false; return !drag; };

  return { shown, dragId, ghost, ghostRef, over, start, clicked };
}
