# Google Cloud Run deployment

Stu · Family Table runs on Cloud Run behind a Cloudflare Worker at
`https://stu.dodofamily.com`. Anyone can sign up with an email and a password;
each account gets its own household.

| Setting | Value |
| --- | --- |
| Google account | `yuzhu9387@gmail.com` |
| Project / region | `leonas-friends` / `us-west2` |
| Browser hostname | `https://stu.dodofamily.com` |
| Cloud Run services | `stu-api` (FastAPI, port 8000), `stu-web` (Next.js, port 3000) |
| Backends | `https://stu-api-314788321213.us-west2.run.app`, `https://stu-web-314788321213.us-west2.run.app` |
| Runtime service accounts | `stu-runtime@…` for the API and jobs (Cloud SQL client, reads the `stu-*` secrets); `stu-web-runtime@…` for the web app (no permissions) |
| Automatic deploys | GitHub Actions `deploy.yml` on every push to `main`, as `stu-deployer@…` |
| Images | `us-west2-docker.pkg.dev/leonas-friends/stu/{api,web}:<tag>` |
| Cloud SQL | instance `leonas-friends:us-west2:avery-db` (shared), database `stu`, role `stu_app` |
| Secrets | `stu-database-url`, `stu-openai-api-key`, `stu-session-signing-key`, `stu-metrics-token`, `stu-action-signing-key`, `stu-edge-proxy-token` |
| Cloudflare | account `LeonaFriends`, Worker `stu-proxy` ([`deploy/cloudflare`](../../deploy/cloudflare)) |
| Cloud Run jobs | `stu-migrate` (`alembic upgrade head`), `stu-plan` (`python -m recipe_agent.run_due`) |
| Scheduled planning | Cloud Scheduler `stu-plan-hourly` runs `stu-plan` at :05 each hour as `stu-scheduler@leonas-friends.iam.gserviceaccount.com` (Cloud Run Invoker on that job only) |

## How it fits together

- The Worker serves `stu.dodofamily.com`: `/api/*` goes to `stu-api` with the
  edge token in `X-Stu-Proxy-Token`; everything else goes to `stu-web`. The API
  refuses any request without that token (404), except `/health/*`, so the
  data is only reachable through Cloudflare. HTTP redirects to HTTPS.
- The web image is built with `NEXT_PUBLIC_API_BASE_URL=https://stu.dodofamily.com`,
  so the browser talks to one origin and the session cookie is first-party.
- Stu's AI work (drafting a week, chat changes, confirmation) runs in the API
  process after the request returns, so `stu-api` runs with **CPU always
  allocated** (`--no-cpu-throttling`). Instances still scale to zero when idle.
- No Redis, Celery worker or dispatcher runs here: the kitchen web app does not
  need them, and `RECIPE_AGENT_REDIS_URL` is empty so readiness checks the
  database only. The dispatcher's scheduled weekly planning is the `stu-plan`
  Cloud Run job, started hourly by Cloud Scheduler: it drafts the weeks whose
  planning time has come and exits, billed only while it runs. Database claims
  keep a week from being drafted twice.
- The Cloud SQL **instance** is shared with Avery and Socrates. Stu has its own
  database and a restricted login (`stu_app`: not a superuser, cannot create
  roles or databases, no grants on other databases). Do not reuse its
  credentials elsewhere.

## Select the account without touching the active gcloud configuration

```sh
export CLOUDSDK_CORE_ACCOUNT=yuzhu9387@gmail.com CLOUDSDK_CORE_PROJECT=leonas-friends
```

## Release

Push to `main`. [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml)
runs every check in [`ci.yml`](../../.github/workflows/ci.yml) (backend on
PostgreSQL 16, migrations on an empty database, web, the Worker, and the browser
stories), then signs in to Google Cloud without a key, builds both images
tagged with the commit SHA, runs `stu-migrate`, moves `stu-api`, `stu-web` and
`stu-plan` to the new images, and smoke-tests the site. A failed check or step
leaves the running version in place; fix it and push again, or re-run the
workflow from the Actions tab. Only the newest commit on `main` is released,
one release at a time. Progress: https://github.com/yuzhu9387/Stu/actions.

The workflow signs in through Workload Identity Federation: pool `stu-github`,
provider `github`, which accepts only repository ID `1302094716` (owner
`33359827`), ref `refs/heads/main`, workflow
`yuzhu9387/Stu/.github/workflows/deploy.yml@refs/heads/main`, and a `push` or
`workflow_dispatch` event. That principal may act only as
`stu-deployer@leonas-friends.iam.gserviceaccount.com`, which holds:

- Artifact Registry writer on the `stu` repository only;
- Cloud Run developer on `stu-api`, `stu-web`, `stu-migrate` and `stu-plan` only;
- Service Account User on `stu-runtime` and `stu-web-runtime` only;
- the custom `stuRunOperationReader` role (`run.operations.get`) on the
  project, since Cloud Run operations are project resources.

It has no key, no GitHub secret, no Secret Manager or Cloud SQL access, and no
role on Avery or Socrates. `stu-web` runs as `stu-web-runtime`, which has no
permissions at all (it serves pages only).

Manual fallback, from the repository root (Cloud Build uploads only what
`.gcloudignore` allows; check with `gcloud meta list-files-for-upload`):

```sh
TAG="$(date +%Y%m%d-%H%M)-$(git rev-parse --short HEAD)"
gcloud builds submit --region=us-west2 --config=deploy/cloudbuild.yaml --substitutions=_TAG="$TAG" .
gcloud run jobs update stu-migrate --region=us-west2 --image="us-west2-docker.pkg.dev/leonas-friends/stu/api:$TAG"
gcloud run jobs execute stu-migrate --region=us-west2 --wait
gcloud run deploy stu-api --region=us-west2 --image="us-west2-docker.pkg.dev/leonas-friends/stu/api:$TAG"
gcloud run deploy stu-web --region=us-west2 --image="us-west2-docker.pkg.dev/leonas-friends/stu/web:$TAG"
gcloud run jobs update stu-plan --region=us-west2 --image="us-west2-docker.pkg.dev/leonas-friends/stu/api:$TAG"
```

`gcloud run deploy` with only `--image` keeps the service's secrets,
environment, Cloud SQL attachment and scaling. Never edit an applied migration.

## First installation (already done on 2026-09-25)

1. Artifact Registry repository `stu`; service account `stu-runtime` with
   `roles/cloudsql.client`.
2. Database: a temporary Cloud SQL user created `stu_app` (`LOGIN NOSUPERUSER
   NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION`) and database `stu` owned by
   it, with `REVOKE ALL ON DATABASE stu FROM PUBLIC`, `REVOKE CREATE ON SCHEMA
   public FROM PUBLIC`; the temporary user was then deleted.
3. Secrets created from private temporary files (never on the command line),
   each readable only by `stu-runtime`. `stu-database-url` is
   `postgresql+asyncpg://stu_app:…@/stu?host=/cloudsql/leonas-friends:us-west2:avery-db`.
4. Services:

```sh
SECRETS='RECIPE_AGENT_DATABASE_URL=stu-database-url:latest,OPENAI_API_KEY=stu-openai-api-key:latest,RECIPE_AGENT_SESSION_SIGNING_KEY=stu-session-signing-key:latest,RECIPE_AGENT_METRICS_TOKEN=stu-metrics-token:latest,RECIPE_AGENT_ACTION_SIGNING_KEY=stu-action-signing-key:latest'
API_SECRETS="$SECRETS,RECIPE_AGENT_EDGE_PROXY_TOKEN=stu-edge-proxy-token:latest"
ENV='RECIPE_AGENT_ENVIRONMENT=production,RECIPE_AGENT_WEB_ORIGIN=https://stu.dodofamily.com,RECIPE_AGENT_REDIS_URL=,RECIPE_AGENT_LITELLM_CHAT_MODEL=openai/gpt-5.1,RECIPE_AGENT_LITELLM_VISION_MODEL=openai/gpt-5-mini,RECIPE_AGENT_LITELLM_FALLBACK_MODEL=openai/gpt-5-mini,RECIPE_AGENT_LITELLM_EMBEDDING_MODEL=openai/text-embedding-3-small,RECIPE_AGENT_LITELLM_REASONING_EFFORT=high,RECIPE_AGENT_LITELLM_TIMEOUT_SECONDS=90,RECIPE_AGENT_LITELLM_MAX_RETRIES=1,RECIPE_AGENT_KITCHEN_GENERATION_TIMEOUT_SECONDS=420,RECIPE_AGENT_KITCHEN_GENERATION_REASONING_EFFORT=low'

gcloud run jobs create stu-migrate --region=us-west2 --image="$API_IMAGE" \
  --service-account=stu-runtime@leonas-friends.iam.gserviceaccount.com \
  --set-cloudsql-instances=leonas-friends:us-west2:avery-db \
  --set-secrets="$SECRETS" --set-env-vars="$ENV" \
  --command=alembic --args=upgrade,head --max-retries=0 --task-timeout=600

gcloud run jobs create stu-plan --region=us-west2 --image="$API_IMAGE" \
  --service-account=stu-runtime@leonas-friends.iam.gserviceaccount.com \
  --set-cloudsql-instances=leonas-friends:us-west2:avery-db \
  --set-secrets="$SECRETS" --set-env-vars="$ENV" \
  --command=python --args=-m,recipe_agent.run_due --cpu=1 --memory=1Gi --max-retries=0 --task-timeout=900

gcloud run deploy stu-api --region=us-west2 --image="$API_IMAGE" \
  --service-account=stu-runtime@leonas-friends.iam.gserviceaccount.com \
  --set-cloudsql-instances=leonas-friends:us-west2:avery-db \
  --set-secrets="$API_SECRETS" --set-env-vars="$ENV" \
  --port=8000 --cpu=1 --memory=1Gi --no-cpu-throttling --concurrency=40 \
  --min-instances=0 --max-instances=2 --timeout=300 \
  --startup-probe='httpGet.path=/health/ready,httpGet.port=8000,periodSeconds=5,timeoutSeconds=3,failureThreshold=24' \
  --ingress=all --allow-unauthenticated

gcloud run deploy stu-web --region=us-west2 --image="$WEB_IMAGE" \
  --service-account=stu-web-runtime@leonas-friends.iam.gserviceaccount.com \
  --port=3000 --cpu=1 --memory=512Mi --concurrency=80 \
  --min-instances=0 --max-instances=2 --ingress=all --allow-unauthenticated
```

