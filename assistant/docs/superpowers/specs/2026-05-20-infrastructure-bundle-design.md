# Infrastructure Bundle Design

**Date:** 2026-05-20
**Status:** Approved (pending user spec review)
**Author:** brainstormed with Claude

## Goal

Refactor the personal-assistant project so all user interaction flows through a single conversational entry point backed by a structured `think → act → react` pipeline. This spec bundles five tightly coupled infrastructure changes that must land together: a Conversation Orchestrator, an LLM router, a persona module, an event log, and a DB cleanup.

These are the bones the rest of the product (proactive agent, daily summaries, memory refinement, coach features) will build on. The DB is currently empty so schema changes carry no migration cost.

## Scope

### In scope

- Single conversational API entry: `POST /api/conversation`
- Conversation orchestrator with `think → act → react` pipeline (2 LLM calls + deterministic action execution)
- LLM router via LiteLLM with task-type-to-model mapping
- Persona module (markdown system prompt applied at REACT)
- `events` table + atomic write contract (every state change emits an event)
- DB cleanup: drop unused tables, add task↔habit FK, formalize `users.preferences` jsonb structure for three-tier memory
- Delete `app/dialogue/` state machine; replace with declarative flow config + LLM-driven asking
- Existing REST endpoints (tasks/goals/habits/plans) reduced to GET-only for frontend display

### Out of scope (deferred to later specs)

- Agent-initiated dialogue (proactive workers, cron jobs)
- Morning/evening reminders & summaries
- Task reminder workflows ("did you finish?" check-ins)
- Daily summary using Opus reasoning model
- Deep Lark calendar/message connector wiring to orchestrator
- Memory consolidation, deduplication, confidence decay
- Vector search over episodic memory
- Coach-mode features

## Constraints / Principles

- **Keep it simple.** Avoid over-engineering. Three similar lines beats a premature abstraction.
- **Single entry point.** All mutations go through `/api/conversation`. Frontend never POSTs to entity endpoints.
- **Pipeline is fixed.** Every turn runs `think → (maybe) act → (maybe) react`. THINK decides if ACT or REACT happens.
- **Events are the source of truth log.** Every DB mutation MUST have a corresponding event in the same transaction.
- **Memory is observable.** All three tiers live in inspectable storage (`users.preferences` jsonb + `events` table).

## Architecture

```
                ┌──────────────────────────────────┐
   User msg ──▶ │  POST /api/conversation          │
                └────────────┬─────────────────────┘
                             │
              [future: agent worker also feeds here]
                             │
                             ▼
   ┌──────────────────────────────────────────────────────┐
   │  load_context()                                       │
   │   - last 10 conversation turns                        │
   │   - users.preferences (profile + procedural)          │
   │   - active dialogue_session (if any flow in progress) │
   │   - up to 5 open tasks                                │
   └────────────────────┬─────────────────────────────────┘
                        ▼
   ┌──────────────────────────────────────────────────────┐
   │  THINK + PLAN   ←  LLM #1 (Haiku 4.5)                 │
   │  output: {                                            │
   │    intent: "...",                                     │
   │    actions: [ {type, params}, ... ],                  │
   │    should_reply: bool,                                │
   │    reply_complexity: "low" | "high",                  │
   │    reply_hint: "...",                                 │
   │    reasoning: "..."                                   │
   │  }                                                    │
   └───────┬──────────────────────────────────────────────┘
           │
           ├─ actions non-empty? ──▶ execute_actions() + emit events (atomic)
           │
           └─ should_reply? ──▶ yes: REACT (LLM #2, Sonnet 4.6,
                              │         upgraded to Opus 4.7 if complexity=="high")
                              └─ no:  response.reply = null (still 200 OK)
```

## Component 1: Conversation Orchestrator

### Module layout

```
app/orchestrator/
  conversation.py     # ConversationOrchestrator class (entry)
  context.py          # load_context()
  think.py            # THINK+PLAN LLM call + JSON parsing
  act.py              # ActionExecutor + atomic event emission
  react.py            # REACT LLM call
  actions.py          # Action types (pydantic) + dispatch table
  flows.py            # Declarative flow definitions (onboarding etc.)
  prompts/
    think.md          # THINK+PLAN system prompt
    react.md          # REACT system prompt (persona placeholder)
```

### load_context contract

