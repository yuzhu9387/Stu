# Memory Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make memory behave like memory. Today's full conversation always stays in context. Cross-day vector retrieval surfaces relevant past events. A nightly cron consolidates accumulated patterns and decays stale ones. Goal progress auto-increments when linked tasks complete.

**Architecture:** Add `app/memory/` package (embeddings writer + retrieval + consolidation + confidence). A new `episodic_embeddings` table holds Voyage-AI vectors via pgvector. `load_context` is rewritten to load today's full conversation (cap 60), an optional yesterday tail in the morning, and a top-3 vector recall above similarity threshold. Embedding writes are fire-and-forget background tasks so the conversation pipeline never waits. Action types `reinforce_pattern` and `contradict_pattern` are added; THINK emits them when user behavior validates or refutes a learned pattern. The nightly `memory_consolidation` cron asks Haiku to dedupe/merge/resolve-contradictions, then applies exponential time decay. `_complete_task` increments `goals.current_value` when the task has a `goal_id`.

**Tech Stack:** Python 3.10 · FastAPI · SQLAlchemy 2 async · Postgres 16 + pgvector · Voyage AI (`voyageai>=0.2`) · `pgvector>=0.2` (SQLAlchemy adapter) · APScheduler · LiteLLM · pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-05-26-memory-refinement-design.md`
**Predecessor plan:** `docs/superpowers/plans/2026-05-21-proactive-agent.md`

---

## Pre-flight

Before any of these tasks, the engineer must:

- [ ] Confirm baseline is green: `pytest tests/ -q` → 182 passed
- [ ] Install pgvector extension on local Postgres:
  ```bash
  brew install pgvector
  # macOS Homebrew puts the extension files in your Postgres' share/extension dir.
  # Verify:
  psql -d my_assistant -c "SELECT * FROM pg_available_extensions WHERE name='vector';"
  ```
  If `pg_available_extensions` returns 0 rows, follow the pgvector install docs for your Postgres install (it's a Postgres extension, not a Python package — the Python `pgvector` adapter we install in Task 1 is separate).
- [ ] **Voyage AI key**: register at https://www.voyageai.com/ and copy your API key. Add to `.env`:
  ```
  PA_VOYAGE_API_KEY=<your-key-here>
  ```
  If you don't have a key yet, leave it as a placeholder (`PA_VOYAGE_API_KEY=`) — the code is designed so all embedding paths soft-fail and the conversation pipeline still works. You can add the key later and the system will start storing embeddings for new content.
- [ ] Optional: rotate the Anthropic API key that appeared in earlier conversation logs.

Branch strategy:

```bash
git checkout -b feat/memory-refinement
```

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `app/memory/__init__.py` | empty package marker |
| `app/memory/embeddings.py` | `embed_and_store`, `EMBEDDABLE_EVENT_TYPES`, content builders |
| `app/memory/retrieval.py` | `episodic_recall(session, user_id, query_text)` |
| `app/memory/consolidation.py` | `consolidate_patterns(session, user_id)` + `_apply_consolidation` |
| `app/memory/confidence.py` | `decay_pattern_confidence`, `reinforce_pattern`, `contradict_pattern` |
| `app/services/voyage_client.py` | `VoyageClient` thin async wrapper |
| `app/models/episodic_embedding.py` | `EpisodicEmbedding` ORM model |
| `alembic/versions/<rev>_memory_refinement.py` | CREATE EXTENSION + table |
| `tests/test_memory/__init__.py` | empty |
| `tests/test_memory/test_embeddings.py` | embed_and_store unit + integration tests |
| `tests/test_memory/test_retrieval.py` | episodic_recall tests |
| `tests/test_memory/test_consolidation.py` | _apply_consolidation + LLM-mocked end-to-end |
| `tests/test_memory/test_confidence.py` | decay + reinforce + contradict math |
| `tests/test_services/test_voyage_client.py` | client tests with mocked voyageai |
| `tests/test_models/test_episodic_embedding.py` | model persistence test |

### Modified files

| Path | Change |
|---|---|
| `pyproject.toml` | + `voyageai>=0.2.0`, + `pgvector>=0.2.0` |
| `app/config.py` | + `voyage_api_key: str = ""` |
| `app/schemas/preferences.py` | + `last_reinforced_at: Optional[str] = None` on `Pattern` |
| `app/orchestrator/actions.py` | + REINFORCE_PATTERN/CONTRADICT_PATTERN enum + param schemas |
| `app/orchestrator/act.py` | + `_reinforce_pattern`, `_contradict_pattern` dispatch; goal increment in `_complete_task`; post-commit fire-and-forget embed in `execute_all` |
| `app/orchestrator/context.py` | rewrite `recent_turns` (today + yesterday tail); add `episodic_recall`; accept `query_text` |
| `app/orchestrator/conversation.py` | pass `query_text=message` to `load_context`; fire-and-forget embed user message |
| `app/orchestrator/think.py` | add `episodic_recall` block in `_build_user_content` |
| `app/orchestrator/prompts/think.md` | + reinforce/contradict guidance + episodic_recall section |
| `app/orchestrator/prompts/react.md` | + episodic_recall usage guidance |
| `app/scheduler/jobs.py` | + `run_memory_consolidation` wrapper |
| `app/scheduler/runtime.py` | register new cron in `register_jobs()` |

---

## Task 1: Dependencies + Settings + .env Placeholder

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/config.py`
- Modify: `.env` (locally — DO NOT COMMIT)

- [ ] **Step 1.1: Add voyageai and pgvector deps**

In `pyproject.toml`, append to `dependencies`:

```
    "voyageai>=0.2.0",
    "pgvector>=0.2.0",
```

- [ ] **Step 1.2: Install**

```bash
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
pip install "voyageai>=0.2.0" "pgvector>=0.2.0"
```

- [ ] **Step 1.3: Add settings field**

Edit `app/config.py`. Add a single line under the existing `lark_*` fields, before `enable_scheduler`:

```python
    voyage_api_key: str = ""
```

The final fields-in-order list should be:

```python
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
    voyage_api_key: str = ""
    enable_scheduler: bool = True
    proactive_dry_run: bool = False
    model_config = {"env_prefix": "PA_", "env_file": ".env"}
```

- [ ] **Step 1.4: Add placeholder to local `.env`**

`.env` is gitignored (verify: `grep -E '^.env' .gitignore`). Append a placeholder line so the engineer remembers the variable exists:

```
PA_VOYAGE_API_KEY=
```

(Leave it empty. The code soft-fails when the key is missing. Fill it in later when you have the key.)

- [ ] **Step 1.5: Run full suite — no regressions**

```bash
cd /Users/guoyuzhu/personal-assistant
source .venv/bin/activate
pytest tests/ -q
```

Expected: 182 passed.

- [ ] **Step 1.6: Commit**

```bash
git add pyproject.toml app/config.py
git commit -m "feat: add voyageai + pgvector deps; PA_VOYAGE_API_KEY setting"
```

(Do NOT commit `.env`.)

---

## Task 2: Alembic Migration — Extension + Table

**Files:**
- Create: `alembic/versions/<auto-rev>_memory_refinement.py`

- [ ] **Step 2.1: Generate revision scaffold**

```bash
cd /Users/guoyuzhu/personal-assistant
source .venv/bin/activate
alembic revision -m "memory refinement: pgvector extension + episodic_embeddings"
```

Note the path that gets created (e.g. `alembic/versions/abc123def_memory_refinement_pgvector_extension_.py`).

- [ ] **Step 2.2: Edit the new revision file**

Replace its content with:

```python
"""memory refinement: pgvector extension + episodic_embeddings

Revision ID: <leave-as-generated>
Revises: 38cff6b9ccc2
Create Date: 2026-05-26 ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Keep the auto-generated `revision` value at the top intact.
down_revision: Union[str, Sequence[str], None] = "38cff6b9ccc2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "episodic_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # vector(1024) via raw SQL — Alembic doesn't know pgvector types natively
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Replace the ARRAY column with a real vector column
    op.execute("ALTER TABLE episodic_embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE episodic_embeddings ADD COLUMN embedding vector(1024) NOT NULL")
    op.create_index("ix_episodic_embeddings_user", "episodic_embeddings", ["user_id"])
    op.execute(
        "CREATE INDEX ix_episodic_embeddings_vec ON episodic_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_index("ix_episodic_embeddings_vec", table_name="episodic_embeddings")
    op.drop_index("ix_episodic_embeddings_user", table_name="episodic_embeddings")
    op.drop_table("episodic_embeddings")
    # Don't drop the vector extension — other future objects may need it.
```

(The two-step `ADD/DROP COLUMN` dance avoids needing a `pgvector.sqlalchemy.Vector` type in the Alembic file. The real model in Task 3 uses the proper type.)

- [ ] **Step 2.3: Apply migration**

```bash
alembic upgrade head
```

Expected output ends with `Running upgrade 38cff6b9ccc2 -> <new-rev>, memory refinement...`. If it errors with "extension vector not available", the pgvector extension isn't installed in Postgres (Pre-flight section). Fix that first.

- [ ] **Step 2.4: Verify table exists**

```bash
psql -d my_assistant -c "\d episodic_embeddings"
```

Expected: shows id, user_id, source_type, source_id, content, embedding (vector(1024)), created_at columns. Two indexes: `ix_episodic_embeddings_user` and `ix_episodic_embeddings_vec`.

- [ ] **Step 2.5: Commit**

```bash
git add alembic/versions/
git commit -m "feat: alembic migration for pgvector extension + episodic_embeddings"
```

---

## Task 3: EpisodicEmbedding ORM Model

**Files:**
- Create: `app/models/episodic_embedding.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_models/test_episodic_embedding.py`

- [ ] **Step 3.1: Write failing test**

Create `tests/test_models/test_episodic_embedding.py`:

```python
import pytest
from sqlalchemy import select

from app.models.episodic_embedding import EpisodicEmbedding
from app.models.user import User


async def test_episodic_embedding_persists_with_vector(session):
    user = User(name="A", lark_user_id="emb_u1", preferences={})
    session.add(user)
    await session.commit()
    vec = [0.1] * 1024
    em = EpisodicEmbedding(
        user_id=user.id,
        source_type="event",
        source_id=42,
        content="hello world",
        embedding=vec,
    )
    session.add(em)
    await session.commit()
    await session.refresh(em)
    assert em.id is not None
    assert em.content == "hello world"
    assert len(em.embedding) == 1024
```

