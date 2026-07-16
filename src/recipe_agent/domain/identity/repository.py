"""Identity persistence with household-scoped reads."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from recipe_agent.domain.identity.models import (
    Account,
    FamilyInvite,
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

    async def get_account(self, account_id: UUID) -> Account | None:
        return await self._session.get(Account, account_id)

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
            select(Household)
            .join(FamilyMembership, FamilyMembership.household_id == Household.id)
            .where(FamilyMembership.account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_membership_for_account(self, account_id: UUID) -> FamilyMembership | None:
        result = await self._session.execute(
            select(FamilyMembership).where(FamilyMembership.account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def create_family_invite(
        self,
        *,
        household_id: UUID,
        created_by_account_id: UUID,
        code_hash: str,
        expires_at: datetime,
    ) -> FamilyInvite:
        invite = FamilyInvite(
            household_id=household_id,
            created_by_account_id=created_by_account_id,
            code_hash=code_hash,
            expires_at=expires_at,
        )
        self._session.add(invite)
        await self._session.flush()
        return invite

    async def consume_family_invite(
        self, *, code_hash: str, account_id: UUID, now: datetime
    ) -> FamilyInvite | None:
        result = await self._session.execute(
            update(FamilyInvite)
            .where(
                FamilyInvite.code_hash == code_hash,
                FamilyInvite.consumed_at.is_(None),
                FamilyInvite.expires_at > now,
            )
            .values(consumed_at=now, consumed_by_account_id=account_id)
            .returning(FamilyInvite)
        )
        return result.scalar_one_or_none()

    async def create_membership(
        self, *, account_id: UUID, household_id: UUID, role: str
    ) -> FamilyMembership:
        membership = FamilyMembership(
            account_id=account_id,
            household_id=household_id,
            role=role,
        )
        self._session.add(membership)
        await self._session.flush()
        return membership

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

    async def get_web_session(self, token_hash: str) -> WebSession | None:
        result = await self._session.execute(
            select(WebSession).where(WebSession.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def delete_web_session(self, token_hash: str) -> None:
        await self._session.execute(
            delete(WebSession).where(WebSession.token_hash == token_hash)
        )

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

    async def consume_lark_link_code(
        self, *, code_hash: str, now: datetime
    ) -> LarkLinkCode | None:
        result = await self._session.execute(
            update(LarkLinkCode)
            .where(
                LarkLinkCode.code_hash == code_hash,
                LarkLinkCode.consumed_at.is_(None),
                LarkLinkCode.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(LarkLinkCode)
        )
        return result.scalar_one_or_none()

    async def create_lark_identity(self, account_id: UUID, open_id: str) -> LarkIdentity:
        identity = LarkIdentity(account_id=account_id, open_id=open_id)
        self._session.add(identity)
        await self._session.flush()
        return identity

    async def get_lark_identity_by_open_id(self, open_id: str) -> LarkIdentity | None:
        result = await self._session.execute(
            select(LarkIdentity).where(LarkIdentity.open_id == open_id)
        )
        return result.scalar_one_or_none()

    async def get_lark_identity_by_account(self, account_id: UUID) -> LarkIdentity | None:
        result = await self._session.execute(
            select(LarkIdentity).where(LarkIdentity.account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_household_account(self, scope: object, account_id: UUID) -> Account:
        household_id = getattr(scope, "household_id", None)
        result = await self._session.execute(
            select(Account)
            .where(
                Account.id == account_id,
                or_(
                    exists().where(
                        Household.id == household_id,
                        Household.owner_account_id == account_id,
                    ),
                    exists().where(
                        FamilyMembership.account_id == account_id,
                        FamilyMembership.household_id == household_id,
                    ),
                ),
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise NotFoundError("Account not found in household")
        return account
