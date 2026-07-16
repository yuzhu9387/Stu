"""Typed import commands and outcomes."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InputKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    EXCEL = "excel"
    URL = "url"


class ImportCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    household_id: UUID
    kind: InputKind
    source: str = Field(min_length=1)
    object_key: str | None = None


class ExtractedInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    source_url: str | None = None
    object_keys: tuple[str, ...] = ()


class ImportReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    household_id: UUID
    raw_input_id: UUID


class ImportOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    household_id: UUID
    raw_input_id: UUID
    recipe_id: UUID
    extracted: ExtractedInput
