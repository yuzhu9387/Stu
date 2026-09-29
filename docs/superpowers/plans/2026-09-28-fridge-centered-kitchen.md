# Fridge-centred Stu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the fridge page the home of Stu and connect planning, cooking, prep day, shopping and recipes to it, with AI only for small help.

**Architecture:** The JSON workspace aggregate stays the source of truth (`engine.apply_command`), projected into relational tables (`relational_write` / `relational_read`); every new field goes through contracts → engine → projection → read → frontend types → demo engine. New AI calls are preview-only endpoints on `KitchenAI` (like `compose`), never writes. The frontend keeps its page components; navigation moves from the top bar to the fridge page.

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy/Alembic (Postgres 16), LiteLLM provider; Next.js/React (TypeScript), Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-28-fridge-centered-kitchen-design.md`

## Global Constraints

- UI labels stay English; replies to the household in Chinese.
- Every AI endpoint is a preview: it never writes the workspace.
- A dish Stu fills or composes is **not** saved to the recipe book (only "Save to recipe 📖", by hand, does).
- `Changed` never takes stock from the fridge.
- Local verification writes only in `/demo`; the local database holds the real household.
- Migrations continue from `0035_dish_secondary_types`.
- Commands keep the pattern `{type, payload, expectedRevision, operationId}`; contracts use `extra="forbid"`.

## Review Focus

1. **Link import to a private address** (`http://localhost`, `10.x`, a public URL redirecting to `169.254.169.254`) must be refused before any request reaches it. → Task 5.1 tests.
2. **+ Prep when next week has no plan** must create a draft plan holding only prep, and a second + Prep must add to that same plan. → Task 3.2 tests.
3. **Prep done with 0 extra portions** must not leave an empty box in the fridge. → Task 3.1 tests.
4. **Put in fridge with a name already in the fridge** merges like `inventory.receive` (shared type/emoji), not a duplicate type. → Task 4.1 tests.
5. **Stu fill fails or times out** — the meal still saves with the blanks left blank. → Task 2.4 tests.

---

## Step 1 — Fridge home

### Task 1.1: Fridge page is home; doors to Recipes, Calendar, Plan; no top navigation

**Files:**
- Modify: `web/src/app/page.tsx` (redirect `/` → `/fridge`)
- Modify: `web/src/features/kitchen/workspace.tsx` (remove `<nav aria-label="Main navigation">`; logo goes to fridge; back bar "← 冰箱" on every page but the fridge; demo default page `fridge`)
- Create: `web/src/features/kitchen/fridge-doors.tsx` (book + two round buttons)
- Modify: `web/src/features/kitchen/fridge.tsx` (render doors beside the fridge)
- Create: `web/src/features/kitchen/fridge-doors.css`
- Test: `web/tests/kitchen-fridge-home.test.tsx`; update tests using "Main navigation" (`web/tests/*.tsx`, `web/tests/e2e/core-flow.spec.ts`)

**Interfaces:**
- Produces: `FridgeDoors({ onOpen }: { onOpen: (page: "recipes" | "calendar" | "plan") => void })`, rendered by `FridgePage` with `navigate`.
- `workspace.tsx` renders `<button className="kw-home-back" onClick={() => navigate("fridge")}>← 冰箱</button>` above page content when `page !== "fridge"`.

- [ ] Write failing tests:
```tsx
it("opens on the fridge, with Recipes, Calendar and Plan beside it", async () => {
  render(<KitchenWorkspace demo />);
  expect(await screen.findByRole("heading", { name: "Fridge" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "Main navigation" })).not.toBeInTheDocument();
  const doors = screen.getByRole("navigation", { name: "Kitchen" });
  expect(within(doors).getAllByRole("button").map(b => b.textContent)).toEqual(["📖Recipes", "📅Calendar", "📋Plan"]);
});
it("goes to Calendar and comes back with ← 冰箱", async () => { /* click Calendar → calendar region; click "← 冰箱" → Fridge heading */ });
```
- [ ] Run `npx vitest run tests/kitchen-fridge-home.test.tsx` → FAIL.
- [ ] Implement (doors: `<nav aria-label="Kitchen" className="kw-fridge-doors">` with `📖 Recipes` book button, `📅 Calendar` and `📋 Plan` round buttons; beside the fridge on wide screens, fixed bottom-right stack at ≤760px).
- [ ] Update every test and the e2e spec that clicked the top navigation to use the doors / back button.
- [ ] Run full web suite, lint, typecheck; e2e (`uv run python scripts/run-kitchen-e2e.py`).
- [ ] Commit: "The fridge is home: Recipes, Calendar and Plan open from beside it".

