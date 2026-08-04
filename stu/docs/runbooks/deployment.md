# Deployment Runbook

## Required configuration

Provide production values through the deployment secret manager. Never commit them.

- `RECIPE_AGENT_ENVIRONMENT=production`
- `RECIPE_AGENT_DATABASE_URL`
- `RECIPE_AGENT_REDIS_URL`
- `RECIPE_AGENT_SESSION_SIGNING_KEY`
- `RECIPE_AGENT_METRICS_TOKEN`
- Lark application credentials and verification keys
- S3-compatible storage credentials
- AI provider credentials used by LiteLLM

The session and metrics secrets must be distinct random values. Production startup rejects the development defaults.

## Release sequence

1. Build immutable API, worker, and Web images from the same commit.
2. Back up PostgreSQL and confirm the restore point.
3. Run `docker compose -f infra/compose.yaml run --rm migrate` (or the equivalent platform release job) exactly once.
4. Deploy the API and wait for `/health/ready` to pass.
5. Deploy the worker, then the Web image.
6. Verify a Lark URL challenge, a Chinese and English Web session, one recipe import, three recommendations, one weekly plan, and one expiring share.
7. Query `/metrics` with the metrics bearer token and confirm request counters are present.

Do not run migrations in every API replica. One explicit release job owns schema changes.

## Rollback

Roll application images back to the previous immutable tag. Database downgrades require an incident review because recipe versions, feedback events, and share snapshots are durable user data. Prefer a forward migration when possible.

## Security checks

- Lark callbacks use HTTPS, token verification, optional encryption, and event ID idempotency.
- Uploads use an allowlist, a configured size limit, private object storage, and household-prefixed object keys.
- Logs contain identifiers and operation names, never message bodies, prompts, credentials, emails, phone numbers, or raw recipe text.
- The metrics endpoint is not public and requires its own bearer token.
