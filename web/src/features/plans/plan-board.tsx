"use client";

import { ArrowClockwise, CalendarDots, MagicWand, PencilSimple, Plus, Trash } from "@phosphor-icons/react";
import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { WorkspaceDialog } from "@/components/workspace-dialog";
import { useLocale } from "@/i18n/locale-context";
import { api } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import type { MealPlan, PlanItem, Recipe } from "@/lib/workspace-types";
import { mealLabel } from "@/lib/workspace-labels";

const slotOrder: Record<string, number> = { breakfast: 0, lunch: 1, dinner: 2, snack: 3 };

function localDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function startOfWeek() {
  const today = new Date();
  const day = today.getDay() || 7;
  today.setDate(today.getDate() - day + 1);
  return localDate(today);
}

export function PlanBoard() {
  const { locale } = useLocale();
  const chinese = locale === "zh-CN";
  const plans = useResource<{ plans: MealPlan[] }>("/api/v1/plans");
  const recipes = useResource<{ recipes: Recipe[] }>("/api/v1/recipes");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [planDialog, setPlanDialog] = useState(false);
  const [itemDialog, setItemDialog] = useState<PlanItem | null | undefined>(undefined);
  const availablePlans = plans.data?.plans ?? [];
  const selected = availablePlans.find((plan) => plan.id === selectedId) ?? availablePlans[0] ?? null;
  const days = useMemo(() => {
    if (!selected) return [];
    return Array.from(new Set(selected.items.map((item) => item.day))).sort();
  }, [selected]);

  async function removePlan() {
    if (!selected || !window.confirm(chinese ? "删除整个计划？" : "Delete this plan?")) return;
    await api<void>(`/api/v1/plans/${selected.id}`, { method: "DELETE" });
    setSelectedId(null);
    await plans.reload();
  }

  async function removeItem(item: PlanItem) {
    if (!selected) return;
    await api<MealPlan>(`/api/v1/plans/${selected.id}/items/${item.id}`, { method: "DELETE" });
    await plans.reload();
  }

  async function savePlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = { title: String(form.get("title")), week_start: String(form.get("week_start")) };
    const saved = selected
      ? await api<MealPlan>(`/api/v1/plans/${selected.id}`, { method: "PATCH", body: JSON.stringify(payload) })
      : await api<MealPlan>("/api/v1/plans", { method: "POST", body: JSON.stringify({ ...payload, items: [] }) });
    setSelectedId(saved.id);
    setPlanDialog(false);
    await plans.reload();
  }

  async function saveItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    const form = new FormData(event.currentTarget);
    const recipe = recipes.data?.recipes.find((entry) => entry.id === form.get("recipe_id"));
    if (!recipe) return;
    const payload = {
      day: String(form.get("day")),
      slot: String(form.get("slot")),
      recipe_id: recipe.id,
      recipe_name: recipe.name,
    };
    const path = itemDialog
      ? `/api/v1/plans/${selected.id}/items/${itemDialog.id}`
      : `/api/v1/plans/${selected.id}/items`;
    await api<MealPlan>(path, { method: itemDialog ? "PATCH" : "POST", body: JSON.stringify(payload) });
    setItemDialog(undefined);
    await plans.reload();
  }

  return (
    <section className="workspace-page plan-board">
      <header className="workspace-page-header">
        <div>
          <p className="warm-eyebrow">{chinese ? "每周计划" : "WEEKLY RHYTHM"}</p>
          <h1>{chinese ? "把一周安排得刚刚好" : "A calmer week starts here"}</h1>
          <p>{chinese ? "安排每一餐，也可以让 AI 根据家里的菜谱生成完整计划。" : "Shape each meal yourself, or let AI build a thoughtful first draft."}</p>
        </div>
        <Link className="primary-action" href="/plan/generate"><MagicWand size={18} /> {chinese ? "AI 生成计划" : "Generate with AI"}</Link>
      </header>
      <div className="plan-toolbar">
        <label>
          <span>{chinese ? "当前计划" : "Current plan"}</span>
          <select value={selected?.id ?? ""} onChange={(event) => setSelectedId(event.target.value)}>
            {availablePlans.map((plan) => <option key={plan.id} value={plan.id}>{plan.title} · {plan.week_start}</option>)}
          </select>
        </label>
        <div>
          <button className="secondary-action" type="button" onClick={() => setPlanDialog(true)}>{selected ? <PencilSimple size={17} /> : <Plus size={17} />}{selected ? (chinese ? "编辑计划" : "Edit plan") : chinese ? "新建计划" : "New plan"}</button>
          {selected?.is_owned_by_current_account ? <button aria-label={chinese ? "删除计划" : "Delete plan"} className="icon-button danger" type="button" onClick={() => void removePlan()}><Trash size={18} /></button> : null}
        </div>
      </div>
      {plans.loading ? <p className="warm-empty">{chinese ? "正在整理餐桌…" : "Setting the table…"}</p> : null}
      {!plans.loading && !selected ? <div className="warm-empty"><CalendarDots size={32} /><p>{chinese ? "还没有计划。创建一个空白计划，或请 AI 帮忙。" : "No plan yet. Start blank or ask AI for a first draft."}</p><button className="primary-action" type="button" onClick={() => setPlanDialog(true)}><Plus size={17} /> {chinese ? "新建计划" : "New plan"}</button></div> : null}
      {selected ? <div className="day-stack">
        {(days.length ? days : [selected.week_start]).map((day) => {
          const entries = selected.items
            .filter((item) => item.day === day)
            .sort((a, b) => (slotOrder[a.slot] ?? 9) - (slotOrder[b.slot] ?? 9));
          return <section className="day-card" key={day}>
            <header><div><span>{new Intl.DateTimeFormat(locale, { weekday: "long" }).format(new Date(`${day}T12:00:00`))}</span><strong>{new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }).format(new Date(`${day}T12:00:00`))}</strong></div><button aria-label={chinese ? "添加餐食" : "Add meal"} className="icon-button" type="button" onClick={() => setItemDialog(null)}><Plus size={18} /></button></header>
            <div className="meal-row-list">
              {entries.map((item) => <article className="meal-row" key={item.id}>
                <span className={`meal-slot ${item.slot}`}>{mealLabel(item.slot, locale)}</span><h3>{item.recipe_name}</h3>
                {selected.is_owned_by_current_account ? <div><button aria-label={chinese ? "编辑餐食" : "Edit meal"} className="icon-button" type="button" onClick={() => setItemDialog(item)}><PencilSimple size={16} /></button><button aria-label={chinese ? "删除餐食" : "Delete meal"} className="icon-button danger" type="button" onClick={() => void removeItem(item)}><Trash size={16} /></button></div> : null}
              </article>)}
              {entries.length === 0 ? <button className="empty-meal" type="button" onClick={() => setItemDialog(null)}><Plus size={16} /> {chinese ? "添加一餐" : "Add a meal"}</button> : null}
            </div>
          </section>;
        })}
      </div> : null}
      <WorkspaceDialog open={planDialog} title={selected ? (chinese ? "编辑计划" : "Edit plan") : chinese ? "新建计划" : "New plan"} onClose={() => setPlanDialog(false)}>
        <form className="workspace-form" onSubmit={savePlan}>
          <label className="wide-field"><span>{chinese ? "计划名称" : "Plan title"}</span><input name="title" required defaultValue={selected?.title ?? (chinese ? "本周计划" : "Weekly plan")} /></label>
          <label className="wide-field"><span>{chinese ? "开始日期" : "Week starts"}</span><input name="week_start" required type="date" defaultValue={selected?.week_start ?? startOfWeek()} /></label>
          <div className="form-actions wide-field"><button className="secondary-action" type="button" onClick={() => setPlanDialog(false)}>{chinese ? "取消" : "Cancel"}</button><button className="primary-action" type="submit"><CalendarDots size={17} /> {chinese ? "保存" : "Save"}</button></div>
        </form>
      </WorkspaceDialog>
      <WorkspaceDialog open={itemDialog !== undefined} title={itemDialog ? (chinese ? "编辑餐食" : "Edit meal") : chinese ? "添加餐食" : "Add meal"} onClose={() => setItemDialog(undefined)}>
        <form className="workspace-form" onSubmit={saveItem}>
          <label><span>{chinese ? "日期" : "Day"}</span><input name="day" required type="date" defaultValue={itemDialog?.day ?? selected?.week_start} /></label>
          <label><span>{chinese ? "餐型" : "Meal"}</span><select name="slot" defaultValue={itemDialog?.slot ?? "dinner"}><option value="breakfast">{chinese ? "早餐" : "Breakfast"}</option><option value="lunch">{chinese ? "午餐" : "Lunch"}</option><option value="dinner">{chinese ? "晚餐" : "Dinner"}</option><option value="snack">{chinese ? "加餐" : "Snack"}</option></select></label>
          <label className="wide-field"><span>{chinese ? "菜谱" : "Recipe"}</span><select name="recipe_id" defaultValue={itemDialog?.recipe_id}>{recipes.data?.recipes.map((recipe) => <option key={recipe.id} value={recipe.id}>{recipe.name}</option>)}</select></label>
          <div className="form-actions wide-field"><button className="secondary-action" type="button" onClick={() => setItemDialog(undefined)}>{chinese ? "取消" : "Cancel"}</button><button className="primary-action" type="submit"><ArrowClockwise size={17} /> {chinese ? "保存" : "Save"}</button></div>
        </form>
      </WorkspaceDialog>
    </section>
  );
}
