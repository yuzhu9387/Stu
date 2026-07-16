"""Signed, one-time consent for suggested domain mutations."""

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.repository import (
    SuggestedActionAlreadyClaimedError,
    SuggestedActionInvalidRecordError,
    SuggestedActionRepository,
    SuggestedActionRunNotFoundError,
)
from recipe_agent.domain.conversation.responses import (
    SuggestedActionDraft,
    SuggestedActionType,
)
from recipe_agent.domain.identity.service import HouseholdScope
from recipe_agent.domain.planning.contracts import PlanSlot
from recipe_agent.domain.planning.service import PlanningService
from recipe_agent.domain.recipes.contracts import RecipeCandidate
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.domain.sharing.service import ShareService
from recipe_agent.infrastructure.lark.crypto import ActionContextSigner, LarkDecryptionError


class InvalidSuggestedActionError(ValueError):
    """The consent token or suggested intent is invalid or expired."""


class SuggestedActionNotFoundError(LookupError):
    """The action does not belong to the authenticated account and household."""


class SuggestedActionConflictError(RuntimeError):
    """The one-time action has already been consumed."""


class ActionExecutionError(RuntimeError):
    """A claimed domain mutation failed and was recorded as failed."""


class SaveRecipeArguments(RecipeCandidate):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreatePlanArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    week_start: date
    slots: tuple[PlanSlot, ...]


class ReplacePlanItemArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: UUID
    day: date


class CreateShareArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str = Field(min_length=1)
    ingredients: tuple[str, ...]
    steps: tuple[str, ...]
    expires_in_hours: int = Field(ge=1, le=24 * 30)


type ActionArguments = (
    SaveRecipeArguments | CreatePlanArguments | ReplacePlanItemArguments | CreateShareArguments
)


class SuggestedActionClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: UUID
    account_id: UUID
    household_id: UUID
    source_run_id: UUID
    action_type: SuggestedActionType
    expires_at: datetime


class IssuedSuggestedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    type: SuggestedActionType
    token: str
    expires_at: datetime


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: UUID
    type: SuggestedActionType
    status: Literal["succeeded"] = "succeeded"
    result: dict[str, JsonValue]


class SuggestedActionHandler(Protocol):
    async def execute(
        self,
        *,
        actor: HouseholdScope,
        arguments: ActionArguments,
        action_id: UUID,
    ) -> Mapping[str, JsonValue] | BaseModel:
        """Execute one already-claimed domain mutation."""


class SaveRecipeMutationHandler:
    """Adapt the existing recipe persistence handler to suggested actions."""

    def __init__(self, repository: RecipeRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        actor: HouseholdScope,
        arguments: ActionArguments,
        action_id: UUID,
    ) -> BaseModel:
        del action_id
        if not isinstance(arguments, SaveRecipeArguments):
            raise TypeError("save_recipe received invalid arguments")
        return await self._repository.create(
            actor.account_id,
            actor.household_id,
            arguments,
        )


class CreatePlanMutationHandler:
    """Adapt the existing weekly planning service to suggested actions."""

    def __init__(self, service: PlanningService) -> None:
        self._service = service

    async def execute(
        self,
        *,
        actor: HouseholdScope,
        arguments: ActionArguments,
        action_id: UUID,
    ) -> BaseModel:
        del action_id
        if not isinstance(arguments, CreatePlanArguments):
            raise TypeError("create_plan received invalid arguments")
        return await self._service.create_week(
            actor.account_id,
            actor.household_id,
            arguments.week_start,
            arguments.slots,
        )


class ReplacePlanItemMutationHandler:
    """Adapt the existing targeted replacement service to suggested actions."""

    def __init__(self, service: PlanningService) -> None:
        self._service = service

    async def execute(
        self,
        *,
        actor: HouseholdScope,
        arguments: ActionArguments,
        action_id: UUID,
    ) -> BaseModel:
        del action_id
        if not isinstance(arguments, ReplacePlanItemArguments):
            raise TypeError("replace_plan_item received invalid arguments")
        return await self._service.replace_item(
            actor.household_id,
            arguments.plan_id,
            arguments.day,
        )


