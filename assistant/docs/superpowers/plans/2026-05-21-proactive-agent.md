# Proactive Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add proactive behavior on top of Spec 1's orchestrator — APScheduler worker in-process, real Lark two-way, task auto-reminders with 3-step check-in, morning brief (Sonnet) with auto-scheduling, evening recap (Opus, structured), onboarding extensions, new-user welcome.

**Architecture:** APScheduler `AsyncIOScheduler` runs inside the uvicorn process. Outbound proactive triggers go through `Orchestrator.send_proactive(user_id, trigger, complexity)` — a REACT-only fast path with optional inline `ACT` for Welcome's `start_flow`. Inbound Lark messages go through the existing `Orchestrator.handle`. Reminders are persisted in the `reminders` table; the check-in state machine progresses by writing/cancelling rows there.

**Tech Stack:** Python 3.10 · FastAPI · SQLAlchemy 2 async (asyncpg / aiosqlite) · APScheduler 3.10+ · Pydantic v2 · LiteLLM · httpx (existing LarkClient) · pytest + pytest-asyncio + httpx · `time-machine` for time-skewed tests

**Spec:** `docs/superpowers/specs/2026-05-21-proactive-agent-design.md`
**Predecessor plan:** `docs/superpowers/plans/2026-05-20-infrastructure-bundle.md`

---

## Pre-flight

- Branch baseline: `feat/infra-bundle` (or whatever branch Spec 1's commits live on). All Spec 1 tasks are green.
- Verify cumulative state: `pytest tests/ -q` should pass.
- A real Lark app must be configured. Required env vars in `.env`:
  - `PA_LARK_APP_ID`
  - `PA_LARK_APP_SECRET`
  - `PA_LARK_VERIFICATION_TOKEN`
  - `PA_LARK_ENCRYPT_KEY` (optional; only if Lark is configured to encrypt)
- Decide branch strategy. If you want isolation from `feat/infra-bundle`:
  ```bash
  git checkout -b feat/proactive-agent
  ```
  Otherwise stay on `feat/infra-bundle` and stack commits.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `app/scheduler/__init__.py` | exports `scheduler` instance + `start_scheduler` / `shutdown_scheduler` |
| `app/scheduler/runtime.py` | `AsyncIOScheduler` instance + lifecycle helpers |
| `app/scheduler/jobs.py` | `scan_reminders`, `orchestrate_daily_jobs`, `send_morning_brief`, `send_evening_recap` |
| `app/orchestrator/triggers.py` | Pydantic models: `WelcomeTrigger`, `TaskCheckinTrigger`, `MorningBriefTrigger`, `EveningRecapTrigger`, plus `Trigger` discriminated union |
| `app/orchestrator/proactive.py` | `send_proactive(orchestrator, user_id, trigger, complexity)` |
| `app/services/lark_messenger.py` | Thin wrapper around `LarkClient`; honors `PA_PROACTIVE_DRY_RUN` |
| `tests/test_scheduler/__init__.py` | empty |
| `tests/test_scheduler/test_jobs.py` | scheduler jobs unit tests |
| `tests/test_orchestrator/test_triggers.py` | trigger model tests |
| `tests/test_orchestrator/test_proactive.py` | send_proactive unit tests |
| `tests/test_services/test_lark_messenger.py` | dry-run + push tests |
| `tests/test_routers/test_lark_webhook_rewire.py` | new-user + dispatch tests |
| `tests/test_e2e_proactive_smoke.py` | end-to-end proactive smoke (task reminder firing) |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | + `apscheduler>=3.10`, + dev: `time-machine>=2.13` |
| `app/config.py` | + `enable_scheduler: bool = True`, + `proactive_dry_run: bool = False` |
| `app/main.py` | startup/shutdown hooks for scheduler |
| `app/routers/lark_webhook.py` | drop `AsyncMock`, real `LarkClient`, new-user detection, dispatch to orchestrator |
| `app/lark/bot.py` | rewrite `handle_message` to delegate to `ConversationOrchestrator` (kept thin) |
| `app/orchestrator/context.py` | add `active_goals` and `active_habits` to `Context`; load them |
| `app/orchestrator/act.py` | `_create_task` auto-schedules `task_checkin_1`; `_complete_task` cancels pending reminders for that task |
| `app/orchestrator/prompts/think.md` | onboarding structurization + check-in interpretation paragraphs |
| `app/orchestrator/prompts/react.md` | per-trigger style guidance + evening_recap structure |
| `app/orchestrator/flows.py` | add `user_expectations` `FieldDef` to `ONBOARDING.required_fields` |
| `app/orchestrator/react.py` | accept `trigger_payload` param + serialize it into user content |

### Not touched

- DB schema (no Alembic migration this spec — reminders table is reused with new `type` values, which are application-level)
- Frontend
- `app/engines/scheduler.py` (consumed unchanged by `send_morning_brief`)

---

## Task 1: Dependencies & Settings

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/config.py`

- [ ] **Step 1.1: Add APScheduler and time-machine to pyproject.toml**

In `pyproject.toml` `dependencies`, append:
```
    "apscheduler>=3.10",
```

In `[project.optional-dependencies] dev`, append:
```
    "time-machine>=2.13",
```

- [ ] **Step 1.2: Install**

```bash
source .venv/bin/activate
pip install "apscheduler>=3.10" "time-machine>=2.13"
```

(Earlier `pip install -e ".[dev]"` is broken because of multiple top-level packages — install pinned deps directly. This was already noted during Spec 1.)

- [ ] **Step 1.3: Extend `app/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://guoyuzhu:guoyuzhu@localhost:5432/my_assistant"
    test_database_url: str = "sqlite+aiosqlite:///./test.db"

    anthropic_api_key: str = ""

    llm_think_model: str = "claude-haiku-4-5-20251001"
    llm_react_model: str = "claude-sonnet-4-6"
    llm_reasoning_model: str = "claude-opus-4-7"

    lark_app_id: str = ""
    lark_app_secret: str = ""
    lark_verification_token: str = ""
    lark_encrypt_key: str = ""

    enable_scheduler: bool = True
    proactive_dry_run: bool = False

    model_config = {"env_prefix": "PA_", "env_file": ".env"}


settings = Settings()
```

- [ ] **Step 1.4: Run full suite to confirm no regression**

```bash
pytest tests/ -q
```

Expected: same green count as before this task.

- [ ] **Step 1.5: Commit**

```bash
git add pyproject.toml app/config.py
git commit -m "feat: add apscheduler dep + enable_scheduler/proactive_dry_run settings"
```

---

## Task 2: Trigger Pydantic Models

**Files:**
- Create: `app/orchestrator/triggers.py`
- Test: `tests/test_orchestrator/test_triggers.py`

- [ ] **Step 2.1: Write failing tests**

Create `tests/test_orchestrator/test_triggers.py`:

```python
import pytest
from pydantic import ValidationError
from app.orchestrator.triggers import (
    WelcomeTrigger,
    TaskCheckinTrigger,
    MorningBriefTrigger,
    EveningRecapTrigger,
    synthetic_message_for,
)


def test_welcome_trigger_default_fields():
    t = WelcomeTrigger()
    assert t.type == "welcome"
    assert t.initial_message is None


def test_welcome_trigger_with_initial():
    t = WelcomeTrigger(initial_message="hi")
    assert t.initial_message == "hi"


def test_task_checkin_required_fields():
    with pytest.raises(ValidationError):
        TaskCheckinTrigger()


def test_task_checkin_full():
    t = TaskCheckinTrigger(
        task_id=1, attempt=1, task_title="write report", deadline="2026-05-21T14:00:00Z"
    )
    assert t.type == "task_checkin"
    assert t.attempt == 1


def test_morning_brief_lists_default_empty():
    t = MorningBriefTrigger(date="2026-05-21")
    assert t.today_plan == []
    assert t.habits_today == []
    assert t.headline_task is None


def test_evening_recap_payload():
    t = EveningRecapTrigger(
        date="2026-05-21",
        tasks_completed=[{"id": 1, "title": "x"}],
        recent_pattern={"avg_completion_rate": 0.7},
    )
    assert t.tasks_completed[0]["id"] == 1


def test_synthetic_message_welcome():
    s = synthetic_message_for(WelcomeTrigger(initial_message="hello"))
    assert "welcome" in s.lower() or "new user" in s.lower()
    assert "hello" in s


def test_synthetic_message_task_checkin():
    t = TaskCheckinTrigger(task_id=42, attempt=2, task_title="email replies", deadline="2026-05-21T10:00:00Z")
    s = synthetic_message_for(t)
    assert "email replies" in s
    assert "attempt 2" in s.lower() or "2nd" in s.lower() or "second" in s.lower()


def test_synthetic_message_morning_brief():
    t = MorningBriefTrigger(date="2026-05-21", headline_task="quarterly review")
    s = synthetic_message_for(t)
    assert "morning" in s.lower()
    assert "quarterly review" in s


def test_synthetic_message_evening_recap():
    t = EveningRecapTrigger(date="2026-05-21")
    s = synthetic_message_for(t)
    assert "evening" in s.lower() or "recap" in s.lower()
```

- [ ] **Step 2.2: Run, expect ImportError**

```bash
pytest tests/test_orchestrator/test_triggers.py -v
```

- [ ] **Step 2.3: Create `app/orchestrator/triggers.py`**

```python
from __future__ import annotations
import json
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class WelcomeTrigger(BaseModel):
    type: Literal["welcome"] = "welcome"
    initial_message: Optional[str] = None


class TaskCheckinTrigger(BaseModel):
    type: Literal["task_checkin"] = "task_checkin"
    task_id: int
    attempt: int  # 1, 2, or 3
    task_title: str
    deadline: str  # ISO-8601 string
    piggyback_with: Optional["TaskCheckinTrigger"] = None


class MorningBriefTrigger(BaseModel):
    type: Literal["morning_brief"] = "morning_brief"
    date: str
    today_plan: list[dict] = Field(default_factory=list)
    headline_task: Optional[str] = None
    habits_today: list[dict] = Field(default_factory=list)
    active_goals_brief: list[dict] = Field(default_factory=list)


class EveningRecapTrigger(BaseModel):
    type: Literal["evening_recap"] = "evening_recap"
    date: str
    tasks_completed: list[dict] = Field(default_factory=list)
    tasks_missed: list[dict] = Field(default_factory=list)
    habits_done: list[dict] = Field(default_factory=list)
    habits_missed: list[dict] = Field(default_factory=list)
    goals_touched: list[dict] = Field(default_factory=list)
    recent_pattern: dict = Field(default_factory=dict)
    user_feedback_today: list[dict] = Field(default_factory=list)


Trigger = Union[WelcomeTrigger, TaskCheckinTrigger, MorningBriefTrigger, EveningRecapTrigger]


def synthetic_message_for(trigger: Trigger) -> str:
    """Produces the [SYSTEM] message that REACT sees as 'user content'.
    The persona/REACT prompt knows to treat these as triggers, not user speech.
    """
    if isinstance(trigger, WelcomeTrigger):
        suffix = f" Their first words: '{trigger.initial_message}'." if trigger.initial_message else ""
        return f"[SYSTEM_TRIGGER:welcome] A new user just joined.{suffix}"
    if isinstance(trigger, TaskCheckinTrigger):
        attempt_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(trigger.attempt, f"attempt {trigger.attempt}")
        piggy = ""
        if trigger.piggyback_with:
            piggy = f" Also gently check on '{trigger.piggyback_with.task_title}' from before."
        return (
            f"[SYSTEM_TRIGGER:task_checkin] {attempt_label} check-in for task "
            f"'{trigger.task_title}' (deadline {trigger.deadline}).{piggy}"
        )
    if isinstance(trigger, MorningBriefTrigger):
        head = f" Headline task: {trigger.headline_task}." if trigger.headline_task else ""
        plan = json.dumps(trigger.today_plan, ensure_ascii=False)
        habits = json.dumps(trigger.habits_today, ensure_ascii=False)
        return (
            f"[SYSTEM_TRIGGER:morning_brief] Date {trigger.date}.{head} "
            f"Today's plan: {plan}. Habits: {habits}."
        )
    if isinstance(trigger, EveningRecapTrigger):
        return (
            f"[SYSTEM_TRIGGER:evening_recap] Date {trigger.date}. "
            f"Payload: {trigger.model_dump_json(exclude={'type', 'date'})}"
        )
    raise ValueError(f"unknown trigger type: {type(trigger)}")
```

- [ ] **Step 2.4: Run, expect PASS**

```bash
pytest tests/test_orchestrator/test_triggers.py -v
```

- [ ] **Step 2.5: Commit**

```bash
git add app/orchestrator/triggers.py tests/test_orchestrator/test_triggers.py
git commit -m "feat: proactive trigger pydantic models + synthetic-message builder"
```

---

## Task 3: REACT Prompt Extensions + `react()` Trigger Payload

**Files:**
- Modify: `app/orchestrator/prompts/react.md`
- Modify: `app/orchestrator/react.py`
- Test: `tests/test_orchestrator/test_react.py` (additive)

- [ ] **Step 3.1: Extend `app/orchestrator/prompts/react.md`**

Append to the existing file (after the existing content):

```markdown

When the user message starts with `[SYSTEM_TRIGGER:<type>]`, you are generating a PROACTIVE message — the user did not just speak. Treat the bracketed payload as your instruction; do not echo it back.

Trigger-specific style:

- **welcome**: Warm + curious. Briefly introduce yourself (1 sentence). If the user's initial words are present, acknowledge them. Then ask the first onboarding question NATURALLY — pick the first missing onboarding field (wake_up). Don't list everything you can do; show, don't tell.
- **task_checkin**: Friendly, like a close friend asking. NEVER say "you should", "did you forget", or anything pressuring. The 1st attempt is curious ("搞定了吗?"). The 2nd is gentler ("还在忙这个吗，要不要换个时间?"). The 3rd attempt rides along with another message — weave it in as a passing question, not standalone.
- **morning_brief**: Short greeting. List today's items by time. Mention the headline task ONCE (don't repeat). Add one encouraging closing line. Plain text, ok to use line breaks. Aim for 4-8 lines total.
- **evening_recap**: Generate exactly four paragraphs in this order — each 1-3 short sentences:
  1. Facts: completed X/Y, habits done. Numbers and names. No editorializing.
  2. Observation: one concrete pattern from today (high-output morning, fragmented afternoon, streak holding, repeated slip). Specific.
  3. Suggestion: at most TWO actionable changes for tomorrow. Not generic advice ("be more focused"). Reference today's data.
  4. Praise: sincere, anchored in something specific from today's artifacts/decisions/moments. No "you're amazing".
  Total under 200 words. If today's data is sparse (user barely engaged the system), output ONLY a short warm note (1-2 sentences) and stop. Don't force structure on empty data.

