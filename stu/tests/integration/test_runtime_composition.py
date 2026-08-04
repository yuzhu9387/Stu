import builtins
from uuid import uuid4

from fastapi.testclient import TestClient

from recipe_agent.api.lark import LarkWebhookHandler
from recipe_agent.app import create_app
from recipe_agent.config import Settings
from recipe_agent.domain.conversation.contracts import ConversationCommand, RunStatus
from recipe_agent.domain.conversation.react import AgentContext
from recipe_agent.domain.identity.locale import Locale
from recipe_agent.infrastructure.ai.react_model import LiteLLMReactModel
from recipe_agent.infrastructure.db.base import Base
from recipe_agent.infrastructure.jobs.agent_runs import run_agent_job
from recipe_agent.worker import create_worker


def _settings(database_url: str, **values: object) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        session_signing_key="runtime-test-session-key",
        metrics_token="runtime-test-metrics-key",
        action_signing_key="runtime-test-action-key",
        **values,
    )


def test_application_wires_every_runtime_service_and_router(tmp_path) -> None:
    settings = _settings(f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    app = create_app(settings)

    for name in (
        "identity_service",
        "conversation_hub",
        "agent_run_service",
        "suggested_action_service",
        "recommendation_service",
        "planning_service",
        "share_service",
        "feedback_service",
        "import_service",
        "lark_handler",
    ):
        assert getattr(app.state, name) is not None
    route_paths = set(app.openapi()["paths"])
    assert {
        "/api/v1/agent/runs",
        "/api/v1/agent/actions/execute",
        "/api/v1/recipes",
        "/api/v1/plans",
        "/api/v1/shopping-lists",
        "/api/v1/imports",
        "/api/v1/shares",
        "/api/v1/settings",
        "/webhooks/lark/events",
    } <= route_paths


def test_disabled_lark_is_closed_and_live_lark_uses_real_handler(tmp_path) -> None:
    disabled = create_app(_settings(f"sqlite+aiosqlite:///{tmp_path / 'disabled-lark.db'}"))
    disabled_response = TestClient(disabled).post(
        "/webhooks/lark/events", json={"type": "url_verification"}
    )
    assert disabled_response.status_code == 503
    assert disabled_response.json()["detail"] == "Lark integration is disabled"

    enabled = create_app(
        _settings(
            f"sqlite+aiosqlite:///{tmp_path / 'enabled-lark.db'}",
            lark_enabled=True,
            lark_app_id="cli_test",
            lark_app_secret="lark-app-secret",
            lark_verification_token="lark-verification-token",
        )
    )
    assert isinstance(enabled.state.lark_handler, LarkWebhookHandler)


def test_api_and_worker_share_settings_and_real_model_configuration(tmp_path) -> None:
    settings = _settings(
        f"sqlite+aiosqlite:///{tmp_path / 'shared-runtime.db'}",
        redis_url="redis://127.0.0.1:6381/4",
        litellm_chat_model="openai/gpt-5.1",
        litellm_fallback_model="openai/gpt-5-mini",
        litellm_reasoning_effort="high",
    )

    app = create_app(settings)
    worker = create_worker(settings)

    assert app.state.settings is settings
    assert worker.conf.broker_url == settings.redis_url
    assert worker.conf.result_backend == settings.redis_url
    assert worker.conf.recipe_agent_environment == settings.environment
    assert isinstance(app.state.runtime.agent_model, LiteLLMReactModel)
    assert app.state.runtime.model_configuration.primary == "openai/gpt-5.1"
    assert app.state.runtime.model_configuration.fallback == "openai/gpt-5-mini"
    assert app.state.runtime.model_configuration.reasoning_effort == "high"
    assert "runtime-test-action-key" not in repr(app.state.runtime)


def test_composition_does_not_import_or_contact_a_model_provider(tmp_path, monkeypatch) -> None:
    original_import = builtins.__import__

    def reject_litellm(name, *args, **kwargs):
        if name == "litellm" or name.startswith("litellm."):
            raise AssertionError("Provider initialization must be lazy")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_litellm)

    create_app(_settings(f"sqlite+aiosqlite:///{tmp_path / 'lazy-provider.db'}"))


