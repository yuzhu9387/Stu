"""Identity persistence with household-scoped reads."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from recipe_agent.domain.identity.models import (
    Account,
    FamilyMembership,
    Household,
    LarkIdentity,
    LarkLinkCode,
    MagicLink,
    WebSession,
)


class NotFoundError(LookupError):
    """A resource does not exist inside the active household."""


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_magic_link(
        self, *, email: str, token_hash: str, expires_at: datetime
    ) -> MagicLink:
        link = MagicLink(email=email, token_hash=token_hash, expires_at=expires_at)
        self._session.add(link)
        await self._session.flush()
        return link

    async def get_magic_link(self, token_hash: str) -> MagicLink | None:
        result = await self._session.execute(
            select(MagicLink).where(MagicLink.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def get_account_by_email(self, email: str) -> Account | None:
        result = await self._session.execute(select(Account).where(Account.email == email))
        return result.scalar_one_or_none()

    async def create_account_and_household(self, email: str) -> tuple[Account, Household]:
        account = Account(email=email)
        self._session.add(account)
        await self._session.flush()
        household = Household(owner_account_id=account.id)
        self._session.add(household)
        await self._session.flush()
        self._session.add(
            FamilyMembership(
                account_id=account.id,
                household_id=household.id,
                role="owner",
            )
        )
        await self._session.flush()
        return account, household

    async def get_household_for_account(self, account_id: UUID) -> Household | None:
        result = await self._session.execute(
            select(Household).where(Household.owner_account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def create_web_session(
        self,
        *,
        account_id: UUID,
        household_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> WebSession:
        session = WebSession(
            account_id=account_id,
            household_id=household_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(session)
        await self._session.flush()
        return session

    async def create_lark_link_code(
        self, *, account_id: UUID, code_hash: str, expires_at: datetime
    ) -> LarkLinkCode:
        link = LarkLinkCode(
            account_id=account_id,
            code_hash=code_hash,
            expires_at=expires_at,
        )
        self._session.add(link)
        await self._session.flush()
        return link

    async def get_lark_link_code(self, code_hash: str) -> LarkLinkCode | None:
        result = await self._session.execute(
            select(LarkLinkCode).where(LarkLinkCode.code_hash == code_hash)
        )
        return result.scalar_one_or_none()

    async def create_lark_identity(self, account_id: UUID, open_id: str) -> LarkIdentity:
        identity = LarkIdentity(account_id=account_id, open_id=open_id)
        self._session.add(identity)
        await self._session.flush()
        return identity

    async def get_household_account(self, scope: object, account_id: UUID) -> Account:
        household_id = getattr(scope, "household_id", None)
        result = await self._session.execute(
            select(Account)
            .join(Household, Household.owner_account_id == Account.id)
            .where(Account.id == account_id, Household.id == household_id)
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise NotFoundError("Account not found in household")
        return account
