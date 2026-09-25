"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { createDemoState, emptyState, uid } from "./data";
import { applyDemoCommand } from "./demo-engine";
import type { CommandResult, KitchenState } from "./types";

export function useKitchen(demo: boolean) {
  const [state,setState]=useState<KitchenState>(emptyState);
  const current=useRef(state);
  const [loading,setLoading]=useState(true),[error,setError]=useState<string|null>(null),[unauthorized,setUnauthorized]=useState(false),[busy,setBusy]=useState(false);
  const busyRef=useRef(false);
  const accept=useCallback((value:KitchenState,force=false)=>{if(!force&&value.revision<current.current.revision)return;current.current=value;setState(value);if(demo)window.localStorage.setItem("stu-kitchen-demo-v1",JSON.stringify(value));},[demo]);
  const reload=useCallback(async()=>{try{if(demo){const stored=window.localStorage.getItem("stu-kitchen-demo-v1");let value=createDemoState();if(stored){try{const parsed=JSON.parse(stored) as KitchenState;if(Array.isArray(parsed.plans)&&Array.isArray(parsed.inventory)&&parsed.settings)value=parsed;}catch{}}accept(value);}else{accept(await api<KitchenState>("/api/v1/kitchen"));}setUnauthorized(false);setError(null);}catch(e){if(e instanceof ApiError&&e.status===401)accept(emptyState(),true);setUnauthorized(e instanceof ApiError&&e.status===401);setError(e instanceof Error?e.message:"Unable to load your kitchen.");}finally{setLoading(false);}},[demo,accept]);
  useEffect(()=>{const start=window.setTimeout(()=>void reload(),0);const focus=()=>{if(!demo&&!busyRef.current)void reload();};window.addEventListener("focus",focus);return()=>{window.clearTimeout(start);window.removeEventListener("focus",focus);};},[demo,reload]);
  const send=useCallback(async(type:string,payload:Record<string,unknown>,expectedRevision?:number):Promise<CommandResult>=>{if(busyRef.current)throw new Error("Please wait for the previous change to finish.");busyRef.current=true;setBusy(true);try{const command={type,payload,expectedRevision:expectedRevision??current.current.revision,operationId:uid()};const result=demo?applyDemoCommand(current.current,command):await api<CommandResult>("/api/v1/kitchen/commands",{method:"POST",body:JSON.stringify(command)});accept(result.state);return result;}catch(e){if(e instanceof ApiError&&e.status===409)await reload();throw e;}finally{busyRef.current=false;setBusy(false);}},[accept,demo,reload]);
  const reset=useCallback(()=>accept(createDemoState(),true),[accept]);
  return {state,loading,error,unauthorized,busy,send,reload,accept,reset};
}