def test_all_router_dependencies_resolve_without_service_overrides(tmp_path) -> None:
    app = create_app(_settings(f"sqlite+aiosqlite:///{tmp_path / 'routers.db'}"))

    with TestClient(app) as client:
        for method, path in (
            ("get", "/api/v1/recipes"),
            ("get", "/api/v1/plans"),
            ("get", "/api/v1/shopping-lists"),
            ("get", "/api/v1/imports"),
            ("get", "/api/v1/shares"),
            ("get", "/api/v1/settings"),
            ("post", "/api/v1/recommendations"),
            ("post", "/api/v1/plans/weeks"),
            ("post", "/api/v1/agent/actions/execute"),
        ):
            response = (
                getattr(client, method)(path, json={})
                if method == "post"
                else getattr(client, method)(path)
            )
            assert response.status_code != 503, path


async def test_runtime_passes_configured_api_key_only_to_provider_call(tmp_path) -> None:
    secret = "runtime-provider-secret"
    app = create_app(
        _settings(
            f"sqlite+aiosqlite:///{tmp_path / 'provider-key.db'}",
            openai_api_key=secret,
        )
    )
    captured: dict[str, object] = {}

    async def completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"thinking":"summary","plan":"read safely",'
                            '"act":"checked facts","answer":"done",'
                            '"suggested_actions":[]}'
                        )
                    }
                }
            ]
        }

    app.state.runtime.agent_model._acompletion = completion
    await app.state.runtime.agent_model.decide(
        AgentContext(
            run_id=uuid4(),
            account_id=uuid4(),
            household_id=uuid4(),
            locale=Locale.EN_US,
            message="Recommend dinner",
        ),
        (),
    )

    assert captured["api_key"] == secret
    assert secret not in repr(app.state.runtime)


async def test_composed_run_worker_executes_model_and_persists_action_references(
    tmp_path,
) -> None:
    app = create_app(_settings(f"sqlite+aiosqlite:///{tmp_path / 'agent-worker.db'}"))
    runtime = app.state.runtime
    engine = runtime.session_factory.kw["bind"]
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    authenticated = await runtime.identity_service.consume_magic_link(
        (await runtime.identity_service.request_magic_link("cook@example.com")).token
    )
    run_id = uuid4()
    await runtime.conversation_hub.submit_message(
        ConversationCommand(
            run_id=run_id,
            account_id=authenticated.account.id,
            household_id=authenticated.household.id,
            allow_conversation_creation=True,
            locale=Locale.EN_US,
            message="Save a tomato soup recipe",
            idempotency_key="runtime-worker-1",
        )
    )

    async def completion(**kwargs):
        del kwargs
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"thinking":"The user wants a recipe draft saved.",'
                            '"plan":"Propose the exact recipe for confirmation.",'
                            '"act":"Prepared a validated save action without writing data.",'
                            '"answer":"Review and confirm the recipe below.",'
                            '"suggested_actions":[{"type":"save_recipe","arguments":['
                            '{"name":"name","value_json":"\\"Tomato soup\\""},'
                            '{"name":"ingredients","value_json":"[{\\"name\\":\\"tomato\\",'
                            '\\"quantity\\":\\"2\\",\\"unit\\":\\"cup\\"}]"},'
                            '{"name":"steps","value_json":"[{\\"number\\":1,'
                            '\\"text\\":\\"Simmer.\\"}]"}]}]}'
                        )
                    }
                }
            ]
        }

    runtime.agent_model._acompletion = completion

    assert await run_agent_job(runtime.agent_run_repository, runtime.agent_run_service, run_id)
    assert not await run_agent_job(runtime.agent_run_repository, runtime.agent_run_service, run_id)
    completed = await runtime.conversation_hub.get_run(
        run_id,
        account_id=authenticated.account.id,
        household_id=authenticated.household.id,
    )

    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    assert completed.response is not None
    assert completed.response["answer"] == "Review and confirm the recipe below."
    actions = completed.response["suggested_actions"]
    assert isinstance(actions, list) and len(actions) == 1
    assert "token" not in actions[0]
