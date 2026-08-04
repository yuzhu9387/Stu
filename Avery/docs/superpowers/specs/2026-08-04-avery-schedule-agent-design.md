# Avery — Schedule Agent

**Date:** 2026-08-04
**Status:** Approved design
**Location:** `Leona's Friends/Avery/`

---

## 1. Purpose

Avery is a personal schedule agent for a single user. It holds three things the user
cannot hold in their head at once:

1. **What a normal week looks like** — a template of recurring daily blocks.
2. **What actually happened** — real calendar events, which drift from the template.
3. **What should be true over a month** — a ratio rule the schedule is measured against.

The product is not a calendar. It is a feedback loop: template produces a week, the week
records reality, the monthly review compares reality against a rule the user committed to
earlier, and the user adjusts either their behavior or the rule. Avery, the conversational
agent, is how the user drives all of it without clicking.

### Success criteria

- Opening the app on a Monday shows a fully populated week without any manual setup.
- A month's schedule can be judged against the 6:3:1 rule in one click, with a verdict
  per group, not just raw numbers.
- Every object can be created, read, updated, and deleted through the REST API and
  through natural language, with identical results.

### Non-goals

Multi-user accounts, timezone handling, recurrence rules beyond the template,
drag-to-resize, mobile apps, calendar import/export.

---

## 2. Decisions taken

| Question | Decision |
|---|---|
| Stack | FastAPI + async SQLAlchemy + SQLite; Vite + React 19 + TS + Tailwind 4 |
| Agent | Real Claude tool-calling agent |
| Push | Lark / 飞书 bot |
| UI language | English |
| Categories | Free-form tags; the rule maps tags → groups |
| Variance | Relative to target share |
| Week creation | Auto every Sunday, with back-arrow history |
| Monthly review | On-demand only |
| Auth | Single user, none |
| Database | `Avery/data/avery.db`, self-contained |

---

## 3. Architecture

```
Avery/
├── backend/
│   ├── app/
│   │   ├── config.py            pydantic-settings, reads .env
│   │   ├── database.py          async engine, session factory, Base
│   │   ├── models/              SQLAlchemy ORM
│   │   ├── schemas/             Pydantic request/response
│   │   ├── services/            ALL business logic
│   │   ├── routers/             thin REST wrappers
│   │   ├── agent/               Claude tool-calling loop + tool definitions
│   │   ├── lark/                client, cards, sender
│   │   ├── scheduler/           APScheduler jobs
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/                 typed fetch client, one module per object
│   │   ├── components/          calendar grid, event card, tag chip, ratio bar
│   │   ├── pages/               Week Month Tasks TaskDetail Template Rules Review
│   │   ├── theme.css            春山景别 palette as CSS custom properties
│   │   └── main.tsx
│   └── package.json
├── data/avery.db
└── docs/
```

### The layering rule

`routers/` and `agent/` are both **thin adapters over `services/`**. Neither contains
business logic. The agent calls Python service functions directly — never HTTP against
its own server.

This matters because it is the only thing preventing the REST API and the natural-language
path from diverging. If `create_event` validates overlap in the router, the agent skips
that validation and produces corrupt data. Every rule lives in the service layer, so both
callers inherit it for free.

### Module responsibilities

| Module | Does | Depends on |
|---|---|---|
| `services/tags.py` | tag CRUD, prevents deleting a tag in use | models |
| `services/tasks.py` | task CRUD, completion, floating-task queries | models |
| `services/events.py` | event CRUD, move, day/week/month queries | models, tasks |
| `services/templates.py` | template CRUD, **materialize_week** | models, events, tasks |
| `services/rules.py` | rule versioning, resolve-rule-for-date | models |
| `services/analytics.py` | minutes-per-tag, group rollup, deviation, verdict | models, rules |
| `services/reports.py` | build report, invoke narrative, persist | analytics, rules, agent |
| `services/reminders.py` | schedule, mark sent, list due | models, tasks |
| `agent/tools.py` | tool schemas → service calls | services |
| `agent/loop.py` | Claude conversation + tool dispatch | agent/tools |
| `lark/sender.py` | render card, POST to Lark | — |
| `scheduler/jobs.py` | Sunday roll, reminder sweep | templates, reminders, lark |

