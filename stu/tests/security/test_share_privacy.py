from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from recipe_agent.domain.sharing.repository import SqlShareRepository
from recipe_agent.domain.sharing.service import (
    InvalidShareTokenError,
    ShareRecord,
    ShareService,
)


class MemoryShareRepository:
    def __init__(self) -> None:
        self.records: dict[str, object] = {}

    async def save(self, record: object) -> None:
        self.records[record.token_hash] = record

    async def find_by_hash(self, token_hash: str):
        return self.records.get(token_hash)

    async def revoke(self, token_hash: str) -> None:
        self.records[token_hash].revoked_at = datetime.now(UTC)


@pytest.mark.asyncio
async def test_share_token_is_hashed_resolvable_and_revocable() -> None:
    repository = MemoryShareRepository()
    service = ShareService(repository=repository)
    snapshot = {"id": str(uuid4()), "name": "Soup", "ingredients": [], "steps": []}

    owner_account_id = uuid4()
    household_id = uuid4()
    delivery = await service.create_snapshot(
        snapshot,
        owner_account_id=owner_account_id,
        household_id=household_id,
        expires_in=timedelta(hours=1),
    )

    assert delivery.token not in str(repository.records)
    resolved = await service.resolve_token(delivery.token)
    assert resolved.snapshot["name"] == "Soup"
    assert resolved.owner_account_id == owner_account_id
    assert resolved.household_id == household_id
    await service.revoke(delivery.token)
    with pytest.raises(InvalidShareTokenError):
        await service.resolve_token(delivery.token)


@pytest.mark.asyncio
async def test_sql_repository_rejects_new_share_without_authenticated_ownership(
    session_factory,
) -> None:
    with pytest.raises(ValueError, match="ownership"):
        await SqlShareRepository(session_factory).save(
            ShareRecord(
                token_hash="z" * 64,
                snapshot={},
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
