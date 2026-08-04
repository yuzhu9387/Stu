# Infrastructure Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `personal-assistant` so all user mutations flow through one `POST /api/conversation` endpoint backed by a `think → act → react` pipeline; ship the supporting infrastructure (LiteLLM router, persona module, events log, cleaned-up DB).

**Architecture:** A new `app/orchestrator/` package runs each turn through THINK (Haiku, JSON-out) → atomic action execution + event emission → REACT (Sonnet, persona, upgrades to Opus when THINK flags high complexity). LiteLLM abstracts the provider. The existing `app/dialogue/` state machine, ad-hoc LLM service, and four unused tables are deleted.

**Tech Stack:** Python 3.10 · FastAPI · SQLAlchemy 2 async + asyncpg (prod) / aiosqlite (test) · Alembic · LiteLLM · Pydantic v2 · pytest + pytest-asyncio + httpx

**Spec:** `docs/superpowers/specs/2026-05-20-infrastructure-bundle-design.md`

---

## Pre-flight

Before starting, the working tree has uncommitted modifications in files this plan rewrites/deletes (`app/services/llm.py`, `app/routers/chat.py`, `app/config.py`, `pyproject.toml`). Decide one:

- [ ] **Option A:** Commit the in-flight work first (`git add -p` then commit) so this plan is a clean base.
- [ ] **Option B:** Stash it (`git stash push -m "pre-infra-bundle"`) and apply later if still relevant.
- [ ] **Option C:** Discard if obsolete (`git checkout -- <files>`) — only if you're sure.

Also make sure the dev servers from the earlier session are stopped if they conflict:

```
pkill -f "uvicorn app.main"
pkill -f "vite"
```

The local Postgres `my_assistant` DB is currently empty — schema changes carry zero data-migration risk.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `app/llm/__init__.py` | package marker |
| `app/llm/config.py` | task_type → model resolution; env-var overrides |
| `app/llm/router.py` | `LLMRouter` — thin LiteLLM wrapper, `complete()` and `complete_json()` |
| `app/persona.py` | `PERSONA_REACT` string + `load_persona(user_name)` |
| `app/schemas/preferences.py` | Pydantic models for `users.preferences` jsonb (Profile, Pattern, UserPreferences) |
| `app/models/event.py` | `Event` ORM model |
| `app/orchestrator/__init__.py` | exports `ConversationOrchestrator` |
| `app/orchestrator/actions.py` | `ActionType` enum + per-type Pydantic param schemas |
| `app/orchestrator/flows.py` | `FieldDef`, `FlowDefinition`, `ONBOARDING` |
| `app/orchestrator/context.py` | `Context` dataclass + `load_context()` |
| `app/orchestrator/think.py` | `think(ctx, message, llm)` → `ThinkResult` |
| `app/orchestrator/act.py` | `ActionExecutor` (dispatch + atomic event emission) |
| `app/orchestrator/react.py` | `react(ctx, message, action_results, hint, llm, complexity)` → str |
| `app/orchestrator/conversation.py` | `ConversationOrchestrator` (top-level pipeline) |
| `app/orchestrator/prompts/think.md` | THINK+PLAN system prompt |
| `app/orchestrator/prompts/react.md` | REACT system prompt (persona + framing) |
| `app/routers/conversation.py` | `POST /api/conversation` endpoint |
| `alembic/versions/<rev>_infra_bundle.py` | one migration applying all schema changes |
| `tests/test_llm/test_router.py` | LLMRouter tests |
| `tests/test_persona.py` | persona tests |
| `tests/test_orchestrator/test_actions.py` | action schema tests |
| `tests/test_orchestrator/test_flows.py` | flow config tests |
| `tests/test_orchestrator/test_context.py` | context loader tests |
| `tests/test_orchestrator/test_act.py` | action executor + atomicity |
| `tests/test_orchestrator/test_think.py` | THINK with mocked LLM |
| `tests/test_orchestrator/test_react.py` | REACT with mocked LLM |
| `tests/test_orchestrator/test_conversation.py` | orchestrator wiring |
| `tests/test_routers/test_conversation.py` | endpoint integration |
| `tests/test_models/test_event.py` | event model |
| `tests/test_schemas_preferences.py` | preferences schema |
| `tests/test_e2e_smoke.py` | end-to-end happy path |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | add `litellm>=1.50.0` |
| `app/config.py` | add `PA_LLM_THINK_MODEL`, `PA_LLM_REACT_MODEL`, `PA_LLM_REASONING_MODEL` env defaults |
| `app/models/task.py` | add `habit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("habits.id"))` |
| `app/models/time_slot.py` | add `date` column; drop `daily_plan_id` |
| `app/models/__init__.py` | import `Event`; remove deleted models |
| `app/main.py` | register `conversation.router`; drop deleted routers |
| `app/routers/tasks.py` | strip POST/PATCH/DELETE — GET only |
| `app/routers/goals.py` | strip POST/PATCH/DELETE — GET only |
| `app/routers/habits.py` | strip POST/PATCH/DELETE — GET only |
| `app/routers/plans.py` | strip POST/PATCH/DELETE — GET only |

### Deleted files

| Path | Reason |
|---|---|
| `app/services/llm.py` | replaced by `app/llm/router.py` |
| `app/services/meeting_notes.py` | feature out of scope |
| `app/engines/conversation.py` | replaced by orchestrator |
| `app/engines/task_extractor.py` | LLM produces actions directly |
| `app/dialogue/` (whole dir) | state machine replaced by declarative flows + LLM-driven asking |
| `app/routers/chat.py` | replaced by `conversation.py` |
| `app/routers/meeting_notes.py` | feature out of scope |
| `app/models/plan.py` | `daily_plans` table dropped |
| `app/models/time_entry.py` | `time_entries` table dropped |
| `app/models/meeting_note.py` | `meeting_notes` table dropped |
| `tests/test_dialogue/` | dialogue/ deleted |
| `tests/test_routers/test_chat.py` | chat.py deleted |
| `tests/test_routers/test_meeting_notes.py` | router deleted |
| `tests/test_services/test_meeting_notes.py` | service deleted |
| `tests/test_models/test_plan.py` (if exists) | model deleted |
| `tests/test_models/test_time_entry.py` (if exists) | model deleted |
| `tests/test_models/test_meeting_note.py` (if exists) | model deleted |

---

## Task 1: DB Migration & Model Updates

**Files:**
- Modify: `app/models/task.py`
- Modify: `app/models/time_slot.py`
- Create: `app/models/event.py`
- Modify: `app/models/__init__.py`
- Delete: `app/models/plan.py`, `app/models/time_entry.py`, `app/models/meeting_note.py`
- Create: `alembic/versions/<rev>_infra_bundle.py`
- Test: `tests/test_models/test_event.py`

- [ ] **Step 1.1: Add `habit_id` FK to Task model**

Open `app/models/task.py` and add `habit_id` alongside existing `goal_id`:

```python
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Interval, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    quadrant: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    priority_score: Mapped[Optional[float]] = mapped_column(Float)
    estimated_duration: Mapped[Optional[timedelta]] = mapped_column(Interval)
    actual_duration: Mapped[Optional[timedelta]] = mapped_column(Interval)
    deadline: Mapped[Optional[datetime]] = mapped_column()
    source: Mapped[Optional[str]] = mapped_column(String(20), default="manual")
    goal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("goals.id"))
    habit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("habits.id"))
    parent_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 1.2: Update `time_slot.py` — add `date`, drop `daily_plan_id`**

Read current file first to preserve other fields, then rewrite:

```bash
cat app/models/time_slot.py
```

Then edit. The result should keep all existing fields except `daily_plan_id`, and add `date`:

```python
from datetime import date as date_type, datetime, time, timezone
from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TimeSlot(Base):
    __tablename__ = "time_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    date: Mapped[date_type] = mapped_column()
    start_time: Mapped[time] = mapped_column()
    end_time: Mapped[time] = mapped_column()
    slot_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    linked_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tasks.id"))
    linked_habit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("habits.id"))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
```

(Adjust to match the existing column set; only the `daily_plan_id` removal and `date` addition are mandatory.)

- [ ] **Step 1.3: Create the Event model**

Create `app/models/event.py`:

```python
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import JSONVariant


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


Index("ix_events_entity", Event.entity_type, Event.entity_id)
```

- [ ] **Step 1.4: Write Event model test**

Create `tests/test_models/test_event.py`:

```python
import pytest
from app.models.event import Event
from app.models.user import User


async def test_event_persists_with_payload(session):
    user = User(name="A", lark_user_id="evt_u1")
    session.add(user)
    await session.commit()
    ev = Event(
        user_id=user.id,
        type="task_created",
        entity_type="task",
        entity_id=42,
        payload={"title": "test"},
    )
    session.add(ev)
    await session.commit()
    await session.refresh(ev)
    assert ev.id is not None
    assert ev.payload["title"] == "test"
    assert ev.created_at is not None
