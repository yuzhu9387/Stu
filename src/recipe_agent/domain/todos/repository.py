"""Account-owned, family-visible todo persistence."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from recipe_agent.domain.identity.models import Account
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.todos.contracts import TodoCreate, TodoUpdate, TodoView
from recipe_agent.domain.todos.models import TodoRecord


class TodoNotFoundError(LookupError):
    pass


class TodoRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_for_scope(self, scope: HouseholdScope) -> tuple[TodoView, ...]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TodoRecord, Account.email)
                .join(Account, Account.id == TodoRecord.owner_account_id)
                .where(
                    TodoRecord.household_id == scope.household_id,
                    or_(
                        TodoRecord.visibility == "family",
                        TodoRecord.owner_account_id == scope.account_id,
                    ),
                )
                .order_by(TodoRecord.completed, TodoRecord.position, TodoRecord.created_at.desc())
                .limit(300)
            )
            return tuple(self._view(record, email, scope) for record, email in result.all())

    async def create(self, scope: HouseholdScope, payload: TodoCreate) -> TodoView:
        async with self._session_factory() as session:
            position = await session.scalar(
                select(func.coalesce(func.max(TodoRecord.position), -1)).where(
                    TodoRecord.owner_account_id == scope.account_id,
                    TodoRecord.household_id == scope.household_id,
                    TodoRecord.category == payload.category,
                )
            )
            record = TodoRecord(
                owner_account_id=scope.account_id,
                household_id=scope.household_id,
                category=payload.category,
                title=payload.title.strip(),
                note=payload.note,
                due_on=payload.due_on,
                visibility=payload.visibility,
                position=int(position or 0) + 1,
            )
            session.add(record)
            await session.commit()
            account = await session.get(Account, scope.account_id)
            assert account is not None
            return self._view(record, account.email, scope)

    async def update(self, scope: HouseholdScope, todo_id: UUID, payload: TodoUpdate) -> TodoView:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(TodoRecord).where(
                    TodoRecord.id == todo_id,
                    TodoRecord.owner_account_id == scope.account_id,
                    TodoRecord.household_id == scope.household_id,
                )
            )
            if record is None:
                raise TodoNotFoundError("Todo not found")
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(
                    record,
                    key,
                    value.strip() if key == "title" and isinstance(value, str) else value,
                )
            record.updated_at = datetime.now(UTC)
            await session.commit()
            account = await session.get(Account, scope.account_id)
            assert account is not None
            return self._view(record, account.email, scope)

    async def delete(self, scope: HouseholdScope, todo_id: UUID) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(TodoRecord).where(
                    TodoRecord.id == todo_id,
                    TodoRecord.owner_account_id == scope.account_id,
                    TodoRecord.household_id == scope.household_id,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise TodoNotFoundError("Todo not found")
            await session.commit()

    @staticmethod
    def _view(record: TodoRecord, email: str, scope: HouseholdScope) -> TodoView:
        return TodoView(
            id=record.id,
            owner_account_id=record.owner_account_id,
            owner_display_name=email.partition("@")[0],
            is_owned_by_current_account=record.owner_account_id == scope.account_id,
            household_id=record.household_id,
            category=record.category,
            title=record.title,
            note=record.note,
            completed=record.completed,
            visibility=record.visibility,
            position=record.position,
            due_on=record.due_on,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
