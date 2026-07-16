"""One composition root shared by the HTTP API and background workers."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from recipe_agent.api.lark import LarkIntegrationDisabledError, LarkWebhookHandler
from recipe_agent.config import Settings
from recipe_agent.domain.common.ai import AIProvider
from recipe_agent.domain.common.types import JsonValue
from recipe_agent.domain.conversation.actions import (
    CreatePlanMutationHandler,
    CreateShareMutationHandler,
    ReplacePlanItemMutationHandler,
    SaveRecipeMutationHandler,
    SuggestedActionHandler,
    SuggestedActionService,
)
from recipe_agent.domain.conversation.contracts import ConversationCommand
from recipe_agent.domain.conversation.hub import ConversationHub
from recipe_agent.domain.conversation.react import AgentContext, ReactAgent
from recipe_agent.domain.conversation.read_tools import ReadOnlyToolRegistry
from recipe_agent.domain.conversation.repository import (
    AgentRunRepository,
    SuggestedActionRepository,
)
from recipe_agent.domain.conversation.responses import SuggestedActionType
from recipe_agent.domain.feedback.repository import SqlFeedbackRepository
from recipe_agent.domain.feedback.service import FeedbackService
from recipe_agent.domain.identity.locale import Locale, Translator
from recipe_agent.domain.identity.models import AgentRun
from recipe_agent.domain.identity.preferences import SqlDietaryPreferenceRepository
from recipe_agent.domain.identity.service import HouseholdScope, IdentityService
from recipe_agent.domain.imports.adapters import (
    AdapterRegistry,
    ExcelAdapter,
    GenericURLAdapter,
    ImageAdapter,
    TextAdapter,
    XiaohongshuURLAdapter,
)
from recipe_agent.domain.imports.service import ImportService
from recipe_agent.domain.planning.repository import SqlPlanRepository
from recipe_agent.domain.planning.service import PlanningService
from recipe_agent.domain.recipes.models import Recipe, RecipeVersion
from recipe_agent.domain.recipes.repository import RawInputRepository, RecipeRepository
from recipe_agent.domain.recommendations.contracts import (
    RecommendationCandidate,
    RecommendationFeatures,
    RecommendationQuery,
    RecommendationSource,
)
from recipe_agent.domain.recommendations.service import RecommendationService
from recipe_agent.domain.sharing.repository import SqlShareRepository
from recipe_agent.domain.sharing.service import ShareService
from recipe_agent.infrastructure.ai.litellm_provider import LiteLLMCompletion, LiteLLMProvider
from recipe_agent.infrastructure.ai.react_model import LiteLLMReactModel
from recipe_agent.infrastructure.db.session import create_session_factory
from recipe_agent.infrastructure.lark.client import LarkClient
from recipe_agent.infrastructure.lark.crypto import ActionContextSigner, LarkCipher
from recipe_agent.infrastructure.lark.delivery import (
    LarkDeliveryService,
    SqlLarkDeliveryQueue,
)
from recipe_agent.infrastructure.lark.events import SqlLarkEventStore
from recipe_agent.infrastructure.lark.normalizer import LarkEventNormalizer
from recipe_agent.infrastructure.lark.renderer import LarkCardRenderer
from recipe_agent.infrastructure.lark.service import LarkInboundService
from recipe_agent.infrastructure.lark.token import LarkTenantTokenProvider


@dataclass(frozen=True)
class ModelConfiguration:
    """Public, secret-free model settings used by both process types."""

    primary: str
    fallback: str
    reasoning_effort: Literal["low", "medium", "high"]
    timeout_seconds: float
    max_retries: int
    max_iterations: int


class _PersistedRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    locale: Locale
    message: str = Field(min_length=1)
    reply_target: str | None = None


class AgentRunService:
    """Load a durable command and execute the shared bounded agent."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        agent: ReactAgent,
        actions: SuggestedActionService,
    ) -> None:
        self._session_factory = session_factory
        self._agent = agent
        self._actions = actions

    async def execute(self, run_id: UUID) -> Mapping[str, JsonValue]:
        command = await self._load_command(run_id)
        final = await self._agent.run(AgentContext.from_command(command))
        actor = HouseholdScope(command.account_id, command.household_id)
        issued = tuple(
            [
                await self._actions.issue(
                    draft,
                    actor=actor,
                    source_run_id=run_id,
                )
                for draft in final.suggested_actions
            ]
        )
        payload = final.model_dump(mode="json")
        payload["suggested_actions"] = [action.model_dump(mode="json") for action in issued]
        return cast(dict[str, JsonValue], payload)

    async def _load_command(self, run_id: UUID) -> ConversationCommand:
        async with self._session_factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is None:
                raise LookupError("Agent run not found")
            try:
                request = _PersistedRunRequest.model_validate_json(run.request_json)
            except ValidationError:
                raise ValueError("Persisted agent request is invalid") from None
            return ConversationCommand(
                run_id=run.id,
                account_id=run.account_id,
                household_id=run.household_id,
                conversation_id=run.conversation_id,
                locale=request.locale,
                message=request.message,
                transport=run.transport,
                idempotency_key=run.idempotency_key,
                reply_target=request.reply_target,
            )


