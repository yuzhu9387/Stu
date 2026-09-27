"""Account sign-up and sign-in, web sessions, and Lark identity linking."""

import asyncio
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.identity.models import (
    Account,
    FamilyMembership,
    Household,
    LarkIdentity,
    McpToken,
)
from recipe_agent.domain.identity.passwords import (
    DUMMY_HASH,
    check_password,
    hash_password,
    verify_password,
)
from recipe_agent.domain.identity.repository import IdentityRepository

# Ten wrong passwords in a row lock the account for fifteen minutes.
MAX_FAILED_SIGN_INS = 10
LOCKOUT = timedelta(minutes=15)
# MCP access tokens: a recognisable prefix, a cap per account, and "last used"
# refreshed at most every few minutes rather than on every call.
MCP_TOKEN_PREFIX = "stu_"
MAX_MCP_TOKENS = 10
MCP_TOUCH_INTERVAL = timedelta(minutes=5)


class InvalidTokenError(ValueError):
    """A token is unknown, expired, or already consumed."""


class InvalidCredentialsError(ValueError):
    """The email and password do not match an account."""


class AccountExistsError(ValueError):
    """An account already uses this email."""


class AccountLockedError(ValueError):
    """Too many wrong passwords; the account is locked for a while."""


class IdentityConflictError(ValueError):
    """An identity already has a conflicting family or transport link."""


class PermissionDeniedError(PermissionError):
    """The account does not have permission for an identity operation."""


_RETRYABLE_TRANSACTION_SQLSTATES = frozenset({"40P01", "40001"})


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
class McpTokenView:
    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


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


@dataclass(frozen=True)
class FamilyMemberView:
    owner_account_id: UUID
    owner_display_name: str
    is_owned_by_current_account: bool
    household_id: UUID
    email: str
    role: str


