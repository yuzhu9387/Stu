export interface Ingredient {
  name: string;
  quantity: string | number | null;
  unit: string | null;
}

export interface RecipeStep {
  number: number;
  text: string;
}

export interface Recipe {
  id: string;
  owner_account_id: string;
  owner_display_name: string;
  is_owned_by_current_account: boolean;
  household_id: string;
  name: string;
  visibility: "private" | "family";
  meal_type: string;
  prep_minutes: number;
  cook_minutes: number;
  suitable_age_years: number;
  image_url: string | null;
  created_at: string;
  ingredients?: Ingredient[];
  steps?: RecipeStep[];
}

export interface PlanItem {
  id: string;
  day: string;
  slot: string;
  recipe_id: string;
  recipe_name: string;
  reason_codes: string[];
}

export interface MealPlan {
  id: string;
  owner_account_id: string;
  owner_display_name: string;
  is_owned_by_current_account: boolean;
  household_id: string;
  title: string;
  generated_by_ai: boolean;
  week_start: string;
  version: number;
  items: PlanItem[];
}

export interface Todo {
  id: string;
  owner_account_id: string;
  owner_display_name: string;
  is_owned_by_current_account: boolean;
  household_id: string;
  category: "grocery" | "todo";
  title: string;
  note: string | null;
  completed: boolean;
  visibility: "private" | "family";
  position: number;
  due_on: string | null;
  created_at: string;
  updated_at: string;
}
