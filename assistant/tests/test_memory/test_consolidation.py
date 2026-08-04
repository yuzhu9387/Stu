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
            "merged": [{"original_ids": [0, 1], "new_text": "dislikes early notifications",
                        "new_confidence": 0.7}],
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
