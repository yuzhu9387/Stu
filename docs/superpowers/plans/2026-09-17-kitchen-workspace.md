# Kitchen Workspace Implementation Plan

Goal: Implement the confirmed kitchen workflow with the supplied editing drawer.
Spec: ../specs/2026-09-17-kitchen-workspace.md
Architecture: A validated household aggregate in PostgreSQL, transactional command service, AI proposal services and authenticated MCP; a shared frontend workspace with screenshot-aligned UI. Existing records and routes retained. Explicit local demo uses the same command semantics where possible.
Global constraints: English UI / Unicode content; 7 days × 3 meals; 240-minute ordinary prep; 30-minute daily active; no production seed or silent fake AI; scope/revision/idempotency enforcement.

## Task 1 — State, persistence, API and stock accounting

- Files: domain/kitchen/{contracts,engine,repository,models}.py; api/v1/kitchen.py; migration 0013; tests/unit/kitchen and tests/integration/kitchen.
- Implement the transport contract and commands in the spec. Tests first: real stock transitions, rejected negatives, retry deduplication, stale revision, household isolation, dirty version changes, safe undo.
- Expose `KitchenRepository(session_factory)`, async `get(scope) -> dict`, async `command(scope, command: dict) -> dict`, and pure `initial_state()`, `apply_command(state, command, actor_id) -> dict` returning `{state,message}`. ExpectedRevision checking and operation receipts live in repository/engine.
- Register router and model/migration, provide simple dependency from request.app.state.session_factory. Add safe legacy projection without mutating originals.
- Run focused Python tests then lint. Review command/data invariants before integration.

## Task 2 — AI, scheduling and MCP

- Files: domain/kitchen/{ai,scheduling}.py; api/v1/kitchen_ai.py; api/v1/kitchen_mcp.py; infrastructure/jobs/kitchen.py; worker integration; focused tests.
- Consume Task 1's repository and JSON contract. Add validated generation/scoped chat/extraction; real image message payload; no silent fallback. Test typed provider fakes, scope, constraint checking, image rejection.
- Add pure resource scheduler and timezone Friday eligibility, then durable job claims/catch-up, and wire worker.
- MCP uses authenticated session initially plus documented compatibility; if scoped tokens are added, hash/revoke them, never hardcode tenant. Test initialize/tools/call protocol and command reuse.

## Task 3 — Shared web data, shell, calendar, Plan and drawer

- Files: web/src/features/kitchen/{types,data,store,workspace,calendar,meal-drawer,plan}.tsx/ts; kitchen.css; new routes; shell interception; tests.
- Data contract follows spec exactly. Production GET/commands via existing API helper. Explicit `/demo` isolated seed/reset. Browser state persists selected page/week/meal; live state refreshes on focus and mutations.
- Match supplied visual hierarchy, create accessible reusable drawer with detail/edit/replace; dirty close and save; calendar shows seven days. Complete/skip/like/undo and chat references work with consistent data.
- Meaningful UI tests for drawer and shared flow; typecheck and browser interaction verification.

## Task 4 — Fridge, Prep, Recipes and guidance

- Files: web/src/features/kitchen/{prep,fridge,recipes,guidance}.tsx. Consume shared props `{state, plan, send, notify, navigate}` and types. No route/shell changes by this task.
- Implement grouped prep, actual portions, skip/like, schedule view; inventory edit/shortages; recipe forms/tags/extraction; guidance and schedule settings. Keep component CSS within kitchen stylesheet classes owned by root.
- Validate forms, failures and Unicode; core controls not placeholders. Run typecheck and review with root integration.

## Task 5 — Integration and review

- Run backend tests and web typecheck/lint/tests, fix introduced failures. Start local backend/web with available infrastructure; use explicit demo when auth infrastructure unavailable while labeling it accurately.
- Browser compare screenshot and actual drawer, test edit/save, dirty-close, scoped reference, prep/stock/complete/undo and mobile.
- Add runbook and final QA evidence; document exact live-service verification limits. No deployment or commit needed (current root is not a Git repository).

## Execution ledger

- 2026-09-17: Spec and plan written. User explicitly authorized spec then execution; no additional approval gate.
- Ruling: work in current workspace; no Git metadata at root, so no worktree/commit operations. Existing nested worktree dependencies are reused read-only; source changes remain at root.
- Ownership: core backend and AI endpoints are separate modules; root owns app router registration and frontend shell; supporting UI touches only assigned files. Shared contracts prevent parallel edits to the same files.

- Tasks 1–4 implemented: persistent commands and ledger, AI services/scheduling/MCP, shared workspace and drawer, supporting pages.
- Task 5: 39 frontend tests pass; TypeScript and changed-file ESLint pass; optimized Next.js production build passes. Kitchen backend unit/integration suite: 44 tests pass. Earlier full backend suite: 280 pass, 25 skip, one pre-existing Lark AES fixture failure; later preference/source tests pass in the kitchen suite.
- Actual HTTP smoke: authentication, empty household, persisted inventory, idempotent retries, stale conflict, invalid quantities, new session, household isolation (11 checks).
- Browser: desktop and mobile drawer, dirty discard, prep 2/6/4→5/6/4, dinner→2/3/1, like unaffected, undo→5/6/4, scoped chat draft, Unicode live save and refresh. QA evidence in `docs/design-assets/qa/` and root `design-qa.md`.
- Local preview uses an isolated SQLite API on port 8001; existing services on port 8000 were not overwritten. No provider key is configured; real AI invocation and deployed Friday execution remain unverified. See runbook for enabling them.

PostgreSQL verification subsequently passed in a unique temporary database: full migration to0014, table creation, concurrent first-insert retry, row-lock retry, same-revision conflict and household isolation. Only the temporary database was dropped afterward. Evidence: `docs/reports/kitchen-postgres-verification-2026-09-17.json`.
