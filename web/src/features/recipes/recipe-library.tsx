"use client";

import { Clock, MagnifyingGlass, PencilSimple, Plus, Trash, UsersThree } from "@phosphor-icons/react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useLocale } from "@/i18n/locale-context";
import { api } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import type { Recipe } from "@/lib/workspace-types";
import { mealLabel } from "@/lib/workspace-labels";

import { RecipeEditor } from "./recipe-editor";

const filters = ["all", "breakfast", "lunch", "dinner", "kids"] as const;

export function RecipeLibrary() {
  const { locale } = useLocale();
  const chinese = locale === "zh-CN";
  const resource = useResource<{ recipes: Recipe[] }>("/api/v1/recipes");
  const [filter, setFilter] = useState<(typeof filters)[number]>("all");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Recipe | null | undefined>(undefined);
  const recipes = useMemo(() => {
    const source = resource.data?.recipes ?? [];
    return source.filter(
      (recipe) =>
        (filter === "all" || recipe.meal_type === filter) &&
        recipe.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
    );
  }, [filter, query, resource.data]);

  async function remove(recipe: Recipe) {
    if (!window.confirm(chinese ? `删除“${recipe.name}”？` : `Delete “${recipe.name}”?`)) return;
    await api<void>(`/api/v1/recipes/${recipe.id}`, { method: "DELETE" });
    await resource.reload();
  }

  return (
    <section className="workspace-page recipe-library">
      <header className="workspace-page-header">
        <div>
          <p className="warm-eyebrow">{chinese ? "家庭菜谱" : "FAMILY RECIPES"}</p>
          <h1>{chinese ? "今天想做什么？" : "What shall we cook?"}</h1>
          <p>{chinese ? "保存家里的味道，也保留每个人的偏好。" : "Keep the recipes your family returns to, beautifully organized."}</p>
        </div>
        <button className="primary-action" type="button" onClick={() => setEditing(null)}>
          <Plus size={18} weight="bold" /> {chinese ? "添加菜谱" : "Add recipe"}
        </button>
      </header>
      <div className="recipe-toolbar">
        <div className="segmented-control" aria-label={chinese ? "菜谱分类" : "Recipe filters"}>
          {filters.map((item) => (
            <button className={filter === item ? "active" : ""} key={item} type="button" onClick={() => setFilter(item)}>
              {item === "all" ? (chinese ? "全部" : "All") : item === "kids" ? (chinese ? "儿童餐" : "Kids") : chinese ? { breakfast: "早餐", lunch: "午餐", dinner: "晚餐" }[item] : item[0].toUpperCase() + item.slice(1)}
            </button>
          ))}
        </div>
        <label className="search-field">
          <MagnifyingGlass size={18} />
          <input value={query} placeholder={chinese ? "搜索菜谱" : "Search recipes"} onChange={(event) => setQuery(event.target.value)} />
        </label>
      </div>
      {resource.loading ? <p className="warm-empty">{chinese ? "正在打开菜谱本…" : "Opening your recipe book…"}</p> : null}
      {resource.error ? <p className="warm-empty error">{resource.error}</p> : null}
      {!resource.loading && recipes.length === 0 ? <p className="warm-empty">{chinese ? "这里还没有菜谱，添加第一道吧。" : "No recipes here yet. Add the first one."}</p> : null}
      <div className="recipe-card-grid">
        {recipes.map((recipe, index) => (
          <article className="recipe-card" key={recipe.id}>
            <Link className="recipe-card-main" href={`/recipes/${recipe.id}`}>
              <div className={`recipe-card-number tone-${index % 3}`}>{String(index + 1).padStart(2, "0")}</div>
              <div>
                <span className="meal-label">{mealLabel(recipe.meal_type, locale)}</span>
                <h2>{recipe.name}</h2>
                <div className="recipe-meta">
                  <span><Clock size={15} /> {recipe.prep_minutes + recipe.cook_minutes} min</span>
                  <span><UsersThree size={15} /> {recipe.suitable_age_years}+ </span>
                </div>
              </div>
              <small>{recipe.is_owned_by_current_account ? (chinese ? "我的菜谱" : "My recipe") : recipe.owner_display_name}</small>
            </Link>
            {recipe.is_owned_by_current_account ? (
              <div className="card-actions">
                <button aria-label={chinese ? "编辑" : "Edit"} type="button" onClick={() => setEditing(recipe)}><PencilSimple size={17} /></button>
                <button aria-label={chinese ? "删除" : "Delete"} type="button" onClick={() => void remove(recipe)}><Trash size={17} /></button>
              </div>
            ) : null}
          </article>
        ))}
      </div>
      <button aria-label={chinese ? "添加菜谱" : "Add recipe"} className="floating-add" type="button" onClick={() => setEditing(null)}>
        <Plus size={24} weight="bold" />
      </button>
      <RecipeEditor
        key={editing === undefined ? "closed" : editing?.id ?? "new"}
        open={editing !== undefined}
        recipe={editing}
        onClose={() => setEditing(undefined)}
        onSaved={() => void resource.reload()}
      />
    </section>
  );
}
