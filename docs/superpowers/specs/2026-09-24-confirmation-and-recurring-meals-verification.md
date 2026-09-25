# Confirmation and recurring meals — verification

Implemented and deployed locally on September 24, 2026.

- Confirm / Save changes is a distinct state-transition control. Edit plan replaces it in place.
- A durable fulfillment task calls the configured AI using recipes, servings and stock. The UI animates until validated shopping/prep output and confirmation are saved atomically. Failure leaves the draft and can be retried; refresh recovers the task.
- Input validation rejects materially changed menus/stock. Fingerprints normalize relational record ordering and storage-location display labels. Linked prep recipes and executed records are protected. Missing known ingredients require correction or an explicit review warning.
- Material menu/recipe edits invalidate shopping snapshots. Stock movements invalidate snapshots across weeks; the existing live calculation then reflects current inventory.
- Weekly weekday/meal-slot locks persist in household settings, show on cards and can be unlocked from any occurrence. Generation preserves locked dishes. Future weeks get independent prep IDs; displaced batches are reconciled and recurring batch portions are scaled. Same-week plan versions preserve compatible prep references.
- Plan hides execution/like controls. Drawer retains From your fridge and has a prominent Edit meal action.
- Recipe links open an authenticated kitchen detail route in a new tab. Unsaved dishes can be reviewed and saved; the button animates into View full recipe.

## Checks

- Backend unit suite: **234 passed**.
- PostgreSQL kitchen integration suite: **53 passed**, isolated schemas.
- Frontend suite: **159 passed**, **1 pre-existing skipped**.
- Playwright: **18 passed** across desktop and mobile, including confirmation, failure recovery, shopping/prep persistence, recurring unlock, real recipe-tab navigation and no planning execution actions.
- TypeScript, ESLint, Ruff and mypy passed.
- Production Docker builds passed. Additive migration `0028_confirmation_recurring` applied. Existing volumes retained.
- Browser inspection verified the deployed recipe detail page and final logo/layout. Existing user tab was refreshed; the household login session had expired and was left at sign-in.

## AI verification boundary

One small synthetic menu was sent through the existing real configured AI provider. It returned a shopping requirement (1 cup Rice), a prep task, and an empty-inventory warning; the normal domain command successfully confirmed the result. This test did not access or mutate household data.

Browser stories use the real API, authentication, task persistence, command validation and PostgreSQL; only the paid fulfillment model response is replaced by the explicit fixture in `tests/e2e_app.py`. Other AI browser tests retain the unconfigured-provider error path. Unit tests cover stale inputs, provider failure/retry and invalid output.

## Review fixes

The final independent review identified source-draft/base lock consistency, stale shopping snapshots, unused/disproportionate prep batches and false empty-shopping output. Regression tests cover all four. Follow-up regressions also cover shared-stock invalidation and linked recipe/prep fingerprints after actual repository writes.
