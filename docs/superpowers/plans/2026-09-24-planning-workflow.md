# Planning workflow implementation

Spec: `../specs/2026-09-24-planning-workflow.md`.

1. Add regression tests for shopping derivation and persisted workflow commands.
2. Add typed weekly workflow and plan shopping checks to contracts, normalized DB
   projection/read path and migration 0027. Preserve preferences on workflow saves;
   confirmation stores Shopping & prep in the same command transaction.
3. Implement deterministic shopping derivation and two-panel shopping/prep UI;
   reuse PrepPage, adding scaled ingredients and compact list mode.
4. Integrate the four steps, restore saved progress, keep explicit deep links,
   add View calendar, swap navigation order, and share Calendar styling.
5. Run focused tests, full unit suites/static checks, relational and browser tests;
   inspect responsive UI, then rebuild the local services without resetting data.

## Execution ledger

- Initial inspection: current confirmation stays on the calendar preview and
  progress exists only in the URL. Inventory stores portions with optional grams
  per portion, so unknown unit conversions must remain review items.
- Ruling: purchase checks record shopping progress; actual purchased quantities
  use the existing Fridge editor. The request does not specify a checkout quantity
  editor, and automatically equating a checked ingredient to a fridge portion
  would corrupt inventory.
- Ruling: implement directly in the shared workspace (not a Git repository).
- Completed: migration 0027, workflow and shopping commands (also available via
  MCP), relational read/write persistence, shared Calendar cards/version control,
  four-step navigation, and responsive Shopping/Prep panels.
- Fresh-context review identified expiry checks, embedded Prep feedback, and
  recovering the selected draft. All three were corrected with regression tests.
- Browser verification caught an asynchronous checkbox reverting visually before
  its save completed; optimistic display now rolls back on save failure.
- Fixed an existing leftovers test race by waiting for its Undo button to become
  enabled after the async save, rather than clicking a disabled button.
- Final validation: frontend 156 tests; backend unit 220 tests; PostgreSQL
  integration 50 tests; desktop/mobile authenticated browser stories 14 tests.
  TypeScript, ESLint, Ruff and kitchen mypy checks pass; production images build.
- Migration applied to the local service without resetting volumes. Desktop and
  mobile Shopping/Prep screenshots inspected; running Calendar verified with no
  browser console errors. Temporary browser preview closed.
