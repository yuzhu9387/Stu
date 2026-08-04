"use client";

import { ArrowLeft, Check, MagicWand, Minus, Plus, Trash } from "@phosphor-icons/react";
import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { useLocale } from "@/i18n/locale-context";
import { api } from "@/lib/api";
import type { MealPlan } from "@/lib/workspace-types";
import { mealLabel } from "@/lib/workspace-labels";

const preferenceOptions = [
  { value: "Light", zh: "清淡" },
  { value: "High protein", zh: "高蛋白" },
  { value: "Low calorie", zh: "低卡" },
  { value: "Vegetarian", zh: "素食" },
  { value: "Less oil", zh: "少油" },
  { value: "Low sodium", zh: "低盐" },
];
const slotOrder: Record<string, number> = { breakfast: 0, lunch: 1, dinner: 2, snack: 3 };

function formatDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function monday() {
  const date = new Date();
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  return formatDate(date);
}

export function PlanGenerator() {
  const { locale } = useLocale();
  const chinese = locale === "zh-CN";
  const [weekStart, setWeekStart] = useState(monday());
  const [meals, setMeals] = useState(["breakfast", "lunch", "dinner"]);
  const [preferences, setPreferences] = useState(["Light"]);
  const [people, setPeople] = useState(2);
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState<MealPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const days = useMemo(() => {
    const start = new Date(`${weekStart}T12:00:00`);
    return Array.from({ length: 7 }, (_, index) => {
      const day = new Date(start);
      day.setDate(start.getDate() + index);
      return formatDate(day);
    });
  }, [weekStart]);

  function toggle(list: string[], value: string, setter: (next: string[]) => void) {
    setter(list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
  }

  async function generate(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      setResult(await api<MealPlan>("/api/v1/plans/generate", {
        method: "POST",
        body: JSON.stringify({
          title: chinese ? "AI 一周食谱" : "AI weekly plan",
          week_start: weekStart,
          days,
          meals,
          preferences,
          people_count: people,
          notes: notes || null,
        }),
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Generation failed");
    } finally {
      setLoading(false);
    }
  }

  async function removeItem(itemId: string) {
    if (!result) return;
    setResult(await api<MealPlan>(`/api/v1/plans/${result.id}/items/${itemId}`, { method: "DELETE" }));
  }

  return (
    <section className="workspace-page generator-page">
      <header className="generator-header">
        <Link className="quiet-link" href="/plan"><ArrowLeft size={18} /> {chinese ? "返回计划" : "Back to plan"}</Link>
        <div><p className="warm-eyebrow">{chinese ? "AI 计划助手" : "AI PLAN STUDIO"}</p><h1>{chinese ? "这一周，吃得轻松一点" : "Make this week feel lighter"}</h1><p>{chinese ? "告诉我时间、餐型和偏好，我会从家庭菜谱与新灵感中安排一周。" : "Choose the rhythm and preferences. The assistant will compose a full week from family favorites and fresh ideas."}</p></div>
      </header>
      {!result ? <form className="generator-form" onSubmit={generate}>
        <section className="generator-section"><span className="section-number">01</span><div><h2>{chinese ? "时间" : "Time"}</h2><p>{chinese ? "从哪一天开始？" : "When should the plan begin?"}</p><input type="date" value={weekStart} onChange={(event) => setWeekStart(event.target.value)} /></div></section>
        <section className="generator-section"><span className="section-number">02</span><div><h2>{chinese ? "餐型" : "Meals"}</h2><p>{chinese ? "希望安排哪些餐？" : "Which meals should be included?"}</p><div className="choice-chips">{["breakfast", "lunch", "dinner"].map((meal) => <button className={meals.includes(meal) ? "active" : ""} type="button" key={meal} onClick={() => toggle(meals, meal, setMeals)}>{meals.includes(meal) ? <Check size={14} /> : null}{chinese ? { breakfast: "早餐", lunch: "午餐", dinner: "晚餐" }[meal as "breakfast" | "lunch" | "dinner"] : meal}</button>)}</div></div></section>
        <section className="generator-section"><span className="section-number">03</span><div><h2>{chinese ? "口味偏好" : "Taste preferences"}</h2><p>{chinese ? "选几个这周想坚持的方向。" : "Choose a few intentions for the week."}</p><div className="choice-chips muted">{preferenceOptions.map((preference) => <button className={preferences.includes(preference.value) ? "active" : ""} type="button" key={preference.value} onClick={() => toggle(preferences, preference.value, setPreferences)}>{chinese ? preference.zh : preference.value}</button>)}</div></div></section>
        <section className="generator-section split"><span className="section-number">04</span><div><h2>{chinese ? "人数" : "People"}</h2><p>{chinese ? "这周有几个人一起吃？" : "How many people are eating?"}</p><div className="stepper"><button aria-label={chinese ? "减少人数" : "Decrease people"} type="button" onClick={() => setPeople((value) => Math.max(1, value - 1))}><Minus size={16} /></button><strong>{people}</strong><button aria-label={chinese ? "增加人数" : "Increase people"} type="button" onClick={() => setPeople((value) => Math.min(20, value + 1))}><Plus size={16} /></button></div></div><label><span>{chinese ? "特别备注" : "Special notes"}</span><textarea rows={4} value={notes} placeholder={chinese ? "例如：周三晚餐要快手，周末想吃得丰富一点" : "For example: a quick Wednesday dinner, something special on Sunday"} onChange={(event) => setNotes(event.target.value)} /></label></section>
        {error ? <p className="form-error">{error}</p> : null}
        <button className="generate-button" disabled={loading || meals.length === 0} type="submit"><MagicWand size={20} weight="fill" /> {loading ? (chinese ? "正在生成…" : "Generating…") : chinese ? "生成一周计划" : "Generate weekly plan"}</button>
      </form> : <section className="generated-result"><header><div><p className="warm-eyebrow">{chinese ? "计划已保存" : "PLAN SAVED"}</p><h2>{result.title}</h2><p>{chinese ? "已经写入你的账户，可以继续调整每一餐。" : "This plan is now in your account and ready to refine."}</p></div><div><button className="secondary-action" type="button" onClick={() => setResult(null)}><MagicWand size={17} /> {chinese ? "重新生成" : "Generate again"}</button><Link className="primary-action" href="/plan">{chinese ? "打开计划" : "Open plan"}</Link></div></header><div className="generated-grid">{days.map((day) => <article key={day}><header><strong>{new Intl.DateTimeFormat(locale, { weekday: "short" }).format(new Date(`${day}T12:00:00`))}</strong><span>{new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }).format(new Date(`${day}T12:00:00`))}</span></header>{result.items.filter((item) => item.day === day).sort((a, b) => (slotOrder[a.slot] ?? 9) - (slotOrder[b.slot] ?? 9)).map((item) => <div key={item.id}><span>{mealLabel(item.slot, locale)}</span><p>{item.recipe_name}</p><button aria-label={chinese ? "删除" : "Delete"} type="button" onClick={() => void removeItem(item.id)}><Trash size={15} /></button></div>)}</article>)}</div></section>}
    </section>
  );
}
