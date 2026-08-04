from decimal import Decimal

from recipe_agent.domain.planning.contracts import IngredientAmount
from recipe_agent.domain.planning.shopping import ShoppingAggregator


def test_shopping_aggregator_merges_compatible_units_only() -> None:
    ingredients = [
        IngredientAmount(name="Egg", quantity=Decimal("2"), unit="piece"),
        IngredientAmount(name=" egg ", quantity=Decimal("3"), unit="piece"),
        IngredientAmount(name="Soy Sauce", quantity=Decimal("1"), unit="tablespoon"),
        IngredientAmount(name="soy sauce", quantity=Decimal("10"), unit="milliliter"),
    ]

    result = ShoppingAggregator().aggregate(ingredients)

    assert result.quantity_for("egg", "piece") == Decimal("5")
    assert result.entries_for("soy sauce") == 2
