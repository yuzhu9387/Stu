"""SQL planning repository with optimistic version checks."""

import json
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.planning.contracts import IngredientAmount, MealPlan, PlanItem
from recipe_agent.domain.planning.models import MealPlanRecord, PlanItemRecord

_ingredients_adapter = TypeAdapter(tuple[IngredientAmount, ...])


class PlanNotFoundError(LookupError):
    pass


class PlanVersionConflictError(RuntimeError):
    pass


class SqlPlanRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, household_id: UUID, plan_id: UUID) -> MealPlan:
        async with self._session_factory() as session:
            result = await session.execute(
                select(MealPlanRecord).where(
                    MealPlanRecord.id == plan_id,
                    MealPlanRecord.household_id == household_id,
                )
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise PlanNotFoundError("Meal plan not found")
            item_result = await session.execute(
                select(PlanItemRecord)
                .where(PlanItemRecord.plan_id == plan_id)
                .order_by(PlanItemRecord.day, PlanItemRecord.slot)
            )
            return MealPlan(
                id=record.id,
                household_id=record.household_id,
                week_start=record.week_start,
                version=record.version,
                items=tuple(self._item_from_record(item) for item in item_result.scalars()),
            )

    async def save(self, plan: MealPlan) -> MealPlan:
        async with self._session_factory() as session:
            record = await session.get(MealPlanRecord, plan.id)
            if record is None:
                record = MealPlanRecord(
                    id=plan.id,
                    household_id=plan.household_id,
                    week_start=plan.week_start,
                    version=plan.version,
                )
                session.add(record)
            else:
                if record.household_id != plan.household_id:
                    raise PlanNotFoundError("Meal plan not found")
                if plan.version != record.version + 1:
                    raise PlanVersionConflictError("Meal plan version conflict")
                record.version = plan.version
                record.week_start = plan.week_start
                await session.execute(
                    delete(PlanItemRecord).where(PlanItemRecord.plan_id == plan.id)
                )
            session.add_all([self._record_from_item(plan.id, item) for item in plan.items])
            await session.commit()
        return plan

    @staticmethod
    def _record_from_item(plan_id: UUID, item: PlanItem) -> PlanItemRecord:
        return PlanItemRecord(
            id=item.id,
            plan_id=plan_id,
            day=item.day,
            slot=item.slot,
            recipe_id=item.recipe_id,
            recipe_name=item.recipe_name,
            reason_codes_json=json.dumps(item.reason_codes),
            ingredients_json=_ingredients_adapter.dump_json(item.ingredients).decode("utf-8"),
        )

    @staticmethod
    def _item_from_record(record: PlanItemRecord) -> PlanItem:
        return PlanItem(
            id=record.id,
            day=record.day,
            slot=record.slot,
            recipe_id=record.recipe_id,
            recipe_name=record.recipe_name,
            reason_codes=tuple(json.loads(record.reason_codes_json)),
            ingredients=_ingredients_adapter.validate_json(record.ingredients_json),
        )
