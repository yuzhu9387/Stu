# Family Recipe Agent Design

**Status:** Approved design for implementation planning

**Date:** 2026-07-15

**Source:** `存菜谱AI_Agent_PRD_竞品调研版.docx`

**Repository:** `yuzhu9387/Stu`

## 1. Product Definition

The Family Recipe Agent is a chat-first household recipe memory and planning product. It receives recipes from Lark or the Web, preserves every original input, extracts structured recipe data, and turns the household's own recipe collection into recommendations, weekly meal plans, shopping lists, feedback-aware household versions, and privacy-safe shares.

The product targets parents and household cooking decision-makers who collect recipes from Xiaohongshu, screenshots, text, and spreadsheets. Its differentiation is low-friction chat input, child-age context, household feedback memory, and action-oriented conversations.

## 2. Goals

The full MVP must:

1. Accept Xiaohongshu links, generic links, images, text, and Excel files from Lark and the Web.
2. Preserve raw inputs before parsing so external or AI failures never lose user content.
3. Extract validated recipe cards with field-level confidence and source provenance.
4. Recommend exactly three choices for a recommendation request.
5. Create weekly meal plans and aggregated shopping lists.
6. Apply natural-language feedback through append-only events and household recipe versions.
7. Record child and adult ratings without exposing private data in shares.
8. Share recipes and collections through revocable, privacy-filtered snapshots.
9. Support Simplified Chinese and English while showing only one language at a time.
10. Operate through an action-oriented agent loop instead of a reply-only chatbot.

## 3. Explicit Non-Goals

The MVP does not include a social feed, automated grocery purchasing, medical advice, nutrition diagnosis, video transcription, voice-first cooking mode, refrigerator inventory tracking, or native mobile applications. Receiving-account import from a shared collection remains an extension point and is not required for the first full-MVP release.

## 4. Confirmed Product Decisions

- Channels: Lark international and a responsive Web UI.
- Account model: one authenticated individual account owns one household.
- Identity: a Lark identity can be linked to the same Web account.
- Localization: Simplified Chinese and English are supported; each screen, bot card, and message uses exactly one active language.
- AI runtime: OpenAI models accessed through a LiteLLM-compatible provider layer.
- Deployment: portable containers for Docker Compose locally and managed container or Kubernetes platforms in production.
- Architecture: a modular orchestration hub with independently scalable background worker spokes.
- Recommendation count: exactly three recommendations by default.
- Interaction model: Understand, Plan, Act, Check, and Continue.

## 5. System Architecture

### 5.1 Repository Shape

The product is a monorepo containing:

- A Python 3.12 FastAPI backend.
- Celery workers grouped by workload.
- A Next.js and TypeScript Web application.
- Versioned Python and JSON contracts shared by the API and workers.
- Docker Compose and production-ready container definitions.
- Unit, contract, integration, end-to-end, and security tests.

### 5.2 Hub Responsibilities

The orchestration hub owns:

- Authentication and household authorization.
- Lark-to-Web identity resolution.
- Conversation state and locale.
- Command normalization and intent routing.
- Agent-loop state transitions.
- Transaction boundaries and idempotency.
- Domain-spoke coordination.
- Response composition for Lark and Web transports.

The hub must not contain input-specific parsing, recommendation scoring, meal-plan algorithms, sharing projections, or vendor-specific AI calls.

### 5.3 Domain Spokes

Each spoke exposes an application-service interface and owns its domain rules:

- **Identity:** accounts, households, sessions, Lark linking, locale preferences.
- **Imports:** raw inputs, media, adapters, extraction, normalization, deduplication.
- **Recipes:** recipes, ingredients, steps, sources, tags, versions, search documents.
- **Recommendations:** retrieval, filtering, scoring, diversity, explanations.
- **Planning:** weekly meal plans, replacements, shopping-list aggregation.
- **Feedback:** cook sessions, ratings, feedback events, structured deltas.
- **Sharing:** snapshots, privacy projections, opaque tokens, expiry, revocation.
- **Conversation:** agent-loop state, progress events, transport-neutral results.

Spokes live in one deployable API codebase initially. Boundaries use explicit interfaces and serializable job contracts so a spoke can later become a separate service without changing channel adapters.

### 5.4 Infrastructure

- PostgreSQL is the system of record.
- pgvector stores recipe and search embeddings in PostgreSQL.
- Redis provides the Celery broker, caching, rate limiting, and short-lived coordination.
- S3-compatible object storage holds original uploads and derived media.
- LiteLLM provides model routing, fallback, budgets, and provider observability.
- OpenTelemetry, Prometheus-compatible metrics, and structured logs provide operational visibility.

## 6. Core Contracts

### 6.1 Conversation Command

Every Lark event or Web message becomes a `ConversationCommand` with:

- `command_id`
- `idempotency_key`
- `account_id`
- `household_id`
- `channel`
- `channel_user_id`
- `conversation_id`
- `locale`
- `text`
- `attachments`
- `received_at`
- `reply_context`

