# Live Kitchen Completion Implementation Plan

> Execute within the current authorized task; no additional design approval is required.

**Goal:** Make the approved kitchen workflow usable through the real persistent service, provide editable environment configuration, and verify the complete application.

**Architecture:** Preserve the existing Next.js / FastAPI / PostgreSQL command model. Keep `/demo` explicitly isolated. Use actual authenticated HTTP for integration tests and deterministic provider contracts for AI until the user supplies a key.

**Spec:** `docs/superpowers/specs/2026-09-17-kitchen-workspace.md` and `docs/product-redesign-proposal-2026-09-17.md`.

## Execution

- [x] Complete missing command and scheduler behavior in `src/recipe_agent/domain/kitchen/`, kitchen API and jobs: persist weekly prompts, expose generation status/retry, atomic bulk tags, and validate malformed MCP input. Add regression cases for each behavior.
- [x] Complete live frontend affordances in `web/src/features/kitchen/`: prompt persistence, job status/retry, tag merge/bulk application, stock/prep source selection, prep schedule and leftovers. Verify with Vitest and TypeScript.
- [x] Create `.env` without overwriting existing values, update `.env.example`, connect Compose configuration to API and both workers, and make browser API URL part of the Next.js build. Preserve existing database volumes.
- [x] Repair the independently demonstrated invalid Lark known-answer fixture; run all Python suites using an isolated PostgreSQL test database.
- [x] Replace obsolete browser assertions with authenticated real-API kitchen stories: login, Chinese recipe/stock persistence, draft and confirmation, drawer actions, prep/meal inventory effects, likes/undo, MCP isolation, and mobile layout.
- [x] Run unit/integration suites, lint/typecheck, optimized build and live browser tests. Record exact passes/skips; never treat a fake provider as live AI verification.
- [x] Start the complete application services and open the real Calendar. Document the single user-supplied AI key and restart command.

## Acceptance evidence

`docker compose --env-file .env -f infra/compose.yaml ps` must report actual running API, Web, worker and dispatcher. `/health/ready` must succeed. A newly authenticated workspace must persist Unicode records over reload, have no implicit demo seed, and expose missing AI configuration honestly. All PostgreSQL tests use a dedicated disposable test database, never the user's `recipe` database.
