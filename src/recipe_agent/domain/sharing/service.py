"""Hashed, expiring, revocable share tokens."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from recipe_agent.domain.common.types import JsonValue


class InvalidShareTokenError(ValueError):
    """The share token is unknown, expired, or revoked."""


@dataclass
class ShareRecord:
    token_hash: str
    snapshot: dict[str, JsonValue]
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class ShareDelivery:
    token: str


class ShareRepository(Protocol):
    async def save(self, record: ShareRecord) -> None: ...

    async def find_by_hash(self, token_hash: str) -> ShareRecord | None: ...

    async def revoke(self, token_hash: str) -> None: ...


class ShareService:
    def __init__(self, *, repository: ShareRepository) -> None:
        self._repository = repository

    async def create_snapshot(
        self,
        snapshot: dict[str, JsonValue],
        *,
        expires_in: timedelta,
    ) -> ShareDelivery:
        token = secrets.token_urlsafe(32)
        record = ShareRecord(
            token_hash=_hash_token(token),
            snapshot=snapshot,
            expires_at=datetime.now(UTC) + expires_in,
        )
        await self._repository.save(record)
        return ShareDelivery(token=token)

    async def resolve_token(self, token: str) -> ShareRecord:
        record = await self._repository.find_by_hash(_hash_token(token))
        if (
            record is None
            or record.revoked_at is not None
            or record.expires_at <= datetime.now(UTC)
        ):
            raise InvalidShareTokenError("Share token is invalid or expired")
        return record

    async def revoke(self, token: str) -> None:
        record = await self._repository.find_by_hash(_hash_token(token))
        if record is None:
            raise InvalidShareTokenError("Share token is invalid")
        await self._repository.revoke(record.token_hash)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
