"""SQL repository for hashed share tokens and immutable snapshots."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.sharing.models import ShareSnapshotRecord
from recipe_agent.domain.sharing.service import ShareRecord


class SqlShareRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, record: ShareRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                ShareSnapshotRecord(
                    token_hash=record.token_hash,
                    snapshot_json=json.dumps(record.snapshot, separators=(",", ":")),
                    expires_at=record.expires_at,
                    revoked_at=record.revoked_at,
                )
            )
            await session.commit()

    async def find_by_hash(self, token_hash: str) -> ShareRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ShareSnapshotRecord).where(
                    ShareSnapshotRecord.token_hash == token_hash
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            expires_at = record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            revoked_at = record.revoked_at
            if revoked_at is not None and revoked_at.tzinfo is None:
                revoked_at = revoked_at.replace(tzinfo=UTC)
            return ShareRecord(
                token_hash=record.token_hash,
                snapshot=json.loads(record.snapshot_json),
                expires_at=expires_at,
                revoked_at=revoked_at,
            )

    async def revoke(self, token_hash: str) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ShareSnapshotRecord).where(
                    ShareSnapshotRecord.token_hash == token_hash
                )
            )
            record = result.scalar_one_or_none()
            if record is not None:
                record.revoked_at = datetime.now(UTC)
                await session.commit()
