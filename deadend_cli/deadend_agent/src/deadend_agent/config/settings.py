# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Configuration management system for the security research framework.

This module provides configuration loading, validation, and management
functionality, supporting both environment variables and TOML configuration
files with caching and validation capabilities.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
import toml

# Load cached CLI configuration first (if present), then environment variables
_CACHE_TOML_PATH = Path.home() / ".cache" / "deadend" / "config.toml"
_CACHE_CONFIG: dict[str, str] = {}

def _load_cache_toml() -> dict[str, str]:
    """Load cached configuration from TOML using the toml library."""
    if not _CACHE_TOML_PATH.exists():
        return {}
    try:
        return toml.load(_CACHE_TOML_PATH)
    except Exception:
        return {}

_CACHE_CONFIG = _load_cache_toml()

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


class Config:
    """
    Configuration class that loads environment variables from a .env file or from 
    environment variables 
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

    # Database
    db_url: str | None = _cfg("DB_URL")
    # Tools
    zap_api_key: str | None = _cfg("ZAP_PROXY_API_KEY")

    # Application settings
    app_env: str = _cfg("APP_ENV", "development") or "development"
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