`--allow-unauthenticated` is needed because the Worker calls Cloud Run without
Google credentials; the API still refuses requests without the edge token.

5. Worker, with its secret uploaded atomically from a private temporary file:

```sh
printf '{"EDGE_PROXY_SECRET":"%s"}\n' "$(cat edge-proxy-token)" > worker-secrets.json   # mode 600
npm exec --yes --package=wrangler@4.130.0 -- wrangler deploy --config deploy/cloudflare/wrangler.jsonc --secrets-file worker-secrets.json
rm worker-secrets.json
```

Later Worker deploys keep the secret: `npm exec --yes --package=wrangler@4.130.0 -- wrangler deploy --config deploy/cloudflare/wrangler.jsonc`.
Test the Worker with `node --test deploy/cloudflare/proxy.test.mjs`.

6. Scheduled planning:

```sh
gcloud iam service-accounts create stu-scheduler --display-name='Stu scheduled planning trigger'
gcloud run jobs add-iam-policy-binding stu-plan --region=us-west2 \
  --member=serviceAccount:stu-scheduler@leonas-friends.iam.gserviceaccount.com --role=roles/run.invoker
gcloud scheduler jobs create http stu-plan-hourly --location=us-west2 \
  --schedule='5 * * * *' --time-zone=UTC --http-method=POST \
  --uri=https://run.googleapis.com/v2/projects/leonas-friends/locations/us-west2/jobs/stu-plan:run \
  --oauth-service-account-email=stu-scheduler@leonas-friends.iam.gserviceaccount.com --attempt-deadline=60s
```

## Rotating a secret

Add a new version (`gcloud secrets versions add stu-<name> --data-file=…`) and
redeploy with `gcloud run services update stu-api --region=us-west2
--update-secrets=…:latest` so a new revision reads it. For the edge token,
upload the same value to the Worker first (`wrangler secret put
EDGE_PROXY_SECRET --config deploy/cloudflare/wrangler.jsonc`), then update the
API.

## Operations

```sh
gcloud run services logs read stu-api --region=us-west2 --limit=100
gcloud run revisions list --service=stu-api --region=us-west2
gcloud run services update-traffic stu-api --region=us-west2 --to-revisions=<known-good>=100
```

`/health/live` reports the process and `/health/ready` the database. A code
rollback does not reverse a migration; roll back only to code that works with
the current schema.

Back up only the `stu` database, through the Cloud SQL Auth Proxy with a fresh
token (`CSQL_PROXY_TOKEN="$(gcloud auth print-access-token)" cloud-sql-proxy
leonas-friends:us-west2:avery-db --port=5439`), then `pg_dump
--username=stu_app --dbname=stu --format=custom`. Restore only into a new,
empty database.

## MCP

AI clients use the app's MCP with a personal access token from Settings → AI
Access; the administrator's database MCP runs locally. See [MCP.md](../MCP.md).

## Known limits

- There is no password reset yet (no email delivery). A forgotten password
  needs a database change by the operator.
- Sign-up is open to anyone; wrong passwords lock an account for 15 minutes
  after 10 tries. There is no CAPTCHA or per-IP limit yet.
- Local and cloud databases are independent; nothing syncs between them.
- There is no account deletion in the app. To remove an account by hand,
  delete its `weekly_plans`, `inventory_batches` and `kitchen_recipes` before
  its `households` row (some references are RESTRICT), then the `accounts` row.
