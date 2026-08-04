"""Authenticated private import status API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.recipes.contracts import RawInputSummary
from recipe_agent.domain.recipes.repository import RawInputNotFoundError, RawInputRepository

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


class ImportListResponse(BaseModel):
    imports: tuple[RawInputSummary, ...]


def get_raw_input_repository(request: Request) -> RawInputRepository:
    return RawInputRepository(request.app.state.session_factory)


RawInputRepositoryDependency = Annotated[RawInputRepository, Depends(get_raw_input_repository)]


@router.get("", response_model=ImportListResponse)
async def list_imports(
    scope: ScopeDependency, repository: RawInputRepositoryDependency
) -> ImportListResponse:
    return ImportListResponse(imports=await repository.list_summaries(scope))


@router.get("/{raw_input_id}", response_model=RawInputSummary)
async def get_import(
    raw_input_id: UUID,
    scope: ScopeDependency,
    repository: RawInputRepositoryDependency,
) -> RawInputSummary:
    try:
        return await repository.get_summary(scope, raw_input_id)
    except RawInputNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