When `trigger.piggyback_with` is set (only on task_checkin attempt 3 or on any other trigger that carries it), naturally include one casual line referencing the older task — at the end, conversational, no header.
```

- [ ] **Step 3.2: Add a failing test for the trigger payload**

Append to `tests/test_orchestrator/test_react.py`:

```python
async def test_react_uses_trigger_payload_in_user_content():
    router = _FakeRouter("ok")
    from app.orchestrator.react import react
    from app.orchestrator.triggers import MorningBriefTrigger
    await react(
        _ctx(),
        message="[SYSTEM_TRIGGER:morning_brief] ...",
        action_results=[],
        hint=None,
        complexity="low",
        llm=router,
    )
    user_msg = router.calls[0]["messages"][1]["content"]
    assert "SYSTEM_TRIGGER:morning_brief" in user_msg


async def test_react_evening_recap_uses_reasoning_model():
    router = _FakeRouter("recap text")
    from app.orchestrator.react import react
    await react(
        _ctx(),
        message="[SYSTEM_TRIGGER:evening_recap] ...",
        action_results=[],
        hint="four paragraphs",
        complexity="high",
        llm=router,
    )
    assert router.calls[0]["task_type"] == "reasoning"
```

- [ ] **Step 3.3: Run tests, confirm prior react tests still pass**

```bash
pytest tests/test_orchestrator/test_react.py -v
```

The two new tests should already pass since `react()` already forwards `message` into user content and chooses task_type by complexity. If they fail, inspect.

- [ ] **Step 3.4: Commit**

```bash
git add app/orchestrator/prompts/react.md tests/test_orchestrator/test_react.py
git commit -m "feat: react prompt addendum for proactive triggers + tests"
```

---

## Task 4: Proactive Pipeline (`send_proactive`)

**Files:**
- Create: `app/orchestrator/proactive.py`
- Modify: `app/orchestrator/conversation.py` (add `send_proactive` method to `ConversationOrchestrator`)
- Test: `tests/test_orchestrator/test_proactive.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/test_orchestrator/test_proactive.py`:

```python
import pytest
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.user import User
from app.orchestrator.conversation import ConversationOrchestrator
from app.orchestrator.triggers import (
    EveningRecapTrigger,
    MorningBriefTrigger,
    TaskCheckinTrigger,
    WelcomeTrigger,
)


class _Router:
    def __init__(self, react_text="ok"):
        self.react_text = react_text
        self.react_task_types = []
        self.react_messages = []
    async def complete(self, task_type, messages, **kw):
        self.react_task_types.append(task_type)
        self.react_messages.append(messages)
        return self.react_text
    async def complete_json(self, task_type, messages, **kw):
        raise AssertionError("THINK should not be called on proactive path")


async def _make_user(session, lark="proactive_u"):
    u = User(name="A", lark_user_id=lark, preferences={})
    session.add(u)
    await session.commit()
    return u


async def test_send_proactive_welcome_starts_flow_and_persists_assistant_msg(session):
    user = await _make_user(session)
    router = _Router(react_text="Hi! Welcome.")
    orch = ConversationOrchestrator(session=session, llm=router)
    out = await orch.send_proactive(
        user_id=user.id,
        trigger=WelcomeTrigger(initial_message="hello"),
        complexity="low",
    )
    assert out == "Hi! Welcome."
    # dialogue_session created with onboarding active
    sessions = (await session.execute(select(DialogueSession))).scalars().all()
    assert len(sessions) == 1 and sessions[0].flow_type == "onboarding" and sessions[0].status == "active"
    # flow_started event written
    events = (await session.execute(select(Event))).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types and "welcome_sent" in types
    # assistant message persisted with intent 'proactive:welcome'
    convs = (await session.execute(select(Conversation))).scalars().all()
    assistant = [c for c in convs if c.role == "assistant"]
    assert len(assistant) == 1 and assistant[0].intent == "proactive:welcome"


async def test_send_proactive_task_checkin_react_only_no_action(session):
    user = await _make_user(session, lark="proactive_u2")
    router = _Router(react_text="搞定了吗？")
    orch = ConversationOrchestrator(session=session, llm=router)
    trigger = TaskCheckinTrigger(
        task_id=42, attempt=1, task_title="写报告", deadline="2026-05-21T14:00:00Z"
    )
    out = await orch.send_proactive(user_id=user.id, trigger=trigger, complexity="low")
    assert "搞定" in out
    events = (await session.execute(select(Event))).scalars().all()
    types = [e.type for e in events]
    assert "task_checkin_sent" in types
    # No DB-mutating action ran
    sessions = (await session.execute(select(DialogueSession))).scalars().all()
    assert len(sessions) == 0


async def test_send_proactive_morning_brief_uses_react_model(session):
    user = await _make_user(session, lark="proactive_u3")
    router = _Router(react_text="Morning ☀️")
    orch = ConversationOrchestrator(session=session, llm=router)
    trigger = MorningBriefTrigger(date="2026-05-21", headline_task="x")
    await orch.send_proactive(user_id=user.id, trigger=trigger, complexity="low")
    assert router.react_task_types == ["react"]


async def test_send_proactive_evening_recap_uses_reasoning_model(session):
    user = await _make_user(session, lark="proactive_u4")
    router = _Router(react_text="recap...")
    orch = ConversationOrchestrator(session=session, llm=router)
    trigger = EveningRecapTrigger(date="2026-05-21")
    await orch.send_proactive(user_id=user.id, trigger=trigger, complexity="high")
    assert router.react_task_types == ["reasoning"]


async def test_send_proactive_handles_llm_failure_gracefully(session):
    user = await _make_user(session, lark="proactive_u5")

    class _BoomRouter:
        async def complete(self, *a, **kw):
            from app.llm.router import LLMError
            raise LLMError("boom")
        async def complete_json(self, *a, **kw):
            raise AssertionError("not called")

    orch = ConversationOrchestrator(session=session, llm=_BoomRouter())
    out = await orch.send_proactive(
        user_id=user.id, trigger=MorningBriefTrigger(date="2026-05-21"), complexity="low"
    )
    assert out is None
    # No conversation row, no *_sent event
    convs = (await session.execute(select(Conversation))).scalars().all()
    events = (await session.execute(select(Event))).scalars().all()
    assert all(c.role != "assistant" for c in convs)
    assert all(not e.type.endswith("_sent") for e in events)
```

- [ ] **Step 4.2: Run, expect AttributeError on `orch.send_proactive`**

```bash
pytest tests/test_orchestrator/test_proactive.py -v
```

- [ ] **Step 4.3: Create `app/orchestrator/proactive.py`**

```python
from __future__ import annotations
import logging
from typing import Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.router import LLMError, LLMRouter
from app.models.conversation import Conversation
from app.models.event import Event
from app.orchestrator.act import ActionExecutor
from app.orchestrator.actions import ActionType, ParsedAction, StartFlowParams
from app.orchestrator.context import load_context
from app.orchestrator.react import react
from app.orchestrator.triggers import Trigger, WelcomeTrigger, synthetic_message_for

logger = logging.getLogger(__name__)


async def send_proactive_impl(
    session: AsyncSession,
    llm: LLMRouter,
    user_id: int,
    trigger: Trigger,
    complexity: Literal["low", "high"],
) -> Optional[str]:
    """Outbound proactive message. REACT-only path with optional pre-ACT for Welcome.

    Returns the reply text, or None if generation failed (caller logs and skips push).
    """
    ctx = await load_context(user_id, session)

    # Welcome is the one trigger that needs a state mutation (start_flow).
    if isinstance(trigger, WelcomeTrigger):
        executor = ActionExecutor(session)
        await executor.execute_all(
            user_id=user_id,
            actions=[ParsedAction(ActionType.START_FLOW, StartFlowParams(flow_name="onboarding"))],
            conversation_id=None,
        )
        # Refresh ctx so active_flow now reflects onboarding
        ctx = await load_context(user_id, session)
        hint = "warmly introduce yourself, then ask the first onboarding question naturally"
    else:
        hint = _hint_for(trigger)

    synth = synthetic_message_for(trigger)
    try:
        reply = await react(
            ctx=ctx,
            message=synth,
            action_results=[],
            hint=hint,
            complexity=complexity,
            llm=llm,
        )
    except LLMError as e:
        logger.warning("send_proactive REACT failed: %s", e)
        return None

    # Persist assistant message
    session.add(
        Conversation(
            user_id=user_id,
            role="assistant",
            content=reply,
            intent=f"proactive:{trigger.type}",
        )
    )
    # Emit *_sent event for idempotency / audit
    session.add(
        Event(
            user_id=user_id,
            conversation_id=None,
            type=f"{trigger.type}_sent",
            entity_type="proactive",
            entity_id=None,
            payload=trigger.model_dump(),
        )
    )
    await session.commit()
    return reply


