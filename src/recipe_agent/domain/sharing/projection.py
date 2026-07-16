"""Explicit public allowlist for recipe shares."""

from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, TypeAdapter


class ShareRecipeSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    name: str
    ingredients: tuple[str, ...]
    steps: tuple[str, ...]


class ShareProjection:
    def recipe(self, private_recipe: Mapping[str, object]) -> ShareRecipeSnapshot:
        return ShareRecipeSnapshot(
            id=TypeAdapter(UUID).validate_python(private_recipe["id"]),
            name=TypeAdapter(str).validate_python(private_recipe["name"]),
            ingredients=TypeAdapter(tuple[str, ...]).validate_python(
                private_recipe["ingredients"]
            ),
            steps=TypeAdapter(tuple[str, ...]).validate_python(private_recipe["steps"]),
        )