```python
@dataclass
class Context:
    user_id: int
    user_name: str
    profile: dict                 # users.preferences.profile (semantic)
    procedural_patterns: list     # users.preferences.procedural
    active_flow: str | None       # from dialogue_sessions
    flow_filled_fields: dict      # fields already collected
    flow_missing_fields: list     # fields still needed
    recent_turns: list[dict]      # last 10 messages
    open_tasks: list[dict]        # up to 5 in-progress tasks
```

Budget: ~1.5-2k tokens. Capped via truncation, not LLM-side compression for MVP.

### THINK output schema

```json
{
  "intent": "one-line description of what user is doing",
  "actions": [
    {"type": "create_task", "params": {"title": "...", "deadline": "..."}},
    {"type": "update_profile", "params": {"path": "diet", "value": "vegetarian"}},
    {"type": "record_pattern", "params": {"pattern": "...", "confidence": 0.8}}
  ],
  "should_reply": true,
  "reply_complexity": "low",
  "reply_hint": "tone should be reassuring",
  "reasoning": "internal trace for debugging"
}
```

`reply_complexity=="high"` triggers REACT model upgrade Sonnet → Opus.

### Action types (MVP)

| Action | DB effect | Event emitted |
|---|---|---|
| `create_task` | INSERT tasks | `task_created` |
| `update_task` | UPDATE tasks | `task_updated` |
| `complete_task` | UPDATE tasks set status='done' | `task_completed` |
| `delete_task` | DELETE tasks | `task_deleted` |
| `create_goal` | INSERT goals | `goal_set` |
| `update_goal` | UPDATE goals | `goal_updated` |
| `add_habit` | INSERT habits | `habit_added` |
| `complete_habit` | (no DB row — just event) | `habit_completed` |
| `update_profile` | UPDATE users.preferences.profile.{path} | `profile_updated` |
| `record_pattern` | APPEND users.preferences.procedural | `pattern_recorded` |
| `record_feedback` | (no DB row — just event) | `feedback_recorded` |
| `start_flow` | INSERT dialogue_sessions | `flow_started` |

Action params validated by pydantic models in `app/orchestrator/actions.py`.

### Declarative flows replacing dialogue state machine

The existing `app/dialogue/` (QuestionNode tree, DialogueState, DialogueFlow) is deleted. Multi-turn flows like onboarding are expressed as a flat field list:

```python
# app/orchestrator/flows.py
ONBOARDING = FlowDefinition(
    name="onboarding",
    required_fields=[
        FieldDef("wake_up", type="time", description="wake-up time"),
        FieldDef("work_start", type="time", description="work-start time"),
        FieldDef("peak_hours", type="time_range", description="deep-work hours"),
        FieldDef("work_end", type="time", description="work-end time"),
        FieldDef("sleep_time", type="time", description="bedtime"),
        FieldDef("daily_habits", type="text", description="daily routines"),
        FieldDef("yearly_goals", type="text", description="goals this year"),
    ],
)
```

THINK prompt receives `active_flow + filled + missing`; LLM picks which missing field to ask about and how to phrase it naturally. Field extraction also happens LLM-side, no regex extractors.

`dialogue_sessions` table is retained but only stores `{flow_name, status}` — field-by-field progress is reconstructed from `users.preferences` (which fields are filled).

### Three-tier memory iteration

```
load_context (reads memory)
      │
      ▼
THINK (decides whether to update memory)
      │
      ▼
ACT executes update_profile / record_pattern
      │
      ▼
events table records the memory write itself
      │
      └─── next turn's load_context sees updated memory
```

- Semantic: `users.preferences.profile` (key→value)
- Procedural: `users.preferences.procedural` (list of `{pattern, confidence, learned_at}`)
- Episodic: `events` table (automatic by-product of every action)

Pattern refinement / deduplication is deferred.

### Error handling

- THINK JSON parse failure → log + fallback reply ("I didn't quite catch that, try again?")
- Any action failure → entire transaction rolled back; `actions_completed` array shows the failed action; REACT generates user-facing apology
- REACT failure → fall back to a templated acknowledgement

## Component 2: LLM Router (LiteLLM)

### Module layout

```
app/llm/
  router.py     # LLMRouter (thin litellm wrapper)
  config.py     # task_type -> model mapping
```

`app/services/llm.py` is deleted.

### Task type mapping

| Task type | Default model | Env override |
|---|---|---|
| `think` | `claude-haiku-4-5-20251001` | `PA_LLM_THINK_MODEL` |
| `react` | `claude-sonnet-4-6` | `PA_LLM_REACT_MODEL` |
| `reasoning` | `claude-opus-4-7` | `PA_LLM_REASONING_MODEL` |

