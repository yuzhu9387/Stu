# Live kitchen acceptance — 2026-09-17

> Historical checkpoint. For current test counts, Knowledge/calendar/palette
> acceptance and the passed full-week live AI generation test, see the
> [latest acceptance report](kitchen-ai-knowledge-calendar-2026-09-17.md).
> The key has since been configured and full-week/recipe/chat calls passed; the
> missing-key statements below describe the earlier checkpoint only.

The previous `http://localhost:3000/demo` page was an explicitly simulated local
workspace. The actual application is now built and running at
**http://localhost:13107/calendar** against PostgreSQL. It has real authentication,
command persistence, an execution worker and the Friday dispatcher. Empty households
are not seeded with demo records.

## Completed core scope

| Requirement | Implemented behavior | Evidence |
| --- | --- | --- |
| Calendar / Plan / drawer | Shared persistent plans, seven days, edit/replace/reference, dirty-edit guard | Frontend tests and real browser execution |
| Planning agent | Recipes, stock/projection, prompt, guidance snapshots, prior week and likes in validated provider input | Provider contracts; actual call awaits key |
| Time budgets | One cook, active/wait separation, equipment/dependencies, waiting-gap use, daily/ordinary prep limits | Scheduler regression tests |
| Friday generation | Persisted week preferences, timezone-aware durable job claims, failure status/retry, never auto-confirms | Job tests and live dispatcher |
| Planning chat | Resolve/clarify scope, protect locked/executed cards, preview and apply meal/prep changes | Provider scope and UI tests |
| Prep | Category groups, schedule order, manual task CRUD, actual yield, skip, inputs and outputs | Tests plus real browser prep completion |
| Meal status / likes | Complete, skip, independent boolean like, exact stock undo, leftover output/undo | PostgreSQL and desktop/mobile browser tests |
| Fridge | Chinese names, fractional portions, category, raw/prepared, batch/date/source, editable quantities | Real UI save and reload |
| Recipes / tags | Text/image extraction previews, source retention, editable recipes/times, tag CRUD/merge/bulk | Provider payload and UI tests |
| Guidance / language | Guidance/settings CRUD, version snapshots; English controls and Unicode data | Contract/UI tests, Chinese E2E |
| MCP | Authenticated read/commands/AI through same engine, revision/idempotency and household isolation | Real HTTP/browser MCP write and unauthorized rejection |

## Verification

- Full frontend suite: **52 passed**, 16 files.
- Full backend suite with real PostgreSQL: **339 passed, 1 skipped, 0 warnings**. The sole skip
  is the intentionally gated external-provider smoke test because no key is filled.
- Real-service Playwright: **8 passed**, desktop Chromium and mobile viewport,
  real authentication + PostgreSQL + migrations + HTTP, no mocked HTTP responses.
- TypeScript and frontend ESLint: passed.
- Ruff check and formatting: passed. Strict mypy: all **117 source files** passed.
- Next.js production Docker build: passed, 18 generated static pages plus retained
  dynamic legacy routes. Backend images use hash-locked dependencies from `uv.lock`.
- PostgreSQL revision **0014_kitchen_generation_jobs (head)** applied successfully.
- Deployed production Web page: login rendered, real API returned expected unauthenticated 401, no browser page errors. Screenshot: `live-service-login.png`.
- API `/health/ready`: ready. Web, API, worker, dispatcher, PostgreSQL, Redis and
  MinIO reported running and healthy. Existing storage volumes were preserved.
- SQLite migration compatibility check also passed from an empty temporary database.

Browser acceptance caught a real mobile interaction defect: completion feedback
covered the drawer footer. Feedback now occupies its own drawer layout row with
bounded height, and the complete → like → undo → skip mobile flow passes naturally.

The old malformed Lark AES fixture was replaced with a valid known-answer vector,
with malformed-envelope rejection tests retained. Production decryption was not
weakened. Legacy test clients now close their application lifespans, eliminating SQLite thread/resource leaks. The app lifespan also closes runtime resources when the context exits with an exception; a regression test verifies this. Resource, thread and unraisable warnings were promoted to errors in the final gate.

## Configuration and what still needs the user's key

Root `.env` now exists, mode 0600, with `OPENAI_API_KEY=` and a sample-format comment.
Application signing/metrics secrets are generated; optional Lark settings are disabled.
No secret is copied into the browser build or Docker build context.

After filling the key, run:

```sh
docker compose --env-file .env -f infra/compose.yaml up -d --force-recreate api worker dispatcher
RUN_LIVE_AI_TESTS=1 uv run pytest tests/live
```

The live smoke covers a real agent response and synthetic Chinese recipe extraction.
No real AI generation quality, external model credentials or actual future Friday
provider execution is claimed as verified in this report. Deterministic provider
contracts cover those code paths without disguising test responses as live output.

## Defined behavior

The approved spec uses one cook and active-then-wait segments, not a detailed
alternating-step cooking simulator. Portions share one household basis without
invented adult/child/gram conversions. Extra physical prep batches are separate
tasks or manual stock additions. Long-term preferences are edited in Guidance;
weekly chat does not silently rewrite them. MCP authenticates with the household
session and validates business commands; it does not expose unrestricted SQL or
independent OAuth tokens.