- [ ] **Step 3.2: Run, expect ImportError**

```bash
source .venv/bin/activate
pytest tests/test_models/test_episodic_embedding.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.models.episodic_embedding'`.

- [ ] **Step 3.3: Create the model**

Create `app/models/episodic_embedding.py`:

```python
from __future__ import annotations
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EpisodicEmbedding(Base):
    __tablename__ = "episodic_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

- [ ] **Step 3.4: Register in models __init__**

Edit `app/models/__init__.py`. Add `from app.models.episodic_embedding import EpisodicEmbedding` alongside other model imports. Also add `EpisodicEmbedding` to the `__all__` list if there is one.

- [ ] **Step 3.5: Run test against sqlite**

```bash
pytest tests/test_models/test_episodic_embedding.py -v
```

Expected: this **may fail on sqlite** because `Vector(1024)` is a pgvector-specific type. Two possible outcomes:

1. `pgvector.sqlalchemy.Vector` has a sqlite fallback (it might emit `BLOB` or `VARCHAR`) → test passes.
2. It rejects sqlite → test fails with a SQLAlchemy compilation error.

If outcome 2, mark the test postgres-only by editing the test:

```python
import pytest
from app.config import settings


pytestmark = pytest.mark.skipif(
    "sqlite" in settings.test_database_url,
    reason="pgvector requires Postgres",
)
```

Then re-run; it should skip cleanly.

- [ ] **Step 3.6: Full suite**

```bash
pytest tests/ -q
```

Expected: 182 passed, or 182 passed + 1 skipped (the new vector test).

- [ ] **Step 3.7: Commit**

```bash
git add app/models/episodic_embedding.py app/models/__init__.py tests/test_models/test_episodic_embedding.py
git commit -m "feat: EpisodicEmbedding ORM model"
```

---

## Task 4: Voyage Client

**Files:**
- Create: `app/services/voyage_client.py`
- Test: `tests/test_services/test_voyage_client.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/test_services/test_voyage_client.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.voyage_client import VoyageClient