Dynamic REACT upgrade: when THINK output sets `reply_complexity=="high"`, REACT call resolves to `reasoning` model instead of `react`.

### Router API

```python
class LLMRouter:
    async def complete(
        self,
        task_type: Literal["think", "react", "reasoning"],
        messages: list[dict],
        response_format: dict | None = None,
        max_tokens: int = 1500,
    ) -> str: ...

    async def complete_json(
        self, task_type, messages, schema: dict
    ) -> dict:
        """JSON-mode call; parses and validates against schema."""
```

### Prompt caching

THINK's stable system prompt (capability list + JSON schema, ~800 tokens) is marked with `cache_control` per Anthropic API. Saves ~90% of those input tokens. Enable from day 1.

### Streaming / tool calling

Both deferred. MVP uses synchronous JSON output. Tool calling is a possible future migration but not needed yet.

### Retry / fallback

Rely on LiteLLM built-in retries. No custom circuit breaker for MVP.

## Component 3: Persona Module

```
app/persona.py        # PERSONA_REACT constant + load_persona(user_name) helper
```

Persona content (initial draft, will be edited as we learn what works):

```
You are {user_name}'s personal assistant.

Personality:
- Altruistic: you exist for the user, not for yourself. Always put their goals and wellbeing first.
- Reliable: you complete what you commit to, or honestly say you can't. Never bullshit.
- Lighthearted: chat like a friend, can take and make jokes, but never oily.
- With boundaries: you're not a yes-man. Gently but firmly call out bad ideas or harmful patterns.
- Concise: 3 sentences over 5. No filler.

Style:
- Reply in whatever language the user used.
- Default to short replies (1-2 sentences). Expand only when explicitly asked.
- Don't lecture. Give advice only when invited.
```

Applied only at REACT. THINK uses a separate, role-neutral system prompt focused on structured output.

Coach-mode persona additions deferred to a later spec.

## Component 4: Event Log

### Schema

```python
class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("conversations.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(50), index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(20))
    entity_id: Mapped[Optional[int]] = mapped_column()
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), index=True
    )

# composite index for entity history queries
Index("ix_events_entity", "entity_type", "entity_id")
```

### Event types (MVP, 13 total)

```
task_created    task_updated    task_completed    task_deleted
goal_set        goal_updated
habit_added     habit_completed
profile_updated pattern_recorded
feedback_recorded
flow_started    flow_completed
```

### Payload conventions

- `*_created`: full entity snapshot
- `*_updated`: `{ "before": {...}, "after": {...} }` with only changed fields
- `*_completed` / `*_deleted`: `{}` or `{ "reason": "..." }`
- `profile_updated`: `{ "path": "diet", "before": null, "after": "vegetarian" }`
- `pattern_recorded`: `{ "pattern": "...", "confidence": 0.8 }`
- `feedback_recorded`: `{ "sentiment": "negative", "content": "you're too pushy" }`
- `flow_*`: `{ "flow_name": "onboarding" }`

### Write contract

Actions and their events MUST be committed atomically:

```python
async def execute_actions(actions, ctx, session):
    async with session.begin_nested():
        for action in actions:
            result = await dispatch(action, ctx, session)
            event = build_event(action, result, ctx)
            session.add(event)
    return results
```

Failure aborts the whole batch. Events table never has an entry whose DB change was rolled back.

### Linking events to conversations

`conversation_id` references the **user message** row in `conversations` (not the assistant reply). This lets us query "what did the user say that caused this state change."

## Component 5: DB Cleanup

### New tables

- `events`

### Modified tables

| Table | Change |
|---|---|
| `tasks` | Add `habit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("habits.id"))` |
| `time_slots` | Add `date` column; `daily_plan_id` becomes nullable then dropped in this migration |

### Dropped tables

- `daily_plans` — collapsed into `time_slots` (date column suffices)
- `habit_records` — replaced by `habit_completed` events
- `time_entries` — MVP doesn't track actual time spent
- `meeting_notes` — out of MVP scope

### users.preferences jsonb structure (convention, not enforced at DB layer)

This jsonb field is what the original requirements call "buyer_profile". Instead of a separate table, all user profile/preference/pattern data lives here under three keys (`profile`, `procedural`, `onboarding_status`).


```json
{
  "profile": {
    "name": "Yuzhu",
    "diet": "vegetarian",
    "timezone": "Asia/Shanghai",
    "wake_up": "07:00",
    "work_start": "09:00",
    "peak_hours_start": "09:00",
    "peak_hours_end": "12:00",
    "work_end": "18:00",
    "sleep_time": "23:00",
    "reminder_minutes_before": 15,
    "weekend_plans": false
  },
  "procedural": [
    { "pattern": "...", "confidence": 0.8, "learned_at": "2026-05-20T..." }
  ],
  "onboarding_status": "pending" | "in_progress" | "completed"
}
```

