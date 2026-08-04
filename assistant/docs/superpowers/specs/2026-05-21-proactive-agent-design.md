# Proactive Agent Design

**Date:** 2026-05-21
**Status:** Approved (pending user spec review)
**Depends on:** Spec 1 — Infrastructure Bundle (`2026-05-20-infrastructure-bundle-design.md`)

## Goal

Add proactive behavior to the assistant: it kicks off onboarding when a user first messages, runs scheduled morning briefs and evening recaps, sends task reminders with check-ins, and communicates over Lark in both directions. All proactive paths reuse the Spec 1 `ConversationOrchestrator` so persona, event log, and memory writes stay unified.

## Scope

### In scope

- APScheduler-based worker running inside the uvicorn process
- Real Lark client wired in (`AsyncMock` removed from `lark_webhook`)
- `LarkBot.handle_message` routes inbound messages to `ConversationOrchestrator.handle`
- New-user detection in the webhook → proactive welcome + onboarding kickoff
- Proactive outbound pipeline `Orchestrator.send_proactive(user_id, trigger, complexity)`
- Task auto-reminders + 3-step check-in state machine (15 min, 2 h, piggy-backed)
- Morning brief at `wake_up + 30 min` (Sonnet, scheduler runs first to plan tasks)
- Evening recap at `sleep_time − 1 h` (Opus, structured: facts → observation → 1-2 suggestions → specific praise)
- Onboarding flow extended: `user_expectations` field + structured `create_goal` / `add_habit` actions
- `load_context` extended to include active goals + habits
- Web frontend continues to display data only — no chat over web in this spec

### Out of scope (later specs)

- Memory consolidation, deduplication, vector search
- Weekly summary
- Coach-mode insights
- Lark calendar deep integration (slot conflict detection, meeting prep)
- Multi-process worker deployment (Celery, Redis, etc.)
- Streaming / typing indicators in Lark

## Constraints / Principles