@dataclass(frozen=True)
class LarkBindingView:
    owner_account_id: UUID
    owner_display_name: str
    is_owned_by_current_account: bool
    household_id: UUID
    is_linked: bool


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

    async def register(self, email: str, password: str) -> AuthenticatedIdentity:
        """Anyone may sign up: a new account with its own household."""
        check_password(password)
        normalized_email = email.strip().casefold()
        password_hash = await asyncio.to_thread(hash_password, password)
        now = self._now()
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            if await repository.get_account_by_email(normalized_email) is not None:
                raise AccountExistsError("An account already uses this email")
            account, household = await repository.create_account_and_household(normalized_email)
            account.password_hash = password_hash
            identity = await self._open_session(repository, account, household, now)
            try:
                await session.commit()
            except IntegrityError as error:
                raise AccountExistsError("An account already uses this email") from error
            return identity

    async def sign_in(self, email: str, password: str) -> AuthenticatedIdentity:
        normalized_email = email.strip().casefold()
        now = self._now()
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            account = await repository.get_account_by_email(normalized_email)
            locked_until = account.locked_until if account is not None else None
            if locked_until is not None and not _expired(locked_until, now):
                raise AccountLockedError("Too many attempts")
            stored = account.password_hash if account is not None else None
            matches = await asyncio.to_thread(verify_password, password, stored or DUMMY_HASH)
            if account is None or stored is None:
                raise InvalidCredentialsError("Email or password is incorrect")
            if not matches:
                account.failed_sign_ins += 1
                if account.failed_sign_ins >= MAX_FAILED_SIGN_INS:
                    account.failed_sign_ins = 0
                    account.locked_until = now + LOCKOUT
                await session.commit()
                raise InvalidCredentialsError("Email or password is incorrect")
            account.failed_sign_ins = 0
            account.locked_until = None
            household = await repository.get_household_for_account(account.id)
            if household is None:
                raise RuntimeError("Account has no household")
            identity = await self._open_session(repository, account, household, now)
            await session.commit()
            return identity

    async def _open_session(
        self,
        repository: IdentityRepository,
        account: Account,
        household: Household,
        now: datetime,
    ) -> AuthenticatedIdentity:
        raw_session_token = secrets.token_urlsafe(32)
        await repository.create_web_session(
            account_id=account.id,
            household_id=household.id,
            token_hash=_hash_token(raw_session_token),
            expires_at=now + timedelta(days=30),
        )
        return AuthenticatedIdentity(account, household, raw_session_token)

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

    async def create_mcp_token(self, scope: HouseholdScope, name: str) -> tuple[McpTokenView, str]:
        """A new access token for an AI client; the raw token is returned once."""
        label = name.strip()
        if not 1 <= len(label) <= 80:
            raise ValueError("Name the token in 1-80 characters")
        raw = MCP_TOKEN_PREFIX + secrets.token_urlsafe(32)
        async with self._session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(McpToken)
                .where(McpToken.account_id == scope.account_id)
            )
            if (count or 0) >= MAX_MCP_TOKENS:
                raise ValueError(f"An account can hold {MAX_MCP_TOKENS} tokens; revoke one first")
            record = McpToken(
                account_id=scope.account_id,
                household_id=scope.household_id,
                name=label,
                token_hash=_hash_token(raw),
                created_at=self._now(),
            )
            session.add(record)
            await session.commit()
            return _token_view(record), raw

    async def list_mcp_tokens(self, scope: HouseholdScope) -> list[McpTokenView]:
        async with self._session_factory() as session:
            records = await session.scalars(
                select(McpToken)
                .where(McpToken.account_id == scope.account_id)
                .order_by(McpToken.created_at)
            )
            return [_token_view(record) for record in records]

    async def revoke_mcp_token(self, scope: HouseholdScope, token_id: UUID) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(McpToken).where(
                    McpToken.id == token_id, McpToken.account_id == scope.account_id
                )
            )
            await session.commit()
            return bool(getattr(result, "rowcount", 0))

    async def resolve_mcp_token(self, token: str) -> HouseholdScope | None:
        """The account and household a token acts for, while both still hold."""
        if not token.startswith(MCP_TOKEN_PREFIX):
            return None
        now = self._now()
        async with self._session_factory() as session:
            record = await session.scalar(
                select(McpToken).where(McpToken.token_hash == _hash_token(token))
            )
            if record is None:
                return None
            membership = await IdentityRepository(session).get_membership_for_account(
                record.account_id
            )
            if membership is None or membership.household_id != record.household_id:
                return None
            last = record.last_used_at
            if last is None or _expired(last + MCP_TOUCH_INTERVAL, now):
                record.last_used_at = now
                await session.commit()
            return HouseholdScope(record.account_id, record.household_id)

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

    async def list_family_members(self, scope: HouseholdScope) -> tuple[FamilyMemberView, ...]:
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            rows = await repository.list_household_members(scope.household_id)
            return tuple(
                FamilyMemberView(
                    owner_account_id=account.id,
                    owner_display_name=account.email.partition("@")[0],
                    is_owned_by_current_account=account.id == scope.account_id,
                    household_id=membership.household_id,
                    email=account.email,
                    role=membership.role,
                )
                for account, membership in rows
            )

    async def get_lark_binding(self, scope: HouseholdScope) -> LarkBindingView:
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            account = await repository.get_household_account(scope, scope.account_id)
            identity = await repository.get_lark_identity_by_account(scope.account_id)
            return LarkBindingView(
                owner_account_id=account.id,
                owner_display_name=account.email.partition("@")[0],
                is_owned_by_current_account=True,
                household_id=scope.household_id,
                is_linked=identity is not None,
            )

    async def create_family_invite(self, scope: HouseholdScope) -> ExpiringCodeDelivery:
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

    async def accept_family_invite(self, scope: HouseholdScope, code: str) -> FamilyMembership:
        now = self._now()
        async with self._session_factory() as session:
            repository = IdentityRepository(session)
            try:
                code_hash = _hash_token(code)
                candidate = await repository.get_family_invite(code_hash)
                if (
                    candidate is None
                    or candidate.consumed_at is not None
                    or _expired(candidate.expires_at, now)
                ):
                    raise InvalidTokenError("Family invite is invalid or expired")
                expected_household_ids = {
                    scope.household_id,
                    candidate.household_id,
                }
                locked_households = await repository.lock_households(tuple(expected_household_ids))
                if {household.id for household in locked_households} != expected_household_ids:
                    raise IdentityConflictError("Family invite could not be accepted")
                source_household = next(
                    household
                    for household in locked_households
                    if household.id == scope.household_id
                )
                invite = await repository.consume_family_invite(
                    code_hash=code_hash, account_id=scope.account_id, now=now
                )
                if invite is None:
                    raise InvalidTokenError("Family invite is invalid or expired")
                membership = await repository.lock_membership_for_account(scope.account_id)
                if membership is None or membership.household_id != scope.household_id:
                    raise InvalidTokenError("Authenticated family scope is no longer valid")
                is_empty_singleton = (
                    membership.role == "owner"
                    and source_household.owner_account_id == scope.account_id
                    and await repository.household_membership_count(scope.household_id) == 1
                    and not await repository.household_has_business_records(scope.household_id)
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
                raise IdentityConflictError("Family invite could not be accepted") from error
            except DBAPIError as error:
                await session.rollback()
                if _is_retryable_transaction_error(error):
                    raise IdentityConflictError("Family invite could not be accepted") from error
                raise

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
                link = await repository.consume_lark_link_code(code_hash=_hash_token(code), now=now)
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

    async def _consume_lark_code_after_conflict(self, code: str, now: datetime) -> None:
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


def _token_view(record: McpToken) -> McpTokenView:
    return McpTokenView(record.id, record.name, record.created_at, record.last_used_at)


def _expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now


def _is_retryable_transaction_error(error: DBAPIError) -> bool:
    sqlstate = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
    return sqlstate in _RETRYABLE_TRANSACTION_SQLSTATES
