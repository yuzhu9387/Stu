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