The normalized command prevents domain services from depending on Lark or browser payload shapes.

### 6.2 Agent Loop

Each actionable conversation uses these states:

1. **UNDERSTANDING:** Resolve intent, referenced entities, constraints, and missing critical context.
2. **PLANNING:** Produce a concise user-visible action plan and an internal typed execution plan.
3. **ACTING:** Invoke domain tools and publish progress events.
4. **CHECKING:** Validate tool results, policy compliance, completeness, and persistence outcomes.
5. **CONTINUING:** Present the result conversationally and propose the most relevant next action.
6. **WAITING_FOR_USER:** Pause only when a critical ambiguity or consequential confirmation remains.
7. **FAILED:** Preserve completed work, explain the recoverable failure, and offer a concrete retry or fallback.

User-visible progress contains concise status summaries, action plans, and action receipts. It never exposes private chain-of-thought, hidden model reasoning, secrets, provider payloads, or raw policy text.

The agent must perform domain actions when the user requests them. It must not claim an import, plan update, recipe update, or share creation unless the corresponding tool result confirms persistence.

### 6.3 AI Provider Boundary

Domain services depend on an internal `AIProvider` interface. The LiteLLM implementation supports:

- Structured text generation.
- Vision-capable structured extraction.
- Embeddings.
- Per-operation model configuration.
- Bounded retries and timeouts.
- Fallback models.
- Token and cost budgets.
- Correlation metadata.

Prompts and response schemas are versioned. All structured results pass Pydantic validation before use.

## 7. Product Flows

### 7.1 Recipe Import

1. Receive a Lark or Web command.
2. Authenticate and authorize the household.
3. Persist `RawInput` and media metadata before parsing.
4. Detect the input adapter.
5. Acknowledge receipt immediately when processing is asynchronous.
6. Extract text and media content.
7. Generate one or more validated `RecipeCandidate` objects.
8. Normalize ingredients, meal types, age suitability, and tags.
9. Detect exact-source and semantic duplicates.
10. Persist recipes, sources, steps, confidence values, and original media.
11. Generate embeddings asynchronously.
12. Deliver a localized recipe card with uncertain fields and correction actions.

Supported adapters are Lark attachment, Web upload, text, image, Excel, Xiaohongshu URL, and generic URL. An unreadable link remains saved and prompts the user to provide screenshots or copied text.

### 7.2 Recommendation

1. Parse available ingredients, meal type, target age, time limit, scenario tags, and exclusions.
2. Retrieve household recipes by structured filters and semantic similarity.
3. Apply hard safety and household constraints.
4. Rank candidates using ingredient match, meal fit, age fit, ratings, time fit, scenario tags, diversity, recent repetition, difficulty, and negative feedback.
5. Return exactly three ordered choices with reasons, available ingredients, missing ingredients, time, age fit, and relevant household feedback.

Household recipes always rank before generated suggestions. When fewer than three eligible household recipes exist, the agent fills the remaining positions with clearly labeled AI-generated suggestions. Generated suggestions are not persisted until the user saves or schedules them.

The model explains the deterministic ranking but cannot silently reorder the scored results.

### 7.3 Weekly Meal Planning

The planning spoke reuses recommendation retrieval and scoring, applies date and meal constraints, prevents unnecessary repetition, balances quick and higher-effort meals, and produces a meal-plan version. Replacements update one item without regenerating accepted items.

Shopping-list aggregation normalizes ingredient identities, combines compatible quantities, preserves unmergeable raw units, records source recipe IDs, and separates ingredients already marked as available.

### 7.4 Feedback and Household Versions

Natural-language feedback first creates an immutable `FeedbackEvent`. A typed parser produces a structured delta for rating, preference, tag, time, quantity, step, or suppression changes. Valid changes create a new household `RecipeVersion`; the original source remains intact. Ambiguous recipe references return at most three candidates for selection.

### 7.5 Sharing

A share operation resolves recipes or collections, creates an immutable localized snapshot, applies the privacy projection, and returns an opaque share token. The default projection excludes real family-member names, private photos, comments, exact child ratings, email addresses, phone numbers, and internal identifiers. Owners can revoke a token or set an expiry.

## 8. Data Model

The core relational model includes:

- `accounts`, `households`, `lark_identities`, `web_sessions`, `magic_links`
- `family_members`
- `raw_inputs`, `media_assets`, `import_jobs`
- `recipes`, `recipe_sources`, `recipe_ingredients`, `recipe_steps`, `step_media`
- `ingredients`, `tags`, `recipe_tags`, `recipe_embeddings`
- `recipe_versions`
- `cook_sessions`, `ratings`, `feedback_events`
- `meal_plans`, `meal_plan_items`
- `shopping_lists`, `shopping_list_items`
- `collections`, `collection_items`
- `share_snapshots`, `share_tokens`
- `conversations`, `conversation_messages`, `agent_runs`, `agent_run_steps`
- `outbox_events`, `job_executions`

Every household-owned row carries `household_id` directly or through a constrained parent. Database indexes and application authorization always include the household scope.

