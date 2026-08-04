# Family Recipe Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-oriented full MVP that operates through Lark international and a localized Web UI, preserves household recipe memory, returns exactly three recommendations, and completes planning, feedback, and sharing actions.

**Architecture:** A Python modular monolith exposes one FastAPI orchestration hub and explicit domain-spoke interfaces. Celery workers scale asynchronous spokes independently; PostgreSQL/pgvector, Redis, and S3-compatible storage remain externalized. A Next.js application and Lark adapter normalize into the same conversation command and agent loop.

**Tech Stack:** Python 3.12, FastAPI 0.139, Pydantic 2.13, SQLAlchemy 2.0, Alembic 1.18, Celery 5.6, LiteLLM 1.84+, PostgreSQL 17/pgvector, Redis 8, MinIO/S3, Node.js 24 LTS, Next.js 16, React 19, TypeScript 5.9, pnpm 10, Pytest, Ruff, mypy, Vitest, Testing Library, and Playwright.

## Global Constraints

- Code, identifiers, comments, commit messages, and technical documentation use English.
- User-visible content supports `zh-CN` and `en-US`, but each screen or message uses one locale only.
- Lark targets `open.larksuite.com` and acknowledges event callbacks within three seconds.
- Each account owns one household; every household-owned operation enforces household scope.
- OpenAI is accessed only through the internal `AIProvider` interface backed by LiteLLM.
- Raw input is persisted before parsing or model invocation.
- Successful recommendation requests return exactly three choices.
- User-visible agent progress summarizes Understand, Plan, Act, Check, and Continue without exposing private reasoning.
- A mutation is never described as successful without a persisted tool result.
- Every production behavior follows a verified red-green-refactor cycle.

---

## File Map

### Root and Infrastructure

- `pyproject.toml`: Python package, dependency, lint, typing, and test configuration.
- `Makefile`: stable developer and CI commands.
- `.env.example`: non-secret configuration contract.
- `infra/compose.yaml`: PostgreSQL/pgvector, Redis, MinIO, API, worker, and Web services.
- `infra/Dockerfile.api`: non-root API image.
- `infra/Dockerfile.worker`: worker command over the API image.
- `infra/Dockerfile.web`: Next.js standalone image.

### Backend

- `src/recipe_agent/app.py`: FastAPI application factory and lifespan.
- `src/recipe_agent/config.py`: validated settings.
- `src/recipe_agent/api/`: transport routes, dependencies, and error mapping.
- `src/recipe_agent/domain/common/`: IDs, clocks, errors, events, and result contracts.
- `src/recipe_agent/domain/identity/`: account, household, sessions, linking, and locale.
- `src/recipe_agent/domain/conversation/`: normalized commands and agent orchestration.
- `src/recipe_agent/domain/imports/`: raw input, adapters, extraction, and import service.
- `src/recipe_agent/domain/recipes/`: recipes, versions, repositories, and queries.
- `src/recipe_agent/domain/recommendations/`: retrieval, scoring, filling, and explanations.
- `src/recipe_agent/domain/planning/`: meal plans and shopping aggregation.
- `src/recipe_agent/domain/feedback/`: feedback events, ratings, and version deltas.
- `src/recipe_agent/domain/sharing/`: collections, privacy projection, snapshots, and tokens.
- `src/recipe_agent/infrastructure/`: SQLAlchemy, LiteLLM, Celery, S3, Lark, and observability adapters.

### Web

- `web/src/app/`: App Router routes.
- `web/src/components/`: shared accessible UI elements.
- `web/src/features/`: chat, recipes, plans, shopping, imports, shares, and settings.
- `web/src/i18n/`: locale catalogs and parity validation.
- `web/tests/`: Vitest component and Playwright E2E tests.

### Tests

- `tests/unit/`: pure domain tests.
- `tests/contract/`: Lark, LiteLLM, job, adapter, and HTTP schema fixtures.
- `tests/integration/`: real service adapters.
- `tests/security/`: tenant isolation, webhook, token, upload, and privacy tests.
- `tests/e2e/`: channel-independent application flows.

---

### Task 1: Reproducible Repository Foundation

**Files:**
- Create: `pyproject.toml`
- Create: `Makefile`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/recipe_agent/__init__.py`
- Create: `src/recipe_agent/config.py`
- Create: `src/recipe_agent/app.py`
- Create: `tests/unit/test_app.py`
- Create: `infra/compose.yaml`
- Create: `infra/Dockerfile.api`
- Create: `infra/Dockerfile.worker`

**Interfaces:**
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`
- Produces: `Settings` with development-safe defaults and production secret validation.

