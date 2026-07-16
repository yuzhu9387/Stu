"""SQL planning repository with optimistic version checks."""

import json
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.identity.models import Account
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.planning.contracts import (
    IngredientAmount,
    MealPlan,
    MealPlanSummary,
    PlanItem,
    ShoppingEntry,
    ShoppingListView,
)
from recipe_agent.domain.planning.models import (
    MealPlanRecord,
    PlanItemRecord,
    ShoppingItemRecord,
    ShoppingListRecord,
)

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
                owner_account_id=record.owner_account_id,
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
                    owner_account_id=plan.owner_account_id,
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

    async def list_for_scope(self, scope: HouseholdScope) -> tuple[MealPlanSummary, ...]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(MealPlanRecord, Account.email)
                .join(Account, Account.id == MealPlanRecord.owner_account_id)
                .where(
                    MealPlanRecord.household_id == scope.household_id,
                    or_(
                        MealPlanRecord.visibility == "family",
                        MealPlanRecord.owner_account_id == scope.account_id,
                    ),
                )
                .order_by(MealPlanRecord.week_start.desc(), MealPlanRecord.id)
                .limit(100)
            )
            rows = result.all()
            items_by_plan = await self._items_by_plan(
                session, tuple(record.id for record, _ in rows)
            )
            return tuple(
                self._summary(record, email, scope, items_by_plan.get(record.id, ()))
                for record, email in rows
            )

    async def get_for_scope(self, scope: HouseholdScope, plan_id: UUID) -> MealPlanSummary:
        async with self._session_factory() as session:
            result = await session.execute(
                select(MealPlanRecord, Account.email)
                .join(Account, Account.id == MealPlanRecord.owner_account_id)
                .where(
                    MealPlanRecord.id == plan_id,
                    MealPlanRecord.household_id == scope.household_id,
                    or_(
                        MealPlanRecord.visibility == "family",
                        MealPlanRecord.owner_account_id == scope.account_id,
                    ),
                )
            )
            row = result.one_or_none()
            if row is None:
                raise PlanNotFoundError("Meal plan not found")
            items_by_plan = await self._items_by_plan(session, (plan_id,))
            return self._summary(row[0], row[1], scope, items_by_plan.get(plan_id, ()))

    async def list_shopping_for_scope(self, scope: HouseholdScope) -> tuple[ShoppingListView, ...]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ShoppingListRecord, MealPlanRecord, Account.email)
                .join(MealPlanRecord, MealPlanRecord.id == ShoppingListRecord.plan_id)
                .join(Account, Account.id == MealPlanRecord.owner_account_id)
                .where(
                    MealPlanRecord.household_id == scope.household_id,
                    or_(
                        MealPlanRecord.visibility == "family",
                        MealPlanRecord.owner_account_id == scope.account_id,
                    ),
                )
                .order_by(MealPlanRecord.week_start.desc(), ShoppingListRecord.id)
                .limit(100)
            )
            rows = result.all()
            entries_by_list = await self._entries_by_list(
                session, tuple(shopping.id for shopping, _, _ in rows)
            )
            return tuple(
                self._shopping_view(
                    shopping,
                    plan,
                    email,
                    scope,
                    entries_by_list.get(shopping.id, ()),
                )
                for shopping, plan, email in rows
            )

    async def get_shopping_for_scope(
        self, scope: HouseholdScope, shopping_list_id: UUID
    ) -> ShoppingListView:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ShoppingListRecord, MealPlanRecord, Account.email)
                .join(MealPlanRecord, MealPlanRecord.id == ShoppingListRecord.plan_id)
                .join(Account, Account.id == MealPlanRecord.owner_account_id)
                .where(
                    ShoppingListRecord.id == shopping_list_id,
                    MealPlanRecord.household_id == scope.household_id,
                    or_(
                        MealPlanRecord.visibility == "family",
                        MealPlanRecord.owner_account_id == scope.account_id,
                    ),
                )
            )
            row = result.one_or_none()
            if row is None:
                raise PlanNotFoundError("Shopping list not found")
            entries = await self._entries_by_list(session, (shopping_list_id,))
            return self._shopping_view(
                row[0], row[1], row[2], scope, entries.get(shopping_list_id, ())
            )

    @classmethod
    async def _items_by_plan(
        cls, session: AsyncSession, plan_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[PlanItem, ...]]:
        if not plan_ids:
            return {}
        result = await session.execute(
            select(PlanItemRecord)
            .where(PlanItemRecord.plan_id.in_(plan_ids))
            .order_by(PlanItemRecord.plan_id, PlanItemRecord.day, PlanItemRecord.slot)
        )
        grouped: dict[UUID, list[PlanItem]] = {}
        for record in result.scalars():
            grouped.setdefault(record.plan_id, []).append(cls._item_from_record(record))
        return {plan_id: tuple(items) for plan_id, items in grouped.items()}

    @staticmethod
    async def _entries_by_list(
        session: AsyncSession, shopping_list_ids: tuple[UUID, ...]
    ) -> dict[UUID, tuple[ShoppingEntry, ...]]:
        if not shopping_list_ids:
            return {}
        result = await session.execute(
            select(ShoppingItemRecord)
            .where(ShoppingItemRecord.shopping_list_id.in_(shopping_list_ids))
            .order_by(ShoppingItemRecord.shopping_list_id, ShoppingItemRecord.name)
        )
        grouped: dict[UUID, list[ShoppingEntry]] = {}
        for record in result.scalars():
            grouped.setdefault(record.shopping_list_id, []).append(
                ShoppingEntry(
                    name=record.name,
                    quantity=record.quantity,
                    unit=record.unit,
                    checked=record.checked,
                )
            )
        return {list_id: tuple(items) for list_id, items in grouped.items()}

    @staticmethod
    def _summary(
        record: MealPlanRecord,
        email: str,
        scope: HouseholdScope,
        items: tuple[PlanItem, ...],
    ) -> MealPlanSummary:
        return MealPlanSummary(
            id=record.id,
            owner_account_id=record.owner_account_id,
            owner_display_name=_owner_display_name(email),
            is_owned_by_current_account=record.owner_account_id == scope.account_id,
            household_id=record.household_id,
            week_start=record.week_start,
            version=record.version,
            items=items,
        )

    @staticmethod
    def _shopping_view(
        shopping: ShoppingListRecord,
        plan: MealPlanRecord,
        email: str,
        scope: HouseholdScope,
        entries: tuple[ShoppingEntry, ...],
    ) -> ShoppingListView:
        return ShoppingListView(
            id=shopping.id,
            owner_account_id=plan.owner_account_id,
            owner_display_name=_owner_display_name(email),
            is_owned_by_current_account=plan.owner_account_id == scope.account_id,
            household_id=plan.household_id,
            plan_id=plan.id,
            version=shopping.version,
            entries=entries,
        )

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


def _owner_display_name(email: str) -> str:
    return email.partition("@")[0]