A Pydantic model in `app/schemas/preferences.py` provides typed access. DB layer remains flexible jsonb.

### Migration

Single new Alembic revision `xxxx_infra_bundle.py` performing all of the above. Existing `c05044bcb82c` initial schema is the base.

## Routers

```
app/routers/
  conversation.py    # NEW: POST /api/conversation (only mutation entry)
  chat.py            # DELETED
  tasks.py           # GET only
  goals.py           # GET only
  habits.py          # GET only
  plans.py           # GET only
  meeting_notes.py   # DELETED
  lark_webhook.py    # UNCHANGED (rewired in next spec)
  ingestion.py       # UNCHANGED
  reports.py         # UNCHANGED
  users.py           # UNCHANGED
```

`POST /api/conversation`:

```python
class ConversationRequest(BaseModel):
    user_id: int
    message: str

class ConversationResponse(BaseModel):
    reply: str | None      # None when should_reply=false
    actions_taken: list[str]   # ["task_created", ...]; useful for UI hints
```

Frontend reads via the GET endpoints; writes only via `/api/conversation`.

## Final code organization

```
app/
├── main.py                       # router wiring
├── config.py                     # +PA_LLM_*_MODEL env vars
├── database.py
├── persona.py                    # NEW
│
├── orchestrator/                 # NEW (top-level)
│   ├── conversation.py
│   ├── context.py
│   ├── think.py
│   ├── act.py
│   ├── react.py
│   ├── actions.py
│   ├── flows.py
│   └── prompts/{think.md, react.md}
│
├── llm/                          # NEW
│   ├── router.py
│   └── config.py
│
├── models/
│   ├── user.py
│   ├── conversation.py
│   ├── task.py                   # + habit_id FK
│   ├── goal.py
│   ├── habit.py
│   ├── reminder.py
│   ├── report.py
│   ├── dialogue_session.py       # kept; usage simplified
│   ├── event.py                  # NEW
│   ├── time_slot.py              # absorbed daily_plan fields
│   ├── time_entry.py             # DELETED
│   ├── plan.py                   # DELETED
│   └── meeting_note.py           # DELETED
│
├── schemas/
│   └── preferences.py            # NEW
│
├── repositories/                 # untouched
│
├── services/
│   ├── llm.py                    # DELETED
│   ├── reports.py                # kept
│   └── meeting_notes.py          # DELETED
│
├── engines/
│   ├── conversation.py           # DELETED
│   ├── task_extractor.py         # DELETED
│   ├── insight.py                # kept (consumed by next spec)
│   └── scheduler.py              # kept; not invoked by orchestrator in this spec (wired in next spec)
│
├── dialogue/                     # DIRECTORY DELETED
│
├── routers/                      # see Routers section above
└── connectors/                   # untouched
```

## Testing strategy (MVP)

- **Unit**: ActionExecutor + each action type with mocked session, no LLM
- **Integration**: orchestrator end-to-end against SQLite test DB, LLM calls use recorded fixtures or skip when `ANTHROPIC_API_KEY` absent
- **Happy path E2E**: new user → walk through 7-field onboarding → create a task → complete it → assert events table has 9-10 expected events

Detailed test plan deferred to writing-plans phase.

## Implementation order (for writing-plans)

1. Alembic migration (DB schema change)
2. `app/llm/` module
3. `app/persona.py`
4. `app/models/event.py` + minimal test
5. `app/orchestrator/` skeleton, action types, atomic ACT
6. THINK / REACT prompts (happy path)
7. `app/routers/conversation.py` entry
8. End-to-end smoke: start service, send "create a task", verify events table
9. Delete obsolete code (`dialogue/`, `chat.py`, etc.)
10. Reduce CRUD routers to GET-only

Each step is independently testable; mid-stream rollback is cheap.

## Roadmap

| Spec | Topic | Depends on |
|---|---|---|
| 1 (this) | Infrastructure bundle | — |
| 2 | Proactive agent (cron workers, task reminders, check-ins, lark webhook deep wiring) | 1 |
| 3 | Daily summary with Opus reasoning | 1, 2 |
| 4 | Memory refinement (consolidation, vector search) | 1, 3 |
| 5 | Coach mode / insight features | 1, 3, 4 |