def _hint_for(trigger: Trigger) -> str:
    return {
        "task_checkin": "gentle friendly check-in; never pressuring",
        "morning_brief": "short greeting + list-style today's plan + close with encouragement",
        "evening_recap": "four short paragraphs: facts → observation → 1-2 suggestions → specific praise",
    }.get(trigger.type, "")
```

- [ ] **Step 4.4: Add `send_proactive` method to `ConversationOrchestrator`**

Open `app/orchestrator/conversation.py`. Add an import at top:

```python
from app.orchestrator.proactive import send_proactive_impl
from app.orchestrator.triggers import Trigger
```

Add a method inside the `ConversationOrchestrator` class (after `handle`):

```python
    async def send_proactive(
        self,
        user_id: int,
        trigger: Trigger,
        complexity: str = "low",
    ) -> Optional[str]:
        return await send_proactive_impl(
            session=self.session,
            llm=self.llm,
            user_id=user_id,
            trigger=trigger,
            complexity=complexity,  # type: ignore[arg-type]
        )
```

- [ ] **Step 4.5: Update `app/orchestrator/__init__.py`** (no API change, just verify it still imports cleanly)

```bash
python -c "from app.orchestrator import ConversationOrchestrator; print('ok')"
```

- [ ] **Step 4.6: Run, expect PASS**

```bash
pytest tests/test_orchestrator/test_proactive.py -v
```

- [ ] **Step 4.7: Run cumulative suite**

```bash
pytest tests/ -q
```

Expect: no regressions; +5 new passing.

- [ ] **Step 4.8: Commit**

```bash
git add app/orchestrator/proactive.py app/orchestrator/conversation.py tests/test_orchestrator/test_proactive.py
git commit -m "feat: Orchestrator.send_proactive for outbound triggers"
```

---

## Task 5: `load_context` Loads Active Goals + Habits

**Files:**
- Modify: `app/orchestrator/context.py`
- Modify: `tests/test_orchestrator/test_context.py` (additive)

- [ ] **Step 5.1: Add failing tests**

Append to `tests/test_orchestrator/test_context.py`:

```python
from app.models.goal import Goal
from app.models.habit import Habit


async def test_load_context_includes_active_goals(session):
    u = User(name="G", lark_user_id="ctx_g1", preferences={})
    session.add(u)
    await session.commit()
    from datetime import date
    session.add(Goal(
        user_id=u.id, title="run a marathon", target_value=42.0, current_value=0.0,
        unit="km", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), status="active",
    ))
    session.add(Goal(
        user_id=u.id, title="old goal", target_value=1.0, current_value=1.0,
        unit="x", period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), status="completed",
    ))
    await session.commit()
    ctx = await load_context(u.id, session)
    titles = [g["title"] for g in ctx.active_goals]
    assert "run a marathon" in titles
    assert "old goal" not in titles


async def test_load_context_includes_active_habits(session):
    u = User(name="H", lark_user_id="ctx_h1", preferences={})
    session.add(u)
    await session.commit()
    session.add(Habit(user_id=u.id, title="morning run", frequency_type="daily", active=True))
    session.add(Habit(user_id=u.id, title="old habit", frequency_type="daily", active=False))
    await session.commit()
    ctx = await load_context(u.id, session)
    titles = [h["title"] for h in ctx.active_habits]
    assert "morning run" in titles
    assert "old habit" not in titles
```

- [ ] **Step 5.2: Run, expect failure**

```bash
pytest tests/test_orchestrator/test_context.py::test_load_context_includes_active_goals -v
```

- [ ] **Step 5.3: Extend `app/orchestrator/context.py`**

Add to imports:
```python
from app.models.goal import Goal
from app.models.habit import Habit
```

Add fields to `Context`:
```python
@dataclass
class Context:
    user_id: int
    user_name: str
    profile: Profile
    procedural_patterns: list[Pattern]
    onboarding_status: str
    active_flow: Optional[str]
    flow_filled_fields: dict
    flow_missing_fields: list[FieldDef]
    recent_turns: list[dict]
    open_tasks: list[dict]
    active_goals: list[dict]
    active_habits: list[dict]
```

Add new constants near top:
```python
ACTIVE_GOALS_LIMIT = 10
ACTIVE_HABITS_LIMIT = 15
```

Inside `load_context`, just before the final `return Context(...)`, add:
```python
    goals_q = (
        select(Goal)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Goal.id)
        .limit(ACTIVE_GOALS_LIMIT)
    )
    goals_rows = (await session.execute(goals_q)).scalars().all()
    active_goals = [
        {"id": g.id, "title": g.title, "target_value": g.target_value,
         "current_value": g.current_value, "unit": g.unit,
         "period_end": g.period_end.isoformat() if g.period_end else None}
        for g in goals_rows
    ]

    habits_q = (
        select(Habit)
        .where(Habit.user_id == user_id, Habit.active == True)
        .order_by(Habit.id)
        .limit(ACTIVE_HABITS_LIMIT)
    )
    habits_rows = (await session.execute(habits_q)).scalars().all()
    active_habits = [
        {"id": h.id, "title": h.title, "frequency_type": h.frequency_type,
         "frequency_count": h.frequency_count}
        for h in habits_rows
    ]
```

And include them in the final `return Context(...)` call:
```python
        active_goals=active_goals,
        active_habits=active_habits,
```

- [ ] **Step 5.4: Update test_think `_empty_ctx` helper to include new fields**

Open `tests/test_orchestrator/test_think.py`. Inside the `_empty_ctx` helper, add `active_goals=[]` and `active_habits=[]` to the `defaults` dict.

Open `tests/test_orchestrator/test_react.py`. Inside the `_ctx` helper, add `active_goals=[], active_habits=[]`.

Open `tests/test_orchestrator/test_proactive.py` (Task 4 fixture if it uses Context manually — it does not, it uses load_context, so safe).

- [ ] **Step 5.5: Run**

```bash
pytest tests/test_orchestrator/ -q
```

Expect: all green including the 2 new tests.

- [ ] **Step 5.6: Run cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 5.7: Commit**

```bash
git add app/orchestrator/context.py tests/test_orchestrator/
git commit -m "feat: load_context loads active goals and habits"
```

---

## Task 6: Lark Messenger Service

**Files:**
- Create: `app/services/lark_messenger.py`
- Test: `tests/test_services/test_lark_messenger.py`

- [ ] **Step 6.1: Write failing tests**

Create `tests/test_services/test_lark_messenger.py`:

```python
import pytest
from unittest.mock import AsyncMock

from app.lark.client import LarkClient
from app.services.lark_messenger import LarkMessenger


async def test_push_sends_text_via_client(monkeypatch):
    monkeypatch.setattr("app.services.lark_messenger.settings.proactive_dry_run", False)
    client = AsyncMock(spec=LarkClient)
    client.send_text = AsyncMock(return_value={"message_id": "m1"})
    m = LarkMessenger(client)
    await m.push("user_xyz", "hi")
    client.send_text.assert_awaited_once_with("user_xyz", "hi")


async def test_push_dry_run_skips_send(monkeypatch, caplog):
    monkeypatch.setattr("app.services.lark_messenger.settings.proactive_dry_run", True)
    client = AsyncMock(spec=LarkClient)
    m = LarkMessenger(client)
    with caplog.at_level("INFO"):
        await m.push("user_xyz", "hello")
    client.send_text.assert_not_called()
    assert "DRY RUN" in caplog.text or "dry run" in caplog.text


async def test_push_swallows_client_error_and_logs(monkeypatch, caplog):
    monkeypatch.setattr("app.services.lark_messenger.settings.proactive_dry_run", False)
    client = AsyncMock(spec=LarkClient)
    client.send_text = AsyncMock(side_effect=RuntimeError("network"))
    m = LarkMessenger(client)
    with caplog.at_level("WARNING"):
        result = await m.push("user_xyz", "hi")
    assert result is False
    assert "lark push failed" in caplog.text.lower() or "lark" in caplog.text.lower()
```

- [ ] **Step 6.2: Run, expect ImportError**

```bash
pytest tests/test_services/test_lark_messenger.py -v
```

- [ ] **Step 6.3: Create `app/services/lark_messenger.py`**

```python
from __future__ import annotations
import logging

from app.config import settings
from app.lark.client import LarkClient

logger = logging.getLogger(__name__)


class LarkMessenger:
    """Thin async wrapper around LarkClient for proactive pushes."""

    def __init__(self, client: LarkClient):
        self.client = client

    async def push(self, lark_user_id: str, text: str) -> bool:
        if settings.proactive_dry_run:
            logger.info("DRY RUN push to %s: %s", lark_user_id, text)
            return True
        try:
            await self.client.send_text(lark_user_id, text)
            return True
        except Exception as e:
            logger.warning("lark push failed for %s: %s", lark_user_id, e)
            return False
```

- [ ] **Step 6.4: Run, expect PASS**

```bash
pytest tests/test_services/test_lark_messenger.py -v
```

- [ ] **Step 6.5: Commit**

```bash
git add app/services/lark_messenger.py tests/test_services/test_lark_messenger.py
git commit -m "feat: LarkMessenger with dry-run support"
```

---

## Task 7: Rewrite `LarkBot.handle_message`

**Files:**
- Modify: `app/lark/bot.py`

- [ ] **Step 7.1: Inspect current `LarkBot` to preserve `handle_card_action` and helpers**

```bash
cat app/lark/bot.py
```

Note: `handle_card_action`, `build_response_card`, and `_format_context` are still present from Spec 1's stub. We're rewriting `handle_message` only and dropping the now-obsolete `_user_flows` dict and stub error.

- [ ] **Step 7.2: Rewrite `app/lark/bot.py`**

```python
from __future__ import annotations
from typing import Optional, Dict, Any

from app.lark.cards import CardBuilder
from app.lark.client import LarkClient
from app.lark.webhook import LarkEvent


class LarkBot:
    """Thin pass-through: parses LarkEvent and delegates to caller.

    The webhook layer is now responsible for resolving lark_user_id → user_id
    and invoking ConversationOrchestrator. LarkBot's only job is to carry
    LarkClient and provide a few view helpers for card responses.
    """

    def __init__(self, client: LarkClient):
        self.client = client

    async def handle_card_action(self, event: LarkEvent) -> Dict[str, Any]:
        return {"user_id": event.user_id, "action": event.action_value, "handled": True}

    @staticmethod
    def text_card(text: str) -> Optional[Dict[str, Any]]:
        return CardBuilder.question_card(title="Assistant", question=text)