- [ ] **Step 1: Write the failing application test**

```python
from fastapi.testclient import TestClient

from recipe_agent.app import create_app
from recipe_agent.config import Settings


def test_health_endpoints_report_application_state() -> None:
    app = create_app(Settings(environment="test"))
    client = TestClient(app)

    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}
```

- [ ] **Step 2: Run the test and verify the missing-package failure**

Run: `python -m pytest tests/unit/test_app.py -v`

Expected: FAIL because `recipe_agent.app` does not exist.

- [ ] **Step 3: Add package configuration and minimal application code**

```python
# src/recipe_agent/config.py
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECIPE_AGENT_")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://recipe:recipe@localhost:5432/recipe"
    redis_url: str = "redis://localhost:6379/0"
    session_signing_key: str = "development-only-session-key"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# src/recipe_agent/app.py
from fastapi import FastAPI

from recipe_agent.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="Family Recipe Agent", version="0.1.0")
    app.state.settings = resolved

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    return app


app = create_app()
```

- [ ] **Step 4: Add Docker Compose dependencies and stable commands**

Define PostgreSQL 17 with pgvector, Redis 8, and MinIO services with named volumes and health checks. Add `make test`, `make lint`, `make typecheck`, `make services-up`, and `make services-down` commands that call explicit tools without shell-specific behavior.

- [ ] **Step 5: Run foundation validation**

Run: `python -m pytest tests/unit/test_app.py -v`

Expected: PASS with two health assertions.

Run: `ruff check src tests && mypy src`

Expected: both commands exit 0.

- [ ] **Step 6: Commit the foundation**

```bash
git add pyproject.toml Makefile .gitignore .env.example src tests/unit/test_app.py infra
git commit -m "build: establish repository foundation"
```

### Task 2: Core Contracts, Localization, and Agent Loop

**Files:**
- Create: `src/recipe_agent/domain/common/types.py`
- Create: `src/recipe_agent/domain/conversation/contracts.py`
- Create: `src/recipe_agent/domain/conversation/orchestrator.py`
- Create: `src/recipe_agent/domain/conversation/tools.py`
- Create: `src/recipe_agent/domain/identity/locale.py`
- Create: `src/recipe_agent/locales/en-US.json`
- Create: `src/recipe_agent/locales/zh-CN.json`
- Create: `tests/unit/conversation/test_orchestrator.py`
- Create: `tests/unit/identity/test_locale.py`

**Interfaces:**
- Produces: `ConversationCommand`, `AgentStage`, `PlannedAction`, `ToolResult`, and `AgentProgress`.
- Produces: `AgentOrchestrator.run(command: ConversationCommand) -> AgentOutcome`.
- Produces: `Translator.render(locale: Locale, key: str, values: Mapping[str, object]) -> str`.

- [ ] **Step 1: Write failing agent and locale tests**

```python
async def test_agent_reports_plan_and_persisted_action_before_success() -> None:
    tool = RecordingTool(result=ToolResult(persisted=True, data={"recipe_id": "r1"}))
    sink = RecordingProgressSink()
    orchestrator = AgentOrchestrator(planner=SaveRecipePlanner(), tools={"save_recipe": tool}, progress=sink)

    outcome = await orchestrator.run(command_for("save this recipe"))

    assert [event.stage for event in sink.events] == [
        AgentStage.UNDERSTANDING,
        AgentStage.PLANNING,
        AgentStage.ACTING,
        AgentStage.CHECKING,
        AgentStage.CONTINUING,
    ]
    assert outcome.persisted is True
```

```python
def test_locale_catalogs_have_identical_keys() -> None:
    translator = Translator.from_package()
    assert translator.keys(Locale.EN_US) == translator.keys(Locale.ZH_CN)
```

- [ ] **Step 2: Verify both tests fail for missing contracts**

Run: `python -m pytest tests/unit/conversation/test_orchestrator.py tests/unit/identity/test_locale.py -v`

Expected: FAIL because the contracts and services do not exist.

- [ ] **Step 3: Implement immutable contracts and tool registry**

