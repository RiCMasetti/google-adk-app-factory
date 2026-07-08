"""Central configuration for Bedrock models, EU endpoints, and workflow limits."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


EU_BEDROCK_REGIONS = frozenset(
    {
        "eu-central-1",
        "eu-west-1",
        "eu-west-2",
        "eu-west-3",
        "eu-north-1",
        "eu-south-1",
        "eu-south-2",
        "eu-central-2",
    }
)

DEFAULT_REGION = "eu-central-1"
PLACEHOLDER_ORCHESTRATOR_MODEL_ID = (
    "eu.anthropic.claude-sonnet-4-6"
)
PLACEHOLDER_SUBAGENT_MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
PLACEHOLDER_BEDROCK_API_KEY = "xxxxxxxxx"


class ConfigurationError(ValueError):
    """Raised when runtime configuration is invalid."""


def load_env_file(path: str | Path = ".env") -> None:
    """Load a simple KEY=VALUE .env file without overriding existing variables."""

    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ConfigurationError(f"{name} must be >= 1")
    return value


def resolve_bedrock_region() -> str:
    region = (
        os.getenv("BEDROCK_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or DEFAULT_REGION
    )
    return validate_eu_bedrock_region(region)


def validate_eu_bedrock_region(region: str) -> str:
    normalized = region.strip()
    if normalized not in EU_BEDROCK_REGIONS:
        allowed = ", ".join(sorted(EU_BEDROCK_REGIONS))
        raise ConfigurationError(
            f"Bedrock region must be an EU region. Got {normalized!r}. Allowed: {allowed}"
        )
    return normalized


def bedrock_runtime_endpoint(region: str) -> str:
    validated = validate_eu_bedrock_region(region)
    return f"https://bedrock-runtime.{validated}.amazonaws.com"


def _model_id_from_env(name: str, placeholder: str) -> str:
    value = os.getenv(name, placeholder).strip()
    if not value:
        raise ConfigurationError(f"{name} must not be empty")
    return value


def _bedrock_api_key_from_env() -> str:
    value = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip()
    if not value:
        raise ConfigurationError(
            "AWS_BEARER_TOKEN_BEDROCK must be set so ADK/LiteLLM can call Bedrock "
            "with the bearer API key."
        )
    return value


def _is_placeholder(value: str) -> bool:
    return value.startswith("<") and value.endswith(">")


@dataclass(frozen=True)
class ModelConfig:
    role: str
    model_id: str
    region: str
    endpoint: str
    input_usd_per_1m: float = 0.0
    output_usd_per_1m: float = 0.0

    @property
    def litellm_model_name(self) -> str:
        if self.model_id.startswith("bedrock/"):
            return self.model_id
        return f"bedrock/{self.model_id}"

    @property
    def is_placeholder(self) -> bool:
        return _is_placeholder(self.model_id)


@dataclass(frozen=True)
class Settings:
    bedrock_region: str
    bedrock_endpoint: str
    bedrock_api_key: str = field(repr=False)
    orchestrator_model: ModelConfig
    subagent_model: ModelConfig
    workspace_dir: Path
    max_agent_iterations: int
    agent_call_timeout_seconds: int
    sandbox_auto_start: bool

    @classmethod
    def from_env(cls) -> "Settings":
        region = resolve_bedrock_region()
        endpoint = bedrock_runtime_endpoint(region)

        orchestrator_model = ModelConfig(
            role="orchestrator",
            model_id=_model_id_from_env(
                "BEDROCK_ORCHESTRATOR_MODEL_ID", PLACEHOLDER_ORCHESTRATOR_MODEL_ID
            ),
            region=region,
            endpoint=endpoint,
            input_usd_per_1m=float(os.getenv("ORCHESTRATOR_INPUT_USD_PER_1M", "0")),
            output_usd_per_1m=float(os.getenv("ORCHESTRATOR_OUTPUT_USD_PER_1M", "0")),
        )
        subagent_model = ModelConfig(
            role="subagent",
            model_id=_model_id_from_env("BEDROCK_SUBAGENT_MODEL_ID", PLACEHOLDER_SUBAGENT_MODEL_ID),
            region=region,
            endpoint=endpoint,
            input_usd_per_1m=float(os.getenv("SUBAGENT_INPUT_USD_PER_1M", "0")),
            output_usd_per_1m=float(os.getenv("SUBAGENT_OUTPUT_USD_PER_1M", "0")),
        )

        return cls(
            bedrock_region=region,
            bedrock_endpoint=endpoint,
            bedrock_api_key=_bedrock_api_key_from_env(),
            orchestrator_model=orchestrator_model,
            subagent_model=subagent_model,
            workspace_dir=Path(os.getenv("WORKSPACE_DIR", "./workspace")).expanduser(),
            max_agent_iterations=parse_positive_int("MAX_AGENT_ITERATIONS", 5),
            agent_call_timeout_seconds=parse_positive_int("AGENT_CALL_TIMEOUT_SECONDS", 900),
            sandbox_auto_start=parse_bool(os.getenv("SANDBOX_AUTO_START"), True),
        )

    def require_configured_models(self) -> None:
        placeholders = [
            model.role for model in (self.orchestrator_model, self.subagent_model) if model.is_placeholder
        ]
        if self.bedrock_api_key == PLACEHOLDER_BEDROCK_API_KEY:
            placeholders.append("bedrock_api_key")
        if placeholders:
            joined = ", ".join(placeholders)
            raise ConfigurationError(
                "Configure real Bedrock model IDs and API key before running agents. "
                f"Placeholder values found for: {joined}"
            )


def create_litellm_model(model_config: ModelConfig, api_key: str):
    """Create an ADK LiteLlm model object for Amazon Bedrock."""

    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(
        model=model_config.litellm_model_name,
        api_key=api_key,
        api_base=model_config.endpoint,
        aws_region_name=model_config.region,
        aws_bedrock_runtime_endpoint=model_config.endpoint,
        timeout=float(os.getenv("BEDROCK_REQUEST_TIMEOUT_SECONDS", "300")),
    )
