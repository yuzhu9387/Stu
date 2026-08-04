# Durable Suggested Actions Re-review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining bounded-retry, receipt-first recovery, migration compatibility, share-delivery, and status-result safety gaps.

**Architecture:** Keep action execution UUID-only and receipt-backed. Add the attempt ceiling to repository claim/recovery transitions, expose typed plan-receipt reads before any prerequisite work, migrate legacy action rows into bounded safe states, and validate persisted results with per-action output schemas before returning them.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy asyncio, Alembic, PostgreSQL, pytest.

## Global Constraints

- Never persist or return a raw consent or share bearer token from action audit state.
- Never requeue an action beyond the configured maximum attempt count.
- Preserve `web/next-env.d.ts` without staging or editing it.
- Use test-first red-green cycles and run the PostgreSQL-enabled full backend gate before commit.

---

### Task 1: Bound Lease Recovery

**Files:**
- Modify: `src/recipe_agent/domain/conversation/repository.py`
- Modify: `src/recipe_agent/domain/conversation/actions.py`
- Modify: `src/recipe_agent/worker.py`
- Test: `tests/security/test_suggested_action_security.py`

**Interfaces:**
- Produces: `claim_for_execution(..., max_attempts: int)` and `recover_expired(..., max_attempts: int)`.

- [x] Add a test that repeatedly expires leases through the ceiling and asserts durable `failed`, `worker_lease_expired`, and no additional action outbox event.
- [x] Run the focused test and confirm current recovery requeues past the ceiling.
- [x] Make recovery atomically fail exhausted rows and make claiming reject rows at the ceiling.
- [x] Pass the service/worker maximum into claim and recovery and run the focused security suite green.

### Task 2: Receipt-first Planning Recovery

**Files:**
- Modify: `src/recipe_agent/domain/planning/repository.py`
- Modify: `src/recipe_agent/domain/planning/service.py`
- Test: `tests/e2e/test_suggested_actions.py`

**Interfaces:**
- Produces: `PlanRepository.get_action_result(action_id, action_type)` returning a typed stored `MealPlan` before recommendation or plan lookup.

- [x] Add create-plan retry coverage with a recommender that now fails and replace-plan retry coverage after the source plan is deleted.
- [x] Run both tests and confirm failures occur before repository receipt recovery.
- [x] Add repository receipt lookup and call it at entry to `create_week` and `replace_item`.
- [x] Run the planning action E2E tests green.

### Task 3: Populated 0009 Migration Safety

**Files:**
- Modify: `migrations/versions/0010_durable_suggested_action_execution.py`
- Modify: `tests/integration/db/test_unified_runtime_migration.py`

**Interfaces:**
- Produces: safely failed legacy executing rows, scrubbed legacy create-share results, and downgrade-safe queued/executing mappings.

- [x] Seed populated 0009 actions for executing, queued-at-0010, and plaintext create-share result cases in the migration integration test.
- [x] Run the PostgreSQL migration test and confirm upgrade leaves unsafe state and downgrade violates the 0009 check.
- [x] During upgrade fail pre-receipt executing rows as `legacy_execution_unrecoverable` without retry and scrub create-share results to `legacy_share_result_scrubbed` with null result.
- [x] Before downgrade map queued and executing rows to bounded failures and clear leases; run upgrade/downgrade tests green.

### Task 4: Safe Share Delivery and Persisted Results

**Files:**
- Modify: `src/recipe_agent/domain/sharing/service.py`
- Modify: `src/recipe_agent/domain/conversation/actions.py`
- Modify: `tests/e2e/test_suggested_actions.py`
- Modify: `tests/security/test_suggested_action_security.py`

**Interfaces:**
- Produces: stable `ActionExecutionError` for unavailable delivery and per-action validation of persisted success results.

- [x] Add delivery tests for revoked, expired, missing, hash-mismatched, and rotated-key records, plus a status test with arbitrary legacy result JSON.
- [x] Run focused tests and confirm expiry/revocation is ignored and arbitrary JSON is returned or raw errors escape.
- [x] Enforce live share state, normalize delivery failures, and validate action results with closed per-action result schemas.
- [x] Run focused API/security/E2E tests green.

### Task 5: Verification and Commit

**Files:**
- Modify: `.superpowers/sdd/task-6-report.md`

**Interfaces:**
- Produces: final review evidence and a single scoped commit.

- [x] Run focused PostgreSQL migration/action tests.
- [x] Run Ruff format/lint, strict mypy, and `git diff --check`.
- [x] Run PostgreSQL-enabled `make backend-verify`.
- [x] Update the Task 6 report with actual evidence, stage everything except `web/next-env.d.ts`, and commit.