class _GeneratedNames(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    names: tuple[str, ...] = Field(min_length=1, max_length=3)


class LiteLLMGeneratedCandidateSource:
    """Generate recommendation candidates through the configured live provider."""

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider

    async def generate(
        self, query: RecommendationQuery, count: int
    ) -> list[RecommendationCandidate]:
        requested = max(1, min(3, count))
        prompt = (
            f"Suggest exactly {requested} concise recipe names as JSON. "
            f"Allergies: {sorted(query.allergies)}. "
            f"Available ingredients: {sorted(query.ingredients)}."
        )
        result = await self._provider.parse_structured(prompt, _GeneratedNames)
        return [
            RecommendationCandidate(
                id=uuid4(),
                name=name,
                source=RecommendationSource.GENERATED,
                features=_default_features(),
            )
            for name in result.names[:requested]
        ]


class SqlHouseholdCandidateSource:
    """Read only family-visible recipe candidates with owner attribution."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def candidates(self, query: RecommendationQuery) -> list[RecommendationCandidate]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(Recipe, RecipeVersion.name)
                .join(RecipeVersion, RecipeVersion.id == Recipe.active_version_id)
                .where(
                    Recipe.household_id == query.household_id,
                    Recipe.visibility == "family",
                )
                .order_by(Recipe.created_at.desc(), Recipe.id)
                .limit(100)
            )
            return [
                RecommendationCandidate(
                    id=recipe.id,
                    owner_account_id=recipe.owner_account_id,
                    name=name,
                    source=RecommendationSource.HOUSEHOLD,
                    features=_default_features(),
                )
                for recipe, name in rows.all()
            ]


def _default_features() -> RecommendationFeatures:
    return RecommendationFeatures(
        ingredient_match=Decimal("0.7"),
        meal_type_fit=Decimal("0.7"),
        age_fit=Decimal("0.8"),
        rating=Decimal("0.6"),
        time_fit=Decimal("0.6"),
        scenario_fit=Decimal("0.7"),
        diversity=Decimal("0.6"),
    )


class DisabledLarkWebhookHandler:
    """Closed Lark boundary used only when the integration is explicitly disabled."""

    async def handle(self, payload: object) -> dict[str, str]:
        del payload
        raise LarkIntegrationDisabledError("Lark integration is disabled")


class ReadinessService:
    """Probe database and broker without exposing connection details."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_url: str,
    ) -> None:
        self._session_factory = session_factory
        self._redis_url = redis_url

    async def check(self) -> None:
        async with self._session_factory() as session:
            await session.execute(sql_text("SELECT 1"))
        redis = Redis.from_url(self._redis_url, socket_connect_timeout=2, socket_timeout=2)
        try:
            if not await redis.ping():
                raise RuntimeError("Broker readiness check failed")
        finally:
            await redis.aclose()


