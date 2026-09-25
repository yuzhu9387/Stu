# Stu · Family Table

A household meal-planning app with Calendar, Plan, weekend Prep, Fridge, Recipes,
planning guidance, a Nutrition Knowledge library and an authenticated MCP API. The real workspace uses FastAPI,
PostgreSQL, Next.js and a persistent Friday dispatcher. English controls support
Chinese recipe names and content throughout.

## Run the real app

1. Open `.env` and fill `OPENAI_API_KEY`. The prepared local file has application
   secrets already generated. `.env.example` documents every setting. If setting
   up a new checkout, copy the example and generate three distinct random secrets.
2. Start Docker Desktop, then run:

   ```sh
   docker compose --env-file .env -f infra/compose.yaml up -d --build
   ```

3. Open **http://localhost:13107/calendar** and sign in with your email. Local
   development signs in directly; it does not send an email. A new household starts
   empty. Add food and household guidance, optionally import nutrition references
   in Knowledge, then generate a plan. An empty recipe library is supported: AI
   creates complete recipes together with the draft.

After editing the API key or model in `.env`, reload the API and both workers:

```sh
docker compose --env-file .env -f infra/compose.yaml up -d --force-recreate api worker dispatcher
```

Use the same hostname (`localhost`) for the Web app and API so session cookies work.
`/demo` is deliberately a separate local simulation; it is not the real workspace.
Without an AI key, manual planning, recipe editing, stock and execution remain usable;
AI generation, chat and extraction report the missing configuration instead of faking output.

## Develop and test

```sh
uv sync --all-groups --frozen
pnpm install --frozen-lockfile
uv run pytest
uv run ruff check src tests migrations scripts
uv run mypy src
pnpm --dir web test
pnpm --dir web typecheck
pnpm --dir web lint
pnpm --dir web build
uv run python scripts/run-kitchen-e2e.py
```

The browser suite creates its own temporary PostgreSQL database on the local Docker
PostgreSQL service, applies every migration, runs a real API, and tests desktop and
mobile browser flows. It deletes only that generated test database. It never uses
demo state or mocks HTTP responses. `RECIPE_AGENT_E2E_DATABASE_ADMIN_URL` can override
the local test database host. API tests that require PostgreSQL use an explicit
`RECIPE_AGENT_TEST_DATABASE_URL` pointing to a separate empty test database; never
point test suites at the application database.

`RUN_LIVE_AI_TESTS=1 uv run pytest tests/live` opts into billable provider verification
after the key is filled. Ordinary automated tests exercise deterministic provider
contracts and clearly report the external-provider smoke test as skipped.
Live tests cover the agent, Chinese extraction, empty-library weekly generation,
knowledge context/snapshots, persistence, repeat rules and selected-meal chat.
Full-week calls use `RECIPE_AGENT_KITCHEN_GENERATION_TIMEOUT_SECONDS` (240 seconds
per proposal); invalid proposals can be repaired twice before any data is saved.
Bootstrap generation returns recipes and reusable meal templates; the server
expands the calendar and computes batch quantities before validating the draft.
`RECIPE_AGENT_KITCHEN_GENERATION_REASONING_EFFORT` defaults to `medium`.

For host development, `.env` configures the API and `web/.env.local` sets the browser
API address. Run `uv run uvicorn recipe_agent.app:app --reload --port 8000`,
`uv run python -m recipe_agent.worker`, and `pnpm --dir web dev` with the corresponding
Docker API/worker services stopped first to avoid port and scheduler conflicts.

## Documentation

- [Product design](docs/product-redesign-proposal-2026-09-17.md)
- [Implementation specification](docs/superpowers/specs/2026-09-17-kitchen-workspace.md)
- [Setup, Friday worker, provider and MCP](docs/runbooks/kitchen-workspace.md)
- [Acceptance results](docs/reports/kitchen-ai-knowledge-calendar-2026-09-17.md)

Existing legacy recipes, account/household features, sharing and Lark routes remain.
The optional Lark keys in `.env` are unnecessary for the kitchen Web workflow.