## 9. Interface Design

### 9.1 Web UI

The responsive Web application provides:

- Chat as the default route.
- Recipe library and recipe detail/version history.
- Weekly plan and item replacement.
- Shopping list.
- Import history and review queue.
- Share management.
- Account, language, and Lark-linking settings.

A language control in the upper-right corner switches the entire interface between Simplified Chinese and English. The preference persists to the account and synchronizes with future Lark responses. A screen never mixes languages except for the language selector's native labels.

### 9.2 Lark Bot

The Lark bot targets `open.larksuite.com`. It supports challenge verification, encrypted event callbacks, signature verification, event deduplication, attachments, interactive cards, and asynchronous follow-up messages.

For actionable requests, the bot visibly progresses through localized equivalents of Understand, Plan, Act, Check, and Continue. It updates or follows up on a progress card for longer work. The final message is conversational, states what changed, explains the result, and proposes a relevant next action.

Lark cards use only the account's selected language. The initial locale follows the Lark user locale and can be changed from the Web or through a bot command.

## 10. Identity and Security

- Web login uses email magic links and secure, HTTP-only sessions.
- Lark linking uses a signed, single-use, short-lived code initiated from the authenticated Web account.
- Lark webhook signatures and encrypted payloads are verified before processing.
- All commands and queries enforce household authorization.
- Uploads enforce content-type allowlists, size limits, malware scanning hooks, generated object keys, and private buckets.
- Object downloads use short-lived signed URLs.
- Shared snapshots use opaque tokens, optional expiry, and revocation.
- Secrets are supplied through environment variables or an external secret manager.
- Logs redact tokens, signed URLs, message bodies, personal data, and provider payloads.
- Child age, allergy, and dietary outputs display uncertainty and never claim medical authority.

## 11. Reliability

- Incoming events, commands, uploads, and jobs use idempotency keys.
- Lark callbacks acknowledge quickly; long-running work completes asynchronously.
- Failures are classified as validation, authentication, authorization, external platform, model provider, storage, transient infrastructure, or internal.
- LiteLLM calls use timeouts, bounded exponential backoff, fallback models, and one structured-output repair attempt.
- Invalid model output routes the import to `needs_review` after the repair attempt.
- Celery jobs have explicit retry policies, persisted job state, and dead-letter handling.
- Database writes use short transactions; long AI and storage operations occur outside transactions.
- The transactional outbox pattern publishes durable post-commit events.
- Compensating cleanup removes abandoned object-storage uploads.
- Correlation IDs connect channel events, agent runs, jobs, model calls, and database changes.

## 12. Testing Strategy

Implementation follows test-driven development: each behavior begins with a failing test, the failure is verified, minimal code is written, the test is made green, and refactoring occurs only while tests remain green.

### 12.1 Test Layers

- **Unit:** schemas, normalizers, ranking, three-result selection, privacy projections, plan constraints, shopping aggregation, feedback deltas, versions, localization.
- **Contract:** Lark payloads, input adapters, LiteLLM structured results, Celery job envelopes, API schemas.
- **Integration:** real PostgreSQL/pgvector, Redis, and S3-compatible storage through Docker Compose.
- **End-to-end:** Web signup, Lark linking, every import type, correction, three recommendations, weekly planning, shopping lists, feedback, ratings, and shares.
- **Failure path:** duplicate events, unreadable links, malformed spreadsheets, invalid AI output, timeouts, retries, unauthorized access, and revoked shares.
- **Security:** webhook verification, upload restrictions, session protection, tenant isolation, redaction, and privacy-safe snapshots.

External Lark and model calls use schema-accurate recorded fakes in deterministic tests. A separate opt-in smoke suite verifies live credentials without becoming a CI requirement.

### 12.2 CI Gates

CI must pass formatting, linting, static typing, unit tests, contract tests, integration tests, migration checks, Web build, container builds, security checks, and end-to-end smoke tests. Each P0 and P1 PRD requirement maps to one or more automated acceptance tests.

## 13. Success Criteria

The MVP is ready for beta when:

- At least 80% of representative supported inputs produce a usable recipe card.
- A new user can save a first recipe in under 60 seconds.
- Recommendation requests return exactly three choices with explanations.
- Every persisted action shown as successful has a confirmed tool result.
- Raw inputs survive parsing and provider failures.
- Household isolation and share privacy tests pass.
- Lark and Web complete the same core workflows in either supported language.
- The complete CI gate passes from a clean checkout.

## 14. Implementation Planning Boundary

Implementation planning will decompose the full MVP into independently testable vertical phases:

1. Platform foundation, identity, localization, and observability.
2. Agent loop and channel transports.
3. Import pipeline and recipe library.
4. Recommendation engine with exactly three results.
5. Weekly planning and shopping lists.
6. Feedback, ratings, and household versions.
7. Privacy-safe sharing.
8. Hardening, full end-to-end validation, and beta readiness.

Each phase must leave the repository runnable and preserve the architectural contracts in this document.