- **Same uvicorn process.** APScheduler runs as `AsyncIOScheduler` in-process. Single-user MVP doesn't need queue infrastructure.
- **One pipeline.** Outbound proactive uses the same orchestrator code base as inbound. Hybrid pipeline depth: task reminders are REACT-only, onboarding welcome + morning brief + evening recap use full THINK+ACT+REACT.
- **Friendly, not robotic.** Reminders go through REACT with persona — never hardcoded templates. Replies always go through THINK so the assistant interprets nuance (didn't start vs in progress vs done-but-forgot-to-say).
- **Idempotent.** Each reminder row has `status` (pending → sent / failed / cancelled / deferred); each daily prompt checks the events table to avoid double-firing.
- **Soft-fail.** LLM failure during a proactive trigger logs a warning and skips that turn. We do not flood the user with retries or apologetic generic templates.

## Architecture

```
                          ┌───────────────────────────────────────────┐
                          │  uvicorn process                          │
                          │                                           │
   inbound (Lark) ──────▶ │  POST /api/lark/webhook  (real client)    │
                          │      ↓                                    │
                          │  LarkBot.handle_message                   │
                          │      ↓                                    │
                          │  detect new user? → send_proactive(Welcome)
                          │  else            → orchestrator.handle()  │
                          │                                           │
                          │  ┌─────────────────────────────────────┐  │
                          │  │ APScheduler (AsyncIOScheduler)      │  │
                          │  │                                     │  │
                          │  │ scan_reminders        every 1 min   │──▶ send_proactive
                          │  │ orchestrate_daily_jobs every 1 hr   │──▶ schedules send_morning_brief / send_evening_recap
                          │  │ send_morning_brief    one-shot      │──▶ send_proactive (low)
                          │  │ send_evening_recap    one-shot      │──▶ send_proactive (high → Opus)
                          │  └─────────────────────────────────────┘  │
                          │      ↓                                    │
                          │  send_proactive() → LarkMessenger.push()  │
                          └───────────────────────────────────────────┘
```

## Component 1: Scheduler Runtime

### Module layout

```
app/scheduler/
  __init__.py          # exports scheduler
  runtime.py           # AsyncIOScheduler instance + start/shutdown helpers
  jobs.py              # job functions (scan_reminders, orchestrate_daily_jobs, send_*)
```

### Job inventory

| Job | Trigger | Behavior |
|---|---|---|
| `scan_reminders` | interval, 1 min | Pulls `reminders` where `status='pending'` and `trigger_time<=now()`, fires each through `send_proactive` |
| `orchestrate_daily_jobs` | cron, every hour at `:00` | For each user, checks if `wake_up+30m` or `sleep_time−1h` falls in this hour (user-timezone aware); if so schedules a one-shot `send_morning_brief` / `send_evening_recap` |
| `send_morning_brief(user_id)` | date (one-shot) | Pre-loads today's tasks/habits/goals, runs scheduler engine to fill `time_slots`, calls `send_proactive` with `MorningBriefTrigger` |
| `send_evening_recap(user_id)` | date (one-shot) | Aggregates today's events + plan vs actual, calls `send_proactive(complexity="high")` (→ Opus) with `EveningRecapTrigger` |

### Startup wiring

`app/main.py`:

```python
@app.on_event("startup")
async def startup_event():
    if settings.enable_scheduler:
        scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown(wait=False)
```

`PA_ENABLE_SCHEDULER=false` for tests.

### Time zone

Each user's `profile.timezone` (defaults to `"UTC"` if absent) is used when computing `wake_up+30m` and `sleep_time−1h`. Implementation uses `zoneinfo`.

### Idempotency

- `scan_reminders` only touches `pending`. Successful send sets `sent`, failure sets `failed` (no retry — manual investigation).
- Daily prompts check `events` table for `morning_brief_sent` / `evening_recap_sent` with `DATE(created_at)=today` and `user_id` matching; skip if already present.

### New event types

```
reminder_fired               # scan_reminders successfully fired one
reminder_failed              # Lark push failure
morning_brief_sent
evening_recap_sent
task_status_unknown          # check-in state machine gave up
```

## Component 2: Lark Integration

### lark_webhook rewrite

```
app/routers/lark_webhook.py
```

Replace `AsyncMock` with real `LarkClient` constructed from `settings.lark_*`. Handler flow on `im.message.receive_v1`:

```
1. parse Lark event → extract lark_user_id, message_text
2. lookup User by lark_user_id
3. if user is None:
       create User with preferences = {profile:{}, procedural:[], onboarding_status:"pending"}
       await orchestrator.send_proactive(user.id, trigger=WelcomeTrigger(initial_message=message_text))
       return ok
4. else:
       await orchestrator.handle(user.id, message_text)
       (the orchestrator response.reply, if any, is pushed via LarkMessenger)
```

`WelcomeTrigger.initial_message` preserves the user's first words so the welcome doesn't ignore what they said.

### app/lark/bot.py

`LarkBot.handle_message` is rewritten from the Spec 1 stub to:

- accept a `ConversationOrchestrator` injection
- delegate to `orchestrator.handle(user_id, text)`
- post the reply back via `LarkClient.send_message` (or a card if rich content emerges later)

### app/services/lark_messenger.py (NEW)

Thin async wrapper around `LarkClient`:

```python
class LarkMessenger:
    def __init__(self, client: LarkClient):
        self.client = client

    async def push(self, lark_user_id: str, text: str) -> None:
        if settings.proactive_dry_run:
            logger.info("DRY RUN push to %s: %s", lark_user_id, text)
            return
        await self.client.send_message(lark_user_id, text)
```

`PA_PROACTIVE_DRY_RUN=true` lets us run scheduler without spamming the user.

## Component 3: Proactive Pipeline

### app/orchestrator/triggers.py (NEW)

Pydantic models for each trigger type. Each carries the data REACT needs.

```python
class WelcomeTrigger(BaseModel):
    type: Literal["welcome"] = "welcome"
    initial_message: Optional[str] = None

class TaskCheckinTrigger(BaseModel):
    type: Literal["task_checkin"] = "task_checkin"
    task_id: int
    attempt: int               # 1, 2, or 3
    task_title: str
    deadline: str
    piggyback_with: Optional["TaskCheckinTrigger"] = None  # for attempt=3

class MorningBriefTrigger(BaseModel):
    type: Literal["morning_brief"] = "morning_brief"
    date: str
    today_plan: list[dict]     # [{time, title, kind, goal_title?, quadrant?}]
    headline_task: Optional[str]
    habits_today: list[dict]
    active_goals_brief: list[dict]

class EveningRecapTrigger(BaseModel):
    type: Literal["evening_recap"] = "evening_recap"
    date: str
    tasks_completed: list[dict]
    tasks_missed: list[dict]
    habits_done: list[dict]
    habits_missed: list[dict]
    goals_touched: list[dict]
    recent_pattern: dict        # aggregate over past 7 days
    user_feedback_today: list[dict]
```

### app/orchestrator/proactive.py (NEW)

```python
async def send_proactive(
    self,
    user_id: int,
    trigger: Trigger,
    complexity: Literal["low", "high"] = "low",
) -> Optional[str]:
    """REACT-only path for outbound system messages.

    - load_context for memory + history (so REACT can be personal)
    - build a synthetic user_content describing the trigger
    - run REACT with complexity (high → reasoning model → Opus)
    - persist assistant message in conversations with role='assistant', intent='proactive:<type>'
    - push via Lark
    - emit a *_sent event
    """
```

`WelcomeTrigger` is the one exception — it needs to emit `start_flow(onboarding)`, so it routes through the full pipeline via a small wrapper that:
- emits the `start_flow` action via ActionExecutor
- then runs REACT with persona to introduce + ask the first question

### Pipeline depth per trigger

| Trigger | THINK | ACT | REACT | Model |
|---|---|---|---|---|
| Welcome | — (hardcoded `start_flow` action) | yes | yes | react (Sonnet) |
| TaskCheckin (1, 2, 3) | — | — | yes | react (Sonnet) |
| MorningBrief | — | — | yes | react (Sonnet) |
| EveningRecap | — | — | yes | **reasoning (Opus)** |

The user's **reply** to any of these goes through normal `orchestrator.handle()` (full pipeline). THINK is responsible for interpreting check-in answers.

### Persona reinforcement

`prompts/react.md` (already exists from Spec 1) gets an addendum per trigger type:

```markdown
If <trigger_payload> is present:
- type=welcome: warm + curious, introduce briefly, ask the first onboarding question
- type=task_checkin: gentle, friendly, no pressure — like a friend asking. NEVER say "you should" or "did you forget"
- type=morning_brief: morning energy, list-style ok, mention the headline task once and don't repeat it
- type=evening_recap: structured (facts → observation → 1-2 suggestions → specific praise). Each section 1-2 short sentences. Praise must reference a concrete fact, no generic encouragement.
```

## Component 4: Task Reminders + Check-in State Machine

### Auto-schedule on task creation

`app/orchestrator/act.py` `_create_task`:

```python
async def _create_task(self, user_id, p):
    task = Task(...)
    self.session.add(task)
    await self.session.flush()
    if task.deadline:
        await self._schedule_first_checkin(task)
    return ActionResult(...)

async def _schedule_first_checkin(self, task: Task):
    self.session.add(Reminder(
        user_id=task.user_id,
        trigger_time=task.deadline + timedelta(minutes=15),
        type="task_checkin_1",
        linked_task_id=task.id,
        status="pending",
        message="",
    ))
```

### Reminder.type enum

| type | Cadence |
|---|---|
| `task_checkin_1` | deadline + 15 min |
| `task_checkin_2` | scheduled at end of attempt 1 if user didn't respond within window |
| `task_checkin_3` | piggy-backed — sat in `status='deferred'` waiting for an outbound proactive call |
| `morning_brief` | not persisted in reminders; orchestrate_daily_jobs schedules one-shot |
| `evening_recap` | same |

(`morning_brief` and `evening_recap` rows could be persisted for trace, but adding them only on send (as events) keeps the table clean.)

### State machine

```
deadline T

[task_checkin_1]  fired at T+15m
   ↓
   ↓ wait for user response (window: 2h)
   ↓
   ├── user says "done"          → THINK emits complete_task → task done, cancel future checkins
   ├── user says "in progress"   → schedule task_checkin_2 at +2h, optionally extend deadline
   ├── user says "didn't start"  → THINK suggests reschedule or cancel; user decides
   ├── user says off-topic       → recap normally; the task stays pending; checkin_2 fires anyway
   └── 2h silence                → fire task_checkin_2

[task_checkin_2]  fired (or scheduled to fire) at T+2h15m
   ↓
   ↓ wait 12-24h
   ↓
   ├── user response             → same branches as above
   └── 24h silence               → mark Reminder(status='deferred'), upgrade to task_checkin_3

[task_checkin_3]  becomes "piggy-backed" — its content is appended to the next outbound proactive
   ↓
   ├── piggy ride happens, user replies → branch as above
   └── 24h further silence       → emit event task_status_unknown, set task.status='unknown'
```

### Cancellation

When a `complete_task` action fires for a task that has pending reminders, ActionExecutor cancels them in the same transaction:

```python
UPDATE reminders SET status='cancelled' WHERE linked_task_id=$task AND status='pending';
```

### THINK prompt extension for check-in interpretation

The THINK prompt (`prompts/think.md`) gains a paragraph:

```markdown
If the conversation history shows the assistant recently asked about a specific task ("the assistant pinged about task #N"), and the user's latest message is short or ambiguous ("done", "still on it", "kinda"), interpret it in the context of that task. Emit complete_task for affirmative completion. Emit update_task with extended deadline if the user signals they're still working. Emit nothing (just should_reply) if the user changed topic — the check-in cycle will continue on its own.
```

### Piggy-backing implementation

```python
# inside send_proactive
deferred = await get_deferred_checkins(user_id, max_age_h=24)
if deferred and trigger.type != "task_checkin":
    trigger.piggyback_with = deferred[0]  # one at a time
    # mark that checkin as sent
    ...
```

REACT prompt covers this: "If trigger.piggyback_with is set, weave in one casual line at the end about that older task."

## Component 5: Morning Brief Details

Triggered at user's `wake_up + 30 min` (in user timezone).

### Pre-REACT data assembly

1. **Load today's tasks**: `tasks where user_id=X and status in (pending, in_progress) and DATE(deadline) in (today, NULL)`
2. **Load today's habits**: `habits where user_id=X and active=true` (frequency filter for today)
3. **Load today's calendar events**: optional, depends on lark calendar connector (deferred → empty list this spec)
4. **Run scheduler engine** (`app/engines/scheduler.py` — already exists from Spec 1) to fill `time_slots`:
   - Important / important+urgent tasks → user's peak hours (morning by default)
   - Errand-type (`quadrant=neither` or `urgent` non-important) → afternoon
   - Habits → at `preferred_time` if set
   - **Persist** new `time_slots` rows for today
5. **Pick headline_task**: highest priority + closest deadline
6. **Build `MorningBriefTrigger`** with `today_plan` (sorted by time), `headline_task`, `habits_today`, `active_goals_brief`

### REACT output style

REACT with Sonnet (complexity="low"). Persona-driven, but the prompt addendum keeps it list-style:

> 早 ☀️ 今天 5 件事，最关键是 **写 Q2 报告**。
> 
> 9:00–10:30  写报告（趁脑子清醒）
> 10:30–11:00 晨跑（今日打卡 ✊）
> ...
> 
> 加油，碰到啥说一声。

### Failure modes

- Scheduler engine throws → log + skip today's brief (don't send broken brief)
- LLM fails → skip + log; no fallback template
- Lark push fails → emit `reminder_failed` event with reason