```

All onboarding/dialogue logic moves to the webhook + orchestrator. Card builder retained because future ad-hoc cards may use it.

- [ ] **Step 7.3: Drop any existing `LarkBot.handle_message` tests that exercised the old NotImplementedError**

```bash
grep -nE "handle_message" tests/test_lark/ 2>/dev/null || echo "no references"
```

If any references exist in `tests/test_lark/`, remove those test cases (the old tests were already deleted in Spec 1 cleanup; verify).

- [ ] **Step 7.4: Run tests**

```bash
pytest tests/test_lark/ -v
```

Expect: green. If `card.action.trigger`/url verification/duplicate tests still exist, they should still pass.

- [ ] **Step 7.5: Commit**

```bash
git add app/lark/bot.py
git commit -m "refactor: slim LarkBot — webhook now drives orchestrator directly"
```

---

## Task 8: Rewrite `lark_webhook` Router (Real Client + New-User Detection)

**Files:**
- Modify: `app/routers/lark_webhook.py`
- Test: `tests/test_routers/test_lark_webhook_rewire.py`

- [ ] **Step 8.1: Write failing tests**

Create `tests/test_routers/test_lark_webhook_rewire.py`:

```python
import pytest
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.event import Event
from app.models.user import User


def _msg_payload(open_id: str, text: str):
    return {
        "schema": "2.0",
        "header": {
            "event_id": f"evt_{open_id}_{text[:8]}",
            "event_type": "im.message.receive_v1",
            "token": "test-verify-token",
        },
        "event": {
            "sender": {"sender_id": {"open_id": open_id}},
            "message": {
                "message_id": f"mid_{open_id}",
                "message_type": "text",
                "content": '{"text":"' + text + '"}',
            },
        },
    }


async def test_webhook_new_user_creates_user_and_triggers_welcome(client, session, monkeypatch):
    # Stub the orchestrator so it doesn't hit Anthropic
    class _StubRouter:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            raise AssertionError("THINK should not run on welcome path")
        async def complete(self, task_type, messages, **kw):
            return "Hi! What time do you usually wake up?"
    monkeypatch.setattr("app.routers.lark_webhook.LLMRouter", _StubRouter)
    # Stub Lark push — no-op
    monkeypatch.setattr("app.routers.lark_webhook.settings.proactive_dry_run", True)

    payload = _msg_payload("open_xxx_new", "hello")
    resp = await client.post("/api/lark/webhook", json=payload)
    assert resp.status_code == 200

    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1 and users[0].lark_user_id == "open_xxx_new"
    flows = (await session.execute(select(DialogueSession))).scalars().all()
    assert len(flows) == 1 and flows[0].flow_type == "onboarding"
    events = (await session.execute(select(Event))).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types
    assert "welcome_sent" in types
    # assistant message persisted
    convs = (await session.execute(select(Conversation))).scalars().all()
    assert any(c.role == "assistant" and c.intent == "proactive:welcome" for c in convs)


async def test_webhook_existing_user_routes_to_handle(client, session, monkeypatch):
    user = User(name="E", lark_user_id="open_existing", preferences={})
    session.add(user)
    await session.commit()

    class _StubRouter:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            return {
                "intent": "greeting",
                "actions": [],
                "should_reply": True,
                "reply_complexity": "low",
                "reply_hint": "say hi back",
                "reasoning": "",
            }
        async def complete(self, *a, **kw):
            return "Hey!"
    monkeypatch.setattr("app.routers.lark_webhook.LLMRouter", _StubRouter)
    monkeypatch.setattr("app.routers.lark_webhook.settings.proactive_dry_run", True)

    payload = _msg_payload("open_existing", "hi")
    resp = await client.post("/api/lark/webhook", json=payload)
    assert resp.status_code == 200

    # No new flow started, but a user conversation row + assistant conversation row exist
    convs = (await session.execute(select(Conversation))).scalars().all()
    roles = {c.role for c in convs}
    assert {"user", "assistant"} <= roles


async def test_webhook_url_verification_passes_through(client):
    resp = await client.post("/api/lark/webhook", json={
        "type": "url_verification", "token": "test-verify-token", "challenge": "abc"
    })
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc"}


async def test_webhook_invalid_token_returns_403(client):
    resp = await client.post("/api/lark/webhook", json={
        "type": "url_verification", "token": "WRONG", "challenge": "abc"
    })
    assert resp.status_code == 403
```

- [ ] **Step 8.2: Run, expect failures (mismatched routing or 500s)**

```bash
pytest tests/test_routers/test_lark_webhook_rewire.py -v
```

- [ ] **Step 8.3: Rewrite `app/routers/lark_webhook.py`**

```python
from __future__ import annotations
import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.lark.client import LarkClient
from app.lark.webhook import LarkEvent, WebhookHandler
from app.llm.router import LLMRouter
from app.models.user import User
from app.orchestrator.conversation import ConversationOrchestrator
from app.orchestrator.triggers import WelcomeTrigger
from app.services.lark_messenger import LarkMessenger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lark", tags=["lark"])

_webhook_handler = WebhookHandler(verification_token=settings.lark_verification_token or "test-verify-token")


def _lark_client() -> LarkClient:
    return LarkClient(app_id=settings.lark_app_id, app_secret=settings.lark_app_secret)


@router.post("/webhook")
async def lark_webhook(payload: Dict[str, Any], session: AsyncSession = Depends(get_session)):
    event: LarkEvent = _webhook_handler.parse(payload)

    if event.event_type == "invalid":
        raise HTTPException(status_code=403, detail="Invalid verification token")
    if event.event_type == "url_verification":
        return {"challenge": event.challenge}
    if event.event_type == "duplicate":
        return {"status": "ok", "message": "duplicate event ignored"}

    if event.event_type == "im.message.receive_v1":
        return await _handle_message(event, session)

    if event.event_type == "card.action.trigger":
        return {"status": "ok"}

    return {"status": "ok", "message": f"unhandled event type: {event.event_type}"}


async def _handle_message(event: LarkEvent, session: AsyncSession) -> Dict[str, Any]:
    open_id = event.user_id
    text = event.message_text or ""
    if not open_id:
        return {"status": "ok", "message": "no sender open_id"}

    user_row = (await session.execute(
        select(User).where(User.lark_user_id == open_id)
    )).scalar_one_or_none()

    client = _lark_client()
    messenger = LarkMessenger(client)
    llm = LLMRouter()
    orchestrator = ConversationOrchestrator(session=session, llm=llm)

    if user_row is None:
        # Brand new user — create + welcome
        user_row = User(name="(new)", lark_user_id=open_id, preferences={})
        session.add(user_row)
        await session.commit()
        await session.refresh(user_row)
        reply = await orchestrator.send_proactive(
            user_id=user_row.id,
            trigger=WelcomeTrigger(initial_message=text or None),
            complexity="low",
        )
        if reply:
            await messenger.push(open_id, reply)
        return {"status": "ok"}

    # Existing user — normal inbound
    out = await orchestrator.handle(user_id=user_row.id, message=text)
    if out.reply:
        await messenger.push(open_id, out.reply)
    return {"status": "ok"}
```

- [ ] **Step 8.4: Drop any leftover Spec 1 stubs in `app/routers/lark_webhook.py` (already replaced above)**

- [ ] **Step 8.5: Run tests, expect green**

```bash
pytest tests/test_routers/test_lark_webhook_rewire.py -v
```

If `WebhookHandler.parse` doesn't extract `open_id` automatically into `event.user_id`, inspect `app/lark/webhook.py` and adjust either the parser or the handler to pull `sender_id.open_id`. The existing `webhook.py` likely already maps this — verify.

- [ ] **Step 8.6: Run cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 8.7: Commit**

```bash
git add app/routers/lark_webhook.py tests/test_routers/test_lark_webhook_rewire.py
git commit -m "feat: real Lark client + new-user detection in webhook"
```

---

## Task 9: ONBOARDING — `user_expectations` Field

**Files:**
- Modify: `app/orchestrator/flows.py`
- Test: `tests/test_orchestrator/test_flows.py` (additive)

- [ ] **Step 9.1: Add failing test**

Append to `tests/test_orchestrator/test_flows.py`:

```python
def test_onboarding_includes_user_expectations():
    names = [f.name for f in ONBOARDING.required_fields]
    assert "user_expectations" in names


def test_user_expectations_is_text_type():
    field = next(f for f in ONBOARDING.required_fields if f.name == "user_expectations")
    assert field.type == "text"
```

- [ ] **Step 9.2: Run, expect failure**

```bash
pytest tests/test_orchestrator/test_flows.py::test_onboarding_includes_user_expectations -v
```

- [ ] **Step 9.3: Modify `app/orchestrator/flows.py`**

In `ONBOARDING.required_fields`, insert this `FieldDef` after `FieldDef("daily_habits", ...)` and before `FieldDef("yearly_goals", ...)`:

```python
        FieldDef("user_expectations", "text", "what the user wants the assistant to help with"),
```

- [ ] **Step 9.4: Run, expect PASS**

```bash
pytest tests/test_orchestrator/test_flows.py -v
```

- [ ] **Step 9.5: Commit**

```bash
git add app/orchestrator/flows.py tests/test_orchestrator/test_flows.py
git commit -m "feat: onboarding asks user_expectations"
```

---

## Task 10: THINK Prompt — Onboarding Structurization + Check-in Interpretation

**Files:**
- Modify: `app/orchestrator/prompts/think.md`

- [ ] **Step 10.1: Append two paragraphs to `app/orchestrator/prompts/think.md`**

```markdown

When `active_flow == "onboarding"`:
- If the user just answered the `daily_habits` question, emit ONE `add_habit` action per distinct habit they describe (parse them apart yourself). ALSO emit a single `update_profile(path="daily_habits", value=<their raw text>)`.
- If the user just answered the `yearly_goals` question, emit ONE `create_goal` action per distinct goal. ALSO emit `update_profile(path="yearly_goals", value=<their raw text>)`.
- For all other onboarding fields (`wake_up`, `work_start`, `peak_hours_start`, `peak_hours_end`, `work_end`, `sleep_time`, `user_expectations`), emit ONE `update_profile(path=<field>, value=<parsed value>)`.

When the conversation history shows the assistant recently asked about a specific task (look for assistant turns with intent containing `proactive:task_checkin` or wording like "搞定了吗" / "still on it" near a known task), and the user's latest message is short or ambiguous ("done", "still on it", "kinda", "做完了"):
- "done" / "做完了" / "搞定了" → emit `complete_task(task_id=<the task being asked about>)`
- "still working" / "在做" / longer-than-expected → no DB action; should_reply true with `reply_hint="acknowledge, ask if they need more time"`
- "didn't start" / "没开始" → emit `update_task(task_id=..., deadline=...)` with a sensibly extended deadline (next day), OR ask if they want to delete
- topic-change → emit no actions, just respond naturally
```

- [ ] **Step 10.2: Sanity-check by reading the file**

```bash
cat app/orchestrator/prompts/think.md
```

Confirm the new paragraphs landed.

- [ ] **Step 10.3: Run cumulative tests**

```bash
pytest tests/ -q
```

(No code-level tests verify prompt content; this is a documentation/prompt-only change. The behavior will be observed live in Task 17 + 18.)

- [ ] **Step 10.4: Commit**

```bash
git add app/orchestrator/prompts/think.md
git commit -m "feat: THINK prompt - onboarding structurization + check-in interpretation"
```

---

## Task 11: Auto-Schedule First Check-in on Task Creation; Cancel on Completion

**Files:**
- Modify: `app/orchestrator/act.py`
- Test: `tests/test_orchestrator/test_act.py` (additive)

- [ ] **Step 11.1: Add failing tests**

Append to `tests/test_orchestrator/test_act.py`:

```python
from datetime import datetime, timedelta, timezone

from app.models.reminder import Reminder


