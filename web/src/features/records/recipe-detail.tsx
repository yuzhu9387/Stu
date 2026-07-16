"use client";

import { useLocale } from "@/i18n/locale-context";
import { useFeatureData } from "@/lib/use-feature-data";

interface RecipeDetailData {
  id: string;
  name: string;
  owner_display_name: string;
  is_owned_by_current_account: boolean;
  visibility: string;
  ingredients: { name: string; quantity: string | number | null; unit: string | null }[];
  steps: { number: number; text: string }[];
}

export function RecipeDetail({ id }: { id: string }) {
  const { locale } = useLocale();
  const state = useFeatureData<RecipeDetailData>(`/api/v1/recipes/${id}`);
  const chinese = locale === "zh-CN";
  if (state.status === "loading") return <p className="empty-state">{chinese ? "正在加载菜谱…" : "Loading recipe…"}</p>;
  if (state.status === "error") return <p className="empty-state" role="alert">{chinese ? "找不到这道菜谱。" : "Recipe not found."}</p>;
  const recipe = state.data;
  return <section className="feature-screen">
    <header className="feature-header"><div><p className="eyebrow">{chinese ? "家庭菜谱" : "FAMILY RECIPE"}</p><h1>{recipe.name}</h1>
      <p className="feature-description">{chinese ? "所有者" : "Owner"}: {recipe.is_owned_by_current_account ? (chinese ? "我" : "Me") : recipe.owner_display_name}</p></div></header>
    <div className="record-grid">
      <article className="record-card"><span className="record-index">01</span><div><h2>{chinese ? "食材" : "Ingredients"}</h2><p>{recipe.ingredients.map((item) => [item.name, item.quantity, item.unit].filter(Boolean).join(" ")).join(" · ")}</p></div><small>{recipe.visibility}</small></article>
      <article className="record-card"><span className="record-index">02</span><div><h2>{chinese ? "步骤" : "Method"}</h2><p>{recipe.steps.map((step) => `${step.number}. ${step.text}`).join(" ")}</p></div><small>{recipe.steps.length} {chinese ? "步" : "steps"}</small></article>
    </div>
  </section>;
}
