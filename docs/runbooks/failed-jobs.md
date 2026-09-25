# Failed Jobs Runbook

## Import jobs

1. Find the raw input by correlation ID, job ID, or household-scoped raw input ID.
2. Confirm the original text, object, or URL still exists in private storage.
3. Inspect the sanitized error class and adapter name. Do not copy source content into logs or tickets.
4. Correct provider credentials, content support, or transient storage access.
5. Move the item from `needs_review` back to the import queue only after the cause is understood.
6. Confirm the retry created one recipe version and did not duplicate the raw input.

## Outbox events

1. Query unpublished `outbox_events` ordered by `created_at`.
2. Review `topic`, `attempts`, and `last_error`; payload values remain private.
3. Restore the downstream publisher before retrying. Never mark an event published manually before the consumer acknowledges its stable event ID.
4. Run one worker cycle and confirm `published_at` is set.
5. If a downstream side effect may have occurred, search by outbox event ID. Consumers must treat that ID as an idempotency key.

## Escalation

Escalate when a job has failed three times, the oldest pending event exceeds 15 minutes, or failures affect more than one household. Include correlation IDs, event IDs, sanitized error classes, deployment version, and timestamps. Exclude recipe text and credentials.