@dataclass
class Runtime:
    """Concrete runtime graph shared by the API and loop-local worker factories."""

    settings: Settings = field(repr=False)
    session_factory: async_sessionmaker[AsyncSession] = field(repr=False)
    identity_service: IdentityService
    agent_run_repository: AgentRunRepository
    conversation_hub: ConversationHub
    agent_model: LiteLLMReactModel
    model_configuration: ModelConfiguration
    agent_run_service: AgentRunService
    suggested_action_service: SuggestedActionService
    recommendation_service: RecommendationService
    planning_service: PlanningService
    share_service: ShareService
    feedback_service: FeedbackService
    import_service: ImportService
    lark_handler: LarkWebhookHandler | DisabledLarkWebhookHandler
    readiness: ReadinessService

    async def aclose(self) -> None:
        bind = self.session_factory.kw.get("bind")
        if isinstance(bind, AsyncEngine):
            await bind.dispose()


def build_runtime(settings: Settings) -> Runtime:
    """Build the complete application graph without starting network I/O."""

    session_factory = create_session_factory(settings)
    identity = IdentityService(session_factory=session_factory)
    run_repository = AgentRunRepository(session_factory)
    hub = ConversationHub(run_repository)
    recipe_repository = RecipeRepository(session_factory)
    plan_repository = SqlPlanRepository(session_factory)
    preference_repository = SqlDietaryPreferenceRepository(session_factory)
    raw_repository = RawInputRepository(session_factory)
    share_repository = SqlShareRepository(session_factory)

    api_key = (
        settings.openai_api_key.get_secret_value() if settings.openai_api_key is not None else None
    )
    provider = LiteLLMProvider(
        model=settings.litellm_vision_model,
        completion=LiteLLMCompletion(
            fallback_model=settings.litellm_fallback_model,
            reasoning_effort=settings.litellm_reasoning_effort,
            timeout_seconds=settings.litellm_timeout_seconds,
            max_retries=settings.litellm_max_retries,
            api_key=api_key,
        ),
    )
    import_service = ImportService(
        repository=raw_repository,
        adapters=AdapterRegistry(
            [
                TextAdapter(),
                ImageAdapter(),
                ExcelAdapter(),
                XiaohongshuURLAdapter(),
                GenericURLAdapter(),
            ]
        ),
        ai_provider=provider,
        recipes=recipe_repository,
    )
    recommendation_service = RecommendationService(
        household=SqlHouseholdCandidateSource(session_factory),
        generator=LiteLLMGeneratedCandidateSource(provider),
    )
    planning_service = PlanningService(
        repository=plan_repository,
        recommendations=recommendation_service,
    )
    share_service = ShareService(
        repository=share_repository,
        action_token_key=settings.action_signing_key,
    )
    action_repository = SuggestedActionRepository(session_factory)
    handlers: dict[SuggestedActionType, SuggestedActionHandler] = {
        "save_recipe": SaveRecipeMutationHandler(recipe_repository),
        "create_plan": CreatePlanMutationHandler(planning_service),
        "replace_plan_item": ReplacePlanItemMutationHandler(planning_service),
        "create_share": CreateShareMutationHandler(share_service),
    }
    action_service = SuggestedActionService(
        repository=action_repository,
        signer=ActionContextSigner(settings.action_signing_key),
        handlers=handlers,
        lifetime=timedelta(seconds=settings.suggested_action_lifetime_seconds),
    )
    tools = ReadOnlyToolRegistry(
        recipe_queries=recipe_repository,
        settings_queries=preference_repository,
        plan_queries=plan_repository,
        shopping_queries=plan_repository,
        recommendation_service=recommendation_service,
        import_service=import_service,
        planning_service=planning_service,
    )
    model = LiteLLMReactModel(
        model=settings.litellm_chat_model,
        fallback_model=settings.litellm_fallback_model,
        reasoning_effort=settings.litellm_reasoning_effort,
        timeout_seconds=settings.litellm_timeout_seconds,
        max_retries=settings.litellm_max_retries,
        tool_definitions=tools.definitions,
        api_key=api_key,
    )
    react_agent = ReactAgent(
        model=model,
        tools=tools,
        max_iterations=settings.react_max_iterations,
    )
    agent_run_service = AgentRunService(
        session_factory=session_factory,
        agent=react_agent,
        actions=action_service,
    )
    lark_handler = _build_lark_handler(
        settings,
        identity=identity,
        hub=hub,
        actions=action_service,
        session_factory=session_factory,
    )
    return Runtime(
        settings=settings,
        session_factory=session_factory,
        identity_service=identity,
        agent_run_repository=run_repository,
        conversation_hub=hub,
        agent_model=model,
        model_configuration=ModelConfiguration(
            primary=settings.litellm_chat_model,
            fallback=settings.litellm_fallback_model,
            reasoning_effort=settings.litellm_reasoning_effort,
            timeout_seconds=settings.litellm_timeout_seconds,
            max_retries=settings.litellm_max_retries,
            max_iterations=settings.react_max_iterations,
        ),
        agent_run_service=agent_run_service,
        suggested_action_service=action_service,
        recommendation_service=recommendation_service,
        planning_service=planning_service,
        share_service=share_service,
        feedback_service=FeedbackService(repository=SqlFeedbackRepository(session_factory)),
        import_service=import_service,
        lark_handler=lark_handler,
        readiness=ReadinessService(session_factory, settings.redis_url),
    )


