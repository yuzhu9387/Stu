"use client";

import { FloppyDisk, Plus, Trash } from "@phosphor-icons/react";
import { useMemo, useState, type FormEvent } from "react";

import { WorkspaceDialog } from "@/components/workspace-dialog";
import { useLocale } from "@/i18n/locale-context";
import { api } from "@/lib/api";
import type { Recipe } from "@/lib/workspace-types";

const emptyRecipe = {
  name: "",
  meal_type: "dinner",
  prep_minutes: 15,
  cook_minutes: 30,
  suitable_age_years: 3,
  visibility: "family",
  image_url: "/assets/honey-soy-chicken.png",
  ingredients: "",
  steps: "",
};

export function RecipeEditor({
  open,
  recipe,
  onClose,
  onSaved,
}: {
  open: boolean;
  recipe?: Recipe | null;
  onClose: () => void;
  onSaved: (recipe: Recipe) => void;
}) {
  const { locale } = useLocale();
  const chinese = locale === "zh-CN";
  const initial = useMemo(
    () =>
      recipe
        ? {
            name: recipe.name,
            meal_type: recipe.meal_type,
            prep_minutes: recipe.prep_minutes,
            cook_minutes: recipe.cook_minutes,
            suitable_age_years: recipe.suitable_age_years,
            visibility: recipe.visibility,
            image_url: recipe.image_url ?? "/assets/honey-soy-chicken.png",
            ingredients: (recipe.ingredients ?? [])
              .map((item) => [item.name, item.quantity, item.unit].filter(Boolean).join(" | "))
              .join("\n"),
            steps: (recipe.steps ?? []).map((step) => step.text).join("\n"),
          }
        : emptyRecipe,
    [recipe],
  );
  const [form, setForm] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const ingredients = form.ingredients
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [name, quantity, unit] = line.split("|").map((part) => part.trim());
        const parsedQuantity = quantity ? Number(quantity) : null;
        return {
          name,
          quantity: Number.isFinite(parsedQuantity) ? parsedQuantity : null,
          unit: unit || null,
        };
      });
    const steps = form.steps
      .split("\n")
      .map((text) => text.trim())
      .filter(Boolean)
      .map((text, index) => ({ number: index + 1, text }));
    try {
      const saved = await api<Recipe>(recipe ? `/api/v1/recipes/${recipe.id}` : "/api/v1/recipes", {
        method: recipe ? "PATCH" : "POST",
        body: JSON.stringify({
          ...form,
          prep_minutes: Number(form.prep_minutes),
          cook_minutes: Number(form.cook_minutes),
          suitable_age_years: Number(form.suitable_age_years),
          ingredients,
          steps,
        }),
      });
      onSaved(saved);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save recipe");
    } finally {
      setSaving(false);
    }
  }

  function field<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  return (
    <WorkspaceDialog
      open={open}
      title={recipe ? (chinese ? "编辑菜谱" : "Edit recipe") : chinese ? "添加菜谱" : "Add recipe"}
      onClose={onClose}
    >
      <form className="workspace-form" onSubmit={submit}>
        <label className="wide-field">
          <span>{chinese ? "菜谱名称" : "Recipe name"}</span>
          <input required value={form.name} onChange={(event) => field("name", event.target.value)} />
        </label>
        <label>
          <span>{chinese ? "餐型" : "Meal"}</span>
          <select value={form.meal_type} onChange={(event) => field("meal_type", event.target.value)}>
            <option value="breakfast">{chinese ? "早餐" : "Breakfast"}</option>
            <option value="lunch">{chinese ? "午餐" : "Lunch"}</option>
            <option value="dinner">{chinese ? "晚餐" : "Dinner"}</option>
            <option value="kids">{chinese ? "儿童餐" : "Kids"}</option>
          </select>
        </label>
        <label>
          <span>{chinese ? "可见范围" : "Visibility"}</span>
          <select value={form.visibility} onChange={(event) => field("visibility", event.target.value)}>
            <option value="family">{chinese ? "家庭" : "Family"}</option>
            <option value="private">{chinese ? "仅自己" : "Private"}</option>
          </select>
        </label>
        <label>
          <span>{chinese ? "准备时间（分钟）" : "Prep minutes"}</span>
          <input min="0" type="number" value={form.prep_minutes} onChange={(event) => field("prep_minutes", Number(event.target.value))} />
        </label>
        <label>
          <span>{chinese ? "烹饪时间（分钟）" : "Cook minutes"}</span>
          <input min="0" type="number" value={form.cook_minutes} onChange={(event) => field("cook_minutes", Number(event.target.value))} />
        </label>
        <label>
          <span>{chinese ? "适合年龄" : "Suitable age"}</span>
          <input min="0" type="number" value={form.suitable_age_years} onChange={(event) => field("suitable_age_years", Number(event.target.value))} />
        </label>
        <label className="wide-field">
          <span>{chinese ? "图片地址" : "Image URL"}</span>
          <input value={form.image_url} onChange={(event) => field("image_url", event.target.value)} />
        </label>
        <label className="wide-field">
          <span>{chinese ? "食材（每行：名称 | 数量 | 单位）" : "Ingredients (name | quantity | unit)"}</span>
          <textarea rows={5} value={form.ingredients} onChange={(event) => field("ingredients", event.target.value)} />
        </label>
        <label className="wide-field">
          <span>{chinese ? "步骤（每行一步）" : "Steps (one per line)"}</span>
          <textarea rows={5} value={form.steps} onChange={(event) => field("steps", event.target.value)} />
        </label>
        {error ? <p className="form-error wide-field">{error}</p> : null}
        <div className="form-actions wide-field">
          <button className="secondary-action" type="button" onClick={onClose}>
            <Trash size={17} /> {chinese ? "取消" : "Cancel"}
          </button>
          <button className="primary-action" disabled={saving} type="submit">
            {recipe ? <FloppyDisk size={17} /> : <Plus size={17} />}
            {saving ? "…" : chinese ? "保存" : "Save"}
          </button>
        </div>
      </form>
    </WorkspaceDialog>
  );
}