## Component 6: Evening Recap Details

Triggered at user's `sleep_time − 1 h`. Uses **Opus** (via `complexity="high"` → reasoning model).

### Pre-REACT data assembly

1. **Today's events**: `events where user_id=X and DATE(created_at)=today` (chronological)
2. **Completed vs missed**: bucket today's tasks
3. **Habit completions today**: events `habit_completed` for today
4. **Goal progress**: tasks completed today whose `goal_id` is set → group by goal
5. **Recent pattern (7d)**: completion rate average, habit streaks
6. **User feedback today**: events `feedback_recorded`

### REACT prompt extension (in `prompts/react.md`)

```markdown
When <trigger_payload>.type == "evening_recap":

Generate four short paragraphs in this exact order:

1. **Facts** — what got done / what didn't (numbers, names). Do not editorialize.
2. **Observation** — one pattern you noticed today (productivity rhythm, recurring slip, streak holding, etc.). Keep it concrete.
3. **Suggestion** — at most TWO specific, actionable changes for tomorrow. Not generic advice.
4. **Praise** — one sincere callout based on something specific from today. No "you're amazing"; reference a concrete artifact, decision, or moment.

Total under 200 words. If today's data is sparse (user barely engaged), give a short warm note and stop. Empty whitespace beats forced structure.
```