```python
class AgentStage(StrEnum):
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    ACTING = "acting"
    CHECKING = "checking"
    CONTINUING = "continuing"
    WAITING_FOR_USER = "waiting_for_user"
    FAILED = "failed"
    COMPLETED = "completed"


class ToolResult(BaseModel):
    persisted: bool
    data: dict[str, JsonValue] = Field(default_factory=dict)


class AgentOutcome(BaseModel):
    run_id: UUID
    persisted: bool
    result: dict[str, JsonValue]
```

Implement the orchestrator as a state machine that publishes each progress event, invokes typed tools, rejects success wording for `persisted=False` mutations, and returns `WAITING_FOR_USER` only for critical ambiguity.

- [ ] **Step 4: Implement catalog loading with parity validation**

Create complete initial keys for health, authentication, agent stages, imports, recommendations, plans, feedback, shares, and generic errors in both catalogs. `Translator` must raise `MissingTranslationError` for unknown keys rather than falling back to mixed-language copy.

- [ ] **Step 5: Run the focused and full unit suites**

Run: `python -m pytest tests/unit/conversation tests/unit/identity -v`

Expected: PASS.

Run: `python -m pytest tests/unit -q`

Expected: all current unit tests pass.

- [ ] **Step 6: Commit core behavior**

```bash
git add src/recipe_agent/domain src/recipe_agent/locales tests/unit/conversation tests/unit/identity
git commit -m "feat: add localized agent execution loop"
```

### Task 3: Database, Identity, and Household Isolation

**Files:**
- Create: `src/recipe_agent/infrastructure/db/base.py`
- Create: `src/recipe_agent/infrastructure/db/session.py`
- Create: `src/recipe_agent/domain/identity/models.py`
- Create: `src/recipe_agent/domain/identity/repository.py`
- Create: `src/recipe_agent/domain/identity/service.py`
- Create: `src/recipe_agent/api/v1/auth.py`
- Create: `migrations/env.py`
- Create: `migrations/versions/0001_identity_and_agent.py`
- Create: `tests/integration/identity/test_identity.py`
- Create: `tests/security/test_household_isolation.py`

**Interfaces:**
- Produces: `IdentityService.request_magic_link(email)`, `consume_magic_link(token)`, `create_lark_link_code(account_id)`, and `link_lark_identity(code, open_id)`.
- Produces: `HouseholdScope(account_id: UUID, household_id: UUID)` dependency for all domain routes.

- [ ] **Step 1: Write failing identity and isolation tests**

```python
async def test_consuming_magic_link_creates_one_account_and_household(identity_service) -> None:
    delivery = await identity_service.request_magic_link("cook@example.com")
    session = await identity_service.consume_magic_link(delivery.token)

    assert session.account.email == "cook@example.com"
    assert session.household.owner_account_id == session.account.id
```

```python
async def test_repository_rejects_recipe_from_another_household(recipe_repository, two_households) -> None:
    first, second = two_households
    recipe = await recipe_repository.create(first.id, recipe_record())

    with pytest.raises(NotFoundError):
        await recipe_repository.get(second.id, recipe.id)
```

- [ ] **Step 2: Verify failures against the real PostgreSQL fixture**

Run: `python -m pytest tests/integration/identity/test_identity.py tests/security/test_household_isolation.py -v`

Expected: FAIL because models and repositories are missing.

- [ ] **Step 3: Implement identity schema and migration**

Create `accounts`, `households`, `lark_identities`, `magic_links`, `web_sessions`, `conversations`, `conversation_messages`, `agent_runs`, and `agent_run_steps`. Use UUIDv7-compatible UUID columns, UTC timestamps, unique normalized email, hashed tokens, expiry, single-use consumption, and non-null ownership constraints.

- [ ] **Step 4: Implement secure identity services and routes**

Magic-link and linking tokens use `secrets.token_urlsafe(32)`, persist only a SHA-256 hash, expire, and are consumed once. Session cookies use Secure outside development, HTTP-only, SameSite=Lax, and rotation after authentication.

- [ ] **Step 5: Run migrations and isolation tests**

Run: `alembic upgrade head`

Expected: migration completes without warnings.

Run: `python -m pytest tests/integration/identity tests/security/test_household_isolation.py -v`

Expected: PASS.

- [ ] **Step 6: Commit identity and persistence**

```bash
git add src/recipe_agent/infrastructure/db src/recipe_agent/domain/identity src/recipe_agent/api/v1/auth.py migrations tests/integration/identity tests/security/test_household_isolation.py
git commit -m "feat: add household identity and isolation"
```

### Task 4: Lark International Transport

