# AI, knowledge library and calendar follow-up

Authorized by the user's follow-up and selected calendar screenshot. This extends
the existing live kitchen workspace; it does not replace it with a demo.

## Accepted behavior

- Real provider calls must succeed using the existing root `.env` key. Never log
  credentials or ship them to the browser. Test content and databases are isolated
  from the user's household.
- An empty recipe library is a supported first-run state. Generate complete recipes
  (ingredients, quantities, steps, servings, active and elapsed time), save them
  atomically with the 21-meal draft, and preserve the normal confirmation step.
  Bootstrap may exceed the usual weekly new-recipe preference when necessary.
  Its AI response uses complete recipes, reusable meal templates and seven daily
  assignments. The server derives calendar IDs and batch demand, preserves recipe
  quantities and cooking times, and runs the same full-plan validation before
  saving. Compiled prep instructions must explain batches and ingredient amounts.
- The same dish may not appear on adjacent calendar dates. The user explicitly
  confirmed **Monday → Wednesday is allowed**. Check the previous week's boundary,
  generated drafts, replacements and confirmed changes. Likes never override it.
- Nutrition Knowledge is a persistent, editable document list: title, category,
  content, optional source URL, enabled state and version. Support Chinese text and
  text/Markdown file import with preview. Only enabled documents enter AI planning
  and chat; save versions used by a draft for traceability. Existing household
  guidance stays available. Document content is reference data, not permission to
  bypass application constraints or execute external instructions.
- Calendar follows the supplied seven-column screenshot: three cards per day,
  breakfast/lunch/dinner color families, category icons and labels inside cards,
  dish composition, elapsed time and truthful inventory-source labels. Preserve
  drawer editing, replacement, chat reference, status and baby-like actions.
- English application controls; Unicode recipe and document contents. Mobile must
  keep controls reachable and allow the week grid to scroll within its container.

## Verification

1. Provider smoke: real model response and Chinese recipe extraction.
2. Live generation: empty library → complete persisted week, valid repeat interval,
   timing and knowledge snapshot; scoped chat and idempotent retry.
3. Backend unit/integration regression with an isolated PostgreSQL database.
4. Frontend behavior, type checking, lint and production build.
5. Real-service browser stories on desktop and mobile, including knowledge CRUD.
6. Visual comparison with the selected screenshot, including drawer state and
   responsive layout; report evidence in `design-qa.md`.

Deployment updates the existing local Docker services and preserves their volumes.

## Additional user-approved color system

The later palette attachment supersedes the earlier screenshot's exact colors.
Apply globally to kitchen, login and retained legacy pages, with shared CSS tokens:
background `#FFF8EF`, primary buttons/selection `#C74732`, secondary/status accent
`#64734B`, body text `#35251F`. Preserve white surfaces, existing interaction/layout,
English controls and Chinese content support. Derive subtle cream/olive/brick meal
tints from these tokens rather than retaining the former sage primary buttons.
