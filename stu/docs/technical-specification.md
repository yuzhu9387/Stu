# Family Recipe Agent Technical Specification

## 1. Runtime Baseline

- Python 3.12.
- FastAPI `>=0.139,<0.140`.
- Pydantic `>=2.13,<2.14`.
- SQLAlchemy `>=2.0.51,<2.1`.
- Alembic `>=1.18.5,<1.19`.
- Celery `>=5.6.3,<5.7` with Redis transport.
- LiteLLM `>=1.84,<2` behind an internal provider interface.
- PostgreSQL 17 with pgvector.
- Redis 8.
- S3-compatible object storage; MinIO is the local implementation.
- Node.js 24 LTS.
- Next.js `>=16.2,<17`, React 19, TypeScript 5.9, pnpm 10.
- Pytest, Ruff, mypy, Vitest, Testing Library, and Playwright.

Dependencies are locked in reproducible lockfiles. Patch upgrades within these ranges require CI to pass.

## 2. Repository Structure

```text
.
├── src/recipe_agent/
│   ├── app.py
│   ├── config.py
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── errors.py
│   │   └── v1/
│   ├── domain/
│   │   ├── common/
│   │   ├── identity/
│   │   ├── conversation/
│   │   ├── imports/
│   │   ├── recipes/
│   │   ├── recommendations/
│   │   ├── planning/
│   │   ├── feedback/
│   │   └── sharing/
│   └── infrastructure/
│       ├── ai/
│       ├── db/
│       ├── jobs/
│       ├── lark/
│       ├── observability/
│       └── storage/
├── migrations/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── security/
│   └── e2e/
├── web/
│   ├── src/app/
│   ├── src/components/
│   ├── src/features/
│   ├── src/i18n/
│   └── tests/
├── infra/
│   ├── compose.yaml
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   └── Dockerfile.web
├── docs/
├── pyproject.toml
├── pnpm-workspace.yaml
└── Makefile
```

Domain modules may import `domain.common` and their own files. They may not import FastAPI, Celery, Lark SDKs, boto clients, LiteLLM, or SQLAlchemy sessions directly. Infrastructure adapters implement domain protocols.

## 3. Configuration

`Settings` is loaded through `pydantic-settings` and contains:

- Application environment, public URLs, log level, and locale defaults.
- PostgreSQL DSN and pool settings.
- Redis broker, result, cache, and rate-limit URLs.
- S3 endpoint, region, bucket, access key, secret key, and signed URL lifetime.
- Lark application ID, secret, verification token, encrypt key, and API base URL.
- Session signing key, magic-link lifetime, and cookie policy.
- LiteLLM extraction, vision, chat, embedding, and fallback model names.
- Per-operation timeout, retry, and budget limits.

Startup validation rejects default secrets in non-development environments.

## 4. Domain Contracts

### 4.1 Identifiers

All internal entities use UUIDv7 values. External tokens use at least 256 bits of cryptographic randomness and are stored as hashes when possible.

### 4.2 Conversation Command

```python
class ConversationCommand(BaseModel):
    command_id: UUID
    idempotency_key: str
    account_id: UUID | None
    household_id: UUID | None
    channel: Literal["web", "lark"]
    channel_user_id: str
    conversation_id: str
    locale: Literal["zh-CN", "en-US"]
    text: str
    attachments: tuple[AttachmentRef, ...] = ()
    received_at: datetime
    reply_context: ReplyContext | None = None
```

### 4.3 Agent Run

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

class PlannedAction(BaseModel):
    action_id: UUID
    tool_name: str
    arguments: dict[str, JsonValue]
    mutation: bool
    requires_confirmation: bool = False

class AgentProgress(BaseModel):
    run_id: UUID
    stage: AgentStage
    message_key: str
    completed_actions: tuple[str, ...] = ()
