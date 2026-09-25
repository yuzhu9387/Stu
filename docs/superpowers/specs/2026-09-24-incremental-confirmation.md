# Incremental confirmation and planning navigation

## Product behavior

- Plan keeps its four-step journey. Navigation steps are separate rounded rectangles. Confirm / Save changes / Edit plan occupies the same position and uses an olive circular control, with a visible label. Red remains reserved for errors and destructive meaning.
- View calendar is a quiet text link on the journey row. Mobile uses abbreviated step labels so all steps remain reachable without hiding the action.
- Shopping and Prep keep the two-panel layout. Selecting a panel expands it with an animated grid transition; the other panel keeps its compact list. Desktop panels stretch to the same height. Focus switches immediately, persists, and rolls back if saving fails. Reduced-motion preferences disable the animation.
- Update fridge and Ready for prep sit together. Remove redundant overview/instruction copy; preserve actionable warnings and actual quantities.

## Confirmation contract

The model no longer owns shopping arithmetic. Missing model `shopping.required` fields cannot break confirmation because shopping quantities are calculated from recipes, servings, planned portions, usable stock and prep capacity in the service.

A compact `FulfillmentAdvice` response must decide explicitly for every requested recipe whether to cook it ahead or keep it fresh. Cook-ahead decisions require full cooking steps, not just chopping instructions. Empty or partial responses fail validation and get one correction attempt. Existing tasks and approved meal contents remain intact. New batches link only to eligible unlocked, unexecuted components of the same recipe.

Fulfillment snapshots store recipe fingerprints and batch decisions. An edit draft copies this server-held metadata from its baseline. Material edits mark the shopping snapshot stale, while preserving decision metadata for reuse. UI derives a current shopping list while stale. Confirmation recalculates quantities locally:

- No menu change: reuse decisions, zero new model calls.
- Only portions, checklist or stock changed: recalculate locally, zero new model calls.
- A new or changed recipe: send only affected recipe/meal context to the model, retaining other tasks.
- Older snapshots without decision metadata are reviewed once by the new path.

New prep reserves only known raw-stock amounts with supported unit conversions; stock is consumed on completion, not confirmation. Completed tasks, recurring locks, optimistic revision checks and durable task recovery retain their existing behavior. Missing quantities and unknown stock conversions remain explicit warnings.

## Failure handling

No raw Pydantic dumps are shown to the user. Invalid model output produces a short retryable error; details stay in server logs. Previously stored validation-error dumps are sanitized when read. Provider failures keep the plan as a draft. Menu or inventory changes during generation still fail the stale-input check atomically.

## Verification

Regression coverage includes empty prep, no-change confirmation, portion-only changes, scoped new-recipe advice, deterministic shopping quantities, expired/unknown stock, raw-stock deduction on prep completion, panel persistence and rollback. PostgreSQL round trips include cache metadata. Browser stories cover desktop/mobile planning, shopping and prep. A real provider test uses exclusively synthetic data and verifies that a repeated unchanged confirmation makes no additional model call.

### Verified results

- Full Python suite: 418 passed, 74 skipped (opt-in provider and database suites without their environment variables).
- PostgreSQL kitchen suite, explicitly configured: 53 passed.
- Frontend unit/component suite: 160 passed, 1 existing skipped.
- Desktop/mobile Playwright: 18 passed against isolated PostgreSQL and the real API; only the paid advice response is mocked.
- Ruff, mypy (127 source files), ESLint and TypeScript passed. API/worker/dispatcher and Next production Docker builds passed.
- Real configured AI provider, synthetic rice/lentil menu: 9.8 seconds, 1 model call, 3 shopping rows, 2 prep batches. Unchanged second confirmation: 0 additional model calls.
- Automatic approval review declined external AI testing with actual household records. No household data was sent by that rejected test; the successful live verification used entirely synthetic data without database access.
- Rebuilt and restarted the local services on ports 13107/8000, with the existing data volumes preserved. API readiness returned ready. Visually inspected the delivered compiled UI and panel toggle.
