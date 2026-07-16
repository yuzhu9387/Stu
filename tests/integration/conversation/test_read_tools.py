from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.conversation.react import ReadOnlyToolCall
from recipe_agent.domain.conversation.read_tools import ReadOnlyToolRegistry
from recipe_agent.domain.identity.models import Account, FamilyMembership, Household
from recipe_agent.domain.identity.preferences import (
    DietaryPreference,
    SqlDietaryPreferenceRepository,
)
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.planning.repository import SqlPlanRepository
from recipe_agent.domain.recipes.contracts import (
    RecipeCandidate,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
)
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.domain.recommendations.contracts import (
    RecommendationCandidate,
    RecommendationFeatures,
    RecommendationQuery,
    RecommendationSource,
)
from recipe_agent.domain.recommendations.service import RecommendationService


class _NoGeneratedCandidates:
    async def generate(
        self, query: RecommendationQuery, count: int
    ) -> list[RecommendationCandidate]:
        return []


class _FixedCandidates:
    def __init__(self, candidates: list[RecommendationCandidate]) -> None:
        self._candidates = candidates

    async def candidates(self, query: RecommendationQuery) -> list[RecommendationCandidate]:
        return self._candidates


class _UnusedPreviewImport:
    async def preview(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("not used")


class _UnusedPreviewPlanning:
    async def preview_replace_item(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("not used")


async def _family(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Account, Account, Household]:
    async with session_factory() as session:
        alice = Account(email="alice@example.com")
        bob = Account(email="bob@example.com")
        session.add_all([alice, bob])
        await session.flush()
        household = Household(owner_account_id=alice.id)
        session.add(household)
        await session.flush()
        session.add_all(
            [
                FamilyMembership(account_id=alice.id, household_id=household.id, role="owner"),
                FamilyMembership(account_id=bob.id, household_id=household.id, role="member"),
            ]
        )
        await session.commit()
        return alice, bob, household


def _candidate(name: str) -> RecipeCandidate:
    return RecipeCandidate(
        name=name,
        ingredients=(RecipeIngredientCandidate(name="tomato"),),
        steps=(RecipeStepCandidate(number=1, text="Simmer."),),
    )


def _recommendation(owner_account_id: UUID, name: str) -> RecommendationCandidate:
    value = Decimal("0.8")
    return RecommendationCandidate(
        id=uuid4(),
        owner_account_id=owner_account_id,
        name=name,
        source=RecommendationSource.HOUSEHOLD,
        features=RecommendationFeatures(
            ingredient_match=value,
            meal_type_fit=value,
            age_fit=value,
            rating=value,
            time_fit=value,
            scenario_fit=value,
            diversity=value,
        ),
    )


async def _registry(
    session_factory: async_sessionmaker[AsyncSession],
    candidates: list[RecommendationCandidate] | None = None,
) -> ReadOnlyToolRegistry:
    plans = SqlPlanRepository(session_factory)
    return ReadOnlyToolRegistry(
        recipe_queries=RecipeRepository(session_factory),
        settings_queries=SqlDietaryPreferenceRepository(session_factory),
        plan_queries=plans,
        shopping_queries=plans,
        recommendation_service=RecommendationService(
            household=_FixedCandidates(candidates or []),
            generator=_NoGeneratedCandidates(),
        ),
        import_service=_UnusedPreviewImport(),
        planning_service=_UnusedPreviewPlanning(),
    )


@pytest.mark.asyncio
async def test_family_recipe_search_keeps_each_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    alice, bob, household = await _family(session_factory)
    recipes = RecipeRepository(session_factory)
    await recipes.create(alice.id, household.id, _candidate("Alice Tomato Soup"))
    await recipes.create(bob.id, household.id, _candidate("Bob Tomato Pasta"))
    tools = await _registry(session_factory)

    rows = await tools.execute(
        ReadOnlyToolCall(name="search_family_recipes", arguments={"query": "tomato"}),
        HouseholdScope(account_id=alice.id, household_id=household.id),
    )

    recipes_data = rows.data["recipes"]
    assert {UUID(row["owner_account_id"]) for row in recipes_data} == {alice.id, bob.id}
    assert {row["owner_display_name"] for row in recipes_data} == {"alice", "bob"}
    assert {row["is_owned_by_current_account"] for row in recipes_data} == {True, False}


@pytest.mark.asyncio
async def test_read_preferences_includes_family_visible_but_not_another_owners_private_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    alice, bob, household = await _family(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                DietaryPreference(
                    owner_account_id=alice.id,
                    household_id=household.id,
                    label="vegetarian",
                ),
                DietaryPreference(
                    owner_account_id=bob.id,
                    household_id=household.id,
                    label="low sodium",
                    visibility="private",
                ),
            ]
        )
        await session.commit()
    tools = await _registry(session_factory)

    result = await tools.execute(
        ReadOnlyToolCall(name="read_dietary_preferences", arguments={}),
        HouseholdScope(account_id=alice.id, household_id=household.id),
    )

    assert [row["label"] for row in result.data["preferences"]] == ["vegetarian"]


@pytest.mark.asyncio
async def test_recommend_three_preserves_exact_count_reason_codes_and_owner_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    alice, bob, household = await _family(session_factory)
    tools = await _registry(
        session_factory,
        [
            _recommendation(alice.id, "Soup"),
            _recommendation(bob.id, "Pasta"),
            _recommendation(alice.id, "Rice"),
        ],
    )

    result = await tools.execute(
        ReadOnlyToolCall(name="recommend_three", arguments={"ingredients": ["tomato"]}),
        HouseholdScope(account_id=alice.id, household_id=household.id),
    )

    recommendations = result.data["recommendations"]
    assert len(recommendations) == 3
    assert {UUID(row["owner_account_id"]) for row in recommendations} == {alice.id, bob.id}
    assert all("from_household_library" in row["reason_codes"] for row in recommendations)


def test_registry_exposes_exactly_eight_closed_read_only_schemas() -> None:
    names = {
        "search_own_recipes",
        "search_family_recipes",
        "read_dietary_preferences",
        "read_plans",
        "read_shopping_lists",
        "recommend_three",
        "preview_recipe_import",
        "preview_plan_change",
    }

    assert set(ReadOnlyToolRegistry.tool_definitions()) == names
    for definition in ReadOnlyToolRegistry.tool_definitions().values():
        assert definition.parameters["type"] == "object"
        assert definition.parameters["additionalProperties"] is False
        assert set(definition.parameters["required"]) == set(definition.parameters["properties"])
