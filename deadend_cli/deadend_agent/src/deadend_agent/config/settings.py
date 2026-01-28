# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Configuration management system for the security research framework.

This module provides configuration loading, validation, and management
functionality, supporting both environment variables and TOML configuration
files with caching and validation capabilities.
"""

import os
from typing import Any, List
from pathlib import Path
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings
import toml
from deadend_agent.logging import logger
# Load cached CLI configuration first (if present), then environment variables
_CACHE_TOML_PATH = Path.home() / ".cache" / "deadend" / "config.toml"
_CACHE_CONFIG: dict[str, str] = {}
_CONFIG_SETTINGS: dict[str, Any] = {}

def load_config_toml() -> dict[str, Any]:
    if not _CACHE_TOML_PATH.exists():
        return {}
    try:
        return toml.load(str(_CACHE_TOML_PATH))
    except OSError:
        logger.info('Could not open config.toml file.')
        return {}

def _load_cache_toml() -> dict[str, str]:
    """Load cached configuration from TOML using the toml library."""
    if not _CACHE_TOML_PATH.exists():
        return {}
    try:
        return toml.load(_CACHE_TOML_PATH)
    except Exception:
        return {}

_CACHE_CONFIG = _load_cache_toml()
_CONFIG_SETTINGS = load_config_toml()

logger.info("Logging is : %s", _CACHE_CONFIG)

def _cfg(key: str, default: str | None = None) -> str | None:
    """Return config value preferring cache TOML, then environment, else default."""
    if key in _CACHE_CONFIG and _CACHE_CONFIG[key] != "":
        return _CACHE_CONFIG[key]
    return os.getenv(key, default)

class ModelConfig(BaseSettings):
    """Model Config"""
    api_key: str
    model_name: str
    base_url: str | None = None

class ModelSettings(BaseSettings):
    """Model settings"""
      # Model provider configs
    openai: ModelConfig | None = None
    anthropic: ModelConfig | None = None
    gemini: ModelConfig | None = None
    openrouter: ModelConfig | None = None
    local: ModelConfig | None = None
    # Default model to use
    default_provider: str = "openai"

class ModelSpec(BaseSettings):
    """Model settings object"""
    provider: str = Field(alias='provider_name'),
    model_name: str = Field(alias='model'),
    api_key: str | None = Field(alias='api_key'),
    base_url: str | None = Field(alias='url'),

    def update_not_null(self, model_name: str | None, api_key: str | None, base_url: str | None):
        if model_name is not None:
            self.model_name = model_name
        if api_key is not None:
            self.api_key = api_key
        if base_url is not None:
            self.base_url = base_url
        


class EmbeddingSpec(ModelSpec):
    type: str = Field(alias='type_model', default="embedding")
    vec_dim: int = Field(alias="dimension", default=1536)

    def update_not_null(
        self,
        model_name: str | None,
        api_key: str | None,
        base_url: str | None,
        type_model: str | None,
        vec_dim: int | None
    ):
        super().update_not_null(model_name, api_key, base_url)
        if type_model is not None:
            self.type = type_model
        if vec_dim is not None:
            self.vec_dim = vec_dim


class ProvidersList(BaseSettings):
    model_providers: List[ModelSpec | EmbeddingSpec]

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
        new_provider = ModelSpec()
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
        vec_dim: str | None = None
    ):
        """Add a provider to the list of providers. Adds it in a unique way, where there is a check 
        that the provider that's being added is not already in the list.

        """
        if type_model is not None and type_model == "embedding":
            embedding_model = EmbeddingSpec(
                provider=provider,
                model_name=model_name,
                api_key=api_key,
                base_url=base_url,
                type=type_model,
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
    - OpenRouter: Uses OPEN_ROUTER_API_KEY and OPEN_ROUTER_MODEL (supports multiple providers)
    - Local/Self-hosted: Uses LOCAL_API_KEY, LOCAL_MODEL, and LOCAL_BASE_URL
    
    Configuration is loaded from ~/.cache/deadend/config.toml (preferred) or environment variables.
    The config.toml file is created/updated via the CLI's through the interactive LLM provider 
    selector in the chat interface.
    
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
    open_router_key: str | None = _cfg("OPEN_ROUTER_API_KEY")
    open_router_model: str | None = _cfg("OPEN_ROUTER_MODEL", "anthropic/claude-4.5-opus")
    local_model: str | None = _cfg("LOCAL_MODEL", "Kimi-K2-Thinking")
    local_api_key: str | None = _cfg("LOCAL_API_KEY")
    local_base_url: str | None = _cfg("LOCAL_BASE_URL")
    # Embedding model
    embedding_model: str | None  = _cfg("EMBEDDING_MODEL")

    # List providers
    providers: ProvidersList = ProvidersList()

    # Database
    db_url: str | None = _cfg("DB_URL")
    # Tools
    zap_api_key: str | None = _cfg("ZAP_PROXY_API_KEY")

    # # Application settings
    # app_env: str = _cfg("APP_ENV", "development") or "development"
    # log_level: str = _cfg("LOG_LEVEL", "INFO") or "INFO"

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
        """Populates the list of providers with all those found in the config.toml"""
        toml_providers = _CONFIG_SETTINGS.get("provider")
        for provider in [*toml_providers]:
            cls.providers.add_provider(
                **toml_providers[provider]
            )

    @classmethod
    def update_provider(
        cls,
        updated_provider: ModelSpec | EmbeddingSpec,
        provider: str,
        model_name: str,
        api_key: str | None,
        type_model: str | None,
        vec_dim: int | None
    ):
        """
        """
        new_provider = cls.providers.update_provider(updated_provider, provider, model_name, api_key, type_model, vec_dim)
        config_file = load_config_toml()
        config_file['provider'].update(new_provider.model_dump())
        try:
            with open(str(_CACHE_TOML_PATH), 'w', encoding='utf-8') as f:
                toml.dump(config_file, f)
        except OSError:
            logger.info("Config file update failed.")
    
    @classmethod
    def all_model_providers(cls) -> ProvidersList:
        """Returns the list of all providers"""
        return cls.providers

    @classmethod
    def get_model_from_provider(cls, provider_name: str) -> List[ModelSpec | EmbeddingSpec]:
        """Returns the """
        models_spec_found = []
        for provider in cls.providers.model_providers:
            if provider.provider == provider_name:
                models_spec_found.append(provider)
        return models_spec_found


    @classmethod
    def get_models_settings(cls) -> ModelSettings:
        """
        Get all the models settings that are configured
        """
        model_settings = ModelSettings()

        if cls.openai_api_key:
            model_settings.openai = ModelConfig(
                api_key=cls.openai_api_key,
                model_name=cls.openai_model_name if cls.openai_model_name else "gpt-4o"
            )
        if cls.anthropic_api_key:
            model_settings.anthropic = ModelConfig(
                api_key=cls.anthropic_api_key,
                model_name=cls.anthropic_model_name if cls.anthropic_model_name \
                    else "claude-3-5-sonnet-20241022"
            )
        if cls.gemini_api_key:
            model_settings.gemini = ModelConfig(
                api_key=cls.gemini_api_key,
                model_name=cls.gemini_model_name if cls.gemini_model_name else "gemini-2.5-flash",
            )
        if cls.open_router_key:
            model_settings.openrouter = ModelConfig(
                api_key=cls.open_router_key,
                model_name=cls.open_router_model
            )

        if cls.local_api_key:
            model_settings.local = ModelConfig(
                api_key=cls.local_api_key,
                model_name=cls.local_model,
                base_url=cls.local_base_url
            )
        return model_settings