```

The orchestrator persists a run and step before publishing progress. A mutation result must include `persisted=True` before the completion renderer can use success language.

### 4.4 AI Provider

```python
class AIProvider(Protocol):
    async def parse_structured[
        T: BaseModel
    ](self, *, operation: str, messages: Sequence[AIMessage], schema: type[T]) -> T: ...

    async def embed(self, *, operation: str, texts: Sequence[str]) -> list[list[float]]: ...
```

The LiteLLM adapter maps operation names to configured models, sets timeouts and budgets, validates outputs, attempts one repair, and raises typed provider errors.

### 4.5 Input Adapter

```python
class InputAdapter(Protocol):
    def supports(self, raw_input: RawInputSnapshot) -> bool: ...
    async def extract(self, raw_input: RawInputSnapshot) -> ExtractedContent: ...
```

The adapter registry selects exactly one adapter or raises `UnsupportedInputError`. Raw persistence happens before registry selection.

### 4.6 Recommendation

```python
class RecommendationQuery(BaseModel):
    household_id: UUID
    available_ingredients: tuple[str, ...] = ()
    meal_type: MealType | None = None
    target_age_months: int | None = None
    max_total_time_minutes: int | None = None
    scenario_tags: tuple[str, ...] = ()
    excluded_recipe_ids: tuple[UUID, ...] = ()

class RecommendationResult(BaseModel):
    recipe_id: UUID | None
    generated_candidate: RecipeCandidate | None
    score: Decimal
    reason_codes: tuple[str, ...]
    explanation: str
    missing_ingredients: tuple[str, ...]
