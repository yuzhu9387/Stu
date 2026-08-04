# Avery Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete Avery backend — all seven objects with full REST CRUD, the 6:3:1 rule engine, template-driven week materialization, and the scheduler — so the app is fully drivable from `/docs` before any UI exists.

**Architecture:** FastAPI over async SQLAlchemy against a local SQLite file. All business logic lives in `app/services/`; routers are thin adapters over it, so the REST API and the (later) agent share one code path and cannot diverge. `app/services/analytics.py` is deliberately pure — it takes events and a rule spec and returns numbers, with no I/O — because it is the piece most likely to be subtly wrong.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), aiosqlite, Alembic, Pydantic v2, pydantic-settings, APScheduler, pytest + pytest-asyncio + httpx.

**Spec:** `docs/superpowers/specs/2026-08-04-avery-schedule-agent-design.md`

## Global Constraints

- Python `>=3.11`. All DB access is async; never use the sync SQLAlchemy API.
- Database is SQLite at `Avery/data/avery.db`. `DATABASE_URL` default: `sqlite+aiosqlite:///data/avery.db`.
- **All datetimes are naive local time.** Never call `datetime.now(tz=...)`, never store tzinfo. The spec accepts this limitation explicitly.
- Business logic goes in `app/services/`. Routers contain no logic beyond serialization and HTTP status. This is the single most important structural rule in the plan.
- `app/services/analytics.py` performs **no I/O and imports no ORM models**. It operates on plain dataclasses only.
- Tag lists are stored as JSON arrays of ints. `tag_ids[0]` is the primary tag and drives both color and analytics attribution.
- **Rules are never mutated in place.** Editing closes the current row (`effective_to`) and inserts a new one.
- **Reports are append-only.** No `PATCH /api/reports/{id}` may exist.
- Ratio verdicts use *relative* tolerance: `|(actual − target) / target| <= tolerance`.
- Every task ends with a passing test run and a commit.

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/config.py` | Settings from env; resolves the DB path absolutely |
| `backend/app/database.py` | Async engine, session factory, `Base`, `get_session` dep |
| `backend/app/models/*.py` | One ORM model per file |
| `backend/app/schemas/*.py` | Pydantic in/out, one file per object |
| `backend/app/services/tags.py` | Tag CRUD; blocks deleting a tag in use |
| `backend/app/services/tasks.py` | Task CRUD, completion, floating queries |
| `backend/app/services/events.py` | Event CRUD, move, range queries, find-or-create task |
| `backend/app/services/templates.py` | Template CRUD and `materialize_week` |
| `backend/app/services/rules.py` | Versioning, active-rule lookup, `to_spec` |
| `backend/app/services/analytics.py` | **Pure.** Minutes, rollup, deviation, verdict |
| `backend/app/services/reports.py` | Build + persist reports (append-only) |
| `backend/app/services/reminders.py` | Schedule, due sweep, mark sent |
| `backend/app/services/calendar.py` | Week and month aggregate payloads |
| `backend/app/services/seed.py` | Seed tags, the 6:3:1 rule, the default template |
| `backend/app/routers/*.py` | Thin REST wrappers, one per object |
| `backend/app/scheduler/jobs.py` | Sunday week-roll, reminder sweep |
| `backend/tests/**` | Mirrors `app/`; `test_analytics.py` is the heaviest |

---

### Task 1: Scaffold, config, database, health check

**Files:**
- Create: `backend/pyproject.toml`, `backend/.env.example`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/database.py`, `backend/app/main.py`, `backend/app/models/__init__.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Base`, `get_session()`, `settings`, FastAPI `app`; pytest fixtures `session`, `client`

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "avery"
version = "0.1.0"
description = "Avery — personal schedule agent"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "aiosqlite>=0.20.0",
    "alembic>=1.13.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.3.0",
    "python-dotenv>=1.0.0",
    "apscheduler>=3.10",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.2.0", "pytest-asyncio>=0.23.0", "time-machine>=2.13"]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `backend/app/config.py`**

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///data/avery.db"
    enable_scheduler: bool = True
    week_roll_hour: int = 20  # Sunday 20:00 local

    def resolved_database_url(self) -> str:
        """Rewrite a relative sqlite path to an absolute one under the project dir."""
        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            return self.database_url
        raw = self.database_url[len(prefix) :]
        if raw == ":memory:" or raw.startswith("/"):
            return self.database_url
        target = (PROJECT_DIR / raw).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return f"{prefix}{target}"


settings = Settings()
```

- [ ] **Step 3: Create `backend/app/database.py`**

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.resolved_database_url(), echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async_session_factory = SessionLocal
```

- [ ] **Step 4: Create `backend/app/models/__init__.py` (empty for now) and `backend/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Avery", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Leave `app/models/__init__.py` as an empty file.

- [ ] **Step 5: Create `backend/tests/conftest.py`**

```python
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  — registers every model on Base.metadata
from app.database import Base, get_session
from app.main import app as fastapi_app


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(session) -> AsyncIterator[AsyncClient]:
    async def _override():
        yield session

    fastapi_app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    fastapi_app.dependency_overrides.clear()
```

The `import app.models` line is load-bearing: without it `Base.metadata` is empty and every table is missing.

- [ ] **Step 6: Write the failing test — `backend/tests/test_health.py`**

```python
async def test_health_returns_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 7: Install and run**

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Run: `cd backend && .venv/bin/pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 8: Create `backend/.env.example`**

```
DATABASE_URL=sqlite+aiosqlite:///data/avery.db
ENABLE_SCHEDULER=true
WEEK_ROLL_HOUR=20
```

- [ ] **Step 9: Commit**

```bash
git add backend/
git commit -m "feat: scaffold Avery backend with config, async db, health check"
```

---

### Task 2: Tag model, service, and REST

**Files:**
- Create: `backend/app/models/tag.py`, `backend/app/schemas/__init__.py`, `backend/app/schemas/tag.py`, `backend/app/services/__init__.py`, `backend/app/services/tags.py`, `backend/app/routers/__init__.py`, `backend/app/routers/tags.py`, `backend/tests/test_tags.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

**Interfaces:**
- Consumes: `Base`, `get_session`
- Produces: `Tag` model; `services.tags.list_tags(session, include_archived=False) -> list[Tag]`, `get_tag(session, tag_id) -> Tag | None`, `create_tag(session, data: TagCreate) -> Tag`, `update_tag(session, tag_id, data: TagUpdate) -> Tag | None`, `delete_tag(session, tag_id) -> bool`

- [ ] **Step 1: Write the failing test — `backend/tests/test_tags.py`**

```python
async def test_create_and_list_tag(client):
    created = await client.post(
        "/api/tags", json={"name": "Work", "color": "#DA96A4", "icon": "briefcase"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Work"
    assert body["color"] == "#DA96A4"
    assert body["archived"] is False

    listed = await client.get("/api/tags")
    assert listed.status_code == 200
    assert [t["name"] for t in listed.json()] == ["Work"]


async def test_duplicate_tag_name_rejected(client):
    await client.post("/api/tags", json={"name": "Work", "color": "#DA96A4"})
    dupe = await client.post("/api/tags", json={"name": "Work", "color": "#BDBD9B"})
    assert dupe.status_code == 409


async def test_update_and_delete_tag(client):
    tag_id = (
        await client.post("/api/tags", json={"name": "Study", "color": "#8FA8A2"})
    ).json()["id"]

    patched = await client.patch(f"/api/tags/{tag_id}", json={"color": "#BDBD9B"})
    assert patched.status_code == 200
    assert patched.json()["color"] == "#BDBD9B"

    deleted = await client.delete(f"/api/tags/{tag_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/tags/{tag_id}")).status_code == 404


async def test_delete_missing_tag_returns_404(client):
    assert (await client.delete("/api/tags/999")).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_tags.py -v`
Expected: FAIL — 404 on `/api/tags`, route does not exist

- [ ] **Step 3: Create `backend/app/models/tag.py`**

```python
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(16), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

- [ ] **Step 4: Set `backend/app/models/__init__.py`**

```python
from app.models.tag import Tag

__all__ = ["Tag"]
```

- [ ] **Step 5: Create `backend/app/schemas/tag.py`**

```python
from pydantic import BaseModel, ConfigDict, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = None
    sort_order: int = 0


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = None
    sort_order: int | None = None
    archived: bool | None = None


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str
    icon: str | None
    sort_order: int
    archived: bool
```

Leave `backend/app/schemas/__init__.py` empty.

- [ ] **Step 6: Create `backend/app/services/tags.py`**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag
from app.schemas.tag import TagCreate, TagUpdate


class DuplicateTagName(Exception):
    """Raised when a tag name collides with an existing one."""


async def list_tags(session: AsyncSession, include_archived: bool = False) -> list[Tag]:
    stmt = select(Tag).order_by(Tag.sort_order, Tag.id)
    if not include_archived:
        stmt = stmt.where(Tag.archived.is_(False))
    return list((await session.scalars(stmt)).all())


async def get_tag(session: AsyncSession, tag_id: int) -> Tag | None:
    return await session.get(Tag, tag_id)


async def _name_taken(session: AsyncSession, name: str, exclude_id: int | None) -> bool:
    stmt = select(Tag.id).where(Tag.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Tag.id != exclude_id)
    return (await session.scalars(stmt)).first() is not None


async def create_tag(session: AsyncSession, data: TagCreate) -> Tag:
    if await _name_taken(session, data.name, None):
        raise DuplicateTagName(data.name)
    tag = Tag(**data.model_dump())
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return tag


async def update_tag(session: AsyncSession, tag_id: int, data: TagUpdate) -> Tag | None:
    tag = await session.get(Tag, tag_id)
    if tag is None:
        return None
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and await _name_taken(session, fields["name"], tag_id):
        raise DuplicateTagName(fields["name"])
    for key, value in fields.items():
        setattr(tag, key, value)
    await session.commit()
    await session.refresh(tag)
    return tag


async def delete_tag(session: AsyncSession, tag_id: int) -> bool:
    tag = await session.get(Tag, tag_id)
    if tag is None:
        return False
    await session.delete(tag)
    await session.commit()
    return True
```

- [ ] **Step 7: Create `backend/app/routers/tags.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.tag import TagCreate, TagOut, TagUpdate
from app.services import tags as service

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
async def list_tags(include_archived: bool = False, session: AsyncSession = Depends(get_session)):
    return await service.list_tags(session, include_archived)


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(data: TagCreate, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_tag(session, data)
    except service.DuplicateTagName as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"tag name already exists: {exc}")


@router.get("/{tag_id}", response_model=TagOut)
async def get_tag(tag_id: int, session: AsyncSession = Depends(get_session)):
    tag = await service.get_tag(session, tag_id)
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tag not found")
    return tag


@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(tag_id: int, data: TagUpdate, session: AsyncSession = Depends(get_session)):
    try:
        tag = await service.update_tag(session, tag_id, data)
    except service.DuplicateTagName as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"tag name already exists: {exc}")
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tag not found")
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: int, session: AsyncSession = Depends(get_session)):
    if not await service.delete_tag(session, tag_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tag not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Leave `backend/app/routers/__init__.py` and `backend/app/services/__init__.py` empty.

- [ ] **Step 8: Register the router in `backend/app/main.py`**

Add after the `add_middleware` call:

```python
from app.routers import tags as tags_router

app.include_router(tags_router.router)
```

- [ ] **Step 9: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (5 tests)

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat: add Tag model, service, and REST endpoints"
```

---

### Task 3: Task model, service, and REST

**Files:**
- Create: `backend/app/models/task.py`, `backend/app/schemas/task.py`, `backend/app/services/tasks.py`, `backend/app/routers/tasks.py`, `backend/tests/test_tasks.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

**Interfaces:**
- Consumes: `Base`, `get_session`, `Tag`
- Produces: `Task` model with `TaskStatus`/`Priority` string enums; `services.tasks.list_tasks(session, *, status=None, is_floating=None) -> list[Task]`, `get_task`, `create_task(session, data: TaskCreate) -> Task`, `update_task`, `delete_task`, `find_or_create_by_name(session, name: str, tag_ids: list[int]) -> Task`

- [ ] **Step 1: Write the failing test — `backend/tests/test_tasks.py`**

```python
async def _tag(client, name="Work", color="#DA96A4"):
    return (await client.post("/api/tags", json={"name": name, "color": color})).json()["id"]


async def test_create_task_defaults(client):
    tag_id = await _tag(client)
    created = await client.post(
        "/api/tasks", json={"name": "Morning routine", "tag_ids": [tag_id]}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "todo"
    assert body["priority"] == "normal"
    assert body["is_floating"] is False
    assert body["tag_ids"] == [tag_id]
    assert body["completed_at"] is None


async def test_floating_task_filter(client):
    await client.post("/api/tasks", json={"name": "Scheduled", "tag_ids": []})
    await client.post(
        "/api/tasks", json={"name": "Renew passport", "tag_ids": [], "is_floating": True}
    )
    floating = await client.get("/api/tasks", params={"is_floating": True})
    assert [t["name"] for t in floating.json()] == ["Renew passport"]


async def test_completing_task_stamps_completed_at(client):
    task_id = (await client.post("/api/tasks", json={"name": "Gym", "tag_ids": []})).json()["id"]
    patched = await client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
    assert patched.status_code == 200
    assert patched.json()["completed_at"] is not None


async def test_reopening_task_clears_completed_at(client):
    task_id = (await client.post("/api/tasks", json={"name": "Gym", "tag_ids": []})).json()["id"]
    await client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
    reopened = await client.patch(f"/api/tasks/{task_id}", json={"status": "todo"})
    assert reopened.json()["completed_at"] is None


async def test_delete_task(client):
    task_id = (await client.post("/api/tasks", json={"name": "Temp", "tag_ids": []})).json()["id"]
    assert (await client.delete(f"/api/tasks/{task_id}")).status_code == 204
    assert (await client.get(f"/api/tasks/{task_id}")).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_tasks.py -v`
Expected: FAIL — `/api/tasks` returns 404

- [ ] **Step 3: Create `backend/app/models/task.py`**

```python
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaskStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    ARCHIVED = "archived"


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tag_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.TODO, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    est_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_floating: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default=Priority.NORMAL, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

```python
from app.models.tag import Tag
from app.models.task import Priority, Task, TaskStatus

__all__ = ["Tag", "Task", "TaskStatus", "Priority"]
```

- [ ] **Step 5: Create `backend/app/schemas/task.py`**

```python
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import Priority, TaskStatus


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tag_ids: list[int] = Field(default_factory=list)
    notes: str = ""
    status: TaskStatus = TaskStatus.TODO
    due_date: date | None = None
    est_minutes: int | None = None
    is_floating: bool = False
    priority: Priority = Priority.NORMAL


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tag_ids: list[int] | None = None
    notes: str | None = None
    status: TaskStatus | None = None
    due_date: date | None = None
    est_minutes: int | None = None
    is_floating: bool | None = None
    priority: Priority | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tag_ids: list[int]
    notes: str
    status: TaskStatus
    due_date: date | None
    est_minutes: int | None
    is_floating: bool
    priority: Priority
    created_at: datetime
    completed_at: datetime | None
```

- [ ] **Step 6: Create `backend/app/services/tasks.py`**

```python
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.models.task import TaskStatus
from app.schemas.task import TaskCreate, TaskUpdate


async def list_tasks(
    session: AsyncSession,
    *,
    status: TaskStatus | None = None,
    is_floating: bool | None = None,
) -> list[Task]:
    stmt = select(Task).order_by(Task.created_at.desc(), Task.id.desc())
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if is_floating is not None:
        stmt = stmt.where(Task.is_floating.is_(is_floating))
    return list((await session.scalars(stmt)).all())


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    return await session.get(Task, task_id)


async def create_task(session: AsyncSession, data: TaskCreate) -> Task:
    payload = data.model_dump()
    task = Task(**payload)
    if task.status == TaskStatus.DONE:
        task.completed_at = datetime.now()
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def update_task(session: AsyncSession, task_id: int, data: TaskUpdate) -> Task | None:
    task = await session.get(Task, task_id)
    if task is None:
        return None
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(task, key, value)
    if "status" in fields:
        task.completed_at = datetime.now() if fields["status"] == TaskStatus.DONE else None
    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, task_id: int) -> bool:
    task = await session.get(Task, task_id)
    if task is None:
        return False
    await session.delete(task)
    await session.commit()
    return True


async def find_or_create_by_name(
    session: AsyncSession, name: str, tag_ids: list[int]
) -> Task:
    """Used by event creation and template materialization to keep one Task per name."""
    stmt = select(Task).where(Task.name == name).order_by(Task.id)
    existing = (await session.scalars(stmt)).first()
    if existing is not None:
        return existing
    task = Task(name=name, tag_ids=list(tag_ids))
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task
```

- [ ] **Step 7: Create `backend/app/routers/tasks.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.task import TaskStatus
from app.schemas.task import TaskCreate, TaskOut, TaskUpdate
from app.services import tasks as service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    status_filter: TaskStatus | None = None,
    is_floating: bool | None = None,
    session: AsyncSession = Depends(get_session),
):
    return await service.list_tasks(session, status=status_filter, is_floating=is_floating)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, session: AsyncSession = Depends(get_session)):
    return await service.create_task(session, data)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await service.get_task(session, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, data: TaskUpdate, session: AsyncSession = Depends(get_session)):
    task = await service.update_task(session, task_id, data)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, session: AsyncSession = Depends(get_session)):
    if not await service.delete_task(session, task_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 8: Register in `backend/app/main.py`**

```python
from app.routers import tasks as tasks_router

app.include_router(tasks_router.router)
```

- [ ] **Step 9: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (10 tests)

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat: add Task model, service, and REST endpoints"
```

---

### Task 4: Event model, service, and REST

**Files:**
- Create: `backend/app/models/event.py`, `backend/app/schemas/event.py`, `backend/app/services/events.py`, `backend/app/routers/events.py`, `backend/tests/test_events.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

**Interfaces:**
- Consumes: `Task`, `services.tasks.find_or_create_by_name`
- Produces: `Event` model with `EventSource`; `services.events.list_events(session, *, start: datetime | None, end: datetime | None, task_id: int | None) -> list[Event]`, `get_event`, `create_event(session, data: EventCreate) -> Event`, `update_event`, `move_event(session, event_id, new_start: datetime) -> Event | None`, `delete_event`

- [ ] **Step 1: Write the failing test — `backend/tests/test_events.py`**

```python
from datetime import datetime


async def _task(client, name="Work block"):
    return (await client.post("/api/tasks", json={"name": name, "tag_ids": []})).json()["id"]


async def test_create_event_with_explicit_task(client):
    task_id = await _task(client)
    created = await client.post(
        "/api/events",
        json={
            "task_id": task_id,
            "start_at": "2026-08-03T09:30:00",
            "end_at": "2026-08-03T16:30:00",
            "tag_ids": [],
        },
    )
    assert created.status_code == 201
    assert created.json()["source"] == "manual"
    assert created.json()["task_id"] == task_id


async def test_create_event_by_name_autocreates_task(client):
    created = await client.post(
        "/api/events",
        json={
            "task_name": "Dentist",
            "start_at": "2026-08-05T15:00:00",
            "end_at": "2026-08-05T16:00:00",
            "tag_ids": [],
        },
    )
    assert created.status_code == 201
    task_id = created.json()["task_id"]
    assert task_id is not None
    task = await client.get(f"/api/tasks/{task_id}")
    assert task.json()["name"] == "Dentist"


async def test_event_requires_task_id_or_name(client):
    bad = await client.post(
        "/api/events",
        json={"start_at": "2026-08-05T15:00:00", "end_at": "2026-08-05T16:00:00"},
    )
    assert bad.status_code == 422


async def test_end_before_start_rejected(client):
    task_id = await _task(client)
    bad = await client.post(
        "/api/events",
        json={
            "task_id": task_id,
            "start_at": "2026-08-05T16:00:00",
            "end_at": "2026-08-05T15:00:00",
        },
    )
    assert bad.status_code == 422


async def test_list_events_filters_by_range(client):
    task_id = await _task(client)
    for day in ("2026-08-03", "2026-08-10"):
        await client.post(
            "/api/events",
            json={
                "task_id": task_id,
                "start_at": f"{day}T09:00:00",
                "end_at": f"{day}T10:00:00",
            },
        )
    listed = await client.get(
        "/api/events", params={"start": "2026-08-03T00:00:00", "end": "2026-08-04T00:00:00"}
    )
    assert len(listed.json()) == 1


async def test_move_event_preserves_duration(client):
    task_id = await _task(client)
    event_id = (
        await client.post(
            "/api/events",
            json={
                "task_id": task_id,
                "start_at": "2026-08-03T09:00:00",
                "end_at": "2026-08-03T10:30:00",
            },
        )
    ).json()["id"]

    moved = await client.post(
        f"/api/events/{event_id}/move", json={"start_at": "2026-08-04T14:00:00"}
    )
    assert moved.status_code == 200
    body = moved.json()
    delta = datetime.fromisoformat(body["end_at"]) - datetime.fromisoformat(body["start_at"])
    assert delta.total_seconds() == 90 * 60
    assert body["start_at"] == "2026-08-04T14:00:00"


async def test_cross_midnight_event_stored_intact(client):
    task_id = await _task(client, "Rest")
    created = await client.post(
        "/api/events",
        json={
            "task_id": task_id,
            "start_at": "2026-08-03T23:00:00",
            "end_at": "2026-08-04T07:00:00",
        },
    )
    assert created.status_code == 201
    assert created.json()["end_at"] == "2026-08-04T07:00:00"


async def test_delete_event(client):
    task_id = await _task(client)
    event_id = (
        await client.post(
            "/api/events",
            json={
                "task_id": task_id,
                "start_at": "2026-08-03T09:00:00",
                "end_at": "2026-08-03T10:00:00",
            },
        )
    ).json()["id"]
    assert (await client.delete(f"/api/events/{event_id}")).status_code == 204
    assert (await client.get(f"/api/events/{event_id}")).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_events.py -v`
Expected: FAIL — `/api/events` returns 404

- [ ] **Step 3: Create `backend/app/models/event.py`**

```python
from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EventSource(StrEnum):
    TEMPLATE = "template"
    MANUAL = "manual"
    AGENT = "agent"


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    tag_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default=EventSource.MANUAL, nullable=False)
    template_block_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    @property
    def duration_minutes(self) -> int:
        return int((self.end_at - self.start_at).total_seconds() // 60)
```

Tags are **copied** onto the event rather than read through the task, so re-tagging a task later cannot rewrite historical analytics.

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

```python
from app.models.event import Event, EventSource
from app.models.tag import Tag
from app.models.task import Priority, Task, TaskStatus

__all__ = ["Tag", "Task", "TaskStatus", "Priority", "Event", "EventSource"]
```

- [ ] **Step 5: Create `backend/app/schemas/event.py`**

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.event import EventSource


class EventCreate(BaseModel):
    task_id: int | None = None
    task_name: str | None = None
    start_at: datetime
    end_at: datetime
    tag_ids: list[int] = Field(default_factory=list)
    source: EventSource = EventSource.MANUAL
    template_block_id: int | None = None
    notes: str = ""

    @model_validator(mode="after")
    def check(self) -> "EventCreate":
        if self.task_id is None and not self.task_name:
            raise ValueError("either task_id or task_name is required")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class EventUpdate(BaseModel):
    start_at: datetime | None = None
    end_at: datetime | None = None
    tag_ids: list[int] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def check(self) -> "EventUpdate":
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class EventMove(BaseModel):
    start_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    start_at: datetime
    end_at: datetime
    tag_ids: list[int]
    source: EventSource
    template_block_id: int | None
    notes: str
```

- [ ] **Step 6: Create `backend/app/services/events.py`**

```python
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Task
from app.schemas.event import EventCreate, EventUpdate
from app.services import tasks as task_service


async def list_events(
    session: AsyncSession,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    task_id: int | None = None,
) -> list[Event]:
    """Returns events overlapping [start, end). Half-open so adjacent days never double-count."""
    stmt = select(Event).order_by(Event.start_at, Event.id)
    if start is not None:
        stmt = stmt.where(Event.end_at > start)
    if end is not None:
        stmt = stmt.where(Event.start_at < end)
    if task_id is not None:
        stmt = stmt.where(Event.task_id == task_id)
    return list((await session.scalars(stmt)).all())


async def get_event(session: AsyncSession, event_id: int) -> Event | None:
    return await session.get(Event, event_id)


async def create_event(session: AsyncSession, data: EventCreate) -> Event:
    tag_ids = list(data.tag_ids)
    if data.task_id is not None:
        task = await session.get(Task, data.task_id)
        if task is None:
            raise ValueError(f"task {data.task_id} not found")
    else:
        task = await task_service.find_or_create_by_name(session, data.task_name, tag_ids)
    if not tag_ids:
        tag_ids = list(task.tag_ids)

    event = Event(
        task_id=task.id,
        start_at=data.start_at,
        end_at=data.end_at,
        tag_ids=tag_ids,
        source=data.source,
        template_block_id=data.template_block_id,
        notes=data.notes,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def update_event(session: AsyncSession, event_id: int, data: EventUpdate) -> Event | None:
    event = await session.get(Event, event_id)
    if event is None:
        return None
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(event, key, value)
    if event.end_at <= event.start_at:
        raise ValueError("end_at must be after start_at")
    await session.commit()
    await session.refresh(event)
    return event


async def move_event(session: AsyncSession, event_id: int, new_start: datetime) -> Event | None:
    event = await session.get(Event, event_id)
    if event is None:
        return None
    duration = event.end_at - event.start_at
    event.start_at = new_start
    event.end_at = new_start + duration
    await session.commit()
    await session.refresh(event)
    return event


async def delete_event(session: AsyncSession, event_id: int) -> bool:
    event = await session.get(Event, event_id)
    if event is None:
        return False
    await session.delete(event)
    await session.commit()
    return True
```

- [ ] **Step 7: Create `backend/app/routers/events.py`**

```python
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.event import EventCreate, EventMove, EventOut, EventUpdate
from app.services import events as service

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=list[EventOut])
async def list_events(
    start: datetime | None = None,
    end: datetime | None = None,
    task_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    return await service.list_events(session, start=start, end=end, task_id=task_id)


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(data: EventCreate, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_event(session, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: int, session: AsyncSession = Depends(get_session)):
    event = await service.get_event(session, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: int, data: EventUpdate, session: AsyncSession = Depends(get_session)
):
    try:
        event = await service.update_event(session, event_id, data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


@router.post("/{event_id}/move", response_model=EventOut)
async def move_event(event_id: int, data: EventMove, session: AsyncSession = Depends(get_session)):
    event = await service.move_event(session, event_id, data.start_at)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(event_id: int, session: AsyncSession = Depends(get_session)):
    if not await service.delete_event(session, event_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "event not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 8: Register in `backend/app/main.py`**

```python
from app.routers import events as events_router

app.include_router(events_router.router)
```

- [ ] **Step 9: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (18 tests)

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat: add Event model, service, and REST endpoints"
```

---

### Task 5: Rule model with versioning

**Files:**
- Create: `backend/app/models/rule.py`, `backend/app/schemas/rule.py`, `backend/app/services/rules.py`, `backend/app/routers/rules.py`, `backend/tests/test_rules.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

**Interfaces:**
- Consumes: `Base`, `get_session`
- Produces: `Rule` model; `services.rules.list_rules(session) -> list[Rule]`, `get_active_rule(session) -> Rule | None`, `create_rule_version(session, data: RuleCreate) -> Rule`, `get_rule`, `delete_rule`, `to_spec(rule) -> RuleSpec` (the dataclass Task 6 consumes)

- [ ] **Step 1: Write the failing test — `backend/tests/test_rules.py`**

```python
from datetime import date

RULE_BODY = {
    "name": "6:3:1 baseline",
    "tolerance": 0.2,
    "exclude_tag_ids": [1, 8],
    "groups": [
        {"key": "A", "label": "Work · Study · Commute", "ratio": 6, "tag_ids": [2, 3, 4]},
        {"key": "B", "label": "Kids · Chores", "ratio": 3, "tag_ids": [5, 6]},
        {"key": "C", "label": "Fitness", "ratio": 1, "tag_ids": [7]},
    ],
    "note": "initial commitment",
}


async def test_create_rule_is_active(client):
    created = await client.post("/api/rules", json=RULE_BODY)
    assert created.status_code == 201
    assert created.json()["effective_to"] is None

    active = await client.get("/api/rules/active")
    assert active.json()["name"] == "6:3:1 baseline"


async def test_new_version_closes_previous(client):
    first_id = (await client.post("/api/rules", json=RULE_BODY)).json()["id"]

    loosened = {**RULE_BODY, "name": "6:3:1 loosened", "tolerance": 0.3, "note": "fitness hard"}
    second = await client.post("/api/rules", json=loosened)
    assert second.status_code == 201

    first = (await client.get(f"/api/rules/{first_id}")).json()
    assert first["effective_to"] == date.today().isoformat()
    assert second.json()["effective_to"] is None

    active = await client.get("/api/rules/active")
    assert active.json()["id"] == second.json()["id"]


async def test_rules_are_never_mutated_in_place(client):
    await client.post("/api/rules", json=RULE_BODY)
    # There is deliberately no PATCH route on rules.
    assert (await client.patch("/api/rules/1", json={"tolerance": 0.9})).status_code == 405


async def test_ratios_must_be_positive(client):
    bad = {**RULE_BODY, "groups": [{**RULE_BODY["groups"][0], "ratio": 0}]}
    assert (await client.post("/api/rules", json=bad)).status_code == 422


async def test_active_rule_404_when_none(client):
    assert (await client.get("/api/rules/active")).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_rules.py -v`
Expected: FAIL — `/api/rules` returns 404

- [ ] **Step 3: Create `backend/app/models/rule.py`**

```python
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    groups: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    tolerance: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    exclude_tag_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
```

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

```python
from app.models.event import Event, EventSource
from app.models.rule import Rule
from app.models.tag import Tag
from app.models.task import Priority, Task, TaskStatus

__all__ = ["Tag", "Task", "TaskStatus", "Priority", "Event", "EventSource", "Rule"]
```

- [ ] **Step 5: Create `backend/app/schemas/rule.py`**

```python
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class RuleGroup(BaseModel):
    key: str = Field(min_length=1, max_length=16)
    label: str = Field(min_length=1, max_length=120)
    ratio: float = Field(gt=0)
    tag_ids: list[int] = Field(default_factory=list)


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    groups: list[RuleGroup] = Field(min_length=1)
    tolerance: float = Field(default=0.2, ge=0, le=1)
    exclude_tag_ids: list[int] = Field(default_factory=list)
    note: str = ""


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    groups: list[RuleGroup]
    tolerance: float
    exclude_tag_ids: list[int]
    effective_from: date
    effective_to: date | None
    note: str
    created_at: datetime
```

- [ ] **Step 6: Create `backend/app/services/rules.py`**

```python
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Rule
from app.schemas.rule import RuleCreate


@dataclass(frozen=True)
class GroupSpec:
    key: str
    label: str
    ratio: float
    tag_ids: tuple[int, ...]


@dataclass(frozen=True)
class RuleSpec:
    """Plain, I/O-free view of a Rule, consumed by the pure analytics module."""

    groups: tuple[GroupSpec, ...]
    tolerance: float
    exclude_tag_ids: tuple[int, ...]


def to_spec(rule: Rule) -> RuleSpec:
    return RuleSpec(
        groups=tuple(
            GroupSpec(
                key=g["key"],
                label=g["label"],
                ratio=float(g["ratio"]),
                tag_ids=tuple(g.get("tag_ids", [])),
            )
            for g in rule.groups
        ),
        tolerance=float(rule.tolerance),
        exclude_tag_ids=tuple(rule.exclude_tag_ids),
    )


async def list_rules(session: AsyncSession) -> list[Rule]:
    stmt = select(Rule).order_by(Rule.effective_from.desc(), Rule.id.desc())
    return list((await session.scalars(stmt)).all())


async def get_rule(session: AsyncSession, rule_id: int) -> Rule | None:
    return await session.get(Rule, rule_id)


async def get_active_rule(session: AsyncSession) -> Rule | None:
    stmt = (
        select(Rule)
        .where(Rule.effective_to.is_(None))
        .order_by(Rule.effective_from.desc(), Rule.id.desc())
    )
    return (await session.scalars(stmt)).first()


async def create_rule_version(session: AsyncSession, data: RuleCreate) -> Rule:
    """Closes the currently open rule and inserts a new one. Never mutates in place."""
    today = date.today()
    current = await get_active_rule(session)
    if current is not None:
        current.effective_to = today

    rule = Rule(
        name=data.name,
        groups=[g.model_dump() for g in data.groups],
        tolerance=data.tolerance,
        exclude_tag_ids=list(data.exclude_tag_ids),
        effective_from=today,
        effective_to=None,
        note=data.note,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def delete_rule(session: AsyncSession, rule_id: int) -> bool:
    rule = await session.get(Rule, rule_id)
    if rule is None:
        return False
    await session.delete(rule)
    await session.commit()
    return True
```

- [ ] **Step 7: Create `backend/app/routers/rules.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.rule import RuleCreate, RuleOut
from app.services import rules as service

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("", response_model=list[RuleOut])
async def list_rules(session: AsyncSession = Depends(get_session)):
    return await service.list_rules(session)


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule_version(data: RuleCreate, session: AsyncSession = Depends(get_session)):
    return await service.create_rule_version(session, data)


@router.get("/active", response_model=RuleOut)
async def get_active_rule(session: AsyncSession = Depends(get_session)):
    rule = await service.get_active_rule(session)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active rule")
    return rule


@router.get("/{rule_id}", response_model=RuleOut)
async def get_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    rule = await service.get_rule(session, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rule not found")
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: int, session: AsyncSession = Depends(get_session)):
    if not await service.delete_rule(session, rule_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

`/active` must be declared **before** `/{rule_id}`, otherwise FastAPI matches `active` as a path param and returns 422.

- [ ] **Step 8: Register in `backend/app/main.py`**

```python
from app.routers import rules as rules_router

app.include_router(rules_router.router)
```

- [ ] **Step 9: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (23 tests)

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat: add Rule model with append-only versioning"
```

---

### Task 6: The analytics engine (pure)

This is the load-bearing task. Everything else is plumbing; this is the product.

**Files:**
- Create: `backend/app/services/analytics.py`, `backend/tests/test_analytics.py`

**Interfaces:**
- Consumes: `RuleSpec`, `GroupSpec` from `services.rules`
- Produces: `EventSlice` dataclass; `minutes_in_window(slice, start, end) -> int`, `split_minutes_by_day(slice) -> dict[date, int]`, `find_overlaps(slices) -> list[tuple[int, int]]`, `evaluate(slices, rule, period_start, period_end) -> Evaluation`, and `Evaluation` / `GroupResult` dataclasses with `.to_dict()`

**This module imports no ORM models and performs no I/O.** Callers convert `Event` rows into `EventSlice` before calling in.

- [ ] **Step 1: Write the failing test — `backend/tests/test_analytics.py`**

```python
from datetime import date, datetime, timedelta

import pytest

from app.services.analytics import EventSlice, evaluate, find_overlaps, split_minutes_by_day
from app.services.rules import GroupSpec, RuleSpec

REST, WORK, STUDY, COMMUTE, KIDS, CHORES, FITNESS, PERSONAL = 1, 2, 3, 4, 5, 6, 7, 8

RULE = RuleSpec(
    groups=(
        GroupSpec("A", "Work · Study · Commute", 6.0, (WORK, STUDY, COMMUTE)),
        GroupSpec("B", "Kids · Chores", 3.0, (KIDS, CHORES)),
        GroupSpec("C", "Fitness", 1.0, (FITNESS,)),
    ),
    tolerance=0.2,
    exclude_tag_ids=(REST, PERSONAL),
)

PERIOD_START = datetime(2026, 8, 1)
PERIOD_END = datetime(2026, 9, 1)


def slice_(id_: int, tag: int, day: int, start_h: int, hours: float) -> EventSlice:
    start = datetime(2026, 8, day, start_h)
    return EventSlice(
        id=id_, start_at=start, end_at=start + timedelta(hours=hours), tag_ids=(tag,)
    )


def test_target_shares_come_from_ratios():
    result = evaluate([slice_(1, WORK, 3, 9, 6.0)], RULE, PERIOD_START, PERIOD_END)
    by_key = {g.key: g for g in result.groups}
    assert by_key["A"].share_target == pytest.approx(0.6)
    assert by_key["B"].share_target == pytest.approx(0.3)
    assert by_key["C"].share_target == pytest.approx(0.1)


def test_perfect_631_all_pass():
    slices = [
        slice_(1, WORK, 3, 8, 6.0),
        slice_(2, KIDS, 3, 15, 3.0),
        slice_(3, FITNESS, 3, 19, 1.0),
    ]
    result = evaluate(slices, RULE, PERIOD_START, PERIOD_END)
    assert result.total_minutes == 600
    assert all(g.verdict == "pass" for g in result.groups)


def test_spec_worked_example_fitness_fails_under():
    """From the spec: a template weekday is 10h / 5h / 1h = 62/31/6%, so C is under."""
    slices = [
        slice_(1, WORK, 3, 9, 7.0),
        slice_(2, STUDY, 3, 21, 1.5),
        slice_(3, COMMUTE, 3, 8, 1.5),
        slice_(4, KIDS, 3, 17, 4.0),
        slice_(5, CHORES, 3, 6, 1.0),
        slice_(6, FITNESS, 3, 5, 1.0),
    ]
    result = evaluate(slices, RULE, PERIOD_START, PERIOD_END)
    by_key = {g.key: g for g in result.groups}

    assert by_key["A"].share_actual == pytest.approx(10 / 16)
    assert by_key["A"].verdict == "pass"
    assert by_key["B"].verdict == "pass"
    assert by_key["C"].share_actual == pytest.approx(1 / 16)
    assert by_key["C"].verdict == "under"


def test_excluded_tags_leave_the_denominator():
    slices = [
        slice_(1, WORK, 3, 8, 6.0),
        slice_(2, KIDS, 3, 15, 3.0),
        slice_(3, FITNESS, 3, 19, 1.0),
        slice_(4, REST, 3, 23, 8.0),
        slice_(5, PERSONAL, 4, 13, 3.0),
    ]
    result = evaluate(slices, RULE, PERIOD_START, PERIOD_END)
    assert result.total_minutes == 600
    assert result.excluded_minutes == 660
    assert all(g.verdict == "pass" for g in result.groups)


def test_unassigned_tag_is_reported_not_counted():
    unknown = 99
    slices = [
        slice_(1, WORK, 3, 8, 6.0),
        slice_(2, KIDS, 3, 15, 3.0),
        slice_(3, FITNESS, 3, 19, 1.0),
        slice_(4, unknown, 4, 10, 3.5),
    ]
    result = evaluate(slices, RULE, PERIOD_START, PERIOD_END)
    assert result.total_minutes == 600
    assert result.unassigned_minutes == 210
    assert result.unassigned_tag_ids == [unknown]


def test_empty_period_has_no_data():
    result = evaluate([], RULE, PERIOD_START, PERIOD_END)
    assert result.has_data is False
    assert result.total_minutes == 0
    assert all(g.minutes == 0 for g in result.groups)


def test_all_events_excluded_has_no_data():
    result = evaluate([slice_(1, REST, 3, 23, 8.0)], RULE, PERIOD_START, PERIOD_END)
    assert result.has_data is False
    assert result.excluded_minutes == 480


def test_zero_minute_group_is_under_with_minus_one_deviation():
    slices = [slice_(1, WORK, 3, 8, 6.0), slice_(2, KIDS, 3, 15, 3.0)]
    result = evaluate(slices, RULE, PERIOD_START, PERIOD_END)
    fitness = next(g for g in result.groups if g.key == "C")
    assert fitness.minutes == 0
    assert fitness.deviation == pytest.approx(-1.0)
    assert fitness.verdict == "under"


def test_events_are_clipped_to_the_period():
    """A rest-of-July event bleeding into August contributes only its August minutes."""
    spanning = EventSlice(
        id=1,
        start_at=datetime(2026, 7, 31, 22),
        end_at=datetime(2026, 8, 1, 6),
        tag_ids=(WORK,),
    )
    result = evaluate([spanning], RULE, PERIOD_START, PERIOD_END)
    assert result.total_minutes == 360


def test_primary_tag_attributes_the_whole_event():
    multi = EventSlice(
        id=1,
        start_at=datetime(2026, 8, 3, 9),
        end_at=datetime(2026, 8, 3, 11),
        tag_ids=(WORK, FITNESS),
    )
    result = evaluate([multi], RULE, PERIOD_START, PERIOD_END)
    by_key = {g.key: g for g in result.groups}
    assert by_key["A"].minutes == 120
    assert by_key["C"].minutes == 0


def test_untagged_event_counts_as_unassigned():
    bare = EventSlice(
        id=1, start_at=datetime(2026, 8, 3, 9), end_at=datetime(2026, 8, 3, 10), tag_ids=()
    )
    result = evaluate([bare], RULE, PERIOD_START, PERIOD_END)
    assert result.unassigned_minutes == 60
    assert result.has_data is False


def test_overlaps_are_counted_and_reported():
    a = EventSlice(1, datetime(2026, 8, 3, 9), datetime(2026, 8, 3, 11), (WORK,))
    b = EventSlice(2, datetime(2026, 8, 3, 10), datetime(2026, 8, 3, 12), (KIDS,))
    result = evaluate([a, b], RULE, PERIOD_START, PERIOD_END)
    assert result.total_minutes == 240
    assert result.overlaps == [(1, 2)]


def test_find_overlaps_ignores_touching_events():
    a = EventSlice(1, datetime(2026, 8, 3, 9), datetime(2026, 8, 3, 10), (WORK,))
    b = EventSlice(2, datetime(2026, 8, 3, 10), datetime(2026, 8, 3, 11), (WORK,))
    assert find_overlaps([a, b]) == []


def test_split_minutes_by_day_divides_at_midnight():
    overnight = EventSlice(
        1, datetime(2026, 8, 3, 23), datetime(2026, 8, 4, 7), (REST,)
    )
    assert split_minutes_by_day(overnight) == {date(2026, 8, 3): 60, date(2026, 8, 4): 420}


def test_split_minutes_by_day_single_day():
    same_day = EventSlice(1, datetime(2026, 8, 3, 9), datetime(2026, 8, 3, 10, 30), (WORK,))
    assert split_minutes_by_day(same_day) == {date(2026, 8, 3): 90}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_analytics.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.analytics`

- [ ] **Step 3: Create `backend/app/services/analytics.py`**

```python
"""Pure ratio analytics. No I/O, no ORM imports — only dataclasses in and out.

This is the module most likely to be subtly wrong, so it is kept free of
infrastructure and covered exhaustively.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.services.rules import RuleSpec

PASS = "pass"
OVER = "over"
UNDER = "under"


@dataclass(frozen=True)
class EventSlice:
    """An Event reduced to exactly what analytics needs."""

    id: int
    start_at: datetime
    end_at: datetime
    tag_ids: tuple[int, ...] = ()

    @property
    def primary_tag_id(self) -> int | None:
        return self.tag_ids[0] if self.tag_ids else None


@dataclass(frozen=True)
class GroupResult:
    key: str
    label: str
    ratio: float
    minutes: int
    share_actual: float
    share_target: float
    deviation: float
    verdict: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "ratio": self.ratio,
            "minutes": self.minutes,
            "hours": round(self.minutes / 60, 2),
            "share_actual": round(self.share_actual, 4),
            "share_target": round(self.share_target, 4),
            "deviation": round(self.deviation, 4),
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class Evaluation:
    total_minutes: int
    groups: list[GroupResult]
    minutes_by_tag: dict[int, int]
    unassigned_minutes: int
    unassigned_tag_ids: list[int]
    excluded_minutes: int
    overlaps: list[tuple[int, int]] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return self.total_minutes > 0

    def to_dict(self) -> dict:
        return {
            "has_data": self.has_data,
            "total_minutes": self.total_minutes,
            "total_hours": round(self.total_minutes / 60, 2),
            "groups": [g.to_dict() for g in self.groups],
            "minutes_by_tag": {str(k): v for k, v in self.minutes_by_tag.items()},
            "unassigned_minutes": self.unassigned_minutes,
            "unassigned_tag_ids": self.unassigned_tag_ids,
            "excluded_minutes": self.excluded_minutes,
            "overlaps": [list(pair) for pair in self.overlaps],
        }


def minutes_in_window(slice_: EventSlice, start: datetime, end: datetime) -> int:
    """Minutes of `slice_` falling inside the half-open window [start, end)."""
    lo = max(slice_.start_at, start)
    hi = min(slice_.end_at, end)
    if hi <= lo:
        return 0
    return int((hi - lo).total_seconds() // 60)


def split_minutes_by_day(slice_: EventSlice) -> dict[date, int]:
    """Distribute an event's minutes across the calendar days it touches."""
    out: dict[date, int] = {}
    cursor = slice_.start_at
    while cursor < slice_.end_at:
        day_end = datetime.combine(cursor.date(), datetime.min.time()) + timedelta(days=1)
        chunk_end = min(day_end, slice_.end_at)
        minutes = int((chunk_end - cursor).total_seconds() // 60)
        if minutes:
            out[cursor.date()] = out.get(cursor.date(), 0) + minutes
        cursor = chunk_end
    return out


def find_overlaps(slices: list[EventSlice]) -> list[tuple[int, int]]:
    """Pairs of event ids whose intervals genuinely intersect. Touching is not overlap."""
    ordered = sorted(slices, key=lambda s: (s.start_at, s.id))
    pairs: list[tuple[int, int]] = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            if b.start_at >= a.end_at:
                break
            pairs.append((a.id, b.id))
    return pairs


def evaluate(
    slices: list[EventSlice],
    rule: RuleSpec,
    period_start: datetime,
    period_end: datetime,
) -> Evaluation:
    excluded = set(rule.exclude_tag_ids)
    tag_to_group: dict[int, str] = {
        tag_id: group.key for group in rule.groups for tag_id in group.tag_ids
    }

    minutes_by_tag: dict[int, int] = {}
    minutes_by_group: dict[str, int] = {g.key: 0 for g in rule.groups}
    unassigned_minutes = 0
    unassigned_tags: set[int] = set()
    excluded_minutes = 0

    for s in slices:
        minutes = minutes_in_window(s, period_start, period_end)
        if minutes == 0:
            continue
        tag_id = s.primary_tag_id
        if tag_id is not None:
            minutes_by_tag[tag_id] = minutes_by_tag.get(tag_id, 0) + minutes
        if tag_id in excluded:
            excluded_minutes += minutes
            continue
        group_key = tag_to_group.get(tag_id) if tag_id is not None else None
        if group_key is None:
            unassigned_minutes += minutes
            if tag_id is not None:
                unassigned_tags.add(tag_id)
            continue
        minutes_by_group[group_key] += minutes

    total = sum(minutes_by_group.values())
    ratio_sum = sum(g.ratio for g in rule.groups)

    groups: list[GroupResult] = []
    for g in rule.groups:
        minutes = minutes_by_group[g.key]
        share_target = g.ratio / ratio_sum if ratio_sum else 0.0
        share_actual = minutes / total if total else 0.0
        if share_target == 0:
            deviation = 0.0
        else:
            deviation = (share_actual - share_target) / share_target
        if not total:
            verdict = UNDER
        elif abs(deviation) <= rule.tolerance:
            verdict = PASS
        else:
            verdict = OVER if deviation > 0 else UNDER
        groups.append(
            GroupResult(
                key=g.key,
                label=g.label,
                ratio=g.ratio,
                minutes=minutes,
                share_actual=share_actual,
                share_target=share_target,
                deviation=deviation,
                verdict=verdict,
            )
        )

    in_period = [s for s in slices if minutes_in_window(s, period_start, period_end) > 0]

    return Evaluation(
        total_minutes=total,
        groups=groups,
        minutes_by_tag=minutes_by_tag,
        unassigned_minutes=unassigned_minutes,
        unassigned_tag_ids=sorted(unassigned_tags),
        excluded_minutes=excluded_minutes,
        overlaps=find_overlaps(in_period),
    )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/pytest tests/test_analytics.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Run the whole suite**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (38 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/
git commit -m "feat: add pure ratio analytics engine with relative-tolerance verdicts"
```

---

### Task 7: Analytics endpoint

**Files:**
- Create: `backend/app/routers/analytics.py`, `backend/tests/test_analytics_api.py`
- Modify: `backend/app/services/analytics.py` (add nothing — this task only adds a caller), `backend/app/main.py`
- Create: `backend/app/services/evaluation.py`

**Interfaces:**
- Consumes: `services.analytics.evaluate`, `services.events.list_events`, `services.rules.get_active_rule` / `to_spec`
- Produces: `services.evaluation.evaluate_period(session, period_start: datetime, period_end: datetime, rule_id: int | None = None) -> tuple[Evaluation, Rule]`; raises `NoActiveRule`

- [ ] **Step 1: Write the failing test — `backend/tests/test_analytics_api.py`**

```python
RULE_BODY = {
    "name": "6:3:1 baseline",
    "tolerance": 0.2,
    "exclude_tag_ids": [],
    "groups": [
        {"key": "A", "label": "Work", "ratio": 6, "tag_ids": [1]},
        {"key": "B", "label": "Kids", "ratio": 3, "tag_ids": [2]},
        {"key": "C", "label": "Fitness", "ratio": 1, "tag_ids": [3]},
    ],
}


async def _setup(client):
    for name, color in (("Work", "#DA96A4"), ("Kids", "#BDBD9B"), ("Fitness", "#8FA8A2")):
        await client.post("/api/tags", json={"name": name, "color": color})
    await client.post("/api/rules", json=RULE_BODY)


async def test_evaluate_period_uses_active_rule(client):
    await _setup(client)
    for tag_id, hours in ((1, 6), (2, 3), (3, 1)):
        await client.post(
            "/api/events",
            json={
                "task_name": f"tag{tag_id}",
                "start_at": "2026-08-03T00:00:00",
                "end_at": f"2026-08-03T{hours:02d}:00:00",
                "tag_ids": [tag_id],
            },
        )

    result = await client.post(
        "/api/analytics/evaluate",
        json={"period_start": "2026-08-01T00:00:00", "period_end": "2026-09-01T00:00:00"},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["metrics"]["has_data"] is True
    assert body["rule"]["name"] == "6:3:1 baseline"
    assert {g["key"]: g["verdict"] for g in body["metrics"]["groups"]}["A"] == "pass"


async def test_evaluate_without_rule_returns_409(client):
    result = await client.post(
        "/api/analytics/evaluate",
        json={"period_start": "2026-08-01T00:00:00", "period_end": "2026-09-01T00:00:00"},
    )
    assert result.status_code == 409


async def test_evaluate_with_explicit_rule_id(client):
    await _setup(client)
    rule_id = (await client.get("/api/rules/active")).json()["id"]
    result = await client.post(
        "/api/analytics/evaluate",
        json={
            "period_start": "2026-08-01T00:00:00",
            "period_end": "2026-09-01T00:00:00",
            "rule_id": rule_id,
        },
    )
    assert result.status_code == 200
    assert result.json()["rule"]["id"] == rule_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_analytics_api.py -v`
Expected: FAIL — `/api/analytics/evaluate` returns 404

- [ ] **Step 3: Create `backend/app/services/evaluation.py`**

```python
"""Bridges the database to the pure analytics module."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Rule
from app.services import events as event_service
from app.services import rules as rule_service
from app.services.analytics import Evaluation, EventSlice, evaluate


class NoActiveRule(Exception):
    """Raised when an evaluation is requested but no rule has ever been created."""


def to_slice(event: Event) -> EventSlice:
    return EventSlice(
        id=event.id,
        start_at=event.start_at,
        end_at=event.end_at,
        tag_ids=tuple(event.tag_ids),
    )


async def evaluate_period(
    session: AsyncSession,
    period_start: datetime,
    period_end: datetime,
    rule_id: int | None = None,
) -> tuple[Evaluation, Rule]:
    if rule_id is None:
        rule = await rule_service.get_active_rule(session)
    else:
        rule = await rule_service.get_rule(session, rule_id)
    if rule is None:
        raise NoActiveRule()

    rows = await event_service.list_events(session, start=period_start, end=period_end)
    slices = [to_slice(e) for e in rows]
    return evaluate(slices, rule_service.to_spec(rule), period_start, period_end), rule
```

- [ ] **Step 4: Create `backend/app/routers/analytics.py`**

```python
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.rule import RuleOut
from app.services import evaluation as service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class EvaluateRequest(BaseModel):
    period_start: datetime
    period_end: datetime
    rule_id: int | None = None


@router.post("/evaluate")
async def evaluate_period(
    body: EvaluateRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    try:
        result, rule = await service.evaluate_period(
            session, body.period_start, body.period_end, body.rule_id
        )
    except service.NoActiveRule:
        raise HTTPException(status.HTTP_409_CONFLICT, "no active rule — create one first")
    return {
        "period_start": body.period_start,
        "period_end": body.period_end,
        "rule": RuleOut.model_validate(rule).model_dump(mode="json"),
        "metrics": result.to_dict(),
    }
```

- [ ] **Step 5: Register in `backend/app/main.py`**

```python
from app.routers import analytics as analytics_router

app.include_router(analytics_router.router)
```

- [ ] **Step 6: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (41 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/
git commit -m "feat: add analytics evaluation endpoint over the pure engine"
```

---

### Task 8: Template, TemplateBlock, and week materialization

**Files:**
- Create: `backend/app/models/template.py`, `backend/app/schemas/template.py`, `backend/app/services/templates.py`, `backend/app/routers/templates.py`, `backend/tests/test_templates.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

**Interfaces:**
- Consumes: `services.tasks.find_or_create_by_name`, `services.events.create_event`, `EventCreate`
- Produces: `Template`, `TemplateBlock` models; `services.templates.get_active_template(session) -> Template | None`, `create_template`, `list_templates`, `get_template`, `delete_template`, `create_block(session, template_id, data: TemplateBlockCreate) -> TemplateBlock | None`, `update_block(session, block_id, data) -> TemplateBlock | None`, `delete_block(session, block_id) -> bool`, `materialize_week(session, any_day: date, template=None) -> tuple[date, list[Event], list[date]]`, `week_bounds(any_day: date) -> tuple[date, date]`

- [ ] **Step 1: Write the failing test — `backend/tests/test_templates.py`**

```python
WEEKDAY_BLOCK = {
    "days": [1, 2, 3, 4, 5],
    "start_time": "09:30:00",
    "end_time": "16:30:00",
    "task_name": "Work",
    "tag_ids": [],
}
OVERNIGHT_BLOCK = {
    "days": [1, 2, 3, 4, 5, 6, 7],
    "start_time": "23:00:00",
    "end_time": "07:00:00",
    "task_name": "Rest",
    "tag_ids": [],
}


async def _template(client, blocks):
    template_id = (await client.post("/api/templates", json={"name": "Default"})).json()["id"]
    for block in blocks:
        await client.post(f"/api/templates/{template_id}/blocks", json=block)
    return template_id


async def test_materialize_creates_one_event_per_matching_day(client):
    await _template(client, [WEEKDAY_BLOCK])
    result = await client.post("/api/weeks/2026-08-03/materialize")
    assert result.status_code == 200
    assert result.json()["created"] == 5

    events = await client.get(
        "/api/events", params={"start": "2026-08-03T00:00:00", "end": "2026-08-10T00:00:00"}
    )
    starts = sorted(e["start_at"] for e in events.json())
    assert starts[0] == "2026-08-03T09:30:00"
    assert len(starts) == 5


async def test_overnight_block_ends_next_morning(client):
    await _template(client, [OVERNIGHT_BLOCK])
    await client.post("/api/weeks/2026-08-03/materialize")
    events = (
        await client.get(
            "/api/events", params={"start": "2026-08-03T00:00:00", "end": "2026-08-04T00:00:00"}
        )
    ).json()
    monday = next(e for e in events if e["start_at"] == "2026-08-03T23:00:00")
    assert monday["end_at"] == "2026-08-04T07:00:00"


async def test_materialize_skips_days_that_already_have_events(client):
    await _template(client, [WEEKDAY_BLOCK])
    await client.post(
        "/api/events",
        json={
            "task_name": "Dentist",
            "start_at": "2026-08-05T15:00:00",
            "end_at": "2026-08-05T16:00:00",
        },
    )
    result = await client.post("/api/weeks/2026-08-03/materialize")
    assert result.json()["created"] == 4
    assert result.json()["skipped_days"] == ["2026-08-05"]


async def test_materialize_is_idempotent(client):
    await _template(client, [WEEKDAY_BLOCK])
    assert (await client.post("/api/weeks/2026-08-03/materialize")).json()["created"] == 5
    assert (await client.post("/api/weeks/2026-08-03/materialize")).json()["created"] == 0


async def test_materialize_reuses_one_task_across_the_week(client):
    await _template(client, [WEEKDAY_BLOCK])
    await client.post("/api/weeks/2026-08-03/materialize")
    events = (
        await client.get(
            "/api/events", params={"start": "2026-08-03T00:00:00", "end": "2026-08-10T00:00:00"}
        )
    ).json()
    assert len({e["task_id"] for e in events}) == 1


async def test_materialized_events_are_tagged_as_template_source(client):
    await _template(client, [WEEKDAY_BLOCK])
    await client.post("/api/weeks/2026-08-03/materialize")
    events = (
        await client.get(
            "/api/events", params={"start": "2026-08-03T00:00:00", "end": "2026-08-10T00:00:00"}
        )
    ).json()
    assert all(e["source"] == "template" for e in events)
    assert all(e["template_block_id"] is not None for e in events)


async def test_materialize_without_template_returns_409(client):
    assert (await client.post("/api/weeks/2026-08-03/materialize")).status_code == 409


async def test_any_date_in_the_week_resolves_to_its_monday(client):
    await _template(client, [WEEKDAY_BLOCK])
    # Wednesday 2026-08-05 belongs to the week starting Monday 2026-08-03.
    result = await client.post("/api/weeks/2026-08-05/materialize")
    assert result.json()["week_start"] == "2026-08-03"


async def test_delete_block(client):
    template_id = await _template(client, [WEEKDAY_BLOCK])
    blocks = (await client.get(f"/api/templates/{template_id}")).json()["blocks"]
    block_id = blocks[0]["id"]
    assert (await client.delete(f"/api/template-blocks/{block_id}")).status_code == 204
    assert (await client.get(f"/api/templates/{template_id}")).json()["blocks"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_templates.py -v`
Expected: FAIL — `/api/templates` returns 404

- [ ] **Step 3: Create `backend/app/models/template.py`**

```python
from datetime import datetime, time

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    blocks: Mapped[list["TemplateBlock"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="TemplateBlock.sort_order",
    )


class TemplateBlock(Base):
    __tablename__ = "template_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    days: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tag_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    template: Mapped[Template] = relationship(back_populates="blocks")
```

`days` holds ISO weekdays 1–7, so `[1,2,3,4,5]` is 周一–周五, `[6]` is 周六, `[7]` is 周日.

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

```python
from app.models.event import Event, EventSource
from app.models.rule import Rule
from app.models.tag import Tag
from app.models.task import Priority, Task, TaskStatus
from app.models.template import Template, TemplateBlock

__all__ = [
    "Tag", "Task", "TaskStatus", "Priority", "Event", "EventSource",
    "Rule", "Template", "TemplateBlock",
]
```

- [ ] **Step 5: Create `backend/app/schemas/template.py`**

```python
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TemplateBlockCreate(BaseModel):
    days: list[int] = Field(min_length=1)
    start_time: time
    end_time: time
    task_name: str = Field(min_length=1, max_length=200)
    tag_ids: list[int] = Field(default_factory=list)
    sort_order: int = 0

    @field_validator("days")
    @classmethod
    def days_are_iso_weekdays(cls, value: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in value):
            raise ValueError("days must be ISO weekdays 1-7")
        return value


class TemplateBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    days: list[int]
    start_time: time
    end_time: time
    task_name: str
    tag_ids: list[int]
    sort_order: int


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    created_at: datetime
    blocks: list[TemplateBlockOut]


class MaterializeResult(BaseModel):
    week_start: str
    created: int
    skipped_days: list[str]
```

- [ ] **Step 6: Create `backend/app/services/templates.py`**

```python
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Template, TemplateBlock
from app.models.event import EventSource
from app.schemas.event import EventCreate
from app.schemas.template import TemplateBlockCreate, TemplateCreate
from app.services import events as event_service


class NoActiveTemplate(Exception):
    """Raised when materialization is requested but no active template exists."""


def week_bounds(any_day: date) -> tuple[date, date]:
    """Monday and the following Monday for the week containing `any_day`."""
    monday = any_day - timedelta(days=any_day.isoweekday() - 1)
    return monday, monday + timedelta(days=7)


async def list_templates(session: AsyncSession) -> list[Template]:
    stmt = select(Template).order_by(Template.id)
    return list((await session.scalars(stmt)).all())


async def get_template(session: AsyncSession, template_id: int) -> Template | None:
    # populate_existing re-runs the selectin load of `blocks`. Without it, a Template
    # already in the identity map returns a stale block list after an add or delete.
    stmt = (
        select(Template)
        .where(Template.id == template_id)
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(stmt)).first()


async def get_active_template(session: AsyncSession) -> Template | None:
    stmt = (
        select(Template)
        .where(Template.is_active.is_(True))
        .order_by(Template.id.desc())
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(stmt)).first()


async def create_template(session: AsyncSession, data: TemplateCreate) -> Template:
    template = Template(**data.model_dump())
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template


async def delete_template(session: AsyncSession, template_id: int) -> bool:
    template = await session.get(Template, template_id)
    if template is None:
        return False
    await session.delete(template)
    await session.commit()
    return True


async def create_block(
    session: AsyncSession, template_id: int, data: TemplateBlockCreate
) -> TemplateBlock | None:
    if await session.get(Template, template_id) is None:
        return None
    block = TemplateBlock(template_id=template_id, **data.model_dump())
    session.add(block)
    await session.commit()
    await session.refresh(block)
    return block


async def update_block(
    session: AsyncSession, block_id: int, data: TemplateBlockCreate
) -> TemplateBlock | None:
    block = await session.get(TemplateBlock, block_id)
    if block is None:
        return None
    for key, value in data.model_dump().items():
        setattr(block, key, value)
    await session.commit()
    await session.refresh(block)
    return block


async def delete_block(session: AsyncSession, block_id: int) -> bool:
    block = await session.get(TemplateBlock, block_id)
    if block is None:
        return False
    await session.delete(block)
    await session.commit()
    return True


async def _days_with_events(session: AsyncSession, monday: date, next_monday: date) -> set[date]:
    rows = await event_service.list_events(
        session,
        start=datetime.combine(monday, datetime.min.time()),
        end=datetime.combine(next_monday, datetime.min.time()),
    )
    return {e.start_at.date() for e in rows}


async def materialize_week(
    session: AsyncSession, any_day: date, template: Template | None = None
) -> tuple[date, list[Event], list[date]]:
    """Create template events for the week containing `any_day`.

    Days that already hold any event are skipped entirely, which makes this
    idempotent: a missed Sunday followed by a lazy trigger cannot double-create.
    """
    if template is None:
        template = await get_active_template(session)
    if template is None:
        raise NoActiveTemplate()

    monday, next_monday = week_bounds(any_day)
    occupied = await _days_with_events(session, monday, next_monday)

    created: list[Event] = []
    skipped = sorted(occupied)

    for offset in range(7):
        day = monday + timedelta(days=offset)
        if day in occupied:
            continue
        for block in template.blocks:
            if day.isoweekday() not in block.days:
                continue
            start = datetime.combine(day, block.start_time)
            end = datetime.combine(day, block.end_time)
            if end <= start:  # crosses midnight
                end += timedelta(days=1)
            event = await event_service.create_event(
                session,
                EventCreate(
                    task_name=block.task_name,
                    start_at=start,
                    end_at=end,
                    tag_ids=list(block.tag_ids),
                    source=EventSource.TEMPLATE,
                    template_block_id=block.id,
                ),
            )
            created.append(event)

    return monday, created, skipped
```

- [ ] **Step 7: Create `backend/app/routers/templates.py`**

```python
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.template import (
    MaterializeResult,
    TemplateBlockCreate,
    TemplateBlockOut,
    TemplateCreate,
    TemplateOut,
)
from app.services import templates as service

router = APIRouter(prefix="/api/templates", tags=["templates"])
block_router = APIRouter(prefix="/api/template-blocks", tags=["templates"])
week_router = APIRouter(prefix="/api/weeks", tags=["weeks"])


@router.get("", response_model=list[TemplateOut])
async def list_templates(session: AsyncSession = Depends(get_session)):
    return await service.list_templates(session)


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(data: TemplateCreate, session: AsyncSession = Depends(get_session)):
    return await service.create_template(session, data)


@router.get("/active", response_model=TemplateOut)
async def get_active_template(session: AsyncSession = Depends(get_session)):
    template = await service.get_active_template(session)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active template")
    return template


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(template_id: int, session: AsyncSession = Depends(get_session)):
    template = await service.get_template(session, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: int, session: AsyncSession = Depends(get_session)):
    if not await service.delete_template(session, template_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{template_id}/blocks", response_model=TemplateBlockOut, status_code=status.HTTP_201_CREATED
)
async def create_block(
    template_id: int, data: TemplateBlockCreate, session: AsyncSession = Depends(get_session)
):
    block = await service.create_block(session, template_id, data)
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "template not found")
    return block


@block_router.patch("/{block_id}", response_model=TemplateBlockOut)
async def update_block(
    block_id: int, data: TemplateBlockCreate, session: AsyncSession = Depends(get_session)
):
    block = await service.update_block(session, block_id, data)
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "block not found")
    return block


@block_router.delete("/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(block_id: int, session: AsyncSession = Depends(get_session)):
    if not await service.delete_block(session, block_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "block not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@week_router.post("/{any_day}/materialize", response_model=MaterializeResult)
async def materialize_week(any_day: date, session: AsyncSession = Depends(get_session)):
    try:
        monday, created, skipped = await service.materialize_week(session, any_day)
    except service.NoActiveTemplate:
        raise HTTPException(status.HTTP_409_CONFLICT, "no active template — create one first")
    return MaterializeResult(
        week_start=monday.isoformat(),
        created=len(created),
        skipped_days=[d.isoformat() for d in skipped],
    )
```

- [ ] **Step 8: Register in `backend/app/main.py`**

```python
from app.routers import templates as templates_router

app.include_router(templates_router.router)
app.include_router(templates_router.block_router)
app.include_router(templates_router.week_router)
```

- [ ] **Step 9: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (50 tests)

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat: add Template, TemplateBlock, and idempotent week materialization"
```

---

### Task 9: Week and month calendar payloads with lazy materialization

**Files:**
- Create: `backend/app/services/calendar.py`, `backend/app/routers/calendar.py`, `backend/tests/test_calendar.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `services.events.list_events`, `services.templates.materialize_week` / `week_bounds`, `services.analytics.split_minutes_by_day`, `services.evaluation.to_slice`
- Produces: `services.calendar.get_week(session, any_day: date, allow_materialize: bool = True) -> dict`, `get_month(session, year: int, month: int) -> dict`

- [ ] **Step 1: Write the failing test — `backend/tests/test_calendar.py`**

```python
from datetime import date, timedelta

WEEKDAY_BLOCK = {
    "days": [1, 2, 3, 4, 5],
    "start_time": "09:30:00",
    "end_time": "16:30:00",
    "task_name": "Work",
    "tag_ids": [],
}


async def _template(client):
    template_id = (await client.post("/api/templates", json={"name": "Default"})).json()["id"]
    await client.post(f"/api/templates/{template_id}/blocks", json=WEEKDAY_BLOCK)


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.isoweekday() - 1)


async def test_week_payload_has_bounds_and_events(client):
    await _template(client)
    monday = _this_monday()
    result = await client.get(f"/api/weeks/{monday.isoformat()}")
    assert result.status_code == 200
    body = result.json()
    assert body["week_start"] == monday.isoformat()
    assert body["week_end"] == (monday + timedelta(days=7)).isoformat()
    assert len(body["events"]) == 5
    assert body["materialized"] is True


async def test_current_week_lazily_materializes(client):
    await _template(client)
    monday = _this_monday()
    assert (await client.get(f"/api/weeks/{monday.isoformat()}")).json()["materialized"] is True
    # Second read must not create anything further.
    second = await client.get(f"/api/weeks/{monday.isoformat()}")
    assert second.json()["materialized"] is False
    assert len(second.json()["events"]) == 5


async def test_next_week_lazily_materializes(client):
    await _template(client)
    next_monday = _this_monday() + timedelta(days=7)
    body = (await client.get(f"/api/weeks/{next_monday.isoformat()}")).json()
    assert body["materialized"] is True
    assert len(body["events"]) == 5


async def test_past_weeks_are_never_materialized(client):
    await _template(client)
    past_monday = _this_monday() - timedelta(days=7)
    body = (await client.get(f"/api/weeks/{past_monday.isoformat()}")).json()
    assert body["materialized"] is False
    assert body["events"] == []


async def test_week_beyond_next_is_not_materialized(client):
    await _template(client)
    far = _this_monday() + timedelta(days=21)
    body = (await client.get(f"/api/weeks/{far.isoformat()}")).json()
    assert body["materialized"] is False
    assert body["events"] == []


async def test_week_without_template_returns_empty_not_error(client):
    monday = _this_monday()
    body = (await client.get(f"/api/weeks/{monday.isoformat()}")).json()
    assert body["events"] == []
    assert body["materialized"] is False


async def test_month_payload_rolls_minutes_per_day_per_tag(client):
    tag_id = (
        await client.post("/api/tags", json={"name": "Rest", "color": "#DEDECF"})
    ).json()["id"]
    await client.post(
        "/api/events",
        json={
            "task_name": "Sleep",
            "start_at": "2026-08-03T23:00:00",
            "end_at": "2026-08-04T07:00:00",
            "tag_ids": [tag_id],
        },
    )
    body = (await client.get("/api/months/2026-08")).json()
    days = {d["date"]: d for d in body["days"]}
    assert days["2026-08-03"]["minutes_by_tag"][str(tag_id)] == 60
    assert days["2026-08-04"]["minutes_by_tag"][str(tag_id)] == 420


async def test_month_payload_covers_every_day(client):
    body = (await client.get("/api/months/2026-08")).json()
    assert len(body["days"]) == 31
    assert body["days"][0]["date"] == "2026-08-01"
    assert body["days"][-1]["date"] == "2026-08-31"


async def test_bad_month_format_returns_422(client):
    assert (await client.get("/api/months/2026-13")).status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_calendar.py -v`
Expected: FAIL — `GET /api/weeks/{day}` is not defined (only the `/materialize` POST exists)

- [ ] **Step 3: Create `backend/app/services/calendar.py`**

```python
import calendar as calendar_lib
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event
from app.services import events as event_service
from app.services import templates as template_service
from app.services.analytics import EventSlice, split_minutes_by_day


def _is_materializable(monday: date) -> bool:
    """Only the current and next week may be created on read. History is a record."""
    today = date.today()
    this_monday = today - timedelta(days=today.isoweekday() - 1)
    return monday in (this_monday, this_monday + timedelta(days=7))


async def get_week(
    session: AsyncSession, any_day: date, allow_materialize: bool = True
) -> dict:
    monday, next_monday = template_service.week_bounds(any_day)
    start = datetime.combine(monday, datetime.min.time())
    end = datetime.combine(next_monday, datetime.min.time())

    rows = await event_service.list_events(session, start=start, end=end)
    materialized = False

    if not rows and allow_materialize and _is_materializable(monday):
        try:
            await template_service.materialize_week(session, monday)
        except template_service.NoActiveTemplate:
            pass
        else:
            materialized = True
            rows = await event_service.list_events(session, start=start, end=end)

    return {
        "week_start": monday.isoformat(),
        "week_end": next_monday.isoformat(),
        "materialized": materialized,
        "events": rows,
    }


async def get_month(session: AsyncSession, year: int, month: int) -> dict:
    first = date(year, month, 1)
    days_in_month = calendar_lib.monthrange(year, month)[1]
    last_exclusive = first + timedelta(days=days_in_month)

    rows: list[Event] = await event_service.list_events(
        session,
        start=datetime.combine(first, datetime.min.time()),
        end=datetime.combine(last_exclusive, datetime.min.time()),
    )

    per_day: dict[date, dict[int, int]] = {}
    counts: dict[date, int] = {}
    for row in rows:
        slice_ = EventSlice(
            id=row.id, start_at=row.start_at, end_at=row.end_at, tag_ids=tuple(row.tag_ids)
        )
        tag_id = slice_.primary_tag_id
        for day, minutes in split_minutes_by_day(slice_).items():
            if not (first <= day < last_exclusive):
                continue
            counts[day] = counts.get(day, 0) + 1
            if tag_id is None:
                continue
            bucket = per_day.setdefault(day, {})
            bucket[tag_id] = bucket.get(tag_id, 0) + minutes

    days = []
    for offset in range(days_in_month):
        day = first + timedelta(days=offset)
        minutes_by_tag = per_day.get(day, {})
        days.append(
            {
                "date": day.isoformat(),
                "event_count": counts.get(day, 0),
                "total_minutes": sum(minutes_by_tag.values()),
                "minutes_by_tag": {str(k): v for k, v in sorted(minutes_by_tag.items())},
            }
        )

    return {"year": year, "month": month, "days": days}
```

An event is counted on every day it touches, so an overnight block appears on both.

- [ ] **Step 4: Create `backend/app/routers/calendar.py`**

```python
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.event import EventOut
from app.services import calendar as service

week_router = APIRouter(prefix="/api/weeks", tags=["weeks"])
month_router = APIRouter(prefix="/api/months", tags=["months"])

MONTH_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")


@week_router.get("/{any_day}")
async def get_week(any_day: date, session: AsyncSession = Depends(get_session)) -> dict:
    payload = await service.get_week(session, any_day)
    payload["events"] = [
        EventOut.model_validate(e).model_dump(mode="json") for e in payload["events"]
    ]
    return payload


@month_router.get("/{month_key}")
async def get_month(month_key: str, session: AsyncSession = Depends(get_session)) -> dict:
    match = MONTH_PATTERN.match(month_key)
    if match is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "expected YYYY-MM")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month must be 01-12")
    return await service.get_month(session, year, month)
```

- [ ] **Step 5: Register in `backend/app/main.py`**

```python
from app.routers import calendar as calendar_router

app.include_router(calendar_router.week_router)
app.include_router(calendar_router.month_router)
```

Register this **after** `templates_router.week_router` — both use the `/api/weeks` prefix but different paths (`GET /{any_day}` vs `POST /{any_day}/materialize`), so they coexist.

- [ ] **Step 6: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (59 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/
git commit -m "feat: add week and month calendar payloads with lazy materialization"
```

---

### Task 10: Report — append-only, snapshots the active rule

**Files:**
- Create: `backend/app/models/report.py`, `backend/app/schemas/report.py`, `backend/app/services/reports.py`, `backend/app/routers/reports.py`, `backend/tests/test_reports.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

**Interfaces:**
- Consumes: `services.evaluation.evaluate_period`, `services.rules.get_active_rule`
- Produces: `Report` model; `services.reports.run_report(session, year, month) -> Report`, `list_reports(session, month_key: str | None = None) -> list[Report]`, `get_report`, `delete_report`, and `NARRATIVE_PLACEHOLDER`

The LLM narrative arrives in Plan 3. This task stores a deterministic placeholder so the object, its append-only semantics, and the endpoint are all complete and testable now.

- [ ] **Step 1: Write the failing test — `backend/tests/test_reports.py`**

```python
RULE_BODY = {
    "name": "6:3:1 baseline",
    "tolerance": 0.2,
    "exclude_tag_ids": [],
    "groups": [
        {"key": "A", "label": "Work", "ratio": 6, "tag_ids": [1]},
        {"key": "B", "label": "Kids", "ratio": 3, "tag_ids": [2]},
        {"key": "C", "label": "Fitness", "ratio": 1, "tag_ids": [3]},
    ],
}


async def _setup(client):
    for name, color in (("Work", "#DA96A4"), ("Kids", "#BDBD9B"), ("Fitness", "#8FA8A2")):
        await client.post("/api/tags", json={"name": name, "color": color})
    await client.post("/api/rules", json=RULE_BODY)
    for tag_id, hours in ((1, 6), (2, 3), (3, 1)):
        await client.post(
            "/api/events",
            json={
                "task_name": f"tag{tag_id}",
                "start_at": "2026-08-03T00:00:00",
                "end_at": f"2026-08-03T{hours:02d}:00:00",
                "tag_ids": [tag_id],
            },
        )


async def test_run_report_snapshots_the_active_rule(client):
    await _setup(client)
    active_id = (await client.get("/api/rules/active")).json()["id"]

    report = await client.post("/api/reports/run", json={"month": "2026-08"})
    assert report.status_code == 201
    body = report.json()
    assert body["rule_id"] == active_id
    assert body["period_start"] == "2026-08-01"
    assert body["period_end"] == "2026-08-31"
    assert body["metrics"]["has_data"] is True


async def test_rerunning_appends_rather_than_overwrites(client):
    await _setup(client)
    first = (await client.post("/api/reports/run", json={"month": "2026-08"})).json()
    second = (await client.post("/api/reports/run", json={"month": "2026-08"})).json()
    assert first["id"] != second["id"]

    listed = (await client.get("/api/reports", params={"month": "2026-08"})).json()
    assert len(listed) == 2
    assert listed[0]["id"] == second["id"]  # newest first


async def test_changing_the_rule_leaves_old_reports_untouched(client):
    await _setup(client)
    original = (await client.post("/api/reports/run", json={"month": "2026-08"})).json()

    loosened = {**RULE_BODY, "name": "loosened", "tolerance": 0.5}
    await client.post("/api/rules", json=loosened)

    refetched = (await client.get(f"/api/reports/{original['id']}")).json()
    assert refetched == original


async def test_new_report_uses_the_now_current_rule(client):
    await _setup(client)
    await client.post("/api/reports/run", json={"month": "2026-08"})

    loosened = {**RULE_BODY, "name": "loosened", "tolerance": 0.5}
    new_rule_id = (await client.post("/api/rules", json=loosened)).json()["id"]

    latest = (await client.post("/api/reports/run", json={"month": "2026-08"})).json()
    assert latest["rule_id"] == new_rule_id


async def test_reports_have_no_patch_route(client):
    await _setup(client)
    report_id = (await client.post("/api/reports/run", json={"month": "2026-08"})).json()["id"]
    assert (await client.patch(f"/api/reports/{report_id}", json={})).status_code == 405


async def test_report_without_rule_returns_409(client):
    assert (await client.post("/api/reports/run", json={"month": "2026-08"})).status_code == 409


async def test_delete_report(client):
    await _setup(client)
    report_id = (await client.post("/api/reports/run", json={"month": "2026-08"})).json()["id"]
    assert (await client.delete(f"/api/reports/{report_id}")).status_code == 204
    assert (await client.get(f"/api/reports/{report_id}")).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_reports.py -v`
Expected: FAIL — `/api/reports/run` returns 404

- [ ] **Step 3: Create `backend/app/models/report.py`**

```python
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Report(Base):
    """Append-only. Never updated after insert — see the spec's rule-versioning section."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
```

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

```python
from app.models.event import Event, EventSource
from app.models.report import Report
from app.models.rule import Rule
from app.models.tag import Tag
from app.models.task import Priority, Task, TaskStatus
from app.models.template import Template, TemplateBlock

__all__ = [
    "Tag", "Task", "TaskStatus", "Priority", "Event", "EventSource",
    "Rule", "Template", "TemplateBlock", "Report",
]
```

- [ ] **Step 5: Create `backend/app/schemas/report.py`**

```python
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ReportRun(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    period_start: date
    period_end: date
    rule_id: int
    metrics: dict
    narrative: str
    created_at: datetime
```

- [ ] **Step 6: Create `backend/app/services/reports.py`**

```python
import calendar as calendar_lib
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Report
from app.services import evaluation as evaluation_service

NARRATIVE_PLACEHOLDER = "Narrative generation arrives with the agent layer."


def month_bounds(year: int, month: int) -> tuple[date, date, datetime, datetime]:
    """Inclusive display bounds plus the half-open datetime window used for querying."""
    first = date(year, month, 1)
    last = date(year, month, calendar_lib.monthrange(year, month)[1])
    start_dt = datetime.combine(first, datetime.min.time())
    end_dt = datetime.combine(last + timedelta(days=1), datetime.min.time())
    return first, last, start_dt, end_dt


async def run_report(session: AsyncSession, year: int, month: int) -> Report:
    """Always inserts. The active rule at this moment is frozen onto the row."""
    first, last, start_dt, end_dt = month_bounds(year, month)
    result, rule = await evaluation_service.evaluate_period(session, start_dt, end_dt)

    report = Report(
        period_start=first,
        period_end=last,
        rule_id=rule.id,
        metrics=result.to_dict(),
        narrative=NARRATIVE_PLACEHOLDER,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def list_reports(session: AsyncSession, month_key: str | None = None) -> list[Report]:
    stmt = select(Report).order_by(Report.created_at.desc(), Report.id.desc())
    if month_key is not None:
        year, month = int(month_key[:4]), int(month_key[5:7])
        first, _, _, _ = month_bounds(year, month)
        stmt = stmt.where(Report.period_start == first)
    return list((await session.scalars(stmt)).all())


async def get_report(session: AsyncSession, report_id: int) -> Report | None:
    return await session.get(Report, report_id)


async def delete_report(session: AsyncSession, report_id: int) -> bool:
    report = await session.get(Report, report_id)
    if report is None:
        return False
    await session.delete(report)
    await session.commit()
    return True
```

- [ ] **Step 7: Create `backend/app/routers/reports.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.report import ReportOut, ReportRun
from app.services import evaluation as evaluation_service
from app.services import reports as service

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=list[ReportOut])
async def list_reports(month: str | None = None, session: AsyncSession = Depends(get_session)):
    return await service.list_reports(session, month)


@router.post("/run", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def run_report(body: ReportRun, session: AsyncSession = Depends(get_session)):
    year, month = int(body.month[:4]), int(body.month[5:7])
    if not 1 <= month <= 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month must be 01-12")
    try:
        return await service.run_report(session, year, month)
    except evaluation_service.NoActiveRule:
        raise HTTPException(status.HTTP_409_CONFLICT, "no active rule — create one first")


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: int, session: AsyncSession = Depends(get_session)):
    report = await service.get_report(session, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return report


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: int, session: AsyncSession = Depends(get_session)):
    if not await service.delete_report(session, report_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

There is deliberately **no PATCH route**. Do not add one.

- [ ] **Step 8: Register in `backend/app/main.py`**

```python
from app.routers import reports as reports_router

app.include_router(reports_router.router)
```

- [ ] **Step 9: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (66 tests)

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat: add append-only Report that snapshots the active rule"
```

---

### Task 11: Reminder model, service, and REST

**Files:**
- Create: `backend/app/models/reminder.py`, `backend/app/schemas/reminder.py`, `backend/app/services/reminders.py`, `backend/app/routers/reminders.py`, `backend/tests/test_reminders.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/main.py`

**Interfaces:**
- Consumes: `Task`
- Produces: `Reminder` model with `Channel`; `services.reminders.list_reminders(session, *, task_id=None, pending_only=False) -> list[Reminder]`, `create_reminder`, `update_reminder`, `delete_reminder`, `list_due(session, now: datetime) -> list[Reminder]`, `mark_sent(session, reminder_id, when: datetime) -> Reminder | None`

- [ ] **Step 1: Write the failing test — `backend/tests/test_reminders.py`**

```python
from datetime import datetime

from app.services import reminders as service


async def _task(client, name="Renew passport"):
    return (
        await client.post("/api/tasks", json={"name": name, "tag_ids": [], "is_floating": True})
    ).json()["id"]


async def test_create_reminder(client):
    task_id = await _task(client)
    created = await client.post(
        "/api/reminders",
        json={"task_id": task_id, "remind_at": "2026-08-10T09:00:00", "channel": "both"},
    )
    assert created.status_code == 201
    assert created.json()["sent_at"] is None
    assert created.json()["channel"] == "both"


async def test_reminder_for_missing_task_returns_404(client):
    bad = await client.post(
        "/api/reminders", json={"task_id": 999, "remind_at": "2026-08-10T09:00:00"}
    )
    assert bad.status_code == 404


async def test_list_due_selects_only_unsent_past_reminders(client, session):
    task_id = await _task(client)
    for when in ("2026-08-01T09:00:00", "2026-08-20T09:00:00"):
        await client.post("/api/reminders", json={"task_id": task_id, "remind_at": when})

    due = await service.list_due(session, datetime(2026, 8, 10, 12, 0))
    assert len(due) == 1
    assert due[0].remind_at == datetime(2026, 8, 1, 9, 0)


async def test_mark_sent_is_not_repeated(client, session):
    task_id = await _task(client)
    reminder_id = (
        await client.post(
            "/api/reminders", json={"task_id": task_id, "remind_at": "2026-08-01T09:00:00"}
        )
    ).json()["id"]

    now = datetime(2026, 8, 10, 12, 0)
    assert len(await service.list_due(session, now)) == 1
    await service.mark_sent(session, reminder_id, now)
    assert await service.list_due(session, now) == []


async def test_dismiss_reminder(client):
    task_id = await _task(client)
    reminder_id = (
        await client.post(
            "/api/reminders", json={"task_id": task_id, "remind_at": "2026-08-10T09:00:00"}
        )
    ).json()["id"]
    patched = await client.patch(
        f"/api/reminders/{reminder_id}", json={"dismissed_at": "2026-08-10T09:05:00"}
    )
    assert patched.json()["dismissed_at"] == "2026-08-10T09:05:00"


async def test_dismissed_reminders_are_not_due(client, session):
    task_id = await _task(client)
    reminder_id = (
        await client.post(
            "/api/reminders", json={"task_id": task_id, "remind_at": "2026-08-01T09:00:00"}
        )
    ).json()["id"]
    await client.patch(
        f"/api/reminders/{reminder_id}", json={"dismissed_at": "2026-08-02T09:00:00"}
    )
    assert await service.list_due(session, datetime(2026, 8, 10, 12, 0)) == []


async def test_delete_reminder(client):
    task_id = await _task(client)
    reminder_id = (
        await client.post(
            "/api/reminders", json={"task_id": task_id, "remind_at": "2026-08-10T09:00:00"}
        )
    ).json()["id"]
    assert (await client.delete(f"/api/reminders/{reminder_id}")).status_code == 204
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_reminders.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.reminders`

- [ ] **Step 3: Create `backend/app/models/reminder.py`**

```python
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Channel(StrEnum):
    INAPP = "inapp"
    LARK = "lark"
    BOTH = "both"


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    remind_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), default=Channel.INAPP, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 4: Update `backend/app/models/__init__.py`**

```python
from app.models.event import Event, EventSource
from app.models.reminder import Channel, Reminder
from app.models.report import Report
from app.models.rule import Rule
from app.models.tag import Tag
from app.models.task import Priority, Task, TaskStatus
from app.models.template import Template, TemplateBlock

__all__ = [
    "Tag", "Task", "TaskStatus", "Priority", "Event", "EventSource",
    "Rule", "Template", "TemplateBlock", "Report", "Reminder", "Channel",
]
```

- [ ] **Step 5: Create `backend/app/schemas/reminder.py`**

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.reminder import Channel


class ReminderCreate(BaseModel):
    task_id: int
    remind_at: datetime
    channel: Channel = Channel.INAPP


class ReminderUpdate(BaseModel):
    remind_at: datetime | None = None
    channel: Channel | None = None
    dismissed_at: datetime | None = None


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    remind_at: datetime
    channel: Channel
    sent_at: datetime | None
    dismissed_at: datetime | None
```

- [ ] **Step 6: Create `backend/app/services/reminders.py`**

```python
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder, Task
from app.schemas.reminder import ReminderCreate, ReminderUpdate


class TaskNotFound(Exception):
    """Raised when a reminder references a task that does not exist."""


async def list_reminders(
    session: AsyncSession, *, task_id: int | None = None, pending_only: bool = False
) -> list[Reminder]:
    stmt = select(Reminder).order_by(Reminder.remind_at)
    if task_id is not None:
        stmt = stmt.where(Reminder.task_id == task_id)
    if pending_only:
        stmt = stmt.where(Reminder.sent_at.is_(None), Reminder.dismissed_at.is_(None))
    return list((await session.scalars(stmt)).all())


async def get_reminder(session: AsyncSession, reminder_id: int) -> Reminder | None:
    return await session.get(Reminder, reminder_id)


async def create_reminder(session: AsyncSession, data: ReminderCreate) -> Reminder:
    if await session.get(Task, data.task_id) is None:
        raise TaskNotFound(data.task_id)
    reminder = Reminder(**data.model_dump())
    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)
    return reminder


async def update_reminder(
    session: AsyncSession, reminder_id: int, data: ReminderUpdate
) -> Reminder | None:
    reminder = await session.get(Reminder, reminder_id)
    if reminder is None:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(reminder, key, value)
    await session.commit()
    await session.refresh(reminder)
    return reminder


async def delete_reminder(session: AsyncSession, reminder_id: int) -> bool:
    reminder = await session.get(Reminder, reminder_id)
    if reminder is None:
        return False
    await session.delete(reminder)
    await session.commit()
    return True


async def list_due(session: AsyncSession, now: datetime) -> list[Reminder]:
    stmt = (
        select(Reminder)
        .where(
            Reminder.remind_at <= now,
            Reminder.sent_at.is_(None),
            Reminder.dismissed_at.is_(None),
        )
        .order_by(Reminder.remind_at)
    )
    return list((await session.scalars(stmt)).all())


async def mark_sent(session: AsyncSession, reminder_id: int, when: datetime) -> Reminder | None:
    reminder = await session.get(Reminder, reminder_id)
    if reminder is None:
        return None
    reminder.sent_at = when
    await session.commit()
    await session.refresh(reminder)
    return reminder
```

- [ ] **Step 7: Create `backend/app/routers/reminders.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.reminder import ReminderCreate, ReminderOut, ReminderUpdate
from app.services import reminders as service

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


@router.get("", response_model=list[ReminderOut])
async def list_reminders(
    task_id: int | None = None,
    pending_only: bool = False,
    session: AsyncSession = Depends(get_session),
):
    return await service.list_reminders(session, task_id=task_id, pending_only=pending_only)


@router.post("", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
async def create_reminder(data: ReminderCreate, session: AsyncSession = Depends(get_session)):
    try:
        return await service.create_reminder(session, data)
    except service.TaskNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")


@router.get("/{reminder_id}", response_model=ReminderOut)
async def get_reminder(reminder_id: int, session: AsyncSession = Depends(get_session)):
    reminder = await service.get_reminder(session, reminder_id)
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    return reminder


@router.patch("/{reminder_id}", response_model=ReminderOut)
async def update_reminder(
    reminder_id: int, data: ReminderUpdate, session: AsyncSession = Depends(get_session)
):
    reminder = await service.update_reminder(session, reminder_id, data)
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    return reminder


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(reminder_id: int, session: AsyncSession = Depends(get_session)):
    if not await service.delete_reminder(session, reminder_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 8: Register in `backend/app/main.py`**

```python
from app.routers import reminders as reminders_router

app.include_router(reminders_router.router)
```

- [ ] **Step 9: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (73 tests)

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat: add Reminder model, service, and REST endpoints"
```

---

### Task 12: Seed data — tags, the 6:3:1 rule, the default template

**Files:**
- Create: `backend/app/services/seed.py`, `backend/app/routers/seed.py`, `backend/tests/test_seed.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `services.tags.create_tag`, `services.rules.create_rule_version`, `services.templates.create_template` / `create_block`
- Produces: `services.seed.seed_all(session) -> dict[str, int]` — idempotent; returns counts created

The template mirrors the source image: 周一–周五 / 周六 / 周日.

- [ ] **Step 1: Write the failing test — `backend/tests/test_seed.py`**

```python
async def test_seed_creates_tags_rule_and_template(client):
    result = await client.post("/api/seed")
    assert result.status_code == 200
    body = result.json()
    assert body["tags"] == 8
    assert body["rules"] == 1
    assert body["templates"] == 1

    tags = (await client.get("/api/tags")).json()
    assert [t["name"] for t in tags] == [
        "Rest", "Work", "Study", "Commute",
        "Kids/Family", "Chores/Prep", "Fitness", "Personal",
    ]


async def test_seeded_rule_is_631_with_rest_and_personal_excluded(client):
    await client.post("/api/seed")
    rule = (await client.get("/api/rules/active")).json()
    assert rule["tolerance"] == 0.2
    assert [g["ratio"] for g in rule["groups"]] == [6, 3, 1]

    tags = {t["name"]: t["id"] for t in (await client.get("/api/tags")).json()}
    assert set(rule["exclude_tag_ids"]) == {tags["Rest"], tags["Personal"]}
    assert set(rule["groups"][0]["tag_ids"]) == {tags["Work"], tags["Study"], tags["Commute"]}
    assert set(rule["groups"][2]["tag_ids"]) == {tags["Fitness"]}


async def test_seed_is_idempotent(client):
    await client.post("/api/seed")
    second = (await client.post("/api/seed")).json()
    assert second == {"tags": 0, "rules": 0, "templates": 0}
    assert len((await client.get("/api/tags")).json()) == 8
    assert len((await client.get("/api/rules")).json()) == 1


async def test_seeded_template_matches_the_source_grid(client):
    await client.post("/api/seed")
    template = (await client.get("/api/templates/active")).json()
    blocks = template["blocks"]

    weekday_work = next(
        b for b in blocks if b["task_name"] == "Work" and b["days"] == [1, 2, 3, 4, 5]
    )
    assert weekday_work["start_time"] == "09:30:00"
    assert weekday_work["end_time"] == "16:30:00"

    rest = next(b for b in blocks if b["task_name"] == "Rest")
    assert rest["days"] == [1, 2, 3, 4, 5, 6, 7]
    assert rest["start_time"] == "23:00:00"
    assert rest["end_time"] == "07:00:00"

    assert any(b["task_name"] == "Baby food prep" and b["days"] == [7] for b in blocks)
    assert any(b["task_name"] == "Personal time" and b["days"] == [6] for b in blocks)


async def test_seeded_week_materializes_and_matches_631_shape(client):
    """Seed, materialize a week, and confirm the analytics engine reads it as the spec predicts."""
    await client.post("/api/seed")
    await client.post("/api/weeks/2026-08-03/materialize")

    result = await client.post(
        "/api/analytics/evaluate",
        json={"period_start": "2026-08-03T00:00:00", "period_end": "2026-08-08T00:00:00"},
    )
    verdicts = {g["key"]: g["verdict"] for g in result.json()["metrics"]["groups"]}
    assert verdicts["A"] == "pass"
    assert verdicts["B"] == "pass"
    assert verdicts["C"] == "under"
```

The last test is the end-to-end proof that seed, template, materialization, and analytics agree — and it locks in the spec's worked example.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_seed.py -v`
Expected: FAIL — `/api/seed` returns 404

- [ ] **Step 3: Create `backend/app/services/seed.py`**

```python
"""Seeds the tag set, the 6:3:1 rule, and the default weekly template.

Idempotent: running twice creates nothing the second time.
"""

from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Rule, Tag, Template
from app.schemas.rule import RuleCreate, RuleGroup
from app.schemas.tag import TagCreate
from app.schemas.template import TemplateBlockCreate, TemplateCreate
from app.services import rules as rule_service
from app.services import tags as tag_service
from app.services import templates as template_service

SEED_TAGS: list[tuple[str, str, str]] = [
    ("Rest", "#DEDECF", "moon"),
    ("Work", "#DA96A4", "briefcase"),
    ("Study", "#C9A88F", "book"),
    ("Commute", "#BDBD9B", "bus"),
    ("Kids/Family", "#8FA8A2", "family"),
    ("Chores/Prep", "#E7C8C8", "home"),
    ("Fitness", "#DA96A4", "dumbbell"),
    ("Personal", "#C9A88F", "user"),
]

WEEKDAYS = [1, 2, 3, 4, 5]
SATURDAY = [6]
SUNDAY = [7]
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]

# (days, start, end, task name, tag name)
SEED_BLOCKS: list[tuple[list[int], time, time, str, str]] = [
    (ALL_DAYS, time(23, 0), time(7, 0), "Rest", "Rest"),
    (WEEKDAYS, time(7, 0), time(8, 0), "Morning routine", "Chores/Prep"),
    (WEEKDAYS, time(8, 0), time(9, 0), "Workout", "Fitness"),
    (WEEKDAYS, time(9, 0), time(9, 30), "Commute in", "Commute"),
    (WEEKDAYS, time(9, 30), time(16, 30), "Work", "Work"),
    (WEEKDAYS, time(16, 30), time(17, 30), "Commute home", "Commute"),
    (WEEKDAYS, time(17, 30), time(21, 30), "Dinner & kids", "Kids/Family"),
    (WEEKDAYS, time(21, 30), time(23, 0), "Study / overtime", "Study"),
    (SATURDAY, time(7, 0), time(9, 0), "Morning walk with kid", "Kids/Family"),
    (SATURDAY, time(9, 0), time(11, 30), "Family outing", "Kids/Family"),
    (SATURDAY, time(11, 30), time(13, 30), "Lunch & nap", "Kids/Family"),
    (SATURDAY, time(13, 30), time(16, 30), "Personal time", "Personal"),
    (SATURDAY, time(19, 30), time(21, 30), "Family time", "Kids/Family"),
    (SUNDAY, time(7, 0), time(9, 0), "Morning walk with kid", "Kids/Family"),
    (SUNDAY, time(9, 0), time(11, 30), "Family outing", "Kids/Family"),
    (SUNDAY, time(11, 30), time(13, 30), "Lunch & nap", "Kids/Family"),
    (SUNDAY, time(13, 30), time(16, 30), "Baby food prep", "Chores/Prep"),
    (SUNDAY, time(16, 30), time(18, 0), "Rest", "Rest"),
    (SUNDAY, time(19, 30), time(21, 0), "Prep for Monday", "Chores/Prep"),
]


async def _any(session: AsyncSession, model) -> bool:
    return (await session.scalars(select(model.id).limit(1))).first() is not None


async def seed_all(session: AsyncSession) -> dict[str, int]:
    created = {"tags": 0, "rules": 0, "templates": 0}

    if not await _any(session, Tag):
        for index, (name, color, icon) in enumerate(SEED_TAGS):
            await tag_service.create_tag(
                session, TagCreate(name=name, color=color, icon=icon, sort_order=index)
            )
            created["tags"] += 1

    by_name = {t.name: t.id for t in await tag_service.list_tags(session)}

    if not await _any(session, Rule):
        await rule_service.create_rule_version(
            session,
            RuleCreate(
                name="6:3:1 baseline",
                tolerance=0.2,
                exclude_tag_ids=[by_name["Rest"], by_name["Personal"]],
                note="Initial commitment.",
                groups=[
                    RuleGroup(
                        key="A",
                        label="Work · Study · Commute",
                        ratio=6,
                        tag_ids=[by_name["Work"], by_name["Study"], by_name["Commute"]],
                    ),
                    RuleGroup(
                        key="B",
                        label="Kids · Chores",
                        ratio=3,
                        tag_ids=[by_name["Kids/Family"], by_name["Chores/Prep"]],
                    ),
                    RuleGroup(key="C", label="Fitness", ratio=1, tag_ids=[by_name["Fitness"]]),
                ],
            ),
        )
        created["rules"] += 1

    if not await _any(session, Template):
        template = await template_service.create_template(
            session, TemplateCreate(name="Default week")
        )
        for order, (days, start, end, task_name, tag_name) in enumerate(SEED_BLOCKS):
            await template_service.create_block(
                session,
                template.id,
                TemplateBlockCreate(
                    days=days,
                    start_time=start,
                    end_time=end,
                    task_name=task_name,
                    tag_ids=[by_name[tag_name]],
                    sort_order=order,
                ),
            )
        created["templates"] += 1

    return created
```

- [ ] **Step 4: Create `backend/app/routers/seed.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services import seed as service

router = APIRouter(prefix="/api/seed", tags=["seed"])


@router.post("")
async def seed(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    return await service.seed_all(session)
```

- [ ] **Step 5: Register in `backend/app/main.py`**

```python
from app.routers import seed as seed_router

app.include_router(seed_router.router)
```

- [ ] **Step 6: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (78 tests)

If `test_seeded_week_materializes_and_matches_631_shape` reports A/B verdicts other than `pass`, the seed block times are wrong — recheck them against the table in Step 3 before changing the analytics engine. The engine is proven by Task 6's tests.

- [ ] **Step 7: Commit**

```bash
git add backend/
git commit -m "feat: seed tags, the 6:3:1 rule, and the default weekly template"
```

---

### Task 13: Scheduler — Sunday week-roll and reminder sweep

**Files:**
- Create: `backend/app/scheduler/__init__.py`, `backend/app/scheduler/jobs.py`, `backend/tests/test_scheduler.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `async_session_factory`, `services.templates.materialize_week`, `services.reminders.list_due` / `mark_sent`
- Produces: `scheduler.jobs.roll_next_week(session, today: date) -> dict`, `sweep_reminders(session, now: datetime) -> list[int]`, `start_scheduler()`, `shutdown_scheduler()`

Both jobs take an explicit `session` and clock value so they are testable without patching time or spinning up APScheduler.

- [ ] **Step 1: Write the failing test — `backend/tests/test_scheduler.py`**

```python
from datetime import date, datetime, timedelta

from app.scheduler.jobs import roll_next_week, sweep_reminders

WEEKDAY_BLOCK = {
    "days": [1, 2, 3, 4, 5],
    "start_time": "09:30:00",
    "end_time": "16:30:00",
    "task_name": "Work",
    "tag_ids": [],
}


async def _template(client):
    template_id = (await client.post("/api/templates", json={"name": "Default"})).json()["id"]
    await client.post(f"/api/templates/{template_id}/blocks", json=WEEKDAY_BLOCK)


async def test_roll_next_week_targets_the_following_monday(client, session):
    await _template(client)
    sunday = date(2026, 8, 2)
    result = await roll_next_week(session, sunday)
    assert result["week_start"] == "2026-08-03"
    assert result["created"] == 5


async def test_roll_next_week_is_idempotent(client, session):
    await _template(client)
    sunday = date(2026, 8, 2)
    assert (await roll_next_week(session, sunday))["created"] == 5
    assert (await roll_next_week(session, sunday))["created"] == 0


async def test_roll_next_week_without_template_reports_zero(client, session):
    result = await roll_next_week(session, date(2026, 8, 2))
    assert result["created"] == 0
    assert result["skipped_reason"] == "no active template"


async def test_sweep_marks_due_reminders_sent(client, session):
    task_id = (
        await client.post("/api/tasks", json={"name": "Renew passport", "tag_ids": []})
    ).json()["id"]
    reminder_id = (
        await client.post(
            "/api/reminders", json={"task_id": task_id, "remind_at": "2026-08-01T09:00:00"}
        )
    ).json()["id"]

    now = datetime(2026, 8, 10, 12, 0)
    assert await sweep_reminders(session, now) == [reminder_id]
    assert await sweep_reminders(session, now) == []


async def test_sweep_ignores_future_reminders(client, session):
    task_id = (await client.post("/api/tasks", json={"name": "Later", "tag_ids": []})).json()["id"]
    future = (datetime.now() + timedelta(days=30)).isoformat(timespec="seconds")
    await client.post("/api/reminders", json={"task_id": task_id, "remind_at": future})
    assert await sweep_reminders(session, datetime.now()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: app.scheduler.jobs`

- [ ] **Step 3: Create `backend/app/scheduler/jobs.py`**

```python
"""Background jobs. Each takes an explicit session and clock value so it is
directly testable without patching time or starting APScheduler.
"""

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.services import reminders as reminder_service
from app.services import templates as template_service

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def roll_next_week(session: AsyncSession, today: date) -> dict:
    """Materialize the week following `today`. Idempotent — safe to run repeatedly."""
    next_monday = today + timedelta(days=8 - today.isoweekday())
    try:
        monday, created, skipped = await template_service.materialize_week(session, next_monday)
    except template_service.NoActiveTemplate:
        logger.warning("week roll skipped: no active template")
        return {"week_start": None, "created": 0, "skipped_reason": "no active template"}
    return {
        "week_start": monday.isoformat(),
        "created": len(created),
        "skipped_days": [d.isoformat() for d in skipped],
    }


async def sweep_reminders(session: AsyncSession, now: datetime) -> list[int]:
    """Mark every due reminder as sent. Returns the ids handled.

    Lark delivery is wired in during Plan 3; marking sent here already makes the
    sweep exactly-once.
    """
    due = await reminder_service.list_due(session, now)
    handled: list[int] = []
    for reminder in due:
        await reminder_service.mark_sent(session, reminder.id, now)
        handled.append(reminder.id)
    if handled:
        logger.info("dispatched %d reminder(s)", len(handled))
    return handled


async def _run_week_roll() -> None:
    async with async_session_factory() as session:
        await roll_next_week(session, date.today())


async def _run_reminder_sweep() -> None:
    async with async_session_factory() as session:
        await sweep_reminders(session, datetime.now())


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.enable_scheduler:
        logger.info("scheduler disabled by config")
        return None
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_week_roll,
        CronTrigger(day_of_week="sun", hour=settings.week_roll_hour, minute=0),
        id="week_roll",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_reminder_sweep,
        CronTrigger(minute="*/15"),
        id="reminder_sweep",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("scheduler started")
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
```

Leave `backend/app/scheduler/__init__.py` empty.

- [ ] **Step 4: Wire the lifespan into `backend/app/main.py`**

Replace the `app = FastAPI(...)` line with:

```python
from contextlib import asynccontextmanager

