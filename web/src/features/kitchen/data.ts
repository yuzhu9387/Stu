import type { KitchenState, Meal, MealSlot, Recipe } from "./types";

export const foodTypes = ["Protein", "Carbs", "Vegetables", "Other"] as const;
export const slots: MealSlot[] = ["breakfast", "lunch", "dinner"];
export const uid = () => crypto.randomUUID();
export function weekDays(week: string) { return Array.from({ length: 7 }, (_, i) => { const d = new Date(`${week}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + i); return d.toISOString().slice(0, 10); }); }
export function mondayOf(date = new Date()) { const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10); }
export function shiftWeek(week: string, offset: number) { const d = new Date(`${week}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + offset * 7); return d.toISOString().slice(0, 10); }
const shortDateFormat = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
const longDateFormat = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" });
const weekDateFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
export function dayLabel(day: string, long = false) { return (long ? longDateFormat : shortDateFormat).format(new Date(`${day}T12:00:00Z`)); }
export function weekLabel(week: string) { const d = weekDays(week); return `${weekDateFormat.format(new Date(`${d[0]}T12:00:00Z`))}-${new Date(`${d[6]}T12:00:00Z`).getUTCDate()}, ${week.slice(0, 4)}`; }
export function minutes(n: number) { return n < 60 ? `${n} min` : `${Math.floor(n / 60)}h${n % 60 ? ` ${n % 60}m` : ""}`; }
export function emptyState(): KitchenState { return { revision: 0, recipes: [], knowledgeDocuments: [], inventory: [], plans: [], tags: [], audit: [], settings: { people: 3, childAge: 3, allergies: [], timezone: "America/Los_Angeles", generateTime: "17:00", prepDay: 6, maxPrepMinutes: 240, maxDailyActiveMinutes: 30, newRecipesPerWeek: 2, recipeRepeatGapDays: 1, guidance: [] } }; }

export function createDemoState(): KitchenState {
  const state = emptyState();
  state.tags = ["Baby-friendly", "Breakfast", "Batch cooking", "Protein", "Quick"];
  const recipe = (id: string, name: string, type: Recipe["type"], mealTypes: MealSlot[], active: number, elapsed: number, ingredients: Recipe["ingredients"], steps: string[]): Recipe => ({id,name,type,mealTypes,tags:["Baby-friendly", "Batch cooking"],servings:6,activeMinutes:active,elapsedMinutes:elapsed,ingredients,steps,liked:false,source:"Family recipe · demo"});
  state.recipes = [
    recipe("recipe-meatballs","鸡肉丸", "Protein",["lunch","dinner"],35,55,[{name:"Chicken mince",quantity:500,unit:"g"},{name:"Carrot",quantity:1,unit:"piece"}], ["Mix chicken mince and finely grated carrot.","Shape into small, evenly sized meatballs.","Cook thoroughly, checking the center is cooked.","Cool as appropriate, portion and store. Label the portions."]),
    recipe("recipe-rice","熟糙米饭", "Carbs",["lunch","dinner"],10,45,[{name:"Brown rice",quantity:2,unit:"cups"}], ["Rinse the rice.","Cook with the appropriate amount of water.","Portion, label and store appropriately."]),
    recipe("recipe-broccoli","西兰花", "Vegetables",["lunch","dinner"],10,15,[{name:"Broccoli",quantity:2,unit:"heads"}], ["Wash and cut into small florets.","Cook until tender; adjust texture for the child.","Portion and store appropriately."]),
    recipe("recipe-oats","牛奶燕麦粥", "Carbs",["breakfast"],5,10,[{name:"Oats",quantity:1,unit:"cup"},{name:"Milk",quantity:2,unit:"cups"}], ["Combine oats and milk.","Simmer, stirring, until soft.","Serve with fruit, at an appropriate temperature."]),
    recipe("recipe-noodles","番茄牛肉面", "Protein",["lunch","dinner"],12,20,[{name:"Tomatoes",quantity:2,unit:"pieces"},{name:"Cooked beef",quantity:3,unit:"portions"},{name:"Noodles",quantity:3,unit:"portions"}], ["Warm the cooked beef and chopped tomatoes.","Cook noodles according to the package.","Combine and serve with vegetables."]),
    recipe("recipe-toast","鸡蛋三明治", "Protein",["breakfast","lunch"],7,10,[{name:"Bread",quantity:6,unit:"slices"},{name:"Cooked eggs",quantity:3,unit:"pieces"}], ["Prepare the egg filling.","Toast the bread and assemble.","Cut into suitable pieces and serve."]),
  ];
  state.inventory = [
    {id:"stock-meatballs",name:"鸡肉丸",type:"Protein",portions:2,location:"Freezer",prepared:true,addedOn:"2026-09-13",recipeId:"recipe-meatballs",priority:true},
    {id:"stock-rice",name:"熟糙米饭",type:"Carbs",portions:6,location:"Freezer",prepared:true,addedOn:"2026-09-16",recipeId:"recipe-rice",priority:false},
    {id:"stock-broccoli",name:"西兰花",type:"Vegetables",portions:4,location:"Freezer",prepared:true,addedOn:"2026-09-16",recipeId:"recipe-broccoli",priority:false},
  ];
  const names = [["牛奶燕麦粥", "水煮蛋 · 全麦吐司", "红薯 · 豆浆", "牛奶燕麦粥", "水果燕麦碗", "鸡蛋三明治", "南瓜粥 · 鸡蛋"],["糙米饭 · 西葫芦", "意面 · 番茄肉酱", "菜披萨", "胡萝卜烩饭", "鸡肉丸三明治", "豆腐蔬菜饭", "蛋炒饭"],["番茄牛肉面", "香煎三文鱼", "鸡肉丸 · 糙米饭 · 西兰花", "清蒸鲈鱼", "鸡肉丸 · 意面", "鸡肉焗饭", "蔬菜汤 · 吐司"]];
  const meals: Meal[] = weekDays("2026-09-21").flatMap((day,i)=>slots.map((slot,j)=>({id:`meal-${i}-${slot}`,day,slot,components:[{id:`component-${i}-${j}`,name:names[j][i],type:"Other" as const,portions:3,recipeId:j===0&&i%3===0?"recipe-oats":undefined}],activeMinutes:[5,8,10][j],elapsedMinutes:[10,15,20][j],steps:["Gather the ingredients and check the portions.","Prepare the meal using its recipe, adapting texture for your child.","Plate, serve and tidy the workspace."],status:"planned",liked:false,locked:false})));
  const wed=meals.find(m=>m.id==="meal-2-dinner")!;
  wed.components = state.inventory.map((s,i)=>({id:`wed-component-${i}`,name:s.name,type:s.type,portions:3,recipeId:s.recipeId,inventoryId:s.id,prepId:i===0?"prep-meatballs":undefined}));
  wed.activeMinutes=8;wed.elapsedMinutes=12;wed.steps=["Check the meatballs are thawed; allow the required time beforehand.","Reheat the cooked rice thoroughly.","Prepare the broccoli and heat the meatballs thoroughly.","Plate, serve and tidy up."];
  meals.find(m=>m.id==="meal-4-dinner")!.components=[{id:"fri-meatballs",name:"鸡肉丸",type:"Protein",portions:3,inventoryId:"stock-meatballs",recipeId:"recipe-meatballs",prepId:"prep-meatballs"},{id:"fri-pasta",name:"意面",type:"Carbs",portions:3}];
  state.plans=[{id:"plan-demo",weekStart:"2026-09-21",status:"confirmed",version:1,prompt:"Use the older chicken meatballs first. Keep weekday meals simple.",meals,prep:[{id:"prep-meatballs",name:"鸡肉丸",type:"Protein",recipeId:"recipe-meatballs",plannedPortions:6,actualPortions:0,activeMinutes:35,elapsedMinutes:55,steps:state.recipes[0].steps,status:"planned",liked:false,outputInventoryId:"stock-meatballs",inputs:[],equipment:["stove"],dependencies:[]}],chat:[]}];
  state.settings.guidance=[{id:"guide-balance",title:"A balanced family plate",content:"Include varied vegetables, a protein source and a carbohydrate source across family meals. Consider the child's needs and our saved dietary restrictions.",enabled:true,version:1},{id:"guide-rhythm",title:"Make the most of Sunday",content:"Reuse batch-cooked food in different combinations. Prefer older stock and keep daily hands-on work within 30 minutes.",enabled:true,version:1}];
  return state;
}

/** Frame 110:5 shows "剩余 N 天". Derived from expiresOn, never stored, and
 * absent when the item has no expiry recorded. */
export function freshness(expiresOn: string | undefined, today = new Date()) {
  if (!expiresOn) return null;
  const due = new Date(`${expiresOn}T12:00:00Z`);
  const noon = new Date(`${today.toISOString().slice(0, 10)}T12:00:00Z`);
  const days = Math.round((due.getTime() - noon.getTime()) / 86400000);
  if (days < 0) return { days, label: `过期 ${-days} 天 Expired`, tone: "expired" as const };
  if (days === 0) return { days, label: "今天到期 Use today", tone: "due" as const };
  if (days <= 2) return { days, label: `剩余 ${days} 天 Use soon`, tone: "soon" as const };
  return { days, label: `剩余 ${days} 天 Fresh ✨`, tone: "fresh" as const };
}

/** `⭐ 4.9 (42 评分)` on frame 36:1030. Counted from the rows, never stored. */
export function ratingSummary(state: KitchenState, recipeId: string) {
  const rows = (state.recipeRatings ?? []).filter(r => r.recipeId === recipeId);
  if (!rows.length) return null;
  const total = rows.reduce((sum, r) => sum + r.stars, 0);
  return { average: Math.round((total / rows.length) * 10) / 10, count: rows.length };
}

/** `已做过 N 次` on frame 36:1030. Counted from completed meals that used the
 * recipe, so it cannot drift from execution history. */
export function timesCooked(state: KitchenState, recipeId: string) {
  return state.plans.reduce(
    (total, plan) =>
      total +
      plan.meals.filter(
        meal =>
          meal.status === "completed" &&
          meal.components.some(component => component.recipeId === recipeId),
      ).length,
    0,
  );
}

export const REHEAT_LABELS: Record<string, string> = {
  microwave: "微波炉 Microwave",
  steamer: "蒸锅 Steamer",
  pan: "炒锅 Pan",
  oven: "烤箱 Oven",
  other: "其他 Other",
};
