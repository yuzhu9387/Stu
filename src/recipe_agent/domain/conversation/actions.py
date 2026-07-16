"""Signed, one-time consent for suggested domain mutations."""

import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.repository import (
    DEFAULT_ACTION_MAX_ATTEMPTS,
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
from recipe_agent.domain.planning.contracts import MealPlan, PlanSlot
from recipe_agent.domain.planning.service import PlanningService
from recipe_agent.domain.recipes.contracts import RecipeCandidate, RecipeView
from recipe_agent.domain.recipes.repository import RecipeRepository
from recipe_agent.domain.sharing.service import ShareDelivery, ShareService
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


class SaveRecipeResult(RecipeView):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanMutationResult(MealPlan):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateShareResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    share_id: UUID
    expires_at: datetime


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
    status: Literal["pending", "queued", "executing", "succeeded", "failed"]
    result: dict[str, JsonValue] | None = None
    delivery: ShareDelivery | None = None


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
        if not isinstance(arguments, SaveRecipeArguments):
            raise TypeError("save_recipe received invalid arguments")
        return await self._repository.create(
            actor.account_id,
            actor.household_id,
            arguments,
            source_action_id=action_id,
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
        if not isinstance(arguments, CreatePlanArguments):
            raise TypeError("create_plan received invalid arguments")
        return await self._service.create_week(
            actor.account_id,
            actor.household_id,
            arguments.week_start,
            arguments.slots,
            source_action_id=action_id,
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
        if not isinstance(arguments, ReplacePlanItemArguments):
            raise TypeError("replace_plan_item received invalid arguments")
        return await self._service.replace_item(
            actor.household_id,
            arguments.plan_id,
            arguments.day,
            source_action_id=action_id,
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
            source_action_id=action_id,
        )
        if delivery.share_id is None or delivery.expires_at is None:
            raise RuntimeError("Share action did not persist delivery metadata")
        return {
            "share_id": str(delivery.share_id),
            "expires_at": delivery.expires_at.isoformat(),
        }

    async def delivery(
        self,
        *,
        actor: HouseholdScope,
        action_id: UUID,
    ) -> ShareDelivery:
        return await self._service.delivery_for_action(
            action_id,
            owner_account_id=actor.account_id,
            household_id=actor.household_id,
        )


_ARGUMENT_MODELS: dict[SuggestedActionType, type[BaseModel]] = {
    "save_recipe": SaveRecipeArguments,
    "create_plan": CreatePlanArguments,
    "replace_plan_item": ReplacePlanItemArguments,
    "create_share": CreateShareArguments,
}
_RESULT_MODELS: dict[SuggestedActionType, type[BaseModel]] = {
    "save_recipe": SaveRecipeResult,
    "create_plan": PlanMutationResult,
    "replace_plan_item": PlanMutationResult,
    "create_share": CreateShareResult,
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
        lease_duration: timedelta = timedelta(minutes=2),
        max_attempts: int = DEFAULT_ACTION_MAX_ATTEMPTS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if lifetime <= timedelta(0):
            raise ValueError("Suggested action lifetime must be positive")
        if lease_duration <= timedelta(0):
            raise ValueError("Suggested action lease duration must be positive")
        if max_attempts < 1:
            raise ValueError("Suggested action max attempts must be positive")
        unknown_handlers = set(handlers).difference(_ARGUMENT_MODELS)
        if unknown_handlers:
            raise ValueError("Unknown suggested action handler")
        self._repository = repository
        self._signer = signer
        self._handlers = dict(handlers)
        self._lifetime = lifetime
        self._lease_duration = lease_duration
        self._max_attempts = max_attempts
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
        expires_at = _normalize_expiry(_aware(self._now()) + self._lifetime)
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
        except SuggestedActionRunNotFoundError:
            raise SuggestedActionNotFoundError("Source run not found") from None
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
            claimed = await self._repository.queue_once(
                token_hash=_hash_token(token),
                action_id=claims.action_id,
                source_run_id=claims.source_run_id,
                account_id=actor.account_id,
                household_id=actor.household_id,
                action_type=claims.action_type,
                claim_expires_at=claims.expires_at,
                now=now,
            )
        except SuggestedActionAlreadyClaimedError:
            raise SuggestedActionConflictError("Suggested action was already consumed") from None
        except SuggestedActionInvalidRecordError:
            raise InvalidSuggestedActionError(
                "Suggested action token is invalid or expired"
            ) from None

        return ActionResult(
            action_id=claimed.id,
            type=claims.action_type,
            status="queued",
        )

    async def reissue_for_delivery(
        self,
        action_ids: tuple[UUID, ...],
        *,
        actor: HouseholdScope,
        source_run_id: UUID,
    ) -> tuple[IssuedSuggestedAction, ...]:
        records = await self._repository.get_delivery_claims(
            action_ids,
            source_run_id=source_run_id,
            account_id=actor.account_id,
            household_id=actor.household_id,
        )
        issued: list[IssuedSuggestedAction] = []
        for record in records:
            claims = SuggestedActionClaims(
                action_id=record.id,
                account_id=record.account_id,
                household_id=record.household_id,
                source_run_id=record.source_run_id,
                action_type=cast(SuggestedActionType, record.action_type),
                expires_at=record.expires_at,
            )
            token = self._signer.dumps(claims.model_dump(mode="json"))
            if not secrets.compare_digest(_hash_token(token), record.token_hash):
                raise InvalidSuggestedActionError("Suggested action token is invalid")
            issued.append(
                IssuedSuggestedAction(
                    id=record.id,
                    type=cast(SuggestedActionType, record.action_type),
                    token=token,
                    expires_at=record.expires_at,
                )
            )
        return tuple(issued)

    async def execute_queued(self, action_id: UUID) -> ActionResult:
        claimed = await self._repository.claim_for_execution(
            action_id,
            now=_aware(self._now()),
            lease_duration=self._lease_duration,
            max_attempts=self._max_attempts,
        )
        if claimed is None:
            raise SuggestedActionConflictError("Suggested action is not runnable")
        actor = HouseholdScope(claimed.account_id, claimed.household_id)
        try:
            arguments = _decode_stored_arguments(claimed.action_type, claimed.arguments_json)
        except InvalidSuggestedActionError:
            await self._repository.fail(
                claimed.id,
                actor.account_id,
                "arguments_invalid",
                attempt_count=claimed.attempt_count,
            )
            raise
        action_type = cast(SuggestedActionType, claimed.action_type)
        handler = self._handlers.get(action_type)
        if handler is None:
            await self._repository.fail(
                claimed.id,
                actor.account_id,
                "handler_unavailable",
                attempt_count=claimed.attempt_count,
            )
            raise ActionExecutionError("Suggested action handler is unavailable")
        try:
            raw_result = await handler.execute(
                actor=actor,
                arguments=arguments,
                action_id=claimed.id,
            )
            result = _handler_result(raw_result)
        except Exception:
            await self._repository.retry_or_fail(
                claimed.id,
                actor.account_id,
                "handler_failed",
                attempt_count=claimed.attempt_count,
                max_attempts=self._max_attempts,
            )
            raise ActionExecutionError("Suggested action execution failed") from None
        result_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if not await self._repository.complete(
            claimed.id,
            actor.account_id,
            result_json,
            attempt_count=claimed.attempt_count,
        ):
            raise ActionExecutionError("Suggested action completion could not be recorded")
        return ActionResult(
            action_id=claimed.id,
            type=action_type,
            status="succeeded",
            result=result,
        )

    async def get_status(
        self,
        action_id: UUID,
        *,
        actor: HouseholdScope,
        include_delivery: bool = False,
    ) -> ActionResult:
        action = await self._repository.get_for_actor(
            action_id,
            account_id=actor.account_id,
            household_id=actor.household_id,
        )
        if action is None:
            raise SuggestedActionNotFoundError("Suggested action not found")
        if action.action_type not in _ARGUMENT_MODELS:
            raise InvalidSuggestedActionError("Suggested action type is invalid")
        result = None
        if action.execution_status == "succeeded":
            result = _decode_action_result(action.action_type, action.result_json)
        delivery = None
        if (
            include_delivery
            and action.execution_status == "succeeded"
            and action.action_type == "create_share"
        ):
            handler = self._handlers.get("create_share")
            if not isinstance(handler, CreateShareMutationHandler):
                raise ActionExecutionError("Share delivery handler is unavailable")
            try:
                delivery = await handler.delivery(actor=actor, action_id=action.id)
            except Exception:
                raise ActionExecutionError("Share delivery is unavailable") from None
        return ActionResult(
            action_id=action.id,
            type=action.action_type,
            status=cast(
                Literal["pending", "queued", "executing", "succeeded", "failed"],
                action.execution_status,
            ),
            result=result,
            delivery=delivery,
        )

    def _load_claims(self, token: str) -> SuggestedActionClaims:
        try:
            payload = self._signer.loads(token)
            return SuggestedActionClaims.model_validate(payload)
        except (LarkDecryptionError, ValidationError):
            raise InvalidSuggestedActionError(
                "Suggested action token is invalid or expired"
            ) from None


def _decode_draft_arguments(draft: SuggestedActionDraft) -> ActionArguments:
    decoded: dict[str, object] = {}
    for argument in draft.arguments:
        if argument.name in decoded:
            raise InvalidSuggestedActionError("Suggested action contains duplicate arguments")
        try:
            decoded[argument.name] = json.loads(argument.value_json)
        except json.JSONDecodeError:
            raise InvalidSuggestedActionError(
                "Suggested action argument is not valid JSON"
            ) from None
    try:
        model = _ARGUMENT_MODELS[draft.type].model_validate(decoded)
    except ValidationError:
        raise InvalidSuggestedActionError("Suggested action arguments are invalid") from None
    return cast(ActionArguments, model)


def _decode_stored_arguments(action_type: str, arguments_json: str) -> ActionArguments:
    if action_type not in _ARGUMENT_MODELS:
        raise InvalidSuggestedActionError("Suggested action type is invalid")
    try:
        decoded = json.loads(arguments_json)
        model = _ARGUMENT_MODELS[action_type].model_validate(decoded)
    except (json.JSONDecodeError, ValidationError):
        raise InvalidSuggestedActionError("Stored suggested action arguments are invalid") from None
    return cast(ActionArguments, model)


def _handler_result(result: Mapping[str, JsonValue] | BaseModel) -> dict[str, JsonValue]:
    payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else dict(result)
    return _json_object_adapter.validate_python(payload)


def _decode_action_result(action_type: str, result_json: str | None) -> dict[str, JsonValue]:
    if result_json is None or action_type not in _RESULT_MODELS:
        raise InvalidSuggestedActionError("Suggested action result is invalid")
    try:
        decoded = json.loads(result_json)
        validated = _RESULT_MODELS[action_type].model_validate(decoded)
        return _json_object_adapter.validate_python(validated.model_dump(mode="json"))
    except (json.JSONDecodeError, ValidationError):
        raise InvalidSuggestedActionError("Suggested action result is invalid") from None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _normalize_expiry(value: datetime) -> datetime:
    return _aware(value).astimezone(UTC).replace(microsecond=0)


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
