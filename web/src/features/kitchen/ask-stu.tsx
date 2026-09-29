"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import type { KitchenState } from "./types";
import "./ask-stu.css";

const QUICK = /quick|快手|快速/i;

/** The demo's stand-in for Stu: what is in the fridge, what to use first, and
 * a quick recipe or two. */
export function demoAnswer(state: Pick<KitchenState, "inventory" | "recipes">): string {
  const foods = state.inventory.filter(item => item.portions > 0).sort((a, b) => Number(b.priority) - Number(a.priority) || Number(b.prepared) - Number(a.prepared) || (a.expiresOn ?? "9999").localeCompare(b.expiresOn ?? "9999"));
  if (!foods.length) return "冰箱是空的。先往冰箱里放点东西，或者翻翻菜谱书里的快手菜。（演示回答 · Demo answer）";
  const first = foods[0];
  const quick = state.recipes.filter(r => !r.incomplete && (r.liked || r.tags.some(tag => QUICK.test(tag)))).slice(0, 2).map(r => r.name);
  return `冰箱里有${foods.slice(0, 4).map(f => f.name).join("、")}。先用${first.name}${first.prepared ? "，加热就能吃" : ""}。${quick.length ? `快手菜可以做${quick.join("或")}。` : ""}（演示回答 · Demo answer）`;
}

/** A small box on the fridge page: ask Stu anything ("今晚吃什么？") and it
 * answers from the fridge and the quick recipes. It only answers; nothing in
 * the kitchen changes. */
export function AskStu({ state, demo }: { state: KitchenState; demo: boolean }) {
  const [question, setQuestion] = useState(""), [reply, setReply] = useState(""), [error, setError] = useState(""), [asking, setAsking] = useState(false);
  async function ask() {
    const message = question.trim();
    if (!message || asking) return;
    setAsking(true); setError("");
    try { setReply(demo ? demoAnswer(state) : (await api<{ reply: string }>("/api/v1/kitchen/ask", { method: "POST", body: JSON.stringify({ message }) })).reply); }
    catch (e) { setError(e instanceof Error ? e.message : "Stu could not answer just now. Please try again."); }
    finally { setAsking(false); }
  }
  return <form role="search" aria-label="Ask Stu" className="kw-ask-stu" onSubmit={e => { e.preventDefault(); void ask(); }}>
    <div className="kw-ask-row">
      <span aria-hidden="true">💬</span>
      <input className="kw-input" aria-label="Question for Stu" placeholder="Ask Stu · 今晚吃什么？" maxLength={1000} value={question} onChange={e => setQuestion(e.target.value)} />
      <button type="submit" className="kw-button" aria-busy={asking} disabled={!question.trim() || asking}>Ask</button>
    </div>
    <div aria-live="polite">{asking ? <p className="kw-ask-reply is-thinking">Stu is thinking…</p> : reply && <p className="kw-ask-reply">{reply}</p>}</div>
    {error && <p className="kw-error" role="alert">{error}</p>}
  </form>;
}
