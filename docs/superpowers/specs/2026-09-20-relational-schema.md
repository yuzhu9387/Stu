# Relational schema for the Figma workspace (Calendar / Plan / Prep / Fridge / Recipes)

Date: 2026-09-20
Status: design, awaiting review before migration `0015`.
Scope: batches 1–3 only. Settings (`36:8`, `36:115`, `36:251`, `7:1135`) is deferred, so
per-member preference profiles, notifications, theme and account panels are out.
Identity is already built and is not touched: `accounts`, `households`,
`family_memberships`, `web_sessions`, `magic_links`.

Sources: frames `59:2`, `42:37`, `105:513`, `47:9`, `47:195`, `102:575`, `47:494`,
`7:800`, `7:651`, `110:5`, `7:949`, `36:1030`, `46:8`, `120:343` of
`exTOMpQuvjEJ4Y4VirSHoL`.

## Why this replaces the JSON aggregate

Today the whole household lives in `kitchen_workspaces.state`, one validated JSON
document, with `kitchen_operation_receipts` for idempotency. That made the first
version easy to ship but it duplicates the same facts in several places:

- An ingredient name is a free string on every recipe, and again on every fridge
  batch. `鸡肉丸` as a recipe, as a prep output and as a fridge item share nothing.
- Stock movements are stored twice: as `inventory[].portions` and again as
  `audit[].deltas`, kept consistent only by engine code.
- Guidance and knowledge are copied wholesale into every plan snapshot.
- Nothing can be queried. "Which recipes use 西兰花" needs a full document scan.

The UI now demands exactly the joins the blob cannot serve: the fridge popup
(`110:5`) links a batch to the meals that consume it, recipe detail (`36:1030`)
shows ratings and times-cooked, and plan analysis (`105:513`) reports fridge
utilisation. So the storage moves to normalised tables, one row per fact.

## Object model

Five aggregates, each with one root table. Everything is household-scoped and
cascades from `households.id`.

```
FoodItem ──┬─< RecipeIngredient >── Recipe ──┬─< RecipeStep
           │                                 ├─< RecipeReheatInstruction
           │                                 ├── RecipeNutrition (0..1)
           │                                 ├─< RecipeTag >── Tag
           │                                 ├─< RecipeEquipment >── Equipment
           │                                 ├─< RecipeMealSlot
           │                                 └─< RecipeRating
           └─< InventoryBatch ──< InventoryLedgerEntry

WeeklyPlan ─┬─< Meal ──┬─< MealComponent >── (Recipe | InventoryBatch | PrepTask)
            │          ├─< MealStep
            │          └─< MealEvent
            ├─< PrepTask ─┬─< PrepTaskStep
            │             ├─< PrepTaskInput >── InventoryBatch
            │             ├─< PrepTaskDependency
            │             └─< PrepTaskEquipment >── Equipment
            ├─< PlanPreset >── MealStylePreset
            ├─< PlanChatMessage ──< PlanChatReference >── Meal
            └─< PlanGuidanceSnapshot / PlanKnowledgeSnapshot >── *DocumentVersion
```

### The deduplication that matters

`FoodItem` is the shared vocabulary. One row per food per household, carrying the
name, the English name, the category and the emoji the cards render. A recipe
ingredient points at it, a fridge batch points at it, and later the per-member
favourite/avoid lists will point at the same row. Renaming 西兰花 updates every
surface at once, and "what uses this" becomes one join instead of a string scan.

`Equipment` and `Tag` are normalised the same way — the scheduler reserves
equipment by identity, not by a repeated string, so `wok` can never drift from
`Wok`.

`InventoryLedgerEntry` becomes the single source of truth for stock. A batch's
current portions is the sum of its ledger rows, so the balance and the history
can no longer disagree, and undo is an exact inverse entry rather than a JSON
patch.

Snapshots reference immutable `*_document_versions` rows rather than copying
content into each plan.

## Tables

Conventions follow the existing models: `Uuid` primary keys defaulting to
`uuid4()`, `StrEnum` for enumerations, timezone-aware `DateTime`, `Numeric` for
quantities so portion arithmetic stays exact.

### Shared vocabulary

**`food_items`** — canonical food, shared by recipes, fridge and preferences.

| column | type | notes |
| --- | --- | --- |
| `id` | uuid pk | |
| `household_id` | uuid fk → households | cascade |
| `name` | varchar(200) | original language, e.g. `鸡肉丸` |
| `name_en` | varchar(200) null | `Chicken Meatballs` from `110:5` |
| `category` | enum | `protein`, `carbs`, `vegetables`, `dairy`, `other` |
| `emoji` | varchar(16) null | `🥩`; replaces the `foodEmoji()` heuristic |
| `default_portion_grams` | numeric null | "每份约 100g" from `110:5`; null means unknown |
| `created_at` | timestamptz | |