from app.database import Base, engine
from app.scheduler.jobs import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Avery", version="0.1.0", lifespan=lifespan)
```

`import app.models` must already have happened for `create_all` to see the tables — it does, because every router imports its models transitively. Add an explicit `import app.models  # noqa: F401` at the top of `main.py` to make that dependency visible rather than accidental.

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/bin/pytest tests/ -v`
Expected: PASS (83 tests)

- [ ] **Step 6: Verify the server actually boots**

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000
```

Then in another shell:

```bash
curl -s -X POST localhost:8000/api/seed && curl -s localhost:8000/api/rules/active
```

Expected: seed counts, then the 6:3:1 rule. Confirm `data/avery.db` now exists. Stop the server.

- [ ] **Step 7: Commit**

```bash
git add backend/
git commit -m "feat: add Sunday week-roll and reminder sweep scheduler jobs"
```

---

### Task 14: Alembic baseline and README

**Files:**
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/alembic/versions/` (initial revision), `backend/README.md`

**Interfaces:**
- Consumes: `Base.metadata`, `settings.resolved_database_url()`
- Produces: a reproducible schema migration; `create_all` in the lifespan remains as a dev convenience

- [ ] **Step 1: Initialize Alembic**

```bash
cd backend && .venv/bin/alembic init -t async alembic
```

- [ ] **Step 2: Point `backend/alembic/env.py` at the app metadata**

Replace the `target_metadata = None` line and add above it:

```python
import app.models  # noqa: F401
from app.config import settings
from app.database import Base