**Files:**
- Create: `src/recipe_agent/infrastructure/lark/crypto.py`
- Create: `src/recipe_agent/infrastructure/lark/client.py`
- Create: `src/recipe_agent/infrastructure/lark/normalizer.py`
- Create: `src/recipe_agent/infrastructure/lark/renderer.py`
- Create: `src/recipe_agent/api/lark.py`
- Create: `tests/contract/lark/fixtures/message_v2.json`
- Create: `tests/contract/lark/test_events.py`
- Create: `tests/unit/lark/test_renderer.py`

**Interfaces:**
- Consumes: `ConversationCommand`, `AgentProgress`, `AgentOutcome`, and `Translator`.
- Produces: `LarkEventNormalizer.normalize(payload) -> ConversationCommand`.
- Produces: `LarkClient.send_progress()` and `send_outcome()`.

- [ ] **Step 1: Write failing verification, deduplication, and rendering tests**

```python
def test_lark_v2_message_normalizes_without_transport_fields(fixture_payload) -> None:
    command = normalizer.normalize(fixture_payload)
    assert command.channel == "lark"
    assert command.idempotency_key == fixture_payload["header"]["event_id"]
    assert command.text == "Save this recipe"
```

```python
async def test_duplicate_event_is_acknowledged_once(client, event_store, signed_payload) -> None:
    first = await client.post("/webhooks/lark/events", json=signed_payload)
    second = await client.post("/webhooks/lark/events", json=signed_payload)
    assert first.status_code == second.status_code == 200
    assert await event_store.publish_count(signed_payload["header"]["event_id"]) == 1
```

- [ ] **Step 2: Verify expected failures**

Run: `python -m pytest tests/contract/lark tests/unit/lark -v`

Expected: FAIL because the Lark transport is absent.

- [ ] **Step 3: Implement Lark v2 callback boundary**

Verify the configured verification token, decrypt encrypted payloads, validate event structure, insert `event_id` with a unique constraint, publish the normalized command once, and return HTTP 200 before background execution.

- [ ] **Step 4: Implement single-locale progress and result cards**

Render one locale per card. Chinese cards use Chinese keys; English cards use English keys. Progress cards show understanding, plan, completed action receipts, checking, and result. Card actions carry signed opaque context rather than raw household IDs.

- [ ] **Step 5: Run contract and latency tests**

Run: `python -m pytest tests/contract/lark tests/unit/lark -v`

Expected: PASS, including duplicate-event and card locale assertions.

- [ ] **Step 6: Commit Lark transport**

```bash
git add src/recipe_agent/infrastructure/lark src/recipe_agent/api/lark.py tests/contract/lark tests/unit/lark
git commit -m "feat: add Lark agent transport"
```

### Task 5: Import Pipeline and Recipe Library

**Files:**
- Create: `src/recipe_agent/domain/imports/contracts.py`
- Create: `src/recipe_agent/domain/imports/adapters.py`
- Create: `src/recipe_agent/domain/imports/service.py`
- Create: `src/recipe_agent/domain/recipes/models.py`
- Create: `src/recipe_agent/domain/recipes/repository.py`
- Create: `src/recipe_agent/infrastructure/ai/litellm_provider.py`
- Create: `src/recipe_agent/infrastructure/storage/s3.py`
- Create: `src/recipe_agent/infrastructure/jobs/imports.py`
- Create: `migrations/versions/0002_imports_and_recipes.py`
- Create: `tests/unit/imports/test_registry.py`
- Create: `tests/integration/imports/test_raw_first.py`
- Create: `tests/contract/ai/test_recipe_extraction.py`

**Interfaces:**
- Produces: `InputAdapter.supports()` and `extract()`.
- Produces: `ImportService.receive(command) -> ImportReceipt` and `process(raw_input_id) -> ImportOutcome`.
- Produces: `AIProvider.parse_structured()` and `embed()`.

- [ ] **Step 1: Write failing raw-first and extraction tests**

```python
async def test_raw_input_survives_adapter_failure(import_service, failing_adapter, raw_repository) -> None:
    receipt = await import_service.receive(import_command("https://example.invalid/recipe"))
    with pytest.raises(ExternalPlatformError):
        await import_service.process(receipt.raw_input_id)

    saved = await raw_repository.get(receipt.household_id, receipt.raw_input_id)
    assert saved.status == RawInputStatus.NEEDS_REVIEW
    assert saved.source_url == "https://example.invalid/recipe"
```

