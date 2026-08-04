"""Unit-safe shopping list aggregation."""

from collections import defaultdict
from decimal import Decimal

from recipe_agent.domain.planning.contracts import (
    IngredientAmount,
    ShoppingEntry,
    ShoppingListDraft,
)


class ShoppingAggregator:
    def aggregate(self, ingredients: list[IngredientAmount]) -> ShoppingListDraft:
        quantities: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        for ingredient in ingredients:
            key = (ingredient.name.strip().casefold(), ingredient.unit.strip().casefold())
            quantities[key] += ingredient.quantity
        entries = tuple(
            ShoppingEntry(name=name, quantity=quantity, unit=unit)
            for (name, unit), quantity in sorted(quantities.items())
        )
        return ShoppingListDraft(entries=entries)