async def test_create_task_with_deadline_schedules_checkin_1(session):
    user = await _make_user(session, lark="ckin_u1")
    executor = ActionExecutor(session)
    deadline_iso = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    actions = [ParsedAction(
        ActionType.CREATE_TASK, CreateTaskParams(title="x", deadline=deadline_iso)
    )]
    await executor.execute_all(user.id, actions, conversation_id=None)
    rems = (await session.execute(select(Reminder))).scalars().all()
    assert len(rems) == 1
    assert rems[0].type == "task_checkin_1"
    assert rems[0].status == "pending"
    assert rems[0].linked_task_id is not None


async def test_create_task_without_deadline_no_reminder(session):
    user = await _make_user(session, lark="ckin_u2")
    executor = ActionExecutor(session)
    actions = [ParsedAction(ActionType.CREATE_TASK, CreateTaskParams(title="x"))]
    await executor.execute_all(user.id, actions, conversation_id=None)
    rems = (await session.execute(select(Reminder))).scalars().all()
    assert len(rems) == 0


async def test_complete_task_cancels_pending_reminders(session):
    user = await _make_user(session, lark="ckin_u3")
    t = Task(user_id=user.id, title="t", status="pending",
             deadline=datetime.now(timezone.utc) + timedelta(hours=1))
    session.add(t)
    await session.commit()
    rem = Reminder(
        user_id=user.id, trigger_time=datetime.now(timezone.utc) + timedelta(hours=2),
        type="task_checkin_1", linked_task_id=t.id, status="pending", message=""
    )
    session.add(rem)
    await session.commit()

    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=t.id)
    )], conversation_id=None)
    await session.refresh(rem)
    assert rem.status == "cancelled"
```

- [ ] **Step 11.2: Run, expect failures**

```bash
pytest tests/test_orchestrator/test_act.py -v
```

- [ ] **Step 11.3: Modify `app/orchestrator/act.py`**

Add to top imports:

```python
from datetime import timedelta
from sqlalchemy import update
from app.models.reminder import Reminder
```

Extend `_create_task` body to schedule a reminder when deadline is set. Replace the existing `_create_task` method:

```python
    async def _create_task(self, user_id: int, p: CreateTaskParams) -> ActionResult:
        task = Task(
            user_id=user_id,
            title=p.title,
            description=p.description,
            deadline=_parse_iso_datetime(p.deadline),
            quadrant=p.quadrant,
            goal_id=p.goal_id,
            habit_id=p.habit_id,
        )
        self.session.add(task)
        await self.session.flush()
        if task.deadline is not None:
            self.session.add(Reminder(
                user_id=user_id,
                trigger_time=task.deadline + timedelta(minutes=15),
                type="task_checkin_1",
                linked_task_id=task.id,
                status="pending",
                message="",
            ))
            await self.session.flush()
        return ActionResult(
            type=ActionType.CREATE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"title": task.title, "deadline": p.deadline, "quadrant": p.quadrant},
        )
```

Extend `_complete_task` to cancel pending reminders. Replace:

```python
    async def _complete_task(self, user_id: int, p: CompleteTaskParams) -> ActionResult:
        task = await self.session.get(Task, p.task_id)
        if task is None or task.user_id != user_id:
            raise ValueError(f"task {p.task_id} not found for user")
        task.status = "done"
        await self.session.execute(
            update(Reminder)
            .where(Reminder.linked_task_id == p.task_id, Reminder.status == "pending")
            .values(status="cancelled")
        )
        await self.session.flush()
        return ActionResult(
            type=ActionType.COMPLETE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"completed_at": _now_iso()},
        )
```

- [ ] **Step 11.4: Run, expect PASS**

```bash
pytest tests/test_orchestrator/test_act.py -v
```

- [ ] **Step 11.5: Run cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 11.6: Commit**

```bash
git add app/orchestrator/act.py tests/test_orchestrator/test_act.py
git commit -m "feat: auto-schedule task_checkin_1; cancel pending reminders on completion"
```

---

## Task 12: Scheduler Runtime + Main.py Wiring

**Files:**
- Create: `app/scheduler/__init__.py`
- Create: `app/scheduler/runtime.py`
- Modify: `app/main.py`
- Test: `tests/test_scheduler/__init__.py`, `tests/test_scheduler/test_runtime.py`

- [ ] **Step 12.1: Write failing tests**

Create `tests/test_scheduler/__init__.py` (empty), then `tests/test_scheduler/test_runtime.py`:

```python
def test_scheduler_instance_is_async_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.scheduler.runtime import scheduler
    assert isinstance(scheduler, AsyncIOScheduler)


def test_scheduler_not_running_at_import():
    from app.scheduler.runtime import scheduler
    assert not scheduler.running


def test_start_and_shutdown_helpers():
    from app.scheduler.runtime import scheduler, start_scheduler, shutdown_scheduler
    start_scheduler()
    assert scheduler.running
    shutdown_scheduler()
    assert not scheduler.running
```

- [ ] **Step 12.2: Run, expect ImportError**

```bash
pytest tests/test_scheduler/test_runtime.py -v
```

- [ ] **Step 12.3: Create `app/scheduler/runtime.py`**

```python
from __future__ import annotations
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
        logger.info("scheduler started")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler shut down")
```

- [ ] **Step 12.4: Create `app/scheduler/__init__.py`**

```python
from app.scheduler.runtime import scheduler, start_scheduler, shutdown_scheduler

__all__ = ["scheduler", "start_scheduler", "shutdown_scheduler"]
```

- [ ] **Step 12.5: Wire into `app/main.py`**

Open `app/main.py`. Add to imports:

```python
from app.config import settings
from app.scheduler import scheduler, start_scheduler, shutdown_scheduler
```

After the existing `app.include_router(...)` calls and the `/health` route, add:

```python
@app.on_event("startup")
async def _startup_scheduler():
    if settings.enable_scheduler:
        start_scheduler()


@app.on_event("shutdown")
async def _shutdown_scheduler():
    shutdown_scheduler()
```

- [ ] **Step 12.6: Run, expect PASS**

```bash
pytest tests/test_scheduler/test_runtime.py -v
```

- [ ] **Step 12.7: Verify the API still boots**

```bash
python -c "from app.main import app; print('ok', len(app.routes))"
```

- [ ] **Step 12.8: Important — disable scheduler in tests**

Open `tests/conftest.py`. Add at the very top (before any app import side-effects):

```python
import os
os.environ.setdefault("PA_ENABLE_SCHEDULER", "false")
```

Re-run full suite:

```bash
pytest tests/ -q
```

- [ ] **Step 12.9: Commit**

```bash
git add app/scheduler/ app/main.py tests/test_scheduler/ tests/conftest.py
git commit -m "feat: APScheduler runtime + main.py startup/shutdown wiring"
```

---

## Task 13: `scan_reminders` Job — Fire Pending Reminders

**Files:**
- Create: `app/scheduler/jobs.py`
- Test: `tests/test_scheduler/test_jobs.py`

- [ ] **Step 13.1: Write failing tests for `scan_reminders` happy path**

Create `tests/test_scheduler/test_jobs.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.models.event import Event
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User


class _FakeOrchestrator:
    """Captures send_proactive calls without touching LLM."""
    def __init__(self):
        self.calls = []

    async def send_proactive(self, user_id, trigger, complexity="low"):
        self.calls.append({"user_id": user_id, "trigger": trigger, "complexity": complexity})
        return f"sent: {trigger.type}"


async def test_scan_reminders_fires_due_task_checkin(session, monkeypatch):
    user = User(name="A", lark_user_id="sched_u1", preferences={})
    session.add(user)
    await session.commit()
    task = Task(user_id=user.id, title="report",
                deadline=datetime.now(timezone.utc) - timedelta(minutes=15), status="pending")
    session.add(task)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(seconds=10),
        type="task_checkin_1",
        linked_task_id=task.id,
        status="pending",
        message="",
    )
    session.add(rem)
    await session.commit()

    orch = _FakeOrchestrator()
    # Stub out Lark messenger so no real push
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import scan_reminders_once
    fired = await scan_reminders_once(session, orchestrator=orch)
    assert fired == 1
    assert orch.calls[0]["trigger"].type == "task_checkin"
    assert orch.calls[0]["trigger"].attempt == 1

    await session.refresh(rem)
    assert rem.status == "sent"


async def test_scan_reminders_skips_future(session, monkeypatch):
    user = User(name="A", lark_user_id="sched_u2", preferences={})
    session.add(user)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) + timedelta(hours=1),
        type="task_checkin_1",
        linked_task_id=None,
        status="pending",
        message="",
    )
    session.add(rem)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import scan_reminders_once
    fired = await scan_reminders_once(session, orchestrator=orch)
    assert fired == 0
    assert orch.calls == []


async def test_scan_reminders_skips_cancelled(session, monkeypatch):
    user = User(name="A", lark_user_id="sched_u3", preferences={})
    session.add(user)
    await session.commit()
    rem = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(minutes=5),
        type="task_checkin_1",
        linked_task_id=None,
        status="cancelled",
        message="",
    )
    session.add(rem)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import scan_reminders_once
    fired = await scan_reminders_once(session, orchestrator=orch)
    assert fired == 0


async def test_scan_reminders_schedules_checkin_2_after_1(session, monkeypatch):
    user = User(name="A", lark_user_id="sched_u4", preferences={})
    session.add(user)
    await session.commit()
    task = Task(user_id=user.id, title="x",
                deadline=datetime.now(timezone.utc) - timedelta(minutes=30), status="pending")
    session.add(task)
    await session.commit()
    rem1 = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(minutes=15),
        type="task_checkin_1",
        linked_task_id=task.id,
        status="pending",
        message="",
    )
    session.add(rem1)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import scan_reminders_once
    await scan_reminders_once(session, orchestrator=orch)

    rems = (await session.execute(select(Reminder).order_by(Reminder.id))).scalars().all()
    # rem1 now sent, plus a new task_checkin_2 row pending
    assert rems[0].status == "sent"
    assert any(r.type == "task_checkin_2" and r.status == "pending" for r in rems)
```

- [ ] **Step 13.2: Run, expect ImportError**

```bash
pytest tests/test_scheduler/test_jobs.py -v
```

- [ ] **Step 13.3: Create `app/scheduler/jobs.py` with `scan_reminders_once`**

```python
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User
from app.orchestrator.triggers import TaskCheckinTrigger
from app.services.lark_messenger import LarkMessenger

logger = logging.getLogger(__name__)


class _OrchestratorLike(Protocol):
    async def send_proactive(self, user_id: int, trigger, complexity: str = "low") -> Optional[str]: ...


# Window after which task_checkin_1 elapses with no reply → schedule task_checkin_2 (relative to checkin_1 fire time)
CHECKIN_2_DELAY = timedelta(hours=2)
# After task_checkin_2 with no reply → schedule task_checkin_3 (deferred / piggy-back)
CHECKIN_3_DELAY = timedelta(hours=24)


async def _push_to_lark(lark_user_id: str, text: str) -> bool:
    """Indirection so tests can monkeypatch."""
    # In production, callers should already have a LarkMessenger.
    # This default is only used if scan_reminders_once is invoked without a custom pusher.
    from app.lark.client import LarkClient
    from app.config import settings
    client = LarkClient(app_id=settings.lark_app_id, app_secret=settings.lark_app_secret)
    return await LarkMessenger(client).push(lark_user_id, text)