```python
def test_recipe_candidate_rejects_steps_without_ingredients() -> None:
    with pytest.raises(ValidationError):
        RecipeCandidate(name="Soup", ingredients=(), steps=(RecipeStepCandidate(number=1, text="Boil"),))
```

- [ ] **Step 2: Run focused tests and confirm missing-feature failures**

Run: `python -m pytest tests/unit/imports tests/integration/imports tests/contract/ai -v`

Expected: FAIL because import contracts and persistence do not exist.

- [ ] **Step 3: Implement schema, migration, and storage adapters**

Create raw input, media, import job, recipe, source, ingredient, step, tag, version, and embedding tables. Store object keys rather than public URLs. Implement text, image, Excel, Xiaohongshu URL, and generic URL adapters through a deterministic registry.

- [ ] **Step 4: Implement LiteLLM extraction and one repair attempt**

The adapter sends the versioned Pydantic JSON schema, validates the response, performs one repair request on validation failure, and then returns a typed provider error. Tests use recorded responses and never call a live provider.

- [ ] **Step 5: Implement recipe APIs and verify all import fixtures**

Run: `alembic upgrade head && python -m pytest tests/unit/imports tests/integration/imports tests/contract/ai -v`

Expected: PASS for text, image metadata, Excel column mapping, URL fallback, raw preservation, and validation.

- [ ] **Step 6: Commit import and recipe capabilities**

```bash
git add src/recipe_agent/domain/imports src/recipe_agent/domain/recipes src/recipe_agent/infrastructure/ai src/recipe_agent/infrastructure/storage src/recipe_agent/infrastructure/jobs migrations tests/unit/imports tests/integration/imports tests/contract/ai
git commit -m "feat: add recipe import pipeline"
```

### Task 6: Exactly-Three Recommendation Engine

**Files:**
- Create: `src/recipe_agent/domain/recommendations/contracts.py`
- Create: `src/recipe_agent/domain/recommendations/scoring.py`
- Create: `src/recipe_agent/domain/recommendations/service.py`
- Create: `src/recipe_agent/api/v1/recommendations.py`
- Create: `tests/unit/recommendations/test_scoring.py`
- Create: `tests/unit/recommendations/test_service.py`
- Create: `tests/e2e/test_recommendations.py`

**Interfaces:**
- Consumes: household recipe repository and `AIProvider` for shortfall generation and explanation.
- Produces: `RecommendationService.recommend(query) -> tuple[RecommendationResult, RecommendationResult, RecommendationResult]`.

- [ ] **Step 1: Write failing count, ordering, and safety tests**

```python
async def test_recommendation_returns_exactly_three_household_first(service) -> None:
    results = await service.recommend(query_with_three_ingredients())
    assert len(results) == 3
    assert [result.source for result in results] == [
        RecommendationSource.HOUSEHOLD,
        RecommendationSource.HOUSEHOLD,
        RecommendationSource.GENERATED,
    ]
```

```python
def test_age_and_allergy_restrictions_are_hard_filters(rank_candidates) -> None:
    results = rank_candidates(candidates_with_allergen(), query_for_child_with_allergy())
    assert all("peanut" not in item.allergens for item in results)
```

- [ ] **Step 2: Verify red state**

Run: `python -m pytest tests/unit/recommendations -v`

Expected: FAIL because recommendation modules are missing.

- [ ] **Step 3: Implement deterministic scoring and reason codes**

```python
score = (
    features.ingredient_match * Decimal("0.25")
    + features.meal_type_fit * Decimal("0.15")
    + features.age_fit * Decimal("0.15")
    + features.rating * Decimal("0.20")
    + features.time_fit * Decimal("0.10")
    + features.scenario_fit * Decimal("0.10")
    + features.diversity * Decimal("0.05")
    - features.difficulty_penalty
    - features.recent_repeat_penalty
    - features.negative_feedback_penalty
)
```

Use stable tie-breaking by score, household source, rating count, canonical name, and recipe ID.

- [ ] **Step 4: Implement exact-three filling**

Retrieve and rank eligible household recipes. If fewer than three remain, request exactly `3 - len(household_results)` generated candidates, label them as generated, validate restrictions, and do not persist them. Raise a typed capacity error only when the provider cannot produce safe candidates.

- [ ] **Step 5: Run unit and E2E recommendation suites**

Run: `python -m pytest tests/unit/recommendations tests/e2e/test_recommendations.py -v`

Expected: PASS with exactly three results and deterministic explanations.

