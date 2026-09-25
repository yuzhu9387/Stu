# Kitchen workspace operations

The authenticated kitchen API uses the same opaque `recipe_session` cookie as the
existing app. Household and account IDs always come from that session. Production
workspaces begin empty and import accessible legacy records without modifying them.
`/demo` in the Web app is a separate local demonstration.

## Schema and startup

Apply migrations through the normal single release job before starting the new API
and worker: `uv run alembic upgrade head` (or the migrate Compose service described
in [deployment](deployment.md)). Revision `0013_kitchen_workspace` adds workspace
aggregates and operation receipts. `0014_kitchen_generation_jobs` adds durable
household/week generation claims. Both models are registered in Alembic metadata.
Existing legacy tables are retained.

Run the API with `uv run uvicorn recipe_agent.app:app --host 127.0.0.1 --port 8000`.
Run the dispatcher with `uv run python -m recipe_agent.worker`; existing Celery
execution workers remain necessary for existing agent/Lark/action work. The kitchen
scheduler runs as a separate asynchronous task in the dispatcher, independently of
outbox polling. Running only a Celery execution worker does not start this scheduler.

## AI provider

Set `OPENAI_API_KEY` (or `RECIPE_AGENT_OPENAI_API_KEY`) and configured LiteLLM model
names: `RECIPE_AGENT_LITELLM_CHAT_MODEL` and `RECIPE_AGENT_LITELLM_VISION_MODEL`.
The defaults are `openai/gpt-5.1` and `openai/gpt-5-mini`. Other LiteLLM providers
use their provider-specific credentials and model prefixes. Production configuration
currently also requires an OpenAI key. Set timeout/retries with
`RECIPE_AGENT_LITELLM_TIMEOUT_SECONDS` and `RECIPE_AGENT_LITELLM_MAX_RETRIES`.
Full-week JSON generation uses its own
`RECIPE_AGENT_KITCHEN_GENERATION_TIMEOUT_SECONDS` (default 240 seconds, maximum
600). It disables transport retries so an expensive timeout is not automatically
duplicated. GPT-5-family kitchen requests use low output verbosity. Weekly planning
uses `RECIPE_AGENT_KITCHEN_GENERATION_REASONING_EFFORT` (default `medium`)
independently of the general agent's reasoning setting. Deterministically
invalid proposals receive up to two correction attempts before the request fails.
Never use session-signing, action-signing or metrics secrets as provider credentials.

`POST /api/v1/kitchen/generate` reads household recipes, stock, enabled guidance,
enabled knowledge documents and
last week's completed meals. It saves a full validated draft, never confirms it.
`/chat` returns a selected-meal proposal and persists conversation history; refresh
workspace revision after receiving it, then apply changes through normal commands.
`/extract` returns editable text/image candidates without saving. PNG/JPEG/WebP
images use actual data URLs, limited to 1.3 MB decoded. Incomplete extracted recipes
must be completed before using them for feasible plans. Provider failures return
503; invalid proposals return 422. There is no mock fallback in production.

Empty-library bootstrap returns complete recipes, reusable meal templates and
seven day assignments. The server expands 21 meals, computes prep demand and batch
counts from exact decimal portions, adds per-batch and total ingredient
instructions, then applies all normal stock, timing, repetition and reference
checks. Optional `prepInputs` allocate known raw inventory to the generated prep.
New recipes start with `liked=false`; only user feedback should increase that
preference. Ingredient quantities and cooking times are never reduced to make a
proposal pass. Existing usable libraries retain the full-plan generation path.

## Friday scheduler

Every scan checks each household's IANA timezone and `generateTime`. The default
window starts Friday at 17:00 local time and ends when the next Monday begins.
A restart during that window catches up. A draft or confirmed plan already present
for next week is retained. The dispatcher waits 60 seconds between scans; a slow
provider may lengthen a scan but does not delay the outbox loop.

`kitchen_generation_jobs` uses `(household_id, week_start)` as its durable unique
key, atomic claims, a 20-minute crash-recovery lease and at most three attempts.
Failure retries wait 5 then 10 minutes. Final failures remain recorded in `error`
and `status`; expired third-attempt leases also become failed. An API save racing
automatic generation wins through revision validation. Completion never confirms a
plan. After fixing provider configuration, users can generate manually from Plan;
no destructive reset of existing weekly plans is necessary.