```

`RecommendationService.recommend(query)` returns a tuple of length three or raises `InsufficientRecommendationCapacityError`. The service retrieves household recipes first, then creates the exact number of labeled generated candidates needed to reach three.

## 5. Persistence

### 5.1 Database Rules

- Timestamps are timezone-aware UTC.
- Household-owned tables include `household_id` directly or through a non-null constrained parent.
- Soft deletion is limited to user-facing content that must remain auditable; security tokens are hard deleted or expired.
- Optimistic version columns protect mutable plans and shopping lists.
- JSONB stores AI confidence maps, structured deltas, immutable snapshots, and provider metadata that has passed redaction.
- pgvector stores embeddings with the model name and source-text hash.

### 5.2 Transactional Outbox

Mutating application services write domain changes and an `outbox_events` row in one transaction. A worker publishes pending events and marks them delivered. Consumers use the event ID as an idempotency key.

### 5.3 Object Storage

Objects use generated keys: `households/{household_id}/{media_id}/{variant}`. Buckets are private. Upload completion validates size and content type. Signed URLs expire after a configured short lifetime.

## 6. HTTP API

All authenticated application endpoints use `/api/v1`.

### 6.1 Health and Operations

- `GET /health/live`
- `GET /health/ready`
- `GET /metrics` on an internal listener or protected route

### 6.2 Identity

- `POST /api/v1/auth/magic-links`
- `GET /api/v1/auth/magic-links/consume`
- `POST /api/v1/auth/logout`
- `POST /api/v1/lark/link-codes`
- `GET /api/v1/account`
- `PATCH /api/v1/account/locale`

### 6.3 Conversation and Imports

- `POST /api/v1/chat/messages`
- `GET /api/v1/chat/runs/{run_id}`
- `GET /api/v1/chat/runs/{run_id}/events` using server-sent events
- `POST /api/v1/uploads`
- `POST /api/v1/imports`
- `GET /api/v1/imports`
- `GET /api/v1/imports/{import_id}`

### 6.4 Domain Resources

- `GET /api/v1/recipes`
- `GET /api/v1/recipes/{recipe_id}`
- `PATCH /api/v1/recipes/{recipe_id}`
- `POST /api/v1/recommendations`
- `POST /api/v1/meal-plans`
- `GET /api/v1/meal-plans/{plan_id}`
- `POST /api/v1/meal-plans/{plan_id}/items/{item_id}/replace`
- `GET /api/v1/shopping-lists/{list_id}`
- `PATCH /api/v1/shopping-lists/{list_id}/items/{item_id}`
- `POST /api/v1/feedback`
- `POST /api/v1/ratings`
- `POST /api/v1/shares`
- `GET /api/v1/shares`
- `DELETE /api/v1/shares/{share_id}`
- `GET /s/{token}`

### 6.5 Lark Callbacks

- `POST /webhooks/lark/events`
- `POST /webhooks/lark/cards`

The event route validates, normalizes, persists the event ID, queues processing, and returns HTTP 200 within three seconds. Duplicate event IDs return HTTP 200 without republishing the command.

## 7. Job Queues

Celery uses named queues:

- `imports.links`
- `imports.images`
- `imports.excel`
- `ai.embeddings`
- `agent.actions`
- `notifications.lark`
- `outbox.publish`
- `maintenance`

Tasks accept one Pydantic job-envelope version and entity IDs, not entire ORM objects. Retries use exponential backoff with jitter and explicit maximum attempts. Permanent failures move to a persisted failed state and trigger a localized user notification when applicable.

## 8. Localization

Backend copy uses message keys and locale catalogs. The backend never concatenates localized fragments. Lark cards are rendered from locale-specific templates.

The Web uses route-independent account locale state and ICU message catalogs. The selector displays `中文` and `English`; after selection, all other page copy uses the active locale. Locale catalog parity is enforced in CI.

## 9. Security

- Magic-link tokens are single-use, short-lived, and stored as hashes.
- Session cookies are Secure, HTTP-only, SameSite=Lax, and rotated after authentication.
- State-changing Web requests require CSRF protection.
- Lark verification token, signature, and encrypted payload handling follow the v2 event protocol.
- Rate limits apply by IP, account, Lark user, and operation cost.
- File uploads are private, size-limited, content-sniffed, and routed through a malware-scanning hook.
- ORM access uses household-scoped repository methods.
- Share projections use explicit allowlists.
- Logs use structured redaction before serialization.

## 10. Observability

Every request and job carries `correlation_id`, `command_id`, and `agent_run_id` when applicable. Metrics cover:

- Request latency and errors by route.
- Lark callback acknowledgement latency and duplicate counts.
- Job queue depth, duration, retries, and failures.
- Model latency, token usage, cost, fallback, repair, and validation failures.
- Import status and confidence.
- Recommendation source mix and selection.
- Database pool and transaction errors.

Traces connect Lark events or Web messages to agent steps, domain tools, jobs, model calls, and persistence.

## 11. Testing

- Unit tests have no network or service dependencies.
- Contract tests validate exact external and internal payload schemas.
- Integration tests start PostgreSQL/pgvector, Redis, and MinIO.
- End-to-end tests start API, worker, and Web containers and use schema-accurate Lark/model fakes.
- Security tests attempt cross-household access, token replay, invalid signatures, prohibited uploads, and private-field leakage.
- Live Lark and OpenAI smoke tests are opt-in and never required for deterministic CI.

## 12. Build and Deployment

Docker images run as non-root users, expose health checks, and contain no development secrets. The API and worker use the same immutable Python application image with different commands. Web uses the Next.js standalone output.

Production deploys external PostgreSQL, Redis, and S3-compatible storage. API and worker replicas scale independently. Database migrations run as a separate release job before new application replicas become ready.

## 13. Official Reference Baseline

- [FastAPI](https://fastapi.tiangolo.com/)
- [LiteLLM](https://docs.litellm.ai/)
- [Next.js App Router](https://nextjs.org/docs/app)
- [Next.js 16](https://nextjs.org/blog/next-16)
- [Lark bot development](https://open.larksuite.com/document/home/develop-a-bot-in-5-minutes/create-an-app)
- [Lark event subscriptions](https://open.larksuite.com/document/ukTMukTMukTM/uUTNz4SN1MjL1UzM)
