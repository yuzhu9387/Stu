import pytest

from app.config import settings

pytestmark = pytest.mark.skipif(
    "sqlite" in settings.test_database_url,
    reason="pgvector Vector type requires Postgres",
)

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
