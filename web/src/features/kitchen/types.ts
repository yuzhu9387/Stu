export type FoodType = "Protein" | "Carbs" | "Vegetables" | "Dairy" | "Other";
export type MealSlot = "breakfast" | "lunch" | "dinner";
export type ExecutionStatus = "planned" | "completed" | "skipped";
export interface Ingredient { name: string; quantity: number; unit: string; group?: string }
export interface StepDetail { index: number; title?: string; titleEn?: string; activeMinutes?: number; waitMinutes?: number }
export interface ReheatInstruction { method: "microwave"|"steamer"|"pan"|"oven"|"other"; instruction: string }
export interface RecipeNutrition { calories?: number; proteinG?: number; carbsG?: number; fatG?: number; fiberG?: number; source: "user"|"imported"|"unknown" }
export interface RecipeRating { recipeId: string; accountId: string; stars: number }
export interface Recipe { id: string; name: string; type: FoodType; mealTypes: MealSlot[]; tags: string[]; servings: number; activeMinutes: number; elapsedMinutes: number; ingredients: Ingredient[]; steps: string[]; liked: boolean; source: string; incomplete?: boolean; allergens?: string[]; equipment?: string[]; nameEn?: string; cuisine?: string; difficulty?: "easy"|"medium"|"hard"; heroImageUrl?: string; nutrition?: RecipeNutrition; reheat?: ReheatInstruction[]; stepDetails?: StepDetail[] }
export interface InventoryItem { id: string; name: string; type: FoodType; portions: number; location: string; prepared: boolean; addedOn: string; recipeId?: string; priority: boolean; expiresOn?: string; notes?: string; portionGrams?: number; emoji?: string; nameEn?: string }
export interface MealComponent { id: string; name: string; type: FoodType; portions: number; recipeId?: string; inventoryId?: string; prepId?: string }
export interface Meal { id: string; day: string; slot: MealSlot; included?: boolean; components: MealComponent[]; activeMinutes: number; elapsedMinutes: number; steps: string[]; status: ExecutionStatus; liked: boolean; locked: boolean }
export interface PrepTask { id: string; name: string; type: FoodType | "Baking"; recipeId?: string; plannedPortions: number; actualPortions: number; activeMinutes: number; elapsedMinutes: number; steps: string[]; status: ExecutionStatus; liked: boolean; outputInventoryId?: string; inputs: {inventoryId: string; portions: number}[]; equipment: string[]; dependencies: string[] }
export interface ChatMessage { id: string; role: "user" | "assistant"; text: string; mealIds?: string[] }
export type PlanStep = "preferences" | "adjust" | "confirmed" | "shopping";
export interface PlanningWorkflow { planId?: string; step: PlanStep; focus: "shopping" | "prep" }
export interface ShoppingRequirement { name:string; unit:string; group:string; required:number; inStock:number; toBuy:number; dishes:string[] }
export interface WeeklyPlan { fulfillment?:{stale?:boolean;recipeHashes?:Record<string,string>;batchRecipes?:string[];prepNotes?:Record<string,string>;shopping:ShoppingRequirement[];warnings:string[];generatedAt:string;source:"ai"}; shoppingChecked?: string[]; knowledgeSnapshot?:KnowledgeDocument[]; guidanceSnapshot?:Guidance[]; id: string; weekStart: string; status: "draft" | "confirmed"; version: number; basePlanId?: string; baseVersion?: number; prompt: string; meals: Meal[]; prep: PrepTask[]; chat: ChatMessage[]; presets?: string[] }
export interface MealStylePreset { key: string; label: string; emoji?: string; tint?: string; enabled: boolean }
export interface Guidance { id: string; title: string; content: string; enabled: boolean; version: number }
export interface KnowledgeDocument { id:string; title:string; content:string; category:string; sourceUrl?:string; enabled:boolean; version:number; updatedAt:string }
export type AnalysisMetric = "prep_time" | "daily_time" | "nutrition_balance" | "repetition" | "fridge_usage";
export interface KitchenSettings { pinnedTags?: string[]; recurringMeals?:{weekday:number;slot:MealSlot;meal:Meal;prep:PrepTask[]}[]; analysisMetrics?: AnalysisMetric[]; recipeRepeatGapDays?:number; people: number; childAge: number; allergies: string[]; timezone: string; generateTime: string; prepDay: number; maxPrepMinutes: number; maxDailyActiveMinutes: number; newRecipesPerWeek: number; guidance: Guidance[] }
export interface AuditEntry { undone?:boolean;planId?:string;entityId?:string;componentId?:string; id: string; kind: string; message: string; at: string; actorId?: string; operationId?: string; deltas?: {inventoryId: string; amount: number}[] }
export interface KitchenState { knowledgeDocuments?:KnowledgeDocument[]; mealStylePresets?: MealStylePreset[]; recipeRatings?: RecipeRating[]; weeklyPrompts?: {weekStart:string;prompt:string;workflow?:PlanningWorkflow}[]; revision: number; recipes: Recipe[]; inventory: InventoryItem[]; plans: WeeklyPlan[]; tags: string[]; settings: KitchenSettings; audit: AuditEntry[] }
export interface KitchenCommand { type: string; payload: Record<string, unknown>; expectedRevision: number; operationId: string }
export interface CommandResult { state: KitchenState; message: string }
export type Page = "calendar" | "plan" | "prep" | "fridge" | "recipes" | "guidance" | "knowledge";
export interface PageProps { state: KitchenState; plan: WeeklyPlan | null; send: (type: string, payload: Record<string, unknown>, options?: { quiet?: boolean }) => Promise<boolean>; notify: (message: string) => void; navigate: (page: Page, mealId?: string) => void; demo: boolean }
/** Stu's answer to a chat message: either changes to review, or — only when a
 * whole-week rebuild is ambiguous — one question with a few answers to tap. */
export interface ChatProposal { violations?:{kind:string;message:string}[]; recipes?:Recipe[]; prep?:PrepTask[]; reply: string; scope: string; meals: Meal[]; needsClarification: boolean; options?: string[] }
