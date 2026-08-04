from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.feedback.models import FeedbackEventRecord
from recipe_agent.domain.feedback.repository import SqlFeedbackRepository
from recipe_agent.domain.identity.models import Account, FamilyMembership, Household
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.recipes.contracts import RecipeCandidate
from recipe_agent.domain.recipes.models import RawInput
from recipe_agent.domain.recipes.repository import (
    RawInputNotFoundError,
    RawInputRepository,
    RecipeNotFoundError,
    RecipeRepository,
)


@pytest.mark.asyncio
async def test_family_reads_and_private_reads_apply_distinct_scope_rules(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        alice = Account(email="alice@example.com")
        bob = Account(email="bob@example.com")
        outsider = Account(email="outsider@example.com")
        session.add_all([alice, bob, outsider])
        await session.flush()
        family = Household(owner_account_id=alice.id)
        other = Household(owner_account_id=outsider.id)
        session.add_all([family, other])
        await session.flush()
        session.add_all(
            [
                FamilyMembership(account_id=alice.id, household_id=family.id, role="owner"),
                FamilyMembership(account_id=bob.id, household_id=family.id, role="member"),
                FamilyMembership(account_id=outsider.id, household_id=other.id, role="owner"),
            ]
        )
        await session.commit()

    recipes = RecipeRepository(session_factory)
    bob_recipe = await recipes.create(
        bob.id,
        family.id,
        RecipeCandidate(name="Shared", ingredients=(), steps=()),
    )
    outsider_recipe = await recipes.create(
        outsider.id, other.id, RecipeCandidate(name="Hidden", ingredients=(), steps=())
    )
    async with session_factory() as session:
        bob_import = RawInput(
            owner_account_id=bob.id,
            household_id=family.id,
            kind="text",
            raw_text="private",
        )
        session.add(bob_import)
        await session.commit()

    scope = HouseholdScope(account_id=alice.id, household_id=family.id)
    assert (await recipes.get_for_scope(scope, bob_recipe.id)).owner_account_id == bob.id
    with pytest.raises(RecipeNotFoundError):
        await recipes.get_for_scope(scope, outsider_recipe.id)
    with pytest.raises(RawInputNotFoundError):
        await RawInputRepository(session_factory).get_summary(scope, bob_import.id)


@pytest.mark.asyncio
async def test_owner_query_does_not_trust_account_without_matching_family(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner_account_id = uuid4()
    household_id = uuid4()
    other_household_id = uuid4()
    recipes = RecipeRepository(session_factory)
    await recipes.create(
        owner_account_id,
        household_id,
        RecipeCandidate(name="Tomato", ingredients=(), steps=()),
    )

    rows = await recipes.search_owned(
        HouseholdScope(account_id=owner_account_id, household_id=other_household_id),
        "tomato",
    )

    assert rows == ()


@pytest.mark.asyncio
async def test_private_feedback_read_requires_matching_account_and_family(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account_id = uuid4()
    other_account_id = uuid4()
    household_id = uuid4()
    recipe_id = uuid4()
    async with session_factory() as session:
        session.add_all(
            [
                FeedbackEventRecord(
                    owner_account_id=account_id,
                    household_id=household_id,
                    recipe_id=recipe_id,
                    raw_text="mine",
                ),
                FeedbackEventRecord(
                    owner_account_id=other_account_id,
                    household_id=household_id,
                    recipe_id=recipe_id,
                    raw_text="not mine",
                ),
            ]
        )
        await session.commit()

    rows = await SqlFeedbackRepository(session_factory).list_events(
        HouseholdScope(account_id=account_id, household_id=household_id)
    )

    assert [row.raw_text for row in rows] == ["mine"]