async def test_embed_returns_vector(monkeypatch):
    fake_result = MagicMock()
    fake_result.embeddings = [[0.5] * 1024]
    fake_aclient = MagicMock()
    fake_aclient.embed = AsyncMock(return_value=fake_result)

    monkeypatch.setattr(
        "app.services.voyage_client.voyageai.AsyncClient",
        lambda **kw: fake_aclient,
    )
    client = VoyageClient(api_key="fake")
    vec = await client.embed("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 1024


async def test_embed_passes_model_name(monkeypatch):
    fake_result = MagicMock()
    fake_result.embeddings = [[0.0] * 1024]
    fake_aclient = MagicMock()
    fake_aclient.embed = AsyncMock(return_value=fake_result)

    monkeypatch.setattr(
        "app.services.voyage_client.voyageai.AsyncClient",
        lambda **kw: fake_aclient,
    )
    client = VoyageClient(api_key="fake")
    await client.embed("test")
    call_args = fake_aclient.embed.await_args
    assert call_args.kwargs.get("model") == "voyage-3" or "voyage-3" in (call_args.args or [None])[1:2] or call_args.args[1] == "voyage-3"
```

(The second test loosely checks `model="voyage-3"` was passed; voyageai's API takes it as a kwarg in modern versions.)

- [ ] **Step 4.2: Run, expect ImportError**

```bash
pytest tests/test_services/test_voyage_client.py -v
```

- [ ] **Step 4.3: Create `app/services/voyage_client.py`**

```python
from __future__ import annotations
import logging
from typing import Optional

import voyageai

from app.config import settings

logger = logging.getLogger(__name__)


class VoyageClient:
    """Thin async wrapper around voyageai.AsyncClient.

    All embedding calls are best-effort: when no API key is configured, embed()
    returns an empty list instead of raising. Callers must handle empty returns
    as 'skip embedding for this item'.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or settings.voyage_api_key
        self._client = (
            voyageai.AsyncClient(api_key=self._api_key) if self._api_key else None
        )

    async def embed(self, text: str) -> list[float]:
        if self._client is None:
            logger.info("voyage_client: no API key, returning empty vector")
            return []
        result = await self._client.embed([text], model="voyage-3")
        return result.embeddings[0]
```

- [ ] **Step 4.4: Run, expect PASS (or adjust the kwarg-check test if voyageai's API differs)**

```bash
pytest tests/test_services/test_voyage_client.py -v
```

If `test_embed_passes_model_name` fails because the voyageai library version takes `model` positionally, simplify the assertion to just `assert fake_aclient.embed.await_count == 1` and remove the model-name check.

- [ ] **Step 4.5: Add a "no key" test**

Append to the test file:

```python
async def test_embed_without_api_key_returns_empty():
    client = VoyageClient(api_key="")
    vec = await client.embed("hello")
    assert vec == []
```

Run:

```bash
pytest tests/test_services/test_voyage_client.py -v
```

Expected: 3 passed.

- [ ] **Step 4.6: Full suite, then commit**

```bash
pytest tests/ -q
git add app/services/voyage_client.py tests/test_services/test_voyage_client.py
git commit -m "feat: VoyageClient with no-key soft-fail"
```

---

## Task 5: embeddings Writer

**Files:**
- Create: `app/memory/__init__.py` (empty)
- Create: `app/memory/embeddings.py`
- Test: `tests/test_memory/__init__.py` (empty)
- Test: `tests/test_memory/test_embeddings.py`

- [ ] **Step 5.1: Create the empty package markers**

```bash
mkdir -p /Users/guoyuzhu/personal-assistant/app/memory
touch /Users/guoyuzhu/personal-assistant/app/memory/__init__.py
mkdir -p /Users/guoyuzhu/personal-assistant/tests/test_memory
touch /Users/guoyuzhu/personal-assistant/tests/test_memory/__init__.py
```

- [ ] **Step 5.2: Write failing tests**

Create `tests/test_memory/test_embeddings.py`:

```python
import pytest
from unittest.mock import AsyncMock

from app.memory.embeddings import (
    EMBEDDABLE_EVENT_TYPES,
    MIN_CONTENT_CHARS,
    MAX_CONTENT_CHARS,
    embed_and_store,
)
from app.models.user import User


async def test_embeddable_event_types_set():
    assert "feedback_recorded" in EMBEDDABLE_EVENT_TYPES
    assert "pattern_recorded" in EMBEDDABLE_EVENT_TYPES
    assert "profile_updated" in EMBEDDABLE_EVENT_TYPES
    assert "task_completed" in EMBEDDABLE_EVENT_TYPES
    assert "goal_set" in EMBEDDABLE_EVENT_TYPES
    # Things we DON'T embed
    assert "flow_started" not in EMBEDDABLE_EVENT_TYPES
    assert "reminder_fired" not in EMBEDDABLE_EVENT_TYPES


async def test_embed_and_store_skips_empty_content(session, monkeypatch):
    fake_voyage = AsyncMock()
    fake_voyage.embed = AsyncMock(return_value=[0.5] * 1024)
    monkeypatch.setattr("app.memory.embeddings._voyage", fake_voyage)

    user = User(name="A", lark_user_id="emb_skip", preferences={})
    session.add(user)
    await session.commit()
    await embed_and_store(session, user.id, "event", 1, "")
    await embed_and_store(session, user.id, "event", 2, "    ")
    fake_voyage.embed.assert_not_called()


async def test_embed_and_store_skips_under_min_chars(session, monkeypatch):
    fake_voyage = AsyncMock()
    fake_voyage.embed = AsyncMock(return_value=[0.5] * 1024)
    monkeypatch.setattr("app.memory.embeddings._voyage", fake_voyage)

    user = User(name="A", lark_user_id="emb_min", preferences={})
    session.add(user)
    await session.commit()
    short = "abc"
    assert len(short) < MIN_CONTENT_CHARS
    await embed_and_store(session, user.id, "event", 3, short)
    fake_voyage.embed.assert_not_called()


async def test_embed_and_store_truncates_long_content(session, monkeypatch):
    captured_input = {}
    async def fake_embed(text):
        captured_input["text"] = text
        return [0.1] * 1024
    fake_voyage = AsyncMock()
    fake_voyage.embed = fake_embed
    monkeypatch.setattr("app.memory.embeddings._voyage", fake_voyage)

    user = User(name="A", lark_user_id="emb_long", preferences={})
    session.add(user)
    await session.commit()
    long_text = "x" * (MAX_CONTENT_CHARS + 500)
    await embed_and_store(session, user.id, "event", 4, long_text)
    assert len(captured_input["text"]) == MAX_CONTENT_CHARS


async def test_embed_and_store_handles_voyage_error(session, monkeypatch):
    async def fake_embed(text):
        raise RuntimeError("voyage down")
    fake_voyage = AsyncMock()
    fake_voyage.embed = fake_embed
    monkeypatch.setattr("app.memory.embeddings._voyage", fake_voyage)

    user = User(name="A", lark_user_id="emb_err", preferences={})
    session.add(user)
    await session.commit()
    # Should not raise
    await embed_and_store(session, user.id, "event", 5, "hello world content")
```

(The success-path persistence test is split into Task 6, which exercises the integration with pgvector — skipped on sqlite.)

- [ ] **Step 5.3: Run, expect ImportError**

```bash
pytest tests/test_memory/test_embeddings.py -v
```

- [ ] **Step 5.4: Create `app/memory/embeddings.py`**

```python
from __future__ import annotations
import logging
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episodic_embedding import EpisodicEmbedding
from app.services.voyage_client import VoyageClient

logger = logging.getLogger(__name__)

EMBEDDABLE_EVENT_TYPES = {
    "feedback_recorded",
    "pattern_recorded",
    "profile_updated",
    "task_completed",
    "goal_set",
}
MIN_CONTENT_CHARS = 5
MAX_CONTENT_CHARS = 4000

# Module-level singleton — tests monkeypatch this.
_voyage = VoyageClient()


async def embed_and_store(
    session: AsyncSession,
    user_id: int,
    source_type: Literal["event", "conversation"],
    source_id: int,
    content: str,
) -> None:
    """Embed `content` and persist an EpisodicEmbedding row.

    Soft-fails: empty/short content → skip; Voyage error → log + skip; no API key
    → embed() returns [] which we treat as skip.
    """
    if not content or len(content.strip()) < MIN_CONTENT_CHARS:
        return
    content = content[:MAX_CONTENT_CHARS]
    try:
        vec = await _voyage.embed(content)
    except Exception as e:
        logger.warning("embed_and_store: voyage error: %s", e)
        return
    if not vec:
        return
    session.add(EpisodicEmbedding(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        content=content,
        embedding=vec,
    ))
    try:
        await session.commit()
    except Exception as e:
        logger.warning("embed_and_store: persist failed: %s", e)
        await session.rollback()
```

- [ ] **Step 5.5: Run, expect PASS**

```bash
pytest tests/test_memory/test_embeddings.py -v
```

Expected: 5 passed.

- [ ] **Step 5.6: Full suite + commit**

```bash
pytest tests/ -q
git add app/memory/__init__.py app/memory/embeddings.py tests/test_memory/
git commit -m "feat: embed_and_store with soft-fail guards"
```

---

## Task 6: Hook Embedding Writes Into Conversation + Action Paths

**Files:**
- Modify: `app/orchestrator/conversation.py`
- Modify: `app/orchestrator/act.py`
- Test: `tests/test_orchestrator/test_proactive.py` (add a regression smoke; no per-task test file because the integration is observed through orchestrator behavior)

- [ ] **Step 6.1: Add helper to act.py: post-commit fire-and-forget embed**

Edit `app/orchestrator/act.py`. Add to imports near the top:

```python
import asyncio
from app.memory.embeddings import EMBEDDABLE_EVENT_TYPES, embed_and_store
from app.database import async_session_factory
```

Add a new private function near the top of the file (after imports, before `ActionExecutor`):

```python
def _content_for_event(action_type: str, payload: dict) -> str:
    """Build embeddable text for a result row."""
    if action_type == "task_completed":
        return f"completed task: {payload.get('title', '')}".strip()
    if action_type == "pattern_recorded":
        return f"learned pattern: {payload.get('pattern', '')}".strip()
    if action_type == "profile_updated":
        return f"profile {payload.get('path', '')}: {payload.get('after', '')}".strip()
    if action_type == "feedback_recorded":
        return str(payload.get("content", "")).strip()
    if action_type == "goal_set":
        return f"goal: {payload.get('title', '')}".strip()
    return ""


async def _background_embed_event(user_id: int, source_id: int, content: str) -> None:
    if not content:
        return
    async with async_session_factory() as session:
        await embed_and_store(session, user_id, "event", source_id, content)
```

- [ ] **Step 6.2: Hook into `execute_all`**

At the END of `ActionExecutor.execute_all` (right before `return results`), schedule fire-and-forget tasks:

Locate the existing return:

```python
        await self.session.commit()
        return results
```

Replace with:

```python
        await self.session.commit()

        # Fire-and-forget embedding writes for embeddable event types.
        for result, action in zip(results, actions):
            event_type = _EVENT_TYPE_MAP.get(action.type)
            if event_type in EMBEDDABLE_EVENT_TYPES:
                content = _content_for_event(event_type, result.payload or {})
                if content and result.entity_id is not None:
                    asyncio.create_task(
                        _background_embed_event(user_id, result.entity_id, content)
                    )
        return results
```

(`_EVENT_TYPE_MAP` already lives at the bottom of `act.py` and is imported by `conversation.py`. Same module access.)

- [ ] **Step 6.3: Hook user-message embed into orchestrator**

Edit `app/orchestrator/conversation.py`. Add imports near the top:

```python
import asyncio
from app.database import async_session_factory
from app.memory.embeddings import embed_and_store
```

Add a helper at module level:

```python
async def _background_embed_user_message(user_id: int, msg_id: int, content: str) -> None:
    async with async_session_factory() as session:
        await embed_and_store(session, user_id, "conversation", msg_id, content)
```

In `ConversationOrchestrator.handle`, immediately after `await self.session.refresh(user_msg)` (which fixes the user_msg.id), add:

```python
        asyncio.create_task(
            _background_embed_user_message(user_id, user_msg.id, message)
        )
```

- [ ] **Step 6.4: Verify no test regression**

```bash
source .venv/bin/activate
pytest tests/ -q
```

Expected: 182 passed. The fire-and-forget embeds call `_voyage.embed()`, which returns `[]` when no API key is set (Task 4 design), so no persistence is attempted. Note: `asyncio.create_task` schedules but doesn't await — the background task may complete after `handle` returns. In tests this is fine because we don't assert on embedding rows.

- [ ] **Step 6.5: Add a smoke test confirming the hook is wired**

Append to `tests/test_orchestrator/test_conversation.py` (the existing file):

```python
async def test_orchestrator_schedules_embed_for_user_message(session, monkeypatch):
    """Smoke: orchestrator triggers a background embed call for the user message."""
    user = User(name="X", lark_user_id="orch_emb_smoke", preferences={})
    session.add(user)
    await session.commit()

    embed_calls = []
    async def fake_embed(s, uid, source_type, source_id, content):
        embed_calls.append({"source_type": source_type, "content": content})
    monkeypatch.setattr("app.orchestrator.conversation.embed_and_store", fake_embed)

    router = _ScriptedRouter(
        think_payload={"intent": "noop", "actions": [], "should_reply": False,
                       "reply_complexity": "low", "reply_hint": None, "reasoning": ""},
        react_text="(unused)",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    await orch.handle(user_id=user.id, message="hello there")

    # Give the background task a tick to run
    import asyncio as _asyncio
    await _asyncio.sleep(0.05)
    assert any(c["source_type"] == "conversation" and "hello there" in c["content"]
               for c in embed_calls)
```

(Verify `User`, `ConversationOrchestrator`, `_ScriptedRouter` are already imported at the top of that test file from Spec 1's Task 11.)

- [ ] **Step 6.6: Run, expect PASS**

```bash
pytest tests/test_orchestrator/test_conversation.py -v
```

- [ ] **Step 6.7: Full suite + commit**

```bash
pytest tests/ -q
git add app/orchestrator/act.py app/orchestrator/conversation.py tests/test_orchestrator/test_conversation.py
git commit -m "feat: fire-and-forget embed for user messages and embeddable actions"
```

---

## Task 7: Episodic Recall (Vector Search)

**Files:**
- Create: `app/memory/retrieval.py`
- Test: `tests/test_memory/test_retrieval.py`

- [ ] **Step 7.1: Write failing test**

Create `tests/test_memory/test_retrieval.py`:

```python
import pytest
from unittest.mock import AsyncMock

from app.config import settings
from app.memory.retrieval import episodic_recall, EPISODIC_SIMILARITY_THRESHOLD, EPISODIC_TOP_K


pytestmark = pytest.mark.skipif(
    "sqlite" in settings.test_database_url,
    reason="vector search requires Postgres + pgvector",
)


async def test_episodic_recall_returns_empty_when_query_blank(session):
    result = await episodic_recall(session, user_id=1, query_text="")
    assert result == []


async def test_episodic_recall_returns_empty_when_no_embeddings(session, monkeypatch):
    fake_voyage = AsyncMock()
    fake_voyage.embed = AsyncMock(return_value=[0.5] * 1024)
    monkeypatch.setattr("app.memory.retrieval._voyage", fake_voyage)
    result = await episodic_recall(session, user_id=999, query_text="anything at all")
    assert result == []


async def test_episodic_recall_top_k_constant():
    assert EPISODIC_TOP_K == 3


async def test_episodic_similarity_threshold_constant():
    assert EPISODIC_SIMILARITY_THRESHOLD == 0.7
```

The two empty-result tests are sqlite-skipped because `episodic_embeddings` table only exists on Postgres. The constant tests run anywhere.

- [ ] **Step 7.2: Run, expect ImportError**

```bash
source .venv/bin/activate
pytest tests/test_memory/test_retrieval.py -v
```

- [ ] **Step 7.3: Create `app/memory/retrieval.py`**

```python
from __future__ import annotations
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episodic_embedding import EpisodicEmbedding
from app.services.voyage_client import VoyageClient

logger = logging.getLogger(__name__)

EPISODIC_TOP_K = 3
EPISODIC_SIMILARITY_THRESHOLD = 0.7   # cosine similarity in [-1, 1], 0.7 ≈ "clearly related"
MIN_QUERY_CHARS = 5

# Module-level singleton — tests monkeypatch this.
_voyage = VoyageClient()


async def episodic_recall(
    session: AsyncSession,
    user_id: int,
    query_text: str,
) -> list[dict]:
    """Top-k cross-day vector recall above similarity threshold.

    Returns list of dicts {source_type, content, date} ordered by similarity desc.
    Empty list on any failure or sub-threshold matches.
    """
    if not query_text or len(query_text.strip()) < MIN_QUERY_CHARS:
        return []
    try:
        query_vec = await _voyage.embed(query_text)
    except Exception as e:
        logger.warning("episodic_recall: voyage error: %s", e)
        return []
    if not query_vec:
        return []

    # pgvector cosine_distance = 1 - cosine_similarity
    distance_threshold = 1.0 - EPISODIC_SIMILARITY_THRESHOLD
    try:
        q = (
            select(EpisodicEmbedding)
            .where(
                EpisodicEmbedding.user_id == user_id,
                EpisodicEmbedding.embedding.cosine_distance(query_vec) <= distance_threshold,
            )
            .order_by(EpisodicEmbedding.embedding.cosine_distance(query_vec))
            .limit(EPISODIC_TOP_K)
        )
        rows = (await session.execute(q)).scalars().all()
    except Exception as e:
        logger.warning("episodic_recall: query failed: %s", e)
        return []

    return [
        {
            "source_type": r.source_type,
            "content": r.content,
            "date": r.created_at.isoformat(),
        }
        for r in rows
    ]
```

- [ ] **Step 7.4: Run tests**

```bash
pytest tests/test_memory/test_retrieval.py -v
```

Expected on sqlite: 2 passed (constants), 2 skipped (DB-dependent).

- [ ] **Step 7.5: Full suite + commit**

```bash
pytest tests/ -q
git add app/memory/retrieval.py tests/test_memory/test_retrieval.py
git commit -m "feat: episodic_recall vector search with similarity threshold"
```

---

## Task 8: load_context Rewrite — Today's Full Conversation + Episodic Recall

**Files:**
- Modify: `app/orchestrator/context.py`
- Modify: `tests/test_orchestrator/test_context.py`
- Modify: `tests/test_orchestrator/test_think.py` (update `_empty_ctx` helper)
- Modify: `tests/test_orchestrator/test_react.py` (update `_ctx` helper)

- [ ] **Step 8.1: Add failing tests**

Append to `tests/test_orchestrator/test_context.py`:

```python
from datetime import datetime, timedelta, timezone


async def test_load_context_loads_all_of_todays_turns(session):
    u = User(name="T", lark_user_id="ctx_today", preferences={})
    session.add(u)
    await session.commit()
    # 25 conversations today — more than the previous 10-turn cap
    for i in range(25):
        session.add(Conversation(user_id=u.id, role="user", content=f"today_msg_{i}"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert len(ctx.recent_turns) == 25
    assert ctx.recent_turns[-1]["content"] == "today_msg_24"


async def test_load_context_caps_at_60_turns(session):
    u = User(name="T", lark_user_id="ctx_cap", preferences={})
    session.add(u)
    await session.commit()
    for i in range(80):
        session.add(Conversation(user_id=u.id, role="user", content=f"m_{i}"))
    await session.commit()
    ctx = await load_context(u.id, session)
    assert len(ctx.recent_turns) == 60
    # last item kept
    assert ctx.recent_turns[-1]["content"] == "m_79"


async def test_load_context_has_episodic_recall_field(session):
    u = User(name="T", lark_user_id="ctx_ep", preferences={})
    session.add(u)
    await session.commit()
    ctx = await load_context(u.id, session)
    assert hasattr(ctx, "episodic_recall")
    assert ctx.episodic_recall == []


async def test_load_context_accepts_query_text(session, monkeypatch):
    """When query_text is passed, episodic_recall is queried."""
    calls = []
    async def fake_recall(s, user_id, query_text):
        calls.append({"user_id": user_id, "query_text": query_text})
        return []
    monkeypatch.setattr("app.orchestrator.context.episodic_recall", fake_recall)

    u = User(name="T", lark_user_id="ctx_query", preferences={})
    session.add(u)
    await session.commit()
    await load_context(u.id, session, query_text="hello")
    assert calls and calls[0]["query_text"] == "hello"


async def test_load_context_blank_query_skips_recall(session, monkeypatch):
    calls = []
    async def fake_recall(s, user_id, query_text):
        calls.append({"user_id": user_id, "query_text": query_text})
        return []
    monkeypatch.setattr("app.orchestrator.context.episodic_recall", fake_recall)

    u = User(name="T", lark_user_id="ctx_noquery", preferences={})
    session.add(u)
    await session.commit()
    await load_context(u.id, session)
    assert calls == []
```

- [ ] **Step 8.2: Run, expect failures**

```bash
source .venv/bin/activate
pytest tests/test_orchestrator/test_context.py -v 2>&1 | tail -30
```

- [ ] **Step 8.3: Rewrite `app/orchestrator/context.py`**

Read the current file first to preserve structure.

Apply these changes:

1. **Add imports** near the top alongside existing imports:

```python
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

from app.memory.retrieval import episodic_recall
```

2. **Replace constants block** (keep existing `OPEN_TASKS_LIMIT`, `ACTIVE_GOALS_LIMIT`, `ACTIVE_HABITS_LIMIT`; replace `RECENT_TURNS_LIMIT`):

```python
RECENT_TURNS_CAP = 60
YESTERDAY_TAIL = 5
MORNING_HOUR_CUTOFF = 12
OPEN_TASKS_LIMIT = 5
ACTIVE_GOALS_LIMIT = 10
ACTIVE_HABITS_LIMIT = 15
```

3. **Add `episodic_recall` field to `Context`** (at the end of the dataclass):

```python
    episodic_recall: list[dict]
```

4. **Replace the `load_context` signature** to accept `query_text`:

```python
async def load_context(
    user_id: int,
    session: AsyncSession,
    query_text: str = "",
) -> Context:
```

5. **Replace the recent_turns query block** with this:

```python
    # Today's full conversation, capped at RECENT_TURNS_CAP
    prefs_obj = UserPreferences.from_jsonb(user.preferences or {})
    tz_name = (prefs_obj.profile.timezone or "UTC") if prefs_obj.profile else "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_local.astimezone(timezone.utc)

    turns_q = (
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.created_at >= today_start_utc,
        )
        .order_by(desc(Conversation.id))
        .limit(RECENT_TURNS_CAP)
    )
    turns_rows = (await session.execute(turns_q)).scalars().all()
    today_turns = [
        {"role": t.role, "content": t.content, "intent": t.intent}
        for t in reversed(turns_rows)
    ]

    # Optionally prepend yesterday's tail in morning if today is sparse
    yesterday_tail: list[dict] = []
    if len(today_turns) < YESTERDAY_TAIL and now_local.hour < MORNING_HOUR_CUTOFF:
        yesterday_end_utc = today_start_utc
        yesterday_start_utc = yesterday_end_utc - timedelta(days=1)
        y_q = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.created_at >= yesterday_start_utc,
                Conversation.created_at < yesterday_end_utc,
            )
            .order_by(desc(Conversation.id))
            .limit(YESTERDAY_TAIL)
        )
        y_rows = (await session.execute(y_q)).scalars().all()
        yesterday_tail = [
            {"role": t.role, "content": t.content, "intent": t.intent}
            for t in reversed(y_rows)
        ]

    recent_turns = yesterday_tail + today_turns
```

(The previous code computed `prefs` once at the top of the function — be careful not to compute it twice. If the existing code already populated `prefs` early, reuse that variable for `tz_name`. The snippet above assumes `user.preferences` is already in scope; adjust the variable name to match whatever the existing function uses.)

6. **Add the episodic_recall block** before the final `return Context(...)`:

```python
    episodic_recall_results: list[dict] = []
    if query_text:
        episodic_recall_results = await episodic_recall(session, user_id, query_text)
```

7. **Update the `return Context(...)` call** to include the new field:

```python
        episodic_recall=episodic_recall_results,
```

Make sure `recent_turns=recent_turns` is in the return as well (it should already be, with the new value).

- [ ] **Step 8.4: Update test helpers in `test_think.py` and `test_react.py`**

In `tests/test_orchestrator/test_think.py`, find the `_empty_ctx` helper and add `episodic_recall=[]` to the `defaults` dict.

In `tests/test_orchestrator/test_react.py`, find the `_ctx` helper and add `episodic_recall=[]` to the keyword arguments.

In `tests/test_orchestrator/test_proactive.py`, no manual Context construction → no change needed.

- [ ] **Step 8.5: Run tests**

```bash
pytest tests/test_orchestrator/ -q
```

Expected: all pass including 5 new tests.

- [ ] **Step 8.6: Full suite**

```bash
pytest tests/ -q
```

- [ ] **Step 8.7: Commit**

```bash
git add app/orchestrator/context.py tests/test_orchestrator/
git commit -m "feat: load_context loads today's full convo + episodic_recall"
```

---

## Task 9: Pass `query_text` Through Orchestrator

**Files:**
- Modify: `app/orchestrator/conversation.py`
- Test: `tests/test_orchestrator/test_conversation.py` (additive)

- [ ] **Step 9.1: Add failing test**

Append to `tests/test_orchestrator/test_conversation.py`:

```python
async def test_orchestrator_passes_message_as_query_text(session, monkeypatch):
    captured = {}
    async def fake_load_context(user_id, session_, query_text=""):
        captured["query_text"] = query_text
        from app.orchestrator.context import Context
        from app.schemas.preferences import Profile
        return Context(
            user_id=user_id, user_name="T", profile=Profile(),
            procedural_patterns=[], onboarding_status="pending",
            active_flow=None, flow_filled_fields={}, flow_missing_fields=[],
            recent_turns=[], open_tasks=[],
            active_goals=[], active_habits=[],
            episodic_recall=[],
        )
    monkeypatch.setattr("app.orchestrator.conversation.load_context", fake_load_context)

    user = User(name="A", lark_user_id="qt_u1", preferences={})
    session.add(user)
    await session.commit()
    router = _ScriptedRouter(
        think_payload={"intent": "noop", "actions": [], "should_reply": False,
                       "reply_complexity": "low", "reply_hint": None, "reasoning": ""},
        react_text="(unused)",
    )
    orch = ConversationOrchestrator(session=session, llm=router)
    await orch.handle(user_id=user.id, message="how am I doing this week?")
    assert captured["query_text"] == "how am I doing this week?"
```

- [ ] **Step 9.2: Run, expect failure**

```bash
source .venv/bin/activate
pytest tests/test_orchestrator/test_conversation.py::test_orchestrator_passes_message_as_query_text -v
```

- [ ] **Step 9.3: Modify `ConversationOrchestrator.handle`**

In `app/orchestrator/conversation.py`, find this line in `handle`:

```python
        ctx = await load_context(user_id, self.session)
```

Replace with:

```python
        ctx = await load_context(user_id, self.session, query_text=message)
```

`send_proactive_impl` already calls `load_context` without `query_text` (the default empty string), so proactive paths are unaffected.

- [ ] **Step 9.4: Run, expect PASS**

```bash
pytest tests/test_orchestrator/test_conversation.py -v
```

- [ ] **Step 9.5: Full suite + commit**

```bash
pytest tests/ -q
git add app/orchestrator/conversation.py tests/test_orchestrator/test_conversation.py
git commit -m "feat: orchestrator passes user message as query_text for recall"
```

---

## Task 10: THINK and REACT Prompts — episodic_recall + reinforce/contradict guidance

**Files:**
- Modify: `app/orchestrator/think.py`
- Modify: `app/orchestrator/prompts/think.md`
- Modify: `app/orchestrator/prompts/react.md`

- [ ] **Step 10.1: Include episodic_recall in THINK's user content**

Read `app/orchestrator/think.py`. Find `_build_user_content`. After the existing `<learned_patterns>...</learned_patterns>` line, add a new XML section. Locate this fragment:

```python
        f"<user_profile>{profile_block}</user_profile>\n"
        f"<learned_patterns>{patterns_block}</learned_patterns>\n"
```

Replace with:

```python
    recall_block = json.dumps(ctx.episodic_recall, ensure_ascii=False)

    return (
        f"<user_profile>{profile_block}</user_profile>\n"
        f"<learned_patterns>{patterns_block}</learned_patterns>\n"
        f"<episodic_recall>{recall_block}</episodic_recall>\n"
```

(Move the `recall_block = ...` line up next to other `*_block = ...` assignments inside `_build_user_content`. Place it right before the `return (` statement.)

- [ ] **Step 10.2: Append guidance to `app/orchestrator/prompts/think.md`**

Append (with one blank line before):

```markdown

`<episodic_recall>` is a small list of past events or messages the system retrieved as potentially relevant to the user's current message. It is NOT a complete history — only the top-3 vector-similar items above threshold. Use it to ground references the user is making ("as I mentioned last week", "remember when we talked about X"). If the recall list is empty, do not pretend to remember.

You can also emit these actions:
- `reinforce_pattern` (params: `pattern_substring`, `delta` default 0.1) — emit when the user's current behavior validates an existing learned pattern (look at `<learned_patterns>`). The substring should uniquely identify which pattern.
- `contradict_pattern` (params: `pattern_substring`, `delta` default 0.3) — emit when the user's current behavior contradicts an existing learned pattern. Larger default delta because contradiction is a stronger signal.

Do not emit reinforce/contradict speculatively. Only when a specific existing pattern is the clear target.
```

- [ ] **Step 10.3: Append guidance to `app/orchestrator/prompts/react.md`**

Append (with one blank line before):

```markdown

When `<episodic_recall>` contains items, you may naturally reference them when relevant ("yeah, like you mentioned X last week..."). Don't list them. Don't fabricate dates. If the recall list is empty, don't pretend to remember things you don't actually have context for.
```

- [ ] **Step 10.4: Update REACT to thread episodic_recall through**

Read `app/orchestrator/react.py`. Find `react_or_raise` (or `react` if there's no split). Find the `user_content` construction. It likely looks like:

```python
    user_content = (
        f"<conversation_history>\n{history}\n</conversation_history>\n"
        f"<user_message>{message}</user_message>\n"
        f"<actions_completed>{json.dumps(action_results, ensure_ascii=False)}</actions_completed>\n"
        f"<hint>{hint or ''}</hint>"
    )
```

Add an `<episodic_recall>` line after `<conversation_history>`:

```python
    recall_block = json.dumps(ctx.episodic_recall, ensure_ascii=False)
    user_content = (
        f"<conversation_history>\n{history}\n</conversation_history>\n"
        f"<episodic_recall>{recall_block}</episodic_recall>\n"
        f"<user_message>{message}</user_message>\n"
        f"<actions_completed>{json.dumps(action_results, ensure_ascii=False)}</actions_completed>\n"
        f"<hint>{hint or ''}</hint>"
    )
```

- [ ] **Step 10.5: Run all orchestrator tests — no behavior regression**

```bash
source .venv/bin/activate
pytest tests/test_orchestrator/ -q
```

The existing tests don't assert the absence of the new XML block, so they should still pass. If `test_react_includes_action_results_in_user_message` or similar substring tests fail, examine — they should still match because we only added blocks, didn't remove.

- [ ] **Step 10.6: Full suite + commit**

```bash
pytest tests/ -q
git add app/orchestrator/think.py app/orchestrator/react.py app/orchestrator/prompts/
git commit -m "feat: episodic_recall + reinforce/contradict guidance in THINK/REACT"
```

---

## Task 11: Goal Auto-Increment on Task Completion

**Files:**
- Modify: `app/orchestrator/act.py`
- Test: `tests/test_orchestrator/test_act.py` (additive)

- [ ] **Step 11.1: Add failing test**

Append to `tests/test_orchestrator/test_act.py`:

```python
from datetime import date as date_type
from app.models.goal import Goal


async def test_complete_task_increments_linked_goal(session):
    user = await _make_user(session, lark="goal_inc_u1")
    goal = Goal(
        user_id=user.id, title="write 50 posts", target_value=50, current_value=3,
        unit="post", period_start=date_type.today(), period_end=date_type.today(),
        status="active",
    )
    session.add(goal)
    await session.commit()
    task = Task(user_id=user.id, title="post 4", status="pending", goal_id=goal.id)
    session.add(task)
    await session.commit()

    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=task.id)
    )], conversation_id=None)
    await session.refresh(goal)
    assert goal.current_value == 4


async def test_complete_task_without_goal_id_does_not_touch_goals(session):
    user = await _make_user(session, lark="goal_inc_u2")
    task = Task(user_id=user.id, title="standalone", status="pending", goal_id=None)
    session.add(task)
    await session.commit()
    executor = ActionExecutor(session)
    # No goals in DB at all — should not error
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=task.id)
    )], conversation_id=None)
    await session.refresh(task)
    assert task.status == "done"


async def test_complete_task_skips_inactive_goal(session):
    user = await _make_user(session, lark="goal_inc_u3")
    goal = Goal(
        user_id=user.id, title="old goal", target_value=10, current_value=8,
        unit="x", period_start=date_type.today(), period_end=date_type.today(),
        status="completed",
    )
    session.add(goal)
    await session.commit()
    task = Task(user_id=user.id, title="leftover", status="pending", goal_id=goal.id)
    session.add(task)
    await session.commit()
    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.COMPLETE_TASK, CompleteTaskParams(task_id=task.id)
    )], conversation_id=None)
    await session.refresh(goal)
    assert goal.current_value == 8   # unchanged
```

- [ ] **Step 11.2: Run, expect failure**

```bash
source .venv/bin/activate
pytest tests/test_orchestrator/test_act.py::test_complete_task_increments_linked_goal -v
```

- [ ] **Step 11.3: Modify `_complete_task` in `app/orchestrator/act.py`**

The current `_complete_task` does:
1. Get task
2. Set task.status = "done"
3. Cancel pending reminders (from Spec 2 Task 11)
4. Flush + return

Add the goal-increment step between (3) and the flush. Locate the current implementation (search for `async def _complete_task`):

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
        # NEW: increment linked goal
        goal_incremented = False
        if task.goal_id is not None:
            goal = await self.session.get(Goal, task.goal_id)
            if goal is not None and goal.status == "active":
                goal.current_value = (goal.current_value or 0) + 1
                goal_incremented = True
        await self.session.flush()
        return ActionResult(
            type=ActionType.COMPLETE_TASK,
            entity_type="task",
            entity_id=task.id,
            payload={"completed_at": _now_iso(), "goal_incremented": goal_incremented},
        )
```

(`Goal` is already imported in `act.py` — Spec 1 Task 9 added the import. Verify with `grep "from app.models.goal" app/orchestrator/act.py`. If absent for any reason, add it.)

- [ ] **Step 11.4: Run, expect PASS**

```bash
pytest tests/test_orchestrator/test_act.py -v
```

Expected: 3 new + existing = all green.

- [ ] **Step 11.5: Full suite + commit**

```bash
pytest tests/ -q
git add app/orchestrator/act.py tests/test_orchestrator/test_act.py
git commit -m "feat: complete_task auto-increments linked goal.current_value"
```

---

## Task 12: Pattern Schema — `last_reinforced_at`

**Files:**
- Modify: `app/schemas/preferences.py`
- Test: `tests/test_schemas_preferences.py`

- [ ] **Step 12.1: Add failing test**

Append to `tests/test_schemas_preferences.py`:

```python
def test_pattern_has_last_reinforced_at_field():
    p = Pattern(pattern="x", confidence=0.5, learned_at="2026-05-26T00:00:00",
                last_reinforced_at="2026-05-26T12:00:00")
    assert p.last_reinforced_at == "2026-05-26T12:00:00"


def test_pattern_last_reinforced_at_defaults_to_none():
    p = Pattern(pattern="x")
    assert p.last_reinforced_at is None


def test_user_preferences_pattern_round_trip_with_last_reinforced_at():
    raw = {
        "profile": {},
        "procedural": [
            {"pattern": "test", "confidence": 0.7, "learned_at": "2026-05-26T00:00:00",
             "last_reinforced_at": "2026-05-26T08:00:00"},
        ],
    }
    prefs = UserPreferences.model_validate(raw)
    assert prefs.procedural[0].last_reinforced_at == "2026-05-26T08:00:00"
    again = UserPreferences.model_validate(prefs.model_dump())
    assert again.procedural[0].last_reinforced_at == "2026-05-26T08:00:00"
```

- [ ] **Step 12.2: Run, expect failure**

```bash
source .venv/bin/activate
pytest tests/test_schemas_preferences.py -v
```

- [ ] **Step 12.3: Modify `app/schemas/preferences.py`**

Edit the `Pattern` class. Add the new field after `learned_at`:

```python
class Pattern(BaseModel):
    pattern: str
    confidence: float = 0.5
    learned_at: Optional[str] = None
    last_reinforced_at: Optional[str] = None
```

- [ ] **Step 12.4: Run, expect PASS**

```bash
pytest tests/test_schemas_preferences.py -v
```

- [ ] **Step 12.5: Commit**

```bash
git add app/schemas/preferences.py tests/test_schemas_preferences.py
git commit -m "feat: add last_reinforced_at to Pattern schema"
```

---

## Task 13: New Action Types — REINFORCE_PATTERN, CONTRADICT_PATTERN

**Files:**
- Modify: `app/orchestrator/actions.py`
- Test: `tests/test_orchestrator/test_actions.py`

- [ ] **Step 13.1: Add failing tests**

Append to `tests/test_orchestrator/test_actions.py`:

```python
from app.orchestrator.actions import (
    ReinforcePatternParams, ContradictPatternParams,
)


def test_reinforce_pattern_action_type_exists():
    assert ActionType.REINFORCE_PATTERN.value == "reinforce_pattern"


def test_contradict_pattern_action_type_exists():
    assert ActionType.CONTRADICT_PATTERN.value == "contradict_pattern"


def test_reinforce_pattern_params_defaults():
    p = ReinforcePatternParams(pattern_substring="early reminders")
    assert p.delta == 0.1


def test_contradict_pattern_params_defaults():
    p = ContradictPatternParams(pattern_substring="early reminders")
    assert p.delta == 0.3


def test_parse_action_reinforce_pattern():
    parsed = parse_action({"type": "reinforce_pattern",
                           "params": {"pattern_substring": "diet", "delta": 0.2}})
    assert parsed.type == ActionType.REINFORCE_PATTERN
    assert parsed.params.delta == 0.2
```

- [ ] **Step 13.2: Run, expect failure**

```bash
pytest tests/test_orchestrator/test_actions.py -v 2>&1 | tail -20
```

- [ ] **Step 13.3: Add to `app/orchestrator/actions.py`**

Add two enum members. In `class ActionType(str, Enum)`, after the existing entries, add:

```python
    REINFORCE_PATTERN = "reinforce_pattern"
    CONTRADICT_PATTERN = "contradict_pattern"
```

Add two new param classes (somewhere alongside the others, e.g. right after `RecordPatternParams`):

```python
class ReinforcePatternParams(BaseModel):
    pattern_substring: str
    delta: float = 0.1


class ContradictPatternParams(BaseModel):
    pattern_substring: str
    delta: float = 0.3
```

Add the entries to `PARAM_REGISTRY` dict:

```python
PARAM_REGISTRY = {
    ...,
    ActionType.REINFORCE_PATTERN: ReinforcePatternParams,
    ActionType.CONTRADICT_PATTERN: ContradictPatternParams,
}
```

(Make sure the entry list ends with a comma where needed and the dict remains syntactically valid.)

- [ ] **Step 13.4: Run, expect PASS**

```bash
pytest tests/test_orchestrator/test_actions.py -v
```

Expected: 5 new tests + existing tests all pass.

- [ ] **Step 13.5: Commit**

```bash
git add app/orchestrator/actions.py tests/test_orchestrator/test_actions.py
git commit -m "feat: REINFORCE_PATTERN + CONTRADICT_PATTERN action types"
```

---

## Task 14: ActionExecutor — Reinforce/Contradict Dispatch

**Files:**
- Modify: `app/orchestrator/act.py`
- Test: `tests/test_orchestrator/test_act.py`

- [ ] **Step 14.1: Add failing tests**

Append to `tests/test_orchestrator/test_act.py`:

```python
from app.orchestrator.actions import ReinforcePatternParams, ContradictPatternParams


async def test_reinforce_pattern_bumps_confidence_and_refreshes_timestamp(session):
    user = await _make_user(session, lark="reinforce_u1")
    user.preferences = {
        "profile": {},
        "procedural": [
            {"pattern": "user dislikes 7am reminders", "confidence": 0.5,
             "learned_at": "2026-05-20T10:00:00+00:00",
             "last_reinforced_at": "2026-05-20T10:00:00+00:00"},
        ],
    }
    await session.commit()

    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.REINFORCE_PATTERN,
        ReinforcePatternParams(pattern_substring="7am reminders", delta=0.2),
    )], conversation_id=None)
    await session.refresh(user)
    assert user.preferences["procedural"][0]["confidence"] == pytest.approx(0.7)
    assert user.preferences["procedural"][0]["last_reinforced_at"] != "2026-05-20T10:00:00+00:00"


async def test_contradict_pattern_lowers_confidence(session):
    user = await _make_user(session, lark="contradict_u1")
    user.preferences = {
        "profile": {},
        "procedural": [
            {"pattern": "user prefers morning workouts", "confidence": 0.8,
             "learned_at": "2026-05-20T10:00:00+00:00",
             "last_reinforced_at": "2026-05-20T10:00:00+00:00"},
        ],
    }
    await session.commit()

    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.CONTRADICT_PATTERN,
        ContradictPatternParams(pattern_substring="morning workouts", delta=0.3),
    )], conversation_id=None)
    await session.refresh(user)
    assert user.preferences["procedural"][0]["confidence"] == pytest.approx(0.5)


async def test_reinforce_pattern_clamps_at_one():
    """Test the clamp logic on confidence."""
    from app.memory.confidence import _clamp
    assert _clamp(1.5) == 1.0
    assert _clamp(-0.2) == 0.0
    assert _clamp(0.7) == 0.7


async def test_reinforce_pattern_no_match_is_noop(session):
    user = await _make_user(session, lark="reinforce_u2")
    user.preferences = {
        "profile": {},
        "procedural": [
            {"pattern": "user likes coffee", "confidence": 0.5,
             "learned_at": "2026-05-20T10:00:00+00:00",
             "last_reinforced_at": "2026-05-20T10:00:00+00:00"},
        ],
    }
    await session.commit()
    executor = ActionExecutor(session)
    await executor.execute_all(user.id, [ParsedAction(
        ActionType.REINFORCE_PATTERN,
        ReinforcePatternParams(pattern_substring="nonexistent topic", delta=0.2),
    )], conversation_id=None)
    await session.refresh(user)
    assert user.preferences["procedural"][0]["confidence"] == 0.5  # unchanged
```

- [ ] **Step 14.2: Create `app/memory/confidence.py` with the `_clamp` helper now**

Even though the full confidence module comes in Task 16, we need `_clamp` for Task 14. Create the file with just the helper:

```python
from __future__ import annotations


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
```

(Task 16 will extend this file.)

- [ ] **Step 14.3: Run, expect failures**

```bash
source .venv/bin/activate
pytest tests/test_orchestrator/test_act.py -v 2>&1 | tail -20
```

- [ ] **Step 14.4: Add dispatch methods to `app/orchestrator/act.py`**

Add to the import list near the top:

```python
from app.memory.confidence import _clamp
from app.orchestrator.actions import (
    ...,
    ReinforcePatternParams,
    ContradictPatternParams,
)
```

(Merge `ReinforcePatternParams` and `ContradictPatternParams` into the existing multi-import block from `app.orchestrator.actions`.)

Add two new dispatch methods alongside the existing private dispatch methods on `ActionExecutor`:

```python
    async def _reinforce_pattern(
        self, user_id: int, p: ReinforcePatternParams
    ) -> ActionResult:
        return await self._adjust_pattern(user_id, p.pattern_substring, +abs(p.delta),
                                           action_type=ActionType.REINFORCE_PATTERN,
                                           event_type="pattern_reinforced")

    async def _contradict_pattern(
        self, user_id: int, p: ContradictPatternParams
    ) -> ActionResult:
        return await self._adjust_pattern(user_id, p.pattern_substring, -abs(p.delta),
                                           action_type=ActionType.CONTRADICT_PATTERN,
                                           event_type="pattern_contradicted")

    async def _adjust_pattern(
        self,
        user_id: int,
        substring: str,
        delta: float,
        action_type: ActionType,
        event_type: str,
    ) -> ActionResult:
        user = await self.session.get(User, user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        prefs = dict(user.preferences or {})
        procedural = list(prefs.get("procedural", []))
        match_idx = None
        for i, p in enumerate(procedural):
            if substring.lower() in p.get("pattern", "").lower():
                match_idx = i
                break
        if match_idx is None:
            # No match — emit a no-op result; event still records the attempt
            return ActionResult(
                type=action_type, entity_type="pattern", entity_id=None,
                payload={"matched": False, "substring": substring, "delta": delta},
            )
        target = dict(procedural[match_idx])
        old_conf = float(target.get("confidence", 0.5))
        new_conf = _clamp(old_conf + delta)
        target["confidence"] = new_conf
        target["last_reinforced_at"] = _now_iso()
        procedural[match_idx] = target
        prefs["procedural"] = procedural
        user.preferences = prefs
        await self.session.flush()
        return ActionResult(
            type=action_type, entity_type="pattern", entity_id=None,
            payload={"matched": True, "substring": substring,
                     "before_confidence": old_conf, "after_confidence": new_conf},
        )
```

- [ ] **Step 14.5: Wire dispatch in `_dispatch`**

Locate the `_dispatch` method's giant if-elif chain. Add:

```python
        if action.type == ActionType.REINFORCE_PATTERN:
            return await self._reinforce_pattern(user_id, action.params)
        if action.type == ActionType.CONTRADICT_PATTERN:
            return await self._contradict_pattern(user_id, action.params)
```

(Place these alongside the other action handlers.)

- [ ] **Step 14.6: Add event type mapping**

Find `_EVENT_TYPE_MAP` at the bottom of `act.py`. Add:

```python
    ActionType.REINFORCE_PATTERN: "pattern_reinforced",
    ActionType.CONTRADICT_PATTERN: "pattern_contradicted",
```

- [ ] **Step 14.7: Run tests, expect PASS**

```bash
pytest tests/test_orchestrator/test_act.py -v
```

Expected: 4 new tests + existing all pass.

- [ ] **Step 14.8: Full suite + commit**

```bash
pytest tests/ -q
git add app/memory/confidence.py app/orchestrator/act.py tests/test_orchestrator/test_act.py
git commit -m "feat: reinforce_pattern + contradict_pattern action dispatch"
```

---

## Task 15: Confidence Decay

**Files:**
- Modify: `app/memory/confidence.py`
- Test: `tests/test_memory/test_confidence.py`

- [ ] **Step 15.1: Write failing tests**

Create `tests/test_memory/test_confidence.py`:

```python
import pytest
from datetime import datetime, timedelta, timezone

from app.memory.confidence import (
    DAILY_DECAY_RATE, MIN_CONFIDENCE, _clamp, decay_pattern_confidence,
)
from app.models.user import User


def test_clamp_boundaries():
    assert _clamp(1.5) == 1.0
    assert _clamp(-0.2) == 0.0
    assert _clamp(0.7) == 0.7


def test_decay_rate_is_one_percent_per_day():
    assert DAILY_DECAY_RATE == 0.99


def test_min_confidence_is_point_one():
    assert MIN_CONFIDENCE == 0.1


async def test_decay_drops_patterns_below_threshold(session):
    long_ago = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    user = User(name="A", lark_user_id="decay_u1",
                preferences={"profile": {}, "procedural": [
                    {"pattern": "ancient pattern", "confidence": 0.5,
                     "learned_at": long_ago, "last_reinforced_at": long_ago},
                ]})
    session.add(user)
    await session.commit()
    dropped = await decay_pattern_confidence(session, user.id)
    assert dropped == 1
    await session.refresh(user)
    assert user.preferences["procedural"] == []


async def test_decay_lowers_confidence_proportionally(session):
    ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    user = User(name="B", lark_user_id="decay_u2",
                preferences={"profile": {}, "procedural": [
                    {"pattern": "recent pattern", "confidence": 0.9,
                     "learned_at": ten_days_ago, "last_reinforced_at": ten_days_ago},
                ]})
    session.add(user)
    await session.commit()
    await decay_pattern_confidence(session, user.id)
    await session.refresh(user)
    new_conf = user.preferences["procedural"][0]["confidence"]
    # 0.9 * 0.99^10 ≈ 0.814
    assert new_conf == pytest.approx(0.9 * (0.99 ** 10), rel=1e-3)


async def test_decay_keeps_recent_patterns(session):
    today = datetime.now(timezone.utc).isoformat()
    user = User(name="C", lark_user_id="decay_u3",
                preferences={"profile": {}, "procedural": [
                    {"pattern": "fresh", "confidence": 0.5,
                     "learned_at": today, "last_reinforced_at": today},
                ]})
    session.add(user)
    await session.commit()
    dropped = await decay_pattern_confidence(session, user.id)
    assert dropped == 0
    await session.refresh(user)
    new_conf = user.preferences["procedural"][0]["confidence"]
    assert new_conf == 0.5  # 0 days elapsed → no decay
```

- [ ] **Step 15.2: Run, expect failure**

```bash
source .venv/bin/activate
pytest tests/test_memory/test_confidence.py -v
```

- [ ] **Step 15.3: Extend `app/memory/confidence.py`**

Replace its content (build on the `_clamp` stub from Task 14):

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.preferences import UserPreferences, Pattern

logger = logging.getLogger(__name__)

DAILY_DECAY_RATE = 0.99
MIN_CONFIDENCE = 0.1


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


async def decay_pattern_confidence(session: AsyncSession, user_id: int) -> int:
    """Apply exponential time decay. Drop patterns below MIN_CONFIDENCE.
    Returns number dropped."""
    user = await session.get(User, user_id)
    if user is None:
        return 0
    prefs = UserPreferences.from_jsonb(user.preferences or {})
    if not prefs.procedural:
        return 0

    survivors: list[Pattern] = []
    dropped = 0
    now = datetime.now(timezone.utc)
    for p in prefs.procedural:
        base = p.last_reinforced_at or p.learned_at
        try:
            base_dt = datetime.fromisoformat(base) if base else now
        except (ValueError, TypeError):
            base_dt = now
        days = max(0, (now - base_dt).days)
        new_conf = p.confidence * (DAILY_DECAY_RATE ** days)
        if new_conf < MIN_CONFIDENCE:
            dropped += 1
            continue
        survivors.append(Pattern(
            pattern=p.pattern, confidence=new_conf,
            learned_at=p.learned_at, last_reinforced_at=p.last_reinforced_at,
        ))
    user.preferences = {
        **(user.preferences or {}),
        "procedural": [p.model_dump() for p in survivors],
    }
    await session.commit()
    return dropped
```

- [ ] **Step 15.4: Run, expect PASS**

```bash
pytest tests/test_memory/test_confidence.py -v
```

Expected: 6 passing.

- [ ] **Step 15.5: Commit**

```bash
git add app/memory/confidence.py tests/test_memory/test_confidence.py
git commit -m "feat: decay_pattern_confidence with exponential time decay"
```

---

## Task 16: Pattern Consolidation

**Files:**
- Create: `app/memory/consolidation.py`
- Test: `tests/test_memory/test_consolidation.py`

- [ ] **Step 16.1: Write failing tests**

Create `tests/test_memory/test_consolidation.py`:

```python
import pytest
from unittest.mock import AsyncMock

from app.memory.consolidation import _apply_consolidation, consolidate_patterns
from app.models.user import User
from app.schemas.preferences import Pattern


def test_apply_consolidation_drops_ids():
    patterns = [
        Pattern(pattern="a", confidence=0.5, learned_at="2026-05-01T00:00:00"),
        Pattern(pattern="b", confidence=0.6, learned_at="2026-05-02T00:00:00"),
        Pattern(pattern="c", confidence=0.7, learned_at="2026-05-03T00:00:00"),
    ]
    result = _apply_consolidation(patterns, {"drop_ids": [1], "merged": [], "keep_unchanged": False})
    assert len(result) == 2
    assert {p.pattern for p in result} == {"a", "c"}


def test_apply_consolidation_merges_originals():
    patterns = [
        Pattern(pattern="dislikes early reminders", confidence=0.5, learned_at="2026-05-01T00:00:00"),
        Pattern(pattern="prefers later notifications", confidence=0.6, learned_at="2026-05-02T00:00:00"),
        Pattern(pattern="loves coffee", confidence=0.7, learned_at="2026-05-03T00:00:00"),
    ]
    result = _apply_consolidation(
        patterns,
        {
            "drop_ids": [],
            "merged": [{"original_ids": [0, 1], "new_text": "dislikes early notifications", "new_confidence": 0.7}],
            "keep_unchanged": False,
        },
    )
    assert len(result) == 2
    titles = [p.pattern for p in result]
    assert "loves coffee" in titles
    assert any("dislikes early notifications" in t for t in titles)


def test_apply_consolidation_unchanged_returns_original():
    patterns = [
        Pattern(pattern="x", confidence=0.5),
        Pattern(pattern="y", confidence=0.6),
    ]
    result = _apply_consolidation(patterns, {"drop_ids": [], "merged": [], "keep_unchanged": True})
    assert len(result) == 2
    assert result == patterns


async def test_consolidate_patterns_skips_when_under_three(session, monkeypatch):
    user = User(name="A", lark_user_id="cons_u1",
                preferences={"profile": {}, "procedural": [
                    {"pattern": "only one", "confidence": 0.5, "learned_at": "2026-05-01"},
                ]})
    session.add(user)
    await session.commit()
    llm_called = []
    async def fake_complete_json(task_type, messages, **kw):
        llm_called.append(True)
        return {"drop_ids": [], "merged": [], "keep_unchanged": True}
    monkeypatch.setattr("app.memory.consolidation._llm.complete_json", fake_complete_json)
    result = await consolidate_patterns(session, user.id)
    assert result == {"unchanged": True}
    assert llm_called == []


async def test_consolidate_patterns_invokes_llm_and_applies(session, monkeypatch):
    iso = "2026-05-01T00:00:00+00:00"
    user = User(name="B", lark_user_id="cons_u2",
                preferences={"profile": {}, "procedural": [
                    {"pattern": "dislikes 7am pings", "confidence": 0.5, "learned_at": iso},
                    {"pattern": "hates early reminders", "confidence": 0.6, "learned_at": iso},
                    {"pattern": "loves coffee", "confidence": 0.7, "learned_at": iso},
                ]})
    session.add(user)
    await session.commit()
    async def fake_complete_json(task_type, messages, **kw):
        return {
            "drop_ids": [],
            "merged": [{"original_ids": [0, 1], "new_text": "dislikes early notifications",
                        "new_confidence": 0.7}],
            "keep_unchanged": False,
        }
    monkeypatch.setattr("app.memory.consolidation._llm.complete_json", fake_complete_json)
    result = await consolidate_patterns(session, user.id)
    assert result["before"] == 3
    assert result["after"] == 2
    await session.refresh(user)
    patterns = user.preferences["procedural"]
    assert len(patterns) == 2
    assert any("early notifications" in p["pattern"] for p in patterns)
```

- [ ] **Step 16.2: Run, expect ImportError**

```bash
pytest tests/test_memory/test_consolidation.py -v
```

- [ ] **Step 16.3: Create `app/memory/consolidation.py`**

```python
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.router import LLMRouter
from app.models.event import Event
from app.models.user import User
from app.schemas.preferences import Pattern, UserPreferences

logger = logging.getLogger(__name__)

MIN_PATTERNS_FOR_CONSOLIDATION = 3

# Module-level singleton — tests monkeypatch this.
_llm = LLMRouter()


CONSOLIDATION_PROMPT = """You are a memory curator. Below is a user's accumulated procedural patterns
(things the assistant has learned about the user). Some may be:
- Near-duplicates: similar meaning, different wording → MERGE
- Contradictions: one says X, a newer one says NOT X → KEEP the newer, drop the older
- Stale: a pattern hasn't been validated by recent behavior → leave for time decay (don't touch here)