config.set_main_option("sqlalchemy.url", settings.resolved_database_url())
target_metadata = Base.metadata
```

- [ ] **Step 3: Generate and apply the baseline revision**

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "baseline schema" && .venv/bin/alembic upgrade head
```

- [ ] **Step 4: Verify every table exists**

```bash
cd backend && .venv/bin/python -c "
import sqlite3, pathlib
db = pathlib.Path('../data/avery.db')
names = {r[0] for r in sqlite3.connect(db).execute(
    \"select name from sqlite_master where type='table'\")}
expected = {'tags','tasks','events','rules','templates','template_blocks','reports','reminders'}
missing = expected - names
print('MISSING:', missing) if missing else print('all tables present')
"
```

Expected: `all tables present`

- [ ] **Step 5: Write `backend/README.md`**

````markdown
# Avery backend

FastAPI + async SQLAlchemy + SQLite. Single user, no auth.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

## Run

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

## First run

```bash
curl -X POST localhost:8000/api/seed
```

Creates the eight tags, the 6:3:1 rule, and the default weekly template.

## Test

```bash
.venv/bin/pytest -v
```

## Migrations

```bash
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head
```

## Layout

- `app/services/` — all business logic. Routers and (later) agent tools are thin
  adapters over it, so the REST API and natural-language paths cannot diverge.
