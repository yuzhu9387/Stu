# Queued Dispatch Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover run and action jobs whose durable outbox event was published but whose worker exhausted broker retries before claiming the queued database row.

**Architecture:** Reconciliation reuses the newest durable outbox event for each queued entity. A published event becomes eligible only after a quiet interval; its existing `attempts` field is the bounded reconciliation counter, and reconciliation atomically resets that event's `published_at` so the normal dispatcher republishes the same UUID-only intent. At the ceiling, the queued entity fails with a safe code; Lark runs enqueue their existing terminal delivery intent.

**Tech Stack:** Python 3.12, SQLAlchemy asyncio, FastAPI/Celery transactional outbox, pytest, SQLite and PostgreSQL-compatible SQL.

## Global Constraints

- Preserve account and household isolation.
- Broker messages contain only durable UUIDs.
- Duplicate broker delivery remains an atomic no-op.
- Never persist or log model, user, token, or provider exception content.
- Reconciliation is bounded and does not republish recently dispatched work.

---

### Task 1: Run queued-dispatch reconciliation

**Files:**
- Modify: `src/recipe_agent/domain/conversation/repository.py`
- Test: `tests/integration/conversation/test_hub.py`

**Interfaces:**
- Consumes: the latest `agent.run.requested` `OutboxEvent` matching `{"run_id":"<uuid>"}`.
- Produces: `AgentRunRepository.reconcile_stale_queued(*, now, stale_after, max_dispatch_attempts, limit) -> int`.

- [ ] Write failing tests for same-event republication, recent-event exclusion, bounded terminal failure, and Lark terminal intent.
- [ ] Run the focused tests and verify missing-method failures.
- [ ] Implement conditional `published_at` reset and fenced queued-to-failed transition.
- [ ] Run the focused tests and verify green.

### Task 2: Action queued-dispatch reconciliation

**Files:**
- Modify: `src/recipe_agent/domain/conversation/repository.py`
- Test: `tests/security/test_suggested_action_security.py`

**Interfaces:**
- Consumes: the latest `agent.action.requested` `OutboxEvent` matching `{"action_id":"<uuid>"}`.
- Produces: `SuggestedActionRepository.reconcile_stale_queued(*, now, stale_after, max_dispatch_attempts, limit) -> int`.

- [ ] Write failing tests for same-event republication and bounded terminal failure.
- [ ] Run the focused tests and verify missing-method failures.
- [ ] Implement the action equivalent with `dispatch_attempts_exhausted` as the safe terminal code.
- [ ] Run the focused tests and verify green.

### Task 3: Dispatcher integration and process regression

**Files:**
- Modify: `src/recipe_agent/worker.py`
- Test: `tests/integration/db/test_outbox.py`
- Test: `tests/unit/jobs/test_agent_runs.py`
- Test: `tests/unit/jobs/test_suggested_actions.py`

**Interfaces:**
- Consumes: both repository reconciliation methods before `publish_pending`.
- Produces: a stale published event is reset, republished with the same event ID, and then claimable/completable by the normal worker.

- [ ] Write a failing process regression that simulates repeated pre-claim database failures, broker retry exhaustion, time advancement, reconciliation, same-event republication, and successful completion.
- [ ] Wire both reconciliation calls into the dispatcher with a two-minute quiet interval and three-publication ceiling.
- [ ] Verify worker task retry bounds and duplicate delivery no-op behavior remain green.

### Task 4: Verification and delivery

**Files:**
- Modify: `.superpowers/sdd/task-8-report.md`

- [ ] Run Ruff formatting/lint and strict mypy.
- [ ] Run focused reconciliation tests.
- [ ] Run `make backend-verify` and Web verification where relevant.
- [ ] Run `docker compose -f infra/compose.yaml config --quiet` and `git diff --check`.
- [ ] Update the Task 8 report and commit the fix.