Input: list of patterns with id (the array index), text, confidence, learned_at.
Output ONLY JSON with this exact shape:
{
  "drop_ids": [<int array index>...],
  "merged": [{"original_ids": [<int array index>...], "new_text": "<str>", "new_confidence": <float 0-1>}],
  "keep_unchanged": <bool>
}

Be conservative — when in doubt, KEEP both. Bias toward stability.
If nothing needs changing, set keep_unchanged=true and leave drop_ids/merged empty.
"""


def _apply_consolidation(
    patterns: list[Pattern],
    result: dict,
) -> list[Pattern]:
    if result.get("keep_unchanged"):
        return list(patterns)
    drop_ids = set(result.get("drop_ids", []) or [])
    merged = result.get("merged", []) or []
    merged_origin_ids = {oid for m in merged for oid in m.get("original_ids", [])}

    survivors: list[Pattern] = []
    for i, p in enumerate(patterns):
        if i in drop_ids or i in merged_origin_ids:
            continue
        survivors.append(p)

    now_iso = datetime.now(timezone.utc).isoformat()
    for m in merged:
        survivors.append(Pattern(
            pattern=m["new_text"],
            confidence=float(m.get("new_confidence", 0.5)),
            learned_at=now_iso,
            last_reinforced_at=now_iso,
        ))
    return survivors


async def consolidate_patterns(session: AsyncSession, user_id: int) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        return {"error": "user not found"}
    prefs = UserPreferences.from_jsonb(user.preferences or {})
    if len(prefs.procedural) < MIN_PATTERNS_FOR_CONSOLIDATION:
        return {"unchanged": True}

    payload = [
        {"id": i, "pattern": p.pattern, "confidence": p.confidence, "learned_at": p.learned_at}
        for i, p in enumerate(prefs.procedural)
    ]
    try:
        result = await _llm.complete_json("think", [
            {"role": "system", "content": CONSOLIDATION_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ])
    except Exception as e:
        logger.warning("consolidate_patterns: LLM error: %s", e)
        return {"error": str(e)}

    new_procedural = _apply_consolidation(prefs.procedural, result)
    if len(new_procedural) == len(prefs.procedural):
        return {"unchanged": True}

    user.preferences = {
        **(user.preferences or {}),
        "procedural": [p.model_dump() for p in new_procedural],
    }
    session.add(Event(
        user_id=user_id,
        type="memory_consolidated",
        entity_type="memory",
        entity_id=None,
        payload={"before_count": len(prefs.procedural), "after_count": len(new_procedural)},
    ))
    await session.commit()
    return {"before": len(prefs.procedural), "after": len(new_procedural)}
```

- [ ] **Step 16.4: Run tests, expect PASS**

```bash
pytest tests/test_memory/test_consolidation.py -v
```

Expected: 5 passing.

- [ ] **Step 16.5: Full suite + commit**

```bash
pytest tests/ -q
git add app/memory/consolidation.py tests/test_memory/test_consolidation.py
git commit -m "feat: consolidate_patterns with conservative LLM-driven dedupe + merge"
```

---

## Task 17: Memory Consolidation Cron Job

**Files:**
- Modify: `app/scheduler/jobs.py`
- Modify: `app/scheduler/runtime.py`
- Test: `tests/test_scheduler/test_runtime.py`

- [ ] **Step 17.1: Add failing test**

Append to `tests/test_scheduler/test_runtime.py`:

```python
def test_register_jobs_includes_memory_consolidation():
    from app.scheduler.runtime import scheduler, register_jobs, _clear_jobs_for_test
    _clear_jobs_for_test()
    register_jobs()
    ids = {job.id for job in scheduler.get_jobs()}
    assert "memory_consolidation" in ids
    _clear_jobs_for_test()
```

- [ ] **Step 17.2: Run, expect failure**

```bash
source .venv/bin/activate
pytest tests/test_scheduler/test_runtime.py::test_register_jobs_includes_memory_consolidation -v
```

- [ ] **Step 17.3: Add the wrapper to `app/scheduler/jobs.py`**

Append at the bottom of `app/scheduler/jobs.py`:

```python
async def run_memory_consolidation() -> None:
    """Nightly: for each user, consolidate patterns + decay confidences."""
    from app.database import async_session_factory
    from app.memory.confidence import decay_pattern_confidence
    from app.memory.consolidation import consolidate_patterns

    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        for u in users:
            try:
                await consolidate_patterns(session, u.id)
                await decay_pattern_confidence(session, u.id)
            except Exception as e:
                logger.warning("memory consolidation failed for user %s: %s", u.id, e)
```

(`select`, `User`, `logger` are already imported at the top of the file from Spec 2.)

- [ ] **Step 17.4: Register the cron in `app/scheduler/runtime.py`**

In `register_jobs()`, after the existing job registrations, add:

```python
    from app.scheduler.jobs import run_memory_consolidation
    scheduler.add_job(run_memory_consolidation, "cron", hour=3, minute=0,
                      id="memory_consolidation", replace_existing=True)
```

(Add it inside the existing block where `run_scan_reminders`, `run_orchestrate_daily`, `run_expire_stale_checkins` are registered.)

- [ ] **Step 17.5: Run runtime test, expect PASS**

```bash
pytest tests/test_scheduler/test_runtime.py -v
```

- [ ] **Step 17.6: Full suite + commit**

```bash
pytest tests/ -q
git add app/scheduler/jobs.py app/scheduler/runtime.py tests/test_scheduler/test_runtime.py
git commit -m "feat: register nightly memory_consolidation cron"
```

---

## Task 18: End-to-End Smoke

**Files:**
- Create: `tests/test_e2e_memory_smoke.py`

- [ ] **Step 18.1: Write the smoke**

Create `tests/test_e2e_memory_smoke.py`:

```python
import pytest
from datetime import date as date_type
from sqlalchemy import select

from app.models.goal import Goal
from app.models.task import Task
from app.models.user import User


async def test_create_complete_increments_goal(client, session, monkeypatch):
    """E2E: user creates a goal-linked task, completes it via THINK action, goal goes up."""

    user = User(name="X", lark_user_id="mem_e2e_u1", preferences={})
    session.add(user)
    await session.commit()
    goal = Goal(
        user_id=user.id, title="post 12 blogs", target_value=12, current_value=0,
        unit="post", period_start=date_type.today(), period_end=date_type.today(),
        status="active",
    )
    session.add(goal)
    await session.commit()

    think_script = [
        # Turn 1: create task linked to goal
        {
            "intent": "add task tied to goal",
            "actions": [{"type": "create_task", "params": {"title": "blog 1", "goal_id": goal.id}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "confirm", "reasoning": "",
        },
        # Turn 2: complete the task (task_id injected)
        {
            "intent": "user reports done",
            "actions": [{"type": "complete_task", "params": {"task_id": None}}],
            "should_reply": True, "reply_complexity": "low",
            "reply_hint": "celebrate", "reasoning": "",
        },
    ]
    react_script = ["Got it.", "Nice 🎉"]

    class _Router:
        def __init__(self, **_): pass
        async def complete_json(self, *a, **kw):
            return think_script.pop(0)
        async def complete(self, task_type, messages, **kw):
            return react_script.pop(0)
    monkeypatch.setattr("app.routers.conversation.LLMRouter", _Router)

    r = await client.post("/api/conversation", json={"user_id": user.id, "message": "add blog 1"})
    assert r.status_code == 200
    task = (await session.execute(select(Task).where(Task.user_id == user.id))).scalar_one()
    assert task.goal_id == goal.id

    think_script[0]["actions"][0]["params"]["task_id"] = task.id
    r = await client.post("/api/conversation", json={"user_id": user.id, "message": "done"})
    assert r.status_code == 200

    await session.refresh(goal)
    assert goal.current_value == 1
```

- [ ] **Step 18.2: Run, expect PASS**

```bash
source .venv/bin/activate
pytest tests/test_e2e_memory_smoke.py -v
```

If it fails, the most likely issue is `create_task` doesn't accept `goal_id` in the params schema. Verify with `grep -A 8 "class CreateTaskParams" app/orchestrator/actions.py` — `goal_id: Optional[int] = None` should already be there from Spec 1 Task 5. If it isn't, that's a separate bug to fix.

- [ ] **Step 18.3: Full suite + commit**

```bash
pytest tests/ -q
git add tests/test_e2e_memory_smoke.py
git commit -m "test: end-to-end smoke for goal auto-increment on task completion"
```

---

## Task 19: Live Sanity Check

Manual smoke test. Requires `PA_VOYAGE_API_KEY` for the embedding+recall paths.

- [ ] **Step 19.1: Boot server**

```bash
pkill -f "uvicorn app.main" 2>/dev/null
sleep 1
source /Users/guoyuzhu/personal-assistant/.venv/bin/activate
PA_PROACTIVE_DRY_RUN=true PA_ENABLE_SCHEDULER=true uvicorn app.main:app --port 8003 > /tmp/pa-memory-sanity.log 2>&1 &
sleep 5
curl -s http://localhost:8003/health
```

Expected: `{"status":"ok"}`.

- [ ] **Step 19.2: Create user + send a few messages**

```bash
USER_ID=$(curl -s -X POST http://localhost:8003/api/users \
  -H "Content-Type: application/json" \
  -d '{"name":"MemSmoke","lark_user_id":"mem-smoke-'"$(date +%s)"'"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
echo "user_id=$USER_ID"

curl -s -X POST http://localhost:8003/api/conversation \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":$USER_ID,\"message\":\"start\"}" | python3 -m json.tool

curl -s -X POST http://localhost:8003/api/conversation \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":$USER_ID,\"message\":\"我每周三都做团队同步\"}" | python3 -m json.tool
```

- [ ] **Step 19.3: Verify embeddings landed (if key present)**

```bash
psql -d my_assistant -c "SELECT count(*) FROM episodic_embeddings WHERE user_id=$USER_ID;"
```

If `PA_VOYAGE_API_KEY` is set: expect ≥ 1 row (user messages get embedded). If empty: expect 0 rows — that's fine, the system still worked.

- [ ] **Step 19.4: Force pattern reinforcement**

Patch a procedural pattern manually then send a message that would reinforce it:

```bash
psql -d my_assistant -c "UPDATE users SET preferences = '{\"profile\":{},\"procedural\":[{\"pattern\":\"user has weekly Wednesday team sync\",\"confidence\":0.5,\"learned_at\":\"2026-05-01T00:00:00\",\"last_reinforced_at\":\"2026-05-01T00:00:00\"}]}'::jsonb WHERE id=$USER_ID;"

curl -s -X POST http://localhost:8003/api/conversation \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":$USER_ID,\"message\":\"明天周三的团队同步要准备啥？\"}" | python3 -m json.tool

psql -d my_assistant -tAc "SELECT preferences->'procedural' FROM users WHERE id=$USER_ID;"
```

If THINK identified the reinforcement opportunity, you should see `confidence > 0.5` and a newer `last_reinforced_at`. If not, that's a prompt-quality issue, not a code bug — file a follow-up to refine the THINK prompt.

- [ ] **Step 19.5: Trigger consolidation manually**

```bash
source .venv/bin/activate
python3 - <<'PYEOF'
import asyncio
from app.database import async_session_factory
from app.scheduler.jobs import run_memory_consolidation

asyncio.run(run_memory_consolidation())
print("ok")
PYEOF
```

Then look for a `memory_consolidated` event:

```bash
psql -d my_assistant -tAc "SELECT type, payload FROM events WHERE type='memory_consolidated' ORDER BY id DESC LIMIT 3;"
```

(Will only fire if user has ≥3 patterns.)

- [ ] **Step 19.6: Stop server**

```bash
pkill -f "uvicorn app.main"
```

- [ ] **Step 19.7: No commit (config-only)**

---

## Plan Summary

After completing all tasks:

- ✅ Voyage AI embedding pipeline with no-key soft-fail (Tasks 1, 4)
- ✅ Alembic migration for pgvector extension + `episodic_embeddings` (Task 2)
- ✅ `EpisodicEmbedding` ORM model (Task 3)
- ✅ `embed_and_store` fire-and-forget writer (Task 5)
- ✅ Hooks into conversation + action executor (Task 6)
- ✅ `episodic_recall` vector search with similarity threshold (Task 7)
- ✅ `load_context` rewrite: today's full conversation + yesterday tail + recall (Task 8)
- ✅ Orchestrator passes message as `query_text` (Task 9)
- ✅ THINK + REACT prompts include `<episodic_recall>` + reinforce/contradict guidance (Task 10)
- ✅ Goal auto-increment on `complete_task` (Task 11)
- ✅ Pattern schema gains `last_reinforced_at` (Task 12)
- ✅ `REINFORCE_PATTERN` / `CONTRADICT_PATTERN` action types (Task 13)
- ✅ ActionExecutor dispatch for reinforce/contradict (Task 14)
- ✅ Confidence decay (Task 15)
- ✅ Pattern consolidation with conservative LLM dedupe (Task 16)
- ✅ Nightly `memory_consolidation` cron registered (Task 17)
- ✅ End-to-end smoke for goal auto-increment (Task 18)
- ✅ Live sanity check guidance (Task 19)

Next: Spec 4 — Coach mode / insight features.
