# Family Recipe Agent Phase Plan

## Planning Principle

Each phase delivers a runnable, independently testable vertical increment. Later phases extend explicit contracts rather than bypassing them. A phase is complete only when its acceptance suite passes from a clean checkout and its user-visible behavior works in the required locale and channel scope.

## Phase 0: Repository and Quality Foundation

### Outcome

A reproducible monorepo with backend and Web quality gates, containerized dependencies, health checks, and CI-ready commands.

### Scope

- Python and Node package configuration.
- FastAPI and Next.js bootstraps.
- PostgreSQL/pgvector, Redis, and MinIO in Docker Compose.
- Settings validation, logging, correlation IDs, health endpoints.
- Ruff, mypy, Pytest, ESLint, TypeScript, Vitest, and Playwright configuration.

### Exit Criteria

- One command starts local dependencies.
- API and Web health checks pass.
- Backend and frontend test commands run from a clean checkout.
- No secrets are committed.

## Phase 1: Identity, Localization, and Agent Core

### Outcome

An authenticated household can use one-language Web sessions and execute a persisted Understand, Plan, Act, Check, Continue agent run with fake tools.

### Scope

- Account, household, session, locale, conversation, agent run, and agent step models.
- Email magic-link service with a development delivery sink.
- Locale catalogs and parity tests.
- Conversation command, planned action, progress, and tool result contracts.
- Server-sent progress events.

### Exit Criteria

- Account creation produces one household.
- Locale switches the entire Web surface.
- A fake action reports success only after a persisted tool result.
- Cross-household access tests fail closed.

## Phase 2: Lark International Channel

### Outcome

A linked Lark identity can issue commands and receive localized progress and result cards through the shared agent core.

### Scope

- Lark v2 event verification, encryption, normalization, and deduplication.
- Three-second acknowledgement path.
- Lark linking code.
- Text, image, file, and card-action normalization.
- Progress and final card rendering.

### Exit Criteria

- Recorded Lark fixtures pass contract tests.
- Duplicate events cause one agent command.
- Long work acknowledges immediately and follows up asynchronously.
- Lark and Web use the same domain command.

## Phase 3: Imports and Recipe Library

### Outcome

Users can import text, images, Excel files, Xiaohongshu URLs, and generic URLs, then review saved recipes and sources.

### Scope

- Raw input, media, import job, recipe, source, ingredient, step, tag, confidence, and embedding models.
- Private object storage.
- Adapter registry and supported adapters.
- LiteLLM structured extraction and embeddings.
- Normalization, exact-source deduplication, review status, and recipe APIs.
- Recipe library and detail Web views.

### Exit Criteria

- Raw input persists before adapter or model execution.
- All supported fixtures create validated candidates.
- Failure fixtures remain `needs_review`.
- Exact duplicate fixtures do not create duplicate recipes.

## Phase 4: Recommendations

### Outcome

Every successful request returns exactly three ordered, explained choices.

### Scope

- Query parsing and structured filters.
- Candidate retrieval, deterministic scoring, diversity, and negative penalties.
- Generated shortfall candidates.
- Explanation rendering and selection analytics.
- Lark and Web recommendation cards.

### Exit Criteria

- Hard restrictions cannot be overridden by generated explanations.
- Household recipes precede generated suggestions.
- The result count is exactly three.
- Ranking fixtures produce deterministic order and reason codes.

## Phase 5: Weekly Planning and Shopping

### Outcome

Users can generate, inspect, and adjust a weekly plan and use its shopping list.

### Scope

- Meal plan, item, shopping list, and item models.
- Constraint and diversity planning.
- Single-item replacement.
- Ingredient quantity aggregation.
- Lark cards and Web plan/shopping views.

### Exit Criteria

- Replacing one item preserves accepted items.
- Shopping items retain recipe provenance.
- Compatible quantities merge; incompatible units remain separate.
- Mutations report success only after persistence.

## Phase 6: Feedback, Ratings, and Household Versions

### Outcome

Real cooking feedback changes future household behavior without destroying the original recipe.

### Scope

- Cook sessions, ratings, feedback events, structured deltas, and recipe versions.
- Natural-language feedback parsing.
- Ambiguous recipe selection.
- Ranking feature updates.
- Version history in Web and confirmation cards in Lark.

### Exit Criteria

- Every feedback request creates an immutable event.
- Structural changes create a new version.
- Negative preference affects ranking without deleting content.
- Private ratings do not enter public output.

## Phase 7: Privacy-Safe Sharing

### Outcome

Users can share a localized recipe or collection through a revocable public snapshot.

### Scope

- Collections, immutable snapshots, share tokens, expiry, and revocation.
- Explicit privacy allowlist.
- Public share page and owner management screen.
- Share analytics without private payloads.

### Exit Criteria

- Security fixtures prove all excluded fields are absent.
- Revoked and expired tokens fail closed.
- Snapshot content does not change when the private recipe changes.

## Phase 8: Full-MVP Hardening and Beta Gate

### Outcome

The complete product is ready for design-partner deployment.

### Scope

- Transactional outbox and dead-letter operations.
- Rate limits, storage validation, redaction, and security headers.
- OpenTelemetry, metrics, dashboards, and operational runbooks.
- Full bilingual, Lark, Web, import, recommendation, plan, feedback, and share E2E suite.
- Container security and migration rehearsal.

### Exit Criteria

- Complete CI passes from a clean checkout.
- P0 and P1 requirements have traceable tests.
- Representative import usability is at least 80%.
- Household isolation and share privacy suites report zero violations.
- Lark callback latency stays below the three-second acknowledgement requirement.

## Dependency Order

Phase 0 precedes all work. Phase 1 precedes Lark and all domain actions. Phase 3 precedes recommendations. Phase 4 precedes weekly planning. Feedback and sharing can begin after the recipe contracts stabilize, but the inline execution order remains sequential to keep migrations and acceptance checkpoints reviewable.