`analytics.py` is deliberately pure: it takes events and a rule, returns numbers. No I/O,
no LLM. This is the piece most likely to be wrong, so it must be testable in isolation.

---

## 4. Data model

### Tag

Free-form and first-class, so it can carry a color. Users create their own.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | str unique | e.g. `Work`, `Study`, `Fitness` |
| `color` | str | hex, from the palette |
| `icon` | str nullable | emoji or icon key |
| `sort_order` | int | display order |
| `archived` | bool | soft delete |

**Seed tags:** Rest, Work, Study, Commute, Kids/Family, Chores/Prep, Fitness, Personal.

### Task — the *what*

Durable and named. Has a detail page. Owns many events over time.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | str | e.g. `Morning routine` |
| `tag_ids` | JSON int[] | `tag_ids[0]` is primary → drives color |
| `notes` | text | markdown |
| `status` | enum | `todo` \| `doing` \| `done` \| `archived` |
| `due_date` | date nullable | |
| `est_minutes` | int nullable | |
| `is_floating` | bool | true = "remember to do, no fixed time" |
| `priority` | enum | `low` \| `normal` \| `high` |
| `created_at`, `completed_at` | datetime | |

A **floating task** is a Task with `is_floating=true` and zero Events — this is the
"没有特定安排时间但是要记得做的事情" bucket. It lives in the Tasks page and can carry
Reminders.

### Event — the *when*

One cell on the calendar. Always belongs to a Task.

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `task_id` | FK Task | required |
| `start_at`, `end_at` | datetime | local naive |
| `tag_ids` | JSON int[] | copied from task at creation, then independent |
| `source` | enum | `template` \| `manual` \| `agent` |
| `template_block_id` | FK nullable | provenance for regeneration |
| `notes` | text nullable | instance-specific |

**Task ≠ Event is the central modeling decision.** "Morning routine" is one Task with
~250 Events. Clicking a card opens the Task detail page showing total hours this
week/month, every upcoming occurrence, and notes — not a lone 07:00–08:00 instance.

Creating an Event with a name that has no matching Task auto-creates the Task and links
it, so the "click card → task detail" invariant always holds.

Tags are **copied** to the Event rather than read through the Task, so re-tagging a Task
today does not silently rewrite last year's analytics.

### Template / TemplateBlock

| Template | Type |
|---|---|
| `id`, `name`, `is_active`, `created_at` | |

| TemplateBlock | Type | Notes |
|---|---|---|
| `id`, `template_id` | | |
| `days` | JSON int[] | ISO weekday 1–7; `[1,2,3,4,5]` = 周一–周五 |
| `start_time`, `end_time` | time | `end < start` means it crosses midnight |
| `task_name` | str | resolved to a Task at materialization |
| `tag_ids` | JSON int[] | |
| `sort_order` | int | |

`days` as an array covers both the three-column shape of the source template and future
per-day overrides, without a `day_type` enum that would have to be widened later.

### Rule — versioned, never edited in place

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | str | e.g. `6:3:1 baseline` |
| `groups` | JSON | `[{key, label, ratio, tag_ids[]}]` |
| `tolerance` | float | `0.2` |
| `exclude_tag_ids` | JSON int[] | Rest, Personal |
| `effective_from` | date | |
| `effective_to` | date nullable | null = currently active |
| `note` | text | why this version exists — the feedback record |
| `created_at` | datetime | |

Editing a rule **closes** the current row (`effective_to = today`) and **inserts** a new
one. Nothing is ever updated in place, so every rule the user has ever committed to
remains recoverable with the note explaining why it changed.

A report **snapshots the rule that is active at the moment it is generated**, storing that
`rule_id` permanently. Reviewing February in March therefore judges February against
March's rule — you are always measured against the standard you currently hold yourself
to. Because the snapshot is stored on the Report, a later rule change cannot reach back
and alter a report that already exists.

**Seed rule.** Written below by tag *name* for readability; the seeder resolves each name
to its `Tag.id` and the stored JSON contains integers only.

