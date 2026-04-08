import os

from deadend_agent.utils.provider_env import (
    AWS_DEFAULT_REGION_ENV,
    AWS_REGION_ENV,
    BEDROCK_BEARER_ENV,
    configure_litellm_provider_env,
    infer_bedrock_region_from_base_url,
)


def test_infer_bedrock_region_from_runtime_endpoint() -> None:
    assert (
        infer_bedrock_region_from_base_url("https://bedrock-runtime.us-east-1.amazonaws.com")
        == "us-east-1"
    )


def test_infer_bedrock_region_from_standard_endpoint() -> None:
    assert (
        infer_bedrock_region_from_base_url("https://bedrock.eu-west-1.amazonaws.com")
        == "eu-west-1"
    )


def test_configure_litellm_provider_env_sets_bedrock_bearer_and_region(monkeypatch) -> None:
    monkeypatch.delenv(BEDROCK_BEARER_ENV, raising=False)
    monkeypatch.delenv(AWS_DEFAULT_REGION_ENV, raising=False)
    monkeypatch.delenv(AWS_REGION_ENV, raising=False)

    configure_litellm_provider_env(
        model="bedrock/us.anthropic.claude-3-5-haiku-20241022-v1:0",
        api_key="bedrock-api-key",
        api_base="https://bedrock-runtime.us-east-1.amazonaws.com",
    )

    assert os.environ[BEDROCK_BEARER_ENV] == "bedrock-api-key"
    assert os.environ[AWS_DEFAULT_REGION_ENV] == "us-east-1"
    assert os.environ[AWS_REGION_ENV] == "us-east-1"


def test_configure_litellm_provider_env_does_not_override_existing_region(monkeypatch) -> None:
    monkeypatch.setenv(AWS_DEFAULT_REGION_ENV, "ca-central-1")
    monkeypatch.setenv(AWS_REGION_ENV, "ca-central-1")

    configure_litellm_provider_env(
        model="bedrock/us.amazon.nova-lite-v1:0",
        api_key=None,
        api_base="https://bedrock-runtime.us-east-1.amazonaws.com",
    )

    assert os.environ[AWS_DEFAULT_REGION_ENV] == "ca-central-1"
    assert os.environ[AWS_REGION_ENV] == "ca-central-1"


def test_configure_litellm_provider_env_ignores_non_bedrock_models(monkeypatch) -> None:
    monkeypatch.delenv(BEDROCK_BEARER_ENV, raising=False)

    configure_litellm_provider_env(
        model="anthropic/claude-sonnet-4-5",
        api_key="not-used",
        api_base="https://example.com",
    )

    assert os.getenv(BEDROCK_BEARER_ENV) is None
