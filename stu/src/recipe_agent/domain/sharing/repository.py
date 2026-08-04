"""SQL repository for hashed share tokens and immutable snapshots."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.conversation.receipts import add_receipt, receipt_result
from recipe_agent.domain.identity.models import Account
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.sharing.models import ShareSnapshotRecord
from recipe_agent.domain.sharing.service import ShareRecord, ShareSummary


class SqlShareRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, record: ShareRecord) -> ShareRecord:
        if record.owner_account_id is None or record.household_id is None:
            raise ValueError("New shares require authenticated ownership")
        async with self._session_factory() as session:
            if record.source_action_id is not None:
                existing = await receipt_result(session, record.source_action_id, "create_share")
                if existing is not None:
                    stored = await session.scalar(
                        select(ShareSnapshotRecord).where(
                            ShareSnapshotRecord.source_action_id == record.source_action_id
                        )
                    )
                    if stored is None:
                        raise RuntimeError("Share action receipt has no snapshot")
                    return self._record(stored)
            session.add(
                ShareSnapshotRecord(
                    id=record.id,
                    owner_account_id=record.owner_account_id,
                    household_id=record.household_id,
                    token_hash=record.token_hash,
                    snapshot_json=json.dumps(record.snapshot, separators=(",", ":")),
                    expires_at=record.expires_at,
                    revoked_at=record.revoked_at,
                    source_action_id=record.source_action_id,
                )
            )
            if record.source_action_id is not None:
                add_receipt(
                    session,
                    record.source_action_id,
                    "create_share",
                    {
                        "share_id": str(record.id),
                        "expires_at": record.expires_at.isoformat(),
                    },
                )
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                if record.source_action_id is None:
                    raise
                existing = await receipt_result(session, record.source_action_id, "create_share")
                if existing is None:
                    raise
                stored = await session.scalar(
                    select(ShareSnapshotRecord).where(
                        ShareSnapshotRecord.source_action_id == record.source_action_id
                    )
                )
                if stored is None:
                    raise RuntimeError("Share action receipt has no snapshot") from error
                return self._record(stored)
            return record

    async def find_by_hash(self, token_hash: str) -> ShareRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ShareSnapshotRecord).where(ShareSnapshotRecord.token_hash == token_hash)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            return self._record(record)

    async def find_by_source_action(self, action_id: UUID) -> ShareRecord | None:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(ShareSnapshotRecord).where(ShareSnapshotRecord.source_action_id == action_id)
            )
            return None if record is None else self._record(record)

    async def list_for_scope(self, scope: HouseholdScope) -> tuple[ShareSummary, ...]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ShareSnapshotRecord, Account.email)
                .join(Account, Account.id == ShareSnapshotRecord.owner_account_id)
                .where(
                    ShareSnapshotRecord.owner_account_id == scope.account_id,
                    ShareSnapshotRecord.household_id == scope.household_id,
                )
                .order_by(ShareSnapshotRecord.expires_at.desc(), ShareSnapshotRecord.id)
                .limit(100)
            )
            return tuple(
                ShareSummary(
                    id=record.id,
                    owner_account_id=record.owner_account_id,
                    owner_display_name=email.partition("@")[0],
                    is_owned_by_current_account=True,
                    household_id=record.household_id,
                    expires_at=_aware(record.expires_at),
                    revoked_at=_aware(record.revoked_at) if record.revoked_at else None,
                )
                for record, email in result.all()
                if record.owner_account_id is not None and record.household_id is not None
            )

    async def get_for_scope(self, scope: HouseholdScope, share_id: UUID) -> ShareSummary | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ShareSnapshotRecord, Account.email)
                .join(Account, Account.id == ShareSnapshotRecord.owner_account_id)
                .where(
                    ShareSnapshotRecord.id == share_id,
                    ShareSnapshotRecord.owner_account_id == scope.account_id,
                    ShareSnapshotRecord.household_id == scope.household_id,
                )
            )
            row = result.one_or_none()
            if row is None:
                return None
            record, email = row
            return ShareSummary(
                id=record.id,
                owner_account_id=record.owner_account_id,
                owner_display_name=email.partition("@")[0],
                is_owned_by_current_account=True,
                household_id=record.household_id,
                expires_at=_aware(record.expires_at),
                revoked_at=_aware(record.revoked_at) if record.revoked_at else None,
            )

    async def revoke(self, token_hash: str) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ShareSnapshotRecord).where(ShareSnapshotRecord.token_hash == token_hash)
            )
            record = result.scalar_one_or_none()
            if record is not None:
                record.revoked_at = datetime.now(UTC)
                await session.commit()

    @staticmethod
    def _record(record: ShareSnapshotRecord) -> ShareRecord:
        return ShareRecord(
            id=record.id,
            token_hash=record.token_hash,
            snapshot=json.loads(record.snapshot_json),
            expires_at=_aware(record.expires_at),
            owner_account_id=record.owner_account_id,
            household_id=record.household_id,
            revoked_at=_aware(record.revoked_at) if record.revoked_at else None,
            source_action_id=record.source_action_id,
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
