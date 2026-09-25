"use client";
import { useState } from "react";
import { ArrowCounterClockwise } from "@phosphor-icons/react";
import type { Page } from "./types";

/** Opening account navigation should not render every recipe/calendar card. */
export function KitchenProfileMenu({ points, demo, onNavigate, onPrefetch, onReset }: {
  points: number; demo: boolean; onNavigate: (page: Page) => void;
  onPrefetch: (page: Page) => void; onReset: () => boolean;
}) {
  const [open, setOpen] = useState(false);
  return <div className="kw-user-menu">
    <span className="kw-points" title="10 points for each completed meal or prep task"><i/>{points} pts</span>
    <button className="kw-avatar" aria-label="Settings and knowledge" aria-expanded={open} onClick={()=>setOpen(v=>!v)}>🐱</button>
    {open && <div className="kw-profile-menu">
      <button aria-label="Settings" onMouseEnter={()=>onPrefetch("guidance")} onFocus={()=>onPrefetch("guidance")} onClick={()=>{setOpen(false);onNavigate("guidance");}}>Settings ⚙️</button>
      <button aria-label="Knowledge" onMouseEnter={()=>onPrefetch("knowledge")} onFocus={()=>onPrefetch("knowledge")} onClick={()=>{setOpen(false);onNavigate("knowledge");}}>Knowledge 📚</button>
      {demo && <button onClick={()=>{if(onReset())setOpen(false);}}><ArrowCounterClockwise size={16}/>Reset demo</button>}
    </div>}
  </div>;
}