## Step 2 — Two drawers

### Task 2.1: A dish keeps its own ingredients and time; a meal can be Changed with a note (backend)

**Files:**
- Modify: `src/recipe_agent/domain/kitchen/contracts.py` (`MealComponent.ingredients: list[Ingredient] | None`, `activeMinutes`, `elapsedMinutes: Number | None`; `MealStatus = Literal["planned","completed","skipped","changed"]`; `Meal.status: MealStatus`; `Meal.note: str | None (max 500)`)
- Modify: `schema.py` (`ExecutionStatus.CHANGED`; `meals.note Text`; `meal_components.ingredients JSON`, `active_minutes`, `elapsed_minutes Numeric`)
- Create: `migrations/versions/0036_dish_details_and_changed_meals.py`
- Modify: `relational_write.py`, `relational_read.py`, `backfill.py` (round-trip the new fields)
- Modify: `engine.py` (`meal.status` accepts `changed` + optional `note`; no consumption; undo like skip)
- Modify: `shopping.py` (a component with no recipe uses its own `ingredients`)
- Modify: `scheduling.py` (`recompute_plan_timing` uses a component's own minutes when it has no recipe; `plan_rule_violations` "recipe" kind skips components with own minutes)
- Test: `tests/unit/kitchen/test_dish_details.py`, `tests/integration/kitchen/test_relational_plans.py`

- [ ] Failing tests: contract accepts dish ingredients/minutes; `meal.status changed` with note keeps stock, sets note, is undoable; shopping list lists a recipe-less dish's own ingredients (pantry staples still skipped); timing uses own minutes; relational round trip of note/status/ingredients/minutes.
- [ ] Implement; run backend suite + ruff + mypy; migration on an empty DB.
- [ ] Commit: "A dish keeps its own ingredients and time; a meal can be Changed with a note".

### Task 2.2: Stu fills a meal's blanks (backend `POST /api/v1/kitchen/fill`)

**Files:**
- Modify: `src/recipe_agent/domain/kitchen/ai.py` (`FillRequest`, `FilledDish`, `KitchenAI.fill`)
- Modify: `src/recipe_agent/api/v1/kitchen_ai.py` (route)
- Test: `tests/unit/kitchen/test_fill.py`

**Interfaces:**
- `FillRequest{slot: Slot, dishes: [FillDish{id, name, type?, secondaryTypes?, ingredients?, steps?, activeMinutes?, elapsedMinutes?}] (1..8), note: str = ""}`
- Response `{dishes: [{id, type, secondaryTypes?, ingredients, steps, activeMinutes, elapsedMinutes}]}` — only dishes asked for; **values the household gave are returned unchanged** (server overwrites model output with provided fields).

- [ ] Failing tests: provided fields never overwritten; unknown ids from the model dropped; ingredients with no amount dropped; guidance/people/allergies sent; nothing written.
- [ ] Implement (prompt: fill only what is missing, kid-first rules, portions = dish portions).
- [ ] Commit: "Stu fills the blanks of a meal's dishes (preview only)".

### Task 2.3: Calendar drawer — Done, Skip, Changed with a note (frontend)

**Files:**
- Modify: `web/src/features/kitchen/types.ts` (`ExecutionStatus` adds `"changed"`; `Meal.note?`; `MealComponent.ingredients?`, `activeMinutes?`, `elapsedMinutes?`)
- Modify: `web/src/features/kitchen/meal-drawer.tsx` (hero actions: add `↺ Changed` → inline note panel → `meal.status {status:"changed", note}`; show note; undo)
- Modify: `web/src/features/kitchen/calendar.tsx` (card shows "Changed" + note in title)
- Modify: `web/src/features/kitchen/demo-engine.ts` (`meal.status changed`, no consumption, note)
- Modify: `web/src/features/kitchen/analysis.ts`, `shopping.ts`, `schedule.ts` (treat `changed` like `skipped`; own ingredients/minutes for recipe-less dishes)
- Test: `web/tests/kitchen-changed.test.tsx`

- [ ] Failing tests: Changed with a note sends `meal.status` `{status:"changed", note}`; demo keeps stock; card shows Changed; empty note allowed.
- [ ] Implement; run suite.
- [ ] Commit: "Calendar drawer: Done, Skip, or Changed with a note".

### Task 2.4: Plan drawer — edit by dish; Stu fills blanks on save (frontend)

**Files:**
- Create: `web/src/features/kitchen/dish-card.tsx` (one dish: name, source select (fridge / recipe / own), portions, group + Also contains, ingredients (recipe's read-only, else own editable rows), steps (per dish), prep time)
- Create: `web/src/features/kitchen/fill.ts` (`blanks(meal, state)`, `fillMeal(meal, state, demo)` → calls `/fill` or demo filler, merges only blanks)
- Modify: `meal-drawer.tsx` (with `planning`, open in edit mode showing dish cards; Save button text "Save · Stu fills N blanks"; on fill failure save anyway with notice)
- Modify: `workspace.tsx` (plan page opens drawers with `initialEdit`)
- Test: `web/tests/kitchen-plan-drawer.test.tsx`

- [ ] Failing tests: plan page card opens straight into edit; dish cards show source, portions, groups, ingredients, steps, time; save with blanks calls fill and saves merged values; filled dish has no recipeId and no recipe is added; fill failure still saves (Review Focus 5); calendar page still opens the cooking view.
- [ ] Implement; run suite; check /demo desktop + phone.
- [ ] Commit: "Plan drawer edits dish by dish; Stu fills the blanks on save".

## Step 3 — 🔪 + Prep

### Task 3.1: Prep from the fridge (backend)

**Files:**
- Modify: `contracts.py` (`PrepTask.origin: Literal["fridge"] | None`)
- Modify: `schema.py` + `migrations/versions/0037_prep_origin_and_shopping.py` (`prep_tasks.origin String(16)`)
- Modify: `relational_write.py` / `relational_read.py` / `backfill.py`
- Modify: `engine.py` (`prep.status completed`: optional `location` (`freezer`|`fridge`), `actualPortions` may be 0 → no output box)
- Test: `tests/unit/kitchen/test_prep_from_fridge.py`

- [ ] Failing tests: completing a fridge prep consumes inputs, stores N extra portions in the chosen place; 0 extra leaves no box (Review Focus 3); undo restores; origin round-trips.
- [ ] Implement, run, commit: "Prep day can cook from fridge foods and store just the extra".

### Task 3.2: Fridge multi-select and + Prep; Prep day card (frontend)

**Files:**
- Create: `web/src/features/kitchen/fridge-select.tsx` (selection state + action bar "N selected · 🔪 + Prep · ✕")
- Create: `web/src/features/kitchen/prep-from-fridge.ts` (`addToPrep(state, foods, compose, send, today)`: compose → prep task `{origin:"fridge", inputs: uses, steps, minutes, plannedPortions: 0}` → `prep.save` into next week's plan, or `plan.save` a new draft `{meals:[], prep:[task]}`)
- Modify: `fridge.tsx` (select circle on cards; long-press on touch; action bar)
- Modify: `prep.tsx` (fridge-origin card: ingredients from fridge chips; Done asks "Extra portions" + ❄️/🧊; not a Quick task)
- Modify: `demo-engine.ts` (`prep.status` location / 0 portions)
- Test: `web/tests/kitchen-prep-from-fridge.test.tsx`

- [ ] Failing tests: select two foods → + Prep → a prep task with those inputs in next week's plan; with no plan a draft is created, second + Prep reuses it (Review Focus 2); Prep day Done with 4 extra → freezer box of 4; 0 extra → none; the dish is not in the recipe book.
- [ ] Implement, run, check /demo, commit: "🔪 + Prep: fridge foods go to prep day".

## Step 4 — Shopping note

### Task 4.1: Shopping list (backend)

**Files:**
- Modify: `contracts.py` (`ShoppingItem{id, name, quantity: float|None, checked: bool}`; `Workspace.shoppingList: list[ShoppingItem] = []`)
- Modify: `schema.py` + migration 0037 (`shopping_items` table: id, household_id, legacy_id, name, quantity, checked, position)
- Modify: `relational_write.py` / `relational_read.py` / `backfill.py`
- Modify: `engine.py` (`shopping.save {item}`, `shopping.delete {id}`, `shopping.putAway {items:[{id, location, portions, type?}]}` → receive into fridge (same merge as `inventory.receive`) and remove those rows)
- Test: `tests/unit/kitchen/test_shopping_note.py`, relational round trip

- [ ] Failing tests: add / check / delete; put away merges with an existing same-name food's type and emoji (Review Focus 4); rows leave the list; relational round trip.
- [ ] Implement, run, commit: "A shopping note on the fridge: add, tick, put away".

### Task 4.2: Shopping note (frontend)

**Files:**
- Create: `web/src/features/kitchen/shopping-note.tsx` (note on the fridge door; drawer with rows, add field, ticks, Put in fridge with location/portions per row)
- Modify: `fridge.tsx`, `types.ts`, `demo-engine.ts`, `data.ts` (`shoppingList: []`)
- Test: `web/tests/kitchen-shopping-note.test.tsx`

- [ ] Failing tests: note shows first items and count; add "牛奶" qty 2; tick; Put in fridge sends `shopping.putAway`; demo adds to the fridge.
- [ ] Implement, run, commit: "Shopping note on the fridge door".

## Step 5 — Recipes

### Task 5.1: Import a recipe from a link (backend, SSRF-safe)

**Files:**
- Create: `src/recipe_agent/domain/kitchen/link_import.py` (`fetch_page_text(url) -> str`: http/https only; resolve host, refuse private/loopback/link-local/multicast/reserved/unspecified addresses; manual redirects ≤3, each re-checked; 10 s; ≤2 MB; HTML → title, meta/og description, JSON-LD recipe text, visible text (no script/style), ≤20 000 chars)
- Modify: `ai.py` (`KitchenAI.import_link(scope, url)` → text → existing extract)
- Modify: `kitchen_ai.py` (`POST /import-link {url}`)
- Test: `tests/unit/kitchen/test_link_import.py` (with an injected transport/resolver)

- [ ] Failing tests: refuses `http://localhost`, `http://10.0.0.1`, `ftp://`, a redirect to `169.254.169.254` (Review Focus 1); over-size body refused; readable page → text contains title and description; empty text → "Paste the text or a screenshot instead".
- [ ] Implement, run, commit: "Recipes from a link, read safely".

### Task 5.2: Link import and "Uses my fridge" (frontend)

**Files:**
- Modify: `web/src/features/kitchen/import-review.tsx` / `recipes.tsx` (link field; call `/import-link`; demo sample)
- Create: `web/src/features/kitchen/fridge-match.ts` (`fridgeMatch(recipe, inventory) -> {have, total}`)
- Modify: `recipes.tsx` (toggle "Uses my fridge" sorts by `have/total`, card shows "🧊 3/5")
- Test: `web/tests/kitchen-recipe-link.test.tsx`

- [ ] Failing tests, implement, run, commit: "Import recipes from links; sort by what the fridge has".

## Step 6 — Ask Stu on the fridge

### Task 6.1: `POST /api/v1/kitchen/ask` and the fridge's ask box

**Files:**
- Modify: `ai.py` (`AskRequest{message}`, `KitchenAI.ask` → `{reply}`; context: fridge foods, Quick/liked recipes, enabled guidance, child age; read-only)
- Modify: `kitchen_ai.py` (route)
- Create: `web/src/features/kitchen/ask-stu.tsx` (input + reply on the fridge page; demo canned reply built from the fridge)
- Test: `tests/unit/kitchen/test_ask.py`, `web/tests/kitchen-ask-stu.test.tsx`

- [ ] Failing tests (payload has fridge + quick recipes; nothing written; UI shows reply and errors), implement, run, commit: "Ask Stu from the fridge".

## Finish

- [ ] Full backend + frontend + e2e suites; migrations on an empty database; /demo walkthrough at desktop and 390 px.
- [ ] Update the spec's section 5 note: meal status is a plain string column (no enum migration).
- [ ] Report; ask before pushing (a push deploys).
