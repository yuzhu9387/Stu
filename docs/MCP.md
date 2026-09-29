# Letting an AI assistant work with Stu (MCP)

There are two MCP servers. Use the first for everyday work in a household; the
second is an administrator's tool over the whole database.

## 1. The app's MCP: one household, everything in it

`https://stu.dodofamily.com/api/v1/kitchen/mcp` (locally
`http://localhost:8000/api/v1/kitchen/mcp`), Streamable HTTP with JSON
responses, protocol `2025-03-26`.

**Access.** Create a personal access token in **Settings → AI Access 🔌**. The
token (`stu_…`) is shown once; only its hash is stored. It acts as you in your
household and nowhere else. It can use every kitchen tool, but it cannot list,
create or revoke tokens (that needs the signed-in web app). Revoke it there to
cut the assistant off; "last used" shows when it was last active. An account
holds at most 10 tokens.

Connect Claude Code:

```sh
claude mcp add --transport http stu https://stu.dodofamily.com/api/v1/kitchen/mcp --header "Authorization: Bearer stu_…"
```

**Tools.** Every change goes through the kitchen engine, so it is validated,
bumps the workspace revision and lands in the undo history, exactly like a
change made in the app.

| Tool | What it does |
| --- | --- |
| `kitchen_read` | The whole household workspace: recipes, tags, fridge, plans (meals, prep, chat), settings and guidance, knowledge documents, presets, weekly prompts, audit history. |
| `kitchen_command` | Any change: `recipe.save/delete/rate`, `tag.save/apply/delete/pin`, `inventory.save/delete/arrange/receive`, `settings.save`, `knowledge.save/delete`, `plan.save/confirm/presets/chat`, `meal.save/delete/include/status/like/lock/leftovers`, `prep.save/delete/status/like`, `preset.save`, `planning.prompt/workflow`, `shopping.check`, `shopping.save/delete/putAway` (the fridge door's note: `{item:{id,name,quantity?,checked}}`, `{id}`, `{items:[{id,location?,portions?,type?}]}`), `change.undo`. `meal.status` takes `changed` with an optional `note` (no stock is taken); `prep.status` takes `location: freezer|fridge` for the extra portions, and a prep task with `origin: "fridge"` (+ Prep) can be done before its plan is confirmed. Pass the current `expectedRevision` from `kitchen_read`. |
| `kitchen_generate` | Start drafting a week in the background; returns the task. |
| `kitchen_task` / `kitchen_task_latest` | Follow a background AI task (a week draft, a chat answer, a confirmation), including ones the web app started. |
| `kitchen_task_apply` | Apply a finished chat task's proposed changes; with `mealIds`, only those meals (and the new recipes and prep they use). |
| `kitchen_chat` | Ask for changes to selected meals and get a preview (nothing is applied). |
| `kitchen_extract` | Turn recipe text or an image into recipe candidates (nothing is saved). |
| `kitchen_import_link` | Read a public recipe page or video link and return recipe candidates (nothing is saved; private addresses are refused). |
| `kitchen_fill` | Fill the blanks of a meal's hand-written dishes: food group, ingredients, steps, minutes (nothing is saved). |
| `kitchen_compose` | Make one dish from chosen fridge foods: a recipe and the portions it takes from each (nothing is saved; add it with `meal.save` or `prep.save`). |

`plan.fulfill` (the confirmed shopping snapshot) is not offered: only the
confirmation task writes it, after checking it.

## 2. The administrator's database MCP: every table, any SQL

[`scripts/stu_db_mcp.py`](../scripts/stu_db_mcp.py) runs on your own computer
over stdio and is never exposed to the internet. It is registered for Claude
Code in [`.mcp.json`](../.mcp.json):

- `stu-db`: the production `stu` database. It starts the Cloud SQL Auth Proxy
  with your personal gcloud account (`yuzhu9387@gmail.com`, restarted with a
  fresh token every 50 minutes) and reads the connection string from Secret
  Manager (`stu-database-url`) without writing it to disk. Requires `gcloud`
  signed in to that account and `cloud-sql-proxy` on the PATH.
- `stu-db-local`: the Docker Compose database on `localhost:55433`.

| Tool | What it does |
| --- | --- |
| `list_tables` | Every table with an approximate row count. |
| `describe_table` | Columns, constraints (keys, foreign keys with ON DELETE) and indexes. |
| `query` | A read-only query (run in a READ ONLY transaction), `$1…` parameters, up to 5000 rows. |
| `execute` | Any SQL with full privileges — INSERT, UPDATE, DELETE, DDL — in one committed transaction. |

This reaches **every account and household**, including password hashes and
session tokens, as the `stu_app` owner of the database. Treat it like `psql` on
production: review writes before approving them.

Household kitchen data is written by the app to `kitchen_workspaces.state`
(JSON) and then projected into the kitchen tables. A direct write to a
projected table can be overwritten the next time the app changes that section;
for durable kitchen changes use the app's MCP, or update the JSON as well.
Deleting a household by hand needs its `weekly_plans`, `inventory_batches` and
`kitchen_recipes` removed first (some references are RESTRICT).