- [ ] **Step 6: Commit recommendations**

```bash
git add src/recipe_agent/domain/recommendations src/recipe_agent/api/v1/recommendations.py tests/unit/recommendations tests/e2e/test_recommendations.py
git commit -m "feat: return three household recommendations"
```

### Task 7: Weekly Planning and Shopping Lists

**Files:**
- Create: `src/recipe_agent/domain/planning/contracts.py`
- Create: `src/recipe_agent/domain/planning/service.py`
- Create: `src/recipe_agent/domain/planning/shopping.py`
- Create: `src/recipe_agent/api/v1/planning.py`
- Create: `migrations/versions/0003_planning.py`
- Create: `tests/unit/planning/test_plan.py`
- Create: `tests/unit/planning/test_shopping.py`
- Create: `tests/e2e/test_weekly_plan.py`

**Interfaces:**
- Consumes: `RecommendationService.recommend()` and recipe ingredient records.
- Produces: `PlanningService.create_week()` and `replace_item()`.
- Produces: `ShoppingAggregator.aggregate(plan) -> ShoppingListDraft`.

- [ ] **Step 1: Write failing replacement and aggregation tests**

```python
async def test_replacing_one_item_preserves_other_plan_items(planning_service, saved_plan) -> None:
    original_ids = {item.id for item in saved_plan.items if item.day != date(2026, 7, 16)}
    updated = await planning_service.replace_item(saved_plan.household_id, saved_plan.id, date(2026, 7, 16))
    assert original_ids <= {item.id for item in updated.items}
```

```python
def test_shopping_aggregator_merges_compatible_units_only() -> None:
    result = ShoppingAggregator().aggregate(ingredients_for_unit_cases())
    assert result.quantity_for("egg", "piece") == Decimal("5")
    assert result.entries_for("soy sauce") == 2
```

- [ ] **Step 2: Verify red state**

Run: `python -m pytest tests/unit/planning -v`

Expected: FAIL because planning services do not exist.

- [ ] **Step 3: Implement plan persistence and optimistic versions**

Create meal plan, plan item, shopping list, and shopping item tables. Persist constraint JSON, source recipe IDs, item reasons, list provenance, checked state, and a version integer used for optimistic updates.

- [ ] **Step 4: Implement planning, replacement, and aggregation**

Use recommendation results per slot, prevent duplicate recipe IDs within the configured window, preserve accepted items during replacement, and aggregate quantities only when canonical ingredient and unit match.

- [ ] **Step 5: Run migration, unit, and E2E tests**

Run: `alembic upgrade head && python -m pytest tests/unit/planning tests/e2e/test_weekly_plan.py -v`

Expected: PASS.

- [ ] **Step 6: Commit planning**

```bash
git add src/recipe_agent/domain/planning src/recipe_agent/api/v1/planning.py migrations/versions/0003_planning.py tests/unit/planning tests/e2e/test_weekly_plan.py
git commit -m "feat: add weekly plans and shopping lists"
```

### Task 8: Feedback, Ratings, Versions, and Sharing

**Files:**
- Create: `src/recipe_agent/domain/feedback/contracts.py`
- Create: `src/recipe_agent/domain/feedback/service.py`
- Create: `src/recipe_agent/domain/sharing/projection.py`
- Create: `src/recipe_agent/domain/sharing/service.py`
- Create: `src/recipe_agent/api/v1/feedback.py`
- Create: `src/recipe_agent/api/v1/shares.py`
- Create: `migrations/versions/0004_feedback_and_sharing.py`
- Create: `tests/unit/feedback/test_service.py`
- Create: `tests/unit/sharing/test_projection.py`
- Create: `tests/security/test_share_privacy.py`
- Create: `tests/e2e/test_feedback_and_share.py`

**Interfaces:**
- Produces: `FeedbackService.record()` and `RatingService.record()`.
- Produces: `ShareService.create_snapshot()`, `resolve_token()`, and `revoke()`.

- [ ] **Step 1: Write failing event/version and privacy tests**

```python
async def test_structural_feedback_creates_event_and_new_version(feedback_service, recipe) -> None:
    outcome = await feedback_service.record(recipe.household_id, recipe.id, "Cook five minutes longer")
    assert outcome.feedback_event.raw_text == "Cook five minutes longer"
    assert outcome.recipe_version.parent_version_id == recipe.active_version_id
```