```json
{
  "name": "6:3:1 baseline",
  "tolerance": 0.2,
  "exclude_tags": ["Rest", "Personal"],
  "groups": [
    {"key": "A", "label": "Work · Study · Commute", "ratio": 6,
     "tags": ["Work", "Study", "Commute"]},
    {"key": "B", "label": "Kids · Chores",          "ratio": 3,
     "tags": ["Kids/Family", "Chores/Prep"]},
    {"key": "C", "label": "Fitness",                "ratio": 1,
     "tags": ["Fitness"]}
  ]
}
```

### Report

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `period_start`, `period_end` | date | month boundaries |
| `rule_id` | FK Rule | the version active at generation time, frozen |
| `metrics` | JSON | full computed payload (below) |
| `narrative` | text | LLM interpretation |
| `created_at` | datetime | |

Reports are on-demand and **append-only**. Re-running a month inserts a *new* Report row
rather than overwriting; the Review page shows the most recent run for a month by default,
with earlier runs listed beneath it. A report is never mutated after creation — there is
no `PATCH /api/reports/{id}`. This is what guarantees that changing a rule leaves every
previously generated report exactly as it was.

### Reminder

| Field | Type | Notes |
|---|---|---|
| `id`, `task_id` | | |
| `remind_at` | datetime | |
| `channel` | enum | `inapp` \| `lark` \| `both` |
| `sent_at`, `dismissed_at` | datetime nullable | |

### AgentMessage

`id, role(user|assistant|tool), content, tool_calls JSON, created_at` — chat history,
so Avery has continuity across sessions.

---

## 5. Rule engine

### Computation

Given all Events in `[period_start, period_end)` and the governing Rule:

1. Sum minutes per tag, using `tag_ids[0]` as the attributing tag.
2. Drop tags in `exclude_tag_ids`.
3. Roll remaining tags into groups via each group's `tag_ids`.
4. Tags matching no group accumulate into an **Unassigned** bucket.

```
total          = Σ minutes(g) over all groups          # Unassigned NOT included
share_actual   = minutes(g) / total
share_target   = ratio(g) / Σ ratios
deviation      = (share_actual − share_target) / share_target
verdict        = pass if |deviation| ≤ tolerance else over | under
```

### Bands for 6:3:1 @ 20%

| Group | Target | Pass band |
|---|---|---|
| A · Work · Study · Commute | 60% | 48 – 72% |
| B · Kids · Chores | 30% | 24 – 36% |
| C · Fitness | 10% | 8 – 12% |

Relative tolerance means small buckets are judged tightly and large ones loosely, which is
the intent: a 2pp miss on Fitness is half the bucket, while 2pp on Work is noise.

### Worked check against the source template

A weekday from the template contributes roughly Work 7h + Study 1.5h + Commute 1.5h = 10h
to A, Kids 4h + Chores 1h = 5h to B, Fitness 1h to C. That is 62 / 31 / **6%**.

A and B pass; **C fails as under**. The engine correctly reports that weekday fitness is
below the committed floor. This is the designed behavior, not a calibration error — the
review exists to surface exactly this.

### Edge cases

| Case | Behavior |
|---|---|
| Period has no events | Report renders "no data", no division |
| A group has zero minutes | `share_actual = 0`, deviation `−1.0`, verdict `under` |
| All events excluded (only Rest) | `total = 0` → "no data" |
| Unassigned > 0 | Warning banner: `Unassigned — 3.5h across 2 tags` |
| Rule changed since last run | The rule active at generation time governs; the report header names the rule version and its date, so two runs of the same month under different rules are distinguishable |
| Event crosses midnight | Minutes split across the two calendar days |
| Overlapping events | Both counted; a warning lists overlaps so the user can fix |

Overlaps are counted rather than deduplicated because deduplication requires guessing
which event is "real", and a visible warning is more honest than a silent choice.

---

## 6. Week materialization

**Sunday 20:00 local**, an APScheduler job materializes the coming Mon–Sun from the active
template.

```
for each day D in target week:
    if D already has any event: skip D          # never overwrite
    for each block B where D.isoweekday in B.days:
        task = find_or_create_task(B.task_name, B.tag_ids)
        create_event(task, D + B.start_time, D + B.end_time,
                     source="template", template_block_id=B.id)
```

