from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.identity.models import Account, Household
from recipe_agent.domain.identity.repository import IdentityRepository, NotFoundError
from recipe_agent.domain.identity.service import HouseholdScope


@pytest.mark.asyncio
async def test_repository_hides_accounts_from_another_household(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first_account = Account(email="first@example.com")
        second_account = Account(email="second@example.com")
        session.add_all([first_account, second_account])
        await session.flush()
        first_household = Household(owner_account_id=first_account.id)
        second_household = Household(owner_account_id=second_account.id)
        session.add_all([first_household, second_household])
        await session.commit()

        repository = IdentityRepository(session)
        scope = HouseholdScope(
            account_id=second_account.id,
            household_id=second_household.id,
        )

        with pytest.raises(NotFoundError):
            await repository.get_household_account(scope, first_account.id)


@pytest.mark.asyncio
async def test_repository_accepts_account_in_current_household(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account = Account(id=uuid4(), email="cook@example.com")
        session.add(account)
        await session.flush()
        household = Household(owner_account_id=account.id)
        session.add(household)
        await session.commit()

        repository = IdentityRepository(session)
        scope = HouseholdScope(account_id=account.id, household_id=household.id)

        assert await repository.get_household_account(scope, account.id) == account
