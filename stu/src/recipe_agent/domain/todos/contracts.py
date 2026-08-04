"""Validated todo input and output contracts."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TodoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal["grocery", "todo"]
    title: str = Field(min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=2000)
    due_on: date | None = None
    visibility: Literal["private", "family"] = "family"


class TodoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal["grocery", "todo"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    note: str | None = Field(default=None, max_length=2000)
    completed: bool | None = None
    due_on: date | None = None
    visibility: Literal["private", "family"] | None = None
    position: int | None = Field(default=None, ge=0)


class TodoView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    owner_account_id: UUID
    owner_display_name: str
    is_owned_by_current_account: bool
    household_id: UUID
    category: str
    title: str
    note: str | None
    completed: bool
    visibility: str
    position: int
    due_on: date | None
    created_at: datetime
    updated_at: datetime