def _build_lark_handler(
    settings: Settings,
    *,
    identity: IdentityService,
    hub: ConversationHub,
    actions: SuggestedActionService,
    session_factory: async_sessionmaker[AsyncSession],
) -> LarkWebhookHandler | DisabledLarkWebhookHandler:
    if not settings.lark_enabled:
        return DisabledLarkWebhookHandler()
    if settings.lark_verification_token is None:
        raise RuntimeError("Lark verification is not configured")
    inbound = LarkInboundService(
        identity=identity,
        hub=hub,
        delivery_queue=SqlLarkDeliveryQueue(session_factory),
        event_store=SqlLarkEventStore(session_factory),
        actions=actions,
    )
    return LarkWebhookHandler(
        verification_token=settings.lark_verification_token.get_secret_value(),
        normalizer=LarkEventNormalizer(),
        inbound=inbound,
        cipher=(
            LarkCipher(settings.lark_encrypt_key.get_secret_value())
            if settings.lark_encrypt_key is not None
            else None
        ),
    )


@asynccontextmanager
async def lark_delivery_context(
    settings: Settings,
) -> AsyncIterator[LarkDeliveryService]:
    """Build HTTP and lock-bearing Lark resources inside the current task loop."""

    if not settings.lark_enabled or settings.lark_app_secret is None or not settings.lark_app_id:
        raise RuntimeError("Lark delivery is not configured")
    runtime = build_runtime(settings)
    try:
        async with httpx.AsyncClient(timeout=settings.litellm_timeout_seconds) as http:
            token_provider = LarkTenantTokenProvider(
                http=http,
                app_id=settings.lark_app_id,
                app_secret=settings.lark_app_secret.get_secret_value(),
                base_url=settings.lark_api_base_url,
            )
            client = LarkClient(
                http=http,
                token_provider=token_provider,
                renderer=LarkCardRenderer(Translator.from_package()),
                base_url=settings.lark_api_base_url,
            )
            yield LarkDeliveryService(
                session_factory=runtime.session_factory,
                client=client,
                actions=runtime.suggested_action_service,
            )
    finally:
        await runtime.aclose()


__all__ = [
    "AgentRunService",
    "ModelConfiguration",
    "Runtime",
    "build_runtime",
    "lark_delivery_context",
]