### Cost estimate

Opus 4.7: ~1500 input + 300 output tokens per recap. At current pricing (~$15/M input, $75/M output) ≈ $0.045/day ≈ $1.4/month for one user.

### Failure modes

Same as morning brief. **Important:** if LLM fails, do NOT fall back to a template recap — the recap depends on insight, and template praise is anti-persona.

## Component 7: Onboarding Extensions

### `app/orchestrator/flows.py` — ONBOARDING gains one field

Insert after `daily_habits`, before `yearly_goals`:

```python
FieldDef("user_expectations", "text", "what the user wants the assistant to help with"),
```

### THINK prompt extension for structured goals/habits

`prompts/think.md` addendum:

```markdown
When active_flow == "onboarding" and the user answers the "daily_habits" question:
- emit ONE add_habit action per distinct habit they describe
- ALSO emit update_profile(path="daily_habits", value=<raw text summary>) so the original phrasing is preserved

Similarly, when they answer the "yearly_goals" question:
- emit ONE create_goal action per distinct goal
- ALSO emit update_profile(path="yearly_goals", value=<raw text>)
```

This means a single onboarding turn can write multiple structured records in addition to the profile update. ActionExecutor already handles batches atomically (Spec 1 design).

### Welcome trigger flow

`send_proactive(user_id, trigger=WelcomeTrigger(...))` is a hybrid case — it needs to emit `start_flow(onboarding)` AND a REACT reply. The proactive.py code path:

```python
async def send_proactive(self, user_id, trigger, complexity="low"):
    ctx = await load_context(user_id, session)

    if isinstance(trigger, WelcomeTrigger):
        # short THINK-equivalent: hardcoded action
        executor = ActionExecutor(session)
        await executor.execute_all(user_id, [
            ParsedAction(ActionType.START_FLOW, StartFlowParams(flow_name="onboarding"))
        ], conversation_id=None)
        hint = "warmly introduce yourself, ask first onboarding question"
    else:
        hint = trigger_hint(trigger)

    reply = await react(ctx, message=trigger.synthetic_message(), action_results=[], hint=hint, complexity=complexity, llm=llm)
    await persist_assistant_msg(reply, intent=f"proactive:{trigger.type}")
    await lark_messenger.push(user.lark_user_id, reply)
    await emit_event(f"{trigger.type}_sent", user_id, payload={"trigger": trigger.model_dump()})
    return reply
```

(Welcome's `synthetic_message` could be `"[SYSTEM] new user just joined, initial words: '<user msg>'"` — REACT sees it as context, not as the user speaking.)

## Component 8: load_context Extension

`app/orchestrator/context.py` adds two fields to `Context`:

```python
@dataclass
class Context:
    ...
    active_goals: list[dict]      # active goals (id, title, target_date, progress hint)
    active_habits: list[dict]     # active habits (id, title, frequency, preferred_time)
```

Loaded via:

```python
goals_q = select(Goal).where(Goal.user_id == user_id, Goal.status == "active").limit(10)
habits_q = select(Habit).where(Habit.user_id == user_id, Habit.active == True).limit(15)
```

Limits keep token budget bounded. THINK and REACT prompts will see these blocks automatically.

## File organization

### Added

```
app/scheduler/
├── __init__.py
├── runtime.py
└── jobs.py

app/orchestrator/
├── proactive.py
└── triggers.py

app/services/
└── lark_messenger.py
```

### Modified

| Path | Change |
|---|---|
| `pyproject.toml` | + `apscheduler>=3.10` |
| `app/config.py` | + `enable_scheduler: bool = True`, + `proactive_dry_run: bool = False` |
| `app/main.py` | startup/shutdown hooks for scheduler |
| `app/routers/lark_webhook.py` | replace AsyncMock with real LarkClient; new-user detection branch |
| `app/lark/bot.py` | rewrite `handle_message` to delegate to ConversationOrchestrator |
| `app/orchestrator/context.py` | + active_goals, active_habits loading |
| `app/orchestrator/act.py` | `_create_task` schedules `task_checkin_1`; `_complete_task` cancels pending reminders |
| `app/orchestrator/think.py` (prompt) | extensions: onboarding structurization + check-in interpretation |
| `app/orchestrator/flows.py` | + `user_expectations` field in ONBOARDING |
| `app/orchestrator/react.py` (prompt) | per-trigger style guidance + evening_recap structure |
| `app/engines/scheduler.py` | (unchanged code; first real caller is morning brief job) |

### Not touched

- `app/models/` — schemas unchanged from Spec 1; `reminders.type` values are application-level, no DDL needed
- Frontend
- Spec 1 tests (additive only)

## Testing Strategy

- **Unit tests** per job function with mocked LLMRouter + LarkClient. Assertions on DB side effects and trigger payload contents.
- **Integration tests** for `lark_webhook` using mock Lark payloads (new user → welcome, existing user → orchestrator.handle, card action → ignored).
- **State machine tests** for check-in: simulate task with deadline → fire checkin_1 → user response branches → assertions on Reminder rows and task.status.
- **End-to-end smoke**: spin scheduler with very short intervals (e.g. trigger reminder 1 second from now), assert push happens via dry-run logger.
- **Not tested**: real Lark API integration (use fake client); APScheduler's internal timing (trust the library).
- **`PA_PROACTIVE_DRY_RUN=true`** is the global escape hatch — set this in test env to make Lark pushes log-only.

## Implementation Order (for writing-plans)

1. `pyproject.toml` + `app/config.py` env settings
2. `app/scheduler/runtime.py` framework + `main.py` startup hook
3. `app/orchestrator/triggers.py` data classes
4. `app/orchestrator/proactive.py` `send_proactive` skeleton (welcome path first)
5. `app/orchestrator/context.py` load active goals + habits
6. `app/services/lark_messenger.py` wraps real `LarkClient`
7. Rewrite `app/routers/lark_webhook.py` + new-user detection
8. Rewrite `app/lark/bot.py` `handle_message` → orchestrator delegation
9. **End-to-end smoke**: real Lark "hello" message → welcome reply
10. Extend `app/orchestrator/think.py` prompts (onboarding structurization, check-in)
11. Add `user_expectations` to `ONBOARDING`
12. Extend `_create_task` (act.py) to schedule `task_checkin_1`; extend `_complete_task` to cancel reminders
13. `scan_reminders` job + state machine for task_checkin_1 → 2 transitions
14. `orchestrate_daily_jobs` + `send_morning_brief` (calls `app/engines/scheduler.py`)
15. `send_evening_recap` with Opus
16. Check-in state machine complete: 2 → 3 (piggy-back) + unknown terminal
17. Live sanity check (Lark device-side: send messages, observe morning/evening triggers using time-skewed test settings)

## Roadmap (updated)

| Spec | Topic | Depends on |
|---|---|---|
| 1 | Infrastructure bundle | — |
| 2 (this) | Proactive agent + Lark + daily prompts (incl. Opus recap) | 1 |
| 3 (was 4) | Memory refinement (consolidation, vector search) | 1, 2 |
| 4 (was 5) | Coach mode / insight features | 1, 2, 3 |
