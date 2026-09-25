from uuid import uuid4

from recipe_agent.domain.sharing.projection import ShareProjection


def test_share_projection_excludes_private_fields() -> None:
    private_recipe = {
        "id": uuid4(),
        "name": "Family Soup",
        "ingredients": ["tomato", "water"],
        "steps": ["Simmer"],
        "child_name": "Private Child",
        "private_photo": "s3://private/photo.jpg",
        "child_rating": 5,
        "email": "cook@example.com",
        "phone": "+10000000000",
    }

    snapshot = ShareProjection().recipe(private_recipe)
    serialized = snapshot.model_dump_json()

    assert snapshot.name == "Family Soup"
    for forbidden in ("child_name", "private_photo", "child_rating", "email", "phone"):
        assert forbidden not in serialized
