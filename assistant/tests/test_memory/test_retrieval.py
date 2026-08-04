import pytest
from unittest.mock import AsyncMock

from app.config import settings
from app.memory.retrieval import (
    EPISODIC_SIMILARITY_THRESHOLD,
    EPISODIC_TOP_K,
    episodic_recall,
)


def test_episodic_top_k_constant():
    assert EPISODIC_TOP_K == 3


def test_episodic_similarity_threshold_constant():
    assert EPISODIC_SIMILARITY_THRESHOLD == 0.7


# Below are sqlite-skipped — they exercise the actual query path.

pg_only = pytest.mark.skipif(
    "sqlite" in settings.test_database_url,
    reason="vector search requires Postgres + pgvector",
)


@pg_only
async def test_episodic_recall_returns_empty_when_query_blank(session):
    result = await episodic_recall(session, user_id=1, query_text="")
    assert result == []


@pg_only
async def test_episodic_recall_returns_empty_when_no_embeddings(session, monkeypatch):
    fake_voyage = AsyncMock()
    fake_voyage.embed = AsyncMock(return_value=[0.5] * 1024)
    monkeypatch.setattr("app.memory.retrieval._voyage", fake_voyage)
    result = await episodic_recall(session, user_id=999, query_text="anything at all")
    assert result == []


async def test_episodic_recall_no_key_returns_empty(session, monkeypatch):
    """No API key path returns [] without raising."""
    fake_voyage = AsyncMock()
    fake_voyage.embed = AsyncMock(return_value=[])  # simulate no key
    monkeypatch.setattr("app.memory.retrieval._voyage", fake_voyage)
    result = await episodic_recall(session, user_id=1, query_text="any query here")
    assert result == []