Unique `(household_id, name)`. `dairy` is new — `110:5` groups 牛奶 under Dairy,
which today collapses into `Other`.

**`equipment`** — `(id, household_id, name)`, unique `(household_id, name)`.

**`tags`** — `(id, household_id, name)`, unique `(household_id, name)`.

### Recipes

**`kitchen_recipes`** — named to avoid colliding with the legacy `recipes` table,
which stays untouched for the old import/share routes.

| column | type | notes |
| --- | --- | --- |
| `id` | uuid pk | |
| `household_id` | uuid fk | |
| `name` / `name_en` | varchar(200) / null | `红烧排骨` / `Braised Pork Ribs` |
| `cuisine` | varchar(60) null | `中餐 Chinese` chip on `36:1030` |
| `hero_media_id` | uuid fk → media_objects null | recipe photo; reuses existing storage |
| `servings` | numeric | > 0 |
| `active_minutes` / `elapsed_minutes` | numeric | `elapsed >= active` enforced |
| `difficulty` | enum null | `easy`, `medium`, `hard` — the `⭐ Easy` pill on `42:37` |
| `is_favorite` | bool | the `♥ Favorite` toggle on `36:1030` |
| `incomplete` | bool | legacy import with unknown timing |
| `source_text` | text null | original pasted text, preserved on save |
| `source_url` | varchar(2000) null | |
| `created_at` / `updated_at` | timestamptz | |

Times cooked (`已做过 328 次`) is **not** a column — it is
`count(meal_events where kind='completed')` joined through `meal_components`, so
it cannot drift from execution history.

**`recipe_ingredients`** — `(id, recipe_id, food_item_id, group_label, quantity,
unit, position)`. `group_label` carries `36:1030`'s 肉类 / 辅料 / 调味糖色 / 调味料
grouping. Unique `(recipe_id, position)`.

**`recipe_steps`** — `(id, recipe_id, position, title, title_en, body,
active_minutes, wait_minutes)`. `36:1030` shows per-step timing (`⏱️ 5 min`),
which today is a plain string list. `wait_minutes` keeps the unattended tail
separate so the scheduler keeps working.

**`recipe_reheat_instructions`** — `(id, recipe_id, method, instruction,
position)`; `method` ∈ `microwave`, `steamer`, `pan`, `oven`, `other`. From the
复热说明 block on `36:1030`.

**`recipe_nutrition`** — `(recipe_id pk, calories, protein_g, carbs_g, fat_g,
fiber_g, source, updated_at)`. Every value nullable. `source` ∈ `user`,
`imported`, `unknown`. **Nothing derives these from tags or dish names**; absent
rows render as unknown, per product doc §5.3.

**`recipe_tags`** — `(recipe_id, tag_id)` composite pk.
**`recipe_equipment`** — `(recipe_id, equipment_id)` composite pk.
**`recipe_meal_slots`** — `(recipe_id, slot)` composite pk; slot ∈ `breakfast`,
`lunch`, `dinner`.

**`kitchen_recipe_ratings`** — `(id, recipe_id, account_id, stars 1..5,
created_at)`, unique `(recipe_id, account_id)`. `⭐ 4.9 (42 评分)` is
`avg(stars)` and `count(*)`, never a stored aggregate.

### Fridge

**`inventory_batches`** — one physical batch.

| column | type | notes |
| --- | --- | --- |
| `id` | uuid pk | |
| `household_id` | uuid fk | |
| `food_item_id` | uuid fk → food_items | |
| `recipe_id` | uuid fk → kitchen_recipes null | set when produced by prep |
| `portion_grams` | numeric null | overrides the food's default |
| `location` | enum | `fridge`, `freezer`, `pantry` |
| `prepared` | bool | cooked vs raw |
| `stored_on` | date | 存入日期 |
| `expires_on` | date null | 保质期 — new in `110:5` |
| `priority` | bool | "use first" |
| `notes` | text null | 备注, e.g. `周日 batch cook 做的` |
| `created_at` | timestamptz | |

Portions are **not** a column. The balance is
`sum(inventory_ledger_entries.delta)`, materialised through a view or a
maintained-in-transaction cache column with a `CHECK (portions >= 0)` guard.
The freshness pill (`剩余 7 天 Fresh ✨`) is computed from `expires_on`.

