# Unified ReAct Runtime Design

**Date:** 2026-07-15

**Status:** Approved

## 1. Objective

Turn the current Web prototype and tested backend modules into one working product runtime. The Web assistant and Lark bot must submit messages to the same application service, use the same account and family data, run the same bounded ReAct agent, and return the same structured answer. Static Web data must be replaced by PostgreSQL-backed APIs.

The agent may inspect data and propose changes, but it must not mutate business data from a natural-language request. A user must click a Web button or Lark card action before a proposed mutation is executed.

## 2. Product Decisions

- The default model is `openai/gpt-5.1` with `reasoning_effort=high` through LiteLLM.
- `openai/gpt-5-mini` is the bounded fallback model.
- Web and Lark return one complete response after the run finishes; they do not stream intermediate progress.
- The response contains concise `Thinking`, `Plan`, `Act`, and `Answer` sections without exposing private chain-of-thought.
- A single account represents a single user.
- A family contains multiple accounts. Family membership never merges account-owned data.
- Web and Lark identities are linked through a one-time code generated from an authenticated Web session.
- Users join a family with a one-time invitation code.
- Shared family data remains attributed to its owner.

## 3. Architecture

The application retains the hub-and-spoke architecture and adds a durable runtime composition root.

```text
Web API -------+
               |
Lark Webhook --+--> ConversationHub --> PostgreSQL Run --> Redis/Celery
               ^                                           |
Lark Actions --+                                           v
                                                    Bounded ReAct Worker
                                                            |
                                               Read-only tools + LiteLLM
                                                            |
                                               Final answer + suggestions
```

`ConversationHub` is the only application-service interface used to submit a user message. Web and Lark are transport adapters; they do not call each other or duplicate agent behavior. The hub authenticates the transport identity, persists the command and run, applies idempotency, and queues execution.

The worker loads the persisted command, resolves the account and family scope, executes the ReAct loop, stores the result, and invokes the correct completion adapter. Web reads the completed run through the API. Lark receives a message or interactive card through the Lark client.

## 4. Identity and Family Model

### 4.1 Relationships

- One `Account` represents one user.
- One `Family` has multiple `FamilyMembership` records.
- An account may have one active family in the MVP.
- Membership roles are `owner` and `member`.
- One Lark Open ID maps to one account.
- One Web session maps to one account and its active family.

### 4.2 Family invitations

An authenticated family owner generates a cryptographically random invitation code. Only its hash is stored. The code expires after ten minutes, may be consumed once, and cannot be used by an account that already has an active family.

### 4.3 Lark linking

An authenticated Web user generates a cryptographically random Lark link code. Only its hash is stored. The code expires after ten minutes and may be consumed once. The user sends the code to the Lark bot; the bot binds the sender Open ID to that existing account. Linking never creates or merges another account.

### 4.4 Ownership and visibility

Business records that can be shared carry `owner_account_id`, `family_id`, and `visibility`. Existing data is migrated without deletion; the current account becomes the owner of its existing family and records.

Default family-visible records:

- recipes;
- dietary preferences;
- weekly plans; and
- shopping lists.

Default private records:

- conversations and messages;
- agent runs and steps;
- raw uploads and import source files; and
- personal feedback.

Recommendations belong to the requesting account. They may use family-visible recipes and preferences, but the response, conversation memory, and later feedback remain owned by the requesting account. Every read is family-scoped and every mutation records both the resource owner and the actual actor. Cross-family access is always rejected.

## 5. Unified Conversation Contract

### 5.1 Web submission

`POST /api/v1/agent/runs` accepts a conversation ID when continuing an existing private conversation, the message, locale, and an idempotency key. It returns HTTP 202 and a run ID after persistence and queue publication.

`GET /api/v1/agent/runs/{run_id}` returns only a run owned by the authenticated account. A completed run includes the final structured response and up to three suggested actions.

### 5.2 Lark submission

`POST /webhooks/lark/events` verifies and decrypts the request, claims the Lark event ID, resolves the sender Open ID, and calls `ConversationHub.submit_message()`. It acknowledges the webhook within three seconds. An unlinked sender receives linking instructions. A linked sender receives the completed result asynchronously after the worker finishes.

### 5.3 Final response

The transport-neutral final response contains:

- a short thinking summary describing the interpretation of the request;
- a short plan describing the selected approach;
- an act summary listing tools used and facts checked;
- the natural-language answer in the user's locale; and
- zero to three typed `SuggestedAction` values.

The response never contains private model reasoning or hidden prompts.

## 6. Bounded ReAct Runtime

Each run executes no more than five ReAct iterations. On each iteration, the model either requests one allowed read-only tool or finishes with a structured response. The server validates every tool name and argument before execution and returns a bounded observation to the model.

Initial read-only tools are:

- search the requesting account's recipes;
- search family-visible recipes while preserving owner attribution;
- read personal and family-visible dietary preferences;
- read existing plans and shopping lists;
- calculate exactly three recommendations from eligible recipes;
- preview a recipe import; and
- preview a weekly-plan change.

The model has no mutation tools. A requested save, plan creation, replacement, or share is represented by a typed `SuggestedAction`.

LiteLLM calls use `openai/gpt-5.1`, `reasoning_effort=high`, a finite timeout, bounded exponential retry, usage capture, and schema-constrained output. The fallback is `openai/gpt-5-mini`. A malformed structured response receives one repair attempt. If five iterations finish without a terminal answer, the worker composes a conservative response from the verified observations already available.

## 7. Suggested Actions and Explicit Consent

A suggested action contains an opaque, signed, single-use token. The token binds:

- account ID;
- family ID;
- source run ID;
- allowed action type;
- validated action arguments; and
- expiration time.

Web renders suggested actions as buttons. Lark renders them as interactive-card buttons. A click is explicit consent to execute that exact action. The action endpoint verifies the signature, current session or Lark identity, account, family, expiration, and unused state before calling an existing domain write service.

Expired, replayed, modified, or mismatched actions are rejected. The final transport response reports a write as successful only after persistence is verified.

## 8. Live Web Data

All static feature data is replaced with authenticated API queries:

- Chat uses the unified run endpoints and private conversation history.
- Recipes show account-owned and family-visible recipes grouped or labeled by owner.
- Plans show family-visible plans without merging plans from different owners.
- Shopping lists are attached to a specific plan and owner.
- Imports show only the requesting account's import records and source metadata.
- Shares show shares created by the requesting account.
- Settings show personal preferences, family membership, invitation controls, and Lark binding status.

The entire page remains in one selected locale. Locale selection persists and is supplied to the conversation hub.

Local development may expose a generated magic-link token and one-time binding codes in a developer-only response or panel. Production never returns those secrets to an unauthenticated client.

## 9. Runtime Composition and Configuration

The FastAPI composition root creates and assigns all concrete services required by the routers and worker, including repositories, identity/session middleware, recommendation and planning services, the conversation hub, LiteLLM client, Redis/Celery publisher, Lark webhook handler, and Lark delivery client.

Validated settings include:

- LiteLLM primary and fallback models;
- reasoning effort;
- model timeout and retry limits;
- OpenAI API key passthrough;
- Lark App ID and App Secret;
- Lark Verification Token and optional Encrypt Key;
- Redis and PostgreSQL URLs; and
- signed-action lifetime and signing key.

Secrets are never logged, returned by operational endpoints, or committed.

## 10. Failure and Recovery

- A queued run is persisted before publication so a transient queue failure does not lose the message.
- Event and message idempotency prevent Lark retries and Web resubmission from creating duplicate runs.
- A worker claims a run atomically and records `queued`, `running`, `completed`, or `failed`.
- Model and tool failures are classified and stored without private prompt or secret data.
- Web displays a localized retry action for a failed run.
- Lark sends a localized failure card after asynchronous processing fails.
- An unlinked Lark sender receives only safe binding instructions.
- Database or queue outages do not produce a false success response.
- Suggested-action execution records the actual actor and cannot be replayed.

## 11. Testing Strategy

Implementation follows red-green-refactor test-driven development.

Unit tests cover the five-iteration bound, read-only tool registry, response schema, suggested actions, visibility rules, and ownership enforcement.

Contract tests cover LiteLLM tool calls and structured responses, Lark event envelopes, encryption, event acknowledgements, outbound cards, and card-action callbacks.

Integration tests use PostgreSQL and Redis to cover account/family membership, invitations, Lark linking, queued run lifecycle, idempotency, action-token consumption, and recovery.

API end-to-end tests cover login, family creation, invitation acceptance, Lark linking, message submission, run completion, and explicit action execution.

Web end-to-end tests use live APIs for Chat, Recipes, Plans, Shopping, Imports, Shares, Settings, and locale switching.

Security tests cover cross-family reads, ownership spoofing, forged or replayed action tokens, expired invitations, duplicate webhook events, and private conversation access.

A separately invoked live smoke test uses environment-provided OpenAI and Lark credentials without recording secrets or provider payloads in fixtures.

## 12. Completion Criteria

The implementation is complete only when:

1. Web assistant responses come from the configured reasoning model through LiteLLM.
2. Lark bot messages produce the same response structure through the same `ConversationHub`.
3. Web and Lark use the same bounded ReAct runtime and read-only tool registry.
4. All Web feature pages display PostgreSQL-backed data instead of static fixtures.
5. Account-owned data remains separate and family-shared data displays owner attribution.
6. Natural-language requests cannot mutate business data.
7. Web and Lark clicks can execute a valid suggested action exactly once.
8. Restarts and retried events cannot create duplicate runs or writes.
9. Python, TypeScript, migration, API, browser, security, and live smoke checks pass.
10. A local step-by-step test runbook documents the complete flow.
