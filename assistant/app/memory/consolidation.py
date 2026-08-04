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