**`inventory_ledger_entries`** — every movement, append only.

`(id, household_id, batch_id, delta numeric, reason enum, meal_id null,
prep_task_id null, audit_id fk, created_at)` with `reason` ∈ `prep_output`,
`meal_consumption`, `leftover_return`, `manual_adjust`, `prep_input`,
`undo_reversal`. Index `(batch_id, created_at)`.

This replaces `audit[].deltas`. Undo writes a compensating row referencing the
original `audit_id` instead of mutating a balance.

### Plans

**`weekly_plans`** — `(id, household_id, week_start date, status enum
draft|confirmed, version int, base_plan_id null, base_version null, prompt text,
created_at, confirmed_at null)`. Unique `(household_id, week_start, id)`;
partial unique index enforcing at most one `confirmed` row per
`(household_id, week_start)`.

**`meals`** — merged with the slot, because `47:9` step 1 makes a slot a
first-class thing that exists whether or not it holds food.

`(id, plan_id, day date, slot enum, included bool, status enum
planned|completed|skipped, liked bool, locked bool, active_minutes,
elapsed_minutes, created_at)`, unique `(plan_id, day, slot)`.

`included=false` is the unchecked Sat/Sun breakfast on `47:9` — the slot is
deliberately not planned, which is different from planned-and-skipped.

**`meal_components`** — `(id, meal_id, position, name, portions,
food_item_id null, recipe_id null, inventory_batch_id null, prep_task_id null)`.
At least one reference must be set; a component is fresh cooking when only
`recipe_id` is set, and an allocation when a batch or prep is named.

**`meal_steps`** — `(id, meal_id, position, text)`.

**`meal_events`** — `(id, meal_id, kind enum completed|skipped|liked|unliked|
reopened, at, actor_id, audit_id)`. Execution history is append-only, so
"already made 328 times" and the undo rules read from the same place.

### Prep

**`prep_tasks`** — `(id, plan_id, recipe_id null, name, category enum
protein|carbs|vegetables|baking|other, planned_portions, actual_portions null,
active_minutes, elapsed_minutes, status enum, liked bool, output_batch_id fk
null, position)`.

**`prep_task_steps`** — `(id, prep_task_id, position, text)`.
**`prep_task_inputs`** — `(id, prep_task_id, inventory_batch_id, portions)`.
**`prep_task_dependencies`** — `(prep_task_id, depends_on_prep_task_id)`, with a
cycle check in the engine.
**`prep_task_equipment`** — `(prep_task_id, equipment_id)`.

### Planning inputs

**`meal_style_presets`** — the `47:9` catalog.
`(id, household_id, key, label, emoji, tint, enabled, position)`; seeded with
`home_cooked`, `light_healthy`, `meal_prep`, `baby_friendly`, `quick_30`,
`fridge_first`.

**`plan_presets`** — `(plan_id, preset_id)` composite pk; which presets a given
week selected.

**`weekly_prompts`** — `(id, household_id, week_start, prompt, updated_at)`,
unique `(household_id, week_start)`. Read by the Friday dispatcher before a plan
exists, so it stays separate from `weekly_plans`.

**`plan_chat_messages`** — `(id, plan_id, role, text, created_at)`.
**`plan_chat_references`** — `(message_id, meal_id)`, the `#Wed · Dinner` chips
on `105:513`.

### Guidance and knowledge

Kept because plans snapshot them, even though the Settings screens are deferred.

**`knowledge_documents`** — `(id, household_id, title, category, source_url,
enabled, current_version_id, created_at)`.
**`knowledge_document_versions`** — `(id, document_id, version, title, content,
created_at)`, unique `(document_id, version)`.
**`guidance_rules`** / **`guidance_rule_versions`** — the same shape.
**`plan_knowledge_snapshots`** — `(plan_id, document_version_id)`.
**`plan_guidance_snapshots`** — `(plan_id, guidance_version_id)`.

Snapshots now pin a version row instead of copying text into the plan.

### Operations

**`kitchen_audit_entries`** — `(id, household_id, kind, message, at, actor_id,
operation_id null, plan_id null, entity_id null, undo jsonb null, undone bool)`.
`kitchen_operation_receipts` is kept as is.

## Derived, never stored

`105:513`'s analysis panel and `59:2`'s day totals are computed per request:
day active minutes, prep elapsed via the existing scheduler, food-group balance,
fridge utilisation, variety warnings and the "friendly fix" suggestion. Storing
them would create a second source of truth for numbers the engine already
computes.

## Migration path

The JSON aggregate cannot be swapped out in one step without breaking the
engine, the MCP endpoint and AI generation at once. Staged instead:

### Progress

- **Done** — `0015`-`0019` create the tables. `backfill.py` copies the aggregate
  and is verified row-for-row against it. `relational_read.py` rebuilds the
  `Workspace` contract with zero differences for a real household, behind
  `RECIPE_AGENT_KITCHEN_RELATIONAL_READ` (default off).
- **Done** — Phase B group 1: `relational_write.project_recipes_and_tags` runs
  inside the command transaction, so `recipe.save/delete`, `tag.save/apply/
  delete` and any command carrying recipes keep the tables in step.
- **Done** — Phase B group 2: `project_inventory_and_audit` reconciles fridge
  batches, appends the stock ledger and the audit trail. A command's recorded
  deltas become ledger rows with their reason and audit link; anything the
  aggregate changed without a delta (a manual quantity edit, an opening
  balance) is squared up afterwards, so `portions == sum(ledger)` holds after
  every command rather than only after a backfill. Undo appends a compensating
  entry and flips `undone` instead of rewriting a balance.
- **Done** — Phase B group 3: `project_plans` writes plans, prep, meals,
  components, steps, chat and pinned snapshots; `project_knowledge_and_settings`
  and `project_prompts` cover the rest. `meal_events` is now populated from
  status and like transitions, so "已做过 N 次" has the rows the design says it
  counts. Every section is projected, and `kitchen_audit_entries.plan_id`
  resolves because plans are written before audit.
- **Ready to switch** — both paths render the same document after a full
  execution loop, including undo. `RECIPE_AGENT_KITCHEN_RELATIONAL_READ` still
  defaults off so the cutover is deliberate; enable it on a backfilled
  household, watch, and fall back by setting it false.

- **In progress** — Phase C, the new UI fields. Done: frame `110:5` (expiry and
  derived freshness, notes, grams per portion, food icon and English name, the
  `Dairy` category) and frame `47:9` (per-slot `included`, the Meal Style Preset
  catalog and per-week selection), frame `36:1030` (English name, cuisine,
  difficulty, hero image URL, ingredient grouping, per-step titles and timing,
  reheating instructions, nutrition, ratings) and frame `105:513` (plan
  analysis with variety warnings and an applicable fix).

Two things on `105:513` stay derived rather than stored, computed in
`web/src/features/kitchen/analysis.ts` with its own tests: the headline counts
and the warnings. A warning states the number it counted and the rule it
applied so it can be argued with, and never claims a nutritional effect. A fix
is only offered when the engine would accept it — it has to suit the slot, fit
the day's hands-on budget and clear the repeat gap — and "already used" is
resolved through recipe id, fridge batch, prep output and dish name, because a
stock-based component usually carries no recipe id and would otherwise look
unused.

An ordering rule learned three times over: any collection the aggregate keeps as
an ordered array needs its own `position` column. Rows written in one loop share
a `created_at` to the microsecond, so ordering by timestamp falls back to a
random UUID and the list silently reshuffles. Tags, audit entries, ledger rows
within an entry, allergies, recipes, fridge batches and plans all carry one.

Three columns were added along the way because the aggregate carries facts the
first schema could not: `prep_tasks.output_batch_key` (a planned task reserves
its output batch id before that batch exists, so it cannot be a foreign key),
`plan_*_snapshots.version` (the pinned number, kept on the link so a preserved
version row can take any free slot), and `household_allergies.position`
(Settings joins the list into one line, so order is user-visible).

1. `0015` creates every table above. Nothing reads them yet.
2. A backfill reads each `kitchen_workspaces.state` and writes the rows, keeping
   the existing string ids as natural keys so links survive.
3. The repository gains a relational read path behind a flag, verified by
   comparing its `Workspace` output against the JSON one for the same household.
4. Commands move across one group at a time — recipes and food items first, then
   inventory plus ledger, then plans, prep and execution.
5. `kitchen_workspaces` becomes the fallback, then is dropped in a later
   migration once the relational path has run clean.

The transport contract in `web/src/features/kitchen/types.ts` does **not** change
in step 1–4, so the frontend keeps working while storage moves underneath.

## Open questions

- `36:1030` shows per-recipe nutrition and `42:37` shows a difficulty rating.
  Both are stored as user-supplied values here and render as unknown when
  absent. Confirm that is the wanted behaviour rather than AI estimation.
- `110:5` links a batch to specific meals ("Wed Dinner", "Fri Dinner"). Modelled
  as existing `meal_components.inventory_batch_id` rows rather than a new join
  table, so the link and the allocation are the same fact.
