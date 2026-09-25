# Kitchen workspace and editing drawer specification

Status: Implemented locally on 2026-09-17; production rollout requires the migration and provider checks in the runbook.
Sources: ../../product-redesign-proposal-2026-09-17.md, ../../prompts/page-design-and-interactions.md.
Visual reference: ../../design-assets/calendar-drawer-reference.png.

## Scope

Implement the approved Calendar / Plan / Prep / Fridge / Recipes / Planning guidance workflow in the existing Next.js and FastAPI application. Preserve existing authentication, legacy records, Lark and sharing routes. English interface; Unicode content. Production uses authenticated persistent state; `/demo` explicitly provides a local, resettable demonstration without authentication or claims of a live AI connection.

Use the supplied screenshot's compact ivory workspace, white sidebar and right drawer, sage selected states and actions, dark green sans-serif text, thin warm gray borders. No large editorial hero. All seven days remain reachable when drawer is open, with horizontal scrolling if needed. The screenshot's five visible columns are a cropped workspace, not a requirement to remove Saturday/Sunday.

## Drawer interaction

One reusable right-side drawer supports meal detail, meal editing and replacement. Desktop width 360–400 px, page remains visible; below 760 px use a full-screen drawer. Heading identifies day and meal. Body scrolls independently, footer actions remain reachable. Close button, Escape, focus restoration, accessible dialog name and focus containment. Unsaved edits require Save / Discard / Keep editing. Clicking another meal cannot discard dirty work.

Details: composition and portions, Active / Elapsed, stock allocations, prep readiness, today's steps, complete / skip / baby-liked, Edit meal, Replace, Reference in chat. Editing fields: date, breakfast/lunch/dinner, portions per component, recipe/component replacement. Save validates then updates the currently viewed draft or confirmed plan, increments revision, preserves stable meal IDs and history, and presents Undo. Executed meals cannot be structurally changed without undoing execution. Reference transfers exact selected meal IDs to Plan for the same week without sending a message.

## Shared data contract

JSON uses camelCase. The TypeScript interface in `web/src/features/kitchen/types.ts` is the transport reference; Python validation must match it.

- Workspace: revision, recipes[], inventory[], plans[], tags[], settings, audit[]. Production begins empty, with a safe import of accessible legacy recipes/plans where possible; no automatic demo seed in a real household.
- Recipe: id, name, type, mealTypes[], tags[], servings, activeMinutes, elapsedMinutes, ingredients[{name,quantity,unit}], steps[], liked, source; optional incomplete, allergens[], equipment[]. Missing values are not nutritional facts.
- Inventory: id, name, type, portions, location, prepared, addedOn, recipeId?, priority. Household default portions; unknown amounts do not get imaginary conversions.
- Plan: id, weekStart, status draft/confirmed, version, basePlanId?, baseVersion?, prompt, meals[], prep[], chat[]. Draft and confirmed versions are distinct objects; stable meal IDs may continue between them.
- Meal: id, day ISO date, slot, components[], activeMinutes, elapsedMinutes, steps[], status planned/completed/skipped, liked, locked. Component: id,name,type,portions,recipeId?,inventoryId?,prepId?.
- Prep: id,name,type,recipeId?,plannedPortions,actualPortions,activeMinutes,elapsedMinutes,steps[],status planned/completed/skipped,liked,outputInventoryId?,inputs[{inventoryId,portions}],equipment[],dependencies[].
- Settings: people,childAge,allergies[],timezone,generateTime,prepDay,maxPrepMinutes,maxDailyActiveMinutes,newRecipesPerWeek,guidance[]. Guidance: id,title,content,enabled,version.
- Audit: id,kind,message,at,actorId?,operationId?,deltas?. Keep enough ledger detail to reverse consumption exactly and reject unsafe reversal.

## HTTP and commands

`GET /api/v1/kitchen` returns Workspace. `POST /api/v1/kitchen/commands` accepts `{type,payload,expectedRevision,operationId}` and returns `{state,message}`. Requires session household scope; never accepts client-provided household/actor ownership. Stale revision returns 409, invalid state 422. Operation IDs deduplicate retries. All read-modify-write state is atomic; PostgreSQL row lock or compare-and-swap prevents lost updates. SQLAlchemy workspace record keyed by household_id with version and validated JSON; this is a coherent household aggregate, not an unvalidated arbitrary JSON replacement API. Keep legacy records untouched and retain source IDs when importing them.