class CreateShareMutationHandler:
    """Adapt the existing privacy-safe share service to suggested actions."""

    def __init__(self, service: ShareService) -> None:
        self._service = service

    async def execute(
        self,
        *,
        actor: HouseholdScope,
        arguments: ActionArguments,
        action_id: UUID,
    ) -> Mapping[str, JsonValue]:
        del action_id
        if not isinstance(arguments, CreateShareArguments):
            raise TypeError("create_share received invalid arguments")
        delivery = await self._service.create_snapshot(
            {
                "id": str(arguments.id),
                "name": arguments.name,
                "ingredients": list(arguments.ingredients),
                "steps": list(arguments.steps),
            },
            owner_account_id=actor.account_id,
            household_id=actor.household_id,
            expires_in=timedelta(hours=arguments.expires_in_hours),
        )
        return {"token": delivery.token}


_ARGUMENT_MODELS: dict[SuggestedActionType, type[BaseModel]] = {
    "save_recipe": SaveRecipeArguments,
    "create_plan": CreatePlanArguments,
    "replace_plan_item": ReplacePlanItemArguments,
    "create_share": CreateShareArguments,
}
_json_object_adapter = TypeAdapter(dict[str, JsonValue])


class SuggestedActionService:
    """Issue opaque consent tokens and consume them after an authenticated click."""

    def __init__(
        self,
        *,
        repository: SuggestedActionRepository,
        signer: ActionContextSigner,
        handlers: Mapping[SuggestedActionType, SuggestedActionHandler],
        lifetime: timedelta = timedelta(minutes=15),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if lifetime <= timedelta(0):
            raise ValueError("Suggested action lifetime must be positive")
        unknown_handlers = set(handlers).difference(_ARGUMENT_MODELS)
        if unknown_handlers:
            raise ValueError("Unknown suggested action handler")
        self._repository = repository
        self._signer = signer
        self._handlers = dict(handlers)
        self._lifetime = lifetime
        self._now = now or (lambda: datetime.now(UTC))

    async def issue(
        self,
        draft: SuggestedActionDraft,
        *,
        actor: HouseholdScope,
        source_run_id: UUID,
    ) -> IssuedSuggestedAction:
        arguments = _decode_draft_arguments(draft)
        action_id = uuid4()
        expires_at = _aware(self._now()) + self._lifetime
        claims = SuggestedActionClaims(
            action_id=action_id,
            account_id=actor.account_id,
            household_id=actor.household_id,
            source_run_id=source_run_id,
            action_type=draft.type,
            expires_at=expires_at,
        )
        token = self._signer.dumps(claims.model_dump(mode="json"))
        try:
            await self._repository.create(
                action_id=action_id,
                token_hash=_hash_token(token),
                source_run_id=source_run_id,
                account_id=actor.account_id,
                household_id=actor.household_id,
                action_type=draft.type,
                arguments_json=arguments.model_dump_json(),
                expires_at=expires_at,
            )
        except SuggestedActionRunNotFoundError as error:
            raise SuggestedActionNotFoundError("Source run not found") from error
        return IssuedSuggestedAction(
            id=action_id,
            type=draft.type,
            token=token,
            expires_at=expires_at,
        )

    async def consume(self, token: str, *, actor: HouseholdScope) -> ActionResult:
        claims = self._load_claims(token)
        now = _aware(self._now())
        if _aware(claims.expires_at) <= now:
            raise InvalidSuggestedActionError("Suggested action token is invalid or expired")
        if claims.account_id != actor.account_id or claims.household_id != actor.household_id:
            raise SuggestedActionNotFoundError("Suggested action not found")
        try:
            claimed = await self._repository.claim_once(
                token_hash=_hash_token(token),
                action_id=claims.action_id,
                source_run_id=claims.source_run_id,
                account_id=actor.account_id,
                household_id=actor.household_id,
                action_type=claims.action_type,
                now=now,
            )
        except SuggestedActionAlreadyClaimedError as error:
            raise SuggestedActionConflictError("Suggested action was already consumed") from error
        except SuggestedActionInvalidRecordError as error:
            raise InvalidSuggestedActionError(
                "Suggested action token is invalid or expired"
            ) from error

        try:
            arguments = _decode_stored_arguments(claimed.action_type, claimed.arguments_json)
        except InvalidSuggestedActionError:
            await self._repository.fail(claimed.id, actor.account_id, "arguments_invalid")
            raise
        handler = self._handlers.get(claims.action_type)
        if handler is None:
            await self._repository.fail(claimed.id, actor.account_id, "handler_unavailable")
            raise ActionExecutionError("Suggested action handler is unavailable")
        try:
            raw_result = await handler.execute(
                actor=actor,
                arguments=arguments,
                action_id=claimed.id,
            )
            result = _handler_result(raw_result)
        except Exception as error:
            await self._repository.fail(claimed.id, actor.account_id, "handler_failed")
            raise ActionExecutionError("Suggested action execution failed") from error
        result_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if not await self._repository.complete(claimed.id, actor.account_id, result_json):
            await self._repository.fail(claimed.id, actor.account_id, "completion_failed")
            raise ActionExecutionError("Suggested action completion could not be recorded")
        return ActionResult(
            action_id=claimed.id,
            type=claims.action_type,
            result=result,
        )

    def _load_claims(self, token: str) -> SuggestedActionClaims:
        try:
            payload = self._signer.loads(token)
            return SuggestedActionClaims.model_validate(payload)
        except (LarkDecryptionError, ValidationError) as error:
            raise InvalidSuggestedActionError(
                "Suggested action token is invalid or expired"
            ) from error


def _decode_draft_arguments(draft: SuggestedActionDraft) -> ActionArguments:
    decoded: dict[str, object] = {}
    for argument in draft.arguments:
        if argument.name in decoded:
            raise InvalidSuggestedActionError("Suggested action contains duplicate arguments")
        try:
            decoded[argument.name] = json.loads(argument.value_json)
        except json.JSONDecodeError as error:
            raise InvalidSuggestedActionError(
                "Suggested action argument is not valid JSON"
            ) from error
    try:
        model = _ARGUMENT_MODELS[draft.type].model_validate(decoded)
    except ValidationError as error:
        raise InvalidSuggestedActionError("Suggested action arguments are invalid") from error
    return cast(ActionArguments, model)


def _decode_stored_arguments(action_type: str, arguments_json: str) -> ActionArguments:
    if action_type not in _ARGUMENT_MODELS:
        raise InvalidSuggestedActionError("Suggested action type is invalid")
    try:
        decoded = json.loads(arguments_json)
        model = _ARGUMENT_MODELS[action_type].model_validate(decoded)
    except (json.JSONDecodeError, ValidationError) as error:
        raise InvalidSuggestedActionError(
            "Stored suggested action arguments are invalid"
        ) from error
    return cast(ActionArguments, model)


def _handler_result(result: Mapping[str, JsonValue] | BaseModel) -> dict[str, JsonValue]:
    payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else dict(result)
    return _json_object_adapter.validate_python(payload)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "ActionArguments",
    "ActionExecutionError",
    "ActionResult",
    "CreatePlanArguments",
    "CreatePlanMutationHandler",
    "CreateShareArguments",
    "CreateShareMutationHandler",
    "InvalidSuggestedActionError",
    "IssuedSuggestedAction",
    "ReplacePlanItemArguments",
    "ReplacePlanItemMutationHandler",
    "SaveRecipeArguments",
    "SaveRecipeMutationHandler",
    "SuggestedActionConflictError",
    "SuggestedActionNotFoundError",
    "SuggestedActionRepository",
    "SuggestedActionService",
]
