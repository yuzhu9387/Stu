"""Passwordless account and Lark identity linking services."""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.identity.models import Account, Household, LarkIdentity
from recipe_agent.domain.identity.repository import IdentityRepository


class InvalidTokenError(ValueError):
    """A token is unknown, expired, or already consumed."""


@dataclass(frozen=True)
class HouseholdScope:
    account_id: UUID
    household_id: UUID


@dataclass(frozen=True)
class TokenDelivery:
    token: str


@dataclass(frozen=True)
class LinkCodeDelivery:
    code: str


@dataclass(frozen=True)
class AuthenticatedIdentity:
    account: Account
    household: Household
    session_token: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class IdentityService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._now = now or (lambda: datetime.now(UTC))

    async def request_magic_link(self, email: str) -> TokenDelivery:
        normalized_email = email.strip().casefold()
        token = secrets.token_urlsafe(32)
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            await repository.create_magic_link(
                email=normalized_email,
                token_hash=_hash_token(token),
                expires_at=self._now() + timedelta(minutes=15),
            )
            await session.commit()
        return TokenDelivery(token=token)

    async def consume_magic_link(self, token: str) -> AuthenticatedIdentity:
        now = self._now()
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            link = await repository.get_magic_link(_hash_token(token))
            if link is None or link.consumed_at is not None or _expired(link.expires_at, now):
                raise InvalidTokenError("Magic link is invalid or expired")
            link.consumed_at = now
            account = await repository.get_account_by_email(link.email)
            if account is None:
                account, household = await repository.create_account_and_household(link.email)
            else:
                existing_household = await repository.get_household_for_account(account.id)
                if existing_household is None:
                    raise RuntimeError("Account has no household")
                household = existing_household
            raw_session_token = secrets.token_urlsafe(32)
            await repository.create_web_session(
                account_id=account.id,
                household_id=household.id,
                token_hash=_hash_token(raw_session_token),
                expires_at=now + timedelta(days=30),
            )
            await session.commit()
            return AuthenticatedIdentity(account, household, raw_session_token)

    async def create_lark_link_code(self, account_id: UUID) -> LinkCodeDelivery:
        code = secrets.token_urlsafe(32)
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            await repository.create_lark_link_code(
                account_id=account_id,
                code_hash=_hash_token(code),
                expires_at=self._now() + timedelta(minutes=10),
            )
            await session.commit()
        return LinkCodeDelivery(code=code)

    async def link_lark_identity(self, code: str, open_id: str) -> LarkIdentity:
        now = self._now()
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            link = await repository.get_lark_link_code(_hash_token(code))
            if link is None or link.consumed_at is not None or _expired(link.expires_at, now):
                raise InvalidTokenError("Lark link code is invalid or expired")
            link.consumed_at = now
            identity = await repository.create_lark_identity(link.account_id, open_id)
            await session.commit()
            return identity


def _expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now
