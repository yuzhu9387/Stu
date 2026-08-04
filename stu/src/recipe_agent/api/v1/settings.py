"""Authenticated settings, family members, preferences, and Lark status reads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from recipe_agent.api.dependencies import ScopeDependency
from recipe_agent.domain.identity.preferences import (
    DietaryPreferenceView,
    SqlDietaryPreferenceRepository,
)
from recipe_agent.domain.identity.service import (
    FamilyMemberView,
    IdentityService,
    LarkBindingView,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class FamilyMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owner_account_id: UUID
    owner_display_name: str
    is_owned_by_current_account: bool
    household_id: UUID
    email: str
    role: str


class LarkBindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    owner_account_id: UUID
    owner_display_name: str
    is_owned_by_current_account: bool
    household_id: UUID
    is_linked: bool


class PreferenceListResponse(BaseModel):
    preferences: tuple[DietaryPreferenceView, ...]


class MemberListResponse(BaseModel):
    members: tuple[FamilyMemberResponse, ...]


class SettingsResponse(BaseModel):
    preferences: tuple[DietaryPreferenceView, ...]
    members: tuple[FamilyMemberResponse, ...]
    lark_binding: LarkBindingResponse


def get_preference_repository(request: Request) -> SqlDietaryPreferenceRepository:
    return SqlDietaryPreferenceRepository(request.app.state.session_factory)


PreferenceRepositoryDependency = Annotated[
    SqlDietaryPreferenceRepository, Depends(get_preference_repository)
]


def get_settings_identity_service(request: Request) -> IdentityService:
    return IdentityService(session_factory=request.app.state.session_factory)


SettingsIdentityDependency = Annotated[IdentityService, Depends(get_settings_identity_service)]


async def _members(
    scope: ScopeDependency, service: IdentityService
) -> tuple[FamilyMemberResponse, ...]:
    rows: tuple[FamilyMemberView, ...] = await service.list_family_members(scope)
    return tuple(FamilyMemberResponse.model_validate(row) for row in rows)


async def _binding(scope: ScopeDependency, service: IdentityService) -> LarkBindingResponse:
    row: LarkBindingView = await service.get_lark_binding(scope)
    return LarkBindingResponse.model_validate(row)


@router.get("", response_model=SettingsResponse)
async def get_settings_read_model(
    scope: ScopeDependency,
    identity: SettingsIdentityDependency,
    preferences: PreferenceRepositoryDependency,
) -> SettingsResponse:
    return SettingsResponse(
        preferences=await preferences.list_for_scope(scope),
        members=await _members(scope, identity),
        lark_binding=await _binding(scope, identity),
    )


@router.get("/preferences", response_model=PreferenceListResponse)
async def list_preferences(
    scope: ScopeDependency, preferences: PreferenceRepositoryDependency
) -> PreferenceListResponse:
    return PreferenceListResponse(preferences=await preferences.list_for_scope(scope))


@router.get("/members", response_model=MemberListResponse)
async def list_members(
    scope: ScopeDependency, identity: SettingsIdentityDependency
) -> MemberListResponse:
    return MemberListResponse(members=await _members(scope, identity))


@router.get("/lark-binding", response_model=LarkBindingResponse)
async def get_lark_binding(
    scope: ScopeDependency, identity: SettingsIdentityDependency
) -> LarkBindingResponse:
    return await _binding(scope, identity)
