"use client";
import { X } from "@phosphor-icons/react";
import { useEffect, useId, useRef, type ReactNode } from "react";

/** The close button calls `onClose`. Escape and a press outside the drawer are
 * more often slips, so they call `onDismiss` when given (which may ask first).
 * `prompt` is that question: right under the header, taking the focus. */
export function Drawer({title,subtitle,lead,onClose,onDismiss,children,footer,notice,prompt}:{title:string;subtitle?:string;lead?:ReactNode;onClose:()=>void;onDismiss?:()=>void;children:ReactNode;footer?:ReactNode;notice?:ReactNode;prompt?:ReactNode}) {
  const id=useId(), ref=useRef<HTMLElement>(null), closeRef=useRef(onDismiss??onClose), promptRef=useRef<HTMLDivElement>(null), asking=Boolean(prompt);
  useEffect(()=>{if(asking)promptRef.current?.querySelector<HTMLElement>("button")?.focus();},[asking]);
  useEffect(()=>{closeRef.current=onDismiss??onClose;},[onClose,onDismiss]);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;const node=ref.current;node?.querySelector<HTMLElement>("button")?.focus();function key(e:KeyboardEvent){if(e.key==="Escape"){e.preventDefault();closeRef.current();}if(e.key==="Tab"&&node){const items=[...node.querySelectorAll<HTMLElement>("*")].filter(el=>el.matches('button,input,select,textarea,a[href],[tabindex]')&&!el.matches(":disabled")&&el.tabIndex>=0);const first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}}document.addEventListener("keydown",key);function outside(e:PointerEvent){const target=e.target as Element|null;if(!node||!target||node.contains(target))return;if(target.closest(".kw-meal-open,.kw-modal,.kw-modal-backdrop,[role=dialog],.kw-navigation"))return;closeRef.current();}document.addEventListener("pointerdown",outside);return()=>{document.removeEventListener("keydown",key);document.removeEventListener("pointerdown",outside);previous?.focus();};},[]);
  return <aside ref={ref} className="kw-drawer" role="dialog" aria-modal="true" aria-labelledby={id}><header className="kw-drawer-header"><div><h2 id={id}>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><button className="kw-icon" aria-label="Close drawer" onClick={onClose}><X size={18}/></button></header>{prompt&&<div ref={promptRef} className="kw-drawer-prompt">{prompt}</div>}{lead&&<div className="kw-drawer-lead">{lead}</div>}{notice&&<div className="kw-drawer-notice">{notice}</div>}<div className="kw-drawer-body">{children}</div>{footer&&<footer className="kw-drawer-footer">{footer}</footer>}</aside>;
}
