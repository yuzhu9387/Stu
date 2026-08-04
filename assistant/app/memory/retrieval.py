from __future__ import annotations
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episodic_embedding import EpisodicEmbedding
from app.services.voyage_client import VoyageClient

logger = logging.getLogger(__name__)

EPISODIC_TOP_K = 3
EPISODIC_SIMILARITY_THRESHOLD = 0.7  # cosine similarity in [-1, 1]; 0.7 ≈ "clearly related"
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
