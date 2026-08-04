import type { Locale } from "@/i18n/catalog";

const mealLabels = {
  "zh-CN": {
    breakfast: "早餐",
    lunch: "午餐",
    dinner: "晚餐",
    snack: "加餐",
    kids: "儿童餐",
  },
  "en-US": {
    breakfast: "Breakfast",
    lunch: "Lunch",
    dinner: "Dinner",
    snack: "Snack",
    kids: "Kids",
  },
} as const;

export function mealLabel(value: string, locale: Locale) {
  return mealLabels[locale][value as keyof (typeof mealLabels)[Locale]] ?? value;
}