async def scan_reminders_once(session: AsyncSession, orchestrator: _OrchestratorLike) -> int:
    """Find pending due reminders, fire each through orchestrator.send_proactive,
    update Reminder.status, and queue follow-ups. Returns count fired this run."""
    now = datetime.now(timezone.utc)
    q = (
        select(Reminder)
        .where(Reminder.status == "pending", Reminder.trigger_time <= now)
        .order_by(Reminder.trigger_time.asc())
        .limit(50)
    )
    rows = (await session.execute(q)).scalars().all()
    fired = 0
    for rem in rows:
        try:
            trigger = await _build_trigger(session, rem)
            if trigger is None:
                rem.status = "cancelled"
                await session.commit()
                continue
            reply = await orchestrator.send_proactive(
                user_id=rem.user_id, trigger=trigger, complexity="low"
            )
            if reply is None:
                rem.status = "failed"
                await session.commit()
                continue
            # Push to Lark
            user = await session.get(User, rem.user_id)
            if user and user.lark_user_id:
                ok = await _push_to_lark(user.lark_user_id, reply)
                if not ok:
                    rem.status = "failed"
                    await session.commit()
                    continue
            rem.status = "sent"
            await session.commit()
            fired += 1

            # Cascade: schedule next checkin if applicable
            await _maybe_schedule_next_checkin(session, rem)
        except Exception as e:
            logger.warning("reminder %s failed: %s", rem.id, e)
            rem.status = "failed"
            await session.commit()
    return fired


async def _build_trigger(session: AsyncSession, rem: Reminder):
    if rem.type in ("task_checkin_1", "task_checkin_2", "task_checkin_3"):
        if rem.linked_task_id is None:
            return None
        task = await session.get(Task, rem.linked_task_id)
        if task is None or task.status in ("done", "cancelled"):
            return None
        attempt = {"task_checkin_1": 1, "task_checkin_2": 2, "task_checkin_3": 3}[rem.type]
        return TaskCheckinTrigger(
            task_id=task.id,
            attempt=attempt,
            task_title=task.title,
            deadline=task.deadline.isoformat() if task.deadline else "",
        )
    return None


async def _maybe_schedule_next_checkin(session: AsyncSession, fired: Reminder) -> None:
    """After a checkin_1 fires, queue checkin_2; after checkin_2, queue a deferred checkin_3."""
    if fired.type == "task_checkin_1":
        session.add(Reminder(
            user_id=fired.user_id,
            trigger_time=datetime.now(timezone.utc) + CHECKIN_2_DELAY,
            type="task_checkin_2",
            linked_task_id=fired.linked_task_id,
            status="pending",
            message="",
        ))
        await session.commit()
    elif fired.type == "task_checkin_2":
        # checkin_3 is "deferred" — scan_reminders won't pick it up; piggy-back logic will.
        session.add(Reminder(
            user_id=fired.user_id,
            trigger_time=datetime.now(timezone.utc) + CHECKIN_3_DELAY,
            type="task_checkin_3",
            linked_task_id=fired.linked_task_id,
            status="deferred",
            message="",
        ))
        await session.commit()
    # checkin_3 fires by piggy-back; no cascade here.
```

- [ ] **Step 13.4: Run, expect PASS**

```bash
pytest tests/test_scheduler/test_jobs.py -v
```

- [ ] **Step 13.5: Cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 13.6: Commit**

```bash
git add app/scheduler/jobs.py tests/test_scheduler/test_jobs.py
git commit -m "feat: scan_reminders_once — fire pending task_checkin_1/2 + cascade to next attempt"
```

---

## Task 14: `task_status_unknown` Terminal — When Checkin_3 Goes Unanswered

**Files:**
- Modify: `app/scheduler/jobs.py`
- Test: `tests/test_scheduler/test_jobs.py` (additive)

- [ ] **Step 14.1: Add failing test**

Append to `tests/test_scheduler/test_jobs.py`:

```python
async def test_expire_unanswered_checkin_3_marks_task_unknown(session):
    user = User(name="A", lark_user_id="sched_u5", preferences={})
    session.add(user)
    await session.commit()
    task = Task(user_id=user.id, title="ghost task",
                deadline=datetime.now(timezone.utc) - timedelta(hours=48), status="pending")
    session.add(task)
    await session.commit()
    rem3 = Reminder(
        user_id=user.id,
        trigger_time=datetime.now(timezone.utc) - timedelta(hours=24),  # expired
        type="task_checkin_3",
        linked_task_id=task.id,
        status="deferred",  # never piggy-backed, now stale
        message="",
    )
    session.add(rem3)
    await session.commit()

    from app.scheduler.jobs import expire_stale_checkins
    expired = await expire_stale_checkins(session)
    assert expired == 1

    await session.refresh(task)
    assert task.status == "unknown"
    await session.refresh(rem3)
    assert rem3.status == "expired"
    events = (await session.execute(select(Event).where(Event.user_id == user.id))).scalars().all()
    assert any(e.type == "task_status_unknown" for e in events)
```

- [ ] **Step 14.2: Run, expect ImportError**

```bash
pytest tests/test_scheduler/test_jobs.py::test_expire_unanswered_checkin_3_marks_task_unknown -v
```

- [ ] **Step 14.3: Extend `app/scheduler/jobs.py`**

At top, ensure imports include `Event` (already there). Append:

```python
async def expire_stale_checkins(session: AsyncSession) -> int:
    """Find task_checkin_3 rows still deferred past their trigger_time and mark
    the linked task as unknown."""
    now = datetime.now(timezone.utc)
    q = (
        select(Reminder)
        .where(
            Reminder.type == "task_checkin_3",
            Reminder.status == "deferred",
            Reminder.trigger_time <= now,
        )
    )
    rows = (await session.execute(q)).scalars().all()
    expired = 0
    for rem in rows:
        task = await session.get(Task, rem.linked_task_id) if rem.linked_task_id else None
        if task and task.status == "pending":
            task.status = "unknown"
            session.add(Event(
                user_id=rem.user_id,
                conversation_id=None,
                type="task_status_unknown",
                entity_type="task",
                entity_id=task.id,
                payload={"reason": "no response after 3 check-ins"},
            ))
        rem.status = "expired"
        await session.commit()
        expired += 1
    return expired
```

- [ ] **Step 14.4: Run, expect PASS**

```bash
pytest tests/test_scheduler/test_jobs.py::test_expire_unanswered_checkin_3_marks_task_unknown -v
```

- [ ] **Step 14.5: Cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 14.6: Commit**

```bash
git add app/scheduler/jobs.py tests/test_scheduler/test_jobs.py
git commit -m "feat: expire_stale_checkins → mark task status=unknown after 3 silent attempts"
```

---

## Task 15: Morning Brief Job

**Files:**
- Modify: `app/scheduler/jobs.py`
- Test: `tests/test_scheduler/test_jobs.py` (additive)

- [ ] **Step 15.1: Add failing test**

Append to `tests/test_scheduler/test_jobs.py`:

```python
async def test_morning_brief_gathers_today_and_calls_send_proactive(session, monkeypatch):
    from datetime import date
    user = User(
        name="A", lark_user_id="sched_morning",
        preferences={"profile": {"wake_up": "07:00"}, "procedural": [], "onboarding_status": "completed"},
    )
    session.add(user)
    await session.commit()
    today_end = datetime.now(timezone.utc).replace(hour=17, minute=0, second=0, microsecond=0)
    task1 = Task(
        user_id=user.id, title="critical", status="pending",
        quadrant="urgent_important", deadline=today_end,
    )
    session.add(task1)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import send_morning_brief_once
    out = await send_morning_brief_once(session, user_id=user.id, orchestrator=orch)
    assert out is True
    assert len(orch.calls) == 1
    trigger = orch.calls[0]["trigger"]
    assert trigger.type == "morning_brief"
    titles = [item.get("title") for item in trigger.today_plan]
    assert "critical" in titles


async def test_morning_brief_idempotent_in_same_day(session, monkeypatch):
    from datetime import date
    user = User(
        name="A", lark_user_id="sched_morning_idem",
        preferences={"profile": {"wake_up": "07:00"}, "procedural": [], "onboarding_status": "completed"},
    )
    session.add(user)
    await session.commit()
    # Pretend a brief already ran today
    session.add(Event(
        user_id=user.id, conversation_id=None,
        type="morning_brief_sent", entity_type="proactive", entity_id=None,
        payload={},
    ))
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import send_morning_brief_once
    out = await send_morning_brief_once(session, user_id=user.id, orchestrator=orch)
    assert out is False
    assert orch.calls == []
```

- [ ] **Step 15.2: Run, expect ImportError**

```bash
pytest tests/test_scheduler/test_jobs.py::test_morning_brief_gathers_today_and_calls_send_proactive -v
```

- [ ] **Step 15.3: Extend `app/scheduler/jobs.py` with `send_morning_brief_once`**

Add at top imports:

```python
from datetime import date as date_type
from sqlalchemy import and_, func
from app.models.habit import Habit
from app.models.goal import Goal
from app.orchestrator.triggers import MorningBriefTrigger, EveningRecapTrigger
```

Append to the file:

```python
async def _already_sent_today(session: AsyncSession, user_id: int, event_type: str) -> bool:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    q = (
        select(Event)
        .where(
            Event.user_id == user_id,
            Event.type == event_type,
            Event.created_at >= today_start,
        )
        .limit(1)
    )
    return (await session.execute(q)).scalar_one_or_none() is not None


def _quadrant_priority(q: Optional[str]) -> int:
    return {"urgent_important": 0, "important": 1, "urgent": 2, "neither": 3}.get(q or "neither", 3)


async def send_morning_brief_once(
    session: AsyncSession,
    user_id: int,
    orchestrator: _OrchestratorLike,
) -> bool:
    """Send a morning brief if not already sent today. Returns True if sent."""
    if await _already_sent_today(session, user_id, "morning_brief_sent"):
        return False

    user = await session.get(User, user_id)
    if user is None:
        return False

    # Today's tasks (pending/in_progress, deadline today or unset)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    tasks_q = (
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.status.in_(["pending", "in_progress"]),
            (Task.deadline.is_(None)) | (Task.deadline >= today_start) & (Task.deadline < today_end),
        )
    )
    tasks = (await session.execute(tasks_q)).scalars().all()

    # Sort by quadrant priority then deadline
    tasks_sorted = sorted(
        tasks, key=lambda t: (_quadrant_priority(t.quadrant), t.deadline or today_end)
    )
    headline = tasks_sorted[0].title if tasks_sorted else None

    today_plan = []
    for t in tasks_sorted:
        time_str = t.deadline.strftime("%H:%M") if t.deadline else "today"
        today_plan.append({
            "time": time_str,
            "title": t.title,
            "quadrant": t.quadrant,
            "kind": "task",
        })

    # Today's habits
    habits_q = select(Habit).where(Habit.user_id == user_id, Habit.active == True)
    habits = (await session.execute(habits_q)).scalars().all()
    habits_today = [{"id": h.id, "title": h.title, "frequency": h.frequency_type} for h in habits]

    # Active goals brief
    goals_q = select(Goal).where(Goal.user_id == user_id, Goal.status == "active").limit(5)
    goals = (await session.execute(goals_q)).scalars().all()
    active_goals_brief = [
        {"title": g.title, "progress": f"{g.current_value}/{g.target_value} {g.unit}"}
        for g in goals
    ]

    trigger = MorningBriefTrigger(
        date=date_type.today().isoformat(),
        today_plan=today_plan,
        headline_task=headline,
        habits_today=habits_today,
        active_goals_brief=active_goals_brief,
    )

    reply = await orchestrator.send_proactive(user_id=user_id, trigger=trigger, complexity="low")
    if reply is None:
        return False
    if user.lark_user_id:
        await _push_to_lark(user.lark_user_id, reply)
    return True