Commands (payload fields):
- `recipe.save {recipe}`, `recipe.delete {id}` (reject deletion if currently referenced), `tag.save {name,previous?}`, `tag.delete {name}`.
- `inventory.save {item}`, `inventory.delete {id}`; preserve references or report invalidation; quantities finite and nonnegative.
- `settings.save {settings}`; validate IANA timezone and HH:mm; defaults 17:00 Friday, Sunday prep, 240 minutes ordinary elapsed (passive baking tail excluded), 30 daily active, 2 new recipes.
- `plan.save {plan}` for a fully validated proposal; `plan.confirm {id}` checks supply/prep and time, reconciles base version, sets confirmed. Conflicts cannot silently override other plans.
- `meal.save {planId,meal}`; stable ID; protect completed/locked meals against unauthorized AI mutation. `meal.status {planId,mealId,status}`; confirmed plan only. `meal.like {planId,mealId,liked}` independent of stock. `meal.lock {planId,mealId,locked}`.
- `prep.status {planId,prepId,status,actualPortions?}`; confirmed plan only, final output adds actual quantities once and consumes registered inputs once. `prep.like {planId,prepId,liked}`.
- `change.undo {auditId}` reverses a supported recent change only if dependent state has not changed; preserve unrelated likes. Do not restore an entire stale workspace snapshot.

Supply allocations derive from pending meals and planned prep. Confirmation does not change physical stock. Completion consumes selected on-hand inventory, using older matching batches first when applicable. No negative stock or double debit. Skip releases projected allocation without debit. Completing with insufficient actual stock is rejected with affected component details. Undo consumption restores its exact deltas; undo output already consumed is rejected. Partial prep produces explicit shortages; future meals remain visible and adjustable. Cards show on-hand/planned/shortage separately.

## AI application services

`POST /api/v1/kitchen/generate {weekStart,prompt,expectedRevision,operationId}` reads workspace + enabled guidance + last week's completed meals + stock + recipes. Generates a validated seven-day draft with full recipes/prep, no title-only invented meals. Use configured LiteLLM provider; fail clearly if unavailable; do not silently replace live AI with fake output. Deterministic validators enforce dates, IDs, dietary constraints present in data, quantities, time, and resource scheduling. Explain incomplete or infeasible inputs rather than claiming feasibility. The UI preserves the user's last state on failure.

`POST /api/v1/kitchen/chat {planId,message,mealIds,componentId?,expectedRevision}` returns `{reply,scope,meals,needsClarification}`. Scope is resolved before proposing edits; selected meal IDs are boundaries unless user explicitly requests wider scope. Locked/completed meals preserved. Multiple changes are previewed; user applies through ordinary validated commands. Record conversation in appropriate plan, use only the household data, no model hidden reasoning in UI.

`POST /api/v1/kitchen/extract {text?,imageData?}` accepts bounded text or a supported image data URL, calls configured model with image content (not its storage key), returns editable complete recipe candidates. Image count/size/MIME validated. Extraction result is a preview, not an implicit save. Preserve original source on save. No live-key required for deterministic tests; test provider requests and failures with typed fakes.

## Time planning and schedule

Keep active, unattended waiting and elapsed separate. The resource scheduler treats one cook as exclusive during active segments; handles equipment and task dependencies; serial manual work cannot overlap. Elapsed is the latest scheduled finish; baking/fermentation unattended tails may be shown separately, while active work and shared-device interference count. Every meal and day uses recomputed values; failures appear as actionable conflicts. Unknown legacy time is incomplete, not zero-cost feasible.

Application worker checks household timezone on/after Friday 17:00 and before the target next Monday. Week-keyed durable request prevents duplicates; an existing user draft/confirmed plan is retained. Catch-up after outage, bounded retry with saved failure, no auto-confirmation. Run through the app's worker, not a Codex automation.

## MCP

