"use client";

import { ArrowLeft, Clock, PencilSimple, Trash, UsersThree } from "@phosphor-icons/react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { RecipeEditor } from "@/features/recipes/recipe-editor";
import { useLocale } from "@/i18n/locale-context";
import { api } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import type { Recipe } from "@/lib/workspace-types";
import { mealLabel } from "@/lib/workspace-labels";

export function RecipeDetail({ id }: { id: string }) {
  const { locale } = useLocale();
  const chinese = locale === "zh-CN";
  const router = useRouter();
  const resource = useResource<Recipe>(`/api/v1/recipes/${id}`);
  const [editing, setEditing] = useState(false);

  if (resource.loading) return <p className="warm-empty">{chinese ? "正在准备菜谱…" : "Preparing the recipe…"}</p>;
  if (resource.error || !resource.data) return <p className="warm-empty error">{chinese ? "找不到这道菜谱。" : "Recipe not found."}</p>;
  const recipe = resource.data;

  function formatQuantity(value: string | number | null) {
    if (value === null || value === "") return "";
    const number = Number(value);
    return Number.isFinite(number) ? new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(number) : String(value);
  }

  async function remove() {
    if (!window.confirm(chinese ? `删除“${recipe.name}”？` : `Delete “${recipe.name}”?`)) return;
    await api<void>(`/api/v1/recipes/${recipe.id}`, { method: "DELETE" });
    router.push("/recipes");
  }

  return (
    <section className="workspace-page recipe-detail-page">
      <div className="detail-top-actions">
        <Link className="quiet-link" href="/recipes"><ArrowLeft size={18} /> {chinese ? "返回菜谱" : "Back to recipes"}</Link>
        {recipe.is_owned_by_current_account ? <div>
          <button aria-label={chinese ? "编辑菜谱" : "Edit recipe"} className="icon-button" type="button" onClick={() => setEditing(true)}><PencilSimple size={18} /></button>
          <button aria-label={chinese ? "删除菜谱" : "Delete recipe"} className="icon-button danger" type="button" onClick={() => void remove()}><Trash size={18} /></button>
        </div> : null}
      </div>
      <div className="recipe-hero">
        <Image priority alt={recipe.name} fill sizes="(max-width: 900px) 100vw, 900px" src={recipe.image_url || "/assets/honey-soy-chicken.png"} />
        <div className="recipe-hero-overlay" />
        <div className="recipe-hero-copy">
          <span className="meal-label light">{mealLabel(recipe.meal_type, locale)}</span>
          <h1>{recipe.name}</h1>
          <p>{chinese ? `由 ${recipe.is_owned_by_current_account ? "我" : recipe.owner_display_name} 收藏` : `Saved by ${recipe.is_owned_by_current_account ? "me" : recipe.owner_display_name}`}</p>
        </div>
      </div>
      <div className="detail-stat-row">
        <div><Clock size={20} /><span>{chinese ? "准备" : "Prep"}</span><strong>{recipe.prep_minutes} min</strong></div>
        <div><Clock size={20} /><span>{chinese ? "烹饪" : "Cook"}</span><strong>{recipe.cook_minutes} min</strong></div>
        <div><UsersThree size={20} /><span>{chinese ? "适合年龄" : "Suitable age"}</span><strong>{recipe.suitable_age_years}+</strong></div>
      </div>
      <div className="recipe-detail-grid">
        <article className="detail-panel ingredients-panel">
          <header><span>01</span><div><p>{chinese ? "准备" : "PREPARE"}</p><h2>{chinese ? "食材" : "Ingredients"}</h2></div></header>
          <ul>{(recipe.ingredients ?? []).map((item) => <li key={`${item.name}-${item.unit}`}><strong>{item.name}</strong><span>{[formatQuantity(item.quantity), item.unit].filter(Boolean).join(" ") || "—"}</span></li>)}</ul>
        </article>
        <article className="detail-panel steps-panel">
          <header><span>02</span><div><p>{chinese ? "开始烹饪" : "LET’S COOK"}</p><h2>{chinese ? "步骤" : "Method"}</h2></div></header>
          <ol>{(recipe.steps ?? []).map((step) => <li key={step.number}><span>{step.number}</span><p>{step.text}</p></li>)}</ol>
        </article>
      </div>
      <RecipeEditor
        key={editing ? recipe.id : "closed"}
        open={editing}
        recipe={recipe}
        onClose={() => setEditing(false)}
        onSaved={() => void resource.reload()}
      />
    </section>
  );
}
