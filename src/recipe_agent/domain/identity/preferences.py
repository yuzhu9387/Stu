"""Family-visible dietary preference read model and scoped repository."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from recipe_agent.domain.identity.models import Account
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.infrastructure.db.base import Base


class DietaryPreference(Base):
    __tablename__ = "dietary_preferences"
    __table_args__ = (
        UniqueConstraint("owner_account_id", "label", name="uq_dietary_preferences_owner_label"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    household_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("households.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="family")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class DietaryPreferenceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    owner_account_id: UUID
    owner_display_name: str
    is_owned_by_current_account: bool
    household_id: UUID
    label: str
    visibility: str
    created_at: datetime


class SqlDietaryPreferenceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_for_scope(self, scope: HouseholdScope) -> tuple[DietaryPreferenceView, ...]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DietaryPreference, Account.email)
                .join(Account, Account.id == DietaryPreference.owner_account_id)
                .where(
                    DietaryPreference.household_id == scope.household_id,
                    or_(
                        DietaryPreference.visibility == "family",
                        DietaryPreference.owner_account_id == scope.account_id,
                    ),
                )
                .order_by(DietaryPreference.label, DietaryPreference.id)
                .limit(100)
            )
            return tuple(
                DietaryPreferenceView(
                    id=record.id,
                    owner_account_id=record.owner_account_id,
                    owner_display_name=_owner_display_name(email),
                    is_owned_by_current_account=record.owner_account_id == scope.account_id,
                    household_id=record.household_id,
                    label=record.label,
                    visibility=record.visibility,
                    created_at=record.created_at,
                )
                for record, email in result.all()
            )


def _owner_display_name(email: str) -> str:
    return email.partition("@")[0]
