import pytest

from recipe_agent.config import Settings
from recipe_agent.domain.kitchen.ai import AIUnavailable, KitchenProvider


@pytest.mark.parametrize("content", ["[]", "null", '"not a recipe"'])
async def test_provider_rejects_non_object_json(content: str):
    async def completion(**kwargs):
        return {"choices": [{"message": {"content": content}}]}

    with pytest.raises(AIUnavailable, match="invalid JSON"):
        await KitchenProvider(Settings(_env_file=None), completion).complete([], {})
