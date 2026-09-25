# Plan, shop, prep

The approved screenshots and seven requested changes define this iteration.

## Journey

Plan is the first navigation item, followed by Calendar. The four visible steps are
Meals & preferences, Adjust plan, Confirm, and Shopping & prep. Saving an edited
plan or confirming a new one advances to Shopping & prep. Review plan returns to
the confirmed calendar; Edit plan retains the existing versioned draft behavior.
A View calendar button is available in the Plan header.

The household's current step, associated plan, and expanded shopping/prep panel
are stored with the weekly preferences in PostgreSQL. Confirmation advances the
step atomically. Explicit deep links win over the saved step; invalid steps are
clamped to the actual draft/confirmed status. Weeks remain independent. Failed
saves keep the current step and show an error.

## Shopping & prep

The same page contains two panels. Shopping starts expanded; Prep is a compact
categorized dish list. Activating Prep expands the existing dish-list/details
template and reduces Shopping to a compact checklist. Panel headings are real
buttons with expanded state; narrow screens stack the panels. The detail includes
recipe ingredients scaled to the batch yield, followed by preparation steps.

Shopping is derived from the selected plan and current fridge: count outstanding
prep batches once, then outstanding included meals not covered by those batches
or their explicitly linked stored food. Scale recipe ingredients by servings,
aggregate matching names/units, and deduct raw stock with known compatible units.
Convert kg/g, l/ml and count aliases; never convert an unknown portion to grams.
Expired stock is excluded. Unknown recipes, unknown quantities and unit ambiguity
are shown as review items rather than claiming the list is complete.

Purchases are a persistent checklist, scoped to the plan and required quantity.
Checking an item does not imply a stock quantity: the page includes Update fridge
to record the actual purchase using the existing inventory editor. Prep and meal
execution continue to update inventory through existing audited commands.
Changes to recipes, included meals, tasks or stock recalculate the list; a changed
purchase quantity has a new check key. No silent purchase or stock mutation.

## Shared presentation

Calendar uses the same day and meal styles as Plan, while retaining its execution
buttons and drawer interactions. Version selection uses the cream/brown/olive
theme, a status indicator, revision label and accessible native select control.

## Acceptance

Verify confirmation and edited-plan save advance; refresh and navigation recover
steps/panel/checklist; draft links cannot reach shopping; week/version switching
does not bleed state. Verify batch deduplication, partial stock, unit conversion,
skipped/excluded/completed meals, missing recipes and insufficient prep output.
Run backend persistence tests, frontend tests/typecheck/lint, and authenticated
desktop/mobile end-to-end tests using an isolated database. Inspect the running UI.
