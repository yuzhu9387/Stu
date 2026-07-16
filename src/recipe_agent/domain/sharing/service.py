"""Hashed, expiring, revocable share tokens."""

import hashlib
import hmac
import secrets
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from recipe_agent.domain.common.types import JsonValue


class InvalidShareTokenError(ValueError):
    """The share token is unknown, expired, or revoked."""


@dataclass
class ShareRecord:
    token_hash: str
    snapshot: dict[str, JsonValue]
    expires_at: datetime
    id: UUID = dataclass_field(default_factory=uuid4)
    owner_account_id: UUID | None = None
    household_id: UUID | None = None
    revoked_at: datetime | None = None
    source_action_id: UUID | None = None


@dataclass(frozen=True)
class ShareDelivery:
    token: str
    share_id: UUID | None = None
    expires_at: datetime | None = None


class ShareSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    owner_account_id: UUID
    owner_display_name: str
    is_owned_by_current_account: bool
    household_id: UUID
    expires_at: datetime
    revoked_at: datetime | None


class ShareRepository(Protocol):
    async def save(self, record: ShareRecord) -> ShareRecord | None: ...

    async def find_by_hash(self, token_hash: str) -> ShareRecord | None: ...

    async def find_by_source_action(self, action_id: UUID) -> ShareRecord | None: ...

    async def revoke(self, token_hash: str) -> None: ...


class ShareService:
    def __init__(
        self,
        *,
        repository: ShareRepository,
        action_token_key: str | None = None,
    ) -> None:
        self._repository = repository
        self._action_token_key = (
            action_token_key.encode("utf-8") if action_token_key is not None else None
        )

    async def create_snapshot(
        self,
        snapshot: dict[str, JsonValue],
        *,
        owner_account_id: UUID,
        household_id: UUID,
        expires_in: timedelta,
        source_action_id: UUID | None = None,
    ) -> ShareDelivery:
        token = (
            self._action_token(source_action_id)
            if source_action_id is not None
            else secrets.token_urlsafe(32)
        )
        record = ShareRecord(
            token_hash=_hash_token(token),
            snapshot=snapshot,
            expires_at=datetime.now(UTC) + expires_in,
            owner_account_id=owner_account_id,
            household_id=household_id,
            source_action_id=source_action_id,
        )
        persisted = await self._repository.save(record) or record
        return ShareDelivery(
            token=token,
            share_id=persisted.id,
            expires_at=persisted.expires_at,
        )

    async def delivery_for_action(
        self,
        action_id: UUID,
        *,
        owner_account_id: UUID,
        household_id: UUID,
    ) -> ShareDelivery:
        record = await self._repository.find_by_source_action(action_id)
        if (
            record is None
            or record.owner_account_id != owner_account_id
            or record.household_id != household_id
        ):
            raise InvalidShareTokenError("Share delivery not found")
        token = self._action_token(action_id)
        if not hmac.compare_digest(record.token_hash, _hash_token(token)):
            raise InvalidShareTokenError("Share delivery is invalid")
        return ShareDelivery(token=token, share_id=record.id, expires_at=record.expires_at)

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

    def _action_token(self, action_id: UUID) -> str:
        if self._action_token_key is None:
            raise RuntimeError("Action share token key is not configured")
        digest = hmac.new(
            self._action_token_key,
            f"suggested-share:{action_id}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
