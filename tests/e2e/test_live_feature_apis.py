from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.api.dependencies import get_household_scope
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.identity.models import Account, FamilyMembership, Household, LarkIdentity
from recipe_agent.domain.identity.preferences import DietaryPreference
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.planning.contracts import MealPlan
from recipe_agent.domain.planning.models import ShoppingItemRecord, ShoppingListRecord
from recipe_agent.domain.planning.repository import SqlPlanRepository
from recipe_agent.domain.recipes.contracts import (
    RecipeCandidate,
    RecipeIngredientCandidate,
    RecipeStepCandidate,
)
from recipe_agent.domain.recipes.models import RawInput
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.domain.sharing.models import ShareSnapshotRecord


async def _seed_live_data(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[HouseholdScope, object, object]:
    async with session_factory() as session:
        alice = Account(email="alice@example.com")
        bob = Account(email="bob@example.com")
        outsider = Account(email="outsider@example.com")
        session.add_all([alice, bob, outsider])
        await session.flush()
        family = Household(owner_account_id=alice.id)
        other_family = Household(owner_account_id=outsider.id)
        session.add_all([family, other_family])
        await session.flush()
        session.add_all(
            [
                FamilyMembership(account_id=alice.id, household_id=family.id, role="owner"),
                FamilyMembership(account_id=bob.id, household_id=family.id, role="member"),
                FamilyMembership(
                    account_id=outsider.id, household_id=other_family.id, role="owner"
                ),
                DietaryPreference(
                    owner_account_id=bob.id,
                    household_id=family.id,
                    label="nut free",
                ),
                LarkIdentity(account_id=alice.id, open_id="ou_alice"),
            ]
        )
        await session.commit()

    candidate = RecipeCandidate(
        name="Tomato Soup",
        ingredients=(RecipeIngredientCandidate(name="tomato", quantity="2", unit="piece"),),
        steps=(RecipeStepCandidate(number=1, text="Simmer."),),
    )
    recipes = RecipeRepository(session_factory)
    family_recipe = await recipes.create(bob.id, family.id, candidate)
    outsider_recipe = await recipes.create(outsider.id, other_family.id, candidate)
    plan = MealPlan(
        id=uuid4(),
        owner_account_id=bob.id,
        household_id=family.id,
        week_start=date(2026, 7, 13),
        version=1,
        items=(),
    )
    await SqlPlanRepository(session_factory).save(plan)
    async with session_factory() as session:
        shopping = ShoppingListRecord(plan_id=plan.id)
        session.add(shopping)
        await session.flush()
        session.add(
            ShoppingItemRecord(
                shopping_list_id=shopping.id,
                name="tomato",
                quantity=2,
                unit="piece",
            )
        )
        session.add_all(
            [
                RawInput(
                    owner_account_id=alice.id,
                    household_id=family.id,
                    kind="text",
                    raw_text="PRIVATE RAW SOURCE",
                    object_key="private/object/key",
                ),
                RawInput(
                    owner_account_id=bob.id,
                    household_id=family.id,
                    kind="url",
                    source_url="https://private.example/recipe",
                ),
                ShareSnapshotRecord(
                    owner_account_id=alice.id,
                    household_id=family.id,
                    token_hash="a" * 64,
                    snapshot_json='{"name":"Soup"}',
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
                ShareSnapshotRecord(
                    token_hash="b" * 64,
                    snapshot_json='{"name":"Legacy"}',
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
            ]
        )
        await session.commit()
    return (
        HouseholdScope(account_id=alice.id, household_id=family.id),
        family_recipe.id,
        outsider_recipe.id,
    )


@pytest.mark.asyncio
async def test_live_endpoints_return_scoped_owner_attributed_dtos_without_private_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scope, family_recipe_id, outsider_recipe_id = await _seed_live_data(session_factory)
    app = create_app(Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:"))
    app.state.session_factory = session_factory
    app.dependency_overrides[get_household_scope] = lambda: scope
    client = TestClient(app)

    recipes = client.get("/api/v1/recipes")
    detail = client.get(f"/api/v1/recipes/{family_recipe_id}")
    hidden_detail = client.get(f"/api/v1/recipes/{outsider_recipe_id}")
    plans = client.get("/api/v1/plans")
    shopping = client.get("/api/v1/shopping-lists")
    imports = client.get("/api/v1/imports")
    shares = client.get("/api/v1/shares")
    settings = client.get("/api/v1/settings")

    assert recipes.status_code == detail.status_code == 200
    assert hidden_detail.status_code == 404
    recipe = recipes.json()["recipes"][0]
    assert recipe["owner_display_name"] == "bob"
    assert recipe["is_owned_by_current_account"] is False
    assert detail.json()["ingredients"][0]["name"] == "tomato"
    assert plans.json()["plans"][0]["owner_display_name"] == "bob"
    assert shopping.json()["shopping_lists"][0]["owner_display_name"] == "bob"
    assert len(imports.json()["imports"]) == 1
    assert "raw_text" not in str(imports.json())
    assert "object_key" not in str(imports.json())
    assert "source_url" not in str(imports.json())
    assert len(shares.json()["shares"]) == 1
    assert "token_hash" not in str(shares.json())
    assert settings.json()["preferences"][0]["owner_display_name"] == "bob"
    assert {member["owner_display_name"] for member in settings.json()["members"]} == {
        "alice",
        "bob",
    }
    assert settings.json()["lark_binding"]["is_linked"] is True


def test_live_routes_require_authentication() -> None:
    app = create_app(Settings(environment="test", database_url="sqlite+aiosqlite:///:memory:"))
    client = TestClient(app)

    for path in (
        "/api/v1/recipes",
        "/api/v1/plans",
        "/api/v1/shopping-lists",
        "/api/v1/imports",
        "/api/v1/shares",
        "/api/v1/settings",
    ):
        assert client.get(path).status_code == 401