```

- [ ] **Step 15.4: Run, expect PASS**

```bash
pytest tests/test_scheduler/test_jobs.py -v
```

- [ ] **Step 15.5: Cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 15.6: Commit**

```bash
git add app/scheduler/jobs.py tests/test_scheduler/test_jobs.py
git commit -m "feat: send_morning_brief_once with idempotency + four-quadrant ordering"
```

---

## Task 16: Evening Recap Job (Opus)

**Files:**
- Modify: `app/scheduler/jobs.py`
- Test: `tests/test_scheduler/test_jobs.py` (additive)

- [ ] **Step 16.1: Add failing test**

Append to `tests/test_scheduler/test_jobs.py`:

```python
async def test_evening_recap_uses_complexity_high(session, monkeypatch):
    user = User(
        name="A", lark_user_id="sched_evening",
        preferences={"profile": {"sleep_time": "23:00"}, "procedural": [], "onboarding_status": "completed"},
    )
    session.add(user)
    await session.commit()

    orch = _FakeOrchestrator()
    async def _no_push(*a, **kw): return True
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", _no_push)

    from app.scheduler.jobs import send_evening_recap_once
    out = await send_evening_recap_once(session, user_id=user.id, orchestrator=orch)
    assert out is True
    assert orch.calls[0]["complexity"] == "high"
    assert orch.calls[0]["trigger"].type == "evening_recap"


async def test_evening_recap_idempotent(session, monkeypatch):
    user = User(
        name="A", lark_user_id="sched_evening_idem",
        preferences={"profile": {"sleep_time": "23:00"}, "procedural": [], "onboarding_status": "completed"},
    )
    session.add(user)
    await session.commit()
    session.add(Event(
        user_id=user.id, conversation_id=None,
        type="evening_recap_sent", entity_type="proactive", entity_id=None,
        payload={},
    ))
    await session.commit()

    orch = _FakeOrchestrator()
    from app.scheduler.jobs import send_evening_recap_once
    out = await send_evening_recap_once(session, user_id=user.id, orchestrator=orch)
    assert out is False
    assert orch.calls == []
```

- [ ] **Step 16.2: Run, expect ImportError**

```bash
pytest tests/test_scheduler/test_jobs.py::test_evening_recap_uses_complexity_high -v
```

- [ ] **Step 16.3: Append `send_evening_recap_once` to `app/scheduler/jobs.py`**

```python
async def send_evening_recap_once(
    session: AsyncSession,
    user_id: int,
    orchestrator: _OrchestratorLike,
) -> bool:
    if await _already_sent_today(session, user_id, "evening_recap_sent"):
        return False
    user = await session.get(User, user_id)
    if user is None:
        return False

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Today's events for context
    events_q = (
        select(Event)
        .where(Event.user_id == user_id, Event.created_at >= today_start, Event.created_at < today_end)
        .order_by(Event.id)
    )
    events = (await session.execute(events_q)).scalars().all()

    tasks_completed = []
    tasks_missed = []
    habits_done = []
    user_feedback = []
    for e in events:
        if e.type == "task_completed":
            tasks_completed.append({"id": e.entity_id, "payload": e.payload})
        elif e.type == "task_status_unknown":
            tasks_missed.append({"id": e.entity_id, "payload": e.payload})
        elif e.type == "habit_completed":
            habits_done.append({"id": e.entity_id, "payload": e.payload})
        elif e.type == "feedback_recorded":
            user_feedback.append(e.payload)

    # Tasks past deadline but still pending = missed
    pending_overdue_q = (
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.status == "pending",
            Task.deadline.is_not(None),
            Task.deadline < datetime.now(timezone.utc),
        )
    )
    overdue = (await session.execute(pending_overdue_q)).scalars().all()
    tasks_missed.extend([{"id": t.id, "title": t.title, "deadline": t.deadline.isoformat()} for t in overdue])

    # Active habits the user did NOT complete today
    habits_active = (await session.execute(
        select(Habit).where(Habit.user_id == user_id, Habit.active == True)
    )).scalars().all()
    done_ids = {h.get("id") for h in habits_done if isinstance(h.get("id"), int)}
    habits_missed = [
        {"id": h.id, "title": h.title} for h in habits_active if h.id not in done_ids
    ]

    # Goals touched (had a completed task linked)
    goals_touched: list[dict] = []
    for t in (await session.execute(
        select(Task).where(Task.user_id == user_id, Task.status == "done", Task.goal_id.is_not(None))
    )).scalars().all():
        if t.goal_id and not any(g["id"] == t.goal_id for g in goals_touched):
            goal = await session.get(Goal, t.goal_id)
            if goal:
                goals_touched.append({"id": goal.id, "title": goal.title})

    # 7-day completion rate (simple)
    week_start = today_start - timedelta(days=7)
    week_done = await session.execute(
        select(func.count(Event.id))
        .where(Event.user_id == user_id, Event.type == "task_completed",
               Event.created_at >= week_start)
    )
    week_done_n = week_done.scalar() or 0
    week_created = await session.execute(
        select(func.count(Event.id))
        .where(Event.user_id == user_id, Event.type == "task_created",
               Event.created_at >= week_start)
    )
    week_created_n = max(week_created.scalar() or 0, 1)
    recent_pattern = {"avg_completion_rate": round(week_done_n / week_created_n, 2)}

    trigger = EveningRecapTrigger(
        date=date_type.today().isoformat(),
        tasks_completed=tasks_completed,
        tasks_missed=tasks_missed,
        habits_done=habits_done,
        habits_missed=habits_missed,
        goals_touched=goals_touched,
        recent_pattern=recent_pattern,
        user_feedback_today=user_feedback,
    )

    reply = await orchestrator.send_proactive(user_id=user_id, trigger=trigger, complexity="high")
    if reply is None:
        return False
    if user.lark_user_id:
        await _push_to_lark(user.lark_user_id, reply)
    return True
```

- [ ] **Step 16.4: Run, expect PASS**

```bash
pytest tests/test_scheduler/test_jobs.py -v
```

- [ ] **Step 16.5: Cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 16.6: Commit**

```bash
git add app/scheduler/jobs.py tests/test_scheduler/test_jobs.py
git commit -m "feat: send_evening_recap_once with Opus + structured event aggregation"
```

---

## Task 17: `orchestrate_daily_jobs` — User-Timezone-Aware Hourly Dispatcher

**Files:**
- Modify: `app/scheduler/jobs.py`
- Test: `tests/test_scheduler/test_jobs.py` (additive)

- [ ] **Step 17.1: Add failing test**

Append to `tests/test_scheduler/test_jobs.py`:

```python
async def test_orchestrate_daily_jobs_picks_users_due_this_hour(session, monkeypatch):
    # Two users: one whose morning is now, one whose morning is at a different hour.
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    wake_due_str = f"{(current_hour - 0):02d}:00"  # wake_up + 30min would still be this hour
    wake_other_str = f"{(current_hour + 6) % 24:02d}:00"  # not this hour

    u_due = User(name="due", lark_user_id="ddl_due",
                 preferences={"profile": {"wake_up": wake_due_str, "sleep_time": "23:00"}})
    u_other = User(name="other", lark_user_id="ddl_other",
                   preferences={"profile": {"wake_up": wake_other_str, "sleep_time": "23:00"}})
    session.add(u_due)
    session.add(u_other)
    await session.commit()

    triggered: list[int] = []

    async def fake_morning(session_, user_id, orchestrator):
        triggered.append(user_id)
        return True

    monkeypatch.setattr("app.scheduler.jobs.send_morning_brief_once", fake_morning)
    monkeypatch.setattr("app.scheduler.jobs.send_evening_recap_once",
                        lambda *a, **kw: pytest.fail("evening should not fire in this scenario"))

    from app.scheduler.jobs import orchestrate_daily_jobs_once
    await orchestrate_daily_jobs_once(session, orchestrator=_FakeOrchestrator())
    assert u_due.id in triggered
    assert u_other.id not in triggered
```

- [ ] **Step 17.2: Run, expect ImportError**

```bash
pytest tests/test_scheduler/test_jobs.py::test_orchestrate_daily_jobs_picks_users_due_this_hour -v
```

- [ ] **Step 17.3: Append `orchestrate_daily_jobs_once`**

Add at imports:

```python
try:
    from zoneinfo import ZoneInfo
except ImportError:  # py < 3.9 fallback (we are 3.10, but defensive)
    from backports.zoneinfo import ZoneInfo  # type: ignore
```

Append:

```python
async def orchestrate_daily_jobs_once(
    session: AsyncSession,
    orchestrator: _OrchestratorLike,
) -> dict:
    """Scan all users; for each, decide if their morning brief or evening recap
    should fire this hour and call the relevant job inline."""
    now_utc = datetime.now(timezone.utc)
    users = (await session.execute(select(User))).scalars().all()
    counts = {"morning": 0, "evening": 0}
    for u in users:
        prefs = u.preferences or {}
        profile = (prefs.get("profile") or {})
        tz_name = profile.get("timezone") or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        now_local = now_utc.astimezone(tz)

        wake_str = profile.get("wake_up")
        sleep_str = profile.get("sleep_time")

        if wake_str:
            try:
                wh, wm = map(int, wake_str.split(":"))
                morning_local = now_local.replace(hour=wh, minute=wm, second=0, microsecond=0) + timedelta(minutes=30)
                if morning_local.hour == now_local.hour:
                    if await send_morning_brief_once(session, user_id=u.id, orchestrator=orchestrator):
                        counts["morning"] += 1
            except ValueError:
                pass

        if sleep_str:
            try:
                sh, sm = map(int, sleep_str.split(":"))
                evening_local = now_local.replace(hour=sh, minute=sm, second=0, microsecond=0) - timedelta(hours=1)
                if evening_local.hour == now_local.hour:
                    if await send_evening_recap_once(session, user_id=u.id, orchestrator=orchestrator):
                        counts["evening"] += 1
            except ValueError:
                pass
    return counts
```

- [ ] **Step 17.4: Run, expect PASS**

```bash
pytest tests/test_scheduler/test_jobs.py::test_orchestrate_daily_jobs_picks_users_due_this_hour -v
```

- [ ] **Step 17.5: Cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 17.6: Commit**

```bash
git add app/scheduler/jobs.py tests/test_scheduler/test_jobs.py
git commit -m "feat: orchestrate_daily_jobs_once — user-tz aware hourly dispatcher"
```

---

## Task 18: Wire APScheduler Triggers (interval + cron) Into Runtime

**Files:**
- Modify: `app/scheduler/runtime.py`
- Modify: `app/scheduler/__init__.py`
- Test: `tests/test_scheduler/test_runtime.py` (additive)

- [ ] **Step 18.1: Add test for `register_jobs`**

Append to `tests/test_scheduler/test_runtime.py`:

```python
def test_register_jobs_adds_expected_job_ids():
    from app.scheduler.runtime import scheduler, register_jobs, _clear_jobs_for_test
    _clear_jobs_for_test()
    register_jobs()
    ids = {job.id for job in scheduler.get_jobs()}
    assert "scan_reminders" in ids
    assert "orchestrate_daily" in ids
    assert "expire_stale_checkins" in ids
    _clear_jobs_for_test()
```

- [ ] **Step 18.2: Run, expect failure**

```bash
pytest tests/test_scheduler/test_runtime.py::test_register_jobs_adds_expected_job_ids -v
```

- [ ] **Step 18.3: Extend `app/scheduler/runtime.py`**

Replace its content with:

```python
from __future__ import annotations
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    if not scheduler.running:
        register_jobs()
        scheduler.start()
        logger.info("scheduler started")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("scheduler shut down")


