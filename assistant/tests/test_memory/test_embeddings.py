import pytest
from unittest.mock import AsyncMock

from app.memory.embeddings import (
    EMBEDDABLE_EVENT_TYPES,
    MIN_CONTENT_CHARS,
    MAX_CONTENT_CHARS,
    embed_and_store,
)
from app.models.user import User


def test_embeddable_event_types_set():
    assert "feedback_recorded" in EMBEDDABLE_EVENT_TYPES
    assert "pattern_recorded" in EMBEDDABLE_EVENT_TYPES
    assert "profile_updated" in EMBEDDABLE_EVENT_TYPES
    assert "task_completed" in EMBEDDABLE_EVENT_TYPES
    assert "goal_set" in EMBEDDABLE_EVENT_TYPES
    # Excluded types
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