**Lazy safety net.** `GET /api/weeks/{iso_week}` materializes on read when *all* hold:
the week is the current or next week, it has zero events, and the active template exists.
A laptop closed on Sunday must not produce a blank Monday.

**Past weeks are never auto-touched.** History is a record, not a projection.

Re-materializing an already-populated week is a no-op — the skip-if-any-event guard makes
the job idempotent, so a missed Sunday followed by a lazy trigger cannot double-create.

---

## 7. Views

### Week — default route

7-column time grid, Google-Calendar-style, 06:00–24:00 with scroll. `‹ › Today` at
top-left. Events are colored blocks positioned by time, drag-to-move (snapping to 15 min),
click → Task detail. A left rail shows the week's group totals against the rule's bands as
three slim bars — the rule is visible continuously, not only at month end.

### Month

Standard month grid. Each day cell carries a thin horizontal stacked bar of that day's tag
proportions plus an event count. Clicking any date opens a side panel with that day's full
schedule. The month view answers "how has the shape of my days drifted?" at a glance.

### Tasks

Three sections: **Scheduled** (has upcoming events), **Floating** (`is_floating`, no
events — the remember-to-do list), **Done**. Each row: name, tag chips, due date, reminder
bell. Overdue rows are tinted rose.

### Task detail

Name, tags, notes, status. Then: total hours this week / this month / all time, a list of
upcoming occurrences, and a list of recent past ones. Reminders managed here.

### Template

Edits the template directly in the 周一–周五 / 周六 / 周日 three-column shape, mirroring the
source layout. Adding a block picks days, times, name, tags. A "Preview next week" button
shows what would be generated without writing.

### Rules

Active rule as a card: group rows with ratio steppers, a tolerance slider, and a tag picker
per group. Saving creates a new version and asks for a `note`. Below, a vertical timeline
of past versions with their notes and date ranges.

### Review

Month picker → **Run review**. Output: a recharts bar per group showing actual share
against the target band, a verdict chip per group, total hours, the Unassigned warning if
any, and Avery's narrative with a suggested rule adjustment. Reports persist and are
listed by month.

### Avery — agent drawer

A right-side drawer reachable from every page, with chat history. Tool calls render as
compact inline chips ("created 1 event") so actions are auditable rather than opaque.

---

## 8. Agent

`POST /api/agent/chat` runs a Claude tool-calling loop, streaming over SSE.

**Tools** (each a direct call into `services/`):

```
list_events        create_event      update_event      delete_event      move_event
list_tasks         create_task       update_task       complete_task     set_reminder
get_template       upsert_template_block                materialize_week
list_rules         create_rule_version                  evaluate_period
run_monthly_review
```

Representative interactions:

| User says | Agent does |
|---|---|
| "Add a dentist appointment Wednesday 3pm, 1 hour" | `create_task` + `create_event` |
| "Skip the gym this week, put study there instead" | `list_events` → `update_event` ×5 |
| "How am I doing against my rule this month?" | `evaluate_period` |
| "Remind me to renew the passport" | `create_task(is_floating)` + `set_reminder` |
| "Loosen fitness to 15%" | `create_rule_version` with a note |

The agent is also the narrative writer for reports: `reports.py` calls the same model with
the computed metrics and asks for interpretation. Narrative generation never computes
numbers — it receives them.

**Failure handling:** a tool error is returned to the model as a tool result so it can
correct itself; after two failed attempts on the same tool the loop stops and reports the
error rather than looping. Destructive tools (`delete_event`, `create_rule_version`) echo
what they will do and require the user's confirmation turn before executing.

---

## 9. Notifications

`lark/sender.py` posts interactive cards to a Lark bot, configured via
`LARK_APP_ID` / `LARK_APP_SECRET` / `LARK_CHAT_ID` in `.env`. Following the pattern in
`assistant/app/lark/`.

Two scheduled jobs:

- **Daily digest, 07:00** — today's schedule plus floating tasks that are due or overdue.
- **Reminder sweep, every 15 min** — sends Reminders whose `remind_at` has passed and
  `sent_at` is null, then stamps `sent_at`.