```python
def test_share_projection_excludes_private_fields() -> None:
    snapshot = ShareProjection().recipe(private_recipe_fixture())
    serialized = snapshot.model_dump_json()
    for forbidden in ("child_name", "private_photo", "child_rating", "email", "phone"):
        assert forbidden not in serialized
```

- [ ] **Step 2: Verify red state**

Run: `python -m pytest tests/unit/feedback tests/unit/sharing tests/security/test_share_privacy.py -v`

Expected: FAIL because feedback and sharing modules are absent.

- [ ] **Step 3: Implement immutable feedback and versions**

Persist every feedback event before applying a structured delta. Validate rating range one to five. Create a new recipe version for ingredient, quantity, time, or step changes; update ranking feature records for preference and suppression changes.

- [ ] **Step 4: Implement explicit privacy allowlist and token lifecycle**

Snapshot models contain only public recipe fields. Generate a 32-byte token, store its SHA-256 hash, return the raw token once, enforce expiry, and mark revocation without changing the immutable snapshot.

- [ ] **Step 5: Run security and E2E suites**

Run: `alembic upgrade head && python -m pytest tests/unit/feedback tests/unit/sharing tests/security/test_share_privacy.py tests/e2e/test_feedback_and_share.py -v`

Expected: PASS with no forbidden fields.

- [ ] **Step 6: Commit memory and sharing**

```bash
git add src/recipe_agent/domain/feedback src/recipe_agent/domain/sharing src/recipe_agent/api/v1/feedback.py src/recipe_agent/api/v1/shares.py migrations/versions/0004_feedback_and_sharing.py tests/unit/feedback tests/unit/sharing tests/security/test_share_privacy.py tests/e2e/test_feedback_and_share.py
git commit -m "feat: add household memory and safe sharing"
```

### Task 9: Localized Web Application

**Files:**
- Create: `pnpm-workspace.yaml`
- Create: `web/package.json`
- Create: `web/next.config.ts`
- Create: `web/src/app/layout.tsx`
- Create: `web/src/app/chat/page.tsx`
- Create: `web/src/app/recipes/page.tsx`
- Create: `web/src/app/recipes/[id]/page.tsx`
- Create: `web/src/app/plan/page.tsx`
- Create: `web/src/app/shopping/page.tsx`
- Create: `web/src/app/imports/page.tsx`
- Create: `web/src/app/shares/page.tsx`
- Create: `web/src/app/settings/page.tsx`
- Create: `web/src/app/s/[token]/page.tsx`
- Create: `web/src/components/app-shell.tsx`
- Create: `web/src/components/language-switcher.tsx`
- Create: `web/src/features/chat/agent-progress.tsx`
- Create: `web/src/i18n/en-US.json`
- Create: `web/src/i18n/zh-CN.json`
- Create: `web/tests/language-switcher.test.tsx`
- Create: `web/tests/agent-progress.test.tsx`
- Create: `web/tests/e2e/core-flow.spec.ts`

**Interfaces:**
- Consumes: `/api/v1` JSON resources and server-sent agent progress.
- Produces: one-language responsive screens for every MVP route.

- [ ] **Step 1: Write failing locale and progress component tests**

```tsx
it("switches the complete shell to English", async () => {
  render(<TestLocalizedShell initialLocale="zh-CN" />);
  await userEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("navigation")).toHaveTextContent("Recipes");
  expect(screen.queryByText("菜谱库")).not.toBeInTheDocument();
});
```

