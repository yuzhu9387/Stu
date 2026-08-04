# Durable Suggested Actions Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make explicit-click mutations recoverable and exactly once without persisting bearer tokens or placing consent tokens in URLs.

**Architecture:** The click endpoint validates the signed token and transactionally transitions the action from `pending` to `queued` while adding an action-ID-only outbox event. Workers lease queued actions, retry expired leases, and dispatch fixed handlers. Each domain mutation stores a unique action receipt in the same transaction as its write; retries return the receipt. Share tokens are deterministically derived from a secret and action ID, while only their hash and token-free audit result are stored.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy asyncio, Alembic, PostgreSQL, Celery, pytest.

## Global Constraints

- Never persist or log raw consent or share bearer tokens.
- Consent claims and database rows must match action ID, account, household, run, type, and normalized expiry exactly.
- Only the four fixed action types and injected domain handlers may execute.
- Do not modify `web/next-env.d.ts`.

---

### Task 1: Closed Inputs, Safe API, and Exact Expiry

**Files:**
- Modify: `src/recipe_agent/domain/recipes/contracts.py`
- Modify: `src/recipe_agent/domain/planning/contracts.py`
- Modify: `src/recipe_agent/domain/conversation/actions.py`
- Modify: `src/recipe_agent/api/v1/actions.py`
- Test: `tests/security/test_suggested_action_security.py`
- Test: `tests/e2e/test_suggested_actions.py`

**Interfaces:**
- Produces: `POST /api/v1/agent/actions/execute`, exact expiry matching, recursively closed nested action values.

- [ ] Write failing tests for body-only consent, no token path, row-expiry tamper, and nested extras.
- [ ] Run the focused tests and confirm failures describe the existing URL and validation behavior.
- [ ] Add `extra="forbid"`, normalize UTC expiry to whole seconds, and move the token to `ExecuteSuggestedAction.token`.
- [ ] Run the focused tests to green.

### Task 2: Durable Queue and Lease Recovery

**Files:**
- Create: `migrations/versions/0010_durable_suggested_actions.py`
- Modify: `src/recipe_agent/domain/identity/models.py`
- Modify: `src/recipe_agent/domain/conversation/repository.py`
- Modify: `src/recipe_agent/infrastructure/jobs/actions.py`
- Modify: `src/recipe_agent/worker.py`
- Test: `tests/security/test_suggested_action_security.py`
- Test: `tests/integration/db/test_unified_runtime_migration.py`

**Interfaces:**
- Produces: `queue_once()`, `claim_for_execution()`, `recover_expired()`, `retry_or_fail()`, `ACTION_EXECUTION_REQUESTED_TOPIC`.

- [ ] Write failing queue, lease-expiry recovery, retry, simultaneous-click, and migration tests.
- [ ] Run them and verify RED against synchronous execution.
- [ ] Add queued state, attempt counter, lease expiry, transactional outbox publication, action status reads, and expired-lease recovery.
- [ ] Add the action Celery publisher/job boundary carrying only action ID.
- [ ] Run queue/recovery/PostgreSQL tests to green.

### Task 3: Transactional Mutation Receipts

**Files:**
- Create: `src/recipe_agent/domain/conversation/receipts.py`
- Modify: `src/recipe_agent/domain/recipes/repository.py`
- Modify: `src/recipe_agent/domain/planning/repository.py`
- Modify: `src/recipe_agent/domain/planning/service.py`
- Modify: `src/recipe_agent/domain/sharing/models.py`
- Modify: `src/recipe_agent/domain/sharing/repository.py`
- Modify: `src/recipe_agent/domain/sharing/service.py`
- Modify: `src/recipe_agent/domain/conversation/actions.py`
- Test: `tests/e2e/test_suggested_actions.py`
- Test: `tests/security/test_suggested_action_security.py`

**Interfaces:**
- Produces: unique `ActionMutationReceipt.action_id`; action-aware repository methods returning the original typed result on retry.

- [ ] Write failing crash-after-domain-commit tests for save, create plan, replace plan item, and share.
- [ ] Verify each retry currently duplicates or conflicts.
- [ ] Add receipt lookup/write helpers and persist each receipt atomically with its domain mutation.
- [ ] Pass `action_id` through all four fixed adapters and return token-free audit results.
- [ ] Run exact-once tests to green.

### Task 4: Recoverable Share Delivery and Four-action E2E

**Files:**
- Modify: `src/recipe_agent/domain/sharing/service.py`
- Modify: `src/recipe_agent/domain/sharing/repository.py`
- Modify: `src/recipe_agent/api/v1/actions.py`
- Test: `tests/e2e/test_suggested_actions.py`
- Test: `tests/security/test_suggested_action_security.py`

**Interfaces:**
- Produces: authenticated action status with optional owner-only share delivery derived from action ID; token-free `result_json` and receipt JSON.

- [ ] Write failing tests proving no share token appears in action/receipt persistence and only the owning account can request delivery.
- [ ] Write E2E tests for create plan, replace plan item, and create share.
- [ ] Implement deterministic HMAC share token derivation and owner-scoped delivery lookup without plaintext persistence.
- [ ] Run all Task 6 E2E and security tests to green.

### Task 5: Verification and Handoff

**Files:**
- Modify: `.superpowers/sdd/task-6-report.md`

- [ ] Run focused SQLite and PostgreSQL race/migration tests.
- [ ] Run Ruff format/lint and strict mypy.
- [ ] Run PostgreSQL-enabled `make backend-verify`.
- [ ] Audit token persistence/logging, exact claims, leases/retries, receipts, ownership, and compatibility.
- [ ] Update the report with actual evidence and commit the review fixes.