def register_jobs() -> None:
    """Add interval + cron jobs. Idempotent: replaces existing job ids."""
    from app.scheduler.jobs import (
        run_scan_reminders,
        run_orchestrate_daily,
        run_expire_stale_checkins,
    )
    scheduler.add_job(run_scan_reminders, "interval", minutes=1,
                      id="scan_reminders", replace_existing=True)
    scheduler.add_job(run_orchestrate_daily, "cron", minute=0,
                      id="orchestrate_daily", replace_existing=True)
    scheduler.add_job(run_expire_stale_checkins, "interval", hours=1,
                      id="expire_stale_checkins", replace_existing=True)


def _clear_jobs_for_test() -> None:
    for j in list(scheduler.get_jobs()):
        scheduler.remove_job(j.id)
```

- [ ] **Step 18.4: Add `run_*` thin wrappers in `app/scheduler/jobs.py`**

Append to the bottom of `app/scheduler/jobs.py`:

```python
async def _build_orchestrator(session: AsyncSession):
    """Constructs a ConversationOrchestrator for a job's session."""
    from app.llm.router import LLMRouter
    from app.orchestrator.conversation import ConversationOrchestrator
    return ConversationOrchestrator(session=session, llm=LLMRouter())


async def run_scan_reminders() -> None:
    """APScheduler entry point. Opens its own DB session."""
    from app.database import async_session_factory
    async with async_session_factory() as session:
        orch = await _build_orchestrator(session)
        await scan_reminders_once(session, orchestrator=orch)


async def run_orchestrate_daily() -> None:
    from app.database import async_session_factory
    async with async_session_factory() as session:
        orch = await _build_orchestrator(session)
        await orchestrate_daily_jobs_once(session, orchestrator=orch)


async def run_expire_stale_checkins() -> None:
    from app.database import async_session_factory
    async with async_session_factory() as session:
        await expire_stale_checkins(session)
```

- [ ] **Step 18.5: Verify `async_session_factory` exists in `app/database.py`**

```bash
grep -n "async_session" app/database.py
```

If `async_session_factory` isn't exposed there but a session maker is, expose it. Open `app/database.py`. If the file currently has `async_session_maker` or similar, add:

```python
async_session_factory = async_session_maker  # alias for jobs
```

or use whatever the existing name is and update the wrappers accordingly. Verify with a `python -c "from app.database import async_session_factory"` check.

- [ ] **Step 18.6: Run scheduler tests, expect PASS**

```bash
pytest tests/test_scheduler/ -v
```

- [ ] **Step 18.7: Cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 18.8: Commit**

```bash
git add app/scheduler/ app/database.py
git commit -m "feat: register interval + cron jobs in scheduler runtime"
```

---

## Task 19: End-to-End Proactive Smoke Test

**Files:**
- Create: `tests/test_e2e_proactive_smoke.py`

- [ ] **Step 19.1: Write smoke**

Create `tests/test_e2e_proactive_smoke.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.event import Event
from app.models.reminder import Reminder
from app.models.task import Task
from app.models.user import User


async def test_full_task_to_reminder_to_completion(client, session, monkeypatch):
    """Walks: create user via lark webhook → user creates a task with deadline →
    scan_reminders fires checkin_1 → user replies 'done' → task marked done + reminder cancelled."""

    # Stub the LLM router so we can script responses
    think_script = [
        # Turn 1: user sends "hi" — orchestrator already creates user + welcome via webhook
        # (welcome path runs REACT only, no THINK)
        # Turn 2: real user message "add task X due in 1 minute" — full pipeline
        {
            "intent": "add task",
            "actions": [{
                "type": "create_task",
                "params": {
                    "title": "fast task",
                    "deadline": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
                },
            }],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "confirm", "reasoning": "",
        },
        # Turn 3: user replies "done" — full pipeline interprets confirmation
        # (TaskId injected at test time)
        {
            "intent": "confirm done",
            "actions": [{"type": "complete_task", "params": {"task_id": None}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "celebrate briefly", "reasoning": "",
        },
    ]
    react_script = ["Hi! What's your wake-up time?", "Got it.", "Nice ✊"]

    class _Router:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            return think_script.pop(0)
        async def complete(self, task_type, messages, **kw):
            return react_script.pop(0)

    monkeypatch.setattr("app.routers.lark_webhook.LLMRouter", _Router)
    monkeypatch.setattr("app.routers.lark_webhook.settings.proactive_dry_run", True)
    monkeypatch.setattr("app.scheduler.jobs._push_to_lark", lambda *a, **kw: True_async())

    async def True_async(): return True

    # Step 1: new user → welcome
    payload_new = {
        "schema": "2.0",
        "header": {"event_id": "e1", "event_type": "im.message.receive_v1", "token": "test-verify-token"},
        "event": {"sender": {"sender_id": {"open_id": "open_smoke"}},
                  "message": {"message_id": "m1", "message_type": "text", "content": '{"text":"hi"}'}},
    }
    r = await client.post("/api/lark/webhook", json=payload_new)
    assert r.status_code == 200
    user = (await session.execute(select(User).where(User.lark_user_id == "open_smoke"))).scalar_one()

    # Step 2: user adds a task — webhook path → orchestrator.handle
    payload_task = {
        "schema": "2.0",
        "header": {"event_id": "e2", "event_type": "im.message.receive_v1", "token": "test-verify-token"},
        "event": {"sender": {"sender_id": {"open_id": "open_smoke"}},
                  "message": {"message_id": "m2", "message_type": "text", "content": '{"text":"add task fast"}'}},
    }
    r = await client.post("/api/lark/webhook", json=payload_task)
    assert r.status_code == 200
    task = (await session.execute(select(Task).where(Task.user_id == user.id))).scalar_one()
    assert task.title == "fast task"

    # A pending task_checkin_1 should exist for this task
    rems = (await session.execute(select(Reminder).where(Reminder.linked_task_id == task.id))).scalars().all()
    assert any(r.type == "task_checkin_1" and r.status == "pending" for r in rems)

    # Inject task_id into next THINK response
    think_script[0]["actions"][0]["params"]["task_id"] = task.id

    # Step 3: user replies "done" — full pipeline → complete_task
    payload_done = {
        "schema": "2.0",
        "header": {"event_id": "e3", "event_type": "im.message.receive_v1", "token": "test-verify-token"},
        "event": {"sender": {"sender_id": {"open_id": "open_smoke"}},
                  "message": {"message_id": "m3", "message_type": "text", "content": '{"text":"done"}'}},
    }
    r = await client.post("/api/lark/webhook", json=payload_done)
    assert r.status_code == 200

    await session.refresh(task)
    assert task.status == "done"
    # Reminder cancelled
    rem1 = (await session.execute(
        select(Reminder).where(Reminder.linked_task_id == task.id, Reminder.type == "task_checkin_1")
    )).scalar_one()
    assert rem1.status == "cancelled"

    # Events: flow_started, welcome_sent, task_created, task_completed
    events = (await session.execute(select(Event).where(Event.user_id == user.id).order_by(Event.id))).scalars().all()
    types = [e.type for e in events]
    assert "flow_started" in types
    assert "welcome_sent" in types
    assert "task_created" in types
    assert "task_completed" in types
```

- [ ] **Step 19.2: Run, expect PASS**

```bash
pytest tests/test_e2e_proactive_smoke.py -v
```

If failures arise, the test exercises every Spec 2 path. Debug carefully — most likely cause is webhook payload parsing or a stubbing miss.

- [ ] **Step 19.3: Cumulative**

```bash
pytest tests/ -q
```

- [ ] **Step 19.4: Commit**

```bash
git add tests/test_e2e_proactive_smoke.py
git commit -m "test: end-to-end proactive smoke (webhook → reminder → completion)"
```

---

## Task 20: Live Sanity Check

This is a manual smoke test, not automated. Requires a real Lark app configured with the env vars in `.env`.

- [ ] **Step 20.1: Start the backend**

```bash
source .venv/bin/activate
PA_PROACTIVE_DRY_RUN=true PA_ENABLE_SCHEDULER=true uvicorn app.main:app --port 8001 > /tmp/pa-sanity.log 2>&1 &
sleep 4
curl -s http://localhost:8001/health
```

Expected: `{"status":"ok"}` and scheduler started log lines:

```bash
grep -i scheduler /tmp/pa-sanity.log
```

- [ ] **Step 20.2: Exercise webhook with a synthetic Lark event**

```bash
curl -s -X POST http://localhost:8001/api/lark/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "schema":"2.0",
    "header":{"event_id":"manual1","event_type":"im.message.receive_v1","token":"'"$PA_LARK_VERIFICATION_TOKEN"'"},
    "event":{"sender":{"sender_id":{"open_id":"open_test_user_1"}},
             "message":{"message_id":"mid1","message_type":"text","content":"{\"text\":\"hello assistant\"}"}}
  }' | python3 -m json.tool
```

Expected: 200 OK. Check `psql -d my_assistant -c "SELECT * FROM users WHERE lark_user_id='open_test_user_1';"` — user exists. Check `events` — `welcome_sent` and `flow_started` present.

Because `PA_PROACTIVE_DRY_RUN=true`, no actual Lark push happens; the welcome text is in the `conversations.assistant` row.

- [ ] **Step 20.3: Force a morning brief**

In a Python REPL:

```bash
python3 - <<'EOF'
import asyncio
from app.database import async_session_factory
from app.scheduler.jobs import send_morning_brief_once, _build_orchestrator

async def main():
    async with async_session_factory() as session:
        orch = await _build_orchestrator(session)
        # Use user_id 1 or whoever exists
        result = await send_morning_brief_once(session, user_id=1, orchestrator=orch)
        print("morning brief sent:", result)

asyncio.run(main())
EOF
```

Expected: prints `morning brief sent: True` if it was the first time today, else `False`. Verify `events.type='morning_brief_sent'` row appears.

- [ ] **Step 20.4: Stop the backend**

```bash
pkill -f "uvicorn app.main"
```

- [ ] **Step 20.5: Optional — turn off dry-run + send for real**

When you're confident, retry Step 20.2 with `PA_PROACTIVE_DRY_RUN=false` and watch the Lark client receive the message. Don't blast yourself with reminders during testing — set `PA_ENABLE_SCHEDULER=false` if you only want to exercise the webhook.

No commit needed (configuration-only exercise).

---

## Plan Summary

After completing tasks:

- ✅ APScheduler in-process worker (Tasks 1, 12, 18)
- ✅ Real Lark client wired into webhook (Task 8)
- ✅ New-user welcome flow (Tasks 4, 8)
- ✅ LarkBot slimmed down (Task 7)
- ✅ Trigger pydantic models (Task 2)
- ✅ `send_proactive` (Task 4)
- ✅ REACT trigger payload + persona addenda (Task 3)
- ✅ THINK prompt extensions for onboarding + check-in (Task 10)
- ✅ `user_expectations` field in onboarding (Task 9)
- ✅ `load_context` loads goals + habits (Task 5)
- ✅ Auto-schedule first check-in + cancel on completion (Task 11)
- ✅ `scan_reminders_once` + check-in cascade (Tasks 13, 14)
- ✅ Morning brief (Task 15)
- ✅ Evening recap with Opus (Task 16)
- ✅ Hourly user-timezone dispatcher (Task 17)
- ✅ End-to-end smoke (Task 19)
- ✅ Live sanity check (Task 20)

Next: Spec 3 — Memory refinement (consolidation, vector search, confidence decay).