- `app/services/analytics.py` — pure: no I/O, no ORM imports. The rule math lives
  here and is covered exhaustively in `tests/test_analytics.py`.
- Rules are append-only versions; reports are append-only and snapshot the rule
  active at generation time.
````

- [ ] **Step 6: Run the full suite one last time**

Run: `cd backend && .venv/bin/pytest -v`
Expected: PASS (83 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/ ../data/.gitkeep
git commit -m "chore: add Alembic baseline migration and backend README"
```

---

## Self-Review

**Spec coverage**

| Spec section | Covered by |
|---|---|
| §3 Architecture / layering rule | Tasks 1–14; enforced by services-only logic in every task |
| §4 Tag | Task 2 |
| §4 Task | Task 3 |
| §4 Event (tags copied, task_id required) | Task 4 |
| §4 Template / TemplateBlock (`days` array) | Task 8 |
| §4 Rule (versioned, never mutated) | Task 5 |
| §4 Report (append-only, rule snapshot) | Task 10 |
| §4 Reminder | Task 11 |
| §4 AgentMessage | **Plan 3** — the agent layer owns it |
| §5 Rule math, all 7 edge cases | Task 6 |
| §5 Worked example (C fails under) | Task 6 + end-to-end in Task 12 |
| §6 Sunday roll, lazy net, past weeks safe, idempotent | Tasks 8, 9, 13 |
| §7 Week/Month/Task payloads | Task 9 (data); views are **Plan 2** |
| §8 Agent | **Plan 3** |
| §9 Lark notifications | **Plan 3** (Task 13 leaves the sweep hook in place) |
| §10 API surface | Tasks 2–12 |
| §11 Theme | **Plan 2** |
| §12 Testing | Every task |
| §13 Build order steps 1–5 | This plan; steps 6–11 are Plans 2 and 3 |

Deliberately deferred, with the seam already built: report narrative (Task 10 stores a
named placeholder), Lark delivery (Task 13's sweep already marks sent exactly-once).

**Placeholder scan:** No TBD/TODO. Every code step contains runnable code. No step says
"similar to Task N". `NARRATIVE_PLACEHOLDER` is a deliberate, named, tested constant, not
an unfinished instruction.

**Type consistency:** `EventSlice`, `RuleSpec`, and `GroupSpec` are defined in Tasks 5–6
and used unchanged in Tasks 7, 9, 10. `week_bounds` is defined in Task 8 and consumed in
Tasks 9 and 13. `find_or_create_by_name` is defined in Task 3 and consumed in Tasks 4 and
8. `to_slice` is defined in Task 7 and reused in Task 9. `materialize_week` returns
`tuple[date, list[Event], list[date]]` in Task 8 and is unpacked that way in Tasks 9
and 13.