Authenticated JSON-RPC endpoint `/api/v1/kitchen/mcp` implements initialize, notifications/initialized, tools/list, tools/call for workspace read/query, validated commands, generation, chat, and extraction as appropriate. Advertise all core business CRUD through commands. Reuse authorization, revisions, operation IDs and engine; no arbitrary SQL bypass of invariants. External clients may use an explicitly generated revocable scoped token or the existing authenticated session; never repurpose an operational secret as a household identity. Invalid arguments and cross-household access fail closed. Document how to connect and which transport/auth is supported.

## UI routes and controls

`/calendar` default; `/plan`, `/prep`, `/fridge`, `/recipes`, `/guidance` (`/settings/guidance` redirects) share the workspace shell and selected week. Meal detail links preserve week/plan/meal. Existing `/chat`, `/settings`, `/todo`, `/imports`, `/shares` and public shares stay accessible as secondary legacy features. Recipe links retain return context.

Plan contains prompt, generate, draft/confirmed selection, full calendar, prep/time/guidance summaries and bottom chat composer with removable references. Draft preview never exposes executable prep completion. Friday-ready banner links directly to the correct draft. Fridge editor needs only name/portions/type. Recipe editor includes text/image import preview, ingredients, steps, tags and time. Guidance controls support CRUD, enable/disable and settings. Visible main controls work; no decorative dead buttons.

## Verification

Meaningful tests: transaction/idempotency/revision conflict; 2/6/4 stock -> confirm unchanged -> prep +3 yields 5/6/4 -> meal consumes3 each yields2/3/1 -> like unchanged -> undo restores5/6/4; skip, repeat, insufficiency, partial prep; draft versus confirmed/base conflict; scoped AI edits; image payload; scheduler timezone/idempotency; MCP authorization/errors. Frontend tests verify drawer dirty-close, Escape/focus, save/undo, page state, referenced chat and seven days. Typecheck, lint, Python tests and browser checks cover edited areas. Compare supplied screenshot with rendered calendar+drawer at matching viewport, then mobile, document differences and screenshots in design QA. Never claim live services verified from mocks.

## Implemented boundaries

- MCP uses the existing authenticated session cookie. OAuth, bearer tokens and separate MCP tokens are not implemented. See `docs/runbooks/kitchen-workspace.md`.
- Already confirmed weeks are adjusted through meal editing or chat; generation retains confirmed history and asks the user to use those paths. Chat proposals applied to a confirmed plan become a separate draft with its base version.
- Fresh recipe components do not debit portion inventory. Only explicit inventory/prep references allocate and consume fridge stock.
- The scheduler uses conservative active-then-wait task segments, one cook and exclusive named equipment. It does not infer unrecorded multitasking. Likes and repetition are transparent preference heuristics; dietary/time validation takes priority.
- Existing recipes with unknown servings/timing are imported as incomplete. Existing legacy plans remain accessible in their original domain, without invented stock conversion.
- The UI is English; user-authored Unicode names/content are preserved. `/demo` uses explicitly simulated AI and isolated localStorage. Authenticated routes use the real persistent command API.

## Live completion addendum — 2026-09-17

- Persist pre-generation weekly prompts separately from plans. The dispatcher reads
  the latest saved prompt; generation jobs expose status/error/attempts and retry.
- Support atomic bulk tag apply/remove and tag merging; manual meal/prep add/edit/
  delete; completed-meal leftovers with separate stock ledger and safe undo.
- Manual meal edits and AI proposals reconcile affected pending prep. Running or
  completed history is retained. Explicit selected-card/text scope conflicts ask
  for clarification without a provider edit or unintended wider mutation.
- Retain enabled guidance title/content/version snapshots on generated plans.
  Generate unique plan-specific prep output batch IDs across weeks.
- Reject supply-overallocated AI drafts before persistence. AI context includes
  projected available stock, preference weights, executed history and an explicitly
  labeled previous confirmed-plan fallback when no executions were recorded.
- Schedule the earliest feasible ready task when equipment is busy, so other
  independent active tasks fill waiting periods while preserving single-cook limits.
- Production services read root `.env`; frontend sees only the public API URL.
  Docker preserves data volumes and uses locked dependencies. The real route is
  `/calendar`; `/demo` remains an explicitly labeled simulation.
- Browser acceptance runs desktop and mobile against actual authentication, API,
  migrations and PostgreSQL. Provider contracts use fakes in deterministic tests;
  the opt-in live smoke is separate and must not be claimed passed without a key.
