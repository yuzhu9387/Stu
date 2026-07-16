# Task 7 Implementation Report

## Scope

Implemented Lark runtime composition on top of the shared account-aware `ConversationHub`,
Task 2 identity/linking services, Task 4 final response contract, and Task 6 durable suggested
action service.

## Behavior delivered

- Replaced the static-account Lark normalizer with verified, transport-only message/action DTOs.
- Resolves each inbound `open_id` to the exact account and household before creating a command.
- Uses the same `ConversationCommand` and `ConversationHub.submit_message()` contract as Web.
- Uses a private deterministic Lark conversation ID derived from account plus chat, preventing
  two family members in the same group chat from sharing private conversation history.
- Persists the Lark reply target with the run so completion delivery is restart-safe.
- Reserves every message and card callback before identity resolution or business side effects,
  using a privacy-safe content fingerprint, processing lease, and accepted outcome. Replays are
  no-ops, stale work is recoverable, and reuse of an event ID with different content is rejected.
- Queues unbound-user guidance through durable event and delivery receipts plus the transactional
  outbox, and performs no outbound Lark call on the webhook request path.
- Supports one-time account binding through `link CODE` / `绑定 CODE`; linking never creates or
  merges accounts, and the code is never submitted as a conversation message.
- Adds callback normalization that accepts real Lark envelope metadata but strictly allows only
  a signed `token` inside the action value (no client-provided account, household, type, or args).
- Resolves card clicks from the clicking `open_id` and calls the same Task 6 `consume()` service.
- Acknowledges valid, expired, invalid, unlinked, cross-account, replayed, and substituted card
  callbacks with Lark-compatible HTTP 200 responses without exposing tokens or validation details.
- Commits a Lark completion outbox event and unique delivery receipt in the same transaction as
  run completion/failure.
- Enqueues only outbox UUIDs to the Lark delivery task; message text, action tokens, and chat IDs
  are not placed in Celery task arguments.
- Adds fenced agent-run leases, attempt counters, stale-run recovery, and attempt-aware completion
  so a replaced worker cannot overwrite a newer attempt.
- Adds fenced delivery claims, stale-send recovery, permanent delivered receipts, late
  acknowledgement, worker-loss rejection, bounded exponential autoretry, and a stable outbox UUID
  passed to Lark for provider-side idempotency. No database session remains open during HTTP I/O.
- Adds a cached, concurrency-safe tenant access-token provider with safe early refresh and bounded
  credential-free errors. A provider auth rejection invalidates only that token generation and
  retries once with a refreshed token.
- Persists only suggested-action IDs, types, and expiries in completed run responses. Delivery
  reconstructs the exact deterministic encrypted token from the authoritative action record,
  verifies its stored hash, and keeps the raw token in memory only.
- Renders one final locale-consistent card with safe Thinking / Plan / Act / Answer summaries and
  zero to three signed action buttons. Chinese uses 思考 / 计划 / 执行 / 回答 throughout.
- Adds localized linking, link-success, and asynchronous failure cards.
- Keeps provider response messages, credentials, and tenant tokens out of raised client errors.

## Test-driven development evidence

The feature tests were written and observed failing before the corresponding implementation:

- missing identity-aware Lark inbound service and normalized event DTOs;
- missing durable linking/completion outbox intents;
- missing tenant-token provider and cache;
- missing final card/action rendering and delivery client methods;
- missing UUID-only Lark delivery task;
- missing link-command behavior;
- callback event-ID reuse with a different token;
- real Lark envelope metadata compatibility;
- missing worker retry/late-ack configuration;
- event substitution and PostgreSQL event-claim races;
- stale agent-run and delivery leases;
- raw consent-token persistence and deterministic delivery reconstruction;
- rejected tenant-token refresh; and
- documented callback route to the real Task 6 action queue.

## Verification

- Focused Lark/worker tests: all pass.
- Full local backend suite: `211 passed, 11 skipped` (skips require external database environment
  when the suite is run without its variables).
- PostgreSQL-backed event, run, delivery, conversation, and suggested-action concurrency/security
  tests: `23 passed` against the local test PostgreSQL service.
- PostgreSQL migration verification: `9 passed` (21 existing Alembic deprecation warnings).
- Ruff: all source and test checks pass.
- mypy strict: success across 100 source files.
- `git diff --check`: clean.

## Integration notes for Task 8

- The FastAPI composition root must instantiate `LarkInboundService`, `LarkWebhookHandler`,
  `LarkTenantTokenProvider`, `LarkClient`, and `LarkDeliveryService`.
- Assign the webhook handler to `app.state.lark_handler`.
- Configure the worker with `configure_lark_delivery(lambda: delivery_service)`.
- Configure `LarkDeliveryService` with the same `SuggestedActionService`/signing key used for
  issuing actions. The run response may contain issued actions at the completion boundary, but
  `AgentRunRepository` strips raw tokens before persistence; delivery reconstructs and validates
  them from the durable suggested-action records.
- Route the existing outbox worker through `RoutingPublisher`, which now handles all supported
  `lark.*` topics.

## Scope hygiene

- Migration `0011_lark_runtime_recovery` adds agent-run attempts/leases, event fingerprints and
  processing leases/outcomes, and durable Lark delivery receipts with attempts and send leases.
- `web/next-env.d.ts` was not edited or staged.
