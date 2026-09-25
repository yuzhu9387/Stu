"""Atomic aggregate writes with revision CAS and durable retry receipts."""

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.kitchen.contracts import KitchenCommand, Workspace
from recipe_agent.domain.kitchen.engine import KitchenError, apply_command, initial_state
from recipe_agent.domain.kitchen.models import KitchenOperationReceipt, KitchenWorkspace
from recipe_agent.domain.kitchen.relational_write import project_workspace
from recipe_agent.domain.recipes.models import (
    Recipe as LegacyRecipe,
)
from recipe_agent.domain.recipes.models import (
    RecipeIngredient,
    RecipeSource,
    RecipeStep,
    RecipeTag,
    RecipeVersion,
)

logger = logging.getLogger(__name__)


def _has_content(state: dict[str, Any]) -> bool:
    return any(state.get(key) for key in ("recipes", "inventory", "plans"))


class KitchenRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        relational_read: bool = False,
    ) -> None:
        self.session_factory = session_factory
        self.relational_read = relational_read

    async def _initial(self, session: AsyncSession, scope: HouseholdScope) -> dict[str, Any]:
        """Project complete family-visible legacy recipes; never change original records.

        Private recipes cannot enter a shared household aggregate. Unknown quantities
        are left in the legacy library instead of inventing portion conversions.
        """
        state = initial_state()
        rows = (
            await session.execute(
                select(LegacyRecipe, RecipeVersion)
                .join(RecipeVersion, LegacyRecipe.active_version_id == RecipeVersion.id)
                .where(
                    LegacyRecipe.household_id == scope.household_id,
                    LegacyRecipe.visibility == "family",
                )
            )
        ).all()
        for recipe, version in rows:
            ingredients = (
                await session.scalars(
                    select(RecipeIngredient)
                    .where(RecipeIngredient.version_id == version.id)
                    .order_by(RecipeIngredient.position)
                )
            ).all()
            steps = (
                await session.scalars(
                    select(RecipeStep)
                    .where(RecipeStep.version_id == version.id)
                    .order_by(RecipeStep.number)
                )
            ).all()
            if (
                not ingredients
                or not steps
                or any(i.quantity is None or i.unit is None for i in ingredients)
            ):
                continue
            tags = list(
                await session.scalars(
                    select(RecipeTag.name).where(RecipeTag.recipe_id == recipe.id)
                )
            )
            sources = list(
                await session.scalars(
                    select(RecipeSource.source_url).where(RecipeSource.recipe_id == recipe.id)
                )
            )
            candidate = {
                "id": str(recipe.id),
                "name": version.name,
                "type": "Other",
                "mealTypes": [recipe.meal_type]
                if recipe.meal_type in {"breakfast", "lunch", "dinner"}
                else [],
                "tags": tags,
                "servings": 1,
                "activeMinutes": recipe.prep_minutes,
                "elapsedMinutes": recipe.prep_minutes + recipe.cook_minutes,
                "ingredients": [
                    {"name": i.name, "quantity": float(cast(Decimal, i.quantity)), "unit": i.unit}
                    for i in ingredients
                ],
                "steps": [step.text for step in steps],
                "liked": False,
                "source": next((url for url in sources if url), "legacy"),
                "incomplete": True,
            }
            # Legacy servings and active cook time are unknown; incomplete blocks AI feasibility.
            try:
                from recipe_agent.domain.kitchen.contracts import Recipe

                state["recipes"].append(
                    Recipe.model_validate(candidate).model_dump(mode="json", exclude_none=True)
                )
                state["tags"] = list(dict.fromkeys([*state["tags"], *tags]))
            except ValueError:
                continue
        return state

    async def get(self, scope: HouseholdScope) -> dict[str, Any]:
        async with self.session_factory() as session:
            row = await session.get(KitchenWorkspace, scope.household_id)
            if row is None:
                return await self._initial(session, scope)
            if self.relational_read:
                # Same contract, different source. Writes still go through the
                # aggregate, so `revision` stays the authoritative counter.
                from recipe_agent.domain.kitchen.relational_read import (
                    RelationalWorkspaceReader,
                )

                rebuilt = await RelationalWorkspaceReader(session).load(
                    scope.household_id, row.revision
                )
                # A household that has an aggregate but was never backfilled
                # would otherwise render as empty. Serving the aggregate is
                # always safe; serving nothing is not.
                if _has_content(row.state) and not _has_content(rebuilt):
                    logger.warning(
                        "kitchen.relational_read.empty household=%s; "
                        "serving the aggregate. Run the backfill for this household.",
                        scope.household_id,
                    )
                else:
                    return Workspace.model_validate(rebuilt).model_dump(
                        mode="json", exclude_none=True
                    )
            return Workspace.model_validate(row.state).model_dump(
                mode="json", exclude_none=True
            )

    async def command(self, scope: HouseholdScope, command: dict[str, Any]) -> dict[str, Any]:
        command = KitchenCommand.model_validate(command).model_dump(mode="json")
        fingerprint = hashlib.sha256(
            json.dumps(command, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        try:
            async with self.session_factory() as session, session.begin():
                receipt = await session.get(
                    KitchenOperationReceipt, (scope.household_id, command["operationId"])
                )
                if receipt:
                    if receipt.fingerprint != fingerprint:
                        raise KitchenError(
                            "Operation ID was already used for a different command", 409
                        )
                    return receipt.result
                row = await session.scalar(
                    select(KitchenWorkspace)
                    .where(KitchenWorkspace.household_id == scope.household_id)
                    .with_for_update()
                )
                # A concurrent retry may have committed while this row lock waited.
                receipt = await session.get(
                    KitchenOperationReceipt,
                    (scope.household_id, command["operationId"]),
                    populate_existing=True,
                )
                if receipt:
                    if receipt.fingerprint != fingerprint:
                        raise KitchenError("Operation ID was already used for another command", 409)
                    return receipt.result
                state = row.state if row else await self._initial(session, scope)
                result = apply_command(state, command, str(scope.account_id))
                # Phase B groups 1-2: recipes, tags, fridge batches, the stock
                # ledger and the audit trail are projected inside the same
                # transaction, so a rolled-back command cannot leave them ahead
                # of the aggregate.
                # The tables already match `state` (written together by the last
                # command), so only what this command changed is rewritten.
                await project_workspace(
                    session, scope.household_id, result["state"], state if row else None
                )
                if row:
                    changed = await session.execute(
                        update(KitchenWorkspace)
                        .where(
                            KitchenWorkspace.household_id == scope.household_id,
                            KitchenWorkspace.revision == command["expectedRevision"],
                        )
                        .values(revision=result["state"]["revision"], state=result["state"])
                    )
                    if cast(CursorResult[Any], changed).rowcount != 1:
                        raise KitchenError(
                            "Workspace changed; refresh before applying this change", 409
                        )
                else:
                    session.add(
                        KitchenWorkspace(
                            household_id=scope.household_id,
                            revision=result["state"]["revision"],
                            state=result["state"],
                        )
                    )
                session.add(
                    KitchenOperationReceipt(
                        household_id=scope.household_id,
                        operation_id=command["operationId"],
                        fingerprint=fingerprint,
                        result=result,
                    )
                )
            return result
        except IntegrityError as exc:
            async with self.session_factory() as session:
                receipt = await session.get(
                    KitchenOperationReceipt, (scope.household_id, command["operationId"])
                )
                if receipt and receipt.fingerprint == fingerprint:
                    return receipt.result
            raise KitchenError("Concurrent update; refresh and retry", 409) from exc
