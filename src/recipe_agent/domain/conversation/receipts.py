"""Transaction-local idempotency receipts for suggested-action mutations."""

import json
from collections.abc import Mapping
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.identity.models import ActionMutationReceipt


async def receipt_result(
    session: AsyncSession,
    action_id: UUID,
    action_type: str,
) -> dict[str, JsonValue] | None:
    receipt = await session.get(ActionMutationReceipt, action_id)
    if receipt is None:
        return None
    if receipt.action_type != action_type:
        raise ValueError("Action receipt type mismatch")
    decoded = json.loads(receipt.result_json)
    if not isinstance(decoded, dict):
        raise TypeError("Action receipt result must be an object")
    return decoded


def add_receipt(
    session: AsyncSession,
    action_id: UUID,
    action_type: str,
    result: Mapping[str, JsonValue] | BaseModel,
) -> None:
    payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else dict(result)
    session.add(
        ActionMutationReceipt(
            action_id=action_id,
            action_type=action_type,
            result_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
    )