```tsx
it("shows action receipts without private reasoning", () => {
  render(<AgentProgressView progress={completedRecommendationProgress} />);
  expect(screen.getByText("Checked household recipes")).toBeVisible();
  expect(screen.queryByText(/chain of thought/i)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Verify component tests fail**

Run: `pnpm --dir web vitest run web/tests/language-switcher.test.tsx web/tests/agent-progress.test.tsx`

Expected: FAIL because the Web application is absent.

- [ ] **Step 3: Implement App Router shell and locale catalogs**

Use an accessible sidebar, top-right language switcher, responsive main region, and account-backed locale mutation. Validate catalog key parity in a Vitest test. Never render both locale values for ordinary page copy.

- [ ] **Step 4: Implement feature routes and agent progress stream**

Chat subscribes to server-sent events and renders understanding, plan, action receipts, checking, result, and next actions. Resource pages use typed API clients and explicit loading, empty, and error states.

- [ ] **Step 5: Run Web unit, type, build, and E2E checks**

Run: `pnpm --dir web test && pnpm --dir web typecheck && pnpm --dir web build`

Expected: all commands exit 0.

Run: `pnpm --dir web playwright test web/tests/e2e/core-flow.spec.ts`

Expected: core Web flow passes in Chinese and English projects.

- [ ] **Step 6: Commit the Web application**

```bash
git add pnpm-workspace.yaml web
git commit -m "feat: add localized Web experience"
```

### Task 10: Operations, Security, and Full-MVP Verification

**Files:**
- Create: `src/recipe_agent/infrastructure/observability/logging.py`
- Create: `src/recipe_agent/infrastructure/observability/metrics.py`
- Create: `src/recipe_agent/infrastructure/db/outbox.py`
- Create: `src/recipe_agent/infrastructure/jobs/outbox.py`
- Create: `src/recipe_agent/api/security.py`
- Create: `infra/Dockerfile.web`
- Create: `.github/workflows/ci.yml`
- Create: `docs/runbooks/deployment.md`
- Create: `docs/runbooks/failed-jobs.md`
- Create: `tests/security/test_webhook_and_uploads.py`
- Create: `tests/e2e/test_full_mvp.py`

**Interfaces:**
- Consumes: all API, worker, Web, and domain capabilities.
- Produces: clean-checkout CI, deployable images, traces, metrics, and recovery runbooks.

- [ ] **Step 1: Write failing redaction, outbox, and full-flow tests**

```python
def test_structured_log_redacts_secrets_and_private_text() -> None:
    rendered = render_log({"authorization": "Bearer secret", "message_text": "private recipe"})
    assert "secret" not in rendered
    assert "private recipe" not in rendered
    assert "[REDACTED]" in rendered
```

```python
async def test_outbox_publishes_committed_event_once(outbox, publisher, db_session) -> None:
    event = await outbox.add(db_session, "recipe.saved", {"recipe_id": "r1"})
    await db_session.commit()
    await publish_pending(outbox, publisher)
    await publish_pending(outbox, publisher)
    assert publisher.count(event.id) == 1
```

- [ ] **Step 2: Verify security and E2E tests fail**

Run: `python -m pytest tests/security tests/e2e/test_full_mvp.py -v`

Expected: FAIL for missing operational components and full-flow fixture.

- [ ] **Step 3: Implement outbox, redaction, limits, and observability**

Persist outbox events in the mutation transaction, publish idempotently, redact configured fields before serialization, enforce route and operation limits, expose protected metrics, and add correlation IDs to request, command, run, job, model, and database spans.

- [ ] **Step 4: Complete production containers and CI**

Run API and Web images as non-root users, add health checks, use Next.js standalone output, run migrations as an explicit CI and release step, and configure CI jobs for backend quality, integration services, Web quality, container builds, and full E2E.

- [ ] **Step 5: Run the complete clean-checkout verification**

Run: `make verify`

Expected: formatting, Ruff, mypy, backend tests, migrations, Web tests, TypeScript, Web build, and Playwright all pass with zero warnings treated as errors.

Run: `docker compose -f infra/compose.yaml build`

Expected: API, worker, and Web images build successfully.

- [ ] **Step 6: Commit beta hardening**

```bash
git add src/recipe_agent/infrastructure/observability src/recipe_agent/infrastructure/db/outbox.py src/recipe_agent/infrastructure/jobs/outbox.py src/recipe_agent/api/security.py infra .github docs/runbooks tests/security tests/e2e/test_full_mvp.py
git commit -m "feat: harden full MVP for beta"
```

---

## Plan Self-Review Matrix

| Specification Area | Implementing Tasks |
| --- | --- |
| Runtime, containers, quality gates | 1, 10 |
| Identity, household scope, locale | 2, 3, 9 |
| Understand, Plan, Act, Check, Continue | 2, 4, 9 |
| Lark international | 4 |
| Raw-first imports and recipe library | 5 |
| LiteLLM provider boundary | 5, 6 |
| Exactly three recommendations | 6 |
| Weekly planning and shopping | 7 |
| Feedback, ratings, versions | 8 |
| Privacy-safe sharing | 8, 9 |
| Responsive one-language Web UI | 9 |
| Security, observability, outbox, CI | 10 |

All specified product requirements map to at least one task. Exact contract names are consistent across producer and consumer tasks: `ConversationCommand`, `AgentProgress`, `AgentOutcome`, `AIProvider`, `InputAdapter`, `RecommendationService`, `PlanningService`, `FeedbackService`, and `ShareService`.