Timing is a conservative estimate: one cook handles active work sequentially;
exclusive equipment remains reserved through waiting; dependencies must finish
first. Multiple recipe batches are counted. Unknown/zero elapsed legacy timing is
incomplete, and infeasible proposals report the conflicting day or prep duration.
The ordinary-prep elapsed limit excludes passive Baking tails: ordinary tasks must
finish within the limit and total active work including baking must also fit. Shared
ovens and dependencies still delay ordinary readiness. Passive baking tails are
reported separately after ordinary tasks and all active work finish.

## MCP connection

Endpoint: `POST /api/v1/kitchen/mcp`. This implements stateless MCP Streamable HTTP
with JSON responses and protocol version `2025-03-26`. `GET` returns 405 because no
server-initiated SSE stream is offered. Supported methods are `initialize`,
`notifications/initialized`, `ping`, `tools/list`, and `tools/call`.

Authenticate using a valid `recipe_session` cookie acquired through the normal
magic-link/session flow. Non-browser clients must support cookie authentication.
There is no OAuth discovery, bearer-token authentication or separately issued MCP
token. Logging out revokes the ordinary session. Operational secrets never confer
household access.

For every POST send `Content-Type: application/json` and
`Accept: application/json, text/event-stream`. Browser clients use credentials and
an Origin matching `RECIPE_AGENT_WEB_ORIGIN`. Cross-origin requests are rejected;
non-JSON POST bodies return 415. The actual app uses HttpOnly, SameSite=Lax session
cookies (Secure outside development), JSON-only requests and Origin checks for MCP
browser CSRF defenses. It does **not** issue or require a CSRF-token header.

