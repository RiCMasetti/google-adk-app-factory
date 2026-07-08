from __future__ import annotations

import pytest

from app.config import (
    ConfigurationError,
    Settings,
    bedrock_runtime_endpoint,
    create_litellm_model,
    validate_eu_bedrock_region,
)


def test_bedrock_endpoint_uses_regional_runtime_format() -> None:
    assert (
        bedrock_runtime_endpoint("eu-central-1")
        == "https://bedrock-runtime.eu-central-1.amazonaws.com"
    )


def test_rejects_non_eu_region() -> None:
    with pytest.raises(ConfigurationError):
        validate_eu_bedrock_region("us-east-1")


def test_region_resolution_prefers_bedrock_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("BEDROCK_ORCHESTRATOR_MODEL_ID", "orchestrator-model")
    monkeypatch.setenv("BEDROCK_SUBAGENT_MODEL_ID", "subagent-model")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-token")

    settings = Settings.from_env()

    assert settings.bedrock_region == "eu-west-1"
    assert settings.bedrock_endpoint == "https://bedrock-runtime.eu-west-1.amazonaws.com"


def test_placeholder_models_are_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "BEDROCK_ORCHESTRATOR_MODEL_ID",
        "BEDROCK_SUBAGENT_MODEL_ID",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BEDROCK_REGION", "eu-central-1")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "xxxxxxxxx")

    settings = Settings.from_env()

    with pytest.raises(ConfigurationError):
        settings.require_configured_models()


def test_bedrock_bearer_token_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_REGION", "eu-central-1")
    monkeypatch.setenv("BEDROCK_ORCHESTRATOR_MODEL_ID", "orchestrator-model")
    monkeypatch.setenv("BEDROCK_SUBAGENT_MODEL_ID", "subagent-model")
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    with pytest.raises(ConfigurationError, match="AWS_BEARER_TOKEN_BEDROCK"):
        Settings.from_env()


def test_litellm_model_receives_bedrock_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_REGION", "eu-central-1")
    monkeypatch.setenv("BEDROCK_ORCHESTRATOR_MODEL_ID", "orchestrator-model")
    monkeypatch.setenv("BEDROCK_SUBAGENT_MODEL_ID", "subagent-model")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "secret-token")

    settings = Settings.from_env()
    model = create_litellm_model(settings.orchestrator_model, settings.bedrock_api_key)

    assert model._additional_args["api_key"] == "secret-token"
    assert model._additional_args["aws_bedrock_runtime_endpoint"] == (
        "https://bedrock-runtime.eu-central-1.amazonaws.com"
    )
    assert model._additional_args["timeout"] == 300.0
    assert "secret-token" not in repr(settings)


def test_agent_timeout_settings_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_REGION", "eu-central-1")
    monkeypatch.setenv("BEDROCK_ORCHESTRATOR_MODEL_ID", "orchestrator-model")
    monkeypatch.setenv("BEDROCK_SUBAGENT_MODEL_ID", "subagent-model")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "secret-token")
    monkeypatch.setenv("AGENT_CALL_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("BEDROCK_REQUEST_TIMEOUT_SECONDS", "45")

    settings = Settings.from_env()
    model = create_litellm_model(settings.orchestrator_model, settings.bedrock_api_key)

    assert settings.agent_call_timeout_seconds == 120
    assert model._additional_args["timeout"] == 45.0


def test_agent_timeout_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEDROCK_REGION", "eu-central-1")
    monkeypatch.setenv("BEDROCK_ORCHESTRATOR_MODEL_ID", "orchestrator-model")
    monkeypatch.setenv("BEDROCK_SUBAGENT_MODEL_ID", "subagent-model")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "secret-token")
    monkeypatch.setenv("AGENT_CALL_TIMEOUT_SECONDS", "0")

    with pytest.raises(ConfigurationError, match="AGENT_CALL_TIMEOUT_SECONDS"):
        Settings.from_env()
