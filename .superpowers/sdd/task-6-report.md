# Task 6 Report: Durable Suggested Actions Review Fixes

## Status

Complete. Explicit clicks now queue recoverable action-ID-only jobs, mutation retries are
idempotent by action ID, and neither consent nor share bearer tokens are persisted in audit,
receipt, snapshot, or outbox payloads.

## Review Fixes

- Replaced the token-bearing URL with `POST /api/v1/agent/actions/execute`; the closed JSON body
  contains only `token`. Account, household, action type, and arguments still come exclusively
  from authenticated scope, signed claims, and the persisted row.
- Normalized signed expiration to whole-second UTC and requires the persisted expiration to equal
  the signed claim exactly. A row-expiry tamper regression fails before queueing.
- Recursively closed recipe ingredient, recipe step, and plan-slot argument models with
  `extra="forbid"`.
- Changed click handling from synchronous dispatch to an atomic `pending -> queued` transition
  plus a transactional `agent.action.requested` outbox event containing only the action UUID.
- Added worker leases, attempt counts, expired-lease recovery, bounded retry/failure, duplicate-job
  no-op behavior, and attempt-number fencing so stale workers cannot complete or fail a newer
  lease. Re-review added the attempt ceiling directly to claim and expired-lease recovery:
  exhausted deaths become durable `worker_lease_expired` failures without another outbox event,
  and an already-exhausted queued row is defensively failed as `attempts_exhausted`.
- Added migration `0010_durable_action_execution` for queued state, leases, attempts, unique
  action mutation receipts, and share source-action linkage. PostgreSQL upgrade/downgrade and
  SQLite upgrade-to-head both pass.
- Added transaction-local mutation receipts keyed by `action_id`. Recipe saves, plan creation,
  plan replacement, and share creation store the receipt in the same transaction as the domain
  write. Retries and concurrent workers return the original typed result; a PostgreSQL race test
  confirms one recipe and one shared result. Planning now reads its typed receipt before calling
  the recommender or loading the current plan, so recovery still succeeds if recommendations fail
  or the source plan was subsequently removed.
- Made share action audit results token-free (`share_id`, `expires_at`). The raw share token is
  deterministically derived with HMAC from a server secret and action ID, and is returned only by
  the authenticated owner-scoped status delivery path. Persistence retains only its hash.
- Added four-action E2E coverage, including retry after the mutation transaction committed before
  action completion, safe share delivery, and a database-field regression proving both raw consent
  and raw share tokens are absent.
- Hardened migration 0010 for populated 0009 databases. Legacy executing rows predate mutation
  receipts and are therefore failed as `legacy_execution_unrecoverable` rather than replayed;
  legacy create-share result JSON is nulled and marked `legacy_share_result_scrubbed`. Downgrade
  maps queued/executing 0010 rows to `downgrade_incomplete_action` failures before restoring the
  old status constraint.
- Share delivery now rejects revoked and expired snapshots. Missing records, hash mismatch, key
  rotation, and malformed persisted snapshots are normalized to a bounded action error and stable
  API 502 response. Persisted successful result JSON is validated and projected through a closed
  schema for its fixed action type, preventing arbitrary legacy fields from being returned.

## TDD and Review Evidence

- The API/schema regressions initially exposed the old token URL, non-exact expiry matching, and
  permissive nested argument fields before the production changes.
- Queue/lease tests were written against the synchronous path and then made green with the
  outbox-backed queued state and recovery flow.
- PostgreSQL first rejected the new migration because its revision identifier exceeded the
  repository's 32-character Alembic version column. The identifier was shortened and the entire
  PostgreSQL migration suite then passed.
- The final concurrency audit identified that lease expiration alone did not fence a stale worker.
  Attempt-number conditions were added to completion, retry, and failure transitions, with a
  regression proving stale completion is rejected.
- Concurrent PostgreSQL mutation execution exercises the receipt uniqueness race and confirms the
  losing transaction rolls back its duplicate domain write and returns the winner's receipt.
- Re-review RED tests reproduced indefinite lease requeueing, planning retries failing before
  receipt lookup, populated migration state remaining unsafe, revoked delivery remaining live,
  and arbitrary persisted result JSON being returned. Each focused test passed after its bounded
  production fix.

## Security and Correctness Audit

- **Token storage/logging:** consent rows store SHA-256 hashes; share rows store SHA-256 hashes;
  action audit, mutation receipts, snapshots, and outbox payloads contain no raw bearer token.
  Operational outbox logging emits payload field names only.
- **Claims and authorization:** signer validation is followed by a closed claims model and exact
  comparison of action ID, token hash, account, household, source run, action type, and expiration.
  Status and share delivery require the same owning authenticated account and household.
- **Recoverability:** committed clicks always have a committed outbox intent. Workers lease by
  UUID, the poller requeues expired leases, handler failures create retry intents up to the bounded
  attempt limit, exhausted leases fail without another event, defensive claims enforce the same
  ceiling, and duplicate Celery deliveries are acknowledged as no-ops.
- **Exactly-once domain effects:** every fixed mutation writes a unique action receipt atomically
  with its domain changes. A crash after the domain commit but before action completion therefore
  reuses the receipt instead of repeating the mutation.
- **Dispatch safety:** persisted or token-supplied data never selects arbitrary code. Only the four
  constructor-injected handlers under the fixed action allowlist can execute.
- **Worktree hygiene:** the pre-existing `web/next-env.d.ts` modification was neither edited nor
  staged.

## Final Verification

Command:

```bash
RECIPE_AGENT_TEST_DATABASE_URL=postgresql+asyncpg://recipe:local-recipe-password@127.0.0.1:55432/postgres make backend-verify
```

Result: exit 0.

- Ruff format: 158 files already formatted.
- Ruff lint: all checks passed.
- Strict mypy: 97 source files passed.
- Pytest: 185 passed, including populated PostgreSQL upgrade/downgrade, simultaneous clicks,
  concurrent mutation receipts, all four action E2E cases, bounded worker-death recovery,
  receipt-first planning retries, safe share-delivery failures, result schemas, ownership, and
  token persistence.
- SQLite migration gate: upgraded through `0010_durable_action_execution`.
- Warnings: 20 pre-existing Alembic `path_separator` deprecation warnings only.

## Concerns

No Task 6 correctness blocker is known. Concrete production service composition remains the
planned composition-root responsibility; Task 6 supplies the transport-neutral service, API,
worker boundary, migrations, fixed adapters, and recovery semantics.
