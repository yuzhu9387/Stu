# Stu Figma implementation — 18 September 2026

Source: https://www.figma.com/design/exTOMpQuvjEJ4Y4VirSHoL/Untitled?node-id=7-498

The authenticated browser can read and export this file. The Figma connector continued returning its edit-access error, so the implementation uses the original `.fig` archive and the six exported PDF frames rather than an inferred screenshot design. `source.fig`, `reference.pdf`, and `reference-1.png` through `reference-6.png` record the source. `assets.json` records embedded recipe-image hashes.

## Visual specification

- Shared 84 px white horizontal navigation, 4 px brown divider, exact exported baby logo at 44 px, Nunito bold/black English typography and Noto Sans SC Chinese typography. Fonts and illustrations are served locally.
- Cream #FFF8EF, brown #35251F, amber #F4AF14, brick #C74732, olive #64734B, blue #7DCCED. Use 2–4 px outlines, 12–32 px corners and hard vertical shadows.
- Calendar (7:6): 40 px desktop inset, large title/date controls and Prep Day action, seven 509 px day panels, 126 px meal cards, explicit completion/skip/like controls, ingredient source and hands-on minutes, daily active totals. Current-day highlight is computed in the household timezone. Clicking a meal opens its functional drawer.
- Plan (7:475, target inner frame 7:498): title/status/actions, editable goal bubble, compact three-meal day columns, four computed summary tiles, assistant chat and referenced meal chips. Guidance snapshots and timing details remain available in an expandable section. Confirmation/proposal safeguards remain unchanged.
- Prep (7:800): active/elapsed/remaining summary, food-group filters, active task and selectable queue, linked meals, actual output input, completion/skip/like, and progress. Timing and stock projections remain available in expandable details. The displayed order uses the existing dependency/equipment scheduler.
- Fridge (7:651): Fridge and Freezer compartments with shelves, editable stock cards, extra compartments for custom locations, add/edit/remove forms and expandable projected supply table.
- Recipes (7:949): image cards, search across names/ingredients/tags, meal/tag filters, liking and selection. Exact original illustrations are matched to corresponding recipe names; other recipes have an explicit food illustration fallback. Recipe details/actions open a drawer. Import, editing, bulk tags, merge and delete remain operational.
- Settings (7:1135): settings navigation, enabled guidance rows, family and planning summaries, working weekly-new-recipe stepper, full household/schedule editor. Nutrition Knowledge remains accessible through settings and the profile menu.
- Narrow layouts retain the horizontal navigation, locally scroll the seven-day calendar, stack prep/fridge/settings panels, use two recipe columns, and present full-screen drawers.

## Data and behavior

This is the live application's presentation layer, not a separate static demo. No production data is seeded or overwritten. Demo remains explicitly labeled. Reference quantities and dates are not hard-coded: recipe, meal, inventory, prep, chat and settings values come from the existing store/API. The point badge is transparently derived as ten points per recorded completed meal/prep task; it does not imply a new stored reward balance. No fabricated nutrition rating is shown; the balance tile reports food-group coverage.

A compact Plan column retains all three meals instead of the single sample dish in the artwork so every planned meal remains reviewable. Additional existing operational details are expandable rather than removed. The original design has no separate Knowledge screen or meal drawer, so those use the same visual tokens while preserving their existing behavior.

## Validation

Frontend component tests, TypeScript, ESLint, production build, and isolated PostgreSQL browser stories cover the implementation. Browser stories run desktop and iPhone layouts and preserve real authenticated state/command behavior. Final command results are recorded in the completion report.
