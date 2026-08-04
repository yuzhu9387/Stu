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
