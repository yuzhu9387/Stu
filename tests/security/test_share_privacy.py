from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from recipe_agent.domain.sharing.service import InvalidShareTokenError, ShareService


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

    delivery = await service.create_snapshot(snapshot, expires_in=timedelta(hours=1))

    assert delivery.token not in str(repository.records)
    assert (await service.resolve_token(delivery.token)).snapshot["name"] == "Soup"
    await service.revoke(delivery.token)
    with pytest.raises(InvalidShareTokenError):
        await service.resolve_token(delivery.token)
