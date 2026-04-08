# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Configuration management system for the security research framework.

This module provides configuration loading, validation, and management
functionality, supporting both environment variables and a JSON-based
configuration file with caching and validation capabilities.
"""

import os
import json
import uuid
from typing import Any, List
from pathlib import Path
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings
from deadend_agent.logging import logger

# Load cached CLI configuration first (if present), then environment variables.
# The file is stored at ~/.cache/deadend/config.json
_CACHE_TOML_PATH = Path.home() / ".cache" / "deadend" / "config.json"
_CACHE_CONFIG: dict[str, str] = {}
_CONFIG_SETTINGS: dict[str, Any] = {}

def load_config_json() -> dict[str, Any]:
    """Loads the JSON config"""
    if not _CACHE_TOML_PATH.exists():
        return {}
    try:
        with open(_CACHE_TOML_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("Could not open or parse config file as JSON: %s", exc)
        return {}

_CONFIG_SETTINGS = load_config_json()

logger.info("Logging is : %s", _CACHE_CONFIG)

def _cfg(key: str, default: str | None = None) -> str | None:
    """Return config value preferring cache TOML, then environment, else default."""
    if key in _CACHE_CONFIG and _CACHE_CONFIG[key] != "":
        return _CACHE_CONFIG[key]
    return os.getenv(key, default)

class ModelSpec(BaseSettings):
    """Model settings object"""
    provider: str = Field(alias='provider')
    model_name: str = Field(alias='model_name')
    api_key: str | None = Field(alias='api_key')
    base_url: str | None = Field(alias='base_url')

    def update_not_null(
        self,
        model_name: str | None,
        api_key: str | None,
        base_url: str | None,
        *args,
        **kwargs
    ):
        if model_name is not None:
            self.model_name = model_name
        if api_key is not None:
            self.api_key = api_key
        if base_url is not None:
            self.base_url = base_url

class EmbeddingSpec(ModelSpec):
    # Use field names and aliases that match the JSON config keys ("type" and "vec_dim")
    type_model: str = Field(alias="type_model", default="embeddings")
    vec_dim: int = Field(alias="vec_dim", default=1536)

    def update_not_null(
        self,
        model_name: str | None,
        api_key: str | None,
        base_url: str | None,
        *args: Any,
        type_model: str | None = None,
        vec_dim: int | None = None,
        **kwargs: Any,
    ):
        """Update only non-null fields, keeping compatibility with caller signature."""
        super(EmbeddingSpec, self).update_not_null(model_name, api_key, base_url, *args, **kwargs)
        if type_model is not None:
            self.type_model = type_model
        if vec_dim is not None:
            self.vec_dim = vec_dim

class ProvidersList(BaseSettings):
    model_providers: List[ModelSpec | EmbeddingSpec] = Field(default_factory=list)

    def update_provider(
        self,
        updated_provider: ModelSpec | EmbeddingSpec,
        provider: str,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        type_model: str | None = None,
        vec_dim: int | None = None,
    ):
        """Updates a provider from the list. 
        Verifies before hand if there is a provider that matches the one we want to change
        
        """
        for idx, provider_spec in enumerate(self.model_providers):
            if provider_spec == updated_provider:
                if isinstance(provider, EmbeddingSpec):
                    provider_spec.update_not_null(
                        model_name=model_name,
                        api_key=api_key,
                        base_url=base_url,
                        type_model=type_model,
                        vec_dim=vec_dim
                    )
                    new_provider = provider_spec
                else:
                    provider_spec.update_not_null(
                        model_name=model_name,
                        api_key=api_key,
                        base_url=base_url,
                        type_model=type_model,
                        vec_dim=vec_dim
                    )
                    new_provider = provider_spec
                self.model_providers[idx] = provider_spec
        return new_provider

    def add_provider(
        self,
        provider: str,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        type_model: str | None = None,
        vec_dim: int | None = None
    ):
        """Add a provider to the list of providers. Adds it in a unique way, where there is a check 
        that the provider that's being added is not already in the list.

        """
        if type_model is not None and vec_dim is not None and type_model == "embeddings":
            embedding_model = EmbeddingSpec(
                provider=provider,
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                type_model=type_model,
                vec_dim=vec_dim
            )
            if embedding_model not in self.model_providers:
                self.model_providers.append(embedding_model)

        llm_model = ModelSpec(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )
        if llm_model not in self.model_providers:
            self.model_providers.append(llm_model)


class Config:
    """
    Configuration class that loads environment variables from a .env file or from 
    environment variables.
    
    This configuration system supports multiple LLM providers through litellm:
    - OpenAI: Uses OPENAI_API_KEY and OPENAI_MODEL
    - Anthropic: Uses ANTHROPIC_API_KEY and ANTHROPIC_MODEL
    - Google Gemini: Uses GEMINI_API_KEY and GEMINI_MODEL
    - AWS Bedrock: Uses AWS_BEARER_TOKEN_BEDROCK and BEDROCK_MODEL
    - OpenRouter: Uses OPEN_ROUTER_API_KEY and OPEN_ROUTER_MODEL (supports multiple providers)
    - Local/Self-hosted: Uses LOCAL_API_KEY, LOCAL_MODEL, and LOCAL_BASE_URL
    
    Configuration is loaded from ~/.cache/deadend/config.toml (preferred) or environment variables.
    The config file is JSON-formatted, despite the historical .toml extension, and is created/updated
    via the CLI's interactive LLM provider selector in the chat interface.
    
    litellm automatically handles provider-specific API formats, so you just need to provide
    the API key and model name. For OpenRouter, use the format "provider/model-name" (e.g., 
    "anthropic/claude-4.5-opus"). For local models, provide the base URL of your OpenAI-compatible
    API endpoint.
    """
    # Models
    openai_api_key: str | None = _cfg("OPENAI_API_KEY")
    openai_model_name : str | None = _cfg("OPENAI_MODEL", "gpt-4o-mini-2024-07-18")
    anthropic_api_key: str | None = _cfg("ANTHROPIC_API_KEY")
    anthropic_model_name : str | None = _cfg("ANTHROPIC_MODEL")
    gemini_api_key: str | None = _cfg("GEMINI_API_KEY")
    gemini_model_name : str | None = _cfg("GEMINI_MODEL", "gemini-2.5-pro")
    bedrock_api_key: str | None = _cfg("AWS_BEARER_TOKEN_BEDROCK")
    bedrock_model_name: str | None = _cfg("BEDROCK_MODEL")
    open_router_key: str | None = _cfg("OPEN_ROUTER_API_KEY")
    open_router_model: str | None = _cfg("OPEN_ROUTER_MODEL", "anthropic/claude-4.5-opus")
    local_model: str | None = _cfg("LOCAL_MODEL", "Kimi-K2-Thinking")
    local_api_key: str | None = _cfg("LOCAL_API_KEY")
    local_base_url: str | None = _cfg("LOCAL_BASE_URL")
    # Embedding model
    embedding_model: str | None  = _cfg("EMBEDDING_MODEL")

    # List providers
    providers: ProvidersList = ProvidersList()
    # Storage
    agents_storage_root: str = _cfg("AGENTS_STORAGE_ROOT", str(Path.home() / ".cache" / "deadend" / "agents")) or str(Path.home() / ".cache" / "deadend" / "agents")
    # Tools
    zap_api_key: str | None = _cfg("ZAP_PROXY_API_KEY")

    # # Application settings
    # app_env: str = _cfg("APP_ENV", "development") or "development"
    log_level: str = _cfg("LOG_LEVEL", "INFO") or "INFO"

    @classmethod
    def configure(cls, env_file: str = ".env"):
        """
        Initialize the configuration by loading environment variables from the specified file.
        """
        cls.env_file = env_file

    @classmethod
    def _load_env_vars(cls) -> None:
        """Load environment variables from the .env file."""
        env_path = Path(cls.env_file)
        if not env_path.exists():
            raise FileNotFoundError(f"Environment file not found: {cls.env_file}")
        # Load the environment variables
        load_dotenv(dotenv_path=cls.env_file)

    @classmethod
    def populate_providers(cls) -> None:
        """Populates the list of providers with all those found in the config file.

        The config file stores providers under the "provider" key as a dictionary
        mapping arbitrary keys to provider definitions. Each definition is passed
        directly to `ProvidersList.add_provider`, which creates ModelSpec or
        EmbeddingSpec instances. Multiple models per provider are supported by
        using distinct keys that share the same `provider_name` value.
        """
        providers_section = _CONFIG_SETTINGS.get("provider") or {}
        if isinstance(providers_section, dict):
            for _, provider_cfg in providers_section.items():
                cls.providers.add_provider(**provider_cfg)

    @classmethod
    def add_provider(
        cls,
        provider: str,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        type_model: str | None = None,
        vec_dim: int | None = None
    ):
        """Add a new provider to the configuration and save to config.json.
        
        Args:
            provider: Provider name (e.g., "openai", "anthropic")
            model_name: Model name
            api_key: API key (optional)
            base_url: Base URL (optional)
            type_model: Type of model, "embeddings" for embedding models (optional)
            vec_dim: Vector dimension for embedding models (optional)
        """
        # Add provider to the in-memory list
        cls.providers.add_provider(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            type_model=type_model,
            vec_dim=vec_dim if vec_dim is not None else None
        )

        # Load existing config
        config_file = load_config_json()
        providers_section = config_file.get("provider", {})
        if not isinstance(providers_section, dict):
            providers_section = {}

        # Find the provider spec that was just added
        key = f"{provider}:{model_name}"
        provider_spec = None
        for spec in cls.providers.model_providers:
            if spec.provider == provider and spec.model_name == model_name:
                provider_spec = spec
                break

        if provider_spec:
            providers_section[key] = provider_spec.model_dump()
            config_file["provider"] = providers_section
            
            try:
                with open(str(_CACHE_TOML_PATH), "w", encoding="utf-8") as f:
                    json.dump(config_file, f, indent=2)
            except OSError:
                logger.info("Config file update failed.")

    @classmethod
    def update_provider(
        cls,
        updated_provider: ModelSpec | EmbeddingSpec,
        provider: str,
        model_name: str,
        base_url: str | None,
        api_key: str | None,
        type_model: str | None,
        vec_dim: int | None
    ):
        """
        """
        new_provider = cls.providers.update_provider(
            updated_provider,
            provider,
            model_name,
            api_key,
            base_url=base_url,
            type_model=type_model,
            vec_dim=vec_dim
        )
        config_file = load_config_json()
        providers_section = config_file.get("provider", {})
        if not isinstance(providers_section, dict):
            providers_section = {}

        # Use provider+model_name as a stable key to allow multiple models per provider.
        key = f"{new_provider.provider}:{new_provider.model_name}"
        providers_section[key] = new_provider.model_dump()
        config_file["provider"] = providers_section

        try:
            with open(str(_CACHE_TOML_PATH), "w", encoding="utf-8") as f:
                json.dump(config_file, f, indent=2)
        except OSError:
            logger.info("Config file update failed.")

    @classmethod
    def all_model_providers(cls) -> ProvidersList:
        """Returns the list of all providers"""
        return cls.providers

    @classmethod
    def get_local_agent_id(cls) -> uuid.UUID:
        """Return a stable local agent ID, generating one on first use.

        The ID is persisted in ``config.json`` under the ``local_agent_id`` key
        so that the directory layout ``{agent_id}/{session}/`` is consistent
        across runs.
        """
        config_file = load_config_json()
        existing = config_file.get("local_agent_id")
        if existing:
            return uuid.UUID(str(existing))

        new_id = uuid.uuid4()
        config_file["local_agent_id"] = str(new_id)
        try:
            _CACHE_TOML_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(str(_CACHE_TOML_PATH), "w", encoding="utf-8") as f:
                json.dump(config_file, f, indent=2)
        except OSError:
            logger.info("Could not persist local_agent_id to config file.")
        return new_id

    @classmethod
    def get_model_from_provider(cls, provider_name: str) -> List[ModelSpec | EmbeddingSpec]:
        """Returns the list of spec by provider"""
        models_spec_found = []
        for provider in cls.providers.model_providers:
            if provider.provider == provider_name:
                models_spec_found.append(provider)
        return models_spec_found
