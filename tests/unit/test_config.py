import pytest
from pydantic import ValidationError

from recipe_agent.config import Settings


def test_live_model_defaults_are_bounded() -> None:
    settings = Settings(_env_file=None, environment="test")

    assert settings.litellm_chat_model == "openai/gpt-5.1"
    assert settings.litellm_fallback_model == "openai/gpt-5-mini"
    assert settings.litellm_reasoning_effort == "high"
    assert settings.react_max_iterations == 5


def test_lark_credentials_are_required_only_when_lark_is_enabled() -> None:
    assert Settings(_env_file=None, environment="test", lark_enabled=False)

    with pytest.raises(ValidationError, match="Lark configuration is incomplete"):
        Settings(
            _env_file=None,
            environment="test",
            lark_enabled=True,
            lark_app_id="cli_only",
        )


def test_production_requires_live_ai_and_non_development_signing_keys() -> None:
    with pytest.raises(ValidationError, match="OpenAI API key is required"):
        Settings(
            _env_file=None,
            environment="production",
            session_signing_key="production-session-key",
            metrics_token="production-metrics-token",
            action_signing_key="production-action-key",
        )


def test_configuration_errors_do_not_render_supplied_secrets() -> None:
    secret = "do-not-render-this-lark-secret"

    with pytest.raises(ValidationError) as raised:
        Settings(
            _env_file=None,
            environment="test",
            lark_enabled=True,
            lark_app_secret=secret,
        )

    assert secret not in str(raised.value)


@pytest.mark.parametrize(
    "field",
    ("session_signing_key", "metrics_token", "action_signing_key"),
)
def test_signing_and_metrics_secrets_reject_blank_or_short_values(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="test", **{field: "  short  "})


def test_production_openai_key_must_be_nonblank_without_echoing_input() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(
            _env_file=None,
            environment="production",
            session_signing_key="production-session-signing-key",
            metrics_token="production-metrics-access-key",
            action_signing_key="production-action-signing-key",
            openai_api_key="   ",
        )
    assert "input_value" not in str(raised.value)
