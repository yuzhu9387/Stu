"""Passwordless account and Lark identity linking services."""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.identity.models import (
    Account,
    FamilyMembership,
    Household,
    LarkIdentity,
)
from recipe_agent.domain.identity.repository import IdentityRepository


class InvalidTokenError(ValueError):
    """A token is unknown, expired, or already consumed."""


class IdentityConflictError(ValueError):
    """An identity already has a conflicting family or transport link."""


class PermissionDeniedError(PermissionError):
    """The account does not have permission for an identity operation."""


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
class ExpiringCodeDelivery:
    code: str
    expires_at: datetime


@dataclass(frozen=True)
class AuthenticatedIdentity:
    account: Account
    household: Household
    session_token: str


@dataclass(frozen=True)
class SessionIdentity:
    account: Account
    scope: HouseholdScope
    role: str


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

    async def resolve_web_session(self, token: str) -> HouseholdScope | None:
        now = self._now()
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            web_session = await repository.get_web_session(_hash_token(token))
            if web_session is None or _expired(web_session.expires_at, now):
                return None
            membership = await repository.get_membership_for_account(web_session.account_id)
            if membership is None or membership.household_id != web_session.household_id:
                return None
            return HouseholdScope(web_session.account_id, web_session.household_id)

    async def delete_web_session(self, token: str) -> None:
        async with self._session_factory() as session:
            await IdentityRepository(session).delete_web_session(_hash_token(token))
            await session.commit()

    async def get_session_identity(self, scope: HouseholdScope) -> SessionIdentity:
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            account = await repository.get_account(scope.account_id)
            membership = await repository.get_membership_for_account(scope.account_id)
            if (
                account is None
                or membership is None
                or membership.household_id != scope.household_id
            ):
                raise InvalidTokenError("Session scope is no longer valid")
            return SessionIdentity(account, scope, membership.role)

    async def get_family_membership(self, scope: HouseholdScope) -> FamilyMembership:
        async with self._session_factory() as session:
            membership = await IdentityRepository(session).get_membership_for_account(
                scope.account_id
            )
            if membership is None or membership.household_id != scope.household_id:
                raise InvalidTokenError("Family membership is no longer valid")
            return membership

    async def create_family_invite(
        self, scope: HouseholdScope
    ) -> ExpiringCodeDelivery:
        now = self._now()
        code = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=10)
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            membership = await repository.get_membership_for_account(scope.account_id)
            if membership is None or membership.household_id != scope.household_id:
                raise InvalidTokenError("Family membership is no longer valid")
            if membership.role != "owner":
                raise PermissionDeniedError("Only a family owner may create an invite")
            await repository.create_family_invite(
                household_id=scope.household_id,
                created_by_account_id=scope.account_id,
                code_hash=_hash_token(code),
                expires_at=expires_at,
            )
            await session.commit()
        return ExpiringCodeDelivery(code, expires_at)

    async def accept_family_invite(
        self, scope: HouseholdScope, code: str
    ) -> FamilyMembership:
        now = self._now()
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            try:
                invite = await repository.consume_family_invite(
                    code_hash=_hash_token(code), account_id=scope.account_id, now=now
                )
                if invite is None:
                    raise InvalidTokenError("Family invite is invalid or expired")
                membership = await repository.lock_membership_for_account(scope.account_id)
                source_household = await repository.lock_household(scope.household_id)
                if (
                    membership is None
                    or membership.household_id != scope.household_id
                    or source_household is None
                ):
                    raise InvalidTokenError("Authenticated family scope is no longer valid")
                is_empty_singleton = (
                    membership.role == "owner"
                    and source_household.owner_account_id == scope.account_id
                    and await repository.household_membership_count(scope.household_id) == 1
                    and not await repository.household_has_business_records(
                        scope.household_id
                    )
                )
                if invite.household_id == scope.household_id or not is_empty_singleton:
                    raise IdentityConflictError("Personal family is not empty")
                await repository.move_membership_to_family(
                    membership=membership,
                    target_household_id=invite.household_id,
                    now=now,
                )
                await session.commit()
                return membership
            except IntegrityError as error:
                await session.rollback()
                raise IdentityConflictError(
                    "Family invite could not be accepted"
                ) from error

    async def create_lark_link_code(self, account_id: UUID) -> LinkCodeDelivery:
        code = secrets.token_urlsafe(32)
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            if await repository.get_account(account_id) is None:
                raise InvalidTokenError("Account does not exist")
            if await repository.get_lark_identity_by_account(account_id) is not None:
                raise IdentityConflictError("Account already has a Lark identity")
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
            try:
                link = await repository.consume_lark_link_code(
                    code_hash=_hash_token(code), now=now
                )
                if link is None:
                    raise InvalidTokenError("Lark link code is invalid or expired")
                if (
                    await repository.get_lark_identity_by_account(link.account_id) is not None
                    or await repository.get_lark_identity_by_open_id(open_id) is not None
                ):
                    await session.commit()
                    raise IdentityConflictError("Lark identity is already linked")
                identity = await repository.create_lark_identity(link.account_id, open_id)
                await session.commit()
                return identity
            except IntegrityError as error:
                await session.rollback()
                await self._consume_lark_code_after_conflict(code, now)
                raise IdentityConflictError("Lark identity is already linked") from error

    async def _consume_lark_code_after_conflict(
        self, code: str, now: datetime
    ) -> None:
        async with self._session_factory() as session:
            await IdentityRepository(session).consume_lark_link_code(
                code_hash=_hash_token(code), now=now
            )
            await session.commit()

    async def resolve_lark_identity(self, open_id: str) -> HouseholdScope | None:
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            identity = await repository.get_lark_identity_by_open_id(open_id)
            if identity is None:
                return None
            membership = await repository.get_membership_for_account(identity.account_id)
            if membership is None:
                return None
            return HouseholdScope(identity.account_id, membership.household_id)


def _expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now
