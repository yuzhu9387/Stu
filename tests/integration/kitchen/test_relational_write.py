"""Phase B group 1: recipe and tag commands must keep the tables in step.

Each test drives the real `KitchenRepository.command` path, then asserts the
relational read of the affected sections matches the aggregate the command
produced. That is the invariant the cutover depends on.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from recipe_agent.domain.kitchen import schema as s
from recipe_agent.domain.kitchen.engine import KitchenError
from recipe_agent.domain.kitchen.repository import KitchenRepository

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECIPE_AGENT_TEST_DATABASE_URL"),
    reason="RECIPE_AGENT_TEST_DATABASE_URL is not configured",
)


def recipe(identifier: str, name: str, **overrides):
    base = {
        "id": identifier,
        "name": name,
        "type": "Protein",
        "mealTypes": ["dinner"],
        "tags": [],
        "servings": 4.0,
        "activeMinutes": 15.0,
        "elapsedMinutes": 30.0,
        "ingredients": [{"name": "鸡蛋", "quantity": 2.0, "unit": "个"}],
        "steps": ["打散", "下锅"],
        "liked": False,
        "source": "手动录入",
        "allergens": [],
        "equipment": ["wok"],
    }
    return {**base, **overrides}


class Driver:
    """Sends commands the way the HTTP route does, tracking the revision."""

    def __init__(self, sessions, scope):
        self.repo = KitchenRepository(sessions)
        self.relational = KitchenRepository(sessions, relational_read=True)
        self.scope = scope
        self.revision = 0

    async def send(self, kind: str, payload: dict):
        result = await self.repo.command(
            self.scope,
            {
                "type": kind,
                "payload": payload,
                "expectedRevision": self.revision,
                "operationId": uuid4().hex,
            },
        )
        self.revision = result["state"]["revision"]
        return result["state"]

    async def both(self) -> tuple[dict, dict]:
        return await self.repo.get(self.scope), await self.relational.get(self.scope)


@pytest.fixture
def driver(relational_sessions, relational_scope):
    return Driver(relational_sessions, relational_scope)


async def test_recipe_save_projects_every_child(driver, relational_sessions):
    await driver.send("tag.save", {"name": "Protein"})
    await driver.send(
        "recipe.save",
        {
            "recipe": recipe(
                "r-1",
                "番茄炒蛋",
                tags=["Protein"],
                allergens=["蛋"],
                equipment=["wok", "锅铲"],
                ingredients=[
                    {"name": "鸡蛋", "quantity": 3.0, "unit": "个"},
                    {"name": "番茄", "quantity": 2.0, "unit": "个"},
                ],
            )
        },
    )

    async with relational_sessions() as session:
        row = await session.scalar(
            select(s.KitchenRecipe).where(s.KitchenRecipe.legacy_id == "r-1")
        )
        assert row is not None
        assert row.name == "番茄炒蛋"
        assert row.category == s.FoodCategory.PROTEIN
        for model, expected in (
            (s.RecipeIngredient, 2),
            (s.RecipeStep, 2),
            (s.RecipeMealSlotLink, 1),
            (s.RecipeTagLink, 1),
            (s.RecipeEquipmentLink, 2),
            (s.RecipeAllergen, 1),
        ):
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.recipe_id == row.id)
            )
            assert count == expected, model.__name__

    aggregate, relational = await driver.both()
    assert relational["recipes"] == aggregate["recipes"]
    assert relational["tags"] == aggregate["tags"]


async def test_editing_a_recipe_replaces_children_rather_than_appending(
    driver, relational_sessions
):
    await driver.send("recipe.save", {"recipe": recipe("r-1", "番茄炒蛋")})
    await driver.send(
        "recipe.save",
        {
            "recipe": recipe(
                "r-1",
                "番茄炒蛋",
                steps=["只剩一步"],
                ingredients=[{"name": "鸡蛋", "quantity": 1.0, "unit": "个"}],
            )
        },
    )
    async with relational_sessions() as session:
        row = await session.scalar(
            select(s.KitchenRecipe).where(s.KitchenRecipe.legacy_id == "r-1")
        )
        steps = await session.scalar(
            select(func.count()).select_from(s.RecipeStep).where(s.RecipeStep.recipe_id == row.id)
        )
        assert steps == 1
    aggregate, relational = await driver.both()
    assert relational["recipes"] == aggregate["recipes"]


async def test_recipe_delete_removes_rows_but_keeps_shared_food(
    driver, relational_sessions
):
    await driver.send("recipe.save", {"recipe": recipe("r-1", "番茄炒蛋")})
    await driver.send("recipe.delete", {"id": "r-1"})

    async with relational_sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(s.KitchenRecipe))
        ) == 0
        assert (
            await session.scalar(select(func.count()).select_from(s.RecipeIngredient))
        ) == 0
        # 鸡蛋 is shared vocabulary; deleting a recipe must not remove it.
        assert (await session.scalar(select(func.count()).select_from(s.FoodItem))) >= 1

    aggregate, relational = await driver.both()
    assert relational["recipes"] == aggregate["recipes"] == []


async def test_tag_apply_adds_the_tag_to_the_catalog(driver, relational_sessions):
    await driver.send("recipe.save", {"recipe": recipe("r-1", "番茄炒蛋")})
    await driver.send("tag.apply", {"name": "冷冻友好", "recipeIds": ["r-1"]})

    async with relational_sessions() as session:
        tag = await session.scalar(select(s.Tag).where(s.Tag.name == "冷冻友好"))
        assert tag is not None
        # tag.apply adds it to the catalog, so it is listed.
        assert tag.listed is True

    aggregate, relational = await driver.both()
    assert relational["tags"] == aggregate["tags"]
    assert relational["recipes"] == aggregate["recipes"]


async def test_tag_rename_and_delete_follow_the_aggregate(driver, relational_sessions):
    await driver.send("tag.save", {"name": "Protein"})
    await driver.send("recipe.save", {"recipe": recipe("r-1", "番茄炒蛋", tags=["Protein"])})
    await driver.send("tag.save", {"name": "蛋白质", "previous": "Protein"})

    aggregate, relational = await driver.both()
    assert relational["tags"] == aggregate["tags"]
    assert relational["recipes"][0]["tags"] == ["蛋白质"]

    await driver.send("tag.delete", {"name": "蛋白质"})
    async with relational_sessions() as session:
        assert (await session.scalar(select(func.count()).select_from(s.Tag))) == 0
        assert (await session.scalar(select(func.count()).select_from(s.RecipeTagLink))) == 0
    aggregate, relational = await driver.both()
    assert relational["tags"] == aggregate["tags"] == []
    assert relational["recipes"] == aggregate["recipes"]


async def test_a_rejected_command_leaves_the_tables_untouched(driver, relational_sessions):
    await driver.send("recipe.save", {"recipe": recipe("r-1", "番茄炒蛋")})
    async with relational_sessions() as session:
        before = await session.scalar(select(func.count()).select_from(s.KitchenRecipe))

    # A stale revision must roll the whole transaction back, projection included.
    with pytest.raises(KitchenError):
        await driver.repo.command(
            driver.scope,
            {
                "type": "recipe.save",
                "payload": {"recipe": recipe("r-2", "红烧肉")},
                "expectedRevision": 999,
                "operationId": uuid4().hex,
            },
        )
    async with relational_sessions() as session:
        after = await session.scalar(select(func.count()).select_from(s.KitchenRecipe))
    assert after == before


async def test_the_two_read_paths_agree_after_a_command_sequence(driver):
    await driver.send("tag.save", {"name": "Protein"})
    await driver.send("tag.save", {"name": "快手菜"})
    await driver.send("recipe.save", {"recipe": recipe("r-1", "番茄炒蛋", tags=["Protein"])})
    await driver.send("recipe.save", {"recipe": recipe("r-2", "红烧肉", tags=["快手菜"])})
    await driver.send("recipe.save", {"recipe": recipe("r-3", "清蒸鱼")})
    await driver.send("tag.apply", {"name": "Protein", "recipeIds": ["r-2", "r-3"]})
    await driver.send("tag.apply", {"name": "快手菜", "recipeIds": ["r-1"], "remove": True})
    await driver.send("recipe.delete", {"id": "r-3"})

    aggregate, relational = await driver.both()
    assert relational["recipes"] == aggregate["recipes"]
    assert relational["tags"] == aggregate["tags"]


def detailed_recipe():
    """Everything frame 36:1030 puts on the page."""
    return recipe(
        "r-ribs",
        "红烧排骨",
        nameEn="Braised Pork Ribs",
        cuisine="中餐 Chinese",
        difficulty="medium",
        heroImageUrl="https://example.com/ribs.jpg",
        servings=3.0,
        activeMinutes=20.0,
        elapsedMinutes=60.0,
        ingredients=[
            {"name": "猪小排", "quantity": 600.0, "unit": "g", "group": "肉类"},
            {"name": "冰糖", "quantity": 30.0, "unit": "g", "group": "调味糖色"},
        ],
        steps=["排骨焯水", "炒糖色", "炖煮"],
        stepDetails=[
            {"index": 0, "title": "排骨焯水", "titleEn": "Blanch ribs", "activeMinutes": 5.0},
            {"index": 2, "title": "炖煮", "titleEn": "Braise", "waitMinutes": 40.0},
        ],
        reheat=[
            {"method": "microwave", "instruction": "中火加热3-4分钟 中途翻拌一次"},
            {"method": "steamer", "instruction": "大火蒸8-10分钟 口感更佳"},
        ],
        nutrition={"calories": 450.0, "proteinG": 35.0, "carbsG": 28.0, "source": "user"},
    )


async def test_recipe_detail_fields_round_trip(driver, relational_sessions):
    await driver.send("recipe.save", {"recipe": detailed_recipe()})

    async with relational_sessions() as session:
        row = await session.scalar(
            select(s.KitchenRecipe).where(s.KitchenRecipe.legacy_id == "r-ribs")
        )
        assert row.name_en == "Braised Pork Ribs"
        assert row.cuisine == "中餐 Chinese"
        assert row.difficulty == "medium"
        assert row.hero_image_url == "https://example.com/ribs.jpg"
        groups = (
            await session.scalars(
                select(s.RecipeIngredient.group_label)
                .where(s.RecipeIngredient.recipe_id == row.id)
                .order_by(s.RecipeIngredient.position)
            )
        ).all()
        assert list(groups) == ["肉类", "调味糖色"]
        blanch = await session.scalar(
            select(s.RecipeStep).where(
                s.RecipeStep.recipe_id == row.id, s.RecipeStep.position == 0
            )
        )
        assert blanch.title_en == "Blanch ribs"
        assert blanch.active_minutes == 5
        assert (
            await session.scalar(
                select(func.count())
                .select_from(s.RecipeReheatInstruction)
                .where(s.RecipeReheatInstruction.recipe_id == row.id)
            )
        ) == 2
        facts = await session.get(s.RecipeNutrition, row.id)
        assert facts.calories == 450
        # Fat and fibre were never supplied, so they stay unknown.
        assert facts.fat_g is None and facts.fiber_g is None

    aggregate, relational = await driver.both()
    assert relational["recipes"] == aggregate["recipes"]


async def test_absent_nutrition_is_not_zero_filled(driver, relational_sessions):
    """Product doc 5.3: missing nutrition renders as unknown, never derived."""
    await driver.send("recipe.save", {"recipe": recipe("r-1", "清炒时蔬")})
    async with relational_sessions() as session:
        row = await session.scalar(
            select(s.KitchenRecipe).where(s.KitchenRecipe.legacy_id == "r-1")
        )
        assert (await session.get(s.RecipeNutrition, row.id)) is None
    aggregate, _ = await driver.both()
    assert "nutrition" not in aggregate["recipes"][0]


async def test_ratings_are_one_per_person_and_average_is_counted(
    driver, relational_sessions
):
    """`⭐ 4.9 (42)` is avg/count over rows, so re-rating replaces, not appends."""
    await driver.send("recipe.save", {"recipe": recipe("r-1", "红烧排骨")})
    await driver.send("recipe.rate", {"recipeId": "r-1", "stars": 4})
    await driver.send("recipe.rate", {"recipeId": "r-1", "stars": 5})

    state = await driver.repo.get(driver.scope)
    assert len(state["recipeRatings"]) == 1
    assert state["recipeRatings"][0]["stars"] == 5

    async with relational_sessions() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(s.KitchenRecipeRating)
            )
        ) == 1
    aggregate, relational = await driver.both()
    assert relational["recipeRatings"] == aggregate["recipeRatings"]

    await driver.send("recipe.rate", {"recipeId": "r-1", "stars": None})
    state = await driver.repo.get(driver.scope)
    assert state["recipeRatings"] == []


async def test_deleting_a_recipe_takes_its_ratings(driver, relational_sessions):
    await driver.send("recipe.save", {"recipe": recipe("r-1", "红烧排骨")})
    await driver.send("recipe.rate", {"recipeId": "r-1", "stars": 5})
    await driver.send("recipe.delete", {"id": "r-1"})

    state = await driver.repo.get(driver.scope)
    assert state["recipeRatings"] == []
    async with relational_sessions() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(s.KitchenRecipeRating)
            )
        ) == 0


async def test_analysis_metrics_default_on_and_round_trip_a_choice(driver, relational_sessions):
    # A household that never chose sees every metric, and the reader agrees.
    aggregate, fresh = await driver.both()
    assert fresh["settings"] == aggregate["settings"]
    assert fresh["settings"]["analysisMetrics"] == [
        "prep_time",
        "daily_time",
        "nutrition_balance",
        "repetition",
        "fridge_usage",
    ]

    # Switching two off is kept as one row per metric with its own flag, and
    # the order sent does not matter.
    settings = {**fresh["settings"], "analysisMetrics": ["repetition", "prep_time"]}
    await driver.send("settings.save", {"settings": settings})

    aggregate, after = await driver.both()
    assert after["settings"]["analysisMetrics"] == ["prep_time", "repetition"]
    assert after["settings"] == aggregate["settings"]
    async with relational_sessions() as session:
        rows = dict(
            (
                await session.execute(
                    select(s.HouseholdAnalysisMetric.metric, s.HouseholdAnalysisMetric.enabled)
                )
            ).all()
        )
    assert rows == {
        "prep_time": True,
        "daily_time": False,
        "nutrition_balance": False,
        "repetition": True,
        "fridge_usage": False,
    }


async def test_pinned_tags_round_trip(driver):
    # Never chosen: neither side stores a choice.
    aggregate, fresh = await driver.both()
    assert "pinnedTags" not in fresh["settings"]
    await driver.send("tag.save", {"name": "Soup"})
    await driver.send("tag.pin", {"name": "Soup", "pinned": True})
    await driver.send("tag.pin", {"name": "lunch", "pinned": False})
    aggregate, after = await driver.both()
    assert after["settings"]["pinnedTags"] == ["breakfast", "dinner", "Soup"]
    assert after["settings"] == aggregate["settings"]

