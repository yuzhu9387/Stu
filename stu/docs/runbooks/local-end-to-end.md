# Local end-to-end test runbook

This runbook tests the Web app, shared ReAct runtime, PostgreSQL, Redis/Celery, explicit-click
actions, family accounts, private shares, and the Lark bot. Each person signs in to a separate
account. Joining a family changes visibility; it never merges account-owned data.

## 1. Configure the environment

From the repository root, confirm `.env` contains nonblank values for:

```text
OPENAI_API_KEY
RECIPE_AGENT_LARK_ENABLED=true
RECIPE_AGENT_LARK_APP_ID
RECIPE_AGENT_LARK_APP_SECRET
RECIPE_AGENT_LARK_VERIFICATION_TOKEN
RECIPE_AGENT_LARK_ENCRYPT_KEY
```

Keep `.env` private. Never paste these values into chat, logs, screenshots, commits, or Lark
messages. The default local model route is `openai/gpt-5.1`, reasoning is `high`, and fallback is
`openai/gpt-5-mini`.

## 2. Start a fresh local stack

To remove old local test data first:

```bash
make local-down
docker compose --env-file .env -f infra/compose.yaml down -v
```

Then start PostgreSQL, Redis, MinIO, migrations, API, worker, dispatcher, and Web:

```bash
make local-up
docker compose --env-file .env -f infra/compose.yaml ps
```

Wait until `api`, `postgres`, `redis`, and `minio` are healthy. Open:

- Web: <http://127.0.0.1:13107/chat>
- API readiness: <http://127.0.0.1:8000/health/ready>
- API docs: <http://127.0.0.1:8000/docs>
- PostgreSQL: `postgresql://recipe:recipe@127.0.0.1:55433/recipe`

If running processes directly instead of Docker, use five terminals: `make services-up`,
`make migrate`, `make run-api`, `make run-worker`, `make run-dispatcher`, and `make run-web`.

## 3. Test account login and language

1. Open `/chat` and enter a test email such as `alice@example.com`.
2. In development the magic link is consumed automatically; the session cookie is HttpOnly.
3. Switch the top-right language to English, then back to Chinese.
4. Confirm the entire visible page changes language together.
5. Open a private window and sign in as `bob@example.com`. This creates a distinct account.

## 4. Test family membership without account merging

1. As Alice, open Settings and select **Create family invite**.
2. Copy the short code only to Bob.
3. As Bob, enter it under **Enter family invite code** and select **Join family**.
4. Confirm Alice and Bob appear as separate family members.
5. Save a recipe as each account later; confirm both recipes are family-visible and retain separate
   owner labels.

## 5. Test the Web assistant and explicit confirmation

1. Ask: `Recommend three quick dinners using tomatoes.`
2. Confirm one final response contains `Thinking → Plan → Act → Answer` (or the Chinese labels).
3. Ask: `Draft a tomato soup recipe and let me save it.`
4. Before clicking **Save recipe**, open Recipes and confirm nothing new was written.
5. Click **Save recipe** once. Confirm the button reports queued and a second click cannot repeat it.
6. Refresh Recipes and confirm the record has the correct owner.
7. Repeat with prompts that produce **Create plan**, **Replace meal**, and **Create private link**.
8. Confirm Plan, Shopping, and Shares update only after their confirmation buttons are clicked.

## 6. Test all live pages

Open Recipes, Weekly plan, Shopping, Imports, Shares, and Settings. For each page verify loading,
empty, and populated states; no demo records should appear. Open a recipe detail. Open a generated
private share in a private browser window and confirm only name, ingredients, and steps appear.

## 7. Bind and test Lark

1. In Settings select **Link Lark** and note the one-time code.
2. Send `link CODE` to the bot from the Lark user that belongs to this Web account.
3. Confirm Lark reports successful binding. Reusing the code must fail safely.
4. Expose the local API through an HTTPS tunnel and configure the Lark event callback as:
   `https://YOUR-TUNNEL/webhooks/lark/events`.
5. Subscribe the app to message-receive and interactive-card callback events. Use the same
   Verification Token and Encrypt Key as `.env`.
6. Send the same recommendation question in Lark. Confirm the final card uses the same four-section
   structure and offers at most three buttons.
7. Click a Lark action button. Confirm it updates the same family data as the Web button.
8. Send a message from an unbound Lark user and confirm it receives linking instructions without
   creating a run.

The webhook only verifies and durably queues work; it does not call the Lark API before responding.

## 8. Inspect local data safely

Do not select token hashes, source payloads, or secret columns while screen sharing. Useful checks:

```bash
docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U recipe -d recipe -c \
  "select status, count(*) from agent_runs group by status;"
docker compose --env-file .env -f infra/compose.yaml exec postgres psql -U recipe -d recipe -c \
  "select execution_status, count(*) from suggested_actions group by execution_status;"
```

## 9. Optional live-model smoke test

```bash
RUN_LIVE_AI_TESTS=1 .venv/bin/python -m pytest tests/live/test_openai_smoke.py -v
```

The test checks only the typed decision contract and never prints keys, prompts, or provider bodies.

## 10. Troubleshooting and shutdown

```bash
docker compose --env-file .env -f infra/compose.yaml logs --tail=100 api worker dispatcher web
make local-down
```

- `401`: sign in again.
- Run stays queued: verify both `worker` and `dispatcher` are running and Redis is healthy.
- Model failure: check that `OPENAI_API_KEY` is present inside API and worker containers.
- Lark `503`: enable Lark and provide App ID, App Secret, and Verification Token.
- Callback fails: verify the public HTTPS URL, Verification Token, Encrypt Key, and callback event
  subscriptions. Never paste the secrets into logs while debugging.