```

- [ ] **Step 1.5: Run model test — expect failure (Event not yet imported by __init__)**

```bash
source .venv/bin/activate
pytest tests/test_models/test_event.py -v
```

Expected: passes if Event is importable. If `tests/conftest.py`'s `Base.metadata.create_all` doesn't see Event, ensure `app/models/__init__.py` imports it (next step).

- [ ] **Step 1.6: Update `app/models/__init__.py`**

Read current contents:

```bash
cat app/models/__init__.py
```

Add `from app.models.event import Event` and **remove** any `from app.models.plan import ...`, `from app.models.time_entry import ...`, `from app.models.meeting_note import ...`. Make sure existing imports of remaining models stay.

- [ ] **Step 1.7: Delete dropped model files**

```bash
rm app/models/plan.py app/models/time_entry.py app/models/meeting_note.py
rm -rf tests/test_models/test_plan.py tests/test_models/test_time_entry.py tests/test_models/test_meeting_note.py 2>/dev/null || true
```

- [ ] **Step 1.8: Re-run all model tests, see what breaks**

```bash
pytest tests/test_models/ -v
```

Expected: `test_event.py` passes. Some other tests may still reference deleted models; fix or delete them in this step. For each failing test that imports a deleted model, delete the test file (it's testing code we just removed).

- [ ] **Step 1.9: Generate Alembic migration scaffold**

```bash
alembic revision -m "infra bundle: add events, drop daily_plans/habit_records/time_entries/meeting_notes, add task.habit_id, time_slots.date"
```

Note the resulting file path; let's call it `alembic/versions/<rev>_infra_bundle.py`.

- [ ] **Step 1.10: Write the Alembic upgrade()/downgrade()**

Open the new migration file and replace `upgrade()`/`downgrade()` with:

```python
"""infra bundle ..."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "<rev>"  # leave as generated
down_revision: Union[str, None] = "c05044bcb82c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. events
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("type", sa.String(50), nullable=False, index=True),
        sa.Column("entity_type", sa.String(20), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("payload", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )
    op.create_index("ix_events_entity", "events", ["entity_type", "entity_id"])

    # 2. task.habit_id FK
    op.add_column("tasks", sa.Column("habit_id", sa.Integer(), sa.ForeignKey("habits.id"), nullable=True))

    # 3. time_slots: add date, drop daily_plan_id
    op.add_column("time_slots", sa.Column("date", sa.Date(), nullable=True))
    # populate date from existing daily_plans rows if any, then enforce NOT NULL
    op.execute(
        "UPDATE time_slots ts SET date = dp.date FROM daily_plans dp WHERE ts.daily_plan_id = dp.id"
    )
    op.alter_column("time_slots", "date", nullable=False)
    op.drop_constraint("time_slots_daily_plan_id_fkey", "time_slots", type_="foreignkey")
    op.drop_column("time_slots", "daily_plan_id")

    # 4. drop tables
    op.drop_table("habit_records")
    op.drop_table("time_entries")
    op.drop_table("meeting_notes")
    op.drop_table("daily_plans")


def downgrade() -> None:
    # Best-effort reverse. Tables recreated empty.
    op.create_table(
        "daily_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.add_column("time_slots", sa.Column("daily_plan_id", sa.Integer(), sa.ForeignKey("daily_plans.id"), nullable=True))
    op.drop_column("time_slots", "date")
    op.drop_column("tasks", "habit_id")
    op.drop_index("ix_events_entity", table_name="events")
    op.drop_table("events")
    # habit_records, time_entries, meeting_notes downgrades intentionally left as TODO
    # if needed, regenerate from initial migration's definitions
```

(Adjust column lists to actually match the dropped tables if you intend full reversibility; for MVP, lossy downgrade is acceptable since the DB is empty.)

- [ ] **Step 1.11: Run migration up & verify schema**

```bash
alembic upgrade head
psql -d my_assistant -c "\dt"
psql -d my_assistant -c "\d events"
psql -d my_assistant -c "\d tasks"
psql -d my_assistant -c "\d time_slots"
```

Expected:
- `\dt` shows `events` present and `daily_plans`, `habit_records`, `time_entries`, `meeting_notes` absent
- `tasks` has `habit_id` column
- `time_slots` has `date` column and no `daily_plan_id`

- [ ] **Step 1.12: Commit**

```bash
git add app/models/event.py app/models/task.py app/models/time_slot.py app/models/__init__.py alembic/versions/ tests/test_models/test_event.py
git rm app/models/plan.py app/models/time_entry.py app/models/meeting_note.py 2>/dev/null || true
git commit -m "feat: events table, task.habit_id FK, time_slots.date; drop unused tables"
```

---

## Task 2: LiteLLM Router

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/config.py`
- Create: `app/llm/__init__.py`
- Create: `app/llm/config.py`
- Create: `app/llm/router.py`
- Test: `tests/test_llm/__init__.py`, `tests/test_llm/test_router.py`

- [ ] **Step 2.1: Add litellm to pyproject.toml**

In `pyproject.toml`, under `dependencies = [...]`, append:

```
    "litellm>=1.50.0",
```

Then install:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 2.2: Extend `app/config.py` with LLM model env vars**

Read current contents (you saw them earlier). Add the three model fields:

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

    model_config = {"env_prefix": "PA_", "env_file": ".env"}


settings = Settings()
```

(Delete the old `llm_model` field; it's no longer used. If the in-flight uncommitted change to `config.py` adds fields, merge them in.)

- [ ] **Step 2.3: Create `app/llm/config.py`**

```python
from typing import Literal
from app.config import settings

TaskType = Literal["think", "react", "reasoning"]


def resolve_model(task_type: TaskType) -> str:
    return {
        "think": settings.llm_think_model,
        "react": settings.llm_react_model,
        "reasoning": settings.llm_reasoning_model,
    }[task_type]
```

- [ ] **Step 2.4: Create `app/llm/__init__.py`**

```python
from app.llm.router import LLMRouter

__all__ = ["LLMRouter"]
```

- [ ] **Step 2.5: Write failing test for resolve_model**

Create `tests/test_llm/__init__.py` (empty) and `tests/test_llm/test_router.py`:

```python
import pytest
from app.llm.config import resolve_model
from app.llm.router import LLMRouter


def test_resolve_model_default_think():
    assert "haiku" in resolve_model("think").lower()


def test_resolve_model_default_react():
    assert "sonnet" in resolve_model("react").lower()


def test_resolve_model_invalid_raises():
    with pytest.raises(KeyError):
        resolve_model("bogus")  # type: ignore[arg-type]
```

- [ ] **Step 2.6: Run resolve_model tests — expect FAIL (router.py not yet importable)**

```bash
pytest tests/test_llm/test_router.py -v
```

Expected: ImportError because LLMRouter isn't defined yet.

- [ ] **Step 2.7: Create `app/llm/router.py`**

```python
from __future__ import annotations
import json
from typing import Any, Optional

import litellm

from app.config import settings
from app.llm.config import TaskType, resolve_model


class LLMError(Exception):
    """Raised when LLM call or response parsing fails."""


class LLMRouter:
    """Thin async LiteLLM wrapper with task-type → model resolution."""

    def __init__(self, *, api_key: Optional[str] = None):
        self._api_key = api_key or settings.anthropic_api_key

    async def complete(
        self,
        task_type: TaskType,
        messages: list[dict],
        max_tokens: int = 1500,
        response_format: Optional[dict] = None,
    ) -> str:
        model = resolve_model(task_type)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as e:
            raise LLMError(f"LLM call failed: {e}") from e
        return response.choices[0].message.content

    async def complete_json(
        self,
        task_type: TaskType,
        messages: list[dict],
        max_tokens: int = 1500,
    ) -> dict:
        text = await self.complete(
            task_type,
            messages,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM did not return valid JSON: {text[:200]}") from e
```

- [ ] **Step 2.8: Re-run resolve_model tests — expect PASS**

```bash
pytest tests/test_llm/test_router.py::test_resolve_model_default_think -v
pytest tests/test_llm/test_router.py::test_resolve_model_default_react -v
```

Expected: both pass.

- [ ] **Step 2.9: Add a router behavior test with monkeypatched litellm**

Append to `tests/test_llm/test_router.py`:

```python
class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


async def test_complete_returns_text(monkeypatch):
    async def fake_acompletion(**kwargs):
        assert kwargs["model"]  # was resolved
        return _FakeResponse("hello")
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    out = await router.complete("react", [{"role": "user", "content": "hi"}])
    assert out == "hello"


async def test_complete_json_parses(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse('{"intent": "test", "actions": []}')
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    out = await router.complete_json("think", [{"role": "user", "content": "hi"}])
    assert out["intent"] == "test"


async def test_complete_json_strips_codefences(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse('```json\n{"ok": true}\n```')
    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    router = LLMRouter(api_key="x")
    out = await router.complete_json("think", [{"role": "user", "content": "hi"}])
    assert out["ok"] is True
```

- [ ] **Step 2.10: Run all router tests**

```bash
pytest tests/test_llm/ -v
```

Expected: all pass.

- [ ] **Step 2.11: Commit**

```bash
git add pyproject.toml app/config.py app/llm/ tests/test_llm/
git commit -m "feat: LiteLLM router with task-type model resolution"
```

---

## Task 3: Persona Module

**Files:**
- Create: `app/persona.py`
- Test: `tests/test_persona.py`

- [ ] **Step 3.1: Write failing persona test**

Create `tests/test_persona.py`:

```python
from app.persona import PERSONA_REACT, load_persona


def test_persona_has_core_traits():
    text = PERSONA_REACT.lower()
    for trait in ["altruistic", "reliable", "boundary", "concise"]:
        assert trait in text


def test_load_persona_substitutes_name():
    rendered = load_persona("Alice")
    assert "Alice" in rendered
    assert "{user_name}" not in rendered


def test_load_persona_default_name():
    rendered = load_persona()
    assert "{user_name}" not in rendered
```

- [ ] **Step 3.2: Run test — expect FAIL**

```bash
pytest tests/test_persona.py -v
```

Expected: ImportError.

- [ ] **Step 3.3: Create `app/persona.py`**

```python
PERSONA_REACT = """You are {user_name}'s personal assistant.

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
"""


def load_persona(user_name: str = "the user") -> str:
    return PERSONA_REACT.format(user_name=user_name)
```

- [ ] **Step 3.4: Run test — expect PASS**

```bash
pytest tests/test_persona.py -v
```

Expected: all pass.

- [ ] **Step 3.5: Commit**

```bash
git add app/persona.py tests/test_persona.py
git commit -m "feat: persona module for REACT system prompt"
```

---

## Task 4: User Preferences Pydantic Schema

**Files:**
- Create: `app/schemas/preferences.py`
- Test: `tests/test_schemas_preferences.py`

- [ ] **Step 4.1: Write failing test**

Create `tests/test_schemas_preferences.py`:

```python
from datetime import datetime
from app.schemas.preferences import Profile, Pattern, UserPreferences


def test_profile_optional_fields():
    p = Profile()
    assert p.name is None
    assert p.wake_up is None


def test_user_preferences_round_trip():
    raw = {
        "profile": {"name": "Yuzhu", "wake_up": "07:00"},
        "procedural": [
            {"pattern": "no 7am pings", "confidence": 0.8, "learned_at": "2026-05-20T10:00:00"}
        ],
        "onboarding_status": "in_progress",
    }
    prefs = UserPreferences.model_validate(raw)
    assert prefs.profile.name == "Yuzhu"
    assert prefs.procedural[0].pattern == "no 7am pings"
    assert prefs.onboarding_status == "in_progress"
    # round-trip
    dumped = prefs.model_dump()
    again = UserPreferences.model_validate(dumped)
    assert again.profile.name == "Yuzhu"


def test_user_preferences_empty_default():
    prefs = UserPreferences()
    assert prefs.profile.name is None
    assert prefs.procedural == []
    assert prefs.onboarding_status == "pending"
```

- [ ] **Step 4.2: Run test — expect FAIL**

```bash
pytest tests/test_schemas_preferences.py -v
```

- [ ] **Step 4.3: Create `app/schemas/preferences.py`**

```python
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Profile(BaseModel):
    name: Optional[str] = None
    diet: Optional[str] = None
    timezone: Optional[str] = None
    wake_up: Optional[str] = None
    work_start: Optional[str] = None
    peak_hours_start: Optional[str] = None
    peak_hours_end: Optional[str] = None
    work_end: Optional[str] = None
    sleep_time: Optional[str] = None
    reminder_minutes_before: Optional[int] = None
    weekend_plans: Optional[bool] = None
    yearly_goals: Optional[str] = None
    daily_habits: Optional[str] = None


class Pattern(BaseModel):
    pattern: str
    confidence: float = 0.5
    learned_at: Optional[str] = None  # ISO-8601 string; ORM stores as jsonb so plain str is simplest


OnboardingStatus = Literal["pending", "in_progress", "completed"]


class UserPreferences(BaseModel):
    profile: Profile = Field(default_factory=Profile)
    procedural: list[Pattern] = Field(default_factory=list)
    onboarding_status: OnboardingStatus = "pending"

    @classmethod
    def from_jsonb(cls, raw: Optional[dict]) -> "UserPreferences":
        if not raw:
            return cls()
        return cls.model_validate(raw)
```

- [ ] **Step 4.4: Run test — expect PASS**

```bash
pytest tests/test_schemas_preferences.py -v
```

- [ ] **Step 4.5: Commit**

```bash
git add app/schemas/preferences.py tests/test_schemas_preferences.py
git commit -m "feat: typed pydantic schema for users.preferences jsonb"
```

---

## Task 5: Action Type Schemas

**Files:**
- Create: `app/orchestrator/__init__.py`
- Create: `app/orchestrator/actions.py`
- Test: `tests/test_orchestrator/__init__.py`, `tests/test_orchestrator/test_actions.py`

- [ ] **Step 5.1: Write failing test**

Create `tests/test_orchestrator/__init__.py` (empty) and `tests/test_orchestrator/test_actions.py`:

```python
import pytest
from pydantic import ValidationError
from app.orchestrator.actions import (
    ActionType,
    CreateTaskParams,
    UpdateProfileParams,
    RecordPatternParams,
    parse_action,
)


def test_create_task_params_required_title():
    with pytest.raises(ValidationError):
        CreateTaskParams()


def test_create_task_params_accepts_optional_fields():
    p = CreateTaskParams(title="x", deadline="2026-05-21", estimated_minutes=30)
    assert p.title == "x"


def test_update_profile_params():
    p = UpdateProfileParams(path="diet", value="vegetarian")
    assert p.path == "diet"


def test_record_pattern_params():
    p = RecordPatternParams(pattern="user dislikes 7am pings", confidence=0.8)
    assert p.confidence == 0.8


def test_parse_action_dispatch():
    raw = {"type": "create_task", "params": {"title": "x"}}
    parsed = parse_action(raw)
    assert parsed.type == ActionType.CREATE_TASK
    assert parsed.params.title == "x"


def test_parse_action_unknown_type_raises():
    with pytest.raises(ValueError):
        parse_action({"type": "fly_to_mars", "params": {}})
```

- [ ] **Step 5.2: Run test — expect FAIL**

```bash
pytest tests/test_orchestrator/test_actions.py -v
```

- [ ] **Step 5.3: Create `app/orchestrator/__init__.py`** (empty stub for now)

```python
# orchestrator package
```

- [ ] **Step 5.4: Create `app/orchestrator/actions.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel


class ActionType(str, Enum):
    CREATE_TASK = "create_task"
    UPDATE_TASK = "update_task"
    COMPLETE_TASK = "complete_task"
    DELETE_TASK = "delete_task"
    CREATE_GOAL = "create_goal"
    UPDATE_GOAL = "update_goal"
    ADD_HABIT = "add_habit"
    COMPLETE_HABIT = "complete_habit"
    UPDATE_PROFILE = "update_profile"
    RECORD_PATTERN = "record_pattern"
    RECORD_FEEDBACK = "record_feedback"
    START_FLOW = "start_flow"


class CreateTaskParams(BaseModel):
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None  # ISO date string
    estimated_minutes: Optional[int] = None
    quadrant: Optional[str] = None
    goal_id: Optional[int] = None
    habit_id: Optional[int] = None


class UpdateTaskParams(BaseModel):
    task_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    estimated_minutes: Optional[int] = None
    quadrant: Optional[str] = None
    status: Optional[str] = None


class CompleteTaskParams(BaseModel):
    task_id: int


class DeleteTaskParams(BaseModel):
    task_id: int


class CreateGoalParams(BaseModel):
    title: str
    description: Optional[str] = None
    target_date: Optional[str] = None


class UpdateGoalParams(BaseModel):
    goal_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    target_date: Optional[str] = None


class AddHabitParams(BaseModel):
    title: str
    frequency: Optional[str] = None  # daily / weekly / etc.
    preferred_time: Optional[str] = None
    duration_minutes: Optional[int] = None


class CompleteHabitParams(BaseModel):
    habit_id: int
    date: Optional[str] = None  # defaults to today in executor


class UpdateProfileParams(BaseModel):
    path: str           # dotted path within Profile, e.g. "diet" or "wake_up"
    value: object       # validated when applied


class RecordPatternParams(BaseModel):
    pattern: str
    confidence: float = 0.5


class RecordFeedbackParams(BaseModel):
    sentiment: Optional[str] = None  # "positive" / "negative" / "neutral"
    content: str


class StartFlowParams(BaseModel):
    flow_name: str


PARAM_REGISTRY: dict[ActionType, type[BaseModel]] = {
    ActionType.CREATE_TASK: CreateTaskParams,
    ActionType.UPDATE_TASK: UpdateTaskParams,
    ActionType.COMPLETE_TASK: CompleteTaskParams,
    ActionType.DELETE_TASK: DeleteTaskParams,
    ActionType.CREATE_GOAL: CreateGoalParams,
    ActionType.UPDATE_GOAL: UpdateGoalParams,
    ActionType.ADD_HABIT: AddHabitParams,
    ActionType.COMPLETE_HABIT: CompleteHabitParams,
    ActionType.UPDATE_PROFILE: UpdateProfileParams,
    ActionType.RECORD_PATTERN: RecordPatternParams,
    ActionType.RECORD_FEEDBACK: RecordFeedbackParams,
    ActionType.START_FLOW: StartFlowParams,
}


@dataclass
class ParsedAction:
    type: ActionType
    params: BaseModel


def parse_action(raw: dict) -> ParsedAction:
    type_str = raw.get("type")
    if not type_str:
        raise ValueError("action missing 'type'")
    try:
        action_type = ActionType(type_str)
    except ValueError as e:
        raise ValueError(f"unknown action type: {type_str}") from e
    schema = PARAM_REGISTRY[action_type]
    params = schema.model_validate(raw.get("params", {}))
    return ParsedAction(type=action_type, params=params)
```

- [ ] **Step 5.5: Run test — expect PASS**

```bash
pytest tests/test_orchestrator/test_actions.py -v
```

- [ ] **Step 5.6: Commit**

```bash
git add app/orchestrator/ tests/test_orchestrator/
git commit -m "feat: orchestrator action types and pydantic param schemas"
```

---

## Task 6: Declarative Flow Config

**Files:**
- Create: `app/orchestrator/flows.py`
- Test: `tests/test_orchestrator/test_flows.py`

- [ ] **Step 6.1: Write failing test**

Create `tests/test_orchestrator/test_flows.py`:

```python
from app.orchestrator.flows import FieldDef, FlowDefinition, ONBOARDING, get_flow


def test_onboarding_has_expected_fields():
    names = {f.name for f in ONBOARDING.required_fields}
    assert "wake_up" in names
    assert "yearly_goals" in names
    assert "daily_habits" in names


def test_field_def_carries_description():
    f = FieldDef("wake_up", type="time", description="wake-up time")
    assert f.description == "wake-up time"


def test_get_flow_by_name():
    assert get_flow("onboarding") is ONBOARDING
    assert get_flow("nope") is None


def test_missing_fields_helper():
    filled = {"wake_up": "07:00", "work_start": "09:00"}
    missing = ONBOARDING.missing_fields(filled)
    names = {f.name for f in missing}
    assert "wake_up" not in names
    assert "yearly_goals" in names
```

- [ ] **Step 6.2: Run test — expect FAIL**

```bash
pytest tests/test_orchestrator/test_flows.py -v
```

- [ ] **Step 6.3: Create `app/orchestrator/flows.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional


FieldType = Literal["time", "time_range", "text", "number", "boolean", "date"]


@dataclass(frozen=True)
class FieldDef:
    name: str
    type: FieldType
    description: str


@dataclass(frozen=True)
class FlowDefinition:
    name: str
    required_fields: tuple[FieldDef, ...]

    def missing_fields(self, filled: dict) -> list[FieldDef]:
        return [f for f in self.required_fields if f.name not in filled or filled[f.name] is None]

    def is_complete(self, filled: dict) -> bool:
        return not self.missing_fields(filled)


ONBOARDING = FlowDefinition(
    name="onboarding",
    required_fields=(
        FieldDef("wake_up", "time", "wake-up time"),
        FieldDef("work_start", "time", "work-start time"),
        FieldDef("peak_hours_start", "time", "start of deep-work window"),
        FieldDef("peak_hours_end", "time", "end of deep-work window"),
        FieldDef("work_end", "time", "work-end time"),
        FieldDef("sleep_time", "time", "bedtime"),
        FieldDef("daily_habits", "text", "daily routines / habits"),
        FieldDef("yearly_goals", "text", "main goals for this year"),
    ),
)


_REGISTRY: dict[str, FlowDefinition] = {ONBOARDING.name: ONBOARDING}


def get_flow(name: str) -> Optional[FlowDefinition]:
    return _REGISTRY.get(name)
```

- [ ] **Step 6.4: Run test — expect PASS**

```bash
pytest tests/test_orchestrator/test_flows.py -v
```

- [ ] **Step 6.5: Commit**

```bash
git add app/orchestrator/flows.py tests/test_orchestrator/test_flows.py
git commit -m "feat: declarative flow definitions replacing dialogue state machine"
```

---

## Task 7: Context Loader

**Files:**
- Create: `app/orchestrator/context.py`
- Test: `tests/test_orchestrator/test_context.py`

- [ ] **Step 7.1: Write failing test**

Create `tests/test_orchestrator/test_context.py`:

```python
from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.task import Task
from app.models.user import User
from app.orchestrator.context import load_context


async def test_load_context_minimal_user(session):
    u = User(name="A", lark_user_id="ctx_u1", preferences={})
    session.add(u)
    await session.commit()
    ctx = await load_context(u.id, session)
    assert ctx.user_id == u.id
    assert ctx.user_name == "A"
    assert ctx.profile.name is None
    assert ctx.recent_turns == []
    assert ctx.active_flow is None


async def test_load_context_includes_recent_turns(session):
    u = User(name="B", lark_user_id="ctx_u2", preferences={})
    session.add(u)
    await session.commit()
    for i in range(15):
        session.add(Conversation(user_id=u.id, role="user", content=f"msg{i}"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert len(ctx.recent_turns) == 10  # capped
    assert ctx.recent_turns[-1]["content"] == "msg14"


async def test_load_context_active_flow_with_missing_fields(session):
    u = User(
        name="C",
        lark_user_id="ctx_u3",
        preferences={
            "profile": {"wake_up": "07:00"},
            "procedural": [],
            "onboarding_status": "in_progress",
        },
    )
    session.add(u)
    await session.commit()
    session.add(DialogueSession(user_id=u.id, flow_type="onboarding", status="active"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert ctx.active_flow == "onboarding"
    assert "wake_up" in ctx.flow_filled_fields
    assert any(f.name == "yearly_goals" for f in ctx.flow_missing_fields)


async def test_load_context_open_tasks_capped(session):
    u = User(name="D", lark_user_id="ctx_u4", preferences={})
    session.add(u)
    await session.commit()
    for i in range(8):
        session.add(Task(user_id=u.id, title=f"t{i}", status="pending"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert len(ctx.open_tasks) == 5
```

- [ ] **Step 7.2: Run — expect FAIL (context.py absent)**

```bash
pytest tests/test_orchestrator/test_context.py -v
```

- [ ] **Step 7.3: Create `app/orchestrator/context.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.dialogue_session import DialogueSession
from app.models.task import Task
from app.models.user import User
from app.orchestrator.flows import FieldDef, get_flow
from app.schemas.preferences import Profile, Pattern, UserPreferences

RECENT_TURNS_LIMIT = 10
OPEN_TASKS_LIMIT = 5


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


async def load_context(user_id: int, session: AsyncSession) -> Context:
    user = await session.get(User, user_id)
    if user is None:
        raise ValueError(f"user {user_id} not found")

    prefs = UserPreferences.from_jsonb(user.preferences or {})

    # active flow
    flow_q = (
        select(DialogueSession)
        .where(DialogueSession.user_id == user_id, DialogueSession.status == "active")
        .order_by(desc(DialogueSession.id))
        .limit(1)
    )
    flow_row = (await session.execute(flow_q)).scalar_one_or_none()
    active_flow_name = flow_row.flow_type if flow_row else None

    flow_filled: dict = {}
    flow_missing: list[FieldDef] = []
    if active_flow_name:
        flow_def = get_flow(active_flow_name)
        if flow_def is not None:
            profile_dict = prefs.profile.model_dump(exclude_none=True)
            flow_filled = {
                f.name: profile_dict[f.name]
                for f in flow_def.required_fields
                if f.name in profile_dict
            }
            flow_missing = flow_def.missing_fields(flow_filled)

    # recent conversation turns
    turns_q = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(desc(Conversation.id))
        .limit(RECENT_TURNS_LIMIT)
    )
    turns_rows = (await session.execute(turns_q)).scalars().all()
    recent_turns = [
        {"role": t.role, "content": t.content, "intent": t.intent}
        for t in reversed(turns_rows)
    ]

    # open tasks
    tasks_q = (
        select(Task)
        .where(Task.user_id == user_id, Task.status.in_(["pending", "in_progress"]))
        .order_by(Task.deadline.nulls_last(), Task.id)
        .limit(OPEN_TASKS_LIMIT)
    )
    tasks_rows = (await session.execute(tasks_q)).scalars().all()
    open_tasks = [
        {"id": t.id, "title": t.title, "status": t.status, "deadline": t.deadline.isoformat() if t.deadline else None}
        for t in tasks_rows
    ]

    return Context(
        user_id=user.id,
        user_name=user.name,
        profile=prefs.profile,
        procedural_patterns=prefs.procedural,
        onboarding_status=prefs.onboarding_status,
        active_flow=active_flow_name,
        flow_filled_fields=flow_filled,
        flow_missing_fields=flow_missing,
        recent_turns=recent_turns,
        open_tasks=open_tasks,
    )
```

- [ ] **Step 7.4: Run — expect PASS**

```bash
pytest tests/test_orchestrator/test_context.py -v
```

If `Task.deadline.nulls_last()` fails on SQLite (it should work with SQLAlchemy 2 ≥ 2.0.30), fall back to `.order_by(Task.deadline.asc(), Task.id)`.

- [ ] **Step 7.5: Commit**

```bash
git add app/orchestrator/context.py tests/test_orchestrator/test_context.py
git commit -m "feat: orchestrator load_context"
```

---

## Task 8: THINK Module + Prompt

**Files:**
- Create: `app/orchestrator/prompts/think.md`
- Create: `app/orchestrator/think.py`
- Test: `tests/test_orchestrator/test_think.py`

- [ ] **Step 8.1: Write the THINK prompt**

Create `app/orchestrator/prompts/think.md`:

```markdown
You are the decision module of a personal assistant. You do NOT speak to the user directly. Your job: analyze the latest user message in context and emit a structured JSON plan.

You receive:
- User profile (semantic memory) and learned patterns (procedural memory)
- Active flow (if any) with the field list still to collect
- Last conversation turns
- A short list of the user's open tasks (for reference)
- The user's latest message

Decide:
1. What is the user's intent?
2. What state changes (actions) should result from this turn? An action is one of:
   - create_task / update_task / complete_task / delete_task
   - create_goal / update_goal
   - add_habit / complete_habit
   - update_profile  (a field under users.preferences.profile, e.g. "diet")
   - record_pattern  (a procedural pattern, e.g. "user dislikes 7am reminders")
   - record_feedback (user expressed (dis)satisfaction with the assistant)
   - start_flow     (kick off a multi-turn flow like "onboarding")
3. Does the assistant need to reply with natural language? Sometimes the user just confirms ("ok", "done") — no reply needed beyond the state change.
4. How complex is the natural-language reply, if any? "low" = a sentence or two, "high" = needs reasoning over multiple data points.

When an active flow exists and some fields are still missing, emit exactly ONE update_profile action for a field the user just answered (if any), AND set should_reply=true with reply_hint that asks the next missing field naturally.

Output ONLY a JSON object with this exact shape (no markdown code fences):

{
  "intent": "<one line>",
  "actions": [ {"type": "...", "params": { ... }}, ... ],
  "should_reply": true|false,
  "reply_complexity": "low"|"high",
  "reply_hint": "<optional brief hint for the speaking module — what tone, what to mention, what to ask next>",
  "reasoning": "<short internal trace>"
}

Use empty `actions: []` when the user is just chatting and nothing changes.
```

- [ ] **Step 8.2: Write failing tests for THINK**

Create `tests/test_orchestrator/test_think.py`:

```python
import pytest
from app.orchestrator.actions import ActionType
from app.orchestrator.context import Context
from app.orchestrator.flows import ONBOARDING
from app.orchestrator.think import ThinkResult, think
from app.schemas.preferences import Profile


class _FakeRouter:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def complete_json(self, task_type, messages, **kw):
        self.calls.append({"task_type": task_type, "messages": messages})
        return self._payload


def _empty_ctx(user_id=1, **overrides) -> Context:
    return Context(
        user_id=user_id,
        user_name="Test",
        profile=Profile(),
        procedural_patterns=[],
        onboarding_status="pending",
        active_flow=None,
        flow_filled_fields={},
        flow_missing_fields=[],
        recent_turns=[],
        open_tasks=[],
        **overrides,
    )


async def test_think_returns_structured_result():
    router = _FakeRouter({
        "intent": "user wants to add a task",
        "actions": [{"type": "create_task", "params": {"title": "buy milk"}}],
        "should_reply": True,
        "reply_complexity": "low",
        "reply_hint": "confirm in a friendly way",
        "reasoning": "explicit task request",
    })
    result = await think(_empty_ctx(), "add task buy milk", router)
    assert isinstance(result, ThinkResult)
    assert result.intent.startswith("user wants")
    assert result.actions[0].type == ActionType.CREATE_TASK
    assert result.should_reply is True
    assert result.reply_complexity == "low"


async def test_think_handles_silent_confirmation():
    router = _FakeRouter({
        "intent": "user confirms task done",
        "actions": [{"type": "complete_task", "params": {"task_id": 7}}],
        "should_reply": False,
        "reply_complexity": "low",
        "reply_hint": None,
        "reasoning": "ok response after did-you-finish",
    })
    result = await think(_empty_ctx(), "ok", router)
    assert result.should_reply is False
    assert result.actions[0].type == ActionType.COMPLETE_TASK


async def test_think_active_flow_in_messages():
    ctx = _empty_ctx(
        active_flow="onboarding",
        flow_filled_fields={"wake_up": "07:00"},
        flow_missing_fields=list(ONBOARDING.missing_fields({"wake_up": "07:00"})),
    )
    router = _FakeRouter({
        "intent": "...", "actions": [], "should_reply": True,
        "reply_complexity": "low", "reply_hint": "", "reasoning": "",
    })
    await think(ctx, "9am", router)
    msgs_str = "\n".join(m["content"] for m in router.calls[0]["messages"] if m["role"] == "user")
    assert "onboarding" in msgs_str.lower()
    assert "wake_up" in msgs_str


async def test_think_invalid_action_skipped(monkeypatch):
    router = _FakeRouter({
        "intent": "...",
        "actions": [
            {"type": "create_task", "params": {"title": "good"}},
            {"type": "fly_to_mars", "params": {}},          # invalid; should be skipped
        ],
        "should_reply": True,
        "reply_complexity": "low",
        "reply_hint": "",
        "reasoning": "",
    })
    result = await think(_empty_ctx(), "hi", router)
    assert len(result.actions) == 1
    assert result.actions[0].type == ActionType.CREATE_TASK
```

- [ ] **Step 8.3: Run — expect FAIL**

```bash
pytest tests/test_orchestrator/test_think.py -v
```

- [ ] **Step 8.4: Create `app/orchestrator/think.py`**

```python
from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from app.llm.router import LLMError, LLMRouter
from app.orchestrator.actions import ParsedAction, parse_action
from app.orchestrator.context import Context

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "think.md"
_SYSTEM_PROMPT: Optional[str] = None


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _PROMPT_PATH.read_text()
    return _SYSTEM_PROMPT


@dataclass
class ThinkResult:
    intent: str
    actions: list[ParsedAction] = field(default_factory=list)
    should_reply: bool = True
    reply_complexity: Literal["low", "high"] = "low"
    reply_hint: Optional[str] = None
    reasoning: Optional[str] = None
    raw: Optional[dict] = None


def _build_user_content(ctx: Context, message: str) -> str:
    flow_block = ""
    if ctx.active_flow:
        missing = [f.name for f in ctx.flow_missing_fields]
        flow_block = (
            f"\nActive flow: {ctx.active_flow}\n"
            f"Filled fields: {json.dumps(ctx.flow_filled_fields, ensure_ascii=False)}\n"
            f"Missing fields (ask one): {missing}\n"
        )
    profile_block = ctx.profile.model_dump_json(exclude_none=True)
    patterns_block = json.dumps([p.model_dump() for p in ctx.procedural_patterns], ensure_ascii=False)
    history = "\n".join(
        f"{t['role']}: {t['content']}" for t in ctx.recent_turns
    )
    tasks_block = json.dumps(ctx.open_tasks, ensure_ascii=False)

    return (
        f"<user_profile>{profile_block}</user_profile>\n"
        f"<learned_patterns>{patterns_block}</learned_patterns>\n"
        f"<open_tasks>{tasks_block}</open_tasks>\n"
        f"{flow_block}"
        f"<conversation_history>\n{history}\n</conversation_history>\n"
        f"<user_message>{message}</user_message>"
    )


async def think(ctx: Context, message: str, llm: LLMRouter) -> ThinkResult:
    messages = [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": _build_user_content(ctx, message)},
    ]
    try:
        raw = await llm.complete_json("think", messages)
    except LLMError as e:
        logger.warning("THINK call failed: %s", e)
        return ThinkResult(
            intent="unknown",
            actions=[],
            should_reply=True,
            reply_complexity="low",
            reply_hint="apologize, ask user to rephrase",
            reasoning=f"LLM error: {e}",
        )

    parsed_actions: list[ParsedAction] = []
    for raw_action in raw.get("actions", []) or []:
        try:
            parsed_actions.append(parse_action(raw_action))
        except (ValueError, Exception) as e:
            logger.warning("dropping invalid action %s: %s", raw_action, e)

    return ThinkResult(
        intent=raw.get("intent", ""),
        actions=parsed_actions,
        should_reply=bool(raw.get("should_reply", True)),
        reply_complexity="high" if raw.get("reply_complexity") == "high" else "low",
        reply_hint=raw.get("reply_hint"),
        reasoning=raw.get("reasoning"),
        raw=raw,
    )
```

- [ ] **Step 8.5: Run — expect PASS**

```bash
pytest tests/test_orchestrator/test_think.py -v
```

- [ ] **Step 8.6: Commit**

```bash
git add app/orchestrator/think.py app/orchestrator/prompts/think.md tests/test_orchestrator/test_think.py
git commit -m "feat: THINK module with structured JSON output from LLM"
```

---

## Task 9: ACT Module (Atomic Dispatch + Events)

**Files:**
- Create: `app/orchestrator/act.py`
- Test: `tests/test_orchestrator/test_act.py`

- [ ] **Step 9.1: Write failing test for happy path**

Create `tests/test_orchestrator/test_act.py`:

```python
import pytest
from sqlalchemy import select

from app.models.event import Event
from app.models.task import Task
from app.models.user import User
from app.orchestrator.act import ActionExecutor
from app.orchestrator.actions import (
    ActionType,
    CompleteTaskParams,
    CreateTaskParams,
    ParsedAction,
    RecordPatternParams,
    UpdateProfileParams,
)


async def _make_user(session, name="A", lark="act_u"):
    u = User(name=name, lark_user_id=lark, preferences={})
    session.add(u)
    await session.commit()
    return u


async def test_create_task_action_writes_task_and_event(session):
    user = await _make_user(session)
    executor = ActionExecutor(session)
    actions = [ParsedAction(ActionType.CREATE_TASK, CreateTaskParams(title="x"))]
    results = await executor.execute_all(user.id, actions, conversation_id=None)
    assert results[0].entity_type == "task"
    assert results[0].entity_id is not None

    tasks = (await session.execute(select(Task))).scalars().all()
    assert len(tasks) == 1 and tasks[0].title == "x"
    events = (await session.execute(select(Event))).scalars().all()
    assert len(events) == 1
    assert events[0].type == "task_created"
    assert events[0].entity_id == tasks[0].id


async def test_update_profile_writes_jsonb_and_event(session):
    user = await _make_user(session, lark="act_u2")
    executor = ActionExecutor(session)
    actions = [
        ParsedAction(ActionType.UPDATE_PROFILE, UpdateProfileParams(path="diet", value="vegetarian"))
    ]
    await executor.execute_all(user.id, actions, conversation_id=None)
    await session.refresh(user)
    assert user.preferences["profile"]["diet"] == "vegetarian"
    events = (await session.execute(select(Event))).scalars().all()
    assert events[0].type == "profile_updated"
    assert events[0].payload["path"] == "diet"
    assert events[0].payload["after"] == "vegetarian"


async def test_record_pattern_appends_and_event(session):
    user = await _make_user(session, lark="act_u3")
    executor = ActionExecutor(session)
    actions = [
        ParsedAction(ActionType.RECORD_PATTERN, RecordPatternParams(pattern="no 7am pings", confidence=0.8))
    ]
    await executor.execute_all(user.id, actions, conversation_id=None)
    await session.refresh(user)
    patterns = user.preferences["procedural"]
    assert len(patterns) == 1 and patterns[0]["pattern"] == "no 7am pings"
    events = (await session.execute(select(Event))).scalars().all()
    assert events[0].type == "pattern_recorded"


async def test_complete_task_marks_status_and_event(session):
    user = await _make_user(session, lark="act_u4")
    t = Task(user_id=user.id, title="t", status="pending")
    session.add(t)
    await session.commit()
    executor = ActionExecutor(session)
    actions = [ParsedAction(ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=t.id))]
    await executor.execute_all(user.id, actions, conversation_id=None)
    await session.refresh(t)
    assert t.status == "done"
    events = (await session.execute(select(Event))).scalars().all()
    assert events[0].type == "task_completed"


async def test_failed_action_rolls_back_all(session):
    user = await _make_user(session, lark="act_u5")
    executor = ActionExecutor(session)
    actions = [
        ParsedAction(ActionType.CREATE_TASK, CreateTaskParams(title="good")),
        ParsedAction(ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=99999)),  # nonexistent
    ]
    with pytest.raises(Exception):
        await executor.execute_all(user.id, actions, conversation_id=None)
    tasks = (await session.execute(select(Task))).scalars().all()
    events = (await session.execute(select(Event))).scalars().all()
    assert len(tasks) == 0  # rolled back
    assert len(events) == 0
```

- [ ] **Step 9.2: Run — expect FAIL**

```bash
pytest tests/test_orchestrator/test_act.py -v
```

- [ ] **Step 9.3: Create `app/orchestrator/act.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import date as date_type, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.goal import Goal
from app.models.habit import Habit
from app.models.task import Task
from app.models.user import User
from app.models.dialogue_session import DialogueSession
from app.orchestrator.actions import (
    ActionType,
    AddHabitParams,
    CompleteHabitParams,
    CompleteTaskParams,
    CreateGoalParams,
    CreateTaskParams,
    DeleteTaskParams,
    ParsedAction,
    RecordFeedbackParams,
    RecordPatternParams,
    StartFlowParams,
    UpdateGoalParams,
    UpdateProfileParams,
    UpdateTaskParams,
)


@dataclass
class ActionResult:
    type: ActionType
    entity_type: Optional[str]
    entity_id: Optional[int]
    payload: dict


class ActionExecutor:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute_all(
        self,
        user_id: int,
        actions: list[ParsedAction],
        conversation_id: Optional[int],
    ) -> list[ActionResult]:
        if not actions:
            return []
        async with self.session.begin_nested():
            results: list[ActionResult] = []
            for action in actions:
                result = await self._dispatch(user_id, action)
                event = Event(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    type=_event_type_for(action.type),
                    entity_type=result.entity_type,
                    entity_id=result.entity_id,
                    payload=result.payload,
                )
                self.session.add(event)
                results.append(result)
        await self.session.commit()
        return results

    async def _dispatch(self, user_id: int, action: ParsedAction) -> ActionResult:
        params = action.params
        if action.type == ActionType.CREATE_TASK:
            return await self._create_task(user_id, params)
        if action.type == ActionType.UPDATE_TASK:
            return await self._update_task(user_id, params)
        if action.type == ActionType.COMPLETE_TASK:
            return await self._complete_task(user_id, params)
        if action.type == ActionType.DELETE_TASK:
            return await self._delete_task(user_id, params)
        if action.type == ActionType.CREATE_GOAL:
            return await self._create_goal(user_id, params)
        if action.type == ActionType.UPDATE_GOAL:
            return await self._update_goal(user_id, params)
        if action.type == ActionType.ADD_HABIT:
            return await self._add_habit(user_id, params)
        if action.type == ActionType.COMPLETE_HABIT:
            return await self._complete_habit(user_id, params)
        if action.type == ActionType.UPDATE_PROFILE:
            return await self._update_profile(user_id, params)
        if action.type == ActionType.RECORD_PATTERN:
            return await self._record_pattern(user_id, params)
        if action.type == ActionType.RECORD_FEEDBACK:
            return await self._record_feedback(user_id, params)
        if action.type == ActionType.START_FLOW:
            return await self._start_flow(user_id, params)
        raise ValueError(f"unhandled action type: {action.type}")

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
        return ActionResult(
            type=ActionType.CREATE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"title": task.title, "deadline": p.deadline, "quadrant": p.quadrant},
        )

    async def _update_task(self, user_id: int, p: UpdateTaskParams) -> ActionResult:
        task = await self.session.get(Task, p.task_id)
        if task is None or task.user_id != user_id:
            raise ValueError(f"task {p.task_id} not found for user")
        before = {"title": task.title, "status": task.status}
        if p.title is not None: task.title = p.title
        if p.description is not None: task.description = p.description
        if p.deadline is not None: task.deadline = _parse_iso_datetime(p.deadline)
        if p.quadrant is not None: task.quadrant = p.quadrant
        if p.status is not None: task.status = p.status
        await self.session.flush()
        return ActionResult(
            type=ActionType.UPDATE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"before": before, "after": {"title": task.title, "status": task.status}},
        )

    async def _complete_task(self, user_id: int, p: CompleteTaskParams) -> ActionResult:
        task = await self.session.get(Task, p.task_id)
        if task is None or task.user_id != user_id:
            raise ValueError(f"task {p.task_id} not found for user")
        task.status = "done"
        await self.session.flush()
        return ActionResult(
            type=ActionType.COMPLETE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"completed_at": _now_iso()},
        )

    async def _delete_task(self, user_id: int, p: DeleteTaskParams) -> ActionResult:
        task = await self.session.get(Task, p.task_id)
        if task is None or task.user_id != user_id:
            raise ValueError(f"task {p.task_id} not found for user")
        snapshot = {"title": task.title, "status": task.status}
        await self.session.delete(task)
        await self.session.flush()
        return ActionResult(
            type=ActionType.DELETE_TASK,
            entity_type="task",
            entity_id=p.task_id,
            payload=snapshot,
        )

    async def _create_goal(self, user_id: int, p: CreateGoalParams) -> ActionResult:
        goal = Goal(user_id=user_id, title=p.title, description=p.description)
        self.session.add(goal)
        await self.session.flush()
        return ActionResult(
            type=ActionType.CREATE_GOAL,
            entity_type="goal",
            entity_id=goal.id,
            payload={"title": goal.title, "target_date": p.target_date},
        )

    async def _update_goal(self, user_id: int, p: UpdateGoalParams) -> ActionResult:
        goal = await self.session.get(Goal, p.goal_id)
        if goal is None or goal.user_id != user_id:
            raise ValueError(f"goal {p.goal_id} not found")
        before = {"title": goal.title, "description": goal.description}
        if p.title is not None: goal.title = p.title
        if p.description is not None: goal.description = p.description
        await self.session.flush()
        return ActionResult(
            type=ActionType.UPDATE_GOAL,
            entity_type="goal",
            entity_id=goal.id,
            payload={"before": before, "after": {"title": goal.title, "description": goal.description}},
        )

    async def _add_habit(self, user_id: int, p: AddHabitParams) -> ActionResult:
        habit = Habit(user_id=user_id, title=p.title)
        # frequency / preferred_time may not exist as columns yet; if so, drop them silently
        for attr in ("frequency", "preferred_time", "duration_minutes"):
            if hasattr(habit, attr) and getattr(p, attr) is not None:
                setattr(habit, attr, getattr(p, attr))
        self.session.add(habit)
        await self.session.flush()
        return ActionResult(
            type=ActionType.ADD_HABIT,
            entity_type="habit",
            entity_id=habit.id,
            payload={"title": habit.title, "frequency": p.frequency},
        )

    async def _complete_habit(self, user_id: int, p: CompleteHabitParams) -> ActionResult:
        habit = await self.session.get(Habit, p.habit_id)
        if habit is None or habit.user_id != user_id:
            raise ValueError(f"habit {p.habit_id} not found")
        return ActionResult(
            type=ActionType.COMPLETE_HABIT,
            entity_type="habit",
            entity_id=habit.id,
            payload={"date": p.date or date_type.today().isoformat()},
        )

    async def _update_profile(self, user_id: int, p: UpdateProfileParams) -> ActionResult:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        prefs = dict(user.preferences or {})
        profile = dict(prefs.get("profile", {}))
        before = profile.get(p.path)
        profile[p.path] = p.value
        prefs["profile"] = profile
        user.preferences = prefs
        await self.session.flush()
        return ActionResult(
            type=ActionType.UPDATE_PROFILE,
            entity_type="profile",
            entity_id=None,
            payload={"path": p.path, "before": before, "after": p.value},
        )

    async def _record_pattern(self, user_id: int, p: RecordPatternParams) -> ActionResult:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        prefs = dict(user.preferences or {})
        patterns = list(prefs.get("procedural", []))
        patterns.append({"pattern": p.pattern, "confidence": p.confidence, "learned_at": _now_iso()})
        prefs["procedural"] = patterns
        user.preferences = prefs
        await self.session.flush()
        return ActionResult(
            type=ActionType.RECORD_PATTERN,
            entity_type="pattern",
            entity_id=None,
            payload={"pattern": p.pattern, "confidence": p.confidence},
        )

    async def _record_feedback(self, user_id: int, p: RecordFeedbackParams) -> ActionResult:
        return ActionResult(
            type=ActionType.RECORD_FEEDBACK,
            entity_type="feedback",
            entity_id=None,
            payload={"sentiment": p.sentiment, "content": p.content},
        )

    async def _start_flow(self, user_id: int, p: StartFlowParams) -> ActionResult:
        ds = DialogueSession(user_id=user_id, flow_type=p.flow_name, status="active")
        self.session.add(ds)
        await self.session.flush()
        return ActionResult(
            type=ActionType.START_FLOW,
            entity_type="flow",
            entity_id=ds.id,
            payload={"flow_name": p.flow_name},
        )


_EVENT_TYPE_MAP: dict[ActionType, str] = {
    ActionType.CREATE_TASK: "task_created",
    ActionType.UPDATE_TASK: "task_updated",
    ActionType.COMPLETE_TASK: "task_completed",
    ActionType.DELETE_TASK: "task_deleted",
    ActionType.CREATE_GOAL: "goal_set",
    ActionType.UPDATE_GOAL: "goal_updated",
    ActionType.ADD_HABIT: "habit_added",
    ActionType.COMPLETE_HABIT: "habit_completed",
    ActionType.UPDATE_PROFILE: "profile_updated",
    ActionType.RECORD_PATTERN: "pattern_recorded",
    ActionType.RECORD_FEEDBACK: "feedback_recorded",
    ActionType.START_FLOW: "flow_started",
}


def _event_type_for(action_type: ActionType) -> str:
    return _EVENT_TYPE_MAP[action_type]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # fallback: treat as date
        try:
            d = date_type.fromisoformat(s)
            return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
        except ValueError:
            return None
```

- [ ] **Step 9.4: Run — expect PASS**

```bash
pytest tests/test_orchestrator/test_act.py -v
```

If the rollback test fails because the savepoint is committed despite an inner error, check that `_complete_task` is raising rather than swallowing the missing-task case.

- [ ] **Step 9.5: Commit**

```bash
git add app/orchestrator/act.py tests/test_orchestrator/test_act.py
git commit -m "feat: ActionExecutor with atomic action dispatch and event emission"
```

---

## Task 10: REACT Module + Prompt

**Files:**
- Create: `app/orchestrator/prompts/react.md`
- Create: `app/orchestrator/react.py`
- Test: `tests/test_orchestrator/test_react.py`

- [ ] **Step 10.1: Write the REACT prompt template**

Create `app/orchestrator/prompts/react.md`:

```markdown
{persona}

Conversation framing:
- You will see the recent conversation, the user's latest message, what was just done on their behalf (if anything), and an optional hint about how to respond.
- Generate ONLY the assistant's natural-language reply text. No markdown headings, no JSON, no "Assistant:" prefix.
- Reply in the user's language.
- Keep it short unless the hint says otherwise.
```

- [ ] **Step 10.2: Write failing test**

Create `tests/test_orchestrator/test_react.py`:

```python
from app.orchestrator.context import Context
from app.orchestrator.react import react
from app.schemas.preferences import Profile


class _FakeRouter:
    def __init__(self, output: str):
        self._output = output
        self.calls = []

    async def complete(self, task_type, messages, **kw):
        self.calls.append({"task_type": task_type, "messages": messages})
        return self._output


def _ctx(name="Test"):
    return Context(
        user_id=1, user_name=name,
        profile=Profile(), procedural_patterns=[],
        onboarding_status="pending", active_flow=None,
        flow_filled_fields={}, flow_missing_fields=[],
        recent_turns=[], open_tasks=[],
    )


async def test_react_returns_text():
    router = _FakeRouter("Got it, added it to your list.")
    out = await react(_ctx(), "add task X", action_results=[], hint=None, complexity="low", llm=router)
    assert "added" in out.lower()
    assert router.calls[0]["task_type"] == "react"


async def test_react_uses_reasoning_when_complexity_high():
    router = _FakeRouter("Here's a detailed analysis...")
    await react(_ctx(), "summarize my week", action_results=[], hint=None, complexity="high", llm=router)
    assert router.calls[0]["task_type"] == "reasoning"


async def test_react_includes_persona_user_name():
    router = _FakeRouter("ok")
    await react(_ctx(name="Alice"), "hi", action_results=[], hint=None, complexity="low", llm=router)
    sys_msg = router.calls[0]["messages"][0]["content"]
    assert "Alice" in sys_msg


async def test_react_includes_action_results_in_user_message():
    router = _FakeRouter("ok")
    await react(
        _ctx(), "add task X",
        action_results=[{"type": "create_task", "entity_id": 42}],
        hint="be brief",
        complexity="low",
        llm=router,
    )
    user_msg = router.calls[0]["messages"][1]["content"]
    assert "create_task" in user_msg
    assert "be brief" in user_msg
```

- [ ] **Step 10.3: Run — expect FAIL**

```bash
pytest tests/test_orchestrator/test_react.py -v
```

- [ ] **Step 10.4: Create `app/orchestrator/react.py`**

```python
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Literal, Optional

from app.llm.router import LLMError, LLMRouter
from app.orchestrator.context import Context
from app.persona import load_persona

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "react.md"
_TEMPLATE: Optional[str] = None


def _load_template() -> str:
    global _TEMPLATE
    if _TEMPLATE is None:
        _TEMPLATE = _PROMPT_PATH.read_text()
    return _TEMPLATE


async def react(
    ctx: Context,
    message: str,
    action_results: list[dict],
    hint: Optional[str],
    complexity: Literal["low", "high"],
    llm: LLMRouter,
) -> str:
    system_prompt = _load_template().replace("{persona}", load_persona(ctx.user_name))
    history = "\n".join(f"{t['role']}: {t['content']}" for t in ctx.recent_turns)
    user_content = (
        f"<conversation_history>\n{history}\n</conversation_history>\n"
        f"<user_message>{message}</user_message>\n"
        f"<actions_completed>{json.dumps(action_results, ensure_ascii=False)}</actions_completed>\n"
        f"<hint>{hint or ''}</hint>"
    )
    task_type = "reasoning" if complexity == "high" else "react"
    try:
        return (await llm.complete(
            task_type,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )).strip()
    except LLMError as e:
        logger.warning("REACT call failed: %s", e)
        return "好的，已记下来。"  # safe fallback
```

- [ ] **Step 10.5: Run — expect PASS**

```bash
pytest tests/test_orchestrator/test_react.py -v
```

- [ ] **Step 10.6: Commit**

```bash
git add app/orchestrator/react.py app/orchestrator/prompts/react.md tests/test_orchestrator/test_react.py
git commit -m "feat: REACT module with persona-driven reply, complexity-based model upgrade"
```

---

## Task 11: ConversationOrchestrator (Wire Everything)

**Files:**
- Create: `app/orchestrator/conversation.py`
- Modify: `app/orchestrator/__init__.py`
- Test: `tests/test_orchestrator/test_conversation.py`

- [ ] **Step 11.1: Write failing integration test**

Create `tests/test_orchestrator/test_conversation.py`:

```python
import pytest
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.event import Event
from app.models.task import Task
from app.models.user import User
from app.orchestrator.conversation import ConversationOrchestrator


class _ScriptedRouter:
    """Returns canned JSON for think and canned text for react."""
    def __init__(self, think_payload, react_text):
        self._think = think_payload
        self._react = react_text
        self.react_task_types = []

    async def complete_json(self, task_type, messages, **kw):
        return self._think

    async def complete(self, task_type, messages, **kw):
        self.react_task_types.append(task_type)
        return self._react


async def test_orchestrator_create_task_flow(session):
    user = User(name="Yuzhu", lark_user_id="orch_u1", preferences={})
    session.add(user)
    await session.commit()
    router = _ScriptedRouter(
        think_payload={
            "intent": "add task",
            "actions": [{"type": "create_task", "params": {"title": "buy milk"}}],
            "should_reply": True,
            "reply_complexity": "low",
            "reply_hint": "confirm friendly",
            "reasoning": "",
        },
        react_text="Done, added 'buy milk'.",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    out = await orch.handle(user_id=user.id, message="add task buy milk")
    assert out.reply == "Done, added 'buy milk'."
    assert out.actions_taken == ["task_created"]

    tasks = (await session.execute(select(Task))).scalars().all()
    events = (await session.execute(select(Event))).scalars().all()
    convs = (await session.execute(select(Conversation))).scalars().all()
    assert len(tasks) == 1
    assert len(events) == 1 and events[0].type == "task_created"
    # both user msg and assistant reply persisted
    roles = {c.role for c in convs}
    assert {"user", "assistant"} <= roles
    # event references the user conversation row
    user_conv = next(c for c in convs if c.role == "user")
    assert events[0].conversation_id == user_conv.id


async def test_orchestrator_silent_turn(session):
    user = User(name="A", lark_user_id="orch_u2", preferences={})
    session.add(user)
    await session.commit()
    t = Task(user_id=user.id, title="report", status="pending")
    session.add(t)
    await session.commit()
    router = _ScriptedRouter(
        think_payload={
            "intent": "confirm done",
            "actions": [{"type": "complete_task", "params": {"task_id": t.id}}],
            "should_reply": False,
            "reply_complexity": "low",
            "reply_hint": None,
            "reasoning": "",
        },
        react_text="(not used)",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    out = await orch.handle(user_id=user.id, message="ok")
    assert out.reply is None
    assert out.actions_taken == ["task_completed"]
    await session.refresh(t)
    assert t.status == "done"


async def test_orchestrator_high_complexity_uses_reasoning_model(session):
    user = User(name="A", lark_user_id="orch_u3", preferences={})
    session.add(user)
    await session.commit()
    router = _ScriptedRouter(
        think_payload={
            "intent": "analysis",
            "actions": [],
            "should_reply": True,
            "reply_complexity": "high",
            "reply_hint": "give thorough analysis",
            "reasoning": "",
        },
        react_text="Detailed analysis...",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    await orch.handle(user_id=user.id, message="how am I doing this week?")
    assert router.react_task_types == ["reasoning"]
```

- [ ] **Step 11.2: Run — expect FAIL**

```bash
pytest tests/test_orchestrator/test_conversation.py -v
```

- [ ] **Step 11.3: Create `app/orchestrator/conversation.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.router import LLMRouter
from app.models.conversation import Conversation
from app.orchestrator.act import ActionExecutor, _EVENT_TYPE_MAP
from app.orchestrator.context import load_context
from app.orchestrator.react import react
from app.orchestrator.think import think


@dataclass
class OrchestratorResponse:
    reply: Optional[str]
    actions_taken: list[str]


class ConversationOrchestrator:
    def __init__(self, session: AsyncSession, llm: LLMRouter):
        self.session = session
        self.llm = llm

    async def handle(self, user_id: int, message: str) -> OrchestratorResponse:
        # 1. persist the user's message immediately so it lands in conversations table
        user_msg = Conversation(user_id=user_id, role="user", content=message)
        self.session.add(user_msg)
        await self.session.commit()
        await self.session.refresh(user_msg)

        # 2. load context (now includes this latest message)
        ctx = await load_context(user_id, self.session)

        # 3. THINK
        think_result = await think(ctx, message, self.llm)

        # tag the user_msg with the inferred intent for analytics
        if think_result.intent:
            user_msg.intent = think_result.intent[:50]
            await self.session.commit()

        # 4. ACT (atomic with events)
        executor = ActionExecutor(self.session)
        action_results = await executor.execute_all(
            user_id=user_id,
            actions=think_result.actions,
            conversation_id=user_msg.id,
        )

        # 5. REACT (if needed)
        reply_text: Optional[str] = None
        if think_result.should_reply:
            reply_text = await react(
                ctx=ctx,
                message=message,
                action_results=[
                    {
                        "type": r.type.value,
                        "entity_type": r.entity_type,
                        "entity_id": r.entity_id,
                        "payload": r.payload,
                    }
                    for r in action_results
                ],
                hint=think_result.reply_hint,
                complexity=think_result.reply_complexity,
                llm=self.llm,
            )
            # persist assistant reply
            self.session.add(
                Conversation(user_id=user_id, role="assistant", content=reply_text, intent=think_result.intent[:50] if think_result.intent else None)
            )
            await self.session.commit()

        return OrchestratorResponse(
            reply=reply_text,
            actions_taken=[_EVENT_TYPE_MAP[r.type] for r in action_results],
        )
```

`actions_taken` returns event-type names (e.g., `"task_created"`), not the action-type values — these are what consumers downstream (and the test) expect.

- [ ] **Step 11.4: Update `app/orchestrator/__init__.py`**

```python
from app.orchestrator.conversation import ConversationOrchestrator, OrchestratorResponse

__all__ = ["ConversationOrchestrator", "OrchestratorResponse"]
```

- [ ] **Step 11.5: Run — expect PASS**

```bash
pytest tests/test_orchestrator/test_conversation.py -v
```

- [ ] **Step 11.6: Commit**

```bash
git add app/orchestrator/conversation.py app/orchestrator/__init__.py tests/test_orchestrator/test_conversation.py
git commit -m "feat: ConversationOrchestrator wiring think->act->react"
```

---

## Task 12: POST /api/conversation Router

**Files:**
- Create: `app/routers/conversation.py`
- Modify: `app/main.py`
- Test: `tests/test_routers/test_conversation.py`

- [ ] **Step 12.1: Write failing integration test**

Create `tests/test_routers/test_conversation.py`:

```python
import pytest
from unittest.mock import patch


async def test_conversation_endpoint_create_task(client, monkeypatch):
    # Stub the LLMRouter so this test doesn't hit the network
    class _StubRouter:
        def __init__(self, **_):
            pass
        async def complete_json(self, task_type, messages, **kw):
            return {
                "intent": "add task",
                "actions": [{"type": "create_task", "params": {"title": "buy milk"}}],
                "should_reply": True,
                "reply_complexity": "low",
                "reply_hint": "confirm",
                "reasoning": "",
            }
        async def complete(self, task_type, messages, **kw):
            return "Got it."
    monkeypatch.setattr("app.routers.conversation.LLMRouter", _StubRouter)

    user_resp = await client.post("/api/users", json={"name": "U", "lark_user_id": "conv_u1"})
    user_id = user_resp.json()["id"]
    resp = await client.post("/api/conversation", json={"user_id": user_id, "message": "add task buy milk"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Got it."
    assert data["actions_taken"] == ["task_created"]


async def test_conversation_endpoint_silent_turn(client, monkeypatch):
    class _StubRouter:
        def __init__(self, **_):
            pass
        async def complete_json(self, task_type, messages, **kw):
            return {
                "intent": "noop",
                "actions": [],
                "should_reply": False,
                "reply_complexity": "low",
                "reply_hint": None,
                "reasoning": "",
            }
        async def complete(self, task_type, messages, **kw):
            raise AssertionError("should not be called")
    monkeypatch.setattr("app.routers.conversation.LLMRouter", _StubRouter)

    user_resp = await client.post("/api/users", json={"name": "U", "lark_user_id": "conv_u2"})
    user_id = user_resp.json()["id"]
    resp = await client.post("/api/conversation", json={"user_id": user_id, "message": "ok"})
    assert resp.status_code == 200
    assert resp.json()["reply"] is None


async def test_conversation_endpoint_unknown_user_404(client):
    resp = await client.post("/api/conversation", json={"user_id": 99999, "message": "hi"})
    assert resp.status_code == 404
```

- [ ] **Step 12.2: Run — expect FAIL (endpoint absent)**

```bash
pytest tests/test_routers/test_conversation.py -v
```

- [ ] **Step 12.3: Create `app/routers/conversation.py`**

```python
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.llm.router import LLMRouter
from app.models.user import User
from app.orchestrator.conversation import ConversationOrchestrator

router = APIRouter(prefix="/api", tags=["conversation"])


class ConversationRequest(BaseModel):
    user_id: int
    message: str


class ConversationResponse(BaseModel):
    reply: Optional[str]
    actions_taken: list[str]


@router.post("/conversation", response_model=ConversationResponse)
async def conversation(
    req: ConversationRequest,
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, req.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    llm = LLMRouter()
    orchestrator = ConversationOrchestrator(session=session, llm=llm)
    out = await orchestrator.handle(user_id=req.user_id, message=req.message)
    return ConversationResponse(reply=out.reply, actions_taken=out.actions_taken)
```

- [ ] **Step 12.4: Register router in `app/main.py`**

Read the current `app/main.py`, then add:

```python
from app.routers import conversation as conversation_router
...
app.include_router(conversation_router.router)
```

Place near the existing `include_router` calls. **Leave the other routers in place for now** — Task 14 strips them.

- [ ] **Step 12.5: Run — expect PASS**

```bash
pytest tests/test_routers/test_conversation.py -v
```

- [ ] **Step 12.6: Commit**

```bash
git add app/routers/conversation.py app/main.py tests/test_routers/test_conversation.py
git commit -m "feat: POST /api/conversation unified entry point"
```

---

## Task 13: End-to-End Smoke Test

**Files:**
- Test: `tests/test_e2e_smoke.py`

This test uses the stub-router pattern from Task 12 but walks a longer happy path to confirm everything still wires up.

- [ ] **Step 13.1: Write the smoke test**

Create `tests/test_e2e_smoke.py`:

```python
from sqlalchemy import select

from app.models.event import Event
from app.models.task import Task
from app.models.user import User


class _ScriptedRouter:
    def __init__(self, script: list[dict], react_text: str = "ok"):
        self._script = list(script)
        self._react_text = react_text

    async def complete_json(self, task_type, messages, **kw):
        return self._script.pop(0)

    async def complete(self, task_type, messages, **kw):
        return self._react_text


async def test_full_happy_path(client, monkeypatch, session):
    script = [
        # Turn 1: start onboarding
        {
            "intent": "start onboarding",
            "actions": [{"type": "start_flow", "params": {"flow_name": "onboarding"}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "ask first question", "reasoning": "",
        },
        # Turn 2: answer wake_up
        {
            "intent": "answer wake_up",
            "actions": [{"type": "update_profile", "params": {"path": "wake_up", "value": "07:00"}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "ask next field", "reasoning": "",
        },
        # Turn 3: add a task
        {
            "intent": "add task",
            "actions": [{"type": "create_task", "params": {"title": "weekly report"}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "", "reasoning": "",
        },
        # Turn 4: complete the task (we will look up the task_id below)
        {
            "intent": "complete task",
            "actions": [{"type": "complete_task", "params": {"task_id": None}}],   # patched below
            "should_reply": False, "reply_complexity": "low",
            "reply_hint": None, "reasoning": "",
        },
    ]

    class _Router:
        def __init__(self, **_): pass
        async def complete_json(self, task_type, messages, **kw): return script.pop(0)
        async def complete(self, task_type, messages, **kw): return "ok"

    monkeypatch.setattr("app.routers.conversation.LLMRouter", _Router)

    user_resp = await client.post("/api/users", json={"name": "Yuzhu", "lark_user_id": "e2e_u1"})
    user_id = user_resp.json()["id"]

    # Turn 1
    r1 = await client.post("/api/conversation", json={"user_id": user_id, "message": "start"})
    assert r1.status_code == 200 and r1.json()["actions_taken"] == ["flow_started"]

    # Turn 2
    r2 = await client.post("/api/conversation", json={"user_id": user_id, "message": "I wake up at 7"})
    assert r2.json()["actions_taken"] == ["profile_updated"]

    # Turn 3
    r3 = await client.post("/api/conversation", json={"user_id": user_id, "message": "add task weekly report"})
    assert r3.json()["actions_taken"] == ["task_created"]

    # Look up created task id, patch the script
    task = (await session.execute(select(Task).where(Task.user_id == user_id))).scalar_one()
    script[0]["actions"][0]["params"]["task_id"] = task.id

    # Turn 4
    r4 = await client.post("/api/conversation", json={"user_id": user_id, "message": "done"})
    assert r4.json()["actions_taken"] == ["task_completed"]
    assert r4.json()["reply"] is None

    # Verify event log
    events = (await session.execute(select(Event).where(Event.user_id == user_id).order_by(Event.id))).scalars().all()
    event_types = [e.type for e in events]
    assert event_types == [
        "flow_started",
        "profile_updated",
        "task_created",
        "task_completed",
    ]
```

- [ ] **Step 13.2: Run — expect PASS**

```bash
pytest tests/test_e2e_smoke.py -v
```

- [ ] **Step 13.3: Commit**

```bash
git add tests/test_e2e_smoke.py
git commit -m "test: end-to-end smoke through orchestrator pipeline"
```

---

## Task 14: Delete Obsolete Code

This task is destructive. Run the existing test suite after each batch of deletions and fix breakage before moving on. **Do not consolidate** — committing in batches makes bisecting easier if something breaks.

**Files (delete):**
- `app/dialogue/` (whole directory)
- `app/services/llm.py`
- `app/services/meeting_notes.py`
- `app/engines/conversation.py`
- `app/engines/task_extractor.py`
- `app/routers/chat.py`
- `app/routers/meeting_notes.py`
- `tests/test_dialogue/`
- `tests/test_routers/test_chat.py`
- `tests/test_routers/test_meeting_notes.py`
- `tests/test_services/test_meeting_notes.py`
- `tests/test_engines/test_conversation.py` (if exists)
- `tests/test_engines/test_task_extractor.py` (if exists)

**Files (modify):**
- `app/main.py` — drop deleted router imports/includes

- [ ] **Step 14.1: Delete `app/dialogue/` and its tests**

```bash
rm -rf app/dialogue tests/test_dialogue
```

- [ ] **Step 14.2: Delete legacy LLM service and meeting notes**

```bash
rm -f app/services/llm.py app/services/meeting_notes.py tests/test_services/test_meeting_notes.py
```

- [ ] **Step 14.3: Delete legacy conversation/extractor engines**

```bash
rm -f app/engines/conversation.py app/engines/task_extractor.py
rm -f tests/test_engines/test_conversation.py tests/test_engines/test_task_extractor.py 2>/dev/null || true
```

- [ ] **Step 14.4: Delete `chat.py` router and tests**

```bash
rm -f app/routers/chat.py tests/test_routers/test_chat.py
```

- [ ] **Step 14.5: Delete `meeting_notes.py` router and tests**

```bash
rm -f app/routers/meeting_notes.py tests/test_routers/test_meeting_notes.py
```

- [ ] **Step 14.6: Update `app/main.py` — drop deleted imports**

Open `app/main.py`. Remove imports of and `include_router` calls for: `chat`, `meeting_notes`. The current `from app.routers import users, tasks, goals, habits, plans, chat, lark_webhook, ingestion, meeting_notes, reports` becomes:

```python
from app.routers import users, tasks, goals, habits, plans, lark_webhook, ingestion, reports, conversation as conversation_router
```

Adjust `app.include_router(...)` calls accordingly.

- [ ] **Step 14.7: Run full test suite, fix orphaned imports**

```bash
pytest -x
```

Expected: should pass except for tests that imported deleted modules. For each ImportError, look at the file:
- If the test was testing deleted code, delete it
- If the test imported a deleted helper but should still work, update it to use new equivalents

Common breakages and fixes:
- `app/lark/bot.py` may import `app.services.llm` or `app.engines.conversation` → update to use `ConversationOrchestrator` (or comment out the bot wiring if Lark isn't in scope for this spec — leave a `TODO(spec-2)` comment)
- `app/routers/lark_webhook.py` may import from `app/dialogue/` → same handling

- [ ] **Step 14.8: Re-run, expect green**

```bash
pytest
```

Expected: all pass.

- [ ] **Step 14.9: Commit**

```bash
git add -A
git commit -m "chore: delete dialogue/, legacy llm service, meeting notes, chat router"
```

---

## Task 15: Reduce CRUD Routers to GET-only

The spec keeps tasks/goals/habits/plans routers for the frontend to read data, but all mutations now go through `/api/conversation`. Strip POST/PATCH/DELETE handlers.

**Files (modify):**
- `app/routers/tasks.py`
- `app/routers/goals.py`
- `app/routers/habits.py`
- `app/routers/plans.py`

- [ ] **Step 15.1: Strip mutations from `app/routers/tasks.py`**

Open the file. Keep only `@router.get(...)` handlers. Delete handlers decorated with `@router.post`, `@router.patch`, `@router.put`, `@router.delete`. Remove any now-unused imports.

- [ ] **Step 15.2: Same for goals.py / habits.py / plans.py**

Repeat for the other three files.

- [ ] **Step 15.3: Update their tests — drop now-removed cases**

Open `tests/test_routers/test_tasks.py` etc. Delete tests that POST/PATCH/DELETE these endpoints. Keep GET tests; they may need a test fixture to seed a task via direct DB insert (since you can no longer create via POST). Example:

```python
async def test_get_tasks_for_user(client, session):
    from app.models.user import User
    from app.models.task import Task
    user = User(name="U", lark_user_id="get_u")
    session.add(user)
    await session.commit()
    session.add(Task(user_id=user.id, title="t", status="pending"))
    await session.commit()
    resp = await client.get(f"/api/tasks/user/{user.id}")  # adjust path to actual GET route
    assert resp.status_code == 200
```

Apply the same edit to the other three test files.

- [ ] **Step 15.4: Run, expect green**

```bash
pytest
```

- [ ] **Step 15.5: Commit**

```bash
git add app/routers/ tests/test_routers/
git commit -m "chore: reduce tasks/goals/habits/plans routers to GET-only; mutations via /api/conversation"
```

---

## Task 16: Sanity-Check Live App

This is a manual smoke step, not a test. Verifies the dev environment still boots end-to-end with real LLM calls. Requires `PA_ANTHROPIC_API_KEY` set in `.env`.

- [ ] **Step 16.1: Start backend**

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000 > /tmp/pa-backend.log 2>&1 &
sleep 3
curl -s http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 16.2: Hit `/api/conversation` for real**

```bash
# First create a user (still allowed via /api/users)
USER_ID=$(curl -s -X POST http://localhost:8000/api/users \
  -H "Content-Type: application/json" \
  -d '{"name":"SmokeTester","lark_user_id":"smoke1"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

# Then talk to the assistant
curl -s -X POST http://localhost:8000/api/conversation \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":$USER_ID,\"message\":\"add task buy groceries by friday\"}" | python3 -m json.tool
```

Expected: a 200 response with a natural-language `reply` and `actions_taken: ["task_created"]`.

- [ ] **Step 16.3: Verify events landed**

```bash
psql -d my_assistant -c "SELECT type, entity_type, entity_id, payload FROM events ORDER BY id DESC LIMIT 5;"
```

Expected: a `task_created` row with the task title in payload.

- [ ] **Step 16.4: Stop backend**

```bash
pkill -f "uvicorn app.main"
```

- [ ] **Step 16.5: Commit (no code changes, but optional changelog entry)**

If you want a documentation marker that the bundle is shipped:

```bash
# optional: append a note to docs/superpowers/specs/2026-05-20-infrastructure-bundle-design.md
# or do nothing; the spec → plan → code lineage is already in git.
```

---

## Plan Summary

After completing all tasks:

- ✅ `events` table + `task.habit_id` + `time_slots.date` (Task 1)
- ✅ LiteLLM router with task-type model resolution (Task 2)
- ✅ Persona module (Task 3)
- ✅ Pydantic preferences schema (Task 4)
- ✅ Action types + declarative flows (Tasks 5–6)
- ✅ Context loader (Task 7)
- ✅ THINK module with structured JSON (Task 8)
- ✅ ACT module with atomic dispatch + events (Task 9)
- ✅ REACT module with persona + dynamic model upgrade (Task 10)
- ✅ ConversationOrchestrator wiring (Task 11)
- ✅ `POST /api/conversation` endpoint (Task 12)
- ✅ End-to-end smoke test (Task 13)
- ✅ Obsolete code deleted (Task 14)
- ✅ CRUD routers reduced to GET-only (Task 15)
- ✅ Live app sanity check (Task 16)

Next: Spec 2 — Proactive Agent (cron workers, task reminders, "did you finish?" check-ins, lark webhook deep wiring). It builds on this orchestrator pipeline and reuses every component.
