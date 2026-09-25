# Confirmation, recurring meals and recipe access

Approved user refinements. Implement inline using the existing service and household data.

- Confirm / Save changes is a distinctive transition action in step 3; Edit plan replaces it in the same place after confirmation.
- Confirm starts a durable AI task with recipes, portions and inventory. Animate while working; confirm and save validated shopping/prep together. Recover tasks after refresh; failures keep the draft and allow retry. Demo remains explicitly local.
- Shopping & prep removes the requested explanatory sentence. Planning cards/drawers hide execution/like/undo actions. Drawer Edit is prominent; From your fridge remains visible.
- Lock means a household weekly weekday + meal-slot rule. Show a small unlockable lock on all matching calendar cards. Preserve the dish and portions on generation, rebind prep to the new week, never reuse consumed stock. Unlock any occurrence removes the rule. Existing executed meals remain unchanged.
- View full recipe opens a real kitchen recipe detail page in a new tab. Unsaved dishes show Save to recipe, allow reviewing ingredients/steps and save atomically; success animates into View full recipe.

Implementation / verification ledger:
1. Add contracts, persistence and recurring-rule enforcement; test cross-week generation/unlock.
2. Implement durable AI confirmation with validated output, stale-input rejection and failure recovery; test provider boundary and PostgreSQL round-trip.
3. Update transition controls, drawer and recipe route; test controls and browser interaction.
4. Run suites/static checks, review whole change, deploy local services and verify.

Ruling: this checkout has no Git repository. Modify the authorized workspace directly; no commits/worktree required.

Status: all implementation steps complete. See `2026-09-24-confirmation-and-recurring-meals-verification.md` for results, provider-test boundary and review fixes.