An authenticated request body to initialize:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"kitchen-client","version":"1.0"}}}
```

Then send `notifications/initialized` as a notification, followed by `tools/list`.
Tools are `kitchen_read`, `kitchen_command`, `kitchen_generate`, `kitchen_chat` and
`kitchen_extract`. The command tool advertises all core CRUD/execution commands,
requires the current `expectedRevision` and a stable retry `operationId`, and uses
the same repository as HTTP. Clients should preview user-facing edits before
calling it. Ownership parameters are not accepted. Stale revisions, invalid stock,
locked history and unsafe undo remain protected by the common command engine.

Protocol references: [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
and [tools](https://modelcontextprotocol.io/specification/2025-03-26/server/tools).

## Verification limits

Tests inject provider fakes to check complete proposals, image payloads, selected
scope, resource timing, durable claims, session authentication and protocol errors.
Passing those tests does not verify a live model, production database or deployed
worker. Run a real authenticated generation and inspect the resulting draft before
claiming live-provider verification.

## Recommendation preferences and active time

Generation sends explicit `planningPreferences`: recipe likes plus likes on meals
and prep increase preference; priority inventory is considered before ordinary
inventory, with older batches first within each group. Repeated draft/confirmed
versions count only once per week. Last week's completed meals are supplied in a
separate `previousWeek` context, with a repetition penalty to encourage variety.
Scores are bounded, transparent heuristics, not nutrition or medical assessments;
allergies, time limits, enabled guidance and explicit user requests take precedence.
The provider receives ranked candidates and these rules; a preference score is not
a guarantee that a particular recipe appears in a generated plan.

Daily `activeMinutes` includes preparation, hands-on cooking, serving and cleanup
across breakfast, lunch and dinner. Passive fermentation/baking waiting is not
active work, but its setup and cleanup are. Elapsed time retains unattended waits;
ordinary prep and baking-tail treatment follows the resource scheduler's limits.
An empty new household uses the same timezone-aware Friday eligibility. When there
are no complete, allergy-compatible saved recipes, bootstrap permits up to 21 new
recipes independently of the ordinary weekly new-recipe preference. At least one
new complete recipe must actually be used by the plan. Recipes and the validated
draft are saved atomically; no automatic demo inventory or completed meals appear.

## Nutrition Knowledge and dish rotation

`/knowledge` stores a household's reference documents in `knowledgeDocuments`:
title, category, plain Unicode content, optional HTTP(S) source URL, enabled state,
server-managed version and updated timestamp. Text/Markdown imports remain an
editable preview until saved. PDF import is not offered. No medical reference
content is silently seeded or fetched from source links.

Use `knowledge.save` with `{document: {...}}` and `knowledge.delete` with `{id}`
through HTTP commands or MCP. Revision and document-version checks prevent lost
edits. Enabled documents enter generation and scoped chat as untrusted reference
data. Generated plans store the document versions/content in `knowledgeSnapshot`;
historical snapshots survive edits/deletion but do not reintroduce disabled content
into future chat. Plan shows the versions used.

`recipeRepeatGapDays` counts full intervening days and defaults to **1**: Monday
and Wednesday are allowed; Monday and Tuesday are rejected. Validation covers
neighboring confirmed/executed weeks, meal edits, draft saves/confirmation and undo.
Skipped meals do not count. Recipe IDs and normalized names/bilingual aliases are
compared. Plain everyday rice, milk, water and plain bread can accompany different
dishes repeatedly; mixed dishes containing those staples still obey rotation.

## Live completion and environment (2026-09-17)

The prepared root `.env` is the actual configuration file. Fill `OPENAI_API_KEY`;
its comment contains an example format only. The three application secrets are
already generated locally. `.env.example` has no credentials and documents required
versus optional values. The Web app never receives the provider key.

`docker compose --env-file .env -f infra/compose.yaml up -d --build` starts the real
workspace at **http://localhost:13107/calendar**. Use `localhost` consistently for
cookie authentication. Docker passes `.env` to the API and both workers, overrides
database/Redis hostnames internally, and supplies the browser API URL at Web build
time. Editing the AI key/model requires recreating API, worker and dispatcher:

```sh
docker compose --env-file .env -f infra/compose.yaml up -d --force-recreate api worker dispatcher
```

Missing key errors are explicit; there is no fake production generation. Manual
recipes, tags, meal planning, stock and completion remain available without it.
The Friday dispatcher is included in Compose and uses household-local settings.
It does not require a separate scheduling key or desktop automation.

Saved weekly preferences use `planning.prompt {weekStart,prompt}` and the
`weeklyPrompts` workspace array. `GET /api/v1/kitchen/generation-jobs` exposes state,
attempts, error and retry time; `POST /api/v1/kitchen/generation-jobs/{week}/retry`
requeues failed work without replacing an existing plan. Plan displays these states.

The additional command surface includes atomic `tag.apply`, manual `meal.delete`,
`prep.save`, `prep.delete`, `plan.delete`, and `meal.leftovers`. Leftover output has
its own ledger operation and safe undo; undoing a meal with unreversed leftovers is
rejected. Meal changes reconcile pending prep quantities while retaining unrelated
prep; chat proposals carry relevant prep changes. Generated plans retain enabled
guidance content/version snapshots and isolate output batch IDs per plan.

## Reproducible acceptance

- `uv run python scripts/run-kitchen-e2e.py` creates an isolated PostgreSQL database,
  applies all migrations, starts the real API and a separate Next.js test server,
  then tests desktop/mobile browser flows. It removes only its generated database.
- `RECIPE_AGENT_TEST_DATABASE_URL=... uv run pytest` exercises all backend suites;
  use an empty disposable test database, never `recipe` or production data.
- `RUN_LIVE_AI_TESTS=1 uv run pytest tests/live` explicitly opts into real provider
  calls after key configuration; checks both an agent decision and Chinese recipe
  extraction. Without a key, it reports a skip instead of a false success.
- Production Python dependencies are hash-locked in `infra/requirements.lock`,
  exported from `uv.lock`. Regenerate with
  `uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file infra/requirements.lock`
  when deliberately updating dependencies.

The timing model remains conservative: one cook, each task's active segment followed
by waiting, with exclusive equipment. Available work fills equipment-wait gaps.
Unified portions have no invented adult/child/gram conversion. Multiple physical
prep batches can be recorded as separate tasks or extra inventory; a completed
single task is not repeatedly credited. Persistent preferences are edited in
Guidance; chat edits a scoped weekly plan and does not silently rewrite guidance.