If Lark credentials are absent the sender no-ops with a log line; in-app reminders still
work. The app must be fully usable before Lark is configured.

---

## 10. API

REST, all under `/api`, full CRUD on every object:

```
GET    POST                    /api/tags          /api/tags/{id}        PATCH DELETE
GET    POST                    /api/tasks         /api/tasks/{id}       PATCH DELETE
GET    POST                    /api/events        /api/events/{id}      PATCH DELETE
GET    POST                    /api/templates     /api/templates/{id}   PATCH DELETE
GET    POST                    /api/templates/{id}/blocks
                               /api/template-blocks/{id}                PATCH DELETE
GET    POST                    /api/rules         /api/rules/{id}       PATCH DELETE
GET    POST                    /api/reports       /api/reports/{id}           DELETE
GET    POST                    /api/reminders     /api/reminders/{id}   PATCH DELETE

GET    /api/weeks/{iso_week}                 week payload, lazily materializes
POST   /api/weeks/{iso_week}/materialize     explicit regeneration
GET    /api/months/{yyyy-mm}                 month payload with per-day tag rollups
POST   /api/analytics/evaluate               {start, end, rule_id?} → metrics
POST   /api/reports/run                      {yyyy-mm} → Report with narrative
POST   /api/agent/chat                       SSE stream
```

FastAPI's generated OpenAPI schema at `/docs` doubles as the agent's tool reference.

---

## 11. Theme — 春山景别

```css
--bg:        #F3F1E7;   --surface:   #FBFAF4;   --ink:      #0B0505;
--ink-muted: #6B6560;   --line:      #E3E0D2;
--pale:      #DEDECF;   --blush:     #E7C8C8;   --sage:     #BDBD9B;
--rose:      #DA96A4;   --teal:      #8FA8A2;   --clay:     #C9A88F;
```

Five hexes are taken from the source palette; `teal` is sampled from its top swatch and
`clay` added as a warm neutral, because six tag colors is the minimum the seeded tag set
requires. Event blocks use tag color at ~22% opacity with a solid 3px left border in the
full color — enough separation to scan a week at a glance without the grid turning loud.
Rounded 12px corners, generous whitespace, one serif display face for headings against a
neutral sans for data.

---

## 12. Testing

`pytest` with `aiosqlite`, focused where correctness is load-bearing:

| Area | Cases |
|---|---|
| `analytics` | happy path, empty period, zero-minute group, all-excluded, unassigned tags, overnight split, overlaps |
| `rules` | version creation closes prior row, active-rule lookup returns newest open row, no rule is ever mutated in place |
| `reports` | generation snapshots the active `rule_id`, re-running appends rather than overwrites, changing a rule leaves existing reports byte-identical |
| `templates` | materializes correct days, skips populated days, idempotent re-run, `days` array respected |
| `events` | CRUD, move preserves duration, cross-midnight storage |
| `reminders` | due-sweep selects correctly, marks sent once |

The analytics suite is written first — it is pure and it is the part most likely to be
subtly wrong.

Frontend testing is limited to a smoke test that each route renders. Heavy component tests
are not worth their maintenance cost at this scale.

---

## 13. Build order

1. Scaffold, config, database, Alembic, seed tags + seed rule
2. Models and schemas
3. `services/` + REST routers + tests, object by object
4. `analytics` + `rules` versioning + tests
5. `templates.materialize_week` + scheduler + tests
6. Theme, shell, Week view
7. Month, Tasks, Task detail
8. Template editor, Rules editor
9. Review page + report generation
10. Agent tools, loop, chat drawer
11. Lark sender + digest and reminder jobs

Each step is independently runnable — the app is usable from step 6 onward and gains
capability rather than waiting on a big-bang integration.

---

## 14. Open risks

- **SQLite + APScheduler in one process** is fine for one user; it would need Postgres and
  a separate worker if this ever became multi-user. Accepted.
- **Naive local datetimes** break if the user travels across timezones. Accepted; noted so
  the fix is a known migration rather than a surprise.
- **Tag-based grouping lets a tag belong to no group**, silently shrinking the denominator.
  Mitigated by the explicit Unassigned warning rather than by forbidding it.
