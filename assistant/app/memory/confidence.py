from __future__ import annotations
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.preferences import Pattern, UserPreferences

logger = logging.getLogger(__name__)

DAILY_DECAY_RATE = 0.99
MIN_CONFIDENCE = 0.1


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


async def decay_pattern_confidence(session: AsyncSession, user_id: int) -> int:
    """Apply exponential time decay to all patterns. Drop those below MIN_CONFIDENCE.
